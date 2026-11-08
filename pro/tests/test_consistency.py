"""〔2.2.0〕全文用字統一（consistency.py；本機處理）的單元測試。不呼叫任何模型。

涵蓋：寫法變體（大小寫、空格、「.」、「-」）、標準寫法的優先序（使用者提供＞用字表＞出現最多）與門檻、
不誤併（一般英文單字、網址、檔名、路徑、程式碼、Notebook 與 NotebookLM、全小寫的一般片語）、
校正版標記格式、字幕時間碼不變、auto_correct／auto_minutes 的接線與紀錄（只有數量）、
consistency.enabled: false 時與沒有這功能的版本（2.1.0）逐位元相同、單獨執行 consistency.py。
"""
import contextlib
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

V22 = _testenv.VER >= (2, 2, 0)
if V22:
    import auto_correct as ac
    import auto_minutes as am
    import common
    import consistency as cs
    import runlog
    from test_auto_correct import FakeModel, write_out
    from test_auto_correct import Base as AcBase
    from test_auto_minutes import Base as AmBase, Fake as AmFake, result
else:                                       # 舊版：整個檔略過（類別仍要定義得出來）
    AcBase = AmBase = unittest.TestCase

V21_SCRIPTS = _testenv.HERE.parent / "meeting-minutes-pro-v2.1.0" / "payload" / "runtime" / "scripts"


def build(texts, user=(), terms=()):
    return cs.build(texts, user, terms)


def rep(text, n):
    return [text] * n


@unittest.skipUnless(V22, "2.2.0 才有")
class Variants(unittest.TestCase):
    """大小寫、空格、「.」、「-」的變體都統一成同一個寫法。"""

    def test_all_variant_kinds(self):
        texts = rep("今天介紹 NotebookLM 的用法。", 4) + ["打開 notebooklm 首頁", "notebookLM 很好用", "用 notebook lm 整理",
                                                         "Notebook-LM 的介面", "notebook.lm 也可以", "Notebook LM 的筆記"]
        u = build(texts)
        self.assertEqual(u.groups["notebooklm"], {"canon": "NotebookLM", "tier": "frequency"})
        for src in texts[4:]:
            new, hits = u.plain(src)
            self.assertIn("NotebookLM", new, src)
            self.assertEqual(len(hits), 1, src)
            self.assertNotRegex(new, r"(?i)notebook[ .\-]lm|notebooklm(?<!NotebookLM)")

    def test_key_and_marked(self):
        for f in ("NotebookLM", "notebook lm", "Notebook-LM", "notebook.lm", "NOTEBOOK LM"):
            self.assertEqual(cs.key_of(f), "notebooklm")
        self.assertEqual(cs.key_of("GPT-4"), "gpt4")
        self.assertNotEqual(cs.key_of("1.5"), cs.key_of("15"))           # 數字之間的「.」不拿掉
        self.assertTrue(cs.is_marked("NotebookLM") and cs.is_marked("AI") and cs.is_marked("iPhone"))
        self.assertTrue(cs.is_marked("16K") and cs.is_marked("Google AI Studio"))
        self.assertFalse(cs.is_marked("Google") or cs.is_marked("notebooklm") or cs.is_marked("A"))

    def test_acronym_and_multiword(self):
        texts = rep("先上傳 PDF 檔", 3) + ["這份 pdf 很亂"] + rep("在 AWS Lambda 測試", 2) + ["AWS lambda 的設定"] + \
            rep("用 Jina AI 轉換", 2) + ["jina ai 免費"] + rep("PDF File 下載", 2) + ["PDF file 下載"]
        u = build(texts)
        self.assertEqual(u.plain("這份 pdf 很亂")[0], "這份 PDF 很亂")
        self.assertEqual(u.plain("AWS lambda 的設定")[0], "AWS Lambda 的設定")
        self.assertEqual(u.plain("jina ai 免費")[0], "Jina AI 免費")
        self.assertEqual(u.plain("PDF file 下載")[0], "PDF file 下載")      # 不同處是一般單字（file）：不當成一組

    def test_unmarked_canon_only_separator(self):
        """標準寫法沒有特徵時（使用者寫的 Redis Sentinel）：只統一分隔，不改大小寫。"""
        u = build(["Redis-Sentinel 切換", "RedisSentinel 設定", "redis sentinel 小寫"], user=["Redis Sentinel"])
        self.assertEqual(u.plain("Redis-Sentinel 切換")[0], "Redis Sentinel 切換")
        self.assertEqual(u.plain("RedisSentinel 設定")[0], "Redis Sentinel 設定")
        self.assertEqual(u.plain("redis sentinel 小寫")[0], "redis sentinel 小寫")


