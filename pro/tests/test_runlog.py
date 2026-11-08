"""執行 log（runlog.py；規格 §11；1.2.0 起）的單元測試：檢查點時間、token 正規化、API 等價費用、
run 的歸屬（MMP_RUN_ID）、runs.jsonl 摘要列、彙整工具，以及 log 不含逐字稿文字與金鑰。不呼叫任何模型。"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

import _testenv  # noqa: F401
import auto_correct as ac
import runlog

from test_auto_correct import FakeModel, write_out

ISO_TZ = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")


class Base(unittest.TestCase):
    def setUp(self):
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = Path(tempfile.mkdtemp(prefix="mmp-rl-home-"))
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self.out = Path(tempfile.mkdtemp(prefix="mmp-rl-out-"))
        self._run_id = os.environ.pop("MMP_RUN_ID", None)

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        os.environ.pop("MMP_RUN_ID", None)
        if self._run_id:
            os.environ["MMP_RUN_ID"] = self._run_id
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def events(self):
        return runlog.read_events(self.out / runlog.LOG_NAME)

    def runs(self):
        p = self.home / "logs" / runlog.RUNS_NAME
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


class Tokens(unittest.TestCase):
    def test_claude_splits_cache_write(self):
        nu = runlog.normalize_usage("claude", {"input": 1200, "cache_write": 200, "cache_read": 50, "output": 300})
        self.assertEqual(nu, {"input": 1000, "cache_read": 50, "cache_write": 200, "output": 300, "reasoning": None})
        nu = runlog.normalize_usage("claude", {"input": 10, "output": 5, "thinking": 3})
        self.assertEqual(nu["reasoning"], 3)

    def test_openai_input_includes_cached(self):
        nu = runlog.normalize_usage("openai", {"input": 9790, "cache_read": 1790, "output": 3100, "thinking": 900})
        self.assertEqual(nu, {"input": 8000, "cache_read": 1790, "cache_write": 0, "output": 3100, "reasoning": 900})
        self.assertEqual(runlog.normalize_usage("openai", None)["input"], 0)


class Prices(Base):
    def test_price_lookup(self):
        p = runlog.load_prices()
        self.assertEqual(runlog.price_for(p, "claude", "claude-opus-5-5")[0], "claude:opus")
        self.assertEqual(runlog.price_for(p, "claude", "opus")[0], "claude:opus")
        self.assertEqual(runlog.price_for(p, "claude", "sonnet")[0], "claude:sonnet")
        self.assertEqual(runlog.price_for(p, "openai", "gpt-6.1-sol")[0], "openai:gpt-6.1-sol")
        self.assertEqual(runlog.price_for(p, "openai", "gpt-6.1-sol-2026-10-01")[0], "openai:gpt-6.1-sol")
        self.assertEqual(runlog.price_for(p, "openai", "gpt-6.1-terra")[0], "openai:gpt-6.1-terra")
        self.assertEqual(runlog.price_for(p, "openai", "mystery"), (None, None))
        self.assertEqual(runlog.price_for(p, "openai", "opus"), (None, None))
        for k, v in p["models"].items():
            for f in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"):
                self.assertIn(f, v, k)
        self.assertTrue(p["updated"] and p["sources"])

    def test_cost_formula(self):
        p = runlog.load_prices()
        nu = {"input": 1_000_000, "cache_read": 1_000_000, "cache_write": 1_000_000, "output": 1_000_000, "reasoning": None}
        c = runlog.cost_of(p, "claude", "cli", "subscription", "claude-opus-5-5", nu)
        self.assertAlmostEqual(c["cost_usd"], 4 + 0.2 + 8 + 20)          # CLI：1 小時快取寫入價
        self.assertEqual(c["cost_basis"], "subscription_equivalent")
        c = runlog.cost_of(p, "claude", "api", "api_key", "claude-opus-5-5", nu)
        self.assertAlmostEqual(c["cost_usd"], 4 + 0.2 + 5 + 20)          # API：5 分鐘快取寫入價
        self.assertEqual(c["cost_basis"], "api")
        c = runlog.cost_of(p, "openai", "cli", "api_key", "gpt-6.1-sol", nu)
        self.assertEqual(c["cost_basis"], "api")                         # codex 以 API 金鑰登入：依 API 計費
        c = runlog.cost_of(p, "openai", "cli", "chatgpt", "unknown-model", nu)
        self.assertIsNone(c["cost_usd"])

    def test_user_override(self):
        (self.home / "pricing.json").write_text(json.dumps({"updated": "2027-01-01", "models": {
            "openai:gpt-6.1-sol": {"input": 1.0}, "openai:gpt-7": {"ids": ["gpt-7"], "input": 3, "output": 9}}}),
            encoding="utf-8")
        p = runlog.load_prices()
        self.assertEqual(p["models"]["openai:gpt-6.1-sol"]["input"], 1.0)
        self.assertEqual(p["models"]["openai:gpt-6.1-sol"]["output"], 10.0)   # 沒寫的鍵沿用內建
        self.assertEqual(runlog.price_for(p, "openai", "gpt-7")[0], "openai:gpt-7")
        self.assertEqual(p["user_updated"], "2027-01-01")


class Events(Base):
    def test_checkpoint_and_wait(self):
        rl = runlog.RunLog(self.out, step="transcribe")
        with rl.checkpoint("asr", backend="openvino") as cp:
            time.sleep(0.02)
            cp["segments"] = 7
        rl.wait("ask_correction", "2026-11-06T10:00:00.000+08:00", "2026-11-06T10:00:05.500+08:00")
        rl.wait("ask_minutes", "2026-11-06T10:01:00+0800", "2026-11-06T10:01:03+0800")    # date +%z 的寫法
        ev = self.events()
        cp = ev[0]
        self.assertEqual((cp["event"], cp["name"], cp["segments"], cp["status"]), ("checkpoint", "asr", 7, "ok"))
        for k in ("started_at", "ended_at", "ts"):
            self.assertRegex(cp[k], ISO_TZ)
        self.assertLessEqual(datetime.fromisoformat(cp["started_at"]), datetime.fromisoformat(cp["ended_at"]))
        self.assertGreater(cp["duration_sec"], 0.01)
        self.assertEqual([e["duration_sec"] for e in ev[1:]], [5.5, 3.0])
        s = rl.finish()
        self.assertEqual(s["wait_sec"], 8.5)
        self.assertLess(s["processing_sec"], 1)            # 等待不算處理時間
        self.assertEqual(s["stages"], {"asr": cp["duration_sec"]})

    def test_checkpoint_error_status(self):
        rl = runlog.RunLog(self.out)
        with self.assertRaises(ValueError):
            with rl.checkpoint("diarize"):
                raise ValueError("x")
        self.assertEqual(self.events()[-1]["status"], "error")

    def test_begin_end(self):
        rl = runlog.RunLog(self.out)
        h = rl.begin("convert_audio")
        rl.end(h, recording_sec=12.5)
        e = self.events()[-1]
        self.assertEqual((e["name"], e["recording_sec"]), ("convert_audio", 12.5))

    def test_owner_by_env(self):
        self.assertTrue(runlog.RunLog(self.out).owns)
        os.environ["MMP_RUN_ID"] = "abc123"
        rl = runlog.RunLog(self.out)
        self.assertEqual((rl.run_id, rl.owns), ("abc123", False))
        self.assertTrue(runlog.RunLog(self.out, "abc123", owns=True).owns)

    def test_finish_summary_row(self):
        rl = runlog.RunLog(self.out, step="transcribe")
        rl.event("info", source="m.wav", recording_sec=3600.0, segments=10, paragraphs=5, speakers=3, asr_model="turbo",
                 device="openvino/NPU")
        rl.event("checkpoint", name="asr", duration_sec=100.0)
        rl.event("checkpoint", name="correct", duration_sec=300.0)
        rl.event("checkpoint", name="correct.chunk", duration_sec=290.0)     # 子檢查點不重複計入
        be = {"provider": "openai", "channel": "cli", "model": "gpt-6.1-sol", "effort": "low", "auth": "chatgpt"}
        rl.step = "correct"
        rl.call(be, {"ok": True, "usage": {"input": 1_000_000, "output": 100_000, "cache_read": 0}, "model": "gpt-6.1-sol"},
                runlog.now(), runlog.now(), 1.0, stage="correct.chunk", chunk=1)
        rl.event("result", status="ok")
        s = rl.finish()
        self.assertEqual(s["stages"], {"asr": 100.0, "correct": 300.0})
        self.assertEqual(s["processing_sec"], 400.0)
        self.assertAlmostEqual(s["cost_usd"], 2.0 + 1.0)
        self.assertAlmostEqual(s["cost_per_recording_hour_usd"], 3.0)
        self.assertEqual(s["cost_note"], "等價估算，不另計費")
        self.assertEqual((s["recording_sec"], s["segments"], s["speakers"]), (3600.0, 10, 3))
        self.assertEqual(s["results"], {"correct": {"status": "ok", "reason": None}})
        self.assertEqual(s["steps"], ["transcribe", "correct"])
        self.assertEqual(self.runs()[0]["run_id"], rl.run_id)
        self.assertEqual(self.events()[-1]["event"], "run_summary")

    def test_cli_wait_finish_summary(self):
        py = sys.executable
        script = str(_testenv.SCRIPTS / "runlog.py")
        env = dict(os.environ, MEETING_MINUTES_PRO_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", MMP_RUN_ID="r1")
        rl = runlog.RunLog(self.out, "r1")
        rl.event("info", source="a.wav", recording_sec=1800.0)
        rl.event("checkpoint", name="asr", duration_sec=60.0)
        subprocess.run([py, "-B", script, "wait", str(self.out), "--name", "ask_correction",
                        "--start", "2026-11-06T10:00:00.123+08:00", "--end", "2026-11-06T10:00:02.123+08:00"],
                       check=True, env=env)
        p = subprocess.run([py, "-B", script, "finish", str(self.out)], check=True, env=env, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertEqual(json.loads(p.stdout)["run_id"], "r1")
        csvp = self.out / "runs.csv"
        p = subprocess.run([py, "-B", script, "summary", "--csv", str(csvp)], check=True, env=env, capture_output=True,
                           text=True, encoding="utf-8")
        self.assertIn("a.wav", p.stdout)
        self.assertIn("每小時錄音", p.stdout)
        self.assertTrue(csvp.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.runs()[0]["wait_sec"], 2.0)


class Version(Base):
    """〔1.2.0〕每個事件、每列摘要帶 runtime 版號；呼叫事件帶 CLI 版本；console 第一行。"""

    def test_events_and_rows_have_version(self):
        import common
        rl = runlog.RunLog(self.out, step="transcribe")
        rl.event("info", source="a.wav", recording_sec=60.0)
        be = {"provider": "claude", "channel": "cli", "model": "opus", "effort": "medium", "auth": "subscription",
              "cli_version": "2.1.318 (Claude Code)"}
        rl.call(be, {"ok": True, "usage": {"input": 10, "output": 5}, "model": "claude-opus-5-5"}, runlog.now(), runlog.now(), 0.1)
        rl.call(dict(be, provider="openai", model="gpt-6.1-sol", cli_version="codex-cli 0.166.0"),
                {"ok": True, "usage": {"input": 10, "output": 5}, "model": "gpt-6.1-sol"}, runlog.now(), runlog.now(), 0.1)
        s = rl.finish()
        ev = self.events()
        self.assertEqual(ev[0]["version"], common.VERSION)                 # 第一筆事件
        self.assertTrue(all(e.get("version") == common.VERSION for e in ev))
        self.assertEqual(self.runs()[0]["version"], common.VERSION)        # runs.jsonl 每一列
        self.assertEqual(s["cli_versions"], ["2.1.318 (Claude Code)", "codex-cli 0.166.0"])
        self.assertEqual(s["versions_seen"], [common.VERSION])
        self.assertEqual([e["cli_version"] for e in ev if e["event"] == "call"], s["cli_versions"])

    def test_banner(self):
        import common
        self.assertEqual(common.version_banner({}), f"meeting-minutes-pro {common.VERSION}")
        self.assertEqual(common.version_banner({"runtime_version": common.VERSION}), f"meeting-minutes-pro {common.VERSION}")
        b = common.version_banner({"runtime_version": "1.1.0"})
        self.assertTrue(b.startswith(f"meeting-minutes-pro {common.VERSION}"))
        self.assertIn("runtime_version 是 1.1.0", b)
        self.assertIn("不一致", b)

    def test_scripts_print_banner_first(self):
        import common
        env = dict(os.environ, MEETING_MINUTES_PRO_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1")
        for script, args in (("auto_minutes.py", [str(self.out / "nope")]), ("auto_correct.py", [str(self.out / "nope")]),
                             ("setup_backend.py", ["--help"])):
            p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / script)] + args, env=env,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(p.stderr.splitlines()[0], f"meeting-minutes-pro {common.VERSION}", script)


class AutoCorrectLog(Base):
    """auto_correct.run() 的每一塊與用字表都有檢查點與呼叫事件；log 不含逐字稿文字與金鑰。"""

    def setUp(self):
        super().setUp()
        # 〔2.2.0〕輸出資料夾放在自己的上層資料夾裡（refs.py 會看「媒體旁」＝上一層，不要看到系統暫存區）
        self._root = self.out
        self.out = self._root / "demo_minutes"
        self.out.mkdir()
        self._callers = dict(ac.CALLERS)
        self._select = ac.select_backend
        os.environ["OPENAI_API_KEY"] = "sk-test-SECRET-should-not-appear"

    def tearDown(self):
        ac.CALLERS.clear()
        ac.CALLERS.update(self._callers)
        ac.select_backend = self._select
        os.environ.pop("OPENAI_API_KEY", None)
        super().tearDown()
        shutil.rmtree(self._root, ignore_errors=True)

    def test_chunks_terms_calls(self):
        texts = ["示範證券下單系統的權限設計要重新檢查一次。" * 3, "Kafka 的 consumer lag 高峰兩萬筆左右。" * 3,
                 "Redis Sentinel 切換花了十二秒左右太久了。" * 3]
        write_out(self.out, [("00:00:00", "S1", texts[0]), ("00:01:00", "S2", texts[1]), ("00:02:00", "S1", texts[2])])
        fake = FakeModel(fix={"示範": "示梵"}, terms=[{"wrong": ["示範"], "right": "示梵", "confidence": "high", "reason": "x"}])
        ac.CALLERS[("claude", "cli")] = fake
        ac.select_backend = lambda cfg, req: {"provider": "claude", "channel": "cli", "exe": "x", "cli_version": "f",
                                              "auth": "subscription", "note": None, "model": "opus", "effort": "medium",
                                              "model_api": "opus"}
        res = ac.run(self.out, {"provider": "claude", "channel": "cli", "model": None, "effort": None},
                     cfg={"correction": {"chunk_chars": 40}}, consent=True)
        self.assertEqual(res["status"], "ok")
        ev = self.events()
        calls = [e for e in ev if e["event"] == "call"]
        self.assertEqual([c["stage"] for c in calls], ["correct.terms"] + ["correct.chunk"] * res["chunks"])
        self.assertEqual([c.get("chunk") for c in calls[1:]], list(range(1, res["chunks"] + 1)))
        for c in calls:
            self.assertEqual((c["provider"], c["channel"], c["model_requested"], c["effort"]), ("claude", "cli", "opus", "medium"))
            self.assertIn("tokens", c)
            self.assertIsNotNone(c["cost_usd"])
            self.assertRegex(c["started_at"], ISO_TZ)
        names = [e["name"] for e in ev if e["event"] == "checkpoint"]
        self.assertEqual(names.count("correct.chunk"), res["chunks"])
        self.assertIn("correct.terms", names)
        self.assertEqual(names[-1], "correct")
        self.assertEqual(ev[-1]["event"], "run_summary")         # 單獨執行：自己寫摘要
        self.assertEqual(len(self.runs()), 1)
        blob = (self.out / runlog.LOG_NAME).read_text(encoding="utf-8") + json.dumps(self.runs(), ensure_ascii=False)
        self.assertNotIn("SECRET", blob)
        for t in texts:
            for i in range(0, len(t) - 6):
                self.assertNotIn(t[i:i + 6], blob, "log 含逐字稿片段")

    def test_parent_run_does_not_finish(self):
        write_out(self.out, [("00:00:00", "S1", "今天確認權限設計。")])
        ac.CALLERS[("claude", "cli")] = FakeModel()
        ac.select_backend = lambda cfg, req: {"provider": "claude", "channel": "cli", "exe": "x", "cli_version": "f",
                                              "auth": "subscription", "note": None, "model": "opus", "effort": "medium",
                                              "model_api": "opus"}
        os.environ["MMP_RUN_ID"] = "entry1"
        ac.run(self.out, {"provider": "claude", "channel": "cli", "model": None, "effort": None}, cfg={}, consent=True)
        ev = self.events()
        self.assertTrue(all(e["run_id"] == "entry1" for e in ev))
        self.assertNotIn("run_summary", [e["event"] for e in ev])      # 入口負責 finish
        self.assertEqual(self.runs(), [])

    def test_skip_is_logged(self):
        write_out(self.out, [("00:00:00", "S1", "今天確認權限設計。")])
        ac.select_backend = lambda cfg, req: {"skip": "cli_not_found", "provider": None, "message": "找不到"}
        ac.run(self.out, {"provider": "auto", "channel": "cli", "model": None, "effort": None}, cfg={}, consent=True)
        res = [e for e in self.events() if e["event"] == "result"][0]
        self.assertEqual((res["status"], res["reason"]), ("skipped", "cli_not_found"))



@unittest.skipUnless(_testenv.VER >= (2, 0, 0), "2.0.0 才有")
class SummaryV2(Base):
    """〔2.0.0〕runs.jsonl 新欄位與 summary 的「類型」「分離」（規格 §6.4、§9.3）。"""

    def test_info_fields_into_runs(self):
        rl = runlog.RunLog(self.out, step="transcribe")
        rl.event("info", source="c.wav", recording_sec=60.0, speakers=3, content_type="course", template="book",
                 speakers_setting="auto", cluster_threshold=1.0, speakers_raw=4, diarize_engine="sherpa",
                 diarize_device="cpu", diarize_engine_reason="config", diarize_fallback=None)
        rl.event("checkpoint", name="diarize", duration_sec=3.0, engine="sherpa", device="cpu", speakers_raw=4, speakers=3)
        rl.event("checkpoint", name="asr", duration_sec=5.0)
        s = rl.finish()
        self.assertEqual((s["content_type"], s["template"], s["diarize_engine"], s["diarize_fallback"], s["speakers_raw"]),
                         ("course", "book", "sherpa", None, 4))
        row = self.runs()[0]
        self.assertIn("diarize_fallback", row)                              # runs.jsonl 寫 null
        r = runlog.summary_rows([row])[0]
        self.assertEqual((r["類型"], r["分離"]), ("course", "sherpa"))
        self.assertEqual(list(r)[:4], ["日期", "來源", "類型", "分離"])

    def test_labels_and_old_rows(self):
        f = runlog.diarize_label
        self.assertEqual(f({"diarize_engine": "pyannote"}), "pyannote")
        self.assertEqual(f({"diarize_engine": "sherpa", "diarize_fallback": "oom"}), "sherpa*")
        self.assertEqual(f({"diarize_engine": "none"}), "略過")
        self.assertEqual(f({"stages": {"convert_audio": 1, "diarize": 2, "asr": 3}}), "sherpa")   # 1.x
        self.assertEqual(f({"stages": {"convert_audio": 1, "asr": 3}}), "略過")                    # 1.x --no-diarize
        self.assertEqual(f({"stages": {"minutes": 3}}), "—")                                       # 只有整理
        old = {"run_id": "x", "version": "1.2.2", "source": "m.wav", "stages": {"diarize": 1.0, "asr": 2.0}}
        self.assertEqual(runlog.summary_rows([old])[0]["類型"], "meeting")

    def test_info_from_2x_transcript(self):
        doc = {"meta": {"source": "m.wav", "duration": 60.0, "speakers": 2, "model": "turbo", "device": "ct2/cuda",
                        "content_type": "panel", "template": None,
                        "diarization": {"engine": "pyannote", "fallback": None, "speakers_raw": 2}},
               "segments": [], "paragraphs": []}
        (self.out / "transcript.json").write_text(json.dumps(doc), encoding="utf-8")
        ev = runlog.RunLog(self.out, step="minutes").info_from_transcript()
        self.assertEqual((ev["content_type"], ev["diarize_engine"], ev["speakers_raw"]), ("panel", "pyannote", 2))
        doc["meta"] = {"source": "m.wav", "duration": 60.0}                   # 1.x 的 transcript.json：不加欄位
        (self.out / "transcript.json").write_text(json.dumps(doc), encoding="utf-8")
        ev = runlog.RunLog(self.out, step="minutes").info_from_transcript()
        self.assertNotIn("content_type", ev)


@unittest.skipUnless(_testenv.VER >= (2, 1, 0), "2.1.0 才有")
class HtmlLog(Base):
    """〔2.1.0〕H-10（規格 2.1.0 §6.4）：網頁版的 checkpoint 欄位齊全；run_log／runs.jsonl 不含 .md 內容的 6 字片段、
    標題與媒體檔名（媒體只記副檔名）；階段名 html 顯示「網頁版」、summary 不加欄位。"""

    MEDIA = "研發部週會錄影第三次.mp4"
    LINES = ["示範系統上線準備週會", "這段摘要文字不應該出現在紀錄裡面", "負責整理壓測報表與權限文件"]
    FIELDS = ("status", "reason", "source", "output", "bytes", "headings", "timecodes", "timecodes_out_of_range", "media",
              "media_ext", "escaped_html", "duration_ms")

    def prepare(self):
        d = self.out / "研發部週會錄影第三次_minutes"
        d.mkdir()
        md = (f"# {self.LINES[0]} 會議記錄\n\n> 自動整理：測試｜**未經人工確認**\n\n## 一、會議摘要\n\n{self.LINES[1]}。`[00:01:00]`\n\n"
              f"## 四、待辦事項（Action Items）\n\n| # | 事項 | 負責人 | 期限 | 備註 | 時間碼 |\n|---|---|---|---|---|---|\n"
              f"| A1 | {self.LINES[2]} | S1 | 未定 | — | 00:02:00 |\n")
        (d / "meeting-minutes.md").write_text(md, encoding="utf-8")
        (d / "transcript.json").write_text(json.dumps({"meta": {"source": self.MEDIA, "duration": 600.0}}, ensure_ascii=False),
                                           encoding="utf-8")
        (self.out / self.MEDIA).write_bytes(b"x")
        return d

    def blob(self, d):
        b = (d / runlog.LOG_NAME).read_text(encoding="utf-8")
        p = self.home / "logs" / runlog.RUNS_NAME
        return b + (p.read_text(encoding="utf-8") if p.exists() else "")

    def no_content(self, blob):
        for t in self.LINES:
            for i in range(0, len(t) - 6):
                self.assertNotIn(t[i:i + 6], blob, "log 含 .md 內容片段")
        self.assertNotIn("研發部週會錄影", blob.replace("研發部週會錄影第三次_minutes", ""))   # out_dir 以外不記媒體檔名
        self.assertNotIn(self.MEDIA, blob)

    def test_standalone_cli(self):
        d = self.prepare()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "render_html.py"), str(d)], capture_output=True,
                           env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        ev = runlog.read_events(d / runlog.LOG_NAME)
        cp = [e for e in ev if e["event"] == "checkpoint" and e["name"] == "html"][0]
        for k in self.FIELDS:
            self.assertIn(k, {**cp, "reason": cp.get("reason")}, k)                 # reason 為 None 時事件省略該鍵
        self.assertEqual((cp["media"], cp["media_ext"], cp["source"], cp["output"]), ("found", ".mp4", "meeting-minutes.md",
                                                                                     "meeting-minutes.html"))
        self.assertTrue(ISO_TZ.match(cp["started_at"]))
        runs = self.runs()
        self.assertEqual(runs[-1]["stages"].keys(), {"html"})
        self.assertEqual(runs[-1]["results"]["html"]["status"], "ok")
        self.no_content(self.blob(d))
        rows = runlog.summary_rows(runs)
        self.assertEqual(list(rows[-1]), list(runlog.summary_rows([{"stages": {}}])[0]))   # 不加欄位
        self.assertEqual(rows[-1]["轉寫"], "—")                                         # 網頁版不算轉寫
        self.assertEqual(runlog.STAGE_NAME["html"], "網頁版")
        self.assertEqual(runlog.STAGE_ORDER[-1], "html")

    def test_checkpoint_via_render(self):
        import render_html
        d = self.prepare()
        rl = runlog.RunLog(d, step="minutes")
        r = render_html.render(d, cfg={}, run_log=rl)
        self.assertEqual(r["status"], "ok")
        cp = [e for e in runlog.read_events(d / runlog.LOG_NAME) if e["event"] == "checkpoint"][0]
        self.assertEqual((cp["name"], cp["step"]), ("minutes.html", "minutes"))
        self.assertEqual({k for k in self.FIELDS if k in cp} | {"reason"}, set(self.FIELDS))
        self.no_content(self.blob(d))
        r = render_html.render(d, md_name="missing.md", cfg={}, run_log=rl)
        cp = [e for e in runlog.read_events(d / runlog.LOG_NAME) if e["event"] == "checkpoint"][-1]
        self.assertEqual((cp["status"], cp["reason"]), ("skipped", "no_md"))


@unittest.skipUnless(_testenv.VER >= (2, 2, 0), "2.2.0 才有")
class RefsLog(Base):
    """〔2.2.0〕規格 2.2.0 §8.4、§11.4：correct.refs 檢查點只有數量與原因代碼；call 事件的 images；
    run_log／runs.jsonl 不含說明檔、文件內容與檔名的片段；階段名「參考資料」、summary 不加欄位。"""

    def setUp(self):
        super().setUp()
        self._root = self.out
        self.out = self._root / "demo_minutes"
        self.out.mkdir()
        self._callers = dict(ac.CALLERS)
        self._select = ac.select_backend

    def tearDown(self):
        ac.CALLERS.clear()
        ac.CALLERS.update(self._callers)
        ac.select_backend = self._select
        super().tearDown()
        shutil.rmtree(self._root, ignore_errors=True)

    CONTEXT = "研發部第三季庫存盤點會議，主持人是物流組長"
    DOC = "倉儲系統的批次揀貨流程要在月底前完成驗收"
    DOC_NAME = "demo.倉儲改善計畫.md"

    def test_checkpoint_fields_and_no_content(self):
        write_out(self.out, [("00:00:00", "S1", "今天確認倉儲系統的批次揀貨流程。" * 3),
                             ("00:01:00", "S2", "月底前完成驗收沒問題。" * 3)])
        (self._root / "demo.context.md").write_text(self.CONTEXT + "\n常用寫法：WMS、RFID", encoding="utf-8")
        (self._root / self.DOC_NAME).write_text(f"# Pick-to-Light 導入\n\n{self.DOC}\n", encoding="utf-8")
        ac.CALLERS[("claude", "cli")] = FakeModel()
        ac.select_backend = lambda cfg, req: {"provider": "claude", "channel": "cli", "exe": "x", "cli_version": "f",
                                              "auth": "subscription", "note": None, "model": "opus", "effort": "medium",
                                              "model_api": "opus"}
        res = ac.run(self.out, {"provider": "claude", "channel": "cli", "model": None, "effort": None}, cfg={}, consent=True)
        self.assertEqual(res["status"], "ok")
        ev = self.events()
        cp = [e for e in ev if e["event"] == "checkpoint" and e["name"] == "correct.refs"]
        self.assertEqual(len(cp), 1)
        self.assertEqual((cp[0]["status"], cp[0]["reason"], cp[0]["docs_read"], cp[0]["participants"]),
                         ("skipped", "no_keyframes", 1, 0))
        self.assertEqual(cp[0]["context_chars"], len(self.CONTEXT) + len("\n常用寫法：WMS、RFID"))
        allowed = {"ts", "run_id", "event", "version", "step", "name", "started_at", "ended_at", "duration_sec", "status",
                   "reason", "frames_available", "frames_sent", "frames_dropped", "frame_px", "docs_read", "docs_skipped",
                   "doc_chars", "terms", "terms_chars", "paragraphs", "paragraphs_chars", "context_chars", "participants",
                   "speakers_mapped", "images_fallback", "duration_ms"}
        self.assertLessEqual(set(cp[0]), allowed)
        self.assertTrue(all(isinstance(v, (int, float, dict)) or v is None or k in ("ts", "run_id", "event", "version", "step",
                                                                                        "name", "started_at", "ended_at",
                                                                                        "status", "reason")
                            for k, v in cp[0].items()))
        blob = (self.out / runlog.LOG_NAME).read_text(encoding="utf-8") + json.dumps(self.runs(), ensure_ascii=False)
        for t in (self.CONTEXT, self.DOC):
            for i in range(0, len(t) - 6):
                self.assertNotIn(t[i:i + 6], blob, "log 含參考資料內容片段")
        for s in (self.DOC_NAME, "倉儲改善計畫", "Pick-to-Light", "demo.context.md", "RFID"):
            self.assertNotIn(s, blob)
        rows = runlog.summary_rows(self.runs())
        self.assertEqual(list(rows[-1]), list(runlog.summary_rows([{"stages": {}}])[0]))      # 不加欄位
        self.assertEqual(set(self.runs()[-1]["stages"]), {"correct", "subtitles"})          # correct.refs 不另成階段
        self.assertEqual(runlog.STAGE_NAME["correct.refs"], "參考資料")

    def test_call_event_images(self):
        rl = runlog.RunLog(self.out, step="correct")
        imgs = [self.out / "a.jpg", self.out / "b.jpg"]
        for p in imgs:
            p.write_bytes(b"\xff\xd8")
        ac.CALLERS[("claude", "cli")] = lambda be, s, u, t, schema=None, images=None: ac._ok("x", None, {"input": 2400}, "m")
        be = {"provider": "claude", "channel": "cli", "model": "opus", "effort": "medium", "model_api": "opus"}
        old = ac.CALL_LOG
        ac.CALL_LOG = rl
        try:
            with ac.call_context(stage="correct.refs"):
                ac.call(be, "s", "u", 5, ac.REFS_SCHEMA, images=imgs)
            ac.call(be, "s", "u", 5)
        finally:
            ac.CALL_LOG = old
        calls = [e for e in self.events() if e["event"] == "call"]
        self.assertEqual((calls[0]["images"], calls[0]["stage"], calls[0]["tokens"]["input"]), (2, "correct.refs", 2400))
        self.assertNotIn("images", calls[1])
        self.assertNotIn("a.jpg", (self.out / runlog.LOG_NAME).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
