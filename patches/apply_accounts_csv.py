#!/usr/bin/env python3
"""Install the shared CSV account runners into already-built FunctionGraph ZIP contents."""
from pathlib import Path
import sys

ROOT = Path(sys.argv[1])
HOYO = ROOT / "hoyolab"
SKLAND = ROOT / "skland"
REPO = Path(__file__).resolve().parents[1]


def patch_hoyolab():
    target = HOYO / "index.py"
    source = target.read_text(encoding="utf-8")
    if "import accounts_csv" not in source:
        source = source.replace("import main\n", "import main\nimport accounts_csv\n", 1)
    if "status_code, push_message = accounts_csv.run_accounts()" not in source:
        if "status_code, push_message = main.main()" not in source:
            raise SystemExit("HoYoLAB main_handler call not found; refusing to patch")
        source = source.replace("status_code, push_message = main.main()",
                                "status_code, push_message = accounts_csv.run_accounts()", 1)
    start = source.index("def _emit_checkin_result_logs(message):")
    end = source.index("\n\ndef main_handler(", start)
    logger = '''def _emit_checkin_result_logs(message):
    """Forward game results with stable account context to FunctionGraph/LTS."""
    game_names = ("崩坏学园2", "崩坏3rd", "未定事件簿", "原神", "崩坏：星穹铁道", "绝区零")
    current_game = "其他"
    account_context = ""
    for raw_line in str(message or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[账号上下文]"):
            account_context = line.replace("[账号上下文]", "").strip()
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
        if empty_header:
            continue
        print("[签到结果][{}]{} {}".format(current_game, account_context, line), flush=True)
'''
    source = source[:start] + logger + source[end:]
    target.write_text(source, encoding="utf-8")
    (HOYO / "accounts_csv.py").write_text(
        (REPO / "runtime" / "hoyolab" / "accounts_csv.py").read_text(encoding="utf-8"),
        encoding="utf-8"
    )


def patch_skland():
    (SKLAND / "skland_entry.py").write_text(
        (REPO / "runtime" / "skland" / "skland_entry.py").read_text(encoding="utf-8"),
        encoding="utf-8"
    )


patch_hoyolab()
patch_skland()
print("CSV account runners installed.")