@unittest.skipUnless(V22, "2.2.0 才有")
class Priority(unittest.TestCase):
    """使用者提供（glossary ＞ corrections ＞ 說明檔與文件 ＞ reference.json）＞ 用字表 ＞ 出現最多。"""
    TEXTS = rep("Notebook-LM 的介面", 5) + ["NotebookLM 一次", "notebooklm 小寫"]

    def test_frequency(self):
        self.assertEqual(build(self.TEXTS).groups["notebooklm"]["canon"], "Notebook-LM")

    def test_terms_over_frequency(self):
        u = build(self.TEXTS, terms=["NotebookLM"])
        self.assertEqual(u.groups["notebooklm"], {"canon": "NotebookLM", "tier": "terms"})
        self.assertEqual(u.plain("Notebook-LM 的介面")[0], "NotebookLM 的介面")

    def test_user_over_terms(self):
        u = build(self.TEXTS, user=["NOTEBOOKLM"], terms=["NotebookLM"])
        self.assertEqual(u.groups["notebooklm"], {"canon": "NOTEBOOKLM", "tier": "user"})
        u = build(self.TEXTS, user=["NotebookLM 課程", "Notebook LM"])          # 同一個鍵：先列的為準；詞裡的中文不算
        self.assertEqual(u.groups["notebooklm"]["canon"], "NotebookLM")

    def test_user_terms_sources_order(self):
        home = Path(os.environ["MEETING_MINUTES_PRO_HOME"])
        g, c = common.default_glossary(), common.corrections_path()
        saved = {p: (p.read_bytes() if p.exists() else None) for p in (g, c)}
        try:
            g.parent.mkdir(parents=True, exist_ok=True)
            g.write_text("# 註解\nNotebookLM\n", encoding="utf-8")
            c.write_text("筆記本\tNotebook-LM\t\n", encoding="utf-8")
            out_dir = Path(tempfile.mkdtemp(prefix="mmp-cs-ref-"))
            (out_dir / "reference.json").write_text(json.dumps({"terms": ["NOTEBOOKLM", "Gemini"]}), encoding="utf-8")
            col = {"context_text": "這是 NotebookLm 課程", "doc_terms": ["Notebook.LM"]}
            terms = cs.user_terms(col=col, out_dir=out_dir)
            self.assertEqual(terms[:2], ["NotebookLM", "Notebook-LM"])
            self.assertLess(terms.index("NotebookLm"), terms.index("Notebook.LM"))
            self.assertLess(terms.index("Notebook.LM"), terms.index("NOTEBOOKLM"))
            self.assertEqual(build(self.TEXTS, user=terms).groups["notebooklm"]["canon"], "NotebookLM")
            shutil.rmtree(out_dir, ignore_errors=True)
            self.assertTrue(str(g).startswith(str(home)))
        finally:
            for p, b in saved.items():
                if b is None:
                    p.unlink(missing_ok=True)
                else:
                    p.write_bytes(b)

    def test_tie_and_thresholds(self):
        # 同票：分隔少的；再來先出現的
        self.assertEqual(build(["Notebook LM", "Notebook LM", "NotebookLM", "NotebookLM", "notebooklm"]).groups["notebooklm"]
                         ["canon"], "NotebookLM")
        self.assertEqual(build(["GitHub", "GitHub", "GITHUB", "GITHUB", "github"]).groups["github"]["canon"], "GitHub")
        # 標準寫法只有 1 次、整組不到 3 次、全部小寫、全部沒有特徵 → 不統一
        self.assertNotIn("notebooklm", build(["NotebookLM", "notebooklm", "notebooklm", "notebooklm"]).groups)
        self.assertNotIn("notebooklm", build(["NotebookLM", "NotebookLM"] + ["x"] * 5).groups)
        self.assertNotIn("notebooklm", build(["NotebookLM", "notebooklm"]).groups)
        self.assertNotIn("pytorch", build(["pytorch"] * 3 + ["py torch"] * 3).groups)
        self.assertNotIn("google", build(["Google"] * 5 + ["google"] * 2).groups)


