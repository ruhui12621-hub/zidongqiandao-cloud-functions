#!/usr/bin/env python3
"""Build-time HoYoLAB request hardening overlay."""
import ast
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(sys.argv[1])


def replace_function(path, name, replacement):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
    if len(nodes) != 1:
        raise SystemExit(f"Expected one {name} in {path}, found {len(nodes)}")
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    repl = replacement.rstrip() + "\n\n"
    if node.col_offset:
        repl = textwrap.indent(repl, " " * node.col_offset)
    lines[node.lineno - 1:node.end_lineno] = [repl]
    path.write_text("".join(lines), encoding="utf-8")


(ROOT / "hoyo_checkin.py").write_text(r'''import hashlib
import os
import setting
import config
from request import get_new_session
from loghelper import log

RET_CODE_ALREADY_SIGNED_IN = -5003
COOKIE_INVALID_ENV = "HOYOLAB_OS_COOKIE_INVALID_SHA256"

class HoyoCookieExpired(Exception):
    pass

class HoyoApiError(Exception):
    pass

def cookie_fingerprint(cookie: str) -> str:
    return hashlib.sha256((cookie or "").strip().encode("utf-8")).hexdigest()

def _response_json(response, endpoint: str, allow_already_signed: bool = False) -> dict:
    status = int(getattr(response, "status_code", 0) or 0)
    if status == 401:
        raise HoyoCookieExpired(f"{endpoint} HTTP 401")
    if status == 429:
        raise HoyoApiError(f"{endpoint} HTTP 429；停止后续请求，不重试")
    if status < 200 or status >= 300:
        raise HoyoApiError(f"{endpoint} HTTP {status}；停止后续请求")
    try:
        payload = response.json()
    except Exception as exc:
        raise HoyoApiError(f"{endpoint} 响应无法解析：{exc}") from exc
    if not isinstance(payload, dict) or "retcode" not in payload:
        raise HoyoApiError(f"{endpoint} 响应缺少有效 retcode")
    try:
        retcode = int(payload["retcode"])
    except (TypeError, ValueError):
        raise HoyoApiError(f"{endpoint} retcode 无效")
    if retcode == -100:
        raise HoyoCookieExpired(f"{endpoint} retcode=-100")
    if allow_already_signed and retcode == RET_CODE_ALREADY_SIGNED_IN:
        return payload
    if retcode != 0:
        message = str(payload.get("message") or payload.get("msg") or "未知错误")
        raise HoyoApiError(f"{endpoint} retcode={retcode}：{message}")
    return payload

def hoyo_checkin(event_base_url: str, act_id: str) -> str:
    """只查询一次状态；已签到时不再请求奖励和签到接口。"""
    os_lang = config.config["games"]["os"].get("lang", "zh-cn")
    reward_url = f"{event_base_url}/home?lang={os_lang}&act_id={act_id}"
    info_url = f"{event_base_url}/info?lang={os_lang}&act_id={act_id}"
    sign_url = f"{event_base_url}/sign?lang={os_lang}"
    cookie = str(config.config.get("games", {}).get("os", {}).get("cookie", "")).strip()
    if not cookie or cookie == "CookieError":
        raise HoyoCookieExpired("Cookie 为空或已作废")
    http = get_new_session()
    headers = {"Referer": setting.os_referer_url, "Accept-Encoding": "gzip, deflate, br", "Cookie": cookie}
    if act_id == setting.os_zzz_act_id:
        headers["x-rpc-signgame"] = "zzz"

    info = _response_json(http.get(info_url, headers=headers), "签到状态查询")
    data = info.get("data")
    if not isinstance(data, dict):
        raise HoyoApiError("签到状态响应缺少 data")
    if data.get("is_sign") in (True, 1, "1"):
        log.info("今天已经签到过；只发送一次状态查询")
        return "今天已经签到过"
    if data.get("first_bind"):
        return "请手动签到一次"
    total_days = data.get("total_sign_day")
    if not isinstance(total_days, int) or total_days < 0:
        raise HoyoApiError("签到状态 total_sign_day 无效")

    rewards = _response_json(http.get(reward_url, headers=headers), "签到奖励查询")
    reward_data = rewards.get("data")
    awards = reward_data.get("awards") if isinstance(reward_data, dict) else None
    if not isinstance(awards, list) or not awards:
        raise HoyoApiError("奖励列表无效；已阻止签到 POST")

    # 只提交一次；超时后不盲目重放，避免重复签到请求。
    result = _response_json(http.post(sign_url, headers=headers, json={"act_id": act_id}),
                             "签到提交", allow_already_signed=True)
    if int(result.get("retcode", 0)) == RET_CODE_ALREADY_SIGNED_IN:
        return "今天已经签到过"
    reward_index = max(total_days - 1, 0)
    if reward_index >= len(awards) or not isinstance(awards[reward_index], dict):
        return "签到成功（奖励详情暂不可用）"
    reward = awards[reward_index]
    return f"今天获得的奖励：{reward.get('cnt', 0)}x「{reward.get('name', '奖励')}」"

def genshin():
    return "原神：\n" + hoyo_checkin("https://sg-hk4e-api.hoyolab.com/event/sol", setting.os_genshin_act_id)

def honkai_sr():
    return "崩坏：星穹铁道：\n" + hoyo_checkin("https://sg-public-api.hoyolab.com/event/luna/os", setting.os_honkai_sr_act_id)

def honkai3rd():
    return "崩坏3：\n" + hoyo_checkin("https://sg-public-api.hoyolab.com/event/mani", setting.os_honkai3rd_act_id)

def tears_of_themis():
    return "未定事件簿：\n" + hoyo_checkin("https://sg-public-api.hoyolab.com/event/luna/os", setting.os_tearsofthemis_act_id)

def zzz():
    return "绝区零：\n" + hoyo_checkin("https://sg-act-nap-api.hoyolab.com/event/luna/zzz/os", setting.os_zzz_act_id)

def _invalidate_cookie(cookie: str, reason: str) -> str:
    fingerprint = cookie_fingerprint(cookie)
    os_config = config.config.get("games", {}).get("os", {})
    os_config["cookie"] = "CookieError"
    os_config["enable"] = False
    # Also block a warm FunctionGraph worker immediately; user_data persists across cold starts.
    os.environ[COOKIE_INVALID_ENV] = fingerprint
    message = f"[COOKIE_INVALID][sha256={fingerprint}] HoYoLAB Cookie 已确认失效：{reason}"
    log.error(message)
    print(message, flush=True)
    return "Cookie 已确认过期；本次所有国际服游戏请求已停止，请重新登录并部署新 Cookie。"

def run_task():
    games = config.config.get("games", {}).get("os", {})
    cookie = str(games.get("cookie", "")).strip()
    if not cookie or cookie == "CookieError":
        log.warning("国际服 Cookie 为空或已作废；未发送请求")
        return "国际服 Cookie 不可用，已跳过"
    fingerprint = cookie_fingerprint(cookie)
    blocked = os.getenv(COOKIE_INVALID_ENV, "").strip().lower()
    if blocked and blocked == fingerprint:
        games["cookie"] = "CookieError"
        games["enable"] = False
        log.error(f"[COOKIE_INVALID_BLOCKED][sha256={fingerprint}] Cookie 已永久标记作废；未发送请求")
        return "当前 Cookie 已被永久标记作废，未向 HoYoLAB 发送请求"
    if not games.get("enable", False):
        return "国际服签到未启用"
    enabled = [(name, value) for name, value in games.items()
               if isinstance(value, dict) and value.get("checkin", False)]
    if not enabled:
        return "没有启用的国际服游戏签到项目"
    funcs = {"genshin": genshin, "honkai_sr": honkai_sr, "honkai3rd": honkai3rd,
             "tears_of_themis": tears_of_themis, "zzz": zzz}
    results = []
    for name, _ in enabled:
        func = funcs.get(name)
        if func is None:
            continue
        try:
            results.append(func())
        except HoyoCookieExpired as exc:
            results.append(_invalidate_cookie(cookie, str(exc)))
            break
        except HoyoApiError as exc:
            log.error(f"HoYoLAB 请求异常，停止本次剩余游戏：{exc}")
            results.append(f"请求异常，已停止后续游戏请求且不重试：{exc}")
            break
        except Exception as exc:
            log.exception(f"HoYoLAB 网络/程序异常，停止本次剩余游戏：{exc}")
            results.append(f"网络/程序异常，未自动重试：{exc}")
            break
    return "\n\n".join(results)
''', encoding="utf-8")

