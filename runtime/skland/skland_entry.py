import csv
import hashlib
import logging
import os

import skyland

ROOT = os.path.dirname(os.path.abspath(__file__))
csv_config_path = os.path.join(ROOT, "code", "accounts.csv")
LEGACY_FIELDS = ("account_id", "platform", "server", "name", "user_id", "credential", "stuid", "stoken", "mid", "games", "enabled", "remark")
FIELDS = ("account_id", "platform", "server", "name", "user_id", "credential", "stuid", "stoken", "mid", "games", "enabled", "remark", "device_manufacturer", "device_model", "device_code", "android_version", "android_sdk", "device_fingerprint", "app_install_id")
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
        header = tuple(reader.fieldnames or ())
        if header not in (LEGACY_FIELDS, FIELDS):
            raise ValueError("森空岛 accounts.csv 表头不匹配；拒绝执行")
        legacy_format = header == LEGACY_FIELDS
        accounts, ids, tokens, user_ids = [], set(), set(), set()
        for line, raw in enumerate(reader, start=2):
            row = {key: str(raw.get(key) or "").strip() for key in FIELDS}
            if legacy_format:
                for key in FIELDS[len(LEGACY_FIELDS):]:
                    row[key] = ""
            if not any(row.values()):
                continue
            token = row["credential"]
            games = sorted({part.strip() for part in row["games"].split("|") if part.strip()})
            if row["platform"] != "skland" or row["server"]:
                raise ValueError("森空岛 accounts.csv 第 %d 行平台或 server 字段错误" % line)
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


def load_accounts():
    if not os.path.isfile(csv_config_path):
        raise FileNotFoundError("缺少必需的 code/accounts.csv；森空岛函数仅支持 CSV 账号配置")
    return _read_csv_accounts()

def start(account):
    try:
        cred = skyland.get_cred_by_token(account["token"])
        success, messages = skyland.do_sign(cred, enabled_games=account["games"])
        for message in messages or []:
            game_name = "其他"
            if isinstance(message, str) and message.startswith("[") and "]" in message:
                game_name = message[1:message.index("]")]
            logging.info("[签到结果][%s][账号ID=%s][账号UUID=%s][账号=%s] %s",
                         game_name, account.get("platformUserId", ""),
                         account.get("account_id", ""), account.get("name", ""), message)
        if not success:
            raise RuntimeError("森空岛签到执行返回失败")
        return True, "\n".join(messages or [])
    except Exception as exc:
        logging.exception("森空岛账号 %s 执行失败", account.get("account_id", ""))
        return False, "签到失败：" + str(exc)


def handler(context=None):
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
