"""〔2.0.0〕說話者分離的實測與計分（規格 §10.2 D-1～D-4、D-6）。

計分邏輯由研究腳本移來（研究目錄不改）：
- score_labels()：2.0.0 開發期研究（內容類型）的 diar_sweep.py score()：段落標籤正確率（匈牙利法一對一對應）、DER（無 collar）
- der_collar()：2.0.0 開發期研究（本地模型評估）的 diar_eval.py der()：10 ms 格、collar 0.25 s、講者混淆＝混淆格 ÷ 基準語音格
分離本身一律呼叫版本目錄的 diarize.py（_testenv 決定版本，預設 2.0.0），素材是 tests/_out/<名>.wav／.ref.json（合成）。

  python -B eval_diar.py sherpa  --out res.json M1=0.8,0.9 CL2n=1.0       # 原始段快取在 res.json 旁的 .segs/；可重複執行
  python -B eval_diar.py pyannote --out res.json --python <GPU venv python> --model-dir <權重> M1 M1:4 CL1
  python -B eval_diar.py gpu-release --python … --model-dir … M1          # D-6：子行程結束後 nvidia-smi 的計算行程、torch 沒進主行程
  python -B eval_diar.py report res.json                                    # D-1～D-4 判定表（Markdown）

MEETING_MINUTES_PRO_HOME 要指向有 sherpa-onnx 模型的測試 home（複製，不要連結到已安裝的 runtime）。
"""
import argparse
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

import _testenv  # noqa: F401  （scripts 上 sys.path、測試 home）

HERE = Path(__file__).resolve().parent
OUT = HERE / "_out"
SR = 16000
FRAME = 0.01

# 內容類型研究「自動＋保留前 N 位」的段落標籤正確率（D-3 的下限；CL2n 用門檻 1.0＋前 3 位的 100%）與實際人數
T0449_TOPN = {"M1": (4, 0.957), "M2": (3, 0.967), "IV1": (3, 1.0), "RQ1": (3, 0.871), "PN1": (5, 1.0),
              "WS1": (4, 0.893), "TU1": (2, 1.0), "CL2n": (3, 0.964), "CL1": (3, 1.0)}
# 本地模型評估研究：sherpa CPU 的後處理案例（講者數要等於 N；講者混淆供參考）
T0445_TOPN = {"M1": (4, 0.013), "M3": (4, 0.017), "IV1": (3, 0.005), "CL2": (3, 0.002), "CL1": (3, 0.0)}
# 本地模型評估研究：pyannote 的講者數（D-1）
T0445_PYANNOTE = {"M1": 4, "M3": 4, "CL1": 3, "IV1": 3}
# 2.0 的類型預設門檻
TYPE_DEFAULT = {"M1": 0.9, "M2": 0.9, "M3": 0.9, "IV1": 0.9, "RQ1": 0.9, "WS1": 0.9, "TU1": 0.9, "PN1": 0.8,
                "CL1": 1.0, "CL2": 1.0, "CL2n": 1.0}


