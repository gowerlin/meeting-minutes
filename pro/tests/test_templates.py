"""〔2.0.0〕自訂範本（templates.py；規格 §3.8）：驗證規則每一列（TP-1）、front matter 的有限語法、
入口的 list／使用者的 check、transcribe.load_template() 的介面。不呼叫任何模型。"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _testenv

V2 = _testenv.VER >= (2, 0, 0)
if V2:
    import content_types
    import templates as tm

GOOD = """---
name: 週會（研發處）               # 必填，≤ 20 字
base: meeting                      # 必填：7 種內建代號之一
description: 研發處每週進度會議     # 選填，≤ 60 字
speakers: auto
cluster_threshold: 0.9
labels:
  actions: 本週待辦
version: 1
---

這一段不會送出（第一個 ## 標題之前）

## 整理重點
- 每個專案寫一個議題：進度百分比、遇到的阻礙、需要誰協助
"""


def fm(**kv):
    """依鍵值組 front matter（值原樣寫入）＋一段整理重點。"""
    lines = ["---"] + [f"{k}: {v}" for k, v in kv.items()] + ["---", "", "## 整理重點", "- 重點一"]
    return "\n".join(lines) + "\n"


@unittest.skipUnless(V2, "2.0.0 才有")
class Base(unittest.TestCase):
    def setUp(self):
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = Path(tempfile.mkdtemp(prefix="mmp-tpl-"))
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self.dir = self.home / "templates"
        self.dir.mkdir()

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.home, ignore_errors=True)

    def put(self, code, text, encoding="utf-8"):
        p = self.dir / f"{code}.md"
        p.write_bytes(text.encode(encoding) if isinstance(text, str) else text)
        return p

    def invalid(self, code, text):
        self.put(code, text)
        with self.assertRaises(tm.TemplateInvalid) as cm:
            tm.load(code)
        return cm.exception


class Valid(Base):
    def test_full_example(self):
        self.put("weekly", GOOD)
        t = tm.load("weekly")
        self.assertEqual((t["code"], t["name"], t["base"], t["description"], t["speakers"], t["cluster_threshold"]),
                         ("weekly", "週會（研發處）", "meeting", "研發處每週進度會議", "auto", 0.9))
        self.assertEqual(t["labels"], {"actions": "本週待辦"})
        self.assertEqual(t["prompt"], "- 每個專案寫一個議題：進度百分比、遇到的阻礙、需要誰協助")
        self.assertEqual((t["prompt_chars"], t["prompt_truncated"], t["notes"]), (len(t["prompt"]), False, []))
        for k in ("code", "name", "base", "speakers", "cluster_threshold", "prompt_chars", "prompt_truncated"):
            self.assertIn(k, t)                                  # transcribe.load_template() 的介面（2.0.0）

    def test_speakers_values_and_quotes_bom_crlf(self):
        self.put("a", chr(0xFEFF) + fm(name='"課程 A"', base="'course'", speakers=3).replace("\n", "\r\n"))
        t = tm.load("a")
        self.assertEqual((t["name"], t["base"], t["speakers"]), ("課程 A", "course", 3))
        self.put("b", fm(name="略過", base="tutorial", speakers="skip"))
        self.assertEqual(tm.load("b")["speakers"], "skip")
        self.put("c", fm(name="只有必填", base="panel"))
        c = tm.load("c")
        self.assertEqual((c["speakers"], c["cluster_threshold"], c["labels"], c["description"]), (None, None, {}, ""))

    def test_prompt_after_first_h2_only_and_empty(self):
        self.put("x", "---\nname: n\nbase: course\n---\n前言不算\n## 第一節\nA\n## 第二節\nB\n")
        self.assertEqual(tm.load("x")["prompt"], "A\n## 第二節\nB")
        self.put("y", "---\nname: n\nbase: course\n---\n沒有標題\n")
        self.assertEqual(tm.load("y")["prompt"], "")

    def test_truncate_prompt(self):
        self.put("long", fm(name="長", base="course").replace("- 重點一", "字" * 2500))
        t = tm.load("long")
        self.assertEqual((t["prompt_chars"], t["prompt_truncated"]), (2000, True))
        self.assertEqual(t["notes"], ["自訂範本 long.md 的整理重點超過 2,000 字，只用前 2,000 字"])

    def test_labels_allowed_keys_per_base(self):
        for code in content_types.CODES:
            keys = content_types.label_keys(code)
            self.assertIn("summary", keys)
            self.put("lb", "---\nname: n\nbase: %s\nlabels:\n  %s: 新標題\n---\n" % (code, keys[-1]))
            self.assertEqual(tm.load("lb")["labels"], {keys[-1]: "新標題"})


class Invalid(Base):
    """TP-1：規格 §3.8.3 每一列各一個檔：reason 與訊息。"""

    def test_parse_error(self):
        for text, line in (("沒有設定區\n## 重點\n", 1), ("---\nname: n\nbase: meeting\n", 3),
                           ("---\nname: n\nbase: meeting\n- 清單\n---\n", 4), ("---\nname: |\n  多行\nbase: meeting\n---\n", 2),
                           ("---\nname: &a n\nbase: meeting\n---\n", 2), ("---\nname: n\n    deep: 1\nbase: meeting\n---\n", 3),
                           ("---\nname: n\nname: m\nbase: meeting\n---\n", 3), ("---\nname: \"沒配對\nbase: meeting\n---\n", 2)):
            with self.subTest(text=text):
                ex = self.invalid("p", text)
                self.assertEqual(ex.reason, "parse_error")
                self.assertEqual(ex.message, f"自訂範本 p.md 沒有載入：開頭的 --- 設定區讀不懂（第 {line} 行）")

    def test_missing_key(self):
        ex = self.invalid("m", fm(base="meeting"))
        self.assertEqual((ex.reason, ex.message), ("missing_key", "自訂範本 m.md 沒有載入：缺少 name（必填）"))
        ex = self.invalid("m", fm(name="n"))
        self.assertEqual((ex.reason, ex.base), ("missing_key", None))
        self.assertIn("缺少 base（必填）", ex.message)

    def test_bad_base(self):
        ex = self.invalid("b", fm(name="n", base="lecture"))
        self.assertEqual(ex.reason, "bad_base")
        self.assertEqual(ex.message, "自訂範本 b.md 沒有載入：base 只能是 meeting、course、interview、tutorial、panel、workshop、requirements")

    def test_unknown_key_rejects_whole_file(self):
        for key in ("model", "flags", "files", "provider", "tools"):
            with self.subTest(key=key):
                ex = self.invalid("u", fm(name="n", base="course", **{key: "x"}))
                self.assertEqual((ex.reason, ex.base), ("unknown_key", "course"))
                self.assertEqual(ex.message, f"自訂範本 u.md 沒有載入：不認得的設定 {key}。範本只能改名稱、講者設定與整理重點，"
                                             "模型、指令與送出的檔案由程式決定")

    def test_bad_value(self):
        for kv, frag in (({"speakers": 0}, "speakers 只能是"), ({"speakers": 21}, "speakers 只能是"),
                         ({"speakers": "two"}, "speakers 只能是"), ({"cluster_threshold": 1.3}, "0.5～1.2"),
                         ({"cluster_threshold": -1}, "0.5～1.2"), ({"cluster_threshold": "abc"}, "0.5～1.2"),
                         ({"version": 2}, "version 目前只能是 1"), ({"name": "名" * 21}, "name 最多 20 字"),
                         ({"description": "說" * 61}, "description 最多 60 字"), ({"labels": "x"}, "labels 底下")):
            with self.subTest(kv=kv):
                args = dict({"name": "n", "base": "course"}, **kv)
                ex = self.invalid("v", fm(**args))
                self.assertEqual(ex.reason, "bad_value")
                self.assertIn(frag, ex.message)
        ex = self.invalid("v", "---\nname: n\nbase: course\nlabels:\n  actions: 待辦\n---\n")
        self.assertEqual(ex.reason, "bad_value")
        self.assertIn("labels 的 actions 不是 course 的欄位；可用的欄位：summary、chapters", ex.message)

    def test_bad_file(self):
        ex = self.invalid("big", fm(name="n", base="course") + "x" * (16 * 1024))
        self.assertEqual(ex.reason, "bad_file")
        self.assertIn("檔案超過 16 KB", ex.message)
        for code in ("course", "Meeting", "README", "readme"):
            with self.subTest(code=code):
                p = self.put(code, fm(name="n", base="course"))
                with self.assertRaises(tm.TemplateInvalid) as cm:
                    tm.load_file(p)
                self.assertEqual(cm.exception.reason, "bad_file")
                p.unlink()
        for code in ("週會", "a b", "x" * 33, "../x"):
            with self.subTest(code=code), self.assertRaises(tm.TemplateInvalid) as cm:
                tm.load(code)
            self.assertEqual(cm.exception.reason, "bad_file")
        self.put("gbk", fm(name="中文", base="course"), encoding="big5")
        with self.assertRaises(tm.TemplateInvalid) as cm:
            tm.load("gbk")
        self.assertEqual(cm.exception.reason, "bad_file")

    def test_secret_like(self):
        for s in ("sk-" + "a" * 24, "hf_" + "B" * 30, "ANTHROPIC_API_KEY=x", "OPENAI_API_KEY"):
            with self.subTest(s=s[:6]):
                ex = self.invalid("s", fm(name="n", base="course") + f"\n- {s}\n")
                self.assertEqual((ex.reason, ex.message), ("secret_like", "自訂範本 s.md 沒有載入：內容看起來含有金鑰，範本不應包含金鑰"))
        self.put("ok", fm(name="n", base="course") + "\n- 討論 hf_short 與 sk-1 這種短字串不算\n")
        self.assertEqual(tm.load("ok")["base"], "course")

    def test_not_found(self):
        with self.assertRaises(tm.TemplateInvalid) as cm:
            tm.load("nothere")
        self.assertEqual(cm.exception.reason, "not_found")


class ListAndCheck(Base):
    def test_list_all(self):
        self.put("weekly", GOOD)
        self.put("bad", fm(name="n", base="course", model="opus"))
        (self.dir / "README.md").write_text("# 說明，不是範本\n", encoding="utf-8")
        rows = tm.list_all()
        self.assertEqual([r["code"] for r in rows], ["bad", "weekly"])
        self.assertEqual([(r["valid"], r["reason"]) for r in rows], [(False, "unknown_key"), (True, None)])
        self.assertEqual(rows[1]["name"], "週會（研發處）")
        self.assertEqual(tm.list_all(self.home / "none"), [])

    def run_cli(self, *args):
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "templates.py"), *args], capture_output=True,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"), timeout=60)
        return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")

    def test_cli_list_and_check(self):
        self.put("weekly", GOOD)
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.strip().splitlines()[-1]),
                         [{"code": "weekly", "name": "週會（研發處）", "base": "meeting", "description": "研發處每週進度會議",
                           "speakers": "auto", "valid": True, "reason": None, "message": None}])   # 〔2.0.0〕加 message
        bad0 = self.put("old", fm(name="n", base="meeting", model="opus"))
        rc, out, _ = self.run_cli("list")                           # 〔2.0.0〕無效的範本：入口在選單下方印 message
        row = [r for r in json.loads(out.strip().splitlines()[-1]) if r["code"] == "old"][0]
        self.assertEqual((row["valid"], row["reason"]), (False, "unknown_key"))
        self.assertTrue(row["message"].startswith("自訂範本 old.md 沒有載入：不認得的設定 model"))
        bad0.unlink()
        rc, out, _ = self.run_cli("check")
        self.assertEqual(rc, 0)
        self.assertIn("[OK] weekly.md：週會（研發處）（base: meeting）", out)
        bad = self.put("bad", fm(name="n", base="course", flags="--yolo"))
        rc, out, _ = self.run_cli("check", str(bad), str(self.dir / "weekly.md"))
        self.assertEqual(rc, 2)
        self.assertIn("[X] 自訂範本 bad.md 沒有載入：不認得的設定 flags", out)
        self.assertNotIn("--yolo", out)                               # 不印範本內容
        rc, _, _ = self.run_cli("nope")
        self.assertEqual(rc, 2)

    def test_log_fields_have_no_content(self):
        self.put("weekly", GOOD)
        f = tm.log_fields(tm.load("weekly"))
        self.assertEqual(set(f), {"code", "base", "valid", "prompt_chars", "prompt_truncated"})
        ex = tm.TemplateInvalid("unknown_key", "msg", "course", "bad")
        self.assertEqual(tm.log_fields(ex=ex), {"code": "bad", "base": "course", "valid": False, "reason": "unknown_key"})


class TranscribeInterface(Base):
    """transcribe.load_template()（I-1，不改 transcribe.py）照 templates.load() 的介面運作。"""

    def test_load_template(self):
        import transcribe
        self.put("weekly", GOOD.replace("speakers: auto", "speakers: 4"))
        t = transcribe.load_template("weekly")
        self.assertEqual((t["ok"], t["base"], t["speakers"], t["cluster_threshold"]), (True, "meeting", 4, 0.9))
        self.put("bad", fm(name="n", base="course", tools="x"))
        t = transcribe.load_template("bad")
        self.assertEqual((t["ok"], t["reason"], t["base"]), (False, "unknown_key", "course"))
        self.assertIn("不認得的設定 tools", t["message"])
        t = transcribe.load_template("missing")
        self.assertEqual((t["ok"], t["reason"]), (False, "not_found"))


if __name__ == "__main__":
    unittest.main()
