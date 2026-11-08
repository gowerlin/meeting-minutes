"""會議記錄校稿的全部自動測試：單元、伺服器整合、安裝與移除（沙盒）、打包、瀏覽器（Playwright＋本機 Chrome／Edge）。

  python -B run_tests.py                 單元＋整合＋瀏覽器
  python -B run_tests.py --no-browser    不跑瀏覽器（沒有 Playwright 時）
  python -B run_tests.py --only install,dist   只跑指定的群組（unit、server、install、dist、browser）

需要：Python 3.10 以上（只用標準函式庫）、repo 內的 meeting-minutes-pro 版本目錄（唯讀，不留 __pycache__）；
安裝與移除測試在 Windows 另需 PowerShell 7（pwsh）、Windows PowerShell 5.1 與 Git Bash（缺的 shell 略過並列出）；
瀏覽器測試另需 Node.js、全域安裝的 playwright、本機 Chrome 與 Edge。結果寫到 tests/_out/results.json（不進版控）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def run_units():
    import test_units
    total, ok, bad = test_units.main()
    return {"group": "單元", "pass": ok, "total": total, "failed": bad}


def run_integration():
    import test_server
    r, perf, sec = test_server.main()
    return {"group": "整合", "pass": r.passed, "total": len(r.cases), "seconds": sec, "perf": perf, "cases": r.cases}


def run_install():
    import test_install
    total, ok, bad, skipped = test_install.main()
    return {"group": "安裝與移除", "pass": ok, "total": total, "failed": bad, "skipped": skipped}


def run_dist():
    import test_dist
    total, ok, bad = test_dist.main()
    return {"group": "打包", "pass": ok, "total": total, "failed": bad}


def run_browser():
    npm_root = subprocess.run("npm root -g", shell=True, capture_output=True, text=True).stdout.strip()
    env = dict(os.environ, NODE_PATH=npm_root, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run(["node", str(HERE / "browser_check.mjs")], env=env, text=True, encoding="utf-8")
    try:
        res = json.loads((HERE / "_out" / "browser.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"group": "瀏覽器", "pass": 0, "total": 1, "error": f"exit {p.returncode}"}
    return {"group": "瀏覽器", "pass": res["pass"], "total": res["total"], "perf": res["perf"], "requests": res["requests"],
            "external": res["external"], "csp": res["csp"], "cases": res["cases"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--only", help="只跑這些群組（逗號分隔）：unit、server、install、dist、browser")
    a = ap.parse_args()
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    t0 = time.time()
    runners = {"unit": run_units, "server": run_integration, "install": run_install, "dist": run_dist, "browser": run_browser}
    want = [x.strip() for x in a.only.split(",")] if a.only else [k for k in runners if not (k == "browser" and a.no_browser)]
    groups = [runners[k]() for k in want]
    ok = sum(g["pass"] for g in groups)
    total = sum(g["total"] for g in groups)
    out = HERE / "_out"
    out.mkdir(exist_ok=True)
    summary = {"python": sys.version.split()[0], "platform": sys.platform, "seconds": round(time.time() - t0, 1),
               "pass": ok, "total": total, "groups": groups}
    (out / "results.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print("\n" + "；".join(f"{g['group']} {g['pass']}/{g['total']}" for g in groups) + f"；合計 {ok}/{total} PASS")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
