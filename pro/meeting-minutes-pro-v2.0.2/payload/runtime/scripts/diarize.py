"""〔2.0.0〕說話者分離（規格 §4）。

- choose_engine()：diarization.engine（auto｜sherpa｜pyannote）＋平台、GPU 套件狀態、nvidia-smi 可用 VRAM → 引擎（§4.1）
- run_sherpa()：1.2.2 transcribe.diarize() 移入（sherpa-onnx CPU）；不再傳 num_clusters（U1，§4.4）
- run_pyannote()：在 GPU venv 以獨立子行程執行 diarize_pyannote.py（§4.2）；本行程不 import torch、不建 CUDA context
- keep_top_n()：講者人數 N → 自動分群後保留發言最多的 N 位（U1）
- speaker_stats()／stats_line()：講者發言時間與零星講者標記（U2，§4.5）
- run()：以上串起來，失敗退回 sherpa（§4.7），回傳段落與 transcript.json 的 meta.diarization（§4.8）

段落格式：(start, end, k)，k 依第一次出現重編 0、1、2…（與 1.2.2 diarize() 相同）；merge_turns 之後才換成 S1、S2…（transcribe.py）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (PYANNOTE_MODEL_FILES, emb_model, gpu_diar_python, pyannote_model_dir,  # noqa: E402
                    seg_model, setting, type_entry)

SR = 16000
THREADS = max(1, min(8, (os.cpu_count() or 4) // 2))
MIN_SEG = 0.4               # 丟掉短於此秒數的段（1.2.2 transcribe.MIN_SEG）
NVSMI_TIMEOUT = 10
PYANNOTE_SCRIPT = Path(__file__).resolve().parent / "diarize_pyannote.py"
PYANNOTE_OUT = "diarize.pyannote.json"      # 子行程的輸出檔（讀完即刪，不留在輸出資料夾）
ENGINES = ("auto", "sherpa", "pyannote")

# 原因代碼 → 中文（console 用；log 只記代碼）
REASON_TEXT = {
    "not_installed": "GPU 說話者分離套件未安裝或不完整", "no_gpu": "沒有偵測到可用的 NVIDIA 顯示卡",
    "low_vram": "顯示卡可用記憶體不足", "macos": "macOS 只支援 CPU 說話者分離",
    "load_failed": "模型載入失敗", "cuda_error": "CUDA 錯誤", "oom": "顯示卡記憶體不足", "audio_error": "讀取音訊失敗",
    "process_failed": "執行失敗", "timeout": "逾時", "bad_output": "輸出格式不對",
    "type": "內容類型的預設",
}
PYANNOTE_FAIL_REASONS = ("load_failed", "cuda_error", "oom", "audio_error", "process_failed")
NOT_INSTALLED_MSG = "  [!] GPU 說話者分離套件未完成安裝，改用 CPU（執行 install.cmd -GpuDiar 補裝）"   # 規格 §4.7


def _log(log, msg):
    (log or (lambda m: print(m, file=sys.stderr, flush=True)))(msg)


# ---------------------------------------------------------------- 段落小工具
def renumber(segs: list) -> list:
    """依第一次出現重編講者 0、1、2…"""
    order = {}
    for _, _, k in segs:
        order.setdefault(k, len(order))
    return [(s, e, order[k]) for s, e, k in segs]


def keep_top_n(segs: list, n: int) -> tuple:
    """U1（規格 §4.4）：保留總發言最多的 n 位，其餘代號的每一段併回時間上相鄰（前一段，沒有就後一段）的保留講者。

    作用在分離的原始段（MIN_SEG 過濾後、merge_turns 之前）；依總發言秒數排序，同秒數依第一次出現先後。
    自動只分出 ≤ n 位時原樣不動（不硬拆）。回傳 (重編後的段落, 被併掉的總秒數)。
    """
    segs = list(segs)
    first, tot = {}, {}
    for i, (s, e, k) in enumerate(segs):
        first.setdefault(k, i)
        tot[k] = tot.get(k, 0.0) + (e - s)
    if n is None or n <= 0 or len(tot) <= n:
        return renumber(segs), 0.0
    keep = set(sorted(tot, key=lambda k: (-tot[k], first[k]))[:n])
    out, merged = [], 0.0
    for i, (s, e, k) in enumerate(segs):
        if k not in keep:
            prev = next((t[2] for t in reversed(out) if t[2] in keep), None)
            nxt = next((t[2] for t in segs[i + 1:] if t[2] in keep), None)
            merged += e - s
            k = prev if prev is not None else nxt
        out.append((s, e, k))
    return renumber(out), round(merged, 2)


def trim_overlaps(segs: list, min_seg: float = MIN_SEG) -> list:
    """依開始時間截掉重疊（後一段的開頭改成前一段的結尾），剩下 < min_seg 秒就丟掉（規格 §4.2.2 改回 speaker_diarization 時用）。
    對不重疊的段落（exclusive_speaker_diarization）沒有作用。"""
    out, end = [], None
    for s, e, k in sorted(segs, key=lambda x: (x[0], x[1])):
        if end is not None and s < end:
            s = end
        if e - s < min_seg:
            continue
        out.append((s, e, k))
        end = e if end is None else max(end, e)
    return renumber(out)


def fmt_talk(sec: float) -> str:
    """講者發言時間：未滿 1 小時 m:ss，滿 1 小時 h:mm:ss（規格 §4.5）。"""
    s = int(round(sec))
    h, rem = divmod(s, 3600)
    m, x = divmod(rem, 60)
    return f"{h}:{m:02d}:{x:02d}" if h else f"{m}:{x:02d}"


def speaker_stats(turns: list, minor_sec: float = 10) -> list:
    """U2（規格 §4.5）：每個代號的總發言秒數、段數、佔比；總發言 < minor_sec 秒標 minor。依發言時間由多到少。"""
    sec, cnt, first = {}, {}, {}
    for i, (s, e, spk) in enumerate(turns):
        sec[spk] = sec.get(spk, 0.0) + (e - s)
        cnt[spk] = cnt.get(spk, 0) + 1
        first.setdefault(spk, i)
    total = sum(sec.values()) or 1.0
    return [{"speaker": k, "sec": round(sec[k], 1), "turns": cnt[k], "share": round(sec[k] / total, 3),
             "minor": sec[k] < minor_sec}
            for k in sorted(sec, key=lambda k: (-sec[k], first[k]))]


MINOR_NOTE = "⚠ 發言很少，可能是分離誤判"


def stats_line(stats: list) -> str | None:
    """transcript.md 表頭的「講者發言時間」一行；只有一位講者（或沒有統計）時不印。"""
    if not stats or len(stats) < 2:
        return None
    parts = []
    for st in stats:
        if st["minor"]:
            parts.append(f"{st['speaker']} {fmt_talk(st['sec'])} {MINOR_NOTE}")
        else:
            parts.append(f"{st['speaker']} {fmt_talk(st['sec'])}（{round(st['share'] * 100)}%）")
    return "- 講者發言時間：" + "、".join(parts)


# ---------------------------------------------------------------- 引擎選擇（§4.1）
def query_gpus(timeout: float = NVSMI_TIMEOUT) -> list | None:
    """nvidia-smi 的每張卡 (index, 可用 MiB)。nvidia-smi 不存在、逾時、輸出讀不懂 → None（視為 no_gpu）。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        p = subprocess.run([exe, "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    out = []
    for line in p.stdout.splitlines():
        m = re.match(r"^\s*(\d+)\s*,\s*(\d+)\s*$", line)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out or None


def choose_engine(cfg: dict, requested: str | None = None, platform: str | None = None, gpus=None, query=None,
                  ctype: str | None = None) -> dict:
    """回傳 {"engine": "pyannote"|"sherpa", "reason": …, "fallback": 代碼或 None, "requested": …, "gpu_index", "free_mib"}。

    auto 選 sherpa 不是退回（fallback None）；只有「要用 pyannote 卻沒用成」才記 fallback（規格 §4.1）。
    gpus：測試用，直接給 [(index, free_mib)] 或 [] 代替 nvidia-smi。
    〔2.0.0〕ctype：內容類型。優先序（規格 §6.3）：requested（命令列 --diarize-engine）> content_types.<ctype>.diarize_engine
    > diarization.engine > DEFAULTS（範本不參與這個鍵）。值來自類型鍵時 reason 記 "type"（座談預設 sherpa；不算退回）。
    """
    from_type = False
    req = requested
    if not req:
        req = type_entry(cfg, ctype, "diarize_engine")
        from_type = req in ENGINES and req != "auto"
        if not from_type:
            req = setting(cfg, "diarization.engine")
    if req not in ENGINES:
        req = "auto"
    base = {"requested": req, "gpu_index": None, "free_mib": None}
    by = "type" if from_type else "config"
    if req == "sherpa":
        return dict(base, engine="sherpa", reason=by, fallback=None)
    platform = platform or sys.platform
    reason, free = None, None
    if platform == "darwin":
        reason = "macos"
    elif platform != "win32" or setting(cfg, "diarization.pyannote.status") != "ready":
        reason = "not_installed"
    else:
        cards = (query or query_gpus)() if gpus is None else gpus
        if not cards:
            reason = "no_gpu"
        else:
            idx, free = max(cards, key=lambda c: c[1])
            if free < int(setting(cfg, "diarization.min_vram_mib")):
                reason = "low_vram"
            else:
                base.update(gpu_index=idx, free_mib=free)
    if reason is None:
        return dict(base, engine="pyannote", reason="auto_gpu" if req == "auto" else by, fallback=None)
    base["free_mib"] = free
    return dict(base, engine="sherpa", reason=reason, fallback=reason if req == "pyannote" else None)


def reason_text(code: str, free_mib=None) -> str:
    t = REASON_TEXT.get(code, code)
    if code == "low_vram" and free_mib is not None:
        t += f"（可用 {free_mib} MiB）"
    return t


# ---------------------------------------------------------------- sherpa（CPU）
def run_sherpa(audio, threshold: float, num_clusters: int = -1, log=None) -> list:
    """sherpa-onnx CPU 說話者分離（1.2.2 transcribe.diarize() 原樣，num_clusters 預設 -1＝依門檻自動分群）。"""
    import sherpa_onnx
    for p in (seg_model(), emb_model()):
        if not p.exists():
            sys.exit(f"缺少模型 {p}，請先執行 download_models.py")
    cfg = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg_model())),
            num_threads=THREADS,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(emb_model()), num_threads=THREADS),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=num_clusters, threshold=threshold),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not cfg.validate():
        sys.exit("sherpa-onnx diarization 設定無效")
    sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)

    step = {"next": 0}

    def progress(done, total):
        pct = done * 100 // max(total, 1)
        if pct >= step["next"]:
            _log(log, f"  說話者分離 {pct}%")
            step["next"] = pct + 10
        return 0

    result = sd.process(audio, callback=progress).sort_by_start_time()
    segs = [(r.start, r.end, r.speaker) for r in result if r.end - r.start >= MIN_SEG]
    return renumber(segs)


