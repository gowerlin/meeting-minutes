"""〔2.0.0〕pyannote 說話者分離（規格 §4.2.2）。在 GPU venv（$MMH/venv-gpu-diar）以獨立子行程執行，由 diarize.run_pyannote() 呼叫。

  venv-gpu-diar/Scripts/python.exe -B diarize_pyannote.py --wav audio16k.wav --model-dir <權重目錄>
      --out diarize.pyannote.json [--num-speakers N] [--device cuda] [--min-seg 0.4] [--annotation exclusive|regular]

- 只讀本機權重（主行程設 HF_HUB_OFFLINE=1，不連網、不需要權杖）；主行程另設 PYANNOTE_METRICS_ENABLED=0 關閉遙測，
  這裡在 import pyannote 之前再設一次（直接執行時也不送出使用統計）。
- 輸出 JSON：{"ok": true, "segments": [[start, end, k], …], "speakers": n, "device", "gpu_name", "torch", "pyannote",
  "init_sec", "process_sec", "peak_mib", "annotation"}；失敗 {"ok": false, "reason": <代碼>, "detail": <錯誤類別名稱>}，exit 1。
  不寫錯誤訊息全文（避免路徑或內容外流到 log）。
- 進度：stderr 每 10% 一行「progress N」（主行程轉成「說話者分離 N%」）。
- 本程式不 import 主 runtime 的模組（GPU venv 沒有主 runtime 的套件）。
"""
import argparse
import json
import os
import sys
import time
import wave

os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")
os.environ.setdefault("HF_HUB_OFFLINE", "1")

SR = 16000
# pipeline 的步驟 → 整體進度的區間（embeddings 佔大部分時間）
STEP_RANGE = {"segmentation": (0, 25), "speaker_counting": (25, 30), "embeddings": (30, 95),
              "discrete_diarization": (95, 100)}


def write(path: str, obj: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def fail(path: str, reason: str, ex: BaseException | None = None) -> int:
    write(path, {"ok": False, "reason": reason, "detail": type(ex).__name__ if ex else None})
    return 1


def read_wav(path: str):
    import numpy as np
    with wave.open(path) as w:
        if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("need 16 kHz mono 16-bit")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


class Progress:
    def __init__(self):
        self.next = 0

    def __call__(self, step_name, step_artifact=None, file=None, total=None, completed=None):
        lo, hi = STEP_RANGE.get(step_name, (None, None))
        if lo is None:
            return
        frac = 1.0 if not total or completed is None else min(1.0, completed / total)
        pct = int(lo + (hi - lo) * frac)
        if pct >= self.next:
            print(f"progress {pct}", file=sys.stderr, flush=True)
            self.next = pct // 10 * 10 + 10


def is_oom(ex: BaseException) -> bool:
    return type(ex).__name__ == "OutOfMemoryError" or "out of memory" in str(ex).lower()


def is_cuda(ex: BaseException) -> bool:
    s = str(ex)
    return "CUDA" in s or "cuda" in s or "cuDNN" in s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--min-seg", type=float, default=0.4)
    ap.add_argument("--annotation", choices=["exclusive", "regular"], default="exclusive",
                    help="exclusive＝exclusive_speaker_diarization（不重疊，預設）；regular＝speaker_diarization")
    a = ap.parse_args()

    try:
        audio = read_wav(a.wav)
    except Exception as ex:  # noqa: BLE001
        return fail(a.out, "audio_error", ex)
    try:
        t0 = time.perf_counter()
        import torch
        from pyannote.audio import Pipeline
        import pyannote.audio as pa
        if a.device.startswith("cuda") and not torch.cuda.is_available():
            return fail(a.out, "cuda_error")
        pipeline = Pipeline.from_pretrained(a.model_dir)
        if pipeline is None:
            return fail(a.out, "load_failed")
        dev = torch.device(a.device)
        pipeline.to(dev)
        init = time.perf_counter() - t0
    except Exception as ex:  # noqa: BLE001
        return fail(a.out, "oom" if is_oom(ex) else ("cuda_error" if is_cuda(ex) else "load_failed"), ex)
    try:
        if dev.type == "cuda":
            torch.cuda.reset_peak_memory_stats()
        wav = {"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": SR}
        kw = {"num_speakers": a.num_speakers} if a.num_speakers and a.num_speakers > 0 else {}
        t1 = time.perf_counter()
        out = pipeline(wav, hook=Progress(), **kw)
        proc = time.perf_counter() - t1
    except Exception as ex:  # noqa: BLE001
        return fail(a.out, "oom" if is_oom(ex) else ("cuda_error" if is_cuda(ex) else "process_failed"), ex)
    used = "regular"
    ann = None
    if a.annotation == "exclusive":
        ann = getattr(out, "exclusive_speaker_diarization", None)
        used = "exclusive" if ann is not None else "regular"
    if ann is None:
        ann = getattr(out, "speaker_diarization", out)       # 3.x 直接回傳 Annotation
    labels, segs = {}, []
    for turn, _, spk in ann.itertracks(yield_label=True):
        if turn.end - turn.start >= a.min_seg:
            segs.append([float(turn.start), float(turn.end), spk])
    segs.sort(key=lambda x: (x[0], x[1]))
    for x in segs:                                            # 依第一次出現重編 0、1、2…
        x[2] = labels.setdefault(x[2], len(labels))
    res = {"ok": True, "segments": [[round(s, 3), round(e, 3), k] for s, e, k in segs], "speakers": len(labels),
           "device": str(dev), "gpu_name": torch.cuda.get_device_name(dev) if dev.type == "cuda" else None,
           "torch": torch.__version__, "pyannote": getattr(pa, "__version__", None),
           "init_sec": round(init, 2), "process_sec": round(proc, 2),
           "peak_mib": round(torch.cuda.max_memory_allocated(dev) / 2**20) if dev.type == "cuda" else None,
           "annotation": f"{used}_speaker_diarization" if used == "exclusive" else "speaker_diarization"}
    write(a.out, res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
