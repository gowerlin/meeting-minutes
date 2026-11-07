"""1.0.0 的 transcript.md／transcript.srt／transcript.json 輸出函式（固定夾具）。

由 meeting-minutes-pro-v1.0.0/payload/runtime/scripts/transcribe.py 的 ts()、write_outputs() 原樣複製，
給 test_regression.py 的 R 回歸用：公開 repo 只放最新版目錄，沒有 1.0.0 目錄也能比對。
不要修改：有 1.0.0 目錄時，test_regression.py 會檢查這兩個函式和原檔相同（AST 比對）。
"""
import json
import re
from pathlib import Path


def ts(sec: float, srt: bool = False) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if srt:
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"


def write_outputs(out_dir: Path, meta: dict, segs: list, frames: list):
    (out_dir / "transcript.json").write_text(
        json.dumps({"meta": meta, "segments": segs, "keyframes": frames}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    with open(out_dir / "transcript.srt", "w", encoding="utf-8") as f:
        for i, s in enumerate(segs, 1):
            f.write(f"{i}\n{ts(s['start'], True)} --> {ts(s['end'], True)}\n[{s['speaker']}] {s['text']}\n\n")

    lines = [f"# 逐字稿：{meta['source']}", "",
             f"- 長度：{ts(meta['duration'])}　講者數：{meta['speakers']}　ASR：{meta['model']} @ {meta['device']}",
             f"- 處理耗時：{meta['elapsed_sec']:.0f}s（RTF {meta['rtf']:.2f}）"]
    fx = meta.get("corrections_applied") or {}
    if fx:
        lines.append("- 對照表自動替換：" + "、".join(f"{k} ×{v}" for k, v in fx.items())
                     + "（原始辨識保留在 transcript.json 的 raw 欄位）")
    lines.append("")
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