# ---------------------------------------------------------------- pyannote（GPU 子行程，§4.2）
class PyannoteFailed(Exception):
    def __init__(self, reason: str, detail: str | None = None, elapsed: float = 0.0):
        super().__init__(reason)
        self.reason, self.detail, self.elapsed = reason, detail, elapsed


def pyannote_installed(python: Path | None = None, model_dir: Path | None = None) -> bool:
    python = Path(python or gpu_diar_python())
    model_dir = Path(model_dir or pyannote_model_dir())
    if not python.is_file():
        return False
    return all((model_dir / f).is_file() and (model_dir / f).stat().st_size > 0 for f in PYANNOTE_MODEL_FILES)


def pyannote_timeout(cfg: dict, duration: float) -> float:
    return max(float(setting(cfg, "diarization.pyannote.timeout_min_sec")),
               duration * float(setting(cfg, "diarization.pyannote.timeout_factor")))


def _valid_segments(raw) -> list | None:
    if not isinstance(raw, list):
        return None
    out = []
    for x in raw:
        if not (isinstance(x, (list, tuple)) and len(x) == 3):
            return None
        s, e, k = x
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (s, e, k)) or e < s:
            return None
        out.append((float(s), float(e), int(k)))
    return out


def run_pyannote(wav: Path, out_dir: Path, duration: float, n: int | None, gpu_index, cfg: dict,
                 has_sound: bool = True, log=None, python=None, script=None, model_dir=None) -> tuple:
    """執行 GPU 子行程，回傳 (段落, 資訊)；失敗丟 PyannoteFailed(reason)。逾時＝max(timeout_min_sec, 錄音秒數 × timeout_factor)。

    子行程環境：HF_HUB_OFFLINE=1（只讀本機權重）、PYANNOTE_METRICS_ENABLED=0（關閉 pyannote 的遙測）、
    CUDA_VISIBLE_DEVICES=<選定的卡>、PYTHONDONTWRITEBYTECODE=1。進度由子行程的 stderr「progress N」轉成 1.2.2 的格式；
    子行程其他 stderr 內容不轉印、不寫 log（可能含路徑）。
    """
    t0 = time.perf_counter()
    python = Path(python or gpu_diar_python())
    model_dir = Path(model_dir or pyannote_model_dir())
    script = Path(script or PYANNOTE_SCRIPT)
    if not pyannote_installed(python, model_dir):
        raise PyannoteFailed("not_installed", elapsed=time.perf_counter() - t0)
    out_json = Path(out_dir) / PYANNOTE_OUT
    out_json.unlink(missing_ok=True)
    cmd = [str(python), "-B", str(script), "--wav", str(wav), "--model-dir", str(model_dir),
           "--out", str(out_json), "--device", "cuda", "--min-seg", str(MIN_SEG)]
    if n:
        cmd += ["--num-speakers", str(int(n))]
    env = dict(os.environ, HF_HUB_OFFLINE="1", PYANNOTE_METRICS_ENABLED="0", PYTHONDONTWRITEBYTECODE="1",
               PYTHONIOENCODING="utf-8")
    if gpu_index is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu_index)
    limit = pyannote_timeout(cfg, duration)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env,
                                text=True, encoding="utf-8", errors="replace")
    except OSError as ex:
        raise PyannoteFailed("not_installed", type(ex).__name__, time.perf_counter() - t0) from None

    def pump():
        nxt = 0
        for line in proc.stderr:
            m = re.match(r"^progress (\d+)\s*$", line.strip())
            if m and int(m.group(1)) >= nxt:
                pct = int(m.group(1))
                _log(log, f"  說話者分離 {pct}%")
                nxt = pct // 10 * 10 + 10
    th = threading.Thread(target=pump, daemon=True)
    th.start()
    try:
        rc = proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        th.join(5)
        proc.stderr.close()
        out_json.unlink(missing_ok=True)
        raise PyannoteFailed("timeout", f"{limit:.0f}s", time.perf_counter() - t0) from None
    th.join(5)
    proc.stderr.close()
    elapsed = time.perf_counter() - t0
    try:
        res = json.loads(out_json.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        res = None
    finally:
        out_json.unlink(missing_ok=True)
    if not isinstance(res, dict):
        raise PyannoteFailed("bad_output", f"exit {rc}", elapsed)
    if rc != 0 or res.get("ok") is not True:
        reason = res.get("reason")
        if not (isinstance(reason, str) and reason in PYANNOTE_FAIL_REASONS):
            reason = "bad_output"
        raise PyannoteFailed(reason, str(res.get("detail") or "")[:80] or None, elapsed)
    segs = _valid_segments(res.get("segments"))
    if segs is None or (not segs and has_sound):
        raise PyannoteFailed("bad_output", "segments", elapsed)
    segs = trim_overlaps(segs)                     # exclusive 版本沒有重疊：沒有作用
    info = {k: res.get(k) for k in ("gpu_name", "torch", "pyannote", "init_sec", "process_sec", "peak_mib", "annotation")}
    info["wall_sec"] = round(elapsed, 2)
    return segs, info


# ---------------------------------------------------------------- 串起來（§4.4～§4.8）
def run(choice: dict, audio, wav: Path, out_dir: Path, duration: float, n: int | None, threshold: float,
        cfg: dict, log=None, warn=None, **pyannote_kw) -> dict:
    """依 choose_engine() 的結果分離；pyannote 失敗退回 sherpa。回傳：
    {"segs": [(s, e, k)], "meta": transcript.json 的 meta.diarization（speakers 由呼叫端在 merge_turns 後補）,
     "pyannote_sec": 退回時 pyannote 用掉的秒數或 None}
    """
    warn = warn or log
    meta = {"engine": choice["engine"], "device": "cpu", "gpu_name": None, "engine_reason": choice["reason"],
            "fallback": choice["fallback"], "setting": "auto" if not n else int(n), "n": int(n) if n else None,
            "cluster_threshold": None, "speakers_raw": None, "speakers": None, "top_n_merged_sec": 0.0,
            "pyannote": None}
    if choice["fallback"] == "not_installed":
        _log(warn, NOT_INSTALLED_MSG)
    elif choice["fallback"]:
        _log(warn, f"  [!] 設定要用 GPU 說話者分離，但{reason_text(choice['fallback'], choice.get('free_mib'))}，改用 CPU")
    pyannote_sec = None
    if choice["engine"] == "pyannote":
        try:
            segs, info = run_pyannote(wav, out_dir, duration, n, choice.get("gpu_index"), cfg,
                                      has_sound=bool(len(audio)) and float(abs(audio).max()) > 1e-3, log=log,
                                      **pyannote_kw)
            meta.update(device=f"cuda:{choice.get('gpu_index') or 0}", gpu_name=info.get("gpu_name"),
                        speakers_raw=len({k for _, _, k in segs}),
                        pyannote={"init_sec": info.get("init_sec"), "process_sec": info.get("process_sec"),
                                  "peak_mib": info.get("peak_mib"), "torch": info.get("torch"),
                                  "version": info.get("pyannote"), "annotation": info.get("annotation")})
            return {"segs": segs, "meta": meta, "pyannote_sec": None}
        except PyannoteFailed as f:
            pyannote_sec = round(f.elapsed, 2)
            meta.update(engine="sherpa", fallback=f.reason, pyannote_sec=pyannote_sec)
            if f.reason == "not_installed":
                _log(warn, NOT_INSTALLED_MSG)
            else:
                _log(warn, f"  [!] GPU 說話者分離失敗（{reason_text(f.reason)}），改用 CPU")
    segs = run_sherpa(audio, threshold, log=log)
    meta.update(cluster_threshold=threshold, speakers_raw=len({k for _, _, k in segs}))
    if n:
        segs, merged = keep_top_n(segs, int(n))
        meta["top_n_merged_sec"] = merged
    return {"segs": segs, "meta": meta, "pyannote_sec": pyannote_sec}