# Disable hidden transport retries that can replay a failed authenticated request.
p = ROOT / "request.py"
s = p.read_text(encoding="utf-8").replace("httpx.HTTPTransport(retries=10)", "httpx.HTTPTransport(retries=0)").replace("HTTPAdapter(max_retries=10)", "HTTPAdapter(max_retries=0)")
if "retries=10" in s or "max_retries=10" in s:
    raise SystemExit("Transport retry guard failed")
p.write_text(s, encoding="utf-8")

replace_function(ROOT / "main.py", "handle_login", r'''def handle_login() -> None:
    """Only prepare BBS credentials when an enabled task actually needs them."""
    account = config.config["account"]
    needs_bbs = bool(config.config.get("mihoyobbs", {}).get("enable", False))
    needs_cn = bool(config.config.get("games", {}).get("cn", {}).get("enable", False))
    needs_web = bool(config.config.get("web_activity", {}).get("enable", False))
    if not (needs_bbs or needs_cn or needs_web):
        log.info("当前只运行国际服/云游戏任务，跳过米游社登录与 Token 补齐")
        return
    if any(account.get(k, "") == "" for k in ("stuid", "stoken", "mid")):
        if needs_bbs:
            login.login()
            time.sleep(random.randint(3, 8))
        account["cookie"] = tools.tidy_cookie(account.get("cookie", ""))
    if account.get("stoken") and account.get("stoken") != "StokenError" and account.get("mid"):
        if config.serverless:
            fields = login.parse_cookie(account.get("cookie", ""))
            if not (fields.get("ltoken_v2") or fields.get("ltoken")) or not (fields.get("cookie_token_v2") or fields.get("cookie_token")):
                log.warning("BBS Cookie 缺少 Token；云函数不自动换票，避免每次定时运行重复登录请求。本次跳过 BBS/国服/网页活动任务")
                config.config["mihoyobbs"]["enable"] = False
                config.config["games"]["cn"]["enable"] = False
                config.config["web_activity"]["enable"] = False
                return
        account["cookie"] = login.build_account_cookie()''')

