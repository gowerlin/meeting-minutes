"""〔2.0.0〕字幕（subtitles.py；規格 §5）的測試與計分。

單元測試（python -B -m unittest test_subtitles；不呼叫任何模型、不需要 GPU）：
  - 對應（S-1 的單元層級）：修改、刪除整段、補字、跨段標記、S? 拆段（段界／段內）、姓名段首、文件層級、手改標記外文字只退回那一段、全部失敗。
  - 字幕規則（S-2 的單元層級）：每行 ≤ 16、最多 2 行、行尾沒有「，、。」、行中句號改全形空白、一條不跨辨識段、
    段首時間＝辨識段開頭、太長再切、太短併同講者、講者標籤 change／always／none、SRT 格式。
  - U5／U6（S-3）：transcript.srt 與 1.2.2 的 write_outputs() 逐位元相同；cues 在 recue: false 時不產生；[?…] 三種顯示。
  - 失敗退回（§5.6）：壞掉的 transcript.json → status error、不丟例外、刪掉過時的字幕；meta 只改 subtitles 鍵。
  - 接線：transcribe.main()（假 ASR／分離）產生 transcript.cues.srt、--no-cues、log 檢查點；auto_correct.run()／main()
    產生 transcript.corrected.srt、--no-corrected-srt、字幕失敗時校正照常 ok。

計分（研究原型 research/content-modes/srt_map.py、cue_timing.py 移來的長期邏輯；研究目錄不改）：
  python -B test_subtitles.py map <資料夾> [...]                 # S-1：每個資料夾（transcript.json＋transcript.corrected.md）的對應結果
  python -B test_subtitles.py rules <srt 檔> [...]               # S-2：條數、超過 16 字的行、行尾標點、超過 7 秒、不足 5/6 秒、每秒字數
  python -B test_subtitles.py timing <素材> <srt 檔> [...]        # S-2：段首時間誤差（基準 tests/_out/<素材>.ref.json）
  python -B test_subtitles.py derive <來源資料夾> <目的資料夾> names|merged|edited   # 由一份校正版做出 S-1 的變化案例
"""
import contextlib
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _testenv

V2 = _testenv.VER >= (2, 0, 0)
HERE = Path(__file__).resolve().parent
SCRIPTS_122 = HERE.parent / "meeting-minutes-pro-v1.2.2" / "payload" / "runtime" / "scripts"
if V2:
    import auto_correct as ac
    import runlog
    import subtitles as sb

TS_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)")