# ---------------------------------------------------------------- 計分（研究腳本移來）
def hungarian(w: list) -> dict:
    """最大化 Σ w[i][j] 的一對一對應（列數、欄數可不同）。回傳 {i: j}。（diar_sweep.py 原樣）"""
    n, m = len(w), len(w[0]) if w else 0
    size = max(n, m)
    big = max((max(r) for r in w), default=0) + 1
    cost = [[big - (w[i][j] if i < n and j < m else 0) for j in range(size)] for i in range(size)]
    INF = float("inf")
    u, v, p, way = [0] * (size + 1), [0] * (size + 1), [0] * (size + 1), [0] * (size + 1)
    for i in range(1, size + 1):
        p[0], j0 = i, 0
        minv, used = [INF] * (size + 1), [False] * (size + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, size + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(size + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = {}
    for j in range(1, size + 1):
        i = p[j] - 1
        if i < n and j - 1 < m and w[i][j - 1] > 0:
            out[i] = j - 1
    return out


def _frames(spans: list, labels: list, n_frames: int) -> np.ndarray:
    a = np.full(n_frames, -1, dtype=np.int32)
    for (s, e), lab in zip(spans, labels):
        a[int(round(s / FRAME)):int(round(e / FRAME))] = lab
    return a


def score_labels(ref: dict, turns: list, duration: float) -> dict:
    """內容類型研究的計分（diar_sweep.score()）：turns＝merge_turns 之後的 [s, e, "S#"]。另加 merged_ref：
    被併成同一個系統講者的基準講者組（每位基準講者取時間重疊最多的系統講者，兩位以上相同＝兩人併成一位）。"""
    paras = ref["paragraphs"]
    rspk = sorted({p["speaker"] for p in paras})
    hspk = sorted({t[2] for t in turns}, key=lambda x: (len(x), x))
    ri, hi = {s: k for k, s in enumerate(rspk)}, {s: k for k, s in enumerate(hspk)}
    nf = int(duration / FRAME) + 2
    R = _frames([(p["start"], p["end"]) for p in paras], [ri[p["speaker"]] for p in paras], nf)
    H = _frames([(t[0], t[1]) for t in turns], [hi[t[2]] for t in turns], nf)
    w = [[0] * len(hspk) for _ in rspk]
    both = (R >= 0) & (H >= 0)
    for r, h in zip(R[both], H[both]):
        w[r][h] += 1
    mp = hungarian(w)
    ref_sp = int((R >= 0).sum())
    miss = int(((R >= 0) & (H < 0)).sum())
    fa = int(((R < 0) & (H >= 0)).sum())
    inv = {h: r for r, h in mp.items()}
    mapped = np.array([inv.get(int(h), -2) for h in H[both]]) if both.any() else np.array([])
    conf = int((mapped != R[both]).sum()) if both.any() else 0
    ok_n = ok_t = tot_t = 0
    for p in paras:
        a, b = int(round(p["start"] / FRAME)), int(round(p["end"] / FRAME))
        seg = H[a:b]
        seg = seg[seg >= 0]
        dur = b - a
        tot_t += dur
        if len(seg):
            best = int(np.bincount(seg).argmax())
            if inv.get(best) == ri[p["speaker"]]:
                ok_n += 1
                ok_t += dur
    major = {}
    for r in range(len(rspk)):
        row = w[r]
        if max(row, default=0) > 0:
            major.setdefault(int(np.argmax(row)), []).append(rspk[r])
    merged = [v for v in major.values() if len(v) > 1]
    return {"ref_speakers": len(rspk), "hyp_speakers": len(hspk), "count_ok": len(rspk) == len(hspk),
            "para_label_acc": round(ok_n / len(paras), 4), "para_label_acc_time": round(ok_t / max(tot_t, 1), 4),
            "der_nocollar": round((miss + fa + conf) / max(ref_sp, 1), 4),
            "confusion_both": round(conf / max(int(both.sum()), 1), 4), "merged_ref": merged}


def der_collar(ref_segs: list, hyp_segs: list, dur: float) -> dict:
    """本地模型評估研究的計分（diar_eval.der()）：collar 0.25 s、最佳對應；confusion＝混淆格 ÷ 基準語音格。"""
    n = int(dur / FRAME) + 1

    def fr(segs):
        lab = np.full(n, -1, dtype=np.int32)
        for s, e, k in segs:
            lab[int(s / FRAME):min(n, int(e / FRAME))] = k
        return lab
    r, h = fr(ref_segs), fr(hyp_segs)
    mask = np.ones(n, dtype=bool)
    for s, e, _ in ref_segs:
        for t in (s, e):
            mask[max(0, int((t - 0.25) / FRAME)):int((t + 0.25) / FRAME)] = False
    r, h = r[mask], h[mask]
    rs, hs = sorted(set(r[r >= 0])), sorted(set(h[h >= 0]))
    co = np.zeros((len(rs), len(hs)), dtype=np.int64)
    for i, a in enumerate(rs):
        for j, b in enumerate(hs):
            co[i, j] = np.sum((r == a) & (h == b))
    best = -1
    if len(rs) <= 8 and len(hs) <= 8:
        big, small = (hs, rs) if len(hs) >= len(rs) else (rs, hs)
        for perm in itertools.permutations(range(len(big)), len(small)):
            tot = sum(co[i, perm[i]] if len(hs) >= len(rs) else co[perm[i], i] for i in range(len(small)))
            best = max(best, tot)
    else:
        used_r, used_h, best = set(), set(), 0
        for i, j in sorted(((i, j) for i in range(len(rs)) for j in range(len(hs))), key=lambda x: -co[x]):
            if i in used_r or j in used_h:
                continue
            used_r.add(i)
            used_h.add(j)
            best += co[i, j]
    speech = int(np.sum(r >= 0))
    miss = int(np.sum((r >= 0) & (h < 0)))
    fa = int(np.sum((r < 0) & (h >= 0)))
    both = int(np.sum((r >= 0) & (h >= 0)))
    conf = both - int(max(best, 0))
    return {"der": round((miss + fa + conf) / speech, 4), "miss": round(miss / speech, 4),
            "false_alarm": round(fa / speech, 4), "confusion": round(conf / speech, 4)}


def load_material(name: str):
    import soundfile as sf
    ref = json.loads((OUT / f"{name}.ref.json").read_text(encoding="utf-8"))
    audio, sr = sf.read(str(OUT / f"{name}.wav"), dtype="float32")
    assert sr == SR
    return ref, audio, len(audio) / SR


def ref_segs(ref: dict) -> list:
    ids = {}
    return [(p["start"], p["end"], ids.setdefault(p["speaker"], len(ids))) for p in ref["paragraphs"]]


def evaluate(ref: dict, segs: list, duration: float) -> dict:
    import transcribe as tr
    turns = [[s, e, f"S{k + 1}"] for s, e, k in tr.merge_turns(segs)]
    out = score_labels(ref, turns, duration)
    out.update(der_collar=der_collar(ref_segs(ref), [tuple(x) for x in segs], duration),
               raw_speakers=len({k for _, _, k in segs}), turns=turns)
    return out


# ---------------------------------------------------------------- 執行
def _save(out: Path, rows: list):
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def _upsert(rows: list, row: dict, keys: tuple) -> list:
    return [r for r in rows if any(r.get(k) != row.get(k) for k in keys)] + [row]


def cmd_sherpa(a):
    import diarize as diar
    out = Path(a.out)
    cache = out.with_suffix(".segs")
    cache.mkdir(exist_ok=True)
    rows = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    for job in a.jobs:
        name, thrs = job.split("=", 1)
        ref, audio, dur = load_material(name)
        for thr in thrs.split(","):
            thr = float(thr)
            cf = cache / f"{name}@{thr}.json"
            if cf.exists():
                c = json.loads(cf.read_text(encoding="utf-8"))
            else:
                t0 = time.perf_counter()
                segs = diar.run_sherpa(audio, thr, log=lambda m: None)
                c = {"segs": [list(x) for x in segs], "sec": round(time.perf_counter() - t0, 1), "threads": diar.THREADS}
                cf.write_text(json.dumps(c), encoding="utf-8")
            segs = [tuple(x) for x in c["segs"]]
            n_ref = len({p["speaker"] for p in ref["paragraphs"]})
            for top in (None, n_ref):
                s2, merged = (segs, 0.0) if top is None else diar.keep_top_n(segs, top)
                ev = evaluate(ref, s2, dur)
                stats = diar.speaker_stats(ev.pop("turns"))
                row = {"engine": "sherpa", "material": name, "threshold": thr, "top_n": top, "sec": c["sec"],
                       "sec_per_hour": round(c["sec"] / dur * 3600, 1), "duration_min": round(dur / 60, 1),
                       "top_n_merged_sec": merged, "speaker_stats": stats, **ev}
                rows = _upsert(rows, row, ("engine", "material", "threshold", "top_n"))
                print(f"{name:4s} thr {thr} top {top or '-':>2} 講者 {row['hyp_speakers']}/{row['ref_speakers']}"
                      f" 標籤 {row['para_label_acc']:.1%} 混淆(collar) {row['der_collar']['confusion']:.1%}"
                      f" 併成一位 {row['merged_ref'] or '無'} {c['sec']}s", flush=True)
            _save(out, rows)


def cmd_pyannote(a):
    import diarize as diar
    out = Path(a.out)
    rows = json.loads(out.read_text(encoding="utf-8")) if out.exists() else []
    tmp = Path(a.work)
    tmp.mkdir(parents=True, exist_ok=True)
    for job in a.jobs:
        name, _, n = job.partition(":")
        n = int(n) if n else None
        ref, audio, dur = load_material(name)
        segs, info = diar.run_pyannote(OUT / f"{name}.wav", tmp, dur, n, a.gpu, {}, log=lambda m: None,
                                       python=a.python, model_dir=a.model_dir)
        ev = evaluate(ref, segs, dur)
        stats = diar.speaker_stats(ev.pop("turns"))
        row = {"engine": "pyannote", "material": name, "speakers_arg": n, "duration_min": round(dur / 60, 1),
               "sec_per_hour": round(info["process_sec"] / dur * 3600, 1),
               "wall_per_hour": round(info["wall_sec"] / dur * 3600, 1), **info, "speaker_stats": stats, **ev}
        rows = _upsert(rows, row, ("engine", "material", "speakers_arg"))
        _save(out, rows)
        print(f"{name:4s} N={n or '自動'} 講者 {row['hyp_speakers']}/{row['ref_speakers']} 混淆 {row['der_collar']['confusion']:.1%}"
              f" 每小時 {row['sec_per_hour']} s（含載入 {row['wall_per_hour']} s）峰值 {info['peak_mib']} MiB {info['annotation']}",
              flush=True)


def compute_apps() -> list:
    p = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader"],
                       capture_output=True, text=True, errors="replace")
    return [line.strip() for line in p.stdout.splitlines() if line.strip()]


def cmd_gpu_release(a):
    """D-6：子行程期間 nvidia-smi 看得到 GPU venv 的 python，結束後（主行程載入 ASR 之前）看不到；主行程沒有 import torch。"""
    import diarize as diar
    name = a.material
    ref, audio, dur = load_material(name)
    tmp = Path(a.work)
    tmp.mkdir(parents=True, exist_ok=True)
    venv_py = str(Path(a.python).resolve()).lower()
    seen, stop = [], threading.Event()

    def poll():
        while not stop.is_set():
            seen.extend(x for x in compute_apps() if x not in seen)
            time.sleep(0.5)
    before = compute_apps()
    th = threading.Thread(target=poll, daemon=True)
    th.start()
    segs, info = diar.run_pyannote(OUT / f"{name}.wav", tmp, dur, None, a.gpu, {}, log=lambda m: None,
                                   python=a.python, model_dir=a.model_dir)
    stop.set()
    th.join()
    after = compute_apps()             # 這時主行程還沒載入 ASR（transcribe.py 的順序）

    # Windows 的 venv python.exe 是轉呼叫基底 Python 的啟動器，nvidia-smi 看到的是基底 python.exe：
    # 以「執行期間新出現、名稱是 python 的 PID」認定子行程，結束後這些 PID 不得還在。
    def pid(x):
        return x.split(",")[0].strip()
    before_pids = {pid(x) for x in before}
    new = [x for x in seen if pid(x) not in before_pids and "python" in x.lower()]
    new_pids = {pid(x) for x in new}
    still = [x for x in after if pid(x) in new_pids]
    res = {"material": name, "segments": len(segs), "venv_python": venv_py, "during_new_python": new,
           "after_still_running": still, "torch_in_main": "torch" in sys.modules, "peak_mib": info.get("peak_mib"),
           "pass": bool(new) and not still and "torch" not in sys.modules}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def _row(rows, **kw):
    for r in rows:
        if all(r.get(k) == v for k, v in kw.items()):
            return r
    return None


def cmd_report(a):
    rows = []
    for f in a.results:
        rows += json.loads(Path(f).read_text(encoding="utf-8"))
    lines = []

    def ok(b):
        return "✅" if b else "❌"
    # D-1
    lines += ["### D-1 pyannote（GPU）", "", "| 素材 | 人數設定 | 講者數 | 講者混淆 | 每小時秒數（處理／含載入） | 峰值 MiB | 判定 |",
              "|---|---|---|---|---|---|---|"]
    for name, want in T0445_PYANNOTE.items():
        for n in (None, want):
            r = _row(rows, engine="pyannote", material=name, speakers_arg=n)
            if not r:
                continue
            good = r["hyp_speakers"] == want and r["der_collar"]["confusion"] <= 0.02 and r["sec_per_hour"] <= 150
            lines.append(f"| {name} | {n or '自動'} | {r['hyp_speakers']}（{want}） | {r['der_collar']['confusion']:.1%} |"
                         f" {r['sec_per_hour']}／{r['wall_per_hour']} | {r.get('peak_mib')} | {ok(good)} |")
    # D-2
    lines += ["", "### D-2 sherpa 類型預設門檻", "", "| 素材 | 門檻 | 講者數 | 段落標籤正確率 | 兩人併成一位 | 門檻條件 | 判定 |",
              "|---|---|---|---|---|---|---|"]
    gates = {"PN1": (0.8, "＝5 位", lambda r: r["hyp_speakers"] == 5),
             "IV1": (0.9, "≤ 4 位且沒有兩人併成一位", lambda r: r["hyp_speakers"] <= 4 and not r["merged_ref"]),
             "CL2n": (1.0, "≤ 5 位、標籤 ≥ 99%", lambda r: r["hyp_speakers"] <= 5 and r["para_label_acc"] >= 0.99),
             "M1": (0.9, "4 位", lambda r: r["hyp_speakers"] == 4)}
    for name, (thr, cond, fn) in gates.items():
        r = _row(rows, engine="sherpa", material=name, threshold=thr, top_n=None)
        if r:
            lines.append(f"| {name} | {thr} | {r['hyp_speakers']}/{r['ref_speakers']} | {r['para_label_acc']:.1%} |"
                         f" {r['merged_ref'] or '無'} | {cond} | {ok(fn(r))} |")
    # D-3
    lines += ["", "### D-3 保留前 N 位（sherpa CPU）", "",
              "| 素材 | 門檻 | 自動講者數 → 前 N 位 | 標籤正確率 | 下限（研究） | 被併掉秒數 | 混淆（collar 0.25 s） | 判定 |",
              "|---|---|---|---|---|---|---|---|"]
    cases = [(m, 0.8, T0449_TOPN[m][1]) for m in T0449_TOPN if m != "CL2n"] + [("CL2n", 0.8, 0.964), ("CL2n", 1.0, 1.0)]
    cases += [(m, 0.8, None) for m in T0445_TOPN if m not in T0449_TOPN]
    cases += [(m, TYPE_DEFAULT[m], None) for m in TYPE_DEFAULT if TYPE_DEFAULT[m] != 0.8 and (m, TYPE_DEFAULT[m]) != ("CL2n", 1.0)]
    for name, thr, floor in cases:
        r = _row(rows, engine="sherpa", material=name, threshold=thr, top_n=None)
        t = _row(rows, engine="sherpa", material=name, threshold=thr, top_n=(T0449_TOPN.get(name) or T0445_TOPN.get(name))[0])
        if not (r and t):
            continue
        good = t["hyp_speakers"] == t["ref_speakers"] and (floor is None or round(t["para_label_acc"], 3) >= floor)   # 研究的表只到 0.1%
        lines.append(f"| {name} | {thr} | {r['hyp_speakers']} → {t['hyp_speakers']}（N={t['top_n']}） | {t['para_label_acc']:.1%} |"
                     f" {'—' if floor is None else f'{floor:.1%}'} | {t['top_n_merged_sec']} | {t['der_collar']['confusion']:.1%} | {ok(good)} |")
    # D-4
    lines += ["", "### D-4 零星講者（自動，類型預設門檻與 0.8）", "", "| 素材 | 引擎／門檻 | 代號（秒，⚠＝minor） |", "|---|---|---|"]
    for name in ("CL1", "M1", "M2"):
        for r in rows:
            if r["material"] == name and r.get("top_n") is None and r.get("speakers_arg") is None:
                tag = f"sherpa {r['threshold']}" if r["engine"] == "sherpa" else "pyannote"
                lines.append(f"| {name} | {tag} | " + "、".join(f"{s['speaker']} {s['sec']}{' ⚠' if s['minor'] else ''}"
                                                            for s in r["speaker_stats"]) + " |")
    print("\n".join(lines))


def main():
    for st in (sys.stdout, sys.stderr):
        st.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sherpa")
    s.add_argument("--out", required=True)
    s.add_argument("jobs", nargs="+")
    for name in ("pyannote", "gpu-release"):
        p = sub.add_parser(name)
        p.add_argument("--python", required=True)
        p.add_argument("--model-dir", required=True)
        p.add_argument("--gpu", type=int, default=0)
        p.add_argument("--work", default=str(OUT / "diar-work"))
        p.add_argument("--out", required=(name == "pyannote"))
        if name == "pyannote":
            p.add_argument("jobs", nargs="+")
        else:
            p.add_argument("material")
    r = sub.add_parser("report")
    r.add_argument("results", nargs="+")
    a = ap.parse_args()
    if a.cmd in ("sherpa", "pyannote", "gpu-release") and not os.environ.get("MEETING_MINUTES_PRO_HOME"):
        sys.exit("請設定 MEETING_MINUTES_PRO_HOME（測試 home，要有 sherpa-onnx 模型）")
    {"sherpa": cmd_sherpa, "pyannote": cmd_pyannote, "gpu-release": cmd_gpu_release, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