replace_function(ROOT / "account.py", "get_account_list", r'''def get_account_list(game_id: str, headers: dict, update: bool = False) -> list:
    """Refresh CookieToken at most once, and only after explicit retcode -100."""
    http = get_new_session()
    game_name = setting.game_id2name.get(game_id, game_id)
    log.info(f"正在获取米哈游账号绑定的「{game_name}」账号列表...")
    data = http.get(setting.account_Info_url, params={"game_biz": game_id}, headers=headers).json()
    if not isinstance(data, dict):
        raise CookieError("BBS 账号列表响应格式异常")
    if data.get("retcode") == -100:
        if update:
            config.config["account"]["cookie"] = "CookieError"
            raise CookieError("BBS Cookie 在一次刷新后仍然失效")
        if not login.update_cookie_token():
            config.config["account"]["cookie"] = "CookieError"
            raise CookieError("BBS Cookie 失效且无法刷新")
        headers["Cookie"] = config.config["account"]["cookie"]
        return get_account_list(game_id, headers, update=True)
    if data.get("retcode") != 0:
        log.warning(f"获取「{game_name}」账号列表失败（retcode={data.get('retcode')}），不刷新 Token")
        return []
    return [[item["nickname"], item["game_uid"], item["region"]] for item in (data.get("data") or {}).get("list", [])]''')

replace_function(ROOT / "index.py", "main_handler", r'''def main_handler(event: dict, context: dict):
    config.serverless = True
    try:
        status_code, push_message = main.main()
    except CookieError as exc:
        status_code, push_message = 1, f"账号 Cookie 不可用：{exc}"
        print(f"[凭据错误] {push_message}", flush=True)
    except Exception as exc:
        status_code, push_message = 1, f"云函数执行异常，已停止后续请求：{type(exc).__name__}: {exc}"
        print(f"[执行错误] {push_message}", flush=True)
    _emit_checkin_result_logs(push_message)
    push.push(status_code, push_message)
    print("云函数测试支持！")
    return 0''')