@unittest.skipUnless(V22, "2.2.0 才有")
class NoMisMerge(unittest.TestCase):
    """一般單字、網址、檔名、路徑、程式碼不改；不同名詞不合併。"""

    def setUp(self):
        self.u = build(rep("NotebookLM 與 PDF、AI、IT 部門、App Store、Go 語言、Apple 發表會", 5),
                       user=["Apple", "Go", "App"])

    def test_common_words(self):
        for s in ("我買了 apple 一顆", "let's go 出發", "這個 app 很好用", "it 是代名詞", "ok 好", "single file 上傳"):
            self.assertEqual(self.u.plain(s), (s, []), s)
        u = build(rep("SingleFile 外掛", 3) + ["single file 上傳"])
        self.assertEqual(u.plain("single file 上傳"), ("single file 上傳", []))

    def test_protected(self):
        for s in ("網址 https://notebooklm.google.com/notebook/abc 開啟", "產品頁 notebooklm.google 介紹",
                  "存成 notebooklm.md 再上傳", "路徑 work/notebooklm/a 底下", "指令 `notebooklm --help`",
                  "看 [說明](https://x.test/notebooklm) 這頁", "寄到 notebooklm@example.com", "結尾是 .pdf 的網址",
                  "參數 --pdf 開啟", "變數 notebooklm_id", "標籤 #notebooklm"):
            self.assertEqual(self.u.plain(s), (s, []), s)

    def test_different_nouns(self):
        u = build(rep("NotebookLM 與 Notebook", 5) + ["notebook 筆記本", "notebooklm 小寫"])
        self.assertEqual(u.plain("notebook 筆記本"), ("notebook 筆記本", []))
        self.assertEqual(u.plain("notebooklm 小寫")[0], "NotebookLM 小寫")
        self.assertEqual(u.plain("Notebook 很多")[0], "Notebook 很多")

    def test_reducible_phrase(self):
        """「NotebookLM is」與「notebooklm is」交給 NotebookLM 那組，不另成一組。"""
        u = build(rep("NotebookLM is great", 3) + ["notebooklm is fine"])
        self.assertIn("notebooklm", u.groups)
        self.assertNotIn("notebooklmis", u.groups)
        self.assertEqual(u.plain("notebooklm is fine")[0], "NotebookLM is fine")


@unittest.skipUnless(V22, "2.2.0 才有")
class Marks(unittest.TestCase):
    """校正版標記格式。"""

    def setUp(self):
        self.u = build(rep("NotebookLM", 4) + ["notebooklm"])

    def test_formats(self):
        u = self.u
        self.assertEqual(u.marked("打開 notebooklm 首頁")[0], "打開 {notebooklm→NotebookLM} 首頁")
        self.assertEqual(u.marked("用 notebook lm 整理")[0], "用 {notebook lm→NotebookLM} 整理")
        self.assertEqual(u.marked("{筆記本→notebooklm}很好")[0], "{筆記本→NotebookLM}很好")           # 模型的修正也統一
        self.assertEqual(u.marked("{NotebookLM→notebooklm}的")[0], "NotebookLM的")                      # 統一後等於原文 → 換回原文
        self.assertEqual(u.marked("[?notebooklm｜筆記]其他")[0], "[?notebooklm｜筆記]其他")             # 待確認不動
        self.assertEqual(u.marked("{→notebook lm}補字")[0], "{→NotebookLM}補字")
        self.assertEqual(u.marked("刪掉{notebooklm→}")[0], "刪掉{notebooklm→}")
        new, hits = u.marked("notebooklm{好→很好}notebooklm")
        self.assertEqual(new, "{notebooklm→NotebookLM}{好→很好}{notebooklm→NotebookLM}")
        self.assertEqual(len(hits), 2)

    def test_mark_re_same_as_auto_correct(self):
        self.assertEqual(cs.MARK_RE.pattern, ac.MARK_RE.pattern)

    def test_source_side_unchanged(self):
        """標記的原文一側（strip_marks）與原文完全相同：字幕對應與驗證照常。"""
        src = "打開 notebooklm 首頁，notebook lm 的 {錯字→對字} 與 [?notebooklm｜x]"
        new, _ = self.u.marked(src)
        self.assertEqual(ac.strip_marks(new), ac.strip_marks(src))
        self.assertEqual(ac.content_of(cs.visible(new)).lower(), ac.content_of(cs.visible(src)).lower())   # 只差大小寫與分隔

    def test_corrected_md_only_body(self):
        md = "\n".join(["# 校正版逐字稿：notebooklm.mp4", "", "> 原始逐字稿：`transcript.md`", "", "## 校正摘要", "",
                        "| 1 | notebooklm | NotebookLM | 1 | 上下文 | ✅ |", "", "## 待確認", "", "- [?notebooklm]", "", "---", "",
                        "**[00:00:01] S1**：打開 notebooklm 首頁", "", "> 🖼 [00:00:02] 畫面：`notebooklm.jpg`", ""])
        new, hits = self.u.corrected_md(md)
        head = md.split("\n---\n")[0]
        self.assertTrue(new.startswith(head + "\n---\n"))
        self.assertIn("**[00:00:01] S1**：打開 {notebooklm→NotebookLM} 首頁", new)
        self.assertIn("> 🖼 [00:00:02] 畫面：`notebooklm.jpg`", new)
        self.assertEqual(len(hits), 1)


