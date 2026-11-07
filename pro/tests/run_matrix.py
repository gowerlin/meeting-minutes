"""跑 P1～P4、K7、R 需要的轉寫（全部輸出到 tests/_out/runs/，不進版控）。

- 用已安裝 runtime 的 venv 唯讀執行（-B、PYTHONDONTWRITEBYTECODE=1），MEETING_MINUTES_PRO_HOME 指向測試 home。
- v1.1.0：turbo、breeze 各跑預設（分段標點＋回復表開）；turbo 另跑 R 用的 --no-punct --no-opencc-keep --no-correct。
- 1.0.0：已安裝 runtime 的 scripts/transcribe.py（唯讀），同一音檔、同一測試 home。

用法：python run_matrix.py --home <測試 home> [--scripts <版本的 scripts 目錄>] [--v100 <1.0.0 scripts 目錄>] [M1 M2 ...]

預設的 scripts 目錄是 repo 裡的 meeting-minutes-pro-v1.1.0（研究用矩陣）。公開 repo 只有最新版目錄：
目錄不存在時印出原因後結束（exit 0，不算失敗）；要用其他版本就以 --scripts 指定。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
V110 = HERE.parent / "meeting-minutes-pro-v1.1.0" / "payload" / "runtime" / "scripts"
SPEAKERS = {"M1": 4, "M2": 3}


def run(script_dir: Path, wav: Path, out: Path, extra: list, home: str) -> dict:
    env = dict(os.environ, MEETING_MINUTES_PRO_HOME=home, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    cmd = [sys.executable, "-B", str(script_dir / "transcribe.py"), str(wav), "--out-dir", str(out)] + extra
    t0 = time.time()
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out.mkdir(parents=True, exist_ok=True)
    (out / "stderr.log").write_text(p.stderr, encoding="utf-8")
    last = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else "{}"
    print(f"  {out.name}: exit {p.returncode}, {time.time() - t0:.0f}s  {last[:160]}", flush=True)
    if p.returncode:
        print(p.stderr[-800:], flush=True)
    return json.loads(last) if last.startswith("{") else {}


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", required=True)
    ap.add_argument("--scripts", type=Path, default=V110, help="要跑的版本的 scripts 目錄（預設 meeting-minutes-pro-v1.1.0）")
    ap.add_argument("--v100", help="1.0.0 的 scripts 目錄（R 回歸）")
    ap.add_argument("names", nargs="*", default=["M1", "M2"])
    args = ap.parse_args()
    if not (args.scripts / "transcribe.py").is_file():
        print(f"略過：找不到 {args.scripts / 'transcribe.py'}（公開 repo 只有最新版目錄；用 --scripts 指定版本）", flush=True)
        return
    runs = HERE / "_out" / "runs"
    for n in args.names:
        wav = HERE / "_out" / f"{n}.wav"
        spk = ["--speakers", str(SPEAKERS.get(n, -1))]
        print(f"[{n}]", flush=True)
        run(args.scripts, wav, runs / f"{n}-turbo", spk, args.home)
        run(args.scripts, wav, runs / f"{n}-breeze", spk + ["--whisper", "breeze"], args.home)
        run(args.scripts, wav, runs / f"{n}-turbo-r110", spk + ["--no-punct", "--no-opencc-keep", "--no-correct"], args.home)
        if args.v100:
            run(Path(args.v100), wav, runs / f"{n}-turbo-v100", spk, args.home)


if __name__ == "__main__":
    main()
