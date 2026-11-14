"""〔2.5.0〕Breeze-ASR-26 的雜訊幻聽處置量測：faster-whisper vad_filter 開與關（規格 2.5.0 §6）。

產品 2.5.0 的 transcribe.py 整條路徑（--whisper breeze26、--type meeting、--local-only、--no-keyframes；
測試 home 的 config：說話者分離 sherpa、不校正）跑兩條路徑 × 兩種設定：
  diar ＝有說話者分離（只把有人聲的段落送進 ASR）
  skip ＝略過說話者分離（--no-diarize：整檔切 28 秒窗）
  vad0 ＝vad_filter 關（2.4.1 的行為）　vad1 ＝vad_filter 開
vad 開關的方法：子行程先改 common.ASR_VAD_FILTER 再 import transcribe（產品程式不改、不加測試用旗標）。
素材：SIL（40 秒數位靜音）、NOISE（40 秒白雜訊）、M1、M2、M3、CV、EY、MX（研究素材，見 research/breeze-asr/README.md；
音檔與輸出都在 tests/_out/，不進版控）。
計分（沿用 research/breeze-asr/score.py 的算法，唯讀 import）：CER（windowed_cer；25 分鐘以下整份一次對齊，M3 每約 10 分鐘一窗；
EY 也整份對齊，不逐則切窗）、數字寫法不計的 CER、
整段漏掉（blank_paras：基準段落 10 字以上、時間範圍內完全沒有輸出）、漏句（omitted：每個對齊窗內把基準與輸出整串用
difflib 對齊，基準段落 10 字以上、70% 以上的字落在「刪除」區段＝整句漏掉；略過分離時輸出是 28 秒窗，blank_paras 看不到窗內漏句）、
SIL／NOISE 有文字的輸出段數。

用法（真實 runtime 的 venv 唯讀執行：python -B、PYTHONDONTWRITEBYTECODE=1；MEETING_MINUTES_PRO_HOME＝測試 home）：
  python -B eval_breeze26_vad.py run [--only SIL,NOISE] [--paths diar,skip] [--vads 0,1]
  python -B eval_breeze26_vad.py score            # → _out/breeze26-vad/summary.json 與表格（印在畫面）
不呼叫任何雲端模型。量測前先看 nvidia-smi 有沒有其他計算行程（run 會記在 _out/breeze26-vad/gpu-before.txt）。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402,F401  版本目錄的 scripts 放上 sys.path；防呆：不得寫入真實安裝

SKILL = HERE.parent
RESEARCH = SKILL / "research" / "breeze-asr"
OUT = HERE / "_out" / "breeze26-vad"
SRC = HERE / "_out" / "breeze-asr"
MATS = ["SIL", "NOISE", "MX", "CV", "EY", "M1", "M2", "M3"]
PATHS = {"diar": [], "skip": ["--no-diarize"]}
WRAP = r"""
import sys
sys.path.insert(0, sys.argv[1])
import common
common.ASR_VAD_FILTER = {("breeze26", "ct2")} if sys.argv[2] == "1" else set()
import transcribe
sys.argv = ["transcribe.py"] + sys.argv[3:]
transcribe.main()
"""


def wav_of(name: str) -> Path:
    return (HERE / "_out" / f"{name}.wav") if name in ("M1", "M2", "M3") else (SRC / f"{name}.wav")


def home() -> Path:
    h = os.environ.get("MEETING_MINUTES_PRO_HOME")
    real = _testenv.real_home()
    if not h or Path(h).resolve() == real.resolve():
        sys.exit("請把 MEETING_MINUTES_PRO_HOME 設成測試 home（不要指向真實安裝）")
    return Path(h)


def run(argv):
    home()
    only = argv[argv.index("--only") + 1].split(",") if "--only" in argv else MATS
    paths = argv[argv.index("--paths") + 1].split(",") if "--paths" in argv else list(PATHS)
    vads = argv[argv.index("--vads") + 1].split(",") if "--vads" in argv else ["0", "1"]
    OUT.mkdir(parents=True, exist_ok=True)
    smi = subprocess.run(["nvidia-smi"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    (OUT / "gpu-before.txt").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z") + "\n" + smi, encoding="utf-8")
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    for name in only:
        for p in paths:
            for v in vads:
                d = OUT / f"{p}-vad{v}" / name
                if (d / "transcript.json").exists():
                    print(f"略過（已有）：{d}", flush=True)
                    continue
                d.mkdir(parents=True, exist_ok=True)
                cmd = [sys.executable, "-B", "-c", WRAP, str(_testenv.SCRIPTS), v, str(wav_of(name)), "--out-dir", str(d),
                       "--whisper", "breeze26", "--type", "meeting", "--local-only", "--no-keyframes", *PATHS[p]]
                t0 = time.time()
                r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
                (d / "console.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
                print(f"{p}-vad{v} {name}: exit {r.returncode}，{time.time() - t0:.0f}s", flush=True)


def omitted(sc, norm, ref, segs) -> int:
    """逐句漏掉的數量：與 windowed_cer 相同的切窗，窗內基準段落接起來與輸出接起來對齊，段落 70% 以上的字被刪 → 漏句。"""
    import difflib
    cuts, last = [0.0], 0.0
    for p in ref["paragraphs"]:
        if ref["duration"] > 1500 and p["start"] - last >= 600:
            cuts.append(p["start"])
            last = p["start"]
    cuts.append(float("inf"))
    n = 0
    for a, b in zip(cuts, cuts[1:]):
        paras = [norm(p["text"]) for p in ref["paragraphs"] if a <= p["start"] < b]
        rc = "".join(paras)
        hc = "".join(norm(s["text"]) for s in segs if a - 1 <= s["start"] < b - 1)
        deleted = [False] * len(rc)
        for op, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, rc, hc, autojunk=False).get_opcodes():
            if op == "delete":
                for i in range(i1, i2):
                    deleted[i] = True
        pos = 0
        for t in paras:
            if len(t) >= 10 and sum(deleted[pos:pos + len(t)]) >= 0.7 * len(t):
                n += 1
            pos += len(t)
    return n


def score(argv):
    sys.path.insert(0, str(RESEARCH))
    import score as sc   # research/breeze-asr/score.py（唯讀 import；只用計分函式）
    from bz_common import norm
    res = {}
    for d in sorted(OUT.glob("*-vad*")):
        for name in MATS:
            f = d / name / "transcript.json"
            if not f.exists():
                continue
            doc = json.loads(f.read_text(encoding="utf-8"))
            segs = doc["segments"]
            r = {"segments": len(segs), "with_text": sum(1 for s in segs if norm(s["text"])),
                 "vad_filter": doc["meta"].get("vad_filter", False), "elapsed_sec": doc["meta"]["elapsed_sec"]}
            if name in ("SIL", "NOISE"):
                r["texts"] = [s["text"] for s in segs if norm(s["text"])]
            else:
                ref = sc.refs(name)
                # EY 一律整份一次對齊（12.6 分鐘，不到 25 分鐘）：略過分離時 28 秒窗會跨好幾則廣告，逐則切窗會錯位
                r["cer"] = sc.windowed_cer(ref, segs)
                r["cer_nonum"] = sc.windowed_cer(ref, segs, f=sc.nonum)
                r["blank_paras"] = sc.blank_paras(ref, segs)
                r["omitted"] = omitted(sc, norm, ref, segs)
                r["ref_paras"] = sum(1 for p in ref["paragraphs"] if len(norm(p["text"])) >= 10)
                r["chars_out"] = sum(len(norm(s["text"])) for s in segs)
                r["chars_ref"] = sum(len(norm(p["text"])) for p in ref["paragraphs"])
            res.setdefault(d.name, {})[name] = r
    (OUT / "summary.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for path in PATHS:
        a, b = res.get(f"{path}-vad0", {}), res.get(f"{path}-vad1", {})
        print(f"\n### {path}（vad 關 → 開）")
        print("| 素材 | CER | 數字不計 CER | 整段漏掉 | 漏句 | 輸出段數（有文字） |\n|---|---|---|---|---|---|")
        for name in MATS:
            x, y = a.get(name), b.get(name)
            if not x or not y:
                continue
            if name in ("SIL", "NOISE"):
                print(f"| {name} | — | — | — | — | {x['with_text']} → {y['with_text']} |")
            else:
                print(f"| {name} | {x['cer']:.1%} → {y['cer']:.1%} | {x['cer_nonum']:.1%} → {y['cer_nonum']:.1%} | "
                      f"{x['blank_paras']} → {y['blank_paras']}（/{x['ref_paras']}） | {x['omitted']} → {y['omitted']} | "
                      f"{x['with_text']} → {y['with_text']} |")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    {"run": run, "score": score}[sys.argv[1]](sys.argv[2:])