@unittest.skipUnless(V22, "2.2.0 才有")
class SrtAndMarkdown(unittest.TestCase):
    SRT = ("1\n00:00:01,000 --> 00:00:03,500\n打開 notebooklm 首頁\n\n2\n00:00:03,500 --> 00:00:06,000\n[S2] notebook lm 很好\n\n"
           "10\n00:01:00,000 --> 00:01:02,000\nNotebookLM\n")

    def test_srt_timecodes_unchanged(self):
        u = build(rep("NotebookLM", 4) + ["notebooklm"])
        new, hits = u.srt(self.SRT)
        self.assertEqual(len(hits), 2)
        tc = lambda s: [l for l in s.split("\n") if "-->" in l or l.strip().isdigit()]
        self.assertEqual(tc(new), tc(self.SRT))
        self.assertIn("打開 NotebookLM 首頁", new)
        self.assertIn("[S2] NotebookLM 很好", new)

    def test_markdown_skips_quote_and_fence(self):
        u = build(rep("NotebookLM", 4) + ["notebooklm"])
        md = "> 自動整理：notebooklm｜依據：`transcript.md`\n\n- 用 notebooklm 整理\n```\nnotebooklm\n```\n| notebook lm | x |"
        new, hits = u.markdown(md)
        self.assertEqual(new, "> 自動整理：notebooklm｜依據：`transcript.md`\n\n- 用 NotebookLM 整理\n```\nnotebooklm\n```\n"
                              "| NotebookLM | x |")
        self.assertEqual(len(hits), 2)

    def test_lines(self):
        hits = [("notebooklm", "NotebookLM")] * 3 + [("pdf", "PDF")]
        self.assertEqual(cs.console_line(hits), "用字統一：2 組、4 處（NotebookLM、PDF；本機處理）")
        self.assertEqual(cs.summary_line(hits), "全文用字統一（本機處理，未呼叫模型）：2 組、4 處，統一處以 {原文→統一} 標出："
                                                "NotebookLM（notebooklm ×3）；PDF（pdf ×1）")
        self.assertIsNone(cs.summary_line([]))

    def test_enabled_setting(self):
        self.assertTrue(cs.enabled({}))
        self.assertFalse(cs.enabled({"consistency": {"enabled": False}}))
        msgs = []
        self.assertTrue(cs.enabled({"consistency": {"enabled": "no"}}, warn=msgs.append))
        self.assertEqual(msgs, ["[!] consistency.enabled 的值 no 不認得，改用 true"])
        self.assertEqual(common.DEFAULTS["consistency"], {"enabled": True})
        self.assertIn("consistency", common.V22_BLOCKS)


