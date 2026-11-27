"""Short-lived Cookie/token validity guard backed only by the platform's own LTS stream."""
import hashlib
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

WINDOW = timedelta(hours=48)
REPORT_PREFIX = "[COOKIE_STATUS_JSON]="


def fingerprint(credential, platform=None):
    value = str(credential or "").strip()
    if platform == "hoyolab":
        fields = []
        for segment in value.split(";"):
            segment = segment.strip()
            if "=" not in segment:
                continue
            key, field_value = segment.split("=", 1)
            key = key.strip()
            if key:
                fields.append((key, field_value.strip()))
        value = ";".join("%s=%s" % pair for pair in sorted(fields)) or value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _user_data(context, key):
    getter = getattr(context, "getUserData", None)
    if not callable(getter):
        return ""
    value = getter(key)
    return str(value or "").strip()


def _utc_now():
    return datetime.now(timezone.utc)


def _stamp(value=None):
    return (value or _utc_now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def report(platform, account_id, credential, status, reason=""):
    record = {
        "platform": str(platform),
        "account_id": str(account_id),
        "status": str(status).upper(),
        "timestamp": _stamp(),
        "sha256": fingerprint(credential, platform),
        "reason": str(reason)[:240],
    }
    print(REPORT_PREFIX + json.dumps(record, ensure_ascii=False, separators=(",", ":")), flush=True)
    return record


def _parse_report(content):
    text = str(content or "")
    pos = text.find(REPORT_PREFIX)
    if pos < 0:
        return None
    raw = text[pos + len(REPORT_PREFIX):].splitlines()[0].strip()
    try:
        item = json.loads(raw)
        if not isinstance(item, dict):
            return None
        return item
    except Exception:
        return None


def _query_recent_report(context, platform, account_id, credential):
    region = _user_data(context, "HUAWEI_CLOUD_REGION")
    group_id = _user_data(context, "LTS_LOG_GROUP_ID")
    stream_id = _user_data(context, "LTS_LOG_STREAM_ID")
    token_getter = getattr(context, "getToken", None)
    token = token_getter() if callable(token_getter) else ""
    if not all((region, group_id, stream_id, token)):
        raise RuntimeError("FunctionGraph user_data 或临时 IAM Token 不完整")
    if not re.fullmatch(r"[a-z0-9-]+", region):
        raise RuntimeError("华为云区域格式无效")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", group_id) or not re.fullmatch(r"[0-9a-fA-F-]{36}", stream_id):
        raise RuntimeError("LTS 日志组/流 ID 格式无效")
    now = _utc_now()
    start_ms = int((now - WINDOW).timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    project_id = _user_data(context, "HUAWEI_CLOUD_PROJECT_ID")
    if not project_id:
        raise RuntimeError("缺少 HUAWEI_CLOUD_PROJECT_ID")
    url = ("https://lts." + region + ".myhuaweicloud.com/v2/" +
           project_id + "/groups/" + group_id + "/streams/" +
           stream_id + "/content/query")
    body = {
        "start_time": str(start_ms),
        "end_time": str(end_ms),
        "keywords": fingerprint(credential, platform),
        "limit": 200,
        "is_desc": True,
        "search_type": "init",
        "is_count": True,
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"X-Auth-Token": str(token), "Content-Type": "application/json;charset=UTF-8",
                 "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    logs = payload.get("logs", []) if isinstance(payload, dict) else []
    if not isinstance(logs, list):
        raise RuntimeError("LTS 查询响应缺少 logs 列表")
    cutoff = now - WINDOW
    matches = []
    for entry in logs:
        if not isinstance(entry, dict):
            continue
        item = _parse_report(entry.get("content", ""))
        if not item:
            continue
        if (item.get("platform") != platform or
                str(item.get("account_id")) != str(account_id) or
                item.get("sha256") != fingerprint(credential, platform) or
                str(item.get("status", "")).upper() not in ("VALID", "INVALID")):
            continue
        try:
            stamp = datetime.fromisoformat(str(item.get("timestamp", "")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if cutoff <= stamp <= now + timedelta(minutes=5):
            matches.append((stamp, item))
    return max(matches, key=lambda pair: pair[0])[1] if matches else None


def should_skip(context, platform, account_id, credential):
    """Use the newest matching VALID/INVALID report; only a fresh INVALID report blocks."""
    try:
        previous = _query_recent_report(context, platform, account_id, credential)
    except Exception as exc:
        print("[COOKIE_GUARD][status=QUERY_UNAVAILABLE][platform={}] {}".format(
            platform, str(exc)[:240]), flush=True)
        return False
    if previous is None or str(previous.get("status", "")).upper() != "INVALID":
        return False
    report(platform, account_id, credential, "INVALID", "最新可信状态仍为失效；跳过外部请求")
    print("[COOKIE_GUARD][status=SKIPPED][platform={}][account_id={}] 最近48小时存在相同凭据失效报告".format(
        platform, account_id), flush=True)
    return True


def is_auth_failure(message):
    text = str(message or "").lower()
    exact_markers = ("http 401", "unauthorized", "invalid token",
                     "token expired", "token is expired", "token has expired",
                     "expired token", "请重新登录", "登录已过期", "登录状态失效",
                     "token无效", "token 无效", "令牌无效", "令牌失效", "凭据已过期")
    return any(marker in text for marker in exact_markers)