# Guard CN/BBS paths too: auth refresh is allowed only once and only for explicit -100.
replace_function(ROOT / "gamecheckin.py", "get_checkin_rewards", r'''def get_checkin_rewards(self) -> list:
        log.info("正在获取签到奖励列表...")
        req = self.http.get(self.rewards_api, params={"act_id": self.act_id}, headers=self.headers)
        if req.status_code == 401:
            config.config["account"]["cookie"] = "CookieError"
            raise CookieError("BBS Cookie HTTP 401")
        if req.status_code == 429:
            raise RuntimeError("签到奖励查询触发 HTTP 429，停止且不重试")
        data = req.json()
        if data.get("retcode") == -100:
            config.config["account"]["cookie"] = "CookieError"
            raise CookieError("BBS Cookie 已失效")
        if data.get("retcode") != 0:
            raise RuntimeError(f"签到奖励查询失败（retcode={data.get('retcode')}），不重试")
        return data["data"]["awards"]''')

replace_function(ROOT / "gamecheckin.py", "is_sign", r'''def is_sign(self, region: str, uid: str, update: bool = False) -> dict:
        req = self.http.get(self.is_sign_api, params={"act_id": self.act_id, "region": region, "uid": uid},
                            headers=self.headers)
        data = {"retcode": -100} if req.status_code == 401 else req.json()
        if data.get("retcode") == -100:
            if not update and login.update_cookie_token():
                self.set_headers()
                return self.is_sign(region, uid, True)
            config.config["account"]["cookie"] = "CookieError"
            raise CookieError("BBS Cookie 在最多一次刷新后仍然失效")
        if data.get("retcode") != 0:
            raise RuntimeError(f"签到状态查询失败（retcode={data.get('retcode')}），不尝试刷新登录")
        return data["data"]''')

# A 429 must not be retried as if it were a CAPTCHA challenge.
game_path = ROOT / "gamecheckin.py"
game_source = game_path.read_text(encoding="utf-8")
game_source = game_source.replace(
    "            if result.status_code == 429:\n                time.sleep(10)  # 429同ip请求次数过多，尝试sleep10s进行解决\n                log.warning('429 Too Many Requests，即将进入下一次请求')\n                continue",
    "            if result.status_code == 429:\n                log.warning('429 Too Many Requests，停止本次签到请求，不自动重试')\n                break",
    1,
)
game_path.write_text(game_source, encoding="utf-8")

# The BBS task-list path refreshes only on explicit auth rejection, never on arbitrary error text.
bbs_path = ROOT / "mihoyobbs.py"
bbs_source = bbs_path.read_text(encoding="utf-8")
old = '        data = req.json()\n        if "err" in data["message"] or data["retcode"] == -100:\n'
new = '        data = req.json()\n        if data.get("retcode") not in (0, -100):\n            raise RuntimeError("米游社任务列表失败（retcode={}），不刷新登录凭据".format(data.get("retcode")))\n        if data.get("retcode") == -100:\n'
if old not in bbs_source:
    raise SystemExit("BBS task-list auth condition not found")
bbs_source = bbs_source.replace(old, new, 1)
bbs_source = bbs_source.replace(
    "                config.clear_cookie()\n                raise StokenError('Cookie expires')",
    '                config.config["account"]["cookie"] = "CookieError"\n                raise StokenError("Cookie expires")',
    1,
)
bbs_source = bbs_source.replace(
    "                    config.clear_stoken()\n                    raise StokenError('Stoken expires')",
    '                    config.config["account"]["stoken"] = "StokenError"\n                    raise StokenError("Stoken expires")',
    1,
)
bbs_path.write_text(bbs_source, encoding="utf-8")

for name in ("hoyo_checkin.py", "request.py", "main.py", "account.py", "index.py"):
    ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)
assert "HTTPTransport(retries=0)" in (ROOT / "request.py").read_text(encoding="utf-8")
assert "COOKIE_INVALID_BLOCKED" in (ROOT / "hoyo_checkin.py").read_text(encoding="utf-8")
print("HoYoLAB hardening overlay applied and syntax-checked.")