# ---------------------------------------------------------------- 接線：auto_correct
VARIANT_PARAS = [("00:00:01", "S1", "今天介紹 NotebookLM 的用法，NotebookLM 可以整理 PDF。"),
                 ("00:00:20", "S2", "我用 notebooklm 上傳了 pdf 檔，notebook lm 的介面很清楚。"),
                 ("00:00:40", "S1", "NotebookLM 也能讀網址 https://notebooklm.google.com 的 PDF 內容。"),
                 ("00:01:00", "S3", "請把 PDF 和筆計本都放進 NotebookLM。")]


@unittest.skipUnless(V22, "2.2.0 才有")
class CorrectRun(AcBase):
    def run_ac(self, cfg, fix=None):
        write_out(self.out, VARIANT_PARAS)
        self.use(FakeModel(fix=fix or {"筆計本": "Notebook-LM 筆記本", "整理 PDF": "整理 pdf"}))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg, consent=True)
        return res, (self.out / "transcript.corrected.md").read_text(encoding="utf-8"), err.getvalue()

    def test_flow(self):
        res, md, console = self.run_ac(self.cfg(chunk_chars=40))
        self.assertEqual(res["status"], "ok", res)
        body = md.split("\n---\n", 1)[1]
        self.assertIn("我用 {notebooklm→NotebookLM} 上傳了 {pdf→PDF} 檔，{notebook lm→NotebookLM} 的介面很清楚。", body)
        self.assertIn("{筆計本→NotebookLM 筆記本}", body)                                    # 模型改的 b 也統一
        self.assertIn("NotebookLM 可以整理 PDF。", body)                                      # {整理 PDF→整理 pdf} 統一後等於原文 → 原文
        self.assertIn("https://notebooklm.google.com", body)                                 # 網址不改
        self.assertNotRegex(cs.visible(body).replace("https://notebooklm.google.com", ""),
                            r"notebooklm|notebook lm|Notebook-LM|pdf")
        self.assertIn("\n全文用字統一（本機處理，未呼叫模型）：2 組、5 處，統一處以 {原文→統一} 標出：", md)
        self.assertIn("| 筆計本 | NotebookLM 筆記本 |", md)                                   # 校正摘要表用統一後的寫法
        self.assertNotIn("| 整理 PDF |", md)
        self.assertIn("用字統一：2 組、5 處（NotebookLM、PDF；本機處理）", console)
        self.assertIn("修改 1 處", console)                                                   # 統一不算進模型的修改
        self.assertEqual(res["consistency"], {"status": "ok", "groups": 2, "edits": 5, "user": 0, "terms": 0,
                                              "frequency": 2})
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["consistency"], res["consistency"])
        ev = runlog.read_events(self.out / runlog.LOG_NAME)
        cp = [e for e in ev if e["event"] == "checkpoint" and e["name"] == "correct.consistency"]
        self.assertEqual(len(cp), 1)
        self.assertEqual({k: cp[0][k] for k in ("status", "groups", "edits", "frequency")},
                         {"status": "ok", "groups": 2, "edits": 5, "frequency": 2})
        log_text = (self.out / runlog.LOG_NAME).read_text(encoding="utf-8")
        for w in ("NotebookLM", "notebooklm", "PDF"):                                         # log 不寫名詞
            self.assertNotIn(w, log_text)
        sug = self.out / "corrections.suggested.tsv"
        if sug.exists():
            self.assertNotIn("notebooklm\tNotebookLM", sug.read_text(encoding="utf-8"))       # 統一不進對照表建議

    def test_srt_follows_corrected_and_timecodes_same(self):
        segs = [{"start": 1.0, "end": 9.5, "text": VARIANT_PARAS[0][2], "speaker": "S1"},
                {"start": 20.0, "end": 29.0, "text": VARIANT_PARAS[1][2], "speaker": "S2"},
                {"start": 40.0, "end": 52.0, "text": VARIANT_PARAS[2][2], "speaker": "S1"},
                {"start": 60.0, "end": 66.0, "text": VARIANT_PARAS[3][2], "speaker": "S3"}]

        def go(cfg):
            res, md, _ = self.run_ac(cfg)
            doc = json.loads((self.out / "transcript.json").read_text(encoding="utf-8"))
            doc["segments"] = segs
            (self.out / "transcript.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            ac._corrected_srt(self.out, cfg, None, runlog.RunLog(self.out, step="correct"))
            return (self.out / "transcript.corrected.srt").read_text(encoding="utf-8")

        on = go(self.cfg(chunk_chars=40))
        shutil.rmtree(self.out)
        self.out.mkdir()
        off = go(dict(self.cfg(chunk_chars=40), consistency={"enabled": False}))
        tc = lambda s: [l for l in s.split("\n") if "-->" in l]
        self.assertEqual(tc(on), tc(off))
        self.assertTrue(tc(on))
        self.assertIn("notebooklm", off)
        self.assertNotIn("notebooklm 上傳", on)
        self.assertIn("NotebookLM 上傳", on)

    def test_disabled(self):
        res, md, console = self.run_ac(dict(self.cfg(chunk_chars=40), consistency={"enabled": False}))
        self.assertEqual(res["consistency"], {"status": "off"})
        self.assertNotIn("全文用字統一", md)
        self.assertNotIn("用字統一", console)
        self.assertIn("我用 notebooklm 上傳了 pdf 檔", md)
        # 關閉＝沒有這個步驟：與把整個步驟拿掉（correct_stage 原樣回傳、不加摘要行）逐位元相同
        saved = cs.correct_stage, cs.summary_line
        try:
            cs.correct_stage = lambda cfg, para_out, *a, **k: (para_out, {"summary": {"status": "off"}, "unifier": None,
                                                                          "hits": []})
            cs.summary_line = lambda hits: None
            shutil.rmtree(self.out)
            self.out.mkdir()
            _, md2, _ = self.run_ac(self.cfg(chunk_chars=40))
        finally:
            cs.correct_stage, cs.summary_line = saved
        self.assertEqual(md2, md)


# ---------------------------------------------------------------- 接線：auto_minutes
@unittest.skipUnless(V22, "2.2.0 才有")
class MinutesRun(AmBase):
    def prepare(self):
        write_out(self.out, VARIANT_PARAS)
        r = result(summary=["介紹 notebooklm 與 Notebook LM 的用法。", "上傳 pdf 檔。"])
        r["topics"][0]["background"] = "NotebookLM 讀 PDF"
        self.use(AmFake([r]))

    def test_minutes_unified(self):
        self.prepare()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            r = self.run_am(cfg={})
        self.assertEqual(r["status"], "ok", r)
        md = (self.out / "meeting-minutes.md").read_text(encoding="utf-8")
        self.assertIn("介紹 NotebookLM 與 NotebookLM 的用法。", md)
        self.assertIn("上傳 PDF 檔。", md)
        self.assertTrue(md.split("\n")[2].startswith("> 自動整理："))
        self.assertEqual(r["consistency"]["edits"], 3)
        self.assertIn("用字統一：2 組、3 處", err.getvalue())
        html = (self.out / "meeting-minutes.html").read_text(encoding="utf-8")
        self.assertNotIn("notebooklm 與", html)
        rec = json.loads((self.out / "auto_minutes.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["consistency"], r["consistency"])
        ev = runlog.read_events(self.out / runlog.LOG_NAME)
        self.assertEqual(len([e for e in ev if e.get("name") == "minutes.consistency"]), 1)
        self.assertNotIn("NotebookLM", (self.out / runlog.LOG_NAME).read_text(encoding="utf-8"))

    def test_minutes_disabled(self):
        self.prepare()
        r = self.run_am(cfg={"consistency": {"enabled": False}})
        md = (self.out / "meeting-minutes.md").read_text(encoding="utf-8")
        self.assertIn("介紹 notebooklm 與 Notebook LM 的用法。", md)
        self.assertEqual(r["consistency"], {"status": "off"})
        # 關閉＝沒有這個步驟：與 minutes_stage 原樣回傳逐位元相同（.md 與網頁版）
        html = (self.out / "meeting-minutes.html").read_bytes()
        saved = cs.minutes_stage
        try:
            cs.minutes_stage = lambda cfg, text, *a, **k: (text, {"status": "off"})
            shutil.rmtree(self.out)
            self.out.mkdir()
            self.prepare()
            self.run_am(cfg={})
        finally:
            cs.minutes_stage = saved
        self.assertEqual((self.out / "meeting-minutes.md").read_text(encoding="utf-8"), md)
        self.assertEqual((self.out / "meeting-minutes.html").read_bytes(), html)

    def test_render_only_unifies(self):
        write_out(self.out, VARIANT_PARAS)
        from test_auto_minutes import notes_result
        d = notes_result("course", examples=[], resources=[], next_session={"time": "", "topic": ""})
        d["summary"] = ["用 notebooklm 讀 pdf。"]
        self.use(AmFake([d]))
        with contextlib.redirect_stderr(io.StringIO()):
            self.run_am(cfg={}, content_type="course")
            md = (self.out / "notes.md").read_text(encoding="utf-8")
            self.assertIn("用 NotebookLM 讀 PDF。", md)
            n = json.loads((self.out / "notes.json").read_text(encoding="utf-8"))
            self.assertIn("用 notebooklm 讀 pdf。", n["data"]["summary"])                     # notes.json 不改
            (self.out / "notes.md").unlink()
            r = am.render_only(self.out, cfg={})
        self.assertEqual(r["status"], "ok")
        self.assertIn("用 NotebookLM 讀 PDF。", (self.out / "notes.md").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 單獨執行
@unittest.skipUnless(V22, "2.2.0 才有")
class Folder(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mmp-cs-dir-")) / "x_minutes"
        self.d.mkdir()
        body = ["# 校正版逐字稿：x.mp4", "", "> 原始逐字稿：`transcript.md`（未修改）", "", "## 校正摘要", "", "（自動校正沒有修改任何地方）",
                "", "---", ""]
        for i, (t, s, txt) in enumerate(VARIANT_PARAS):
            body += [f"**[{t}] {s}**：{txt}", ""]
        (self.d / "transcript.corrected.md").write_text("\n".join(body), encoding="utf-8")
        (self.d / "transcript.corrected.srt").write_text(SrtAndMarkdown.SRT, encoding="utf-8")
        (self.d / "notes.md").write_text("# 筆記\n\n> 自動整理：x\n\n- 用 notebooklm 讀 pdf\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.d.parent, ignore_errors=True)

    def test_dry_run_and_apply(self):
        before = {p.name: p.read_bytes() for p in self.d.iterdir()}
        r = cs.run_folder(self.d, cfg={}, dry_run=True, log=lambda m: None)
        self.assertEqual({p.name: p.read_bytes() for p in self.d.iterdir() if p.name != runlog.LOG_NAME}, before)
        self.assertEqual(r["files"], {"transcript.corrected.md": 3, "transcript.corrected.srt": 2, "notes.md": 2})
        r = cs.run_folder(self.d, cfg={}, log=lambda m: None)
        self.assertEqual((r["groups"], r["edits"]), (2, 5))
        names = sorted(p.name for p in self.d.iterdir())
        self.assertEqual(len([n for n in names if ".bak." in n]), 3)
        self.assertIn("- 用 NotebookLM 讀 PDF", (self.d / "notes.md").read_text(encoding="utf-8"))
        srt = (self.d / "transcript.corrected.srt").read_text(encoding="utf-8")
        self.assertEqual([l for l in srt.split("\n") if "-->" in l], [l for l in SrtAndMarkdown.SRT.split("\n") if "-->" in l])
        ev = runlog.read_events(self.d / runlog.LOG_NAME)
        cp = [e for e in ev if e.get("name") == "consistency"]
        self.assertEqual((cp[-1]["groups"], cp[-1]["edits"]), (2, 5))
        r2 = cs.run_folder(self.d, cfg={}, log=lambda m: None)                     # 再跑一次：沒有要改的
        self.assertEqual(r2["edits"], 0)

    def test_cli(self):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "consistency.py"), str(self.d), "--dry-run"],
                           capture_output=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        out = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])["consistency"]
        self.assertEqual((out["status"], out["dry_run"], out["edits"]), ("ok", True, 5))
        self.assertIn("NotebookLM ← notebooklm", p.stderr.decode("utf-8"))
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "consistency.py"), str(self.d / "nope")],
                           capture_output=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 2)


