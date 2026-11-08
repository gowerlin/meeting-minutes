"""單元測試：解析、狀態、人工修改、定稿、字幕（Pro map_corrected）、經驗、匯入（Pro corrections）、名詞同步、接續帶入、Pro 偵測。

  python -B test_units.py          （或經由 run_tests.py）

Pro 的模組從 repo 內 Pro 版本目錄唯讀 import；$MMH 是暫存區的假資料夾。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers as H  # noqa: E402

WORK = H.workdir("mmproof-unit-")
HOME = H.make_home(WORK)
H.apply_env(HOME)
import mmproof_model as M  # noqa: E402
import mmproof_pro as P  # noqa: E402

CHK = P.check(HOME)
assert CHK["ok"], CHK
PRO = CHK["pro"]
DEMO = H.materials.make_all(WORK / "demo")


def load(name="D1", text=None):
    t = text if text is not None else (DEMO[name] / "transcript.corrected.md").read_text(encoding="utf-8")
    return M.parse_corrected(t, PRO.key_of)


def mk(doc_text: str):
    return M.parse_corrected(doc_text, PRO.key_of)


def sess_for(doc, marks=None, manual=None):
    s = M.empty_session("transcript.corrected.md", "x")
    s["marks"] = marks or {}
    s["manual"] = manual or []
    return s


def find(doc, kind, orig=None):
    return [m for m in M.all_marks(doc) if m["kind"] == kind and (orig is None or m["orig"] == orig)]


# ---------------------------------------------------------------- 解析
class Parse(unittest.TestCase):
    def test_mark_re_identical_to_pro(self):
        self.assertEqual(M.MARK_PATTERN, PRO.m["consistency"].MARK_RE.pattern)
        self.assertEqual(M.HEAD_RE.pattern, PRO.m["subtitles"].HEAD.pattern)

    def test_kinds(self):
        d = mk("---\n\n**[00:00:01] S1**：A{星荷→星河}B{謝謝→}C{→在}D{kafka→Kafka}E[?七月三號｜七月十三號]F[?滑頂]G\n")
        kinds = [(m["kind"], m["orig"], m["sugg"], m["guess"]) for m in M.all_marks(d)]
        self.assertEqual(kinds, [("fix", "星荷", "星河", None), ("delete", "謝謝", "", None), ("insert", "", "在", None),
                                 ("unify", "kafka", "Kafka", None), ("uncertain", "七月三號", None, "七月十三號"),
                                 ("uncertain", "滑頂", None, None)])

    def test_unify_uses_key_of(self):
        d = mk("---\n\n**[00:00:01] S1**：{notebook lm→NotebookLM}{Notebook-LM→NotebookLM}{Redis→Redix}\n")
        self.assertEqual([m["kind"] for m in M.all_marks(d)], ["unify", "unify", "fix"])

    def test_header_body_split_and_speakers(self):
        d = load("D1")
        self.assertEqual(len(M.paragraphs(d)), 12)
        self.assertEqual(d["speakers"][0], ["S1", "王小明", "合成示範"])
        self.assertEqual(d["title"], "校正版逐字稿：D1-demo.wav")
        self.assertTrue(any(b["t"] == "line" and b["text"].startswith("> 🖼") for b in d["body"]))

    def test_d1_counts(self):
        from collections import Counter
        c = Counter(m["kind"] for m in M.all_marks(load("D1")))
        self.assertEqual(dict(c), {"fix": 6, "unify": 4, "uncertain": 2, "insert": 1, "delete": 1})

    def test_continuation_line(self):
        d = mk("---\n\n**[0:00:01] S1**：第一行{星荷→星河}\n接著的一行\n\n> 註記不接\n")
        p = M.paragraphs(d)[0]
        self.assertEqual(p["time"], "00:00:01")
        self.assertEqual(M.para_raw(p), "第一行{星荷→星河}接著的一行")
        self.assertTrue(any(b["t"] == "line" and b["text"] == "> 註記不接" for b in d["body"]))

    def test_no_separator(self):
        d = mk("**[00:00:01] S1**：沒有分隔線也是本文\n")
        self.assertEqual(len(M.paragraphs(d)), 1)
        self.assertEqual(d["speakers"], [])

    def test_original_only(self):
        d = load(text=(DEMO["D1"] / "transcript.md").read_text(encoding="utf-8"))
        self.assertEqual(len(M.paragraphs(d)), 12)
        self.assertEqual(M.all_marks(d), [])

    def test_ids_stable(self):
        a, b = load("D1"), load("D1")
        self.assertEqual([m["id"] for m in M.all_marks(a)], [m["id"] for m in M.all_marks(b)])
        self.assertEqual(M.all_marks(a)[0]["id"], "m0-0")


# ---------------------------------------------------------------- 狀態
class States(unittest.TestCase):
    TABLE = [  # (kind, decision, state, value)
        ("fix", None, "pending", "星河"), ("fix", {"choice": "suggest"}, "accepted", "星河"),
        ("fix", {"choice": "orig"}, "rejected", "星荷"), ("fix", {"choice": "free", "value": "星合"}, "edited", "星合"),
        ("delete", None, "pending", ""), ("delete", {"choice": "suggest"}, "accepted", ""), ("delete", {"choice": "orig"}, "rejected", "謝謝"),
        ("insert", None, "pending", "在"), ("insert", {"choice": "suggest"}, "accepted", "在"), ("insert", {"choice": "orig"}, "rejected", ""),
        ("unify", {"choice": "suggest"}, "accepted", "Kafka"), ("unify", {"choice": "orig"}, "rejected", "kafka"),
        ("uncertain", None, "pending", "七月三號〔?七月十三號〕"), ("uncertain", {"choice": "guess"}, "accepted", "七月十三號"),
        ("uncertain", {"choice": "suggest"}, "accepted", "七月十三號"), ("uncertain", {"choice": "orig"}, "accepted", "七月三號"),
        ("uncertain", {"choice": "free", "value": "七月二十三號"}, "edited", "七月二十三號"),
    ]

    def test_state_table(self):
        d = mk("---\n\n**[00:00:01] S1**：{星荷→星河}{謝謝→}{→在}{kafka→Kafka}[?七月三號｜七月十三號]\n")
        by = {m["kind"]: m for m in M.all_marks(d)}
        for kind, dec, st, val in self.TABLE:
            with self.subTest(kind=kind, dec=dec):
                self.assertEqual(M.mark_state(by[kind], dec), st)
                self.assertEqual(M.mark_value(by[kind], dec), val)

    def test_uncertain_without_guess(self):
        d = mk("---\n\n**[00:00:01] S1**：[?滑頂]\n")
        m = M.all_marks(d)[0]
        self.assertEqual(M.mark_value(m, None), "滑頂〔?〕")
        self.assertEqual(M.mark_value(m, {"choice": "suggest"}), "滑頂")
        self.assertEqual(M.mark_value(m, None, final=False), "滑頂")

    def test_progress_counts_manual(self):
        d = load("D1")
        s = sess_for(d, {"m0-0": {"choice": "suggest"}, "m0-2": {"choice": "orig"}},
                     [{"id": "u1", "para": 11, "start": 0, "end": 1, "orig": "好", "value": "嗯"}])
        pg = M.progress(M.with_manual(d, s), s)
        self.assertEqual((pg["total"], pg["manual"], pg["accepted"], pg["rejected"], pg["edited"]), (15, 1, 1, 1, 1))
        self.assertEqual(pg["done"], 3)
        self.assertEqual(pg["pending"], 12)

    def test_clean_decisions(self):
        d = load("D1")
        marks, err = M.clean_decisions(d, {"m0-0": {"choice": "suggest"}, "zz": {"choice": "suggest"}, "m0-1": {"choice": "bad"}})
        self.assertEqual((marks, err), ({"m0-0": {"choice": "suggest"}}, None))
        _, err = M.clean_decisions(d, {"m0-0": {"choice": "free", "value": "a{b"}})
        self.assertIn("不能含", err)

    def test_same_marks_grouping_key(self):
        """一起套用：同種類、同原文、同建議、同推測（前端用同樣的鍵）。D1 有 3 處 星荷→星河。"""
        ms = find(load("D1"), "fix", "星荷")
        self.assertEqual(len(ms), 3)
        self.assertEqual(len({(m["kind"], m["orig"], m["sugg"], m["guess"]) for m in ms}), 1)


# ---------------------------------------------------------------- 人工修改
class Manual(unittest.TestCase):
    def setUp(self):
        self.d = mk("---\n\n**[00:00:01] S1**：前面的密等字{星荷→星河}後面的退幣字\n")
        self.raw = M.para_raw(M.paragraphs(self.d)[0])

    def u(self, text, value="X", uid="u1", start=None):
        s = self.raw.index(text) if start is None else start
        return {"id": uid, "para": 0, "start": s, "end": s + len(text), "orig": text, "value": value}

    def test_ok_and_adjacent_to_mark_and_edges(self):
        ok = [self.u("前面", "之前", "u1"), self.u("字", "字", "u2", self.raw.index("{") - 1),
              self.u("後面", "之後", "u3"), self.u("字", "字", "u4", len(self.raw) - 1)]
        self.assertIsNone(M.check_manual(self.d, ok))
        toks = M.paragraphs(M.with_manual(self.d, sess_for(self.d, manual=ok)))[0]["tokens"]
        self.assertEqual([t["kind"] for t in toks if t["t"] == "mark"], ["manual", "manual", "fix", "manual", "manual"])

    def test_rule1_cross_mark(self):
        s = self.raw.index("字{")
        bad = {"id": "u1", "para": 0, "start": s, "end": s + 5, "orig": self.raw[s:s + 5], "value": "x"}
        self.assertIn("跨到標記", M.check_manual(self.d, [bad]))

    def test_rule2_orig_mismatch(self):
        self.assertIn("對不上", M.check_manual(self.d, [dict(self.u("前面"), orig="別的")]))

    def test_rule3_overlap(self):
        self.assertIn("重疊", M.check_manual(self.d, [self.u("前面的", uid="u1"), self.u("面的密", uid="u2")]))

    def test_rule4_bad_value(self):
        for v in ("a{b", "a}b", "a[?b", "a\nb"):
            with self.subTest(v=v):
                self.assertIn("不能含", M.check_manual(self.d, [self.u("前面", v)]))

    def test_final_keeps_text_outside(self):
        s = sess_for(self.d, {"m0-0": {"choice": "suggest"}}, [self.u("密等", "冪等")])
        full = M.with_manual(self.d, s)
        self.assertEqual(M.final_paragraph(M.paragraphs(full)[0], s), "前面的冪等字星河後面的退幣字")
        self.assertEqual(M.resolved_marked(M.paragraphs(full)[0], s), "前面的{密等→冪等}字{星荷→星河}後面的退幣字")


# ---------------------------------------------------------------- 定稿
class Final(unittest.TestCase):
    def test_final_markdown(self):
        d = load("D1")
        dec, manual = H.d1_decisions({"doc": d})
        s = sess_for(d, dec, manual)
        full = M.with_manual(d, s)
        md = M.final_markdown(full, s, "transcript.corrected.md", "2026-01-01 10:00", "D1-demo.wav")
        body = md.split("\n---\n", 1)[1]
        self.assertNotRegex(body, r"[{}]|\[\?")
        self.assertIn("# 定稿逐字稿：D1-demo.wav", md)
        self.assertIn("| S1 | 王小明 | 合成示範 |", md)
        self.assertIn("> 🖼 `[00:00:05]`", body)
        self.assertNotIn("## 校正摘要", md)
        self.assertNotIn("## 待確認", md)
        for w in ("冪等", "退避", "星河", "七月十三號", "Redis", "NotebookLM", "跟滑頂確認一下在週三前"):
            self.assertIn(w, body)
        self.assertNotIn("謝謝觀看", body)
        import auto_minutes                       # Pro 的摘要讀定稿的方式（parse_paragraphs corrected=True）
        paras = auto_minutes.parse_paragraphs(md, corrected=True)
        self.assertEqual(len(paras), 12)
        self.assertEqual(paras[0]["time"], "00:00:00")

    def test_pending_rules(self):
        d = load("D1")
        s = sess_for(d)
        md = M.final_markdown(M.with_manual(d, s), s, "transcript.corrected.md", "t", "x")
        self.assertIn("七月三號〔?七月十三號〕", md)
        self.assertIn("滑頂〔?〕", md)
        self.assertIn("星河物流", md)
        self.assertIn("未處理 14", md)

    def test_original_source_header(self):
        d = load(text=(DEMO["D1"] / "transcript.md").read_text(encoding="utf-8"))
        s = sess_for(d)
        md = M.final_markdown(d, s, "transcript.md", "t", "D1-demo.wav")
        self.assertIn("沒有校正版", md)
        self.assertIn("# 定稿逐字稿：D1-demo.wav", md)


# ---------------------------------------------------------------- 字幕（Pro map_corrected）
def srt_texts(srt: str) -> list:
    """每條字幕的內容字元（去掉講者標籤「[S1] 」與標點：Pro 的字幕規則會拿掉行尾標點）。"""
    out = []
    for block in srt.strip().split("\n\n"):
        text = "".join(block.split("\n")[2:])
        out.append(M.content(re.sub(r"^\[[^\]]+\] ", "", text)))
    return out


def tiny(segs: list, cor_line: str, spk="S1"):
    """自訂辨識段＋一段校正版：回傳 (transcript.json 內容, doc)。"""
    t, segments = 0.0, []
    for x in segs:
        segments.append({"start": t, "end": t + 2.0, "speaker": spk, "text": x, "para": 0})
        t += 2.0
    tdoc = {"meta": {"source": "x.wav"}, "segments": segments}
    return tdoc, mk(f"---\n\n**[00:00:00] {spk}**：{cor_line}\n")


class Subtitles(unittest.TestCase):
    def run_srt(self, tdoc, d, marks=None, manual=None):
        if marks is None:
            marks = {m["id"]: {"choice": "suggest"} for m in M.all_marks(d)}
        s = sess_for(d, marks, manual)
        full = M.with_manual(d, s)
        srt, n, failed = PRO.final_srt(tdoc, M.resolved_corrected_text(full, s))
        return srt, n, failed

    def test_demo_folders_no_failure(self):
        for name in ("D1", "D2", "D3"):
            with self.subTest(name=name):
                d = load(name)
                tdoc = json.loads((DEMO[name] / "transcript.json").read_text(encoding="utf-8"))
                srt, n, failed = self.run_srt(tdoc, d)
                self.assertEqual(failed, 0)
                self.assertGreater(n, 0)
                self.assertNotRegex(srt, r"[{}]")

    def test_longer_and_shorter(self):
        tdoc, d = tiny(["我們用庫伯部署，", "然後是星荷系統。"], "我們用{庫伯→Kubernetes}部署，然後是{星荷系統→星河}。")
        srt, _, failed = self.run_srt(tdoc, d)
        self.assertEqual(failed, 0)
        self.assertEqual(srt_texts(srt), ["我們用Kubernetes部署", "然後是星河"])

    def test_delete_whole_segment(self):
        tdoc, d = tiny(["前面一句話，", "謝謝觀看，", "後面一句話。"], "前面一句話，{謝謝觀看，→}後面一句話。")
        srt, n, failed = self.run_srt(tdoc, d)
        self.assertEqual((failed, srt_texts(srt)), (0, ["前面一句話", "後面一句話"]))

    def test_insert(self):
        tdoc, d = tiny(["我們週三前回覆，", "就這樣。"], "我們{→在}週三前回覆，就這樣。")
        srt, _, failed = self.run_srt(tdoc, d)
        self.assertEqual(failed, 0)
        self.assertEqual(srt_texts(srt)[0], "我們在週三前回覆")

    def test_manual_edit(self):
        tdoc, d = tiny(["改成密等的介面，", "沒有標記。"], "改成密等的介面，沒有標記。")
        raw = M.para_raw(M.paragraphs(d)[0])
        s = raw.index("密等")
        srt, _, failed = self.run_srt(tdoc, d, {}, [{"id": "u1", "para": 0, "start": s, "end": s + 2, "orig": "密等", "value": "冪等"}])
        self.assertEqual((failed, srt_texts(srt)), (0, ["改成冪等的介面", "沒有標記"]))

    def test_cross_segment_mark(self):
        tdoc, d = tiny(["今天討論星", "荷的進度。"], "今天討論{星荷→星河}的進度。")
        srt, _, failed = self.run_srt(tdoc, d)
        self.assertEqual((failed, srt_texts(srt)), (0, ["今天討論星河", "的進度"]))

    def test_pending_uncertain_uses_original(self):
        tdoc, d = tiny(["日期是七月三號。"], "日期是[?七月三號｜七月十三號]。")
        srt, _, failed = self.run_srt(tdoc, d, {})
        self.assertEqual((failed, srt_texts(srt)), (0, ["日期是七月三號"]))

    def test_failed_paragraph_counted(self):
        tdoc, d = tiny(["原本的文字。"], "完全不同的文字。")
        _, _, failed = self.run_srt(tdoc, d)
        self.assertEqual(failed, 1)


# ---------------------------------------------------------------- 經驗整理
def d1_experience(rows=None, gloss=None, keeps=frozenset(), min_count=2, extra_marks=None):
    d = load("D1")
    dec, manual = H.d1_decisions({"doc": d})
    dec.update(extra_marks or {})
    s = sess_for(d, dec, manual)
    full = M.with_manual(d, s)
    orig = M.original_paragraphs((DEMO["D1"] / "transcript.md").read_text(encoding="utf-8"))
    return M.experience(full, s, orig, rows if rows is not None else [("酷伯內蒂斯", "Kubernetes", "")],
                        gloss if gloss is not None else {"星河物流"}, keeps, PRO.common_words, min_count)


class Experience(unittest.TestCase):
    def by(self, ex):
        return {(c["wrong"], c["right"]): c for c in ex["corrections"]}

    def test_default_checks(self):
        c = self.by(d1_experience())
        self.assertTrue(c[("星荷", "星河")]["checked"])
        self.assertTrue(c[("瑞迪斯", "Redis")]["checked"])
        self.assertTrue(c[("退幣", "退避")]["checked"])
        self.assertIn("不是每處都改成這個寫法（原文 2 處、改 1 處）", c[("全線", "權限")]["why"])
        self.assertIn("本場只出現 1 次", c[("密等", "冪等")]["why"])
        self.assertIn("刪除", c[("謝謝觀看", "")]["why"])
        self.assertFalse(c[("七月三號", "七月十三號")]["checked"])

    def test_condition_short(self):
        c = self.by(d1_experience(extra_marks={"m7-2": {"choice": "free", "value": "再"}}))
        self.assertNotIn(("", "再"), c)          # 補字沒有原文，不進建議
        d = mk("---\n\n**[00:00:01] S1**：{甲→乙}與{甲→乙}\n")
        s = sess_for(d, {m["id"]: {"choice": "suggest"} for m in M.all_marks(d)})
        ex = M.experience(d, s, ["甲與甲"], [], set(), frozenset(), PRO.common_words, 2)
        self.assertIn("太短（少於 2 字）", ex["corrections"][0]["why"])

    def test_condition_min_count(self):
        c = self.by(d1_experience(min_count=4))
        self.assertIn("本場只出現 3 次", c[("星荷", "星河")]["why"])
        c = self.by(d1_experience(min_count=1))
        self.assertTrue(c[("密等", "冪等")]["checked"])

    def test_condition_conflicts(self):
        c = self.by(d1_experience(rows=[("星荷", "星河", "x")]))
        self.assertEqual(c[("星荷", "星河")]["why"], ["已在對照表"])
        self.assertFalse(c[("星荷", "星河")]["importable"])
        c = self.by(d1_experience(rows=[("星荷", "興和", "x")]))
        self.assertFalse(c[("星荷", "星河")]["importable"])
        self.assertIn("對照表已有「星荷 → 興和」", c[("星荷", "星河")]["why"])
        c = self.by(d1_experience(rows=[("星河", "銀河", "x")]))
        self.assertIn("與對照表衝突", c[("星荷", "星河")]["why"])
        c = self.by(d1_experience(rows=[("某某", "瑞迪斯", "x")]))
        self.assertIn("與對照表衝突", c[("瑞迪斯", "Redis")]["why"])

    def test_condition_keep_glossary_common(self):
        c = self.by(d1_experience(keeps={"星荷"}))
        self.assertIn("OpenCC 回復表的詞", c[("星荷", "星河")]["why"])
        c = self.by(d1_experience(gloss={"瑞迪斯"}))
        self.assertIn("詞表裡的詞", c[("瑞迪斯", "Redis")]["why"])
        d = mk("---\n\n**[00:00:01] S1**：{note→Node}{note→Node}\n")
        s = sess_for(d, {m["id"]: {"choice": "suggest"} for m in M.all_marks(d)})
        ex = M.experience(d, s, ["notenote"], [], set(), frozenset(), PRO.common_words, 2)
        self.assertIn("一般英文單字", ex["corrections"][0]["why"])

    def test_phrase_and_glossary(self):
        ex = d1_experience(extra_marks={"m3-0": {"choice": "free", "value": "星河 物流"}})
        kinds = {(c["wrong"], c["right"]): c["kind"] for c in ex["corrections"]}
        self.assertEqual(kinds[("星荷", "星河 物流")], "片語")
        self.assertEqual(kinds[("瑞迪斯", "Redis")], "詞")
        gl = {g["term"]: g for g in ex["glossary"]}
        self.assertTrue(gl["Redis"]["checked"])
        self.assertTrue(gl["NotebookLM"]["checked"])
        self.assertTrue(gl["Kafka"]["checked"])
        self.assertFalse(gl["冪等"]["checked"])
        self.assertIn("中文詞預設不勾", gl["冪等"]["why"][0])
        self.assertNotIn("星河物流", gl)

    def test_pick_imports(self):
        ex = d1_experience()
        pairs, terms, skipped = M.pick_imports(ex, [{"wrong": "星荷", "right": "星河"}, {"wrong": "不存在", "right": "x"},
                                                   {"wrong": "全線", "right": "權限"}], ["NotebookLM", "亂寫"])
        self.assertEqual((pairs, terms, skipped), ([("星荷", "星河"), ("全線", "權限")], ["NotebookLM"], []))
        ex["corrections"].append(dict(ex["corrections"][0], right="星河2", importable=True))
        _, _, skipped = M.pick_imports(ex, [{"wrong": "星荷", "right": "星河"}, {"wrong": "星荷", "right": "星河2"}], [])
        self.assertEqual(skipped, [["星荷", "星河2"]])


# ---------------------------------------------------------------- 匯入（Pro corrections）
class Import(unittest.TestCase):
    def test_backup_append_keep_comments(self):
        home = H.make_home(WORK, "home-import")
        before = (home / "corrections.tsv").read_text(encoding="utf-8")
        cp = home / "corrections.tsv"
        mods = PRO.m["corrections"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(home)
        try:
            b = mods.backup("20260101-000000", cp)
            mods.append_rows([("星荷", "星河", "proofread:2026-01-01 D1-demo")], cp)
        finally:
            os.environ["MEETING_MINUTES_PRO_HOME"] = str(HOME)
        self.assertEqual(Path(b).read_text(encoding="utf-8"), before)
        after = cp.read_text(encoding="utf-8")
        self.assertTrue(after.startswith(before))
        self.assertIn("星荷\t星河\tproofread:2026-01-01 D1-demo\n", after)
        self.assertIn(("星荷", "星河", "proofread:2026-01-01 D1-demo"), mods.load(cp))

    def test_append_when_missing_writes_header(self):
        cp = WORK / "new-corrections.tsv"
        PRO.m["corrections"].append_rows([("甲乙", "丙丁", "proofread:x")], cp)
        self.assertTrue(cp.read_text(encoding="utf-8").startswith(PRO.m["corrections"].HEADER))


# ---------------------------------------------------------------- 名詞同步
class Sync(unittest.TestCase):
    def test_pairs_and_apply(self):
        d = load("D1")
        dec, manual = H.d1_decisions({"doc": d})
        s = sess_for(d, dec, manual)
        pairs = dict(M.sync_pairs(M.with_manual(d, s), s))
        self.assertEqual(pairs["星荷"], "星河")
        self.assertEqual(pairs["notebook lm"], "NotebookLM")
        self.assertNotIn("謝謝觀看", pairs)
        text = (DEMO["D1"] / "meeting-minutes.md").read_text(encoding="utf-8")
        new, hits = M.apply_pairs(text, list(pairs.items()))
        self.assertIn("這一行提到星荷不會被改", new)
        self.assertIn("程式區塊裡的星荷不會被改", new)
        self.assertIn("星河物流倉儲系統升級", new)
        self.assertEqual(hits["星荷"], 2)

    def test_longest_first_single_pass(self):
        new, hits = M.apply_pairs("星荷物流與星荷", [("星荷", "星河"), ("星荷物流", "星河物流公司"), ("星河", "不該連鎖")])
        self.assertEqual(new, "星河物流公司與星河")
        self.assertEqual(hits, {"星荷物流": 1, "星荷": 1})

    def test_render_html_regenerates(self):
        folder = WORK / "sync-html" / "D1-demo_minutes"
        shutil.copytree(DEMO["D1"], folder)
        self.assertEqual(PRO.render_html(folder, "meeting-minutes.md"), "ok")
        self.assertTrue((folder / "meeting-minutes.html").exists())


# ---------------------------------------------------------------- 接續帶入
class Carry(unittest.TestCase):
    def test_carry_rules(self):
        old_text = (DEMO["D1"] / "transcript.corrected.md").read_text(encoding="utf-8")
        old = mk(old_text)
        dec, manual = H.d1_decisions({"doc": old})
        s = sess_for(old, dec, manual)
        new_text = old_text.replace("{瑞迪斯→Redis}的快取", "{瑞迪斯→Redis}的快取（重跑）").replace(
            "{全線→權限}設計", "{全線→許可}設計").replace("改成密等，", "改成冪等，")
        new = mk(new_text)
        marks, man, info = M.carry_over(old, s, new)
        self.assertEqual(info["marks_total"], 14)
        self.assertEqual(info["marks"], 13)                  # 全線→許可 的建議不同：不帶
        self.assertEqual((info["manual"], info["manual_total"]), (2, 3))   # 密等 已不在新稿：不帶
        self.assertIsNone(M.check_manual(new, man))

    def test_same_group_in_order(self):
        old = mk("---\n\n**[00:00:01] S1**：{星荷→星河}A{星荷→星河}\n")
        s = sess_for(old, {"m0-0": {"choice": "orig"}, "m0-1": {"choice": "suggest"}})
        new = mk("---\n\n**[00:00:01] S1**：B{星荷→星河}A{星荷→星河}\n")
        marks, _, info = M.carry_over(old, s, new)
        self.assertEqual(marks, {"m0-0": {"choice": "orig"}, "m0-1": {"choice": "suggest"}})
        self.assertEqual(info["marks"], 2)


# ---------------------------------------------------------------- 暫存格式
class SessionFormat(unittest.TestCase):
    def test_major(self):
        self.assertEqual(M.session_major({"format": "mm-proofread-session/1"}), 1)
        self.assertEqual(M.session_major({"format": "mm-proofread-session/2"}), 2)
        self.assertIsNone(M.session_major({"format": "other"}))

    def test_normalize_keeps_values(self):
        s = M.normalize_session({"format": M.SESSION_FORMAT, "rev": 3, "marks": {"m0-0": {"choice": "orig"}}})
        self.assertEqual((s["rev"], s["marks"], s["log"], s["imports"]), (3, {"m0-0": {"choice": "orig"}}, [], []))

    def test_log_has_no_content(self):
        s = M.empty_session("a", "b")
        M.log_op(s, "定稿", ["transcript.final.md"], "12 段")
        self.assertEqual(set(s["log"][0]), {"at", "action", "files", "note"})


# ---------------------------------------------------------------- Pro 偵測（子行程：每種假 Pro 各自 import）
def check_cli(home: Path, scripts: Path, python_ok=True) -> tuple:
    env = H.base_env(home, scripts)
    if not python_ok:
        env["MMPROOF_PRO_PYTHON"] = str(home / "no-python.exe")
    r = subprocess.run([sys.executable, "-B", str(H.APP / "mmproof_pro.py"), "--check", "--home", str(home)],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    return r.returncode, json.loads(r.stdout)


class ProDetect(unittest.TestCase):
    def test_real_pro_passes(self):
        """repo 內最新的 Pro（〔1.1.0〕不寫死 2.2.0）通過相容檢查。"""
        code, res = check_cli(HOME, H.PRO_SCRIPTS)
        self.assertEqual((code, res["code"], res["version"]), (0, "ok", H.PRO_VERSION))

    def test_no_pro(self):
        empty = WORK / "no-pro-home"
        empty.mkdir(exist_ok=True)
        code, res = check_cli(empty, empty / "scripts")
        self.assertEqual((code, res["code"]), (2, "no_pro"))
        self.assertIn("請先安裝 meeting-minutes-pro 2.2.0 以上", res["message"])
        code, res = check_cli(HOME, H.PRO_SCRIPTS, python_ok=False)
        self.assertEqual((code, res["code"]), (2, "no_pro"))

    def test_too_old(self):
        fake = H.materials.make_fake_pro(H.PRO_SCRIPTS, WORK / "pro-210", version="2.1.0")
        code, res = check_cli(HOME, fake)
        self.assertEqual((code, res["code"], res["version"]), (2, "too_old", "2.1.0"))
        self.assertIn("太舊", res["message"])

    def test_incompatible_mark(self):
        fake = H.materials.make_fake_pro(H.PRO_SCRIPTS, WORK / "pro-mark", version="2.4.0", mark_pattern=r"\{([^}]*)\}")
        code, res = check_cli(HOME, fake)
        self.assertEqual((code, res["code"]), (2, "incompatible"))
        self.assertIn("不相容", res["message"])

    def test_incompatible_missing_name(self):
        fake = H.materials.make_fake_pro(H.PRO_SCRIPTS, WORK / "pro-drop", version="2.4.0", drop=(("subtitles", "recue"),))
        code, res = check_cli(HOME, fake)
        self.assertEqual((code, res["code"]), (2, "incompatible"))
        self.assertIn("subtitles.recue", res["missing"])

    def test_redo_gate(self):
        # 〔1.1.0〕repo 內的 Pro 取最新版：重做是否可用依實際版號
        self.assertEqual(PRO.redo_available, H.locate.vtuple(H.PRO_VERSION) >= (2, 3, 0))
        self.assertTrue(P.version_ge("2.3.0", P.REDO_MIN_PRO))
        self.assertTrue(P.version_ge("2.10.1", "2.3.0"))
        self.assertFalse(P.version_ge("2.2.9", "2.3.0"))

    def test_local_only_state(self):
        """〔1.1.0〕本機限定的判定：只看 $MMH/config.json 的 privacy.local_only 是 true 與輸出資料夾的 local-only.json。"""
        home, out = WORK / "lo-home", WORK / "lo-out"
        for d in (home, out):
            d.mkdir(exist_ok=True)
        (home / "config.json").write_text(json.dumps({"runtime_version": "2.2.0"}), encoding="utf-8")
        self.assertIsNone(P.local_only_state(home, out))
        for v in ("true", 1, None, False):
            (home / "config.json").write_text(json.dumps({"privacy": {"local_only": v}}), encoding="utf-8")
            self.assertIsNone(P.local_only_state(home, out), v)
        (home / "config.json").write_text("{壞掉的 JSON", encoding="utf-8")
        self.assertIsNone(P.local_only_state(home, out))
        (out / "local-only.json").write_text("", encoding="utf-8")
        st = P.local_only_state(home, out)
        self.assertEqual((st["sources"], st["source"]), (["marker"], "marker"))
        self.assertIn("刪除輸出資料夾裡的 local-only.json", st["message"])
        (home / "config.json").write_text(json.dumps({"privacy": {"local_only": True}}), encoding="utf-8")
        st = P.local_only_state(home, out)
        self.assertEqual(st["source"], "config+marker")
        self.assertIn("privacy.local_only 改成 false", st["message"])
        self.assertIn("「用定稿重做」會送出內容，所以停用", st["message"])
        self.assertEqual(P.local_only_state(home, None)["sources"], ["config"])

    def test_marker_name_matches_pro(self):
        """標記檔名與 Pro（2.4.0 起）common.LOCAL_ONLY_MARKER 相同；repo 內的 Pro 比 2.4.0 舊時只比對常數本身。"""
        self.assertEqual(P.LOCAL_ONLY_MARKER, "local-only.json")
        src = (H.PRO_SCRIPTS / "common.py").read_text(encoding="utf-8")
        if H.locate.vtuple(H.PRO_VERSION) >= (2, 4, 0):
            self.assertIn(f'LOCAL_ONLY_MARKER = "{P.LOCAL_ONLY_MARKER}"', src)

    def test_no_pycache_in_pro(self):
        self.assertEqual(list(H.PRO_SCRIPTS.rglob("__pycache__")), [])


def main() -> tuple:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    r = unittest.TextTestRunner(verbosity=1).run(suite)
    total = r.testsRun
    bad = len(r.failures) + len(r.errors)
    shutil.rmtree(WORK, ignore_errors=True)
    return total, total - bad, [str(t) for t, _ in r.failures + r.errors]


if __name__ == "__main__":
    t, ok, bad = main()
    print(f"units {ok}/{t} PASS")
    sys.exit(0 if ok == t else 1)
