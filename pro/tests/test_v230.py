"""〔2.3.0〕配合會議記錄校稿（規格 2.3.0）：
- §2 `auto_minutes.py --source final`（定稿逐字稿 transcript.final.md；auto 的順序 final ＞ corrected ＞ original；表頭與備註）
- §3 `auto_minutes.py --estimate-only`（不呼叫模型、不寫任何檔、預估 JSON 的欄位）
- §4 Pro 解除安裝時先以安靜模式執行會議記錄校稿的移除程式（PowerShell 7／5.1 實跑 install.ps1 -Uninstall；install.sh 的函式在 Git Bash 實跑）
- §5 安裝時保留 $MMH/proofread/（只刪 scripts/）
- §6 入口 --hotwords 用 Native-Arg（情境實測在 entry_harness.py 的 hotwords_special_chars）
- §7 tests/_testenv.py 預設取最新的版本目錄
- §8 會議記錄校稿相容性：校稿用到的 Pro 介面與 2.2.0 相同（沒有 2.2.0 目錄時略過）
不呼叫任何模型、不碰已安裝的 runtime。2.3.0 以前的版本整個略過。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import _testenv

V23 = _testenv.VER >= (2, 3, 0)
VD = _testenv.VERSION_DIR
INSTALL_PS1 = VD / "install.ps1"
INSTALL_SH = VD / "install.sh"
GIT_BASH = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))
V220 = _testenv.HERE.parent / "meeting-minutes-pro-v2.2.0"

if V23:
    import auto_correct as ac
    import auto_minutes as am
    from test_auto_minutes import Base, Fake, result
    from test_auto_correct import write_out
else:  # pragma: no cover
    Base = unittest.TestCase

PARAS = [("00:00:00", "S1", "今天確認星河物流倉儲系統升級的進度。"), ("00:01:00", "S2", "壓測已經達標，下週二上線。"),
         ("00:02:00", "S1", "權限文件由王小明負責。")]
FINAL_TEXTS = ["今天確認星河物流倉儲系統升級的進度，這是定稿。", "壓測已經達標，下週二上線（定稿）。", "權限文件由王小明負責（定稿）。"]


def write_corrected(d: Path, texts):
    body = [f"**[{t}] {s}**：{{錯字→{x}}}" for (t, s, _), x in zip(PARAS, texts)]
    d.joinpath("transcript.corrected.md").write_text(
        "\n".join(["# 校正版逐字稿：demo.wav", "", "> 校正：自動", "", "## 校正摘要", "", "---", ""] + sum(([b, ""] for b in body), [])),
        encoding="utf-8")


def write_final(d: Path, texts=FINAL_TEXTS):
    """規格（會議記錄校稿 1.0.0 §7.1）的定稿格式：表頭、〈講者對應〉、`---` 之後是沒有標記的本文。"""
    body = [f"**[{t}] {s}**：{x}" for (t, s, _), x in zip(PARAS, texts)]
    head = ["# 定稿逐字稿：demo.wav", "",
            "> 原始逐字稿：`transcript.md`（未修改）｜校正版：`transcript.corrected.md`｜定稿：會議記錄校稿 1.0.0，2026-11-08 11:20",
            "> 校稿：標記 3 處（確認 3、改 0、退回 0、未處理 0）、人工修改 0 處", "", "## 講者對應", "",
            "| 代號 | 姓名 | 依據 |", "|---|---|---|", "| S1 | 王小明 | 自我介紹 |", "", "---", ""]
    d.joinpath("transcript.final.md").write_text("\n".join(head + sum(([b, ""] for b in body), [])), encoding="utf-8")


def touch_older(p: Path, than: Path, sec=60):
    t = than.stat().st_mtime - sec
    os.utime(p, (t, t))


def snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): (p.stat().st_size, p.stat().st_mtime_ns) for p in d.rglob("*")}


@unittest.skipUnless(V23, "2.3.0 起")
class PickSource(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="mmp-v230-src-"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def files(self, *names):
        for n in names:
            (self.d / n).write_text("x", encoding="utf-8")

    def test_without_final_same_as_220(self):
        self.files("transcript.md", "transcript.corrected.md")
        self.assertEqual(am.pick_source(self.d, "auto"), (self.d / "transcript.corrected.md", None))
        self.assertEqual(am.pick_source(self.d, "corrected")[0].name, "transcript.corrected.md")
        self.assertEqual(am.pick_source(self.d, "original")[0].name, "transcript.md")
        (self.d / "transcript.corrected.md").unlink()
        self.assertEqual(am.pick_source(self.d, "auto"), (self.d / "transcript.md", None))
        self.assertEqual(am.pick_source(self.d, "final")[0].name, "transcript.final.md")   # 不退回其他檔
        self.assertFalse(am.pick_source(self.d, "final")[0].exists())

    def test_auto_prefers_final(self):
        self.files("transcript.md", "transcript.corrected.md", "transcript.final.md")
        self.assertEqual(am.pick_source(self.d, "auto"), (self.d / "transcript.final.md", None))
        self.assertEqual(am.pick_source(self.d, "corrected")[0].name, "transcript.corrected.md")   # 明確指定時照指定
        self.assertEqual(am.pick_source(self.d, "original")[0].name, "transcript.md")

    def test_auto_final_without_corrected(self):
        self.files("transcript.md", "transcript.final.md")
        self.assertEqual(am.pick_source(self.d, "auto")[0].name, "transcript.final.md")

    def test_auto_skips_stale_final(self):
        self.files("transcript.md", "transcript.corrected.md", "transcript.final.md")
        touch_older(self.d / "transcript.final.md", self.d / "transcript.corrected.md")
        p, note = am.pick_source(self.d, "auto")
        self.assertEqual(p.name, "transcript.corrected.md")
        self.assertIn("transcript.final.md 比 transcript.corrected.md 舊", note)
        self.assertIn("--source final", note)
        self.assertEqual(am.pick_source(self.d, "final"), (self.d / "transcript.final.md", None))   # 明確指定照用

    def test_labels(self):
        self.assertEqual(am.src_label("transcript.final.md"), "`transcript.final.md`（已人工校稿）")
        self.assertEqual(am.src_label("transcript.corrected.md"), "`transcript.corrected.md`")
        self.assertEqual(am.made_by("transcript.md"), "自動轉寫 + AI 自動整理")
        self.assertEqual(am.made_by("transcript.final.md"), "自動轉寫 + 人工校稿 + AI 自動整理")
        self.assertEqual(am.final_line("transcript.corrected.md"), [])
        self.assertTrue(am.is_marked("transcript.final.md") and am.is_marked("transcript.corrected.md"))
        self.assertFalse(am.is_marked("transcript.md"))

    def test_parse_final(self):
        write_final(self.d)
        ps = am.parse_paragraphs((self.d / "transcript.final.md").read_text(encoding="utf-8"), True)
        self.assertEqual([p["text"] for p in ps], FINAL_TEXTS)          # 〈講者對應〉表與表頭不送
        self.assertEqual([p["time"] for p in ps], ["00:00:00", "00:01:00", "00:02:00"])


@unittest.skipUnless(V23, "2.3.0 起")
class FinalRun(Base):
    def prepare(self, final=True, corrected=True):
        write_out(self.out, PARAS)
        if corrected:
            write_corrected(self.out, ["校正版一", "校正版二", "校正版三"])
        if final:
            write_final(self.out)

    def test_source_final(self):
        self.prepare()
        fake = Fake()
        self.use(fake)
        r = self.run_am(source="final", html=False)
        self.assertEqual((r["status"], r["source_file"]), ("ok", "transcript.final.md"))
        self.assertEqual(len(fake.calls), 1)
        user = fake.calls[0]["user"]
        for t in FINAL_TEXTS:
            self.assertIn(t, user)
        self.assertNotIn("校正版一", user)
        self.assertNotIn("王小明 | 自我介紹", user)
        md = (self.out / "meeting-minutes.md").read_text(encoding="utf-8")
        self.assertIn("｜依據：`transcript.final.md`（已人工校稿）｜一次整理｜", md)
        self.assertIn("自動轉寫 + 人工校稿 + AI 自動整理 |", md)
        self.assertIn("- 定稿逐字稿：`transcript.final.md`（已人工校稿），會議記錄校稿產生", md)
        self.assertIn("依據 `transcript.final.md`（已人工校稿），一次整理；", md)
        rec = json.loads((self.out / "auto_minutes.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["source_file"], "transcript.final.md")
        meta = json.loads((self.out / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["minutes"]["source_file"], "transcript.final.md")

    def test_auto_uses_final_and_html(self):
        self.prepare()
        self.use(Fake())
        r = self.run_am()                                      # auto、網頁版照設定（預設開）
        self.assertEqual(r["source_file"], "transcript.final.md")
        self.assertEqual(r["html"]["status"], "ok")
        page = (self.out / "meeting-minutes.html").read_text(encoding="utf-8")
        self.assertIn("transcript.final.md", page)
        self.assertIn("已人工校稿", page)

    def test_auto_stale_final_uses_corrected(self):
        self.prepare()
        touch_older(self.out / "transcript.final.md", self.out / "transcript.corrected.md")
        fake = Fake()
        self.use(fake)
        r = self.run_am(html=False)
        self.assertEqual(r["source_file"], "transcript.corrected.md")
        self.assertIn("校正版一", fake.calls[0]["user"])
        md = (self.out / "meeting-minutes.md").read_text(encoding="utf-8")
        self.assertNotIn("已人工校稿", md)
        self.assertNotIn("定稿逐字稿", md)

    def test_final_missing(self):
        self.prepare(final=False)
        fake = Fake()
        self.use(fake)
        r = self.run_am(source="final", html=False)
        self.assertEqual((r["status"], r["reason"]), ("failed", "no_transcript"))
        self.assertIn("transcript.final.md", r["message"])
        self.assertEqual(fake.calls, [])
        self.assertFalse((self.out / "meeting-minutes.md").exists())

    def test_auto_without_final_unchanged(self):
        self.prepare(final=False)
        self.use(Fake())
        r = self.run_am(html=False)
        self.assertEqual(r["source_file"], "transcript.corrected.md")
        md = (self.out / "meeting-minutes.md").read_text(encoding="utf-8")
        self.assertIn("｜依據：`transcript.corrected.md`｜", md)
        self.assertIn("自動轉寫 + AI 自動整理 |", md)
        self.assertNotIn("人工校稿", md)

    def test_notes_type_and_render_only(self):
        self.prepare()
        self.use(Fake([{"title": "課程", "summary": ["重點"], "participants": [], "uncertain": [], "questions": []}]))
        r = self.run_am(source="final", content_type="course", html=False)
        self.assertEqual((r["status"], r["output"]), ("ok", "notes.md"))
        notes = json.loads((self.out / "notes.json").read_text(encoding="utf-8"))
        self.assertEqual(notes["render"]["src"], "transcript.final.md")
        md = (self.out / "notes.md").read_text(encoding="utf-8")
        self.assertIn("｜依據：`transcript.final.md`（已人工校稿）｜", md)
        self.assertIn("自動轉寫 + 人工校稿 + AI 自動整理 |", md)
        self.assertIn("- 定稿逐字稿：`transcript.final.md`（已人工校稿），會議記錄校稿產生", md)
        (self.out / "notes.md").unlink()
        rr = am.render_only(self.out, cfg={}, html=False)                   # 不呼叫模型
        self.assertEqual(rr["status"], "ok")
        self.assertEqual((self.out / "notes.md").read_text(encoding="utf-8"), md)


@unittest.skipUnless(V23, "2.3.0 起")
class RunCost(Base):
    """§3.5：完成時 stdout 的 minutes 帶 cost_usd、cost_basis（本次 run_log 的 call 事件合計；沒有資訊時不加）。"""

    def calls_cost(self):
        evs = [json.loads(x) for x in (self.out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
        return [e.get("cost_usd") for e in evs if e.get("event") == "call"]

    def test_cost_in_result_and_stdout(self):
        write_out(self.out, PARAS)
        write_final(self.out)
        self.use(Fake())
        r = self.run_am(source="final", html=False)
        costs = self.calls_cost()
        self.assertGreaterEqual(len(costs), 1)
        self.assertTrue(all(c is not None for c in costs))
        self.assertAlmostEqual(r["cost_usd"], round(sum(costs), 6), places=6)
        self.assertEqual(r["cost_basis"], "subscription_equivalent")
        # 第二次（--force）只算這一次的呼叫
        r2 = self.run_am(source="final", html=False, force=True)
        self.assertAlmostEqual(r2["cost_usd"], round(sum(self.calls_cost()[len(costs):]), 6), places=6)

    def test_main_stdout(self):
        import contextlib
        import io
        write_out(self.out, PARAS)
        self.use(Fake())
        argv, buf = sys.argv, io.StringIO()
        sys.argv = ["auto_minutes.py", str(self.out), "--no-html", "--claude"]
        try:
            with contextlib.redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
                am.main()
        finally:
            sys.argv = argv
        self.assertEqual(cm.exception.code, 0)
        m = json.loads(buf.getvalue().strip().splitlines()[-1])["minutes"]
        self.assertAlmostEqual(m["cost_usd"], round(sum(self.calls_cost()), 6), places=6)
        self.assertEqual(m["cost_basis"], "subscription_equivalent")

    def test_omitted_without_info(self):
        write_out(self.out, PARAS)
        self.use(Fake(), model="fake-model-x")
        unknown = Fake()
        unknown_model = "fake-model-x"

        def call(be, system, user, timeout, schema=None):
            r = unknown(be, system, user, timeout, schema)
            r["model"] = unknown_model
            return r
        ac.CALLERS[("claude", "cli")] = call
        r = self.run_am(html=False)
        self.assertEqual(r["status"], "ok")
        self.assertNotIn("cost_usd", r)                          # 價格表沒有這個模型：不加鍵（不寫 0）
        (self.out / "meeting-minutes.md").write_text("x", encoding="utf-8")
        r = self.run_am(html=False)                              # 已有會議記錄、沒有呼叫
        self.assertEqual(r["status"], "skipped")
        self.assertNotIn("cost_usd", r)


@unittest.skipUnless(V23, "2.3.0 起")
class EstimateMath(unittest.TestCase):
    def be(self, provider, model):
        return {"provider": provider, "model": model, "channel": "cli", "effort": "medium", "auth": "subscription"}

    def test_measured(self):
        lo, hi, basis = am.estimate_usd(self.be("claude", "opus"), [2400])
        self.assertEqual(basis, "measured")
        self.assertEqual((lo, hi), (round(0.08 + 0.035 * 2.4, 3), round(0.17 + 0.045 * 2.4, 3)))
        lo, hi, basis = am.estimate_usd(self.be("claude", "claude-opus-5-5"), [2400])    # 完整 ID 也對得上
        self.assertEqual(basis, "measured")
        lo2, hi2, _ = am.estimate_usd(self.be("openai", "gpt-6.1-sol"), [9000, 9000])     # 分段：加彙整 1 次
        self.assertAlmostEqual(lo2, 2 * 0.025 + 0.010 * 18 + 0.05, places=3)
        self.assertAlmostEqual(hi2, 2 * 0.05 + 0.013 * 18 + 0.07, places=3)

    def test_f3_measurements_inside_range(self):
        """1.2.0 附錄 F.3 的實測（每小時錄音的 API 等價美元 × 錄音長度）落在預估範圍內。"""
        m1, m3 = [2400], [9144, 9144]          # M1 單段約 2.4 千字；M3 18,288 字分 2 段
        cases = {("openai", "gpt-6.1-sol"): (0.33 * 9.65 / 60, (0.22 * 79.3 / 60, 0.27 * 79.3 / 60)),
                 ("claude", "opus"): (1.18 * 9.65 / 60, (0.84 * 79.3 / 60, 0.92 * 79.3 / 60)),
                 ("claude", "sonnet"): (0.37 * 9.65 / 60, (0.35 * 79.3 / 60, 0.35 * 79.3 / 60))}
        # 有待釐清補判的實測：2.3.0 sol 427 字單段（part＋recheck）US$0.0455；2.2.0 opus 約 2.5 千字＋參考資料（part＋recheck）US$0.258
        self.assertTrue(am.estimate_usd(self.be("openai", "gpt-6.1-sol"), [427])[1] >= 0.0455)
        self.assertTrue(am.estimate_usd(self.be("claude", "opus"), [2500])[1] >= 0.258)
        for (prov, model), (one, (a, b)) in cases.items():
            lo, hi, _ = am.estimate_usd(self.be(prov, model), m1)
            self.assertTrue(lo <= one <= hi, (model, lo, one, hi))
            lo, hi, _ = am.estimate_usd(self.be(prov, model), m3)
            self.assertTrue(lo <= a and b <= hi, (model, lo, a, b, hi))

    def test_scaled_by_price(self):
        prices = {"models": {"claude:sonnet": {"ids": ["sonnet"], "input": 2.0, "output": 10.0},
                             "claude:haiku": {"ids": ["haiku"], "input": 0.1, "output": 0.5},
                             "openai:gpt-6.1-sol": {"ids": ["gpt-6.1-sol"], "input": 2.0, "output": 10.0},
                             "openai:gpt-6-astra": {"ids": ["gpt-6-astra"], "input": 10.0, "output": 50.0}}}
        lo, hi, basis = am.estimate_usd(self.be("claude", "haiku"), [1000], prices)
        self.assertEqual(basis, "scaled")
        self.assertAlmostEqual(lo, round((0.025 + 0.013) * 0.05, 3), places=3)
        lo, hi, basis = am.estimate_usd(self.be("openai", "gpt-6-astra"), [1000], prices)
        self.assertEqual(basis, "scaled")
        self.assertAlmostEqual(hi, round((0.05 + 0.013) * 5, 3), places=3)

    def test_fallback(self):
        lo, hi, basis = am.estimate_usd(self.be("claude", "claude-unknown-9"), [1000], {"models": {}})
        self.assertEqual(basis, "fallback")
        self.assertEqual((lo, hi), (round(0.025 + 0.013, 3), round(0.17 + 0.045, 3)))


EST_KEYS = {"provider", "model", "usd_low", "usd_high", "chars", "effort", "channel", "basis", "cost_basis", "parts",
            "sec_low", "sec_high", "source_file", "content_type"}


class _Boom:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        raise AssertionError("--estimate-only 不得呼叫模型")


@unittest.skipUnless(V23, "2.3.0 起")
class EstimateRun(Base):
    REQ = {"provider": "claude", "channel": "cli", "model": None, "effort": None, "section": "minutes"}

    def test_no_call_no_write(self):
        write_out(self.out, PARAS)
        write_final(self.out)
        (self.out / "meeting-minutes.md").write_text("舊的", encoding="utf-8")       # 已有會議記錄也能預估
        boom = _Boom()
        self.use(boom)
        before, home_before = snapshot(self.out), snapshot(self.home)
        r = am.estimate(self.out, self.REQ, source="final", cfg={})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(boom.calls, 0)
        self.assertEqual(snapshot(self.out), before)                 # 沒有 run_log.jsonl、auto_minutes.json，transcript.json 沒改
        self.assertEqual(snapshot(self.home), home_before)           # 沒有 $MMH/logs/runs.jsonl
        e = r["estimate"]
        self.assertEqual(set(e), EST_KEYS)
        chars = sum(len(ac.content_of(x)) for x in FINAL_TEXTS)
        self.assertEqual((e["provider"], e["model"], e["chars"], e["parts"]), ("claude", "opus", chars, 1))
        self.assertEqual((e["source_file"], e["content_type"], e["basis"]), ("transcript.final.md", "meeting", "measured"))
        self.assertEqual(e["cost_basis"], "subscription_equivalent")
        self.assertEqual((e["usd_low"], e["usd_high"]), am.estimate_usd({"provider": "claude", "model": "opus"}, [chars])[:2])
        self.assertLess(e["usd_low"], e["usd_high"])

    def test_estimate_final_missing(self):
        write_out(self.out, PARAS)
        self.use(_Boom())
        r = am.estimate(self.out, self.REQ, source="final", cfg={})
        self.assertEqual((r["status"], r["reason"], r["estimate"]), ("failed", "no_transcript", None))

    def test_estimate_context_not_written(self):
        write_out(self.out, PARAS)
        write_final(self.out)
        self.use(_Boom())
        r = am.estimate(self.out, self.REQ, source="final", cfg={}, refs_opts={"context": "背景一行", "refs": [], "no_refs": False,
                                                                                  "no_context": False})
        self.assertEqual(r["status"], "ok")
        self.assertFalse((self.out / "context.md").exists())

    def test_estimate_backend_skip(self):
        write_out(self.out, PARAS)
        am.select_backend = lambda cfg, req, section=None: {"skip": "cli_not_found", "provider": None, "message": "x"}
        r = am.estimate(self.out, self.REQ, cfg={})
        self.assertEqual((r["status"], r["reason"]), ("skipped", "cli_not_found"))


@unittest.skipUnless(V23, "2.3.0 起")
class EstimateCli(unittest.TestCase):
    """命令列：API 通道＋假的金鑰（不連網；預估不呼叫模型），stdout 最後一行 JSON、exit code、不寫檔。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-v230-cli-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.out = self.tmp / "demo_minutes"
        self.out.mkdir()
        write_out(self.out, PARAS)
        write_final(self.out)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "MMP_RUN_ID")}
        env.update(MEETING_MINUTES_PRO_HOME=str(self.home), OPENAI_API_KEY="sk-test-not-a-real-key", PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "auto_minutes.py"), str(self.out), *args],
                              capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)

    def test_estimate_only(self):
        before = snapshot(self.out)
        r = self.run_cli("--source", "final", "--estimate-only", "--minutes-channel", "api")
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(set(d), {"estimate"})
        e = d["estimate"]
        self.assertEqual(set(e), EST_KEYS)
        self.assertEqual((e["provider"], e["model"], e["channel"], e["cost_basis"]), ("openai", "gpt-6.1-sol", "api", "api"))
        self.assertIn("沒有呼叫模型", r.stderr)
        self.assertNotIn("sk-test-not-a-real-key", r.stdout + r.stderr)
        self.assertEqual(snapshot(self.out), before)
        self.assertFalse((self.out / "run_log.jsonl").exists())
        self.assertFalse((self.home / "logs").exists())

    def test_estimate_only_missing_final(self):
        (self.out / "transcript.final.md").unlink()
        r = self.run_cli("--source", "final", "--estimate-only", "--minutes-channel", "api")
        self.assertEqual(r.returncode, 5)
        d = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual((d["estimate"], d["reason"]), (None, "no_transcript"))
        self.assertIn("transcript.final.md", r.stderr)

    def test_estimate_with_render_only(self):
        r = self.run_cli("--estimate-only", "--render-only")
        self.assertEqual(r.returncode, 2)

    def test_help_lists_new_flags(self):
        r = self.run_cli("--help")
        self.assertIn("--estimate-only", r.stdout)
        self.assertIn("final", r.stdout)


