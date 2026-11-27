import copy
import csv
import os
import tempfile
import yaml

import config
import main

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "config", "accounts.csv")
FIELDS = ("account_id", "platform", "name", "user_id", "credential", "stuid", "stoken", "mid", "games", "enabled", "remark")
CN_GAMES = {"genshin", "honkai2", "honkai3rd", "tears_of_themis", "honkai_sr", "zzz"}
OS_GAMES = {"genshin", "honkai3rd", "tears_of_themis", "honkai_sr", "zzz"}


def _enabled(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on", "启用")


def load_accounts():
    if not os.path.isfile(CSV_PATH):
        return None
    if os.path.getsize(CSV_PATH) > 2 * 1024 * 1024:
        raise ValueError("HoYoLAB accounts.csv 超过 2 MB，已停止执行")
    with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if tuple(reader.fieldnames or ()) != FIELDS:
            raise ValueError("HoYoLAB accounts.csv 表头不匹配；拒绝执行")
        rows, ids, credentials, user_ids = [], set(), set(), set()
        for line, raw in enumerate(reader, start=2):
            row = {key: str(raw.get(key) or "").strip() for key in FIELDS}
            if not any(row.values()):
                continue
            platform = row["platform"]
            if platform not in ("hoyolab", "miyoushe_cn"):
                raise ValueError("accounts.csv 第 %d 行平台不属于 HoYoLAB 函数" % line)
            if not row["account_id"] or row["account_id"] in ids:
                raise ValueError("accounts.csv 第 %d 行账号 ID 为空或重复" % line)
            active = _enabled(row["enabled"])
            if (active and not row["credential"]) or "\n" in row["credential"] or "\r" in row["credential"]:
                raise ValueError("accounts.csv 第 %d 行启用账号凭据为空或包含换行" % line)
            if active and platform == "miyoushe_cn" and not all(row[k] for k in ("stuid", "stoken", "mid")):
                raise ValueError("accounts.csv 第 %d 行启用的国服账号缺少 stuid/stoken/mid" % line)
            games = {part.strip() for part in row["games"].split("|") if part.strip()}
            allowed = CN_GAMES if platform == "miyoushe_cn" else OS_GAMES
            if not games.issubset(allowed):
                raise ValueError("accounts.csv 第 %d 行游戏列表无效" % line)
            if row["credential"] and row["credential"] in credentials:
                raise ValueError("accounts.csv 存在重复凭据；拒绝重复执行同一账号")
            if row["user_id"] and (row["platform"], row["user_id"]) in user_ids:
                raise ValueError("accounts.csv 存在重复 user_id；拒绝重复执行同一账号")
            if any("\n" in row[key] or "\r" in row[key] for key in ("account_id", "name", "user_id", "remark")):
                raise ValueError("accounts.csv 第 %d 行包含非法换行字段" % line)
            ids.add(row["account_id"])
            if row["credential"]:
                credentials.add(row["credential"])
            if row["user_id"]:
                user_ids.add((row["platform"], row["user_id"]))
            row["games_set"] = games
            row["active"] = active
            rows.append(row)
            if len(rows) > 100:
                raise ValueError("HoYoLAB accounts.csv 超过 100 个账号")
    return rows


def _make_config(base, row):
    data = copy.deepcopy(base)
    data["enable"] = True
    data.setdefault("account", {}).update({"cookie": "", "stuid": "", "stoken": "", "mid": ""})
    data.setdefault("games", {})
    data.setdefault("mihoyobbs", {})
    data.setdefault("web_activity", {})
    if row["platform"] != "miyoushe_cn":
        data["mihoyobbs"]["enable"] = False
        data["web_activity"]["enable"] = False
    for region in ("cn", "os"):
        data["games"].setdefault(region, {})
        data.setdefault("cloud_games", {}).setdefault(region, {})["enable"] = False
    if row["platform"] == "miyoushe_cn":
        data["account"].update({
            "cookie": row["credential"], "stuid": row["stuid"],
            "stoken": row["stoken"], "mid": row["mid"]
        })
        data["games"]["cn"]["enable"] = True
        data["games"]["os"]["enable"] = False
        for key, value in data["games"]["cn"].items():
            if isinstance(value, dict) and "checkin" in value:
                value["checkin"] = key in row["games_set"]
    else:
        data["games"]["cn"]["enable"] = False
        data["games"]["os"]["enable"] = True
        data["games"]["os"]["cookie"] = row["credential"]
        for key, value in data["games"]["os"].items():
            if isinstance(value, dict) and "checkin" in value:
                value["checkin"] = key in row["games_set"]
    return data


def run_accounts():
    rows = load_accounts()
    if rows is None:
        # Old cloud packages remain usable until the APK migrates their legacy config.
        return main.main()
    active = [row for row in rows if row["active"]]
    if not active:
        raise RuntimeError("HoYoLAB accounts.csv 中没有启用的账号；未发送请求")
    with open(config.config_Path, "r", encoding="utf-8") as source:
        base = yaml.load(source, Loader=yaml.FullLoader)
    original_path = config.config_Path
    results, failures, captcha = [], 0, False
    try:
        for row in active:
            marker = "[账号上下文][account_id=%s][user_id=%s][name=%s]" % (
                row["account_id"], row["user_id"], row["name"] or row["account_id"])
            print(marker, flush=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as target:
                    yaml.dump(_make_config(base, row), target, Dumper=yaml.Dumper,
                              sort_keys=False, allow_unicode=True)
                    temp_path = target.name
                config.config_Path = temp_path
                status, message = main.main()
                if status in (1, 2):
                    failures += 1
                if status == 3:
                    captcha = True
                results.append((row, status, message or "任务执行完成，但没有返回消息"))
            except Exception as exc:
                failures += 1
                message = "签到失败：%s: %s" % (type(exc).__name__, exc)
                results.append((row, 1, message))
                print("[账号异常][account_id=%s] %s" % (row["account_id"], message), flush=True)
            finally:
                config.config_Path = original_path
                if temp_path:
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
    finally:
        config.config_Path = original_path
    output = []
    for row, status, message in results:
        output.extend((
            "[账号上下文][account_id=%s][user_id=%s][name=%s]" % (
                row["account_id"], row["user_id"], row["name"] or row["account_id"]),
            message,
            "[账号执行结束][account_id=%s][status=%s]" % (row["account_id"], status)
        ))
    overall = 1 if failures == len(results) else 2 if failures else 3 if captcha else 0
    return overall, "\n".join(output)
