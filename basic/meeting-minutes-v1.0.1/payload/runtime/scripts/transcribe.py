"""Local meeting transcription pipeline.

ffmpeg (16 kHz mono) -> sherpa-onnx speaker diarization (CPU)
  -> Whisper（後端依 config.json：OpenVINO NPU/GPU/CPU、faster-whisper CUDA/CPU、MLX Apple GPU）-> OpenCC s2twp
裝置不在執行時偵測，一律使用安裝時 setup_backend.py 選定的組合。
  -> transcript.json / transcript.md / transcript.srt (+ video keyframes)

Usage:
  python transcribe.py <錄音或錄影檔> [--out-dir DIR] [--backend openvino|ct2 --device ...]
                      [--speakers N] [--hotwords-file glossary.txt] [--no-diarize]
                      [--no-keyframes] [--whisper turbo]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULT_WHISPER, default_glossary, emb_model, load_config, seg_model, utf8_console  # noqa: E402

SR = 16000
MAX_WIN = 28.0          # seconds per Whisper call (fits the 30 s window, NPU-friendly static shape)
THREADS = max(1, min(8, (os.cpu_count() or 4) // 2))
MIN_SEG = 0.4           # drop diarization segments shorter than this
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".flv"}

# Common Whisper zh hallucinations on silence/music
HALLUCINATION = re.compile(
    r"(字幕|字幕組|訂閱|點贊|點讚|按讚|明鏡|Amara|請不吝|感謝觀看|謝謝觀看|打賞|支持明鏡)", re.I)


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def ts(sec: float, srt: bool = False) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"


# ---------------------------------------------------------------- audio / video
def to_wav(src: Path, dst: Path):
    if not shutil.which("ffmpeg"):
        sys.exit("找不到 ffmpeg，請先安裝：winget install Gyan.FFmpeg")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn",
                    "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)], check=True)


def extract_keyframes(src: Path, out_dir: Path, scene: float, max_frames: int) -> list:
    """Scene-change frames (slides / screen share) with timestamps from showinfo."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "frame_%04d.jpg"
    vf = f"select='eq(n,0)+gt(scene,{scene})',showinfo,scale='min(1600,iw)':-2"
    proc = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-i", str(src), "-vf", vf,
                           "-fps_mode", "vfr", "-q:v", "3", "-frames:v", str(max_frames),
                           str(pattern)], capture_output=True, text=True, errors="ignore")
    times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
    frames = []
    for i, t in enumerate(times, 1):
        old = out_dir / f"frame_{i:04d}.jpg"
        if old.exists():
            new = out_dir / f"frame_{i:04d}_{ts(t).replace(':', '')}.jpg"
            old.replace(new)
            frames.append({"time": round(t, 2), "file": str(new)})
    return frames


# ---------------------------------------------------------------- diarization
def diarize(audio: np.ndarray, speakers: int, threshold: float) -> list:
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
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speakers, threshold=threshold),
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
            log(f"  說話者分離 {pct}%")
            step["next"] = pct + 10
        return 0

    result = sd.process(audio, callback=progress).sort_by_start_time()
    segs = [(r.start, r.end, r.speaker) for r in result if r.end - r.start >= MIN_SEG]
    order = {}  # renumber speakers by first appearance: 0,1,2...
    for _, _, spk in segs:
        order.setdefault(spk, len(order))
    return [(s, e, order[spk]) for s, e, spk in segs]


def merge_turns(segs: list, max_len: float = MAX_WIN, max_gap: float = 1.0) -> list:
    """Merge consecutive same-speaker segments into windows <= max_len."""
    merged = []
    for s, e, spk in segs:
        if merged and merged[-1][2] == spk and s - merged[-1][1] <= max_gap and e - merged[-1][0] <= max_len:
            merged[-1][1] = e
        else:
            merged.append([s, e, spk])
    return merged