def _shells():
    out = []
    for name in ("pwsh", "powershell"):
        if shutil.which(name):
            out.append(name)
    return out


FAKE_UNINSTALL_PS1 = """param([switch]$Quiet, [string]$TestRoot = "")
$o = [ordered]@{ quiet = [bool]$Quiet; test_root = $TestRoot; mmh = $env:MEETING_MINUTES_PRO_HOME
                 skill_exists = (Test-Path -LiteralPath (Join-Path $TestRoot "skills\\meeting-minutes-pro")) }
$o | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot "called.json") -Encoding UTF8
exit [int]$env:FAKE_PROOF_EXIT
"""


@unittest.skipUnless(V23 and sys.platform == "win32", "2.3.0 起；Windows")
class UninstallProofreadPs1(unittest.TestCase):
    """§4：install.ps1 -Uninstall -TestRoot（PowerShell 7 與 5.1 實跑；runtime 刪除題回答 n）。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v230-un-"))
        (self.root / "skills" / "meeting-minutes-pro").mkdir(parents=True)
        self.home = self.root / "home"
        self.home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_un(self, shell, exit_code=0):
        env = {k: v for k, v in os.environ.items() if k != "MEETING_MINUTES_PRO_HOME"}
        env["FAKE_PROOF_EXIT"] = str(exit_code)
        return subprocess.run([shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1), "-Uninstall",
                               "-TestRoot", str(self.root)], input="n\n", capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=120)

    def add_proofread(self):
        pr = self.home / "proofread"
        pr.mkdir()
        (pr / "uninstall.ps1").write_text(FAKE_UNINSTALL_PS1, encoding="utf-8-sig")
        return pr

    def test_runs_proofread_uninstall_first_quietly(self):
        for sh in _shells():
            with self.subTest(shell=sh):
                (self.root / "skills" / "meeting-minutes-pro").mkdir(parents=True, exist_ok=True)
                pr = self.add_proofread() if not (self.home / "proofread").exists() else self.home / "proofread"
                (pr / "called.json").unlink(missing_ok=True)
                r = self.run_un(sh)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                c = json.loads((pr / "called.json").read_text(encoding="utf-8-sig"))
                self.assertTrue(c["quiet"])
                self.assertEqual(Path(c["test_root"]).resolve(), self.root.resolve())
                self.assertEqual(Path(c["mmh"]).resolve(), self.home.resolve())
                self.assertTrue(c["skill_exists"], "校稿的移除程式要在 Pro 刪自己的檔案之前執行")
                self.assertIn("已移除會議記錄校稿", r.stdout)
                self.assertFalse((self.root / "skills" / "meeting-minutes-pro").exists())

    def test_failure_only_warns(self):
        self.add_proofread()
        for sh in _shells():
            with self.subTest(shell=sh):
                (self.root / "skills" / "meeting-minutes-pro").mkdir(parents=True, exist_ok=True)
                r = self.run_un(sh, exit_code=3)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("會議記錄校稿的移除程式回報錯誤（exit 3）", r.stdout)
                self.assertFalse((self.root / "skills" / "meeting-minutes-pro").exists())     # Pro 的解除安裝照常

    def test_without_proofread_does_nothing(self):
        for sh in _shells():
            with self.subTest(shell=sh):
                (self.root / "skills" / "meeting-minutes-pro").mkdir(parents=True, exist_ok=True)
                r = self.run_un(sh)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("會議記錄校稿", r.stdout + r.stderr)
                self.assertFalse((self.home / "proofread").exists())


def _sh_functions() -> str:
    """install.sh 的 step／ok／warn／fail 與 uninstall_proofread、do_uninstall（install.sh 在 macOS 以外一開始就停止，所以只取函式）。"""
    s = INSTALL_SH.read_text(encoding="utf-8")
    helpers = re.search(r"^c_cyan=.*?^fail\(\) \{.*?\n", s, re.S | re.M).group(0)
    funcs = re.search(r"^uninstall_proofread\(\) \{.*?\n\}\n\ndo_uninstall\(\) \{.*?\n\}\n", s, re.S | re.M).group(0)
    return helpers + funcs


FAKE_UNINSTALL_SH = """#!/bin/bash
here="$(cd "$(dirname "$0")" && pwd)"
skill=0; [ -d "$TEST_ROOT_SEEN/skills/meeting-minutes-pro" ] && skill=1
printf '%s\\n' "args=$*" "skill=$skill" > "$here/called.txt"
exit "${FAKE_PROOF_EXIT:-0}"
"""


@unittest.skipUnless(V23 and GIT_BASH.exists(), "2.3.0 起；要 Git Bash")
class UninstallProofreadSh(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v230-sh-", dir=_testenv.HERE / "_out"
                                          if (_testenv.HERE / "_out").is_dir() else None))
        self.home = self.root / "home"
        (self.root / "skills" / "meeting-minutes-pro").mkdir(parents=True)
        self.home.mkdir()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_un(self, exit_code=0):
        root = self.root.as_posix()
        script = (_sh_functions() + f'\nTEST_ROOT="{root}"; MMH="{root}/home"; SKILL_DST="{root}/skills/meeting-minutes-pro"\n'
                  f'APP_DST="{root}/Applications/x.app"; LEGACY_APP="{root}/Applications/y.app"; UPLOAD_ZIP="{root}/Desktop/z.zip"\n'
                  f'DESKTOP_DIR="{root}/Desktop"\ndo_uninstall\n')
        env = dict(os.environ, FAKE_PROOF_EXIT=str(exit_code), TEST_ROOT_SEEN=root)
        return subprocess.run([str(GIT_BASH), "-c", script], input="n\n", capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=60)

    def test_runs_first_quietly(self):
        pr = self.home / "proofread"
        pr.mkdir()
        (pr / "uninstall.sh").write_text(FAKE_UNINSTALL_SH, encoding="utf-8", newline="\n")
        r = self.run_un()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        called = (pr / "called.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(called, [f"args=--quiet --test-root {self.root.as_posix()}", "skill=1"])
        self.assertIn("已移除會議記錄校稿", r.stdout)
        self.assertFalse((self.root / "skills" / "meeting-minutes-pro").exists())

    def test_failure_only_warns(self):
        pr = self.home / "proofread"
        pr.mkdir()
        (pr / "uninstall.sh").write_text(FAKE_UNINSTALL_SH, encoding="utf-8", newline="\n")
        r = self.run_un(exit_code=4)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("會議記錄校稿的移除程式回報錯誤（exit 4）", r.stdout)
        self.assertFalse((self.root / "skills" / "meeting-minutes-pro").exists())

    def test_without_proofread(self):
        r = self.run_un()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("會議記錄校稿", r.stdout + r.stderr)


@unittest.skipUnless(V23, "2.3.0 起")
class KeepProofreadOnInstall(unittest.TestCase):
    """§5：安裝時只刪 $MMH/scripts，$MMH/proofread 保留（靜態檢查＋把那幾行拿出來實跑）。"""

    def test_static_ps1(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        install_part = s[s.index("if ($Uninstall) { Do-Uninstall }"):]
        self.assertNotRegex(install_part, r"Remove-Item\s+(-LiteralPath\s+)?\$MMH\b(?!\\|\w)")
        self.assertIn("proofread\\", install_part[:install_part.index("Copy-Item (Join-Path $Payload \"runtime\\scripts\")")])
        self.assertIn("不要改成清空 $MMH", s)

    def test_static_sh(self):
        s = INSTALL_SH.read_text(encoding="utf-8")
        install_part = s[s.index('[ -n "$UNINSTALL" ] && do_uninstall'):]
        self.assertNotRegex(install_part, r'rm -rf "\$MMH"(\s|;|$)')
        self.assertIn("proofread/", install_part)
        self.assertIn("不要改成清空 $MMH", s)

    def _tree(self):
        tmp = Path(tempfile.mkdtemp(prefix="mmp-v230-keep-", dir=_testenv.HERE / "_out"
                                    if (_testenv.HERE / "_out").is_dir() else None))
        home, payload = tmp / "home", tmp / "payload"
        for p in (home / "proofread" / "app", home / "proofread" / "state", home / "scripts", payload / "runtime" / "scripts"):
            p.mkdir(parents=True)
        (home / "proofread" / "app" / "mmproof_server.py").write_text("x", encoding="utf-8")
        (home / "proofread" / "state" / "recent.json").write_text("[]", encoding="utf-8")
        (home / "scripts" / "old_left_over.py").write_text("x", encoding="utf-8")
        (payload / "runtime" / "scripts" / "common.py").write_text("x", encoding="utf-8")
        return tmp, home, payload

    def _check(self, home):
        self.assertTrue((home / "proofread" / "app" / "mmproof_server.py").exists())
        self.assertTrue((home / "proofread" / "state" / "recent.json").exists())
        self.assertFalse((home / "scripts" / "old_left_over.py").exists())
        self.assertTrue((home / "scripts" / "common.py").exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows")
    def test_ps1_lines(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        a = s.index('$scriptsDst = Join-Path $MMH "scripts"')
        b = s.index("\n", s.index('Copy-Item (Join-Path $Payload "runtime\\scripts") $MMH -Recurse -Force'))
        for sh in _shells():
            with self.subTest(shell=sh):
                tmp, home, payload = self._tree()
                try:
                    code = (f"$ErrorActionPreference='Stop'; $MMH = '{home}'; $Payload = '{payload}'\n" + s[a:b] + "\n")
                    r = subprocess.run([sh, "-NoProfile", "-Command", code], capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=60)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self._check(home)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)

    @unittest.skipUnless(GIT_BASH.exists(), "要 Git Bash")
    def test_sh_lines(self):
        s = INSTALL_SH.read_text(encoding="utf-8")
        a = s.index('rm -rf "$MMH/scripts"')
        b = s.index("\n", s.index('cp -R "$PAYLOAD/runtime/scripts" "$MMH/scripts"'))
        tmp, home, payload = self._tree()
        try:
            code = f'set -e; MMH="{home.as_posix()}"; PAYLOAD="{payload.as_posix()}"\n' + s[a:b] + "\n"
            r = subprocess.run([str(GIT_BASH), "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self._check(home)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(V23, "2.3.0 起")
class EntryHotwords(unittest.TestCase):
    def test_native_arg(self):
        s = (_testenv.RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('$argList += @("--hotwords", (Native-Arg $hot))', s)
        self.assertNotIn('@("--hotwords", $hot)', s)
        self.assertLess(s.index("function Native-Arg"), s.index('@("--hotwords", (Native-Arg $hot))'))


class TestEnvLatest(unittest.TestCase):
    """§7：_testenv 不帶 MMP_TEST_VERSION 時取最新的版本目錄（依數字比較）。"""

    def test_numeric_order(self):
        tmp = Path(tempfile.mkdtemp(prefix="mmp-v230-env-"))
        try:
            for n in ("meeting-minutes-pro-v2.9.0", "meeting-minutes-pro-v2.10.0", "meeting-minutes-pro-v10.0.0-beta",
                      "meeting-minutes-pro-vX", "other-v9.9.9"):
                (tmp / n).mkdir()
            (tmp / "meeting-minutes-pro-v99.0.0").write_text("不是資料夾", encoding="utf-8")
            self.assertEqual(_testenv.latest_version(tmp), "2.10.0")
            shutil.rmtree(tmp / "meeting-minutes-pro-v2.9.0")
            shutil.rmtree(tmp / "meeting-minutes-pro-v2.10.0")
            with self.assertRaises(RuntimeError):
                _testenv.latest_version(tmp)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_default_is_latest(self):
        env = {k: v for k, v in os.environ.items() if k != "MMP_TEST_VERSION"}
        r = subprocess.run([sys.executable, "-B", "-c", "import _testenv; print(_testenv.VERSION)"], cwd=str(_testenv.HERE),
                           capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), _testenv.latest_version())
        r = subprocess.run([sys.executable, "-B", "-c", "import _testenv; print(_testenv.VERSION)"], cwd=str(_testenv.HERE),
                           capture_output=True, text=True, encoding="utf-8", env=dict(env, MMP_TEST_VERSION="2.2.0"), timeout=60)
        self.assertEqual(r.stdout.strip(), "2.2.0")


@unittest.skipUnless(V23, "2.3.0 起")
class Docs(unittest.TestCase):
    def test_skill_and_readme(self):
        skill = (VD / "payload" / "skill" / "meeting-minutes-pro" / "SKILL.md").read_text(encoding="utf-8")
        readme = (VD / "README.md").read_text(encoding="utf-8")
        for doc in (skill, readme):
            for k in ("--source final", "--estimate-only", "transcript.final.md", "會議記錄校稿"):
                self.assertIn(k, doc)
        self.assertLessEqual(len(re.search(r"^description: (.*)$", skill, re.M).group(1)), 1024)   # Claude App 的上限


@unittest.skipUnless(V23, "2.3.0 起")
class RegressionV22(unittest.TestCase):
    """AC：沒有 transcript.final.md 時，獨立行程跑 2.2.0 與 2.3.0（假的呼叫器），auto／corrected／original 三種 --source 的
    來源檔、送出的系統提示詞與使用者訊息、meeting-minutes.md 逐位元相同。沒有 2.2.0 目錄時略過。"""

    PROBE = "\n".join([
        "import json, sys",
        "sys.path.insert(0, sys.argv[1])",
        "import auto_correct as ac, auto_minutes as am",
        "calls = []",
        "R = json.loads(sys.argv[4])",
        "def fake(be, system, user, timeout, schema=None):",
        "    calls.append([system, user])",
        "    return ac._ok(json.dumps(R, ensure_ascii=False), R, {'input': 1, 'output': 1}, 'claude-opus-5-5', 0.0)",
        "ac.CALLERS[('claude', 'cli')] = fake",
        "am.select_backend = lambda cfg, req, section=None: {'provider': 'claude', 'channel': 'cli', 'exe': 'x',",
        "    'cli_version': 'fake 1.0', 'auth': 'subscription', 'note': None, 'model': 'opus', 'effort': 'medium', 'model_api': 'opus'}",
        "req = {'provider': 'claude', 'channel': 'cli', 'model': None, 'effort': None, 'section': 'minutes'}",
        "r = am.run(sys.argv[2], req, cfg={}, source=sys.argv[3], html=False)",
        "md = open(sys.argv[2] + '/meeting-minutes.md', encoding='utf-8').read()",
        "print(json.dumps({'status': r['status'], 'source_file': r['source_file'], 'calls': calls, 'md': md}, ensure_ascii=False))",
    ])

    @unittest.skipUnless(V220.is_dir(), "沒有 meeting-minutes-pro-v2.2.0 目錄")
    def test_bit_identical_without_final(self):
        tmp = Path(tempfile.mkdtemp(prefix="mmp-v230-reg-"))
        try:
            got = {}
            for v, vd in (("2.2.0", V220), ("2.3.0", VD)):
                for src in ("auto", "corrected", "original"):
                    out = tmp / f"{v}-{src}" / "demo_minutes"
                    out.mkdir(parents=True)
                    write_out(out, PARAS)
                    write_corrected(out, ["校正版一", "校正版二", "校正版三"])
                    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                               MEETING_MINUTES_PRO_HOME=str(tmp / f"home-{v}-{src}"))
                    r = subprocess.run([sys.executable, "-B", "-c", self.PROBE, str(vd / "payload" / "runtime" / "scripts"),
                                        str(out), src, json.dumps(result(), ensure_ascii=False)],
                                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    got[(v, src)] = json.loads(r.stdout.strip().splitlines()[-1])
            for src in ("auto", "corrected", "original"):
                a, b = got[("2.2.0", src)], got[("2.3.0", src)]
                self.assertEqual(a["status"], "ok")
                self.assertEqual(a, b, src)
            self.assertEqual(got[("2.3.0", "auto")]["source_file"], "transcript.corrected.md")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(V23, "2.3.0 起")
class ProofreadInterface(unittest.TestCase):
    """§8 會議記錄校稿相容性：校稿 1.0.0 介面檢查用到的名稱都在，且所在檔案與 2.2.0 相同
    （common.py 只有 VERSION 一行、render_html.py 只有 FALLBACK_VERSION 一行不同）。沒有 2.2.0 目錄時只查名稱。"""

    NAMES = {"common": ("VERSION", "data_home", "load_config", "setting", "default_glossary", "corrections_path"),
             "consistency": ("MARK_RE", "key_of", "COMMON_WORDS"),
             "corrections": ("load", "backup", "append_rows", "HEADER", "MIN_LEN"),
             "subtitles": ("map_corrected", "recue", "render_srt", "options"),
             "render_html": ("render",)}
    MARK_PATTERN_220 = None

    def test_names_present(self):
        import importlib
        for mod, names in self.NAMES.items():
            m = importlib.import_module(mod)
            for n in names:
                self.assertTrue(hasattr(m, n), f"{mod}.{n}")

    @unittest.skipUnless(V220.is_dir(), "沒有 meeting-minutes-pro-v2.2.0 目錄")
    def test_files_unchanged_from_220(self):
        old, new = V220 / "payload" / "runtime" / "scripts", _testenv.SCRIPTS
        for f in ("consistency.py", "corrections.py", "subtitles.py"):
            self.assertEqual((old / f).read_bytes(), (new / f).read_bytes(), f)
        for f, key in (("common.py", "VERSION = "), ("render_html.py", "FALLBACK_VERSION = ")):
            a = (old / f).read_text(encoding="utf-8").splitlines()
            b = (new / f).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(a), len(b), f)
            diff = [(x, y) for x, y in zip(a, b) if x != y]
            self.assertEqual(len(diff), 1, (f, diff))
            self.assertTrue(diff[0][0].startswith(key) and diff[0][1].startswith(key), diff)
        skill_old = V220 / "payload" / "skill" / "meeting-minutes-pro" / "scripts" / "html_template.html"
        self.assertEqual(skill_old.read_bytes(), (new / "html_template.html").read_bytes())


if __name__ == "__main__":
    unittest.main()