# ---------------------------------------------------------------- 關閉時與沒有這功能的版本相同
DISABLED_SCRIPT = r'''
import json, os, sys
args = json.loads(sys.argv[1])
os.environ["MMP_TEST_VERSION"] = args["version"]
sys.path.insert(0, args["tests"])
import _testenv
import auto_correct as ac
import auto_minutes as am
from pathlib import Path
sys.path.insert(0, args["tests"])
from test_auto_correct import FakeModel
from test_auto_minutes import Fake, result
be = {"provider": "claude", "channel": "cli", "exe": "x", "cli_version": "fake 1.0", "auth": "subscription", "note": None,
      "model": "opus", "effort": "medium", "model_api": "opus"}
ac.select_backend = lambda cfg, req, section=None: dict(be)
am.select_backend = lambda cfg, req, section=None: dict(be)
cfg = json.loads(args["cfg"])
ac.CALLERS[("claude", "cli")] = FakeModel(fix={"筆計本": "筆記本", "notebook lm 的介面": "notebooklm 的介面"})
req = {"provider": "claude", "channel": "cli", "model": None, "effort": None, "section": "correction"}
r1 = ac.run(args["out"], req, cfg=dict(cfg, correction={"chunk_chars": 40}), consent=True)
ac.CALLERS[("claude", "cli")] = Fake([result(summary=["介紹 notebooklm 與 Notebook LM 的用法。"])])
r2 = am.run(args["out"], dict(req, section="minutes"), cfg=cfg, html=False)
print(json.dumps({"correct": r1["status"], "minutes": r2["status"]}))
'''