# ---------------------------------------------------------------- 計分工具（研究原型移來）
def read_srt(path: Path) -> list:
    """[{start, end, label, lines}]（講者標籤從第一行拿掉）。"""
    cues = []
    text = Path(path).read_text(encoding="utf-8")
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        m = TS_RE.search(block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        s = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        e = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        body = lines[2:]
        label = None
        if body:
            lm = re.match(r"^\[([^\]]+)\] ", body[0])
            if lm:
                label, body[0] = lm.group(1), body[0][lm.end():]
        cues.append({"start": s, "end": e, "label": label, "lines": body})
    return cues


def width(s: str) -> float:
    return sum(0.5 if ord(c) < 0x2E80 else 1 for c in s)


def content_of(s: str) -> str:
    import auto_correct
    return auto_correct.content_of(s)


def rule_stats(path: Path, max_line=16, max_lines=2, min_sec=0.833, max_sec=7.0, cps=9.0) -> dict:
    """S-2 規則統計（比例為 0～1；cue_timing／srt_map.cue_stats 的計法，行寬不含講者標籤）。"""
    cues = read_srt(path)
    lines = [ln for c in cues for ln in c["lines"]]
    durs = [c["end"] - c["start"] for c in cues]
    speed = [width(content_of("".join(c["lines"]))) / max(d, 0.01) for c, d in zip(cues, durs)]
    n, nl = max(len(cues), 1), max(len(lines), 1)
    return {"srt": Path(path).parent.name + "/" + Path(path).name, "cues": len(cues),
            "line_over": round(sum(width(ln) > max_line for ln in lines) / nl, 4),
            "lines_over": round(sum(len(c["lines"]) > max_lines for c in cues) / n, 4),
            "line_end_punct": sum(bool(re.search(r"[，、。]$", ln)) for ln in lines),
            "too_long": round(sum(d > max_sec + 1e-3 for d in durs) / n, 4),
            "too_short": round(sum(d < min_sec - 1e-3 for d in durs) / n, 4),
            "cps_over": round(sum(s > cps for s in speed) / n, 4),
            "max_width": max((width(ln) for ln in lines), default=0)}


def timing(ref_path: Path, srt_path: Path) -> dict:
    """段首時間誤差（cue_timing.py）：基準每段第一個字真正開始的時間 vs 字幕估到的時間（條內依內容字元平均分配）。"""
    ref = json.loads(Path(ref_path).read_text(encoding="utf-8"))
    rc, starts = "", []
    for p in ref["paragraphs"]:
        starts.append((len(rc), p["start"]))
        rc += content_of(p["text"])
    hc, ctime = "", []
    for c in read_srt(srt_path):
        t = content_of("".join(c["lines"]))
        for k in range(len(t)):
            ctime.append(c["start"] + (c["end"] - c["start"]) * k / max(len(t), 1))
        hc += t
    sm = difflib.SequenceMatcher(None, rc, hc, autojunk=False)
    r2h = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            r2h[a + k] = b + k
    errs = []
    for pos, t in starts:
        for d in range(4):
            if pos + d in r2h:
                errs.append(abs(ctime[r2h[pos + d]] - t))
                break
    errs.sort()
    if not errs:
        return {"srt": str(srt_path), "matched": 0}
    return {"srt": Path(srt_path).parent.name + "/" + Path(srt_path).name, "paragraphs": len(starts),
            "matched": len(errs), "err_median_sec": round(errs[len(errs) // 2], 2),
            "err_p90_sec": round(errs[int(len(errs) * 0.9)], 2), "err_max_sec": round(errs[-1], 2),
            "over_1s": round(sum(e > 1 for e in errs) / len(errs), 3)}


def map_case(d: Path, mode: str = "orig") -> dict:
    """S-1：一個資料夾的對應結果（subtitles.map_corrected）。"""
    doc = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
    cor = (d / "transcript.corrected.md").read_text(encoding="utf-8")
    cues, st = sb.map_corrected(doc, cor, mode)
    body = cor.split("\n---\n", 1)[-1]                       # 只算本文（表頭的校正摘要、待確認清單不算）
    marks = list(ac.MARK_RE.finditer(body))
    return {"case": d.name, "segments": len(doc["segments"]), "paragraphs": st["paragraphs"],
            "edits": sum(1 for m in marks if m.group(1) is not None or m.group(2) is not None),
            "uncertain": sum(1 for m in marks if m.group(1) is None and m.group(2) is None),
            "s_heads": len(re.findall(r"^\*\*\[[^\]]+\] S\?\*\*：", body, re.M)),
            "split_in_segment": st["split_in_segment"], "cross_segment_marks": st["cross_segment_marks"],
            "map_failed_paragraphs": st["map_failed_paragraphs"], "doc_level": st["doc_level"],
            "map_failed": st["map_failed"], "deleted_segments": st["deleted_segments"],
            "changed_segments": st["changed_segments"]}


def derive(src: Path, dst: Path, kind: str) -> dict:
    """由一份校正版做出 S-1 的變化案例（2.0.0 研究的後三種變化）：
    names＝段首改「姓名（S#）」（模擬對話補校）；merged＝把第 2、3 個段落合併成一段（段首對不上 → 文件層級）；
    edited＝第一個「標記外有 4 個以上內容字元」的段落裡，把標記外的一個字改掉（模擬手改標記外文字 → 該段對應失敗）。"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.srt", "run_log.jsonl"))
    p = dst / "transcript.corrected.md"
    head, body = p.read_text(encoding="utf-8").split("\n---\n", 1)
    lines = body.split("\n")
    heads = [i for i, ln in enumerate(lines) if sb.HEAD.match(ln)]
    info = {"kind": kind}
    if kind == "names":
        names = {"S1": "陳怡君", "S2": "林志明", "S3": "王雅婷", "S4": "張家豪"}
        n = 0
        for i in heads:
            m = sb.HEAD.match(lines[i])
            if m.group(2) in names:
                lines[i] = f"**[{m.group(1)}] {names[m.group(2)]}（{m.group(2)}）**：" + lines[i][m.end():]
                n += 1
        info["renamed"] = n
    elif kind == "merged":
        i2, i3 = heads[1], heads[2]
        m3 = sb.HEAD.match(lines[i3])
        lines[i2] = lines[i2] + lines[i3][m3.end():]
        del lines[i3]
        info["merged"] = [sb.HEAD.match(lines[i2]).group(1), m3.group(1)]
    elif kind == "edited":
        for i in heads:
            m = sb.HEAD.match(lines[i])
            text = lines[i][m.end():]
            plain = ac.MARK_RE.sub("", text)
            cands = [k for k, ch in enumerate(text) if content_of(ch) and not any(
                mm.start() <= k < mm.end() for mm in ac.MARK_RE.finditer(text))]
            if len(content_of(plain)) >= 4 and cands:
                k = cands[len(cands) // 2]
                text = text[:k] + ("甲" if text[k] != "甲" else "乙") + text[k + 1:]
                lines[i] = lines[i][:m.end()] + text
                info["edited_paragraph"] = m.group(1)
                break
    else:
        raise SystemExit(f"unknown kind {kind}")
    p.write_text(head + "\n---\n" + "\n".join(lines), encoding="utf-8", newline="\n")
    return info


# ---------------------------------------------------------------- 測試資料
def seg(start, end, spk, text, para=None):
    s = {"start": start, "end": end, "speaker": spk, "text": text}
    if para is not None:
        s["para"] = para
    return s


def write_doc(d: Path, segs: list, frames=None, corrected: str | None = None):
    """用 2.0.0 transcribe.write_outputs() 寫 transcript.json／md／srt（段落規則與產品相同）。"""
    import transcribe as tr
    meta = {"version": "2.0.0", "source": "demo.wav", "duration": max(s["end"] for s in segs), "device": "ct2/cpu",
            "model": "turbo", "speakers": len({s["speaker"] for s in segs}), "elapsed_sec": 1.0, "rtf": 0.1,
            "diarization": {"setting": "auto"}, "speaker_stats": []}
    with contextlib.redirect_stderr(io.StringIO()):
        tr.write_outputs(d, meta, [dict(s) for s in segs], frames or [])
    if corrected is not None:
        (d / "transcript.corrected.md").write_text("# 校正版逐字稿：demo.wav\n\n> 原始逐字稿\n\n---\n\n" + corrected,
                                                  encoding="utf-8", newline="\n")


def para_line(t, spk, text):
    return f"**[{t}] {spk}**：{text}\n\n"


SEGS = [
    seg(0.0, 4.0, "S1", "今天我們來討論卡夫卡的設定，", 0),
    seg(4.0, 9.5, "S1", "還有延持的問題要先處理。", 0),
    seg(10.0, 14.0, "S2", "我這邊已經查過了謝謝觀看", 1),
    seg(14.2, 20.0, "S2", "延持主要是網路造成的，下週會修好。", 1),
    seg(21.0, 26.0, "S1", "好，那就這樣決定。", 2),
]


def mapped(segs, corrected, mode="orig"):
    with tempfile.TemporaryDirectory(prefix="mmp-sub-") as t:
        d = Path(t)
        write_doc(d, segs, corrected=corrected)
        doc = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
        return sb.map_corrected(doc, (d / "transcript.corrected.md").read_text(encoding="utf-8"), mode)


O = sb.options({}) if V2 else {}


# ---------------------------------------------------------------- 對應
@unittest.skipUnless(V2, "2.0.0 才有")
class Mapping(unittest.TestCase):
    def test_edits_delete_insert(self):
        cor = (para_line("00:00:00", "S1", "今天我們來討論{卡夫卡→Kafka}的設定，還有{延持→延遲}的問題要先處理。")
               + para_line("00:00:10", "S2", "我這邊已經查過了{謝謝觀看→}{延持→延遲}主要是網路造成的，下週會修好{→了}。")
               + para_line("00:00:21", "S1", "好，那就這樣決定。"))
        cues, st = mapped(SEGS, cor)
        texts = [c["text"] for c in cues]
        self.assertEqual(texts[0], "今天我們來討論Kafka的設定，")
        self.assertEqual(texts[1], "還有延遲的問題要先處理。")
        self.assertEqual(texts[2], "我這邊已經查過了")
        self.assertEqual(texts[3], "延遲主要是網路造成的，下週會修好了。")
        self.assertEqual((st["map_failed_paragraphs"], st["doc_level"], st["cross_segment_marks"]), (0, False, 0))
        self.assertEqual(st["changed_segments"], 4)

    def test_whole_segment_deleted_is_dropped(self):
        segs = [seg(0, 3, "S1", "請大家先坐好。", 0), seg(3, 5, "S1", "謝謝觀看", 0), seg(5, 9, "S1", "我們開始吧。", 0)]
        cues, st = mapped(segs, para_line("00:00:00", "S1", "請大家先坐好。{謝謝觀看→}我們開始吧。"))
        self.assertEqual([c["text"] for c in cues], ["請大家先坐好。", "我們開始吧。"])
        self.assertEqual(st["deleted_segments"], 1)

    def test_cross_segment_mark(self):
        cor = (para_line("00:00:00", "S1", "今天我們來討論卡夫卡的{設定，還有→設定與}延持的問題要先處理。")
               + para_line("00:00:10", "S2", "我這邊已經查過了謝謝觀看延持主要是網路造成的，下週會修好。")
               + para_line("00:00:21", "S1", "好，那就這樣決定。"))
        cues, st = mapped(SEGS, cor)
        self.assertEqual(st["cross_segment_marks"], 1)
        self.assertEqual(cues[0]["text"], "今天我們來討論卡夫卡的設定與")       # 替換文字放在起點那段
        self.assertEqual(cues[1]["text"], "延持的問題要先處理。")
        self.assertEqual(st["map_failed_paragraphs"], 0)

    def test_split_at_boundary_and_inside(self):
        cor = (para_line("00:00:00", "S1", "今天我們來討論卡夫卡的設定，")
               + para_line("00:00:00", "S?", "還有延持的問題要先處理。")                # 拆點在段界 → 第 2 段改 S?
               + para_line("00:00:10", "S2", "我這邊已經查過了謝謝")
               + para_line("00:00:10", "S?", "觀看延持主要是網路造成的，下週會修好。")    # 拆點在段內
               + para_line("00:00:21", "S1", "好，那就這樣決定。"))
        cues, st = mapped(SEGS, cor)
        # 拆點所在的 segment（第 3 條）保留原講者；開頭落在 S? 段裡的下一個 segment 改 S?
        self.assertEqual([c["spk"] for c in cues], ["S1", "S?", "S2", "S?", "S1"])
        self.assertEqual(st["split_in_segment"], 1)
        self.assertEqual(st["map_failed_paragraphs"], 0)

    def test_names_label(self):
        cor = (para_line("00:00:00", "陳怡君（S1）", "今天我們來討論卡夫卡的設定，還有延持的問題要先處理。")
               + para_line("00:00:10", "S2", "我這邊已經查過了謝謝觀看延持主要是網路造成的，下週會修好。")
               + para_line("00:00:21", "陳怡君（S1）", "好，那就這樣決定。"))
        cues, st = mapped(SEGS, cor)
        self.assertEqual([c["label"] for c in cues], ["陳怡君", "陳怡君", "S2", "S2", "陳怡君"])
        self.assertEqual([c["spk"] for c in cues], ["S1", "S1", "S2", "S2", "S1"])
        self.assertFalse(st["doc_level"])

    def test_merged_paragraphs_doc_level(self):
        cor = (para_line("00:00:00", "S1", "今天我們來討論{卡夫卡→Kafka}的設定，還有延持的問題要先處理。"
                                           "我這邊已經查過了謝謝觀看延持主要是網路造成的，下週會修好。")
               + para_line("00:00:21", "S1", "好，那就這樣決定。"))
        cues, st = mapped(SEGS, cor)
        self.assertTrue(st["doc_level"])
        self.assertEqual((st["map_failed_paragraphs"], st["map_failed"]), (0, False))
        self.assertEqual(cues[0]["text"], "今天我們來討論Kafka的設定，")
        self.assertEqual([c["spk"] for c in cues], ["S1", "S1", "S2", "S2", "S1"])   # 文件層級不改講者

    def test_literal_edit_fails_only_that_paragraph(self):
        cor = (para_line("00:00:00", "S1", "今天我們來討論{卡夫卡→Kafka}的設定，還有延持的問題要先處理。")
               + para_line("00:00:10", "S2", "我這邊已經查過了謝謝觀看延持主要是網路導致的，下週會修好。")   # 標記外手改
               + para_line("00:00:21", "S1", "好，那就這樣決定。"))
        cues, st = mapped(SEGS, cor)
        self.assertEqual(st["map_failed_paragraphs"], 1)
        self.assertEqual(cues[0]["text"], "今天我們來討論Kafka的設定，")
        self.assertEqual(cues[3]["text"], SEGS[3]["text"])                       # 該段用原文

    def test_document_level_failure_all_original(self):
        cor = para_line("00:00:05", "S9", "完全不同的內容。")
        cues, st = mapped(SEGS, cor)
        self.assertTrue(st["map_failed"] and st["doc_level"])
        self.assertEqual([c["text"] for c in cues], [s["text"] for s in SEGS])

    def test_frames_and_notes_skipped(self):
        segs = [seg(0, 4, "S1", "先看這個畫面。", 0), seg(6, 10, "S1", "接著按下儲存。", 1)]
        cor = (para_line("00:00:00", "S1", "先看這個畫面。") + "> 🖼 [00:00:05] 畫面：`frame_0001.jpg`\n\n"
               + "> ⚠ 以下 1 段未自動校正（原因：timeout）\n\n" + para_line("00:00:06", "S1", "接著按下{儲存→存檔}。"))
        with tempfile.TemporaryDirectory(prefix="mmp-sub-") as t:
            d = Path(t)
            write_doc(d, segs, frames=[{"time": 5.0, "file": "frames/frame_0001.jpg"}], corrected=cor)
            doc = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
            cues, st = sb.map_corrected(doc, (d / "transcript.corrected.md").read_text(encoding="utf-8"))
        self.assertEqual([c["text"] for c in cues], ["先看這個畫面。", "接著按下存檔。"])
        self.assertEqual(st["map_failed_paragraphs"], 0)

    def test_english_segments_join_with_space(self):
        segs = [seg(0, 3, "S1", "我們用", 0), seg(3, 6, "S1", "Grafana dashboard 看", 0), seg(6, 9, "S1", "狀態。", 0)]
        cues, st = mapped(segs, para_line("00:00:00", "S1", "我們用 {Grafana→Grafana} dashboard 看狀態。"))
        self.assertEqual([c["text"] for c in cues], ["我們用", "Grafana dashboard 看", "狀態。"])
        self.assertEqual(st["map_failed_paragraphs"], 0)


@unittest.skipUnless(V2, "2.0.0 才有")
class Uncertain(unittest.TestCase):
    """U6（規格 §5.5）：orig／guess／mark。"""
    COR = (para_line("00:00:00", "S1", "今天我們來討論[?卡夫卡｜Kafka]的設定，還有[?延持]的問題要先處理。")
           + para_line("00:00:10", "S2", "我這邊已經查過了謝謝觀看延持主要是網路造成的，下週會修好。")
           + para_line("00:00:21", "S1", "好，那就這樣決定。"))

    def test_three_modes(self):
        want = {"orig": ("卡夫卡", "延持"), "guess": ("Kafka", "延持"), "mark": ("卡夫卡〔?Kafka〕", "延持〔?〕")}
        for mode, (a, b) in want.items():
            with self.subTest(mode=mode):
                cues, st = mapped(SEGS, self.COR, mode)
                self.assertEqual(cues[0]["text"], f"今天我們來討論{a}的設定，")
                self.assertEqual(cues[1]["text"], f"還有{b}的問題要先處理。")

    def test_cli_override(self):
        with tempfile.TemporaryDirectory(prefix="mmp-sub-") as t:
            d = Path(t)
            write_doc(d, SEGS, corrected=self.COR)
            r = sb.write_corrected(d, {"subtitles": {"uncertain": "orig"}}, uncertain="mark", log=lambda m: None)
            self.assertEqual((r["status"], r["uncertain"]), ("ok", "mark"))
            srt = (d / sb.CORRECTED_NAME).read_text(encoding="utf-8")
            self.assertIn("〔?Kafka〕", srt)                                 # 標記中間不斷行、「?」不被當成切點
            self.assertIn("卡夫卡〔?Kafka〕", srt.replace("\n", ""))
            r = sb.write_corrected(d, {"subtitles": {"uncertain": "guess"}}, log=lambda m: None)
            srt = (d / sb.CORRECTED_NAME).read_text(encoding="utf-8")
            self.assertIn("Kafka", srt)
            self.assertNotIn("〔?", srt)


# ---------------------------------------------------------------- 字幕規則
LONG = [
    seg(0.0, 12.0, "S1", "這個參數目前寫在設定檔裡面，可以在Grafana的面板上看到狀態。另外我們還要確認一下，"
                         "測試環境的資料庫連線數量是不是足夠，如果不夠的話要先跟維運部門申請。", 0),
    seg(12.0, 12.5, "S1", "好。", 0),
    seg(13.0, 16.0, "S2", "了解，我下午就去申請。", 1),
    seg(16.0, 40.0, "S2", "這段話完全沒有標點符號所以只能硬切但是每一條還是要符合字幕規則每行不超過十六個字而且最多兩行", 1),
    seg(41.0, 60.0, "S1", "接下來", 2),
]


@unittest.skipUnless(V2, "2.0.0 才有")
class Rules(unittest.TestCase):
    def cues(self, segs=LONG, **ov):
        o = sb.options({}, **ov)
        return sb.recue(sb.segment_cues({"segments": segs}), o), o

    def test_line_width_lines_and_punct(self):
        cues, o = self.cues()
        for c in cues:
            self.assertLessEqual(len(c["lines"]), 2, c)
            for ln in c["lines"]:
                self.assertLessEqual(sb.width(ln), 16, ln)
                self.assertNotRegex(ln, r"[，、。]$")
                self.assertNotIn("。", ln)
        self.assertEqual(sb.clean_line("好了。我們走，"), "好了　我們走")           # 行中句號 → 全形空白、行尾標點拿掉
        self.assertEqual(sb.clean_line("真的嗎？"), "真的嗎？")                     # 問號保留
        st = sb.cue_stats(cues, o)
        self.assertEqual((st["over_line"], st["over_lines"], st["line_end_punct"]), (0, 0, 0))

    def test_segment_start_kept_and_no_cross_segment(self):
        cues, o = self.cues()
        starts = [c["start"] for c in cues]
        for s in LONG:
            if s["start"] == 12.0:                                # 「好。」太短：併進同講者前一條
                continue
            self.assertIn(s["start"], starts)
        for c in cues:
            segs = [s for s in LONG if s["start"] <= c["start"] + 1e-9 and c["end"] <= s["end"] + 1e-9]
            if c["text"].endswith("好。"):
                continue
            self.assertTrue(segs or c["end"] - c["start"] <= o["min_sec"] + 1e-6, c)

    def test_too_short_merged_same_speaker(self):
        cues, o = self.cues()
        self.assertTrue(any(c["text"].endswith("好。") and c["start"] < 12.0 for c in cues))
        st = sb.cue_stats(cues, o)
        self.assertEqual(st["under_min_sec"], 0)

    def test_too_long_split(self):
        cues, o = self.cues()
        st = sb.cue_stats(cues, o)
        long_ones = [c for c in cues if c["end"] - c["start"] > o["max_sec"] + 1e-6]
        self.assertEqual([c["text"] for c in long_ones], ["接下來"])   # 3 個字：不再切（每條至少 4 字）
        self.assertEqual(st["over_max_sec"], 1)
        hard = [c for c in cues if 16.0 <= c["start"] < 40.0]
        self.assertGreaterEqual(len(hard), 4)                       # 24 秒、無標點 → 照字數平均切
        for c in hard:
            self.assertLessEqual(c["end"] - c["start"], o["max_sec"] + 1e-6)

    def test_time_proportional_and_contiguous(self):
        cues, o = self.cues()
        first = [c for c in cues if c["seg"] == 0]
        self.assertEqual(first[0]["start"], 0.0)
        for a, b in zip(first, first[1:]):
            self.assertAlmostEqual(a["end"], b["start"])
        n = [len(sb.content(c["text"])) for c in first]
        d = [c["end"] - c["start"] for c in first]
        self.assertAlmostEqual(d[0] / d[1], n[0] / n[1], places=5)

    def test_speaker_label_modes(self):
        cues, o = self.cues()
        srt = sb.render_srt(cues, "change")
        blocks = srt.strip().split("\n\n")
        labelled = [b.split("\n")[2] for b in blocks if b.split("\n")[2].startswith("[")]
        self.assertEqual([x.split("]")[0] for x in labelled], ["[S1", "[S2", "[S1"])
        self.assertEqual(sum(1 for b in sb.render_srt(cues, "always").strip().split("\n\n")
                             if b.split("\n")[2].startswith("[")), len(cues))
        self.assertNotIn("[S", sb.render_srt(cues, "none"))

    def test_srt_format(self):
        cues, o = self.cues()
        srt = sb.render_srt(cues, "change")
        self.assertNotIn("\r", srt)
        blocks = srt.split("\n\n")[:-1]
        self.assertEqual([int(b.split("\n")[0]) for b in blocks], list(range(1, len(cues) + 1)))
        for b in blocks:
            self.assertRegex(b.split("\n")[1], r"^\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}$")
            self.assertLessEqual(len(b.split("\n")) - 2, 2)
        self.assertEqual(sb.srt_ts(3725.5), "01:02:05,500")

    def test_wrap_prefers_punctuation_and_not_inside_words(self):
        self.assertEqual(sb.wrap("可以在Grafana的面板上看到狀態，另外還要確認", 16, 2),
                         ["可以在Grafana的面板上看到狀態", "另外還要確認"])
        lines = sb.wrap("請打開PowerShellTerminal然後輸入指令", 16, 2)
        self.assertEqual("".join(lines), "請打開PowerShellTerminal然後輸入指令")
        self.assertIsNone(sb.wrap("一" * 40, 16, 2))

    def test_options_invalid_values_fall_back(self):
        o = sb.options({"subtitles": {"max_line_chars": "x", "speaker_label": "bogus", "uncertain": "?", "max_lines": 0}})
        self.assertEqual((o["max_line_chars"], o["speaker_label"], o["uncertain"], o["max_lines"]), (16.0, "change", "orig", 2))
        o = sb.options({"subtitles": {"max_line_chars": 18}})
        cues, _ = self.cues(max_line_chars=18)
        self.assertTrue(all(sb.width(ln) <= 18 for c in cues for ln in c["lines"]))


# ---------------------------------------------------------------- 檔案、U5、失敗退回
@unittest.skipUnless(V2, "2.0.0 才有")
class Files(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mmp-subf-"))
        self.msgs = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_cues_written_and_meta(self):
        write_doc(self.d, LONG)
        before = (self.d / "transcript.srt").read_bytes()
        r = sb.write_cues(self.d, {}, log=self.msgs.append)
        self.assertEqual(r["status"], "ok")
        self.assertEqual((self.d / "transcript.srt").read_bytes(), before)        # transcript.srt 不變
        raw = (self.d / sb.CUES_NAME).read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)
        meta = json.loads((self.d / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["subtitles"]["cues"]["cues"], r["cues"])
        self.assertEqual(meta["source"], "demo.wav")                              # 其他鍵不動
        self.assertEqual(self.msgs, [f"  字幕：transcript.cues.srt {r['cues']} 條"])
        for k in ("over_line", "over_max_sec", "under_min_sec", "over_cps"):
            self.assertIn(k, r)

    def test_cues_disabled_and_recue_off(self):
        write_doc(self.d, LONG)
        self.assertEqual(sb.write_cues(self.d, {"subtitles": {"cues_srt": False}}, log=self.msgs.append)["reason"], "disabled")
        self.assertEqual(sb.write_cues(self.d, {}, enabled=False, log=self.msgs.append)["reason"], "disabled")
        self.assertEqual(sb.write_cues(self.d, {"subtitles": {"recue": False}}, log=self.msgs.append)["reason"], "recue_off")
        self.assertFalse((self.d / sb.CUES_NAME).exists())

    def test_corrected_recue_off_one_to_one(self):
        cor = (para_line("00:00:00", "S1", "這個參數目前寫在設定檔裡面，可以在{Grafana→Grafana}的面板上看到狀態。另外我們還要確認一下，"
                                           "測試環境的資料庫連線數量是不是足夠，如果不夠的話要先跟維運部門申請。好。")
               + para_line("00:00:13", "S2", "了解，我下午就去申請。這段話完全沒有標點符號所以只能硬切但是每一條還是要符合字幕規則每行不超過十六個字而且最多兩行")
               + para_line("00:00:41", "S1", "接下來"))
        write_doc(self.d, LONG, corrected=cor)
        r = sb.write_corrected(self.d, {"subtitles": {"recue": False}}, log=self.msgs.append)
        self.assertEqual((r["status"], r["recue"], r["cues"]), ("ok", False, len(LONG)))
        a = [(c["start"], c["end"]) for c in read_srt(self.d / "transcript.srt")]
        b = [(c["start"], c["end"]) for c in read_srt(self.d / sb.CORRECTED_NAME)]
        self.assertEqual(a, b)                                                    # 一條對一條、時間軸相同
        self.assertTrue(all(c["label"] for c in read_srt(self.d / sb.CORRECTED_NAME)))

    def test_corrected_console_and_record(self):
        cor = (para_line("00:00:00", "S1", "今天我們來討論{卡夫卡→Kafka}的設定，還有延持的問題要先處理。")
               + para_line("00:00:10", "S2", "我這邊已經查過了謝謝觀看延持主要是網路導致的，下週會修好。")
               + para_line("00:00:21", "S1", "好，那就這樣決定。"))
        write_doc(self.d, SEGS, corrected=cor)
        r = sb.write_corrected(self.d, {}, log=self.msgs.append)
        self.assertEqual((r["status"], r["map_failed_paragraphs"], r["doc_level"], r["paragraphs"]), ("ok", 1, False, 3))
        self.assertEqual(self.msgs, [f"  字幕：transcript.corrected.srt {r['cues']} 條（對應失敗 1 段，該段用原文）"])
        for k in ("cross_segment_marks", "split_in_segment", "uncertain", "recue"):
            self.assertIn(k, r)
        meta = json.loads((self.d / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["subtitles"]["corrected"]["map_failed_paragraphs"], 1)

    def test_corrected_skipped_without_md_or_disabled(self):
        write_doc(self.d, SEGS)
        self.assertEqual(sb.write_corrected(self.d, {}, log=self.msgs.append)["reason"], "no_corrected")
        write_doc(self.d, SEGS, corrected=para_line("00:00:00", "S1", "x"))
        self.assertEqual(sb.write_corrected(self.d, {"subtitles": {"corrected_srt": False}},
                                            log=self.msgs.append)["reason"], "disabled")
        self.assertFalse((self.d / sb.CORRECTED_NAME).exists())

    def test_error_falls_back_and_removes_stale(self):
        write_doc(self.d, SEGS)
        sb.write_cues(self.d, {}, log=self.msgs.append)
        self.assertTrue((self.d / sb.CUES_NAME).exists())
        doc = json.loads((self.d / "transcript.json").read_text(encoding="utf-8"))
        doc["segments"][0].pop("text")                                           # 壞掉的資料 → KeyError
        (self.d / "transcript.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.msgs.clear()
        r = sb.write_cues(self.d, {}, log=self.msgs.append)
        self.assertEqual((r["status"], r["reason"]), ("error", "KeyError"))
        self.assertFalse((self.d / sb.CUES_NAME).exists())
        self.assertIn("transcript.cues.srt 產生失敗（KeyError）；轉寫結果不受影響", self.msgs[0])
        meta = json.loads((self.d / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["subtitles"]["cues"]["status"], "error")

    def test_cli(self):
        cor = para_line("00:00:00", "S1", "今天我們來討論[?卡夫卡｜Kafka]的設定，還有延持的問題要先處理。")
        cor += para_line("00:00:10", "S2", "我這邊已經查過了謝謝觀看延持主要是網路造成的，下週會修好。")
        cor += para_line("00:00:21", "S1", "好，那就這樣決定。")
        write_doc(self.d, SEGS, corrected=cor)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.pop("MMP_RUN_ID", None)
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "subtitles.py"), str(self.d), "--corrected",
                            "--uncertain", "guess"], capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        res = json.loads(p.stdout.strip().splitlines()[-1])["subtitles"]
        self.assertEqual(list(res), ["corrected"])
        self.assertEqual((res["corrected"]["status"], res["corrected"]["uncertain"]), ("ok", "guess"))
        self.assertFalse((self.d / sb.CUES_NAME).exists())
        ev = runlog.read_events(self.d / runlog.LOG_NAME)
        cp = [e for e in ev if e["event"] == "checkpoint" and e["name"] == "subtitles"]
        self.assertEqual((cp[0]["step"], cp[0]["file"], cp[0]["cues"]), ("subtitles", "corrected", res["corrected"]["cues"]))
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "subtitles.py"), str(self.d)],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        res = json.loads(p.stdout.strip().splitlines()[-1])["subtitles"]
        self.assertEqual(sorted(res), ["corrected", "cues"])
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "subtitles.py"), str(self.d / "nope")],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(p.returncode, 2)


@unittest.skipUnless(V2 and (SCRIPTS_122 / "transcribe.py").exists(), "需要 1.2.2 目錄")
class SrtFrozen(unittest.TestCase):
    """S-3：transcript.srt 與 1.2.2 的 write_outputs() 逐位元相同。"""

    def test_same_bytes_as_122(self):
        segs = LONG + [seg(61.0, 63.25, "S?", "English words, and 中文。", 3)]
        with tempfile.TemporaryDirectory(prefix="mmp-s3-") as t:
            d2, d1 = Path(t) / "v2", Path(t) / "v122"
            d2.mkdir()
            d1.mkdir()
            write_doc(d2, segs)
            (Path(t) / "segs.json").write_text(json.dumps(segs, ensure_ascii=False), encoding="utf-8")
            code = ("import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import transcribe as tr;"
                    "segs=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'));"
                    "meta={'version':'1.2.2','source':'demo.wav','duration':63.25,'device':'ct2/cpu','model':'turbo',"
                    "'speakers':3,'elapsed_sec':1.0,'rtf':0.1};tr.write_outputs(Path(sys.argv[3]),meta,segs,[])")
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
            p = subprocess.run([sys.executable, "-B", "-c", code, str(SCRIPTS_122), str(Path(t) / "segs.json"), str(d1)],
                               capture_output=True, text=True, encoding="utf-8", env=env)
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertEqual((d2 / "transcript.srt").read_bytes(), (d1 / "transcript.srt").read_bytes())


# ---------------------------------------------------------------- 接線：transcribe.py、auto_correct.py
@unittest.skipUnless(V2, "2.0.0 才有")
class TranscribeWiring(unittest.TestCase):
    """transcribe.main()（假 ffmpeg／ASR／sherpa）：cues 在 [4/x] 之後產生、--no-cues、log、失敗不影響轉寫。"""

    def setUp(self):
        import numpy as np
        import soundfile as sf
        import diarize as diar
        import transcribe as tr
        self.tr, self.diar = tr, diar
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-subt-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        (self.home / "config.json").write_text(json.dumps({"diarization": {"engine": "sherpa"}}), encoding="utf-8")
        self.src = self.tmp / "meeting.wav"
        sf.write(str(self.src), (np.random.default_rng(0).standard_normal(16000 * 30) * 0.1).astype(np.float32), 16000)
        self.saved = {n: getattr(tr, n) for n in ("to_wav", "load_asr")}
        self.saved_d = {n: getattr(diar, n) for n in ("run_sherpa", "choose_engine")}
        self.saved_s = {n: getattr(sb, n) for n in ("recue",)}

        class ASR:
            i = 0

            def transcribe(self, audio):
                ASR.i += 1
                return f"這是第{ASR.i}句測試用的文字，內容是虛構的而且比較長一點，用來確認長句會被切成好幾條"
        tr.to_wav = lambda src, dst: shutil.copyfile(src, dst)
        tr.load_asr = lambda *a, **k: ASR()
        diar.run_sherpa = lambda audio, threshold, num_clusters=-1, log=None: [(0.0, 14.0, 0), (14.0, 29.0, 1)]
        orig = self.saved_d["choose_engine"]
        diar.choose_engine = lambda cfg, req=None, **kw: orig(cfg, req, platform="win32")
        self._run_id = os.environ.pop("MMP_RUN_ID", None)

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(self.tr, n, v)
        for n, v in self.saved_d.items():
            setattr(self.diar, n, v)
        for n, v in self.saved_s.items():
            setattr(sb, n, v)
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        if self._run_id is not None:
            os.environ["MMP_RUN_ID"] = self._run_id
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, *extra):
        out = self.tmp / f"out{len(list(self.tmp.glob('out*')))}"
        argv = sys.argv
        sys.argv = ["transcribe.py", str(self.src), "--out-dir", str(out), "--no-correct", "--no-corrections",
                    "--backend", "ct2", "--device", "cpu", "--no-punct", *extra]
        so, se = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                self.tr.main()
        finally:
            sys.argv = argv
        return json.loads(so.getvalue().strip().splitlines()[-1]), se.getvalue(), out

    def test_cues_after_outputs(self):
        res, err, out = self.main()
        self.assertTrue((out / sb.CUES_NAME).exists())
        self.assertEqual(res["subtitles"]["cues"]["status"], "ok")
        self.assertGreater(res["subtitles"]["cues"]["cues"], res["segments"])      # 長句被切成多條
        lines = err.splitlines()
        self.assertLess(lines.index("[4/4] 輸出檔案"), [i for i, l in enumerate(lines) if "字幕：transcript.cues.srt" in l][0])
        ev = runlog.read_events(out / runlog.LOG_NAME)
        cp = [e for e in ev if e["event"] == "checkpoint" and e["name"] == "subtitles"]
        self.assertEqual(len(cp), 1)
        self.assertEqual((cp[0]["step"], cp[0]["file"], cp[0]["status"], cp[0]["cues"]),
                         ("transcribe", "cues", "ok", res["subtitles"]["cues"]["cues"]))
        meta = json.loads((out / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["subtitles"]["cues"]["status"], "ok")
        blob = (out / runlog.LOG_NAME).read_text(encoding="utf-8")
        self.assertNotIn("測試用的文字", blob)                                       # log 不含逐字稿

    def test_no_cues_flag_and_config(self):
        res, err, out = self.main("--no-cues")
        self.assertFalse((out / sb.CUES_NAME).exists())
        self.assertEqual(res["subtitles"]["cues"], {"status": "skipped", "reason": "disabled"})
        (self.home / "config.json").write_text(json.dumps({"diarization": {"engine": "sherpa"},
                                                           "subtitles": {"cues_srt": False}}), encoding="utf-8")
        res, err, out = self.main()
        self.assertFalse((out / sb.CUES_NAME).exists())

    def test_subtitle_failure_does_not_break_transcription(self):
        def boom(*a, **k):
            raise RuntimeError("boom")
        sb.recue = boom
        res, err, out = self.main()
        self.assertEqual(res["subtitles"]["cues"]["status"], "error")
        self.assertTrue((out / "transcript.srt").exists() and (out / "transcript.md").exists())
        self.assertIn("transcript.cues.srt 產生失敗（RuntimeError）；轉寫結果不受影響", err)
        ev = runlog.read_events(out / runlog.LOG_NAME)
        self.assertEqual([e["status"] for e in ev if e["event"] == "checkpoint" and e["name"] == "subtitles"], ["error"])
        self.assertEqual([e["status"] for e in ev if e["event"] == "result"], ["ok"])


@unittest.skipUnless(V2, "2.0.0 才有")
class CorrectWiring(unittest.TestCase):
    """auto_correct.run()／main()：校正版寫好後產生 transcript.corrected.srt；--no-corrected-srt；字幕失敗時校正照常。"""

    def setUp(self):
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = Path(tempfile.mkdtemp(prefix="mmp-subc-home-"))
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self.out = Path(tempfile.mkdtemp(prefix="mmp-subc-out-"))
        write_doc(self.out, SEGS)
        self._callers, self._select = dict(ac.CALLERS), ac.select_backend
        self._wc = sb.write_corrected
        self._run_id = os.environ.pop("MMP_RUN_ID", None)

        def fake(be, system, user, timeout, schema=None):
            body = re.search(r"## 要校正的逐字稿[^\n]*\n(.*?)(?=\n## |\Z)", user, re.S).group(1).strip()
            body = body.replace("卡夫卡", "{卡夫卡→Kafka}").replace("謝謝觀看", "{謝謝觀看→}")
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {"input": 1, "output": 1}, "claude-sonnet-5-5")
        ac.CALLERS[("claude", "cli")] = fake
        ac.select_backend = lambda cfg, req: {"provider": "claude", "channel": "cli", "exe": "x", "cli_version": "fake",
                                              "auth": "subscription", "note": None, "model": "sonnet",
                                              "effort": "medium", "model_api": "sonnet"}

    def tearDown(self):
        ac.CALLERS.clear()
        ac.CALLERS.update(self._callers)
        ac.select_backend = self._select
        sb.write_corrected = self._wc
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        if self._run_id is not None:
            os.environ["MMP_RUN_ID"] = self._run_id
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def run_ac(self, **kw):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            res = ac.run(self.out, ac.resolve_request({}), cfg={}, consent=True, **kw)
        return res, err.getvalue()

    def test_corrected_srt_produced(self):
        res, err = self.run_ac()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["subtitles"]["status"], "ok")
        srt = (self.out / sb.CORRECTED_NAME).read_text(encoding="utf-8")
        self.assertIn("Kafka", srt)
        self.assertNotIn("謝謝觀看", srt)
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["subtitles"]["cues"], res["subtitles"]["cues"])
        self.assertIn("字幕：transcript.corrected.srt", err)
        ev = runlog.read_events(self.out / runlog.LOG_NAME)
        cp = [e for e in ev if e["event"] == "checkpoint" and e["name"] == "subtitles"]
        self.assertEqual((cp[0]["step"], cp[0]["file"], cp[0]["map_failed_paragraphs"], cp[0]["doc_level"]),
                         ("correct", "corrected", 0, False))
        meta = json.loads((self.out / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual((meta["correction"]["status"], meta["subtitles"]["corrected"]["status"]), ("ok", "ok"))

    def test_no_corrected_srt(self):
        res, err = self.run_ac(corrected_srt=False)
        self.assertEqual((res["status"], res["subtitles"]["reason"]), ("ok", "disabled"))
        self.assertFalse((self.out / sb.CORRECTED_NAME).exists())

    def test_main_flag(self):
        argv = sys.argv
        sys.argv = ["auto_correct.py", str(self.out), "--claude", "--no-corrected-srt"]
        so = io.StringIO()
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as cm:
                ac.main()
        finally:
            sys.argv = argv
        self.assertEqual(cm.exception.code, 0)
        out = json.loads(so.getvalue().strip().splitlines()[-1])["correction"]
        self.assertEqual((out["status"], out["subtitles"]["reason"]), ("ok", "disabled"))
        self.assertFalse((self.out / sb.CORRECTED_NAME).exists())
        sys.argv = ["auto_correct.py", str(self.out), "--claude", "--force"]
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                ac.main()
        finally:
            sys.argv = argv
        self.assertTrue((self.out / sb.CORRECTED_NAME).exists())

    def test_subtitle_crash_keeps_correction(self):
        def boom(*a, **k):
            raise RuntimeError("boom")
        sb.write_corrected = boom
        res, err = self.run_ac()
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["subtitles"], {"status": "error", "reason": "RuntimeError"})
        self.assertTrue((self.out / "transcript.corrected.md").exists())
        self.assertEqual(ac.exit_code(res), 0)


# ---------------------------------------------------------------- 計分命令列
def _cli():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "map":
        mode = "orig"
        if args and args[0].startswith("--uncertain="):
            mode = args.pop(0).split("=", 1)[1]
        for d in args:
            print(json.dumps(map_case(Path(d), mode), ensure_ascii=False))
    elif cmd == "rules":
        for f in args:
            print(json.dumps(rule_stats(Path(f)), ensure_ascii=False))
    elif cmd == "timing":
        name, files = args[0], args[1:]
        ref = HERE / "_out" / f"{name}.ref.json"
        for f in files:
            print(json.dumps(timing(ref, Path(f)), ensure_ascii=False))
    elif cmd == "derive":
        print(json.dumps(derive(Path(args[0]), Path(args[1]), args[2]), ensure_ascii=False))
    else:
        raise SystemExit(__doc__)



@unittest.skipUnless(_testenv.VER >= (2, 2, 0), "2.2.0 才有")
class TranscribeRefFlags(TranscribeWiring):
    """〔2.2.0〕transcribe.py 的參考資料旗標（規格 2.2.0 §7.3）：原樣轉給接著執行的校正；沒給時呼叫方式與 2.1.0 相同；
    沒有校正時 --context 仍寫 context.md、其他旗標只提示。假 ASR／分離、假 auto_correct.run（不呼叫模型）。"""

    test_cues_after_outputs = test_no_cues_flag_and_config = test_subtitle_failure_does_not_break_transcription = None  # 只借用環境

    def setUp(self):
        super().setUp()
        import auto_correct
        self.ac = auto_correct
        self._ac_run = auto_correct.run
        self.calls = []

        def fake_run(out_dir, req=None, **kw):
            self.calls.append({"out_dir": out_dir, "kw": kw})
            return {"status": "skipped", "reason": "fake", "provider": None, "model": None, "channel": None,
                    "chunks": 0, "chunks_ok": 0, "fallback": None}
        auto_correct.run = fake_run

    def tearDown(self):
        self.ac.run = self._ac_run
        super().tearDown()

    def test_no_flags_same_call_as_210(self):
        res, err, out = self.main("--correct")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(sorted(self.calls[0]["kw"]), ["cfg", "consent", "in_pipeline", "interactive", "run_log"])
        self.assertFalse((out / "context.md").exists())

    def test_flags_forwarded(self):
        doc = self.tmp / "議程.pdf"
        res, err, out = self.main("--correct", "--context", "示範週會，主持人陳怡君", "--refs", str(doc), "--refs", "refs2",
                                  "--no-context", "--no-frames")
        self.assertEqual(self.calls[0]["kw"]["refs_opts"], {"context": "示範週會，主持人陳怡君", "refs": [str(doc), "refs2"],
                                                            "no_refs": False, "no_context": True, "no_frames": True})
        res, err, out = self.main("--claude", "--no-refs")                  # 捷徑也會校正
        self.assertEqual(self.calls[1]["kw"]["refs_opts"], {"context": None, "refs": [], "no_refs": True,
                                                            "no_context": False, "no_frames": False})

    def test_without_correct(self):
        res, err, out = self.main("--context", "示範週會\n第二行", "--no-frames")
        self.assertEqual(self.calls, [])
        ctx = (out / "context.md").read_text(encoding="utf-8")
        self.assertTrue(ctx.startswith("---\nsource: entry\n") and ctx.endswith("---\n示範週會\n"))
        self.assertIn("背景說明已存成 context.md", err)
        self.assertIn("--refs／--no-refs／--no-context／--no-frames 只在 AI 校正時使用；這次沒有做 AI 校正", err)
        res, err, out = self.main()
        self.assertFalse((out / "context.md").exists())
        self.assertNotIn("只在 AI 校正時使用", err)
        self.assertNotIn("背景說明", err)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("map", "rules", "timing", "derive"):
        _cli()
    else:
        unittest.main()
