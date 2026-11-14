"""Local meeting transcription pipeline.

ffmpeg (16 kHz mono) -> 說話者分離〔2.0.0：diarize.py；pyannote GPU 子行程（選用安裝）或 sherpa-onnx CPU，失敗退回 sherpa〕
  -> Whisper（後端依 config.json：OpenVINO NPU/GPU/CPU、faster-whisper CUDA/CPU、MLX Apple GPU）
  -> ① OpenCC 詞彙回復表保護 -> OpenCC s2twp -> 放回保留詞 -> corrections.tsv
  -> ② 分段（講者／畫面／停頓／段長）-> ③ 標點（Whisper 自帶或 CT-Transformer）
  -> ④ 自動語意校正（選用；auto_correct.py，GPT 或 Claude）
  -> 〔1.2.0〕每一步寫進 <輸出資料夾>/run_log.jsonl（runlog.py）；沒有外層 MMP_RUN_ID 時結束前另寫 $MMH/logs/runs.jsonl
裝置不在執行時偵測，一律使用安裝時 setup_backend.py 選定的組合。
  -> transcript.json / transcript.md / transcript.srt (+ video keyframes)

Usage:
  python transcribe.py <錄音或錄影檔> [--out-dir DIR] [--backend openvino|ct2 --device ...]
                      [--type meeting|course|interview|tutorial|panel|workshop|requirements] [--template 代號]
                      [--speakers N] [--diarize-engine auto|sherpa|pyannote] [--cluster-threshold X]
                      [--hotwords-file glossary.txt] [--no-diarize]
                      [--no-keyframes] [--whisper turbo]
                      [--no-punct | --punct] [--paragraph-gap SEC] [--paragraph-max-chars N]
                      [--no-opencc-keep] [--correct | --no-correct | --claude | --openai]
                      [--correct-provider auto|claude|openai] [--correct-model M] [--correct-effort E]
                      [--correct-channel cli|api]
                      [--context "<一行>"] [--refs <檔或資料夾> …] [--no-refs] [--no-context] [--no-frames]   〔2.2.0〕
  〔2.2.0〕參考資料的旗標（規格 2.2.0 §7.3）原樣轉給接著執行的 AI 校正（auto_correct.run 的 refs_opts）；
  沒給這些旗標時呼叫方式與 2.1.0 相同。沒有做 AI 校正時 --context 仍寫 <輸出資料夾>/context.md（之後的校正、摘要沿用），
  其他四個旗標只在校正時有作用。
  〔2.4.0〕本機限定（規格 2.4.0 §2）：--local-only 在輸出資料夾寫入標記檔 local-only.json（之後這份的 AI 校正與摘要都拒絕送出；
  要解除只能刪掉標記檔）；config.json 的 privacy.local_only: true 時每一份都是本機限定。本機限定時管線內的 AI 校正不執行：
  命令列明確要求（--correct／--claude／--openai）時轉寫照常完成、最後 exit 6；只是 correction.enabled 開著時 exit 0。
  轉寫、對照表與詞表替換、分段標點、字幕都照常（本機處理）。
  〔2.4.1〕config.json 讀不了或 privacy.local_only 的值看不懂（規格 2.4.1 §2）：也當成本機限定（來源 config-unreadable），
  其他設定照舊用預設值，開頭另印一行警告（路徑與原因）；JSON 的 local_only 欄位是 config-unreadable。
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BREEZE26_NO_DIAR_NOTE, DEFAULT_WHISPER, LOCAL_ONLY_EXIT, VERSION, asr_vad_filter,  # noqa: E402
                    config_problem_text,
                    default_glossary,
                    load_config, local_only_message, local_only_state, local_only_why, print_banner, punct_model,
                    punct_ready, read_config, setting,
                    type_setting, utf8_console, write_local_only_marker)
import content_types  # noqa: E402
import diarize as diar  # noqa: E402

SR = 16000
MAX_WIN = 28.0          # seconds per Whisper call (fits the 30 s window, NPU-friendly static shape)
THREADS = diar.THREADS
MIN_SEG = diar.MIN_SEG  # drop diarization segments shorter than this
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v", ".flv"}

# Common Whisper zh hallucinations on silence/music
HALLUCINATION = re.compile(
    r"(字幕|字幕組|訂閱|點贊|點讚|按讚|明鏡|Amara|請不吝|感謝觀看|謝謝觀看|打賞|支持明鏡)", re.I)


def log(msg: str):
    print(msg, file=sys.stderr, flush=True)


def warn(msg: str):
    """黃字（主控台才上色；寫進檔案或管線時原樣）。"""
    if sys.stderr.isatty():
        msg = f"\033[33m{msg}\033[0m"
    print(msg, file=sys.stderr, flush=True)


def load_template(code: str) -> dict:
    """〔2.0.0〕自訂範本的轉寫部分（規格 §3.8.1：transcribe.py 只讀 speakers／cluster_threshold）。

    範本的載入與驗證由 templates.py（I-2）實作，這裡只依介面呼叫：templates.load(code) → dict，至少有
    code、name、base、speakers（"auto"｜整數｜"skip"｜None）、cluster_threshold（float｜None）、prompt_chars、prompt_truncated；
    無效時丟 templates.TemplateInvalid（屬性 reason、message）。回傳 {"ok": False, "reason", "message"} 表示不能用。
    """
    try:
        import templates
    except ImportError:
        return {"ok": False, "reason": "unsupported", "message": "這個版本還沒有自訂範本模組（templates.py）"}
    try:
        t = dict(templates.load(code))
    except getattr(templates, "TemplateInvalid", ValueError) as ex:
        return {"ok": False, "reason": getattr(ex, "reason", "load_failed"), "message": getattr(ex, "message", str(ex)),
                "base": getattr(ex, "base", None)}
    t["ok"] = True
    return t


class SettingsError(ValueError):
    """命令列與設定組不起來（類型與範本衝突、範本無效等）；main() 印訊息後 exit 2。"""


def resolve_settings(args, cfg: dict, explicit: set) -> dict:
    """〔2.0.0〕內容類型、自訂範本、講者設定、門檻、畫面設定（規格 §4.3、§4.4、§6.3）。

    優先序：命令列 > 自訂範本（speakers、cluster_threshold）> content_types.<代號> > 共用鍵 > DEFAULTS。
    explicit：命令列明確給了的旗標名稱（--speakers 的預設 -1 與明確給 -1 都是「自動」）。
    回傳 {"content_type", "type_note", "template"（load_template() 的結果或 None）, "speakers_setting"（"auto"｜N｜"skip"）,
          "cluster_threshold", "scene", "max_frames"}。
    """
    tpl = None
    if args.template:
        tpl = load_template(args.template)
        if not tpl["ok"]:
            raise SettingsError(f"自訂範本 {args.template} 沒有載入：{tpl['message']}")
    try:
        ctype, type_note = content_types.resolve_type(args.content_type, tpl.get("base") if tpl else None, cfg)
    except content_types.TypeChoiceError as ex:
        raise SettingsError(str(ex)) from None
    speakers_setting = "auto"                            # auto｜N｜skip（規格 §0.4）
    if args.no_diarize:
        speakers_setting = "skip"
    elif "--speakers" in explicit:
        speakers_setting = args.speakers if args.speakers > 0 else "auto"
    elif tpl and tpl.get("speakers") not in (None, "auto"):
        speakers_setting = "skip" if tpl["speakers"] == "skip" else int(tpl["speakers"])
    if args.cluster_threshold is not None:
        threshold = float(args.cluster_threshold)
    elif tpl and tpl.get("cluster_threshold") is not None:
        threshold = float(tpl["cluster_threshold"])
    else:
        threshold = float(type_setting(cfg, ctype, "cluster_threshold"))
    scene = args.scene if args.scene is not None else float(type_setting(cfg, ctype, "scene"))
    max_frames = args.max_frames if args.max_frames is not None else int(setting(cfg, "keyframes.max_frames"))
    return {"content_type": ctype, "type_note": type_note, "template": tpl, "speakers_setting": speakers_setting,
            "cluster_threshold": threshold, "scene": scene, "max_frames": max_frames}


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
    """〔2.0.0〕薄包裝：sherpa-onnx CPU 分離已移到 diarize.run_sherpa()（測試與研究腳本 import 這個名稱）。

    參數與 1.2.2 相同：speakers > 0 時照舊傳給 sherpa 的 num_clusters（固定分群）。轉寫主流程不再走這裡，
    改用 diarize.run()（--speakers N＝保留發言最多的 N 位，規格 §4.4）。
    """
    return diar.run_sherpa(audio, threshold, num_clusters=speakers, log=log)


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
# 〔2.1.0〕console 顯示用的模型名稱（config 的 whisper 值 → 顯示名稱）。別名改印完整模型名；
# 不在表上的值（例如 --whisper 直接給 Hugging Face repo）印「Whisper <原值>」。
ASR_DISPLAY = {
    "breeze": "Breeze-ASR-25",
    "breeze26": "Breeze-ASR-26（台語）",               # 〔2.5.0〕
    "turbo": "Whisper large-v3-turbo",
    "large-v3": "Whisper large-v3",
    "base": "Whisper base",
}


def asr_display_name(model: str) -> str:
    return ASR_DISPLAY.get(model, f"Whisper {model}")


def load_asr(backend: str, model: str, device: str, compute_type: str, language, hotwords, vad_filter: bool = False):
    """依 config 載入，不做即時偵測；失敗就明確告知重新偵測。〔2.5.0〕vad_filter：呼叫端依 asr_vad_filter() 決定。"""
    import backends
    name = asr_display_name(model)
    t0 = time.time()
    try:
        b = backends.create(backend, model, device, language, hotwords, compute_type, vad_filter=vad_filter)
    except Exception as ex:  # noqa: BLE001
        sys.exit(f"無法以 {backend}/{device} 載入 {name}：{ex}\n"
                 "硬體或驅動可能已變更，請重新執行 install.cmd（或 setup_backend.py）重新偵測。")
    vad = "；vad_filter 開：略過非人聲" if vad_filter else ""   # 〔2.5.0〕規格 2.5.0 §6
    log(f"  {name} 載入：{backend} / {device}（{time.time() - t0:.1f}s{vad}）")
    return b


TW_PREFER = {"臺": "台"}   # 台灣日常書寫習慣；OpenCC s2twp 會把「台」轉成「臺」


def clean(text: str, cc, protect: dict | None = None, keep=None) -> tuple:
    """回傳 (清理後文字, {OpenCC 詞彙回復表命中的保留寫法: 次數})。"""
    hits = {}
    if cc:
        if keep is not None:
            text, hits = keep.convert(text, cc)     # ① 保護 → s2twp → 放回保留詞
        else:
            text = cc.convert(text)
        for wrong, right in (protect or {}).items():
            text = text.replace(wrong, right)
    text = re.sub(r"(.{1,6}?)\1{4,}", r"\1", text)      # collapse looping repeats
    if HALLUCINATION.search(text) and len(text) < 40:
        return "", {}
    return text.strip(), hits


# ---------------------------------------------------------------- outputs
def punct_header(meta: dict) -> str:
    p = meta.get("punctuation") or {}
    if not p.get("enabled"):
        return "- 分段標點：關閉"
    if not p.get("model_ready"):
        return "- 分段標點：只分段（標點模型未安裝，執行 `setup_backend.py --punct-only` 補裝）"
    by = p.get("by_source", {})
    parts = [f"CT-Transformer {by.get('ct', 0)} 段", f"Whisper 標點 {by.get('whisper', 0)} 段"]
    if by.get("mixed"):
        parts.append(f"兩者混合 {by['mixed']} 段")
    if by.get("ct_failed"):
        parts.append(f"CT 對齊失敗改用 Whisper 標點 {by['ct_failed']} 段")
    if by.get("none"):
        parts.append(f"未加標點 {by['none']} 段")
    return (f"- 分段標點：本機（{'、'.join(parts)}；停頓 ≥ {p['paragraph_gap']} s"
            f" 或滿 {p['paragraph_max_chars']} 字換段）")


def write_outputs(out_dir: Path, meta: dict, segs: list, frames: list, paras: list | None = None):
    doc = {"meta": meta}
    if paras is not None:
        doc["paragraphs"] = paras
    doc.update(segments=segs, keyframes=frames)
    (out_dir / "transcript.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    with open(out_dir / "transcript.srt", "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{ts(s['start'], True)} --> {ts(s['end'], True)}\n[{s['speaker']}] {s['text']}\n\n")

    lines = [f"# 逐字稿：{meta['source']}", "",
             f"- 長度：{ts(meta['duration'])}　講者數：{meta['speakers']}　ASR：{meta['model']} @ {meta['device']}"]
    if (meta.get("diarization") or {}).get("setting") != "skip":    # 〔2.0.0 U2〕講者發言時間（一位講者或略過時不印）
        sl = diar.stats_line(meta.get("speaker_stats") or [])
        if sl:
            lines.append(sl)
    lines.append(f"- 處理耗時：{meta['elapsed_sec']:.0f}s（RTF {meta['rtf']:.2f}）")
    fx = meta.get("corrections_applied") or {}
    if fx:
        lines.append("- 對照表自動替換：" + "、".join(f"{k} ×{v}" for k, v in fx.items())
                     + "（原始辨識保留在 transcript.json 的 raw 欄位）")
    if "punctuation" in meta:
        lines.append(punct_header(meta))
    keep_hits = meta.get("opencc_keep_applied") or {}
    if keep_hits:
        lines.append("- OpenCC 詞彙回復：" + "、".join(f"{k} ×{v}" for k, v in keep_hits.items())
                     + "（不讓簡繁轉換改寫這些詞）")
    lines.append("")
    events = [(s["start"], "seg", s) for s in segs] + [(k["time"], "frame", k) for k in frames]
    cur_spk, buf, buf_t, cur_para = None, [], 0.0, None

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
        para = item.get("para")
        if item["speaker"] != cur_spk or (para is not None and para != cur_para):
            flush(); buf.clear()
            cur_spk, buf_t, cur_para = item["speaker"], item["start"], para
        sep = "" if not buf or re.match(r"[一-鿿，。！？、]", item["text"][:1]) else " "
        buf.append(sep + item["text"])
    flush()
    (out_dir / "transcript.md").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- main
def ref_flags(args, auto_correct) -> dict | None:
    """〔2.2.0〕參考資料旗標（規格 2.2.0 §7.3）→ auto_correct.run() 的 refs_opts；一個都沒給回傳 None（＝2.1.0 的呼叫方式）。"""
    ro = auto_correct.ref_options_of(args)
    return ro if (ro["context"] or ro["refs"] or ro["no_refs"] or ro["no_context"] or ro["no_frames"]) else None


def note_refs_without_correct(out_dir: Path, ro: dict):
    """〔2.2.0〕這次沒有做 AI 校正：--context 照樣寫 context.md（寫檔規則在 refs.py），其他旗標只提示沒有作用。"""
    if ro.get("context"):
        try:
            import refs
            p = refs.write_context(out_dir, ro["context"])
            if p:
                log(f"  背景說明已存成 {p.name}（之後的 AI 校正與會議摘要會沿用）")
        except Exception as ex:  # noqa: BLE001
            log(f"  [!] 無法寫入 context.md：{type(ex).__name__}")
    if ro.get("refs") or ro.get("no_refs") or ro.get("no_context") or ro.get("no_frames"):
        log("  [!] --refs／--no-refs／--no-context／--no-frames 只在 AI 校正時使用；這次沒有做 AI 校正")


def main():
    utf8_console()
    print_banner()                     # 〔1.2.0〕第一行顯示版號
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
    ap.add_argument("--type", dest="content_type", default=None,
                    help="〔2.0.0〕內容類型：" + "、".join(content_types.CODES) + "（預設 config.json 的 content_type.default）")
    ap.add_argument("--template", default=None, help="〔2.0.0〕自訂範本代號（$MMH/templates/<代號>.md；類型＝範本的 base）")
    ap.add_argument("--diarize-engine", choices=list(diar.ENGINES), default=None,
                    help="〔2.0.0〕說話者分離引擎（預設 config.json 的 diarization.engine＝auto）")
    ap.add_argument("--speakers", type=int, default=-1,
                    help="講者人數；-1 = 自動。〔2.0.0〕sherpa：自動分群後保留發言最多的 N 位；pyannote：num_speakers=N")
    ap.add_argument("--cluster-threshold", type=float, default=None,
                    help="sherpa 自動分群門檻，越大講者越少（〔2.0.0〕預設依類型：共用 0.9、課程 1.0、座談 0.8）")
    ap.add_argument("--hotwords", help="專有名詞，以逗號或空白分隔")
    ap.add_argument("--hotwords-file", default=str(default_glossary()), help="專有名詞清單檔（一行一個），預設為 runtime 目錄的 glossary.txt")
    ap.add_argument("--no-diarize", action="store_true")
    ap.add_argument("--no-keyframes", action="store_true")
    ap.add_argument("--scene", type=float, default=None, help="畫面變化門檻（0~1；〔2.0.0〕預設依類型：共用 0.3、操作教學 0.1）")
    ap.add_argument("--max-frames", type=int, default=None, help="最多幾張（預設 config.json 的 keyframes.max_frames＝60）")
    ap.add_argument("--no-opencc", action="store_true")
    ap.add_argument("--no-corrections", action="store_true", help="不套用 corrections.tsv")
    ap.add_argument("--no-cues", action="store_true", help="〔2.0.0〕本次不產生 transcript.cues.srt（字幕規則重新切條的字幕）")
    # 本機分段標點（預設取自 config.json 的 punctuation.*；同組開關以後出現的為準）
    ap.add_argument("--punct", dest="punct", action="store_true", default=None, help="本次開啟分段標點")
    ap.add_argument("--no-punct", dest="punct", action="store_false", default=None,
                    help="本次關閉分段標點（段落化回到 1.0.0：同講者連續合併）")
    ap.add_argument("--paragraph-gap", type=float, default=None, help="停頓幾秒以上換段（預設 2.0）")
    ap.add_argument("--paragraph-max-chars", type=int, default=None, help="段落滿幾個字換段（預設 200）")
    ap.add_argument("--no-opencc-keep", dest="opencc_keep", action="store_false", default=None,
                    help="本次不套 OpenCC 詞彙回復表")
    # ④ 自動語意校正（行為由 auto_correct.py 實作；--claude／--openai 是捷徑）
    import auto_correct
    auto_correct.add_cli_options(ap, with_switch=True)
    auto_correct.add_ref_options(ap)                  # 〔2.2.0〕--context／--refs／--no-refs／--no-context／--no-frames（轉給校正）
    ap.add_argument("--local-only", action="store_true",
                    help="〔2.4.0〕本機限定：在輸出資料夾寫入標記檔 local-only.json，這份之後的 AI 校正與摘要都不送出"
                         "（要解除：刪掉標記檔）")
    args = ap.parse_args()
    refs_opts = ref_flags(args, auto_correct)
    punct_on = setting(cfg, "punctuation.enabled") if args.punct is None else args.punct
    gap = setting(cfg, "punctuation.paragraph_gap") if args.paragraph_gap is None else args.paragraph_gap
    max_chars = (setting(cfg, "punctuation.paragraph_max_chars") if args.paragraph_max_chars is None
                 else args.paragraph_max_chars)
    density = setting(cfg, "punctuation.whisper_density")
    keep_on = (not args.no_opencc) and (setting(cfg, "opencc_keep.enabled") if args.opencc_keep is None
                                        else args.opencc_keep)
    correct_consent = args.correct is True          # 命令列明確要求：視為已同意送出逐字稿，略過長會議確認
    args.correct = setting(cfg, "correction.enabled") if args.correct is None else args.correct
    correct_req = None
    if args.correct:
        try:
            correct_req = auto_correct.resolve_request(cfg, args.correct_provider, args.correct_model,
                                                       args.correct_effort, args.correct_channel)
        except auto_correct.OptionError as ex:
            ap.error(str(ex))
    n_steps = 5 if args.correct else 4
    explicit = {a.split("=")[0] for a in sys.argv[1:] if a.startswith("--")}
    try:
        rs = resolve_settings(args, cfg, explicit)
    except SettingsError as ex:
        ap.exit(2, f"{ex}\n")
    tpl, ctype, speakers_setting = rs["template"], rs["content_type"], rs["speakers_setting"]
    threshold, scene, max_frames = rs["cluster_threshold"], rs["scene"], rs["max_frames"]
    if rs["type_note"]:
        warn(f"  [!] {rs['type_note']}")
    prof = cfg.get("profiles", {}).get(args.whisper)
    if prof and not explicit & {"--backend", "--device", "--compute-type"}:
        # 安裝時已為此模型選定後端／裝置（例如 Breeze 在 NPU 失敗時改用 CPU）
        args.backend, args.device = prof["backend"], prof["device"]
        args.compute_type = prof.get("compute_type", "default")
    cfg_read = read_config()                             # 〔2.4.1〕讀不了時：設定用預設值，另印一行警告（規格 2.4.1 §3.3）
    if cfg_read["status"] == "unreadable":
        log(f"  [!] {config_problem_text(cfg_read)}：{cfg_read['path']}。這次的設定都用預設值（暫以 openvino/CPU 執行），"
            "而且當成本機限定（不送 GPT 或 Claude）；請修好它，或刪掉後重新執行安裝程式")
    elif not cfg:
        log("  [!] 找不到 config.json，請先執行 install.cmd；暫以 openvino/CPU 執行")
    if args.backend != cfg.get("backend", "openvino") and args.compute_type == cfg.get("compute_type"):
        args.compute_type = "default"   # 手動換後端時不沿用另一個後端的精度設定

    src = Path(args.input).resolve()
    if not src.exists():
        sys.exit(f"找不到檔案：{src}")
    out_dir = Path(args.out_dir) if args.out_dir else src.with_name(src.stem + "_minutes")
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    import runlog
    rl = runlog.RunLog(out_dir, step="transcribe")      # 〔1.2.0〕執行 log（規格 §11）
    if args.local_only:                                  # 〔2.4.0〕本機限定：先寫標記檔（轉寫中途失敗也已標記）
        import os
        write_local_only_marker(out_dir, os.environ.get("MMP_LOCAL_ONLY_SOURCE") or "transcribe")
    local_only = local_only_state(out_dir, cfg)
    refused = None
    if local_only:
        rl.privacy(local_only)
        why = local_only_why(local_only, out_dir)        # 〔2.4.1〕config 讀不了時寫出原因；其他來源照 2.4.0 的短稱
        labels = [{"config": "config.json", "marker": "標記檔"}.get(x, why[i]) for i, x in enumerate(local_only["sources"])]
        log(f"本機限定（{'、'.join(labels)}）：不會送出任何資料到 GPT 或 Claude")
        if args.correct:                                 # 管線內的 AI 校正不執行（規格 2.4.0 §2.3）
            refused = local_only_message(local_only, "AI 校正", out_dir)
            args.correct = False
            n_steps = 4
    if tpl:                                              # 〔2.0.0〕只記代號與驗證結果，不記範本內容（規格 §6.4）
        rl.event("template", code=args.template, base=tpl.get("base"), valid=True,
                 prompt_chars=tpl.get("prompt_chars"), prompt_truncated=tpl.get("prompt_truncated"))

    log(f"[1/{n_steps}] 轉換音訊 16kHz mono")
    wav = out_dir / "audio16k.wav"
    h = rl.begin("convert_audio")
    to_wav(src, wav)
    audio, sr = sf.read(str(wav), dtype="float32")
    assert sr == SR
    duration = len(audio) / SR
    rl.end(h, recording_sec=round(duration, 2))
    log(f"  長度 {ts(duration)}")

    frames = []
    if src.suffix.lower() in VIDEO_EXT and not args.no_keyframes:
        log("[*] 擷取影片關鍵畫面")
        h = rl.begin("keyframes")
        frames = extract_keyframes(src, out_dir / "frames", scene, max_frames)
        rl.end(h, frames=len(frames), scene=scene)
        log(f"  {len(frames)} 張")

    if speakers_setting == "skip":
        turns = [[0.0, duration, "S?"]]
        dmeta = {"engine": "none", "device": None, "gpu_name": None, "engine_reason": None, "fallback": None,
                 "setting": "skip", "n": None, "cluster_threshold": None, "speakers_raw": None, "speakers": 1,
                 "top_n_merged_sec": 0.0, "pyannote": None}
    else:
        n = speakers_setting if isinstance(speakers_setting, int) else None
        choice = diar.choose_engine(cfg, args.diarize_engine, ctype=ctype)   # 〔2.0.0〕依類型選引擎
        log(f"[2/{n_steps}] 說話者分離（{'pyannote／GPU' if choice['engine'] == 'pyannote' else 'sherpa／CPU'}）")
        h = rl.begin("diarize")
        dres = diar.run(choice, audio, wav, out_dir, duration, n, threshold, cfg, log=log, warn=warn)
        # 〔2.0.0〕ASR 在分離之後才載入；pyannote 子行程此時已結束（GPU 已釋放，規格 §4.2.4）
        turns = [[s, e, f"S{spk + 1}"] for s, e, spk in merge_turns(dres["segs"])]
        if not turns:
            turns = [[0.0, duration, "S?"]]
        dmeta = dres["meta"]
        dmeta["speakers"] = len({t[2] for t in turns})
        rl.end(h, turns=len(turns), speakers=dmeta["speakers"], engine=dmeta["engine"], device=dmeta["device"],
               fallback=dmeta["fallback"], speakers_raw=dmeta["speakers_raw"], pyannote_sec=dres["pyannote_sec"])
    speakers = len({t[2] for t in turns})
    stats = diar.speaker_stats(turns, float(setting(cfg, "diarization.minor_speaker_note_sec")))
    log(f"  {len(turns)} 段、{speakers} 位講者")
    minor = [st["speaker"] for st in stats if st["minor"]] if speakers_setting != "skip" and speakers > 1 else []
    if minor:
        log(f"  講者 {'、'.join(minor)} 發言很少，可能是分離誤判（見 transcript.md 表頭）")

    log(f"[3/{n_steps}] 語音辨識（{args.backend} / {args.device}）")
    # 〔2.5.0〕breeze26（ct2）有說話者分離時開 vad_filter；只在開的時候多記一欄（規格 2.5.0 §6）
    vad_on = asr_vad_filter(args.whisper, args.backend, diarized=speakers_setting != "skip")
    vad_kw = {"vad_filter": True} if vad_on else {}
    if args.whisper == "breeze26" and speakers_setting == "skip":
        warn(f"  [!] {BREEZE26_NO_DIAR_NOTE}")
    h_asr = rl.begin("asr", backend=args.backend, device=args.device, asr_model=args.whisper, **vad_kw)
    hot = args.hotwords or ""
    if args.hotwords_file and Path(args.hotwords_file).exists():
        hot += " " + " ".join(l.strip() for l in Path(args.hotwords_file).read_text(encoding="utf-8").splitlines()
                              if l.strip() and not l.startswith("#"))
    corrector = None
    if not args.no_corrections:
        from corrections import Corrector, load as load_corrections
        corrector = Corrector(load_corrections())
        hot += " " + " ".join(corrector.right_terms())   # 對照表的正確寫法也當成辨識提示
    terms = [t for t in re.split(r"[,，\s]+", hot) if t]
    hot = ", ".join(dict.fromkeys(terms)) or None
    lang = None if args.language == "auto" else args.language
    cc = None
    if not args.no_opencc:
        from opencc import OpenCC
        cc = OpenCC("s2twp")
    keep = None
    if cc and keep_on:
        from opencc_keep import load_table
        keep = load_table()
    # 專有名詞維持 glossary 原樣（避免 OpenCC 改寫），再套台灣慣用字
    protect = {}
    for w in (hot or "").split(", "):
        if w and cc and cc.convert(w) != w:
            protect[cc.convert(w)] = w
    protect.update(TW_PREFER)
    asr = load_asr(args.backend, args.whisper, args.device, args.compute_type, lang, hot, vad_filter=vad_on)
    dev = f"{args.backend}/{args.device}"

    out = []
    fixed_total = {}
    keep_total = {}
    t_asr = time.time()
    done_sec = 0.0
    for i, (s, e, spk) in enumerate(turns, 1):
        for ws, we in split_long(audio, s, e):
            a, b = max(0, int((ws - 0.15) * SR)), min(len(audio), int((we + 0.15) * SR))
            text, kh = clean(asr.transcribe(audio[a:b]), cc, protect, keep)
            if not text:
                continue
            for k, n in kh.items():
                keep_total[k] = keep_total.get(k, 0) + n
            seg = {"start": round(ws, 2), "end": round(we, 2), "speaker": spk, "text": text}
            if corrector:
                new, fixes = corrector.apply(text)
                if fixes:
                    seg.update(text=new, raw=text, fixes=fixes)   # 保留原始辨識結果以便查證
                    for w, r, n in fixes:
                        fixed_total[f"{w}→{r}"] = fixed_total.get(f"{w}→{r}", 0) + n
            out.append(seg)
        done_sec += e - s
        if i % 10 == 0 or i == len(turns):
            el = time.time() - t_asr
            eta = el / max(done_sec, 1e-6) * (duration - done_sec)
            log(f"  {i}/{len(turns)} 段，已處理 {ts(done_sec)}，預估剩餘 {ts(max(eta, 0))}")

    rl.end(h_asr, turns=len(turns), segments=len(out))
    log(f"[4/{n_steps}] 輸出檔案")
    from punctuate import Punctuator, build_paragraphs, punctuate_paragraphs
    t_p = time.time()
    h = rl.begin("punctuate", enabled=bool(punct_on))
    paras = build_paragraphs(out, frames, gap, max_chars, punct_on)   # ② 分段
    for k, p in enumerate(paras):
        for i in range(p["segments"][0], p["segments"][1] + 1):
            out[i]["para"] = k
    pmeta = {"enabled": bool(punct_on)}
    if punct_on:                                                     # ③ 標點
        punctuator = None
        if punct_ready():
            try:
                punctuator = Punctuator(punct_model(), THREADS)
            except Exception as ex:  # noqa: BLE001
                log(f"  [!] 標點模型載入失敗，改用 Whisper 標點：{str(ex)[:120]}")
        else:
            log("  [!] 標點模型未安裝：只分段（執行 setup_backend.py --punct-only 補裝）")
        st = punctuate_paragraphs(paras, out, args.whisper, punctuator, density)
        p_el = time.time() - t_p
        pmeta.update(model=setting(cfg, "punctuation.model"), model_ready=punctuator is not None,
                     paragraph_gap=gap, paragraph_max_chars=max_chars, whisper_density=density,
                     paragraphs=len(paras), by_source=st["by_source"], by_segment=st["by_segment"],
                     elapsed_sec=round(p_el, 3))
        by = st["by_source"]
        log(f"  分段標點：{len(paras)} 段（CT {by['ct']}、Whisper {by['whisper']}"
            + (f"、混合 {by['mixed']}" if by.get("mixed") else "")
            + (f"、CT 對齊失敗 {by['ct_failed']}" if by["ct_failed"] else "")
            + (f"、未加標點 {by['none']}" if by["none"] else "") + f"），{p_el:.1f}s")
    rl.end(h, paragraphs=len(paras))
    h = rl.begin("write_outputs")
    for s in out:   # 欄位順序：時間、講者、段落、文字、加標點前、對照表前
        tail = {k: s.pop(k) for k in ("text", "text_plain", "raw", "fixes") if k in s}
        s.update(tail)
    elapsed = time.time() - t_start
    meta = {"version": VERSION, "source": src.name, "duration": round(duration, 2), "device": dev,
            "model": args.whisper, "language": args.language, "speakers": speakers,
            "elapsed_sec": round(elapsed, 1), "rtf": elapsed / max(duration, 1e-6), "hotwords": hot,
            "corrections_applied": fixed_total, "punctuation": pmeta, "opencc_keep_applied": keep_total,
            # 〔2.0.0〕只新增欄位（規格 §2.1、§4.8）
            "content_type": ctype, "template": args.template, "diarization": dmeta, "speaker_stats": stats,
            **vad_kw}                                               # 〔2.5.0〕breeze26（ct2）才有 vad_filter 欄
    write_outputs(out_dir, meta, out, frames, paras)
    wav.unlink(missing_ok=True)
    rl.end(h, files=["transcript.json", "transcript.md", "transcript.srt"])
    try:                                                              # 〔2.0.0 I-3〕字幕（規格 §5.1）；失敗不影響轉寫
        import subtitles
        cues_res = subtitles.write_cues(out_dir, cfg, enabled=False if args.no_cues else None, run_log=rl, log=log)
    except Exception as ex:  # noqa: BLE001  write_cues() 本身不丟例外；這裡防模組載入失敗
        cues_res = {"status": "error", "reason": type(ex).__name__}
        log(f"  [!] 字幕：transcript.cues.srt 產生失敗（{type(ex).__name__}）；轉寫結果不受影響")
    rl.event("info", source=src.name, recording_sec=round(duration, 2), segments=len(out), paragraphs=len(paras),
             speakers=speakers, asr_model=args.whisper, device=dev,
             content_type=ctype, template=args.template, speakers_setting=speakers_setting,
             cluster_threshold=dmeta["cluster_threshold"], speakers_raw=dmeta["speakers_raw"],
             diarize_engine=dmeta["engine"], diarize_device=dmeta["device"],
             diarize_engine_reason=dmeta["engine_reason"], diarize_fallback=dmeta["fallback"])
    rl.event("result", status="ok", frames=len(frames))
    correction, subs = None, {"cues": cues_res}
    if refs_opts and not args.correct:                                # 〔2.2.0〕沒有校正：--context 仍寫 context.md
        note_refs_without_correct(out_dir, refs_opts)
    if refused:                                                       # 〔2.4.0〕本機限定：拒絕送出
        log(f"  [!] {refused}")
        rl.event("result", step="correct", status="skipped", reason="local_only")
        correction = {"status": "skipped", "reason": "local_only", "provider": None, "model": None, "channel": None,
                      "chunks": 0, "chunks_ok": 0, "fallback": None}
    if args.correct:                                                  # ④ 失敗不影響轉寫的 exit code
        kw = {"refs_opts": refs_opts} if refs_opts else {}   # 〔2.2.0〕沒給參考資料旗標時呼叫方式與 2.1.0 相同
        cr = auto_correct.run(out_dir, correct_req, interactive=sys.stdin.isatty(), consent=correct_consent,
                              in_pipeline=True, cfg=cfg, run_log=rl, **kw)
        correction = {k: cr.get(k) for k in ("status", "reason", "provider", "model", "channel", "chunks", "chunks_ok",
                                             "fallback")}
        if cr.get("subtitles"):
            subs["corrected"] = cr["subtitles"]
    lo_field = {"local_only": local_only["source"]} if local_only else {}     # 〔2.4.0〕只在本機限定時多這一欄
    print(json.dumps({"out_dir": str(out_dir), "transcript_md": str(out_dir / "transcript.md"),
                      "segments": len(out), "speakers": speakers, "keyframes": len(frames),
                      "device": dev, "model": args.whisper, "corrections_applied": sum(fixed_total.values()),
                      "paragraphs": len(paras), "opencc_keep_applied": sum(keep_total.values()),
                      "elapsed_sec": round(elapsed, 1), "version": VERSION, "correction": correction,
                      "duration": round(duration, 2), "run_id": rl.run_id, "run_log": str(rl.path),   # 〔1.2.0〕新欄位
                      "content_type": ctype, "diarize_engine": dmeta["engine"],               # 〔2.0.0〕新欄位
                      "diarize_fallback": dmeta["fallback"], "subtitles": subs, **lo_field},
                     ensure_ascii=False))
    if rl.owns:
        rl.finish()
    if refused and correct_consent:                   # 〔2.4.0〕命令列明確要求校正卻是本機限定：轉寫照常，exit 6
        sys.exit(LOCAL_ONLY_EXIT)


if __name__ == "__main__":
    main()
