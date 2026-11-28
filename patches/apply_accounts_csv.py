#!/usr/bin/env python3
"""Install strict CSV-only account runners into FunctionGraph packages."""
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1])
HOYO = ROOT / "hoyolab"
SKLAND = ROOT / "skland"
REPO = Path(__file__).resolve().parents[1]


def patch_hoyolab_config():
    target = HOYO / "config.py"
    source = target.read_text(encoding="utf-8")
    source = source.replace("import yaml\n", "")
    source = re.sub(
        r"^path = .*?\n(?:if os\.getenv\(\"AutoMihoyoBBS_config_path\"\).*?\n)?"
        r"config_prefix = .*?\n(?:if config_prefix is None:.*?\n    config_prefix = \"\"\n)?"
        r"config_Path = .*?\n",
        'path = os.path.dirname(os.path.realpath(__file__)) + "/config"\n'
        'config_Path = os.path.join(path, "accounts.csv")\n',
        source,
        count=1,
        flags=re.M | re.S,
    )
    start = source.index("def load_config(")
    end = source.index("def clear_stoken(", start)
    replacement = '''def load_config(data=None):
    """Load one already-validated CSV account configuration in memory."""
    global config
    if data is None:
        raise RuntimeError("HoYoLAB 仅支持 accounts.csv；必须由 CSV 账号执行器选择账号")
    config = deepcopy(data)
    log.info("CSV 账号配置加载完毕")
    return config


def save_config(p_path=None, p_config=None):
    """FunctionGraph accounts are immutable during a run; never write YAML."""
    if serverless:
        log.info("云函数执行，CSV 账号数据只读，不写回配置")
        return None
    log.warning("当前版本仅支持 CSV 账号配置，不提供 YAML 文件写入")
    return None


'''
    source = source[:start] + replacement + source[end:]
    if "import yaml" in source or "yaml.load" in source or "yaml.dump" in source:
        raise SystemExit("HoYoLAB config.py still contains YAML configuration support")
    target.write_text(source, encoding="utf-8")


def patch_hoyolab():
    patch_hoyolab_config()
    target = HOYO / "index.py"
    target.write_text('''import accounts_csv
import config
import push


def _emit_checkin_result_logs(message):
    """Forward per-game results to FunctionGraph/LTS with account context."""
    game_names = ("崩坏学园2", "崩坏3rd", "未定事件簿", "原神", "崩坏：星穹铁道", "绝区零")
    current_game = "其他"
    account_context = ""
    for raw_line in str(message or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[账号上下文]"):
            account_context = line.replace("[账号上下文]", "").strip()
            current_game = "其他"
            continue
        if line.startswith("[账号执行结束]"):
            continue
        empty_header = False
        for name in game_names:
            if line == name + "：" or line == name + ":":
                current_game = name
                empty_header = True
                break
            if line.startswith(name + "：") or line.startswith(name + ":"):
                current_game = name
                break
        if not empty_header:
            print("[签到结果][{}]{} {}".format(current_game, account_context, line), flush=True)


def main_handler(event: dict, context: dict):
    config.serverless = True
    try:
        status_code, push_message = accounts_csv.run_accounts(context=context)
    except Exception as exc:
        status_code = 1
        push_message = "CSV 账号配置或执行失败：%s: %s" % (type(exc).__name__, exc)
        print(push_message, flush=True)
    _emit_checkin_result_logs(push_message)
    push.push(status_code, push_message)
    print("HoYoLAB CSV 云函数执行完毕！", flush=True)
    return 0
''', encoding="utf-8")

    (HOYO / "accounts_csv.py").write_text(
        (REPO / "runtime" / "hoyolab" / "accounts_csv.py").read_text(encoding="utf-8"),
        encoding="utf-8"
    )
    for stale in (HOYO / "main_multi.py", HOYO / "config" / "config.yaml",
                  HOYO / "config" / "config.yaml.example"):
        stale.unlink(missing_ok=True)

    requirements = HOYO / "requirements.txt"
    if requirements.exists():
        lines = [line for line in requirements.read_text(encoding="utf-8").splitlines()
                 if not line.strip().lower().startswith("pyyaml")]
        requirements.write_text("\n".join(lines) + "\n", encoding="utf-8")

    stale_refs = []
    for path in HOYO.rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        if re.search(r"import yaml|yaml\.(?:load|dump)|config\.yaml|main_multi", content):
            stale_refs.append(str(path.relative_to(HOYO)))
    if stale_refs:
        raise SystemExit("Legacy YAML/multi-user code remains: " + ", ".join(stale_refs))


def patch_skland():
    skyland_file = SKLAND / "skyland.py"
    skyland_source = skyland_file.read_text(encoding="utf-8")
    skyland_source = skyland_source.replace(
        "            os.remove(token_save_name)",
        "            # Per-account credentials live in accounts.csv; never delete shared token storage."
    )
    skyland_file.write_text(skyland_source, encoding="utf-8")
    (SKLAND / "skland_entry.py").write_text(
        (REPO / "runtime" / "skland" / "skland_entry.py").read_text(encoding="utf-8"),
        encoding="utf-8"
    )


patch_hoyolab()
patch_skland()
print("CSV-only account runners installed; HoYoLAB YAML fallback and legacy multi-user entry removed.")