def split_long(audio: np.ndarray, s: float, e: float, max_len: float = MAX_WIN) -> list:
    """Split [s,e] into <= max_len windows, cutting at the quietest 100 ms near each boundary."""
    out = []
    while e - s > max_len:
        lo, hi = int((s + max_len * 0.7) * SR), int((s + max_len) * SR)
        frame = SR // 10
        seg = audio[lo:hi]
        n = max(1, len(seg) // frame)
        rms = [float(np.sqrt(np.mean(seg[i * frame:(i + 1) * frame] ** 2) + 1e-12)) for i in range(n)]
        cut = (lo + int(np.argmin(rms)) * frame + frame // 2) / SR
        out.append((s, cut))
        s = cut
    out.append((s, e))
    return out


# ---------------------------------------------------------------- ASR
def load_asr(backend: str, model: str, device: str, compute_type: str, language, hotwords):
    """依 config 載入，不做即時偵測；失敗就明確告知重新偵測。"""
    import backends
    t0 = time.time()
    try:
        b = backends.create(backend, model, device, language, hotwords, compute_type)
    except Exception as ex:  # noqa: BLE001
        sys.exit(f"無法以 {backend}/{device} 載入 Whisper：{ex}\n"
                 "硬體或驅動可能已變更，請重新執行 install.cmd（或 setup_backend.py）重新偵測。")
    log(f"  Whisper 載入：{backend} / {device}（{time.time() - t0:.1f}s）")
    return b


TW_PREFER = {"臺": "台"}   # 台灣日常書寫習慣；OpenCC s2twp 會把「台」轉成「臺」


def clean(text: str, cc, protect: dict | None = None) -> str:
    if cc:
        text = cc.convert(text)
        for wrong, right in (protect or {}).items():
            text = text.replace(wrong, right)
    text = re.sub(r"(.{1,6}?)\1{4,}", r"\1", text)      # collapse looping repeats
    if HALLUCINATION.search(text) and len(text) < 40:
        return ""
    return text.strip()


# ---------------------------------------------------------------- outputs
def write_outputs(out_dir: Path, meta: dict, segs: list, frames: list):
    (out_dir / "transcript.json").write_text(
        json.dumps({"meta": meta, "segments": segs, "keyframes": frames}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    with open(out_dir / "transcript.srt", "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{ts(s['start'], True)} --> {ts(s['end'], True)}\n[{s['speaker']}] {s['text']}\n\n")

    lines = [f"# 逐字稿：{meta['source']}", "",
             f"- 長度：{ts(meta['duration'])}　講者數：{meta['speakers']}　ASR：{meta['model']} @ {meta['device']}",
             f"- 處理耗時：{meta['elapsed_sec']:.0f}s（RTF {meta['rtf']:.2f}）", ""]
    events = [(s["start"], "seg", s) for s in segs] + [(k["time"], "frame", k) for k in frames]
    cur_spk, buf, buf_t = None, [], 0.0

    def flush():
        if buf:
            lines.append(f"**[{ts(buf_t)}] {cur_spk}**：{''.join(buf)}")
            lines.append("")

    for t, kind, item in sorted(events, key=lambda x: x[0]):
        if kind == "frame":
            flush(); buf.clear(); cur_spk = None
            lines.append(f"> 🖼 [{ts(t)}] 畫面：`{Path(item['file']).name}`")
            lines.append("")
            continue
        if item["speaker"] != cur_spk:
            flush(); buf.clear()
            cur_spk, buf_t = item["speaker"], item["start"]
        sep = "" if not buf or re.match(r"[一-鿿，。！？、]", item["text"][:1]) else " "
        buf.append(sep + item["text"])
    flush()
    (out_dir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- main
def main():
    utf8_console()
    ap = argparse.ArgumentParser(description="本機會議錄音轉寫（Whisper + sherpa-onnx 說話者分離）")
    ap.add_argument("input")
    ap.add_argument("--out-dir", help="預設：<輸入檔名>_minutes/")
    cfg = load_config()
    ap.add_argument("--backend", default=cfg.get("backend", "openvino"), choices=["openvino", "ct2", "mlx"],
                    help="預設取自 config.json（安裝時偵測決定）；手動覆寫僅供測試")
    ap.add_argument("--device", default=cfg.get("device", "CPU"),
                    help="openvino：NPU / GPU / CPU；ct2：cuda / cuda:1 / cpu；mlx：gpu。預設取自 config.json")
    ap.add_argument("--compute-type", default=cfg.get("compute_type", "default"))
    ap.add_argument("--whisper", default=cfg.get("whisper", DEFAULT_WHISPER))
    ap.add_argument("--language", default="zh", help="zh / en / ja ...；auto = 自動偵測")
    ap.add_argument("--speakers", type=int, default=-1, help="已知講者人數；-1 = 自動")
    ap.add_argument("--cluster-threshold", type=float, default=0.8, help="自動分群門檻，越大講者越少（已知人數請改用 --speakers）")
    ap.add_argument("--hotwords", help="專有名詞，以逗號或空白分隔")
    ap.add_argument("--hotwords-file", default=str(default_glossary()), help="專有名詞清單檔（一行一個），預設為 runtime 目錄的 glossary.txt")
    ap.add_argument("--no-diarize", action="store_true")
    ap.add_argument("--no-keyframes", action="store_true")
    ap.add_argument("--scene", type=float, default=0.3, help="畫面變化門檻（0~1）")
    ap.add_argument("--max-frames", type=int, default=60)
    ap.add_argument("--no-opencc", action="store_true")
    args = ap.parse_args()
    if not cfg:
        log("  [!] 找不到 config.json，請先執行 install.cmd；暫以 openvino/CPU 執行")
    if args.backend != cfg.get("backend", "openvino") and args.compute_type == cfg.get("compute_type"):
        args.compute_type = "default"   # 手動換後端時不沿用另一個後端的精度設定

    src = Path(args.input).resolve()
    if not src.exists():
        sys.exit(f"找不到檔案：{src}")
    out_dir = Path(args.out_dir) if args.out_dir else src.with_name(src.stem + "_minutes")
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    log("[1/4] 轉換音訊 16kHz mono")
    wav = out_dir / "audio16k.wav"
    to_wav(src, wav)
    audio, sr = sf.read(str(wav), dtype="float32")
    assert sr == SR
    duration = len(audio) / SR
    log(f"  長度 {ts(duration)}")

    frames = []
    if src.suffix.lower() in VIDEO_EXT and not args.no_keyframes:
        log("[*] 擷取影片關鍵畫面")
        frames = extract_keyframes(src, out_dir / "frames", args.scene, args.max_frames)
        log(f"  {len(frames)} 張")

    if args.no_diarize:
        turns = [[0.0, duration, "S?"]]
    else:
        log("[2/4] 說話者分離（CPU）")
        segs = diarize(audio, args.speakers, args.cluster_threshold)
        turns = [[s, e, f"S{spk + 1}"] for s, e, spk in merge_turns(segs)]
        if not turns:
            turns = [[0.0, duration, "S?"]]
    speakers = len({t[2] for t in turns})
    log(f"  {len(turns)} 段、{speakers} 位講者")

    log(f"[3/4] 語音辨識（{args.backend} / {args.device}）")
    hot = args.hotwords or ""
    if args.hotwords_file and Path(args.hotwords_file).exists():
        hot += " " + " ".join(l.strip() for l in Path(args.hotwords_file).read_text(encoding="utf-8").splitlines()
                              if l.strip() and not l.startswith("#"))
    hot = re.sub(r"[,，\s]+", ", ", hot).strip(", ") or None
    lang = None if args.language == "auto" else args.language
    cc = None
    if not args.no_opencc:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
    # 專有名詞維持 glossary 原樣（避免 OpenCC 改寫），再套台灣慣用字
    protect = {}
    for w in (hot or "").split(", "):
        if w and cc and cc.convert(w) != w:
            protect[cc.convert(w)] = w
    protect.update(TW_PREFER)
    asr = load_asr(args.backend, args.whisper, args.device, args.compute_type, lang, hot)
    dev = f"{args.backend}/{args.device}"

    out = []
    t_asr = time.time()
    done_sec = 0.0
    for i, (s, e, spk) in enumerate(turns, 1):
        for ws, we in split_long(audio, s, e):
            a, b = max(0, int((ws - 0.15) * SR)), min(len(audio), int((we + 0.15) * SR))
            text = clean(asr.transcribe(audio[a:b]), cc, protect)
            if text:
                out.append({"start": round(ws, 2), "end": round(we, 2), "speaker": spk, "text": text})
        done_sec += e - s
        if i % 10 == 0 or i == len(turns):
            el = time.time() - t_asr
            eta = el / max(done_sec, 1e-6) * (duration - done_sec)
            log(f"  {i}/{len(turns)} 段，已處理 {ts(done_sec)}，預估剩餘 {ts(max(eta, 0))}")

    log("[4/4] 輸出檔案")
    elapsed = time.time() - t_start
    meta = {"source": src.name, "duration": round(duration, 2), "device": dev, "model": args.whisper,
            "language": args.language, "speakers": speakers, "elapsed_sec": round(elapsed, 1),
            "rtf": elapsed / max(duration, 1e-6), "hotwords": hot}
    write_outputs(out_dir, meta, out, frames)
    wav.unlink(missing_ok=True)
    print(json.dumps({"out_dir": str(out_dir), "transcript_md": str(out_dir / "transcript.md"),
                      "segments": len(out), "speakers": speakers, "keyframes": len(frames),
                      "device": dev, "elapsed_sec": round(elapsed, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
