import csv
import hashlib
import json
import logging
import os

import skyland

ROOT = os.path.dirname(os.path.abspath(__file__))
file_save_token = os.path.join(ROOT, "code", "INPUT_HYPERGRYPH_TOKEN.txt")
account_config_path = os.path.join(ROOT, "code", "INPUT_HYPERGRYPH_ACCOUNTS.json")
csv_config_path = os.path.join(ROOT, "code", "accounts.csv")
FIELDS = ("account_id", "platform", "name", "user_id", "credential", "stuid", "stoken", "mid", "games", "enabled", "remark")
SUPPORTED_GAMES = {"arknights", "endfield"}
logging.getLogger().setLevel(logging.INFO)


def _stable_id(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _enabled(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "启用")


def _read_csv_accounts():
    if os.path.getsize(csv_config_path) > 2 * 1024 * 1024:
        raise ValueError("森空岛 accounts.csv 超过 2 MB")
    with open(csv_config_path, "r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("森空岛 accounts.csv 表头不匹配；拒绝执行")
        accounts, ids, tokens, user_ids = [], set(), set(), set()
        for line, raw in enumerate(reader, start=2):
            row = {key: str(raw.get(key) or "").strip() for key in FIELDS}
            if not any(row.values()):
                continue
            token = row["credential"]
            games = sorted({part.strip() for part in row["games"].split("|") if part.strip()})
            if row["platform"] != "skland":
                raise ValueError("森空岛 accounts.csv 第 %d 行平台错误" % line)
            if not row["account_id"] or row["account_id"] in ids:
                raise ValueError("森空岛 accounts.csv 第 %d 行账号 ID 为空或重复" % line)
            active = _enabled(row["enabled"])
            if (active and not token) or any(ch.isspace() for ch in token):
                raise ValueError("森空岛 accounts.csv 第 %d 行启用账号 Token 无效" % line)
            if not set(games).issubset(SUPPORTED_GAMES):
                raise ValueError("森空岛 accounts.csv 第 %d 行游戏列表无效" % line)
            if token and token in tokens:
                raise ValueError("森空岛 accounts.csv 存在重复 Token")
            if row["user_id"] and row["user_id"] in user_ids:
                raise ValueError("森空岛 accounts.csv 存在重复 user_id")
            if any("\n" in row[key] or "\r" in row[key] for key in ("account_id", "name", "user_id", "remark")):
                raise ValueError("森空岛 accounts.csv 第 %d 行包含非法换行字段" % line)
            ids.add(row["account_id"])
            if token:
                tokens.add(token)
            if row["user_id"]:
                user_ids.add(row["user_id"])
            accounts.append({
                "account_id": row["account_id"],
                "platformUserId": row["user_id"] or _stable_id(token),
                "name": row["name"], "token": token, "games": games,
                "enabled": _enabled(row["enabled"])
            })
            if len(accounts) > 100:
                raise ValueError("森空岛 accounts.csv 超过 100 个账号")
    return accounts


def _read_legacy_tokens():
    if not os.path.exists(file_save_token):
        return []
    result = []
    with open(file_save_token, "r", encoding="utf-8") as source:
        for raw in source:
            token = raw.strip()
            if token and not token.startswith("#") and token not in result:
                result.append(token)
    return result


def _load_legacy_accounts():
    if os.path.exists(account_config_path):
        with open(account_config_path, "r", encoding="utf-8") as source:
            raw = source.read().strip()
        if raw:
            document = json.loads(raw)
            if document.get("version") != 1 or not isinstance(document.get("accounts"), list):
                raise ValueError("森空岛旧账号配置格式不受支持")
            accounts = []
            for item in document["accounts"]:
                token = str(item.get("token") or "").strip()
                games = sorted(set(item.get("games") or []))
                if not token or not games or not set(games).issubset(SUPPORTED_GAMES):
                    raise ValueError("森空岛旧账号配置包含无效条目")
                accounts.append({
                    "account_id": _stable_id(token),
                    "platformUserId": str(item.get("platformUserId") or _stable_id(token)),
                    "name": "", "token": token, "games": games, "enabled": True
                })
            return accounts
    return [{
        "account_id": _stable_id(token), "platformUserId": _stable_id(token),
        "name": "", "token": token, "games": sorted(SUPPORTED_GAMES), "enabled": True
    } for token in _read_legacy_tokens()]


def load_accounts():
    if os.path.isfile(csv_config_path):
        return _read_csv_accounts()
    return _load_legacy_accounts()


def start(account):
    try:
        cred = skyland.get_cred_by_token(account["token"])
        success, messages = skyland.do_sign(cred, enabled_games=account["games"])
        for message in messages or []:
            game_name = "其他"
            if isinstance(message, str) and message.startswith("[") and "]" in message:
                game_name = message[1:message.index("]")]
            logging.info("[签到结果][%s][账号ID=%s][账号=%s] %s",
                         game_name, account.get("platformUserId", ""),
                         account.get("name", ""), message)
        if not success:
            raise RuntimeError("森空岛签到执行返回失败")
        return True, "\n".join(messages or [])
    except Exception as exc:
        logging.exception("森空岛账号 %s 执行失败", account.get("account_id", ""))
        return False, "签到失败：" + str(exc)


def handler():
    accounts = load_accounts()
    active = [account for account in accounts if account.get("enabled", True)]
    if not active:
        print("森空岛 accounts.csv 中没有启用的账号，未发送任何请求。", flush=True)
        return
    failures = 0
    for account in active:
        print("[账号上下文][account_id=%s][user_id=%s][name=%s]" % (
            account.get("account_id", ""), account.get("platformUserId", ""),
            account.get("name", "")), flush=True)
        if not account["games"]:
            print("[账号执行结束][account_id=%s][status=skipped] 未选择任何签到游戏，未发送请求。" % account.get("account_id", ""), flush=True)
            continue
        success, message = start(account)
        if not success:
            failures += 1
        print("[账号执行结束][account_id=%s][status=%s] %s" % (
            account.get("account_id", ""), "success" if success else "failed", message), flush=True)
    if failures == len(active):
        raise RuntimeError("所有森空岛账号均执行失败")