@unittest.skipUnless(V22, "2.2.0 才有")
class DisabledSameAsV21(unittest.TestCase):
    """consistency.enabled: false 時，有寫法變體的輸入跑出的校正版，和沒有這功能的 2.1.0 逐位元相同
    （兩個版本各在獨立行程、同一個假模型）；開著時不同。會議記錄在 2.2.0 本來就改了〈轉寫品質備註〉的送出說明，
    不跨版本比（關閉時與拿掉步驟相同：MinutesRun.test_minutes_disabled）；這裡只比開與關不同。
    沒有 meeting-minutes-pro-v2.1.0 目錄時略過。"""

    def setUp(self):
        if not V21_SCRIPTS.is_dir():
            self.skipTest("沒有 meeting-minutes-pro-v2.1.0 目錄")
        self.root = Path(tempfile.mkdtemp(prefix="mmp-cs-reg-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_version(self, version, cfg):
        out = self.root / f"{version}-{len(list(self.root.iterdir()))}" / "demo_minutes"
        out.mkdir(parents=True)
        write_out(out, VARIANT_PARAS)
        home = self.root / f"home-{len(list(self.root.iterdir()))}"
        home.mkdir()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", MMP_TEST_VERSION=version,
                   MEETING_MINUTES_PRO_HOME=str(home), MMP_RUN_ID="")
        env.pop("MMP_RUN_ID")
        arg = json.dumps({"version": version, "tests": str(_testenv.HERE), "out": str(out), "cfg": json.dumps(cfg)})
        p = subprocess.run([sys.executable, "-B", "-c", DISABLED_SCRIPT, arg], capture_output=True, timeout=120, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace")[-2000:])
        self.assertEqual(json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1]), {"correct": "ok", "minutes": "ok"})
        md = (out / "meeting-minutes.md").read_text(encoding="utf-8")
        md = re.sub(r"2\.\d\.\d", "V", md)                                                   # 版號字樣
        return (out / "transcript.corrected.md").read_bytes(), md

    def test_disabled_identical(self):
        old = self.run_version("2.1.0", {})
        off = self.run_version(_testenv.VERSION, {"consistency": {"enabled": False}})
        on = self.run_version(_testenv.VERSION, {})
        self.assertEqual(off[0], old[0])
        self.assertNotEqual(on[0], old[0])
        self.assertNotEqual(on[1], off[1])
        self.assertIn("介紹 notebooklm 與 Notebook LM 的用法。", off[1])
        self.assertIn("介紹 NotebookLM 與 NotebookLM 的用法。", on[1])


if __name__ == "__main__":
    unittest.main()
