"""〔2.4.0〕本機限定（機敏會議）與供應商名稱統一（規格 2.4.0）。不呼叫任何模型。

- Config：DEFAULTS 的 privacy.local_only、upgrade_config() 補 privacy 區塊並保留使用者的值（升級保留設定）
- Marker／State：標記檔 local-only.json 的寫入與內容、local_only_state() 的兩種來源、拒絕訊息
- Refuse*：auto_correct.py／auto_minutes.py 實跑（子行程）拒絕送出：exit 6、reason local_only、假的 claude／codex 被呼叫 0 次、
  不寫 auto_correct.json／auto_minutes.json、不改 transcript.json、run_log 有 privacy 事件；試圖用旗標或 API 金鑰繞過也一樣；
  對照組（不是本機限定）同一組假 CLI 會被呼叫
- EstimateAndRender：--estimate-only 照常（不送內容）、--render-only 照常
- TranscribeLocalOnly：transcribe.main() 整個流程（假 ASR）：--local-only 寫標記檔、管線內校正不執行（auto_correct.run 0 次）、
  明確 --correct 時 exit 6、只有 correction.enabled 時 exit 0、本機步驟照常、run_log 欄位
- RunLogPrivacy：privacy 事件、run_summary 只在本機限定時多兩欄
- Docs：SKILL 的提醒段落與措辭、README〈本機限定〉一節、雲端說明（執行中補充 #1）
- Naming：畫面與文件的供應商名稱（GPT／Claude）、common.py 的 provider: auto 註解
- EntryStatic：兩支入口的參數、標記檔名與 common 一致、本機限定時不偵測 CLI
- SendToLinks（PowerShell 7／5.1）、DropApps（Git Bash）：第二個入口的建立與移除（沙盒）
"""
import contextlib
import copy
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402

V24 = _testenv.V24
VD = _testenv.VERSION_DIR
SCRIPTS = _testenv.SCRIPTS
RUNTIME = _testenv.RUNTIME
INSTALL_PS1 = VD / "install.ps1"
INSTALL_SH = VD / "install.sh"
SKILL = VD / "payload" / "skill" / "meeting-minutes-pro" / "SKILL.md"
GIT_BASH = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))

if V24:
    import common  # noqa: E402

TRANSCRIPT_MD = """# 逐字稿：meet.wav

> 時長 00:00:30｜講者 2 位｜模型：turbo @ cpu

---

**[00:00:01] S1**：今天討論酷伯內蒂斯的升級時程，下週三之前要準備好測試環境。

**[00:00:12] S2**：好，我會先確認預算分配，再跟財務部門確認清楚。
"""
TRANSCRIPT_JSON = {"meta": {"source": "meet.wav", "duration": 30.0, "model": "turbo", "device": "cpu", "speakers": 2,
                            "content_type": "meeting"},
                   "segments": [{"start": 1.0, "end": 11.0, "speaker": "S1", "text": "今天討論"},
                                {"start": 12.0, "end": 20.0, "speaker": "S2", "text": "好"}],
                   "paragraphs": []}
FAKE_CLI_CMD = "@echo off\r\necho %~n0 %*>>\"%FAKE_CLI_LOG%\"\r\necho fake 1.0\r\nexit /b 0\r\n"


def _shells():
    return [n for n in ("pwsh", "powershell") if shutil.which(n)]


class _Folder(unittest.TestCase):
    """暫存的 runtime home（config.json）＋輸出資料夾＋假的 claude／codex（.cmd，記下每次被呼叫的參數）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-v240-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.out = self.tmp / "meet_minutes"
        self.out.mkdir()
        (self.out / "transcript.md").write_text(TRANSCRIPT_MD, encoding="utf-8")
        (self.out / "transcript.json").write_text(json.dumps(TRANSCRIPT_JSON, ensure_ascii=False), encoding="utf-8")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for n in ("claude", "codex"):
            (self.bin / f"{n}.cmd").write_text(FAKE_CLI_CMD, encoding="ascii", newline="")
        self.cli_log = self.tmp / "cli.log"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def config(self, local_only=None, **extra):
        cfg = {"backend": "ct2", "device": "cpu", "whisper": "turbo",
               "correction": {"claude": {"cli_path": str(self.bin / "claude.cmd")},
                              "openai": {"cli_path": str(self.bin / "codex.cmd")}}}
        if local_only is not None:
            cfg["privacy"] = {"local_only": local_only}
        cfg.update(extra)
        (self.home / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def marker(self):
        common.write_local_only_marker(self.out, "test")

    def run_script(self, name, *args, extra_env=None):
        env = {k: v for k, v in os.environ.items() if k.upper() not in (
            "MEETING_MINUTES_PRO_HOME", "MMP_RUN_ID", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_API_KEY", "PATH")}
        fake_user = self.tmp / "user"
        fake_user.mkdir(exist_ok=True)
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        env.update(MEETING_MINUTES_PRO_HOME=str(self.home), FAKE_CLI_LOG=str(self.cli_log), PYTHONDONTWRITEBYTECODE="1",
                   PYTHONUTF8="1", PATH=os.pathsep.join([str(self.bin), str(Path(sysroot) / "System32")]),
                   USERPROFILE=str(fake_user), HOME=str(fake_user), APPDATA=str(fake_user), LOCALAPPDATA=str(fake_user))
        env.update(extra_env or {})
        r = subprocess.run([sys.executable, "-B", str(SCRIPTS / name), str(self.out), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=env, timeout=180, stdin=subprocess.DEVNULL)
        last = (r.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            j = json.loads(last)
        except ValueError:
            j = {}
        return r, j

    def cli_calls(self):
        return self.cli_log.read_text(encoding="utf-8", errors="replace").splitlines() if self.cli_log.exists() else []

    def events(self):
        p = self.out / "run_log.jsonl"
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


@unittest.skipUnless(V24, "2.4.0 才有")
class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-v240-cfg-"))
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.tmp)

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def upgrade(self, before):
        (self.tmp / "config.json").write_text(json.dumps(before, ensure_ascii=False), encoding="utf-8")
        return common.upgrade_config()

    def test_default_false(self):
        self.assertIs(common.DEFAULTS["privacy"]["local_only"], False)
        self.assertIsNone(common.local_only_state(None, {}))

    def test_upgrade_adds_block(self):
        before = {"backend": "ct2", "runtime_version": "2.3.0", "consistency": {"enabled": True}}
        after = self.upgrade(copy.deepcopy(before))
        self.assertEqual(after["privacy"], {"local_only": False})
        self.assertIn("privacy", common.added_config_keys(before, after))

    def test_upgrade_keeps_true(self):
        before = {"runtime_version": "2.4.0", "privacy": {"local_only": True}}
        after = self.upgrade(copy.deepcopy(before))
        self.assertIs(after["privacy"]["local_only"], True)
        self.assertNotIn("privacy", common.added_config_keys(before, after))
        self.assertEqual(common.local_only_state(None, after)["sources"], ["config"])

    def test_upgrade_partial_block(self):
        after = self.upgrade({"privacy": {}})
        self.assertIs(after["privacy"]["local_only"], False)

    def test_only_true_counts(self):
        for v in ("true", 1, "yes", None, False):
            with self.subTest(v=v):
                self.assertIsNone(common.local_only_state(None, {"privacy": {"local_only": v}}))


@unittest.skipUnless(V24, "2.4.0 才有")
class MarkerAndState(_Folder):
    def test_marker_content(self):
        p = common.write_local_only_marker(self.out, "sendto", created_at="2026-11-08T14:30:00+08:00")
        self.assertEqual(p.name, "local-only.json")
        doc = json.loads(p.read_text(encoding="utf-8"))
        self.assertEqual((doc["local_only"], doc["source"], doc["created_at"], doc["version"]),
                         (True, "sendto", "2026-11-08T14:30:00+08:00", common.VERSION))
        self.assertNotIn("meet", json.dumps(doc), "標記檔不得含檔名或內容")

    def test_marker_not_overwritten(self):
        common.write_local_only_marker(self.out, "sendto", created_at="2026-01-01T00:00:00+08:00")
        common.write_local_only_marker(self.out, "transcribe")
        doc = json.loads((self.out / "local-only.json").read_text(encoding="utf-8"))
        self.assertEqual((doc["source"], doc["created_at"]), ("sendto", "2026-01-01T00:00:00+08:00"))

    def test_sources(self):
        self.assertIsNone(common.local_only_state(self.out, {}))
        self.assertEqual(common.local_only_state(self.out, {"privacy": {"local_only": True}})["source"], "config")
        (self.out / "local-only.json").write_text("", encoding="utf-8")      # 空檔也算（只看存在）
        self.assertEqual(common.local_only_state(self.out, {})["source"], "marker")
        self.assertEqual(common.local_only_state(self.out, {"privacy": {"local_only": True}})["sources"], ["config", "marker"])

    def test_message(self):
        self.marker()
        m = common.local_only_message(common.local_only_state(self.out, {"privacy": {"local_only": True}}), "AI 校正", self.out)
        for s in ("本機限定", "AI 校正", "GPT 或 Claude", "已拒絕", "沒有送出任何資料", "privacy.local_only", "改成 false",
                  "local-only.json", "刪除"):
            self.assertIn(s, m)


@unittest.skipUnless(V24, "2.4.0 才有")
class RefuseCorrect(_Folder):
    """auto_correct.py 實跑：本機限定一律 exit 6，假 CLI 0 次。"""

    def check_refused(self, r, j, source):
        self.assertEqual(r.returncode, common.LOCAL_ONLY_EXIT, r.stdout + r.stderr)
        c = j.get("correction") or {}
        self.assertEqual((c.get("status"), c.get("reason"), c.get("local_only_source")), ("skipped", "local_only", source))
        self.assertEqual(self.cli_calls(), [], "本機限定時不得執行 claude／codex 的任何指令")
        self.assertIn("本機限定", r.stderr)
        self.assertIn("沒有送出任何資料", r.stderr)
        self.assertFalse((self.out / "auto_correct.json").exists())
        self.assertFalse((self.out / "transcript.corrected.md").exists())
        self.assertEqual(json.loads((self.out / "transcript.json").read_text(encoding="utf-8")), TRANSCRIPT_JSON)
        ev = self.events()
        pv = [e for e in ev if e["event"] == "privacy"]
        self.assertEqual([(e["local_only"], e["local_only_source"]) for e in pv], [(True, source)])
        self.assertTrue(any(e["event"] == "result" and e.get("reason") == "local_only" for e in ev))
        self.assertFalse(any(e["event"] == "call" for e in ev))

    def test_config(self):
        self.config(local_only=True)
        self.check_refused(*self.run_script("auto_correct.py", "--force"), "config")

    def test_marker(self):
        self.config()
        self.marker()
        self.check_refused(*self.run_script("auto_correct.py"), "marker")

    def test_both(self):
        self.config(local_only=True)
        self.marker()
        self.check_refused(*self.run_script("auto_correct.py"), "config+marker")

    def test_no_flag_bypasses(self):
        self.config()
        self.marker()
        for args in (["--claude"], ["--openai", "--correct-model", "gpt-6.1-sol"], ["--correct-provider", "claude", "--force"],
                     ["--correct-channel", "api"], ["--claude", "--correct-model", "gpt-6.1-sol"]):   # 最後一組參數矛盾也照樣 6
            with self.subTest(args=args):
                self.check_refused(*self.run_script("auto_correct.py", *args,
                                                    extra_env={"OPENAI_API_KEY": "sk-test-not-real",
                                                               "ANTHROPIC_API_KEY": "sk-test-not-real"}), "marker")
                (self.out / "run_log.jsonl").unlink(missing_ok=True)

    def test_control_calls_cli(self):
        """對照組：不是本機限定時，同一組假 CLI 會被呼叫（證明 0 次不是假 CLI 沒接上）。"""
        self.config()
        r, j = self.run_script("auto_correct.py", "--claude")
        self.assertNotEqual((j.get("correction") or {}).get("reason"), "local_only", r.stdout + r.stderr)
        self.assertTrue(self.cli_calls(), r.stdout + r.stderr)


@unittest.skipUnless(V24, "2.4.0 才有")
class RefuseMinutes(_Folder):
    def check_refused(self, r, j, source):
        self.assertEqual(r.returncode, common.LOCAL_ONLY_EXIT, r.stdout + r.stderr)
        m = j.get("minutes") or {}
        self.assertEqual((m.get("status"), m.get("reason"), m.get("local_only_source")), ("skipped", "local_only", source))
        self.assertEqual(self.cli_calls(), [])
        self.assertIn("本機限定", r.stderr)
        for n in ("auto_minutes.json", "meeting-minutes.md", "meeting-minutes.html", "context.md"):
            self.assertFalse((self.out / n).exists(), n)
        self.assertEqual(json.loads((self.out / "transcript.json").read_text(encoding="utf-8")), TRANSCRIPT_JSON)
        ev = self.events()
        self.assertEqual([e["local_only_source"] for e in ev if e["event"] == "privacy"], [source])
        self.assertFalse(any(e["event"] == "call" for e in ev))

    def test_config(self):
        self.config(local_only=True)
        self.check_refused(*self.run_script("auto_minutes.py"), "config")

    def test_marker_and_flags(self):
        self.config()
        self.marker()
        for args in ([], ["--force"], ["--openai"], ["--claude", "--minutes-model", "opus"], ["--source", "original"],
                     ["--minutes-channel", "api"], ["--context", "一行背景"], ["--type", "course"]):
            with self.subTest(args=args):
                self.check_refused(*self.run_script("auto_minutes.py", *args, extra_env={"OPENAI_API_KEY": "sk-test-not-real"}),
                                   "marker")
                (self.out / "run_log.jsonl").unlink(missing_ok=True)

    def test_control_calls_cli(self):
        self.config()
        r, j = self.run_script("auto_minutes.py", "--claude")
        self.assertNotEqual((j.get("minutes") or {}).get("reason"), "local_only")
        self.assertTrue(self.cli_calls(), r.stdout + r.stderr)


@unittest.skipUnless(V24, "2.4.0 才有")
class EstimateAndRender(_Folder):
    def test_estimate_only_still_works(self):
        """--estimate-only 不送內容（只跑 --version／login status），本機限定時照常，另印一行提醒。"""
        self.config()
        self.marker()
        before = sorted(p.name for p in self.out.iterdir())
        r, j = self.run_script("auto_minutes.py", "--claude", "--estimate-only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIsInstance(j.get("estimate"), dict)
        self.assertIn("本機限定：這裡只有預估", r.stderr)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), before)
        for line in self.cli_calls():
            self.assertRegex(line, r"^(claude|codex) (--version|login status)\s*$", "預估不得送出內容")

    def test_render_only_still_works(self):
        self.config(local_only=True)
        (self.out / "notes.json").write_text(json.dumps({}), encoding="utf-8")
        r, j = self.run_script("auto_minutes.py", "--render-only", "--type", "course")
        self.assertNotEqual((j.get("minutes") or {}).get("reason"), "local_only", r.stdout + r.stderr)
        self.assertEqual(self.cli_calls(), [])


@unittest.skipUnless(V24, "2.4.0 才有")
class TranscribeLocalOnly(unittest.TestCase):
    """transcribe.main() 整個流程（假的轉檔與 ASR；說話者分離略過）。auto_correct.run 換成記錄器。"""

    def setUp(self):
        import numpy as np
        import soundfile as sf
        import auto_correct
        import transcribe as tr
        self.tr, self.ac = tr, auto_correct
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-v240-tr-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self._run_id = os.environ.pop("MMP_RUN_ID", None)
        self.src = self.tmp / "meet.wav"
        rng = np.random.default_rng(0)
        sf.write(str(self.src), (rng.standard_normal(16000 * 20) * 0.1).astype(np.float32), 16000)
        self.saved = {"to_wav": tr.to_wav, "load_asr": tr.load_asr, "run": auto_correct.run}
        tr.to_wav = lambda src, dst: shutil.copyfile(src, dst)

        class FakeASR:
            i = 0

            def transcribe(self, audio):
                FakeASR.i += 1
                return f"預算分配要先跟財務部門確認清楚第{FakeASR.i}句"
        tr.load_asr = lambda *a, **k: FakeASR()
        self.corr_calls = []

        def fake_run(out_dir, *a, **k):
            self.corr_calls.append(str(out_dir))
            return {"status": "ok", "reason": None, "provider": "claude", "model": "opus", "channel": "cli", "chunks": 1,
                    "chunks_ok": 1, "fallback": None}
        auto_correct.run = fake_run

    def tearDown(self):
        self.tr.to_wav, self.tr.load_asr, self.ac.run = self.saved["to_wav"], self.saved["load_asr"], self.saved["run"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        os.environ.pop("MMP_LOCAL_ONLY_SOURCE", None)
        if self._run_id is not None:
            os.environ["MMP_RUN_ID"] = self._run_id
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, *extra, cfg=None):
        (self.home / "config.json").write_text(json.dumps(cfg or {}), encoding="utf-8")
        out = self.tmp / f"out{len(list(self.tmp.glob('out*')))}"
        argv = sys.argv
        sys.argv = ["transcribe.py", str(self.src), "--out-dir", str(out), "--no-corrections", "--no-diarize",
                    "--backend", "ct2", "--device", "cpu", *extra]
        so, se = io.StringIO(), io.StringIO()
        code = 0
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                self.tr.main()
        except SystemExit as ex:
            code = ex.code
        finally:
            sys.argv = argv
        self.err = se.getvalue()
        res = json.loads(so.getvalue().strip().splitlines()[-1])
        import runlog
        return code, res, out, runlog.read_events(out / runlog.LOG_NAME)

    def test_flag_writes_marker_and_local_steps_run(self):
        os.environ["MMP_LOCAL_ONLY_SOURCE"] = "sendto"
        code, res, out, ev = self.main("--no-correct", "--local-only")
        self.assertEqual(code, 0)
        doc = json.loads((out / "local-only.json").read_text(encoding="utf-8"))
        self.assertEqual((doc["local_only"], doc["source"]), (True, "sendto"))
        for n in ("transcript.md", "transcript.json", "transcript.srt", "transcript.cues.srt"):
            self.assertTrue((out / n).exists(), n)
        self.assertEqual(res["local_only"], "marker")
        self.assertEqual([e["local_only_source"] for e in ev if e["event"] == "privacy"], ["marker"])
        summ = [e for e in ev if e["event"] == "run_summary"][-1]
        self.assertEqual((summ["local_only"], summ["local_only_source"]), (True, "marker"))
        self.assertIn("本機限定（標記檔）：不會送出任何資料到 GPT 或 Claude", self.err)
        self.assertEqual(self.corr_calls, [])

    def test_explicit_correct_refused_exit6(self):
        for flag in ("--correct", "--claude", "--openai"):
            with self.subTest(flag=flag):
                code, res, out, ev = self.main(flag, "--local-only")
                self.assertEqual(code, common.LOCAL_ONLY_EXIT)
                self.assertEqual((res["correction"]["status"], res["correction"]["reason"]), ("skipped", "local_only"))
                self.assertTrue((out / "transcript.md").exists(), "轉寫照常完成")
                self.assertEqual(self.corr_calls, [])
                self.assertIn("已拒絕，沒有送出任何資料", self.err)
                self.assertIn("[1/4]", self.err)
                self.assertTrue(any(e["event"] == "result" and e.get("step") == "correct" and e.get("reason") == "local_only"
                                    for e in ev))

    def test_config_enabled_exit0(self):
        code, res, out, ev = self.main(cfg={"privacy": {"local_only": True}, "correction": {"enabled": True}})
        self.assertEqual(code, 0)
        self.assertEqual(res["correction"]["reason"], "local_only")
        self.assertEqual(res["local_only"], "config")
        self.assertFalse((out / "local-only.json").exists(), "全域設定不寫標記檔")
        self.assertEqual(self.corr_calls, [])

    def test_control_without_local_only(self):
        code, res, out, ev = self.main("--correct")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.corr_calls), 1)
        self.assertNotIn("local_only", res)
        self.assertFalse(any(e["event"] == "privacy" for e in ev))
        summ = [e for e in ev if e["event"] == "run_summary"][-1]
        self.assertNotIn("local_only", summ)


@unittest.skipUnless(V24, "2.4.0 才有")
class RunLogPrivacy(unittest.TestCase):
    def test_summary_fields(self):
        import runlog
        tmp = Path(tempfile.mkdtemp(prefix="mmp-v240-rl-"))
        try:
            rl = runlog.RunLog(tmp, run_id="r1", owns=True, step="transcribe")
            self.assertIsNone(rl.privacy(None))
            rl.event("checkpoint", name="asr", duration_sec=1.0)
            base = runlog.summarize(runlog.read_events(rl.path, "r1"), tmp)
            self.assertNotIn("local_only", base)
            rl.privacy({"source": "config+marker"})
            s = runlog.summarize(runlog.read_events(rl.path, "r1"), tmp)
            self.assertEqual((s["local_only"], s["local_only_source"]), (True, "config+marker"))
            skip = ("finished_at", "wall_sec")                    # 兩次 summarize 的時間不同
            self.assertEqual({k: v for k, v in s.items() if k not in ("local_only", "local_only_source") + skip},
                             {k: v for k, v in base.items() if k not in skip})
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(V24, "2.4.0 才有")
class Docs(unittest.TestCase):
    def test_skill_reminder(self):
        s = SKILL.read_text(encoding="utf-8")
        sec = s[s.index("### 0.1 本機限定（機敏會議）（2.4）"):s.index("## 1. 開始前確認")]
        for t in ("**讀逐字稿內容（", "之前**，先說：「這份是本機限定。在這個對話裡讀逐字稿＝逐字稿與截圖會送到 Anthropic 雲端（Claude）。要繼續嗎？",
                  "**等使用者明確回答要繼續**才讀", "不執行 `auto_correct.py`、`auto_minutes.py`", "privacy.local_only",
                  "local-only.json", "會議記錄校稿", "exit 6", "你不要替使用者刪標記檔或改設定", "何時用", "怎麼解除"):
            self.assertIn(t, sec, t)
        self.assertIn("本機限定、機敏會議時使用", s)
        desc = re.search(r"^description: (.*)$", s, re.M).group(1)
        self.assertLessEqual(len(desc), 1024)

    def test_cloud_wording(self):
        """執行中補充 #1：不再只說「Claude 只讀逐字稿」，寫明對話中讀到的逐字稿與截圖送到 Anthropic 雲端。"""
        s = SKILL.read_text(encoding="utf-8")
        rd = (VD / "README.md").read_text(encoding="utf-8")
        for txt, where in ((s, "SKILL"), (rd, "README")):
            self.assertNotIn("Claude 只讀逐字稿", txt, where)
            self.assertNotIn("Claude 只會讀到逐字稿", txt, where)
            self.assertNotIn("（只讀逐字稿）", txt, where)
            self.assertIn("在 Claude 對話（Claude Code、Claude 桌面 App）中讀到的逐字稿與", txt, where)
            self.assertIn("送到 Anthropic 雲端", txt, where)
            self.assertIn("沒有另外的送出確認", txt, where)

    def test_readme_section(self):
        rd = (VD / "README.md").read_text(encoding="utf-8")
        sec = rd[rd.index("### 17. 本機限定（機敏會議）（2.4.0）"):rd.index("## 升級注意（1.x → 2.0）")]
        for t in ("**何時用**", "**兩種開法**", "**會做什麼**", "**不做什麼**", "**改用人工校稿**", "**怎麼解除**",
                  "會議轉寫（Pro，本機限定）", "privacy.local_only", "local-only.json", "exit 6", "沒有 AI 摘要", "經驗"):
            self.assertIn(t, sec, t)
        self.assertIn("(#17-本機限定機敏會議240)", rd)
        self.assertIn("**2.4.0 新功能：本機限定（機敏會議）**", rd)


# 〔2.4.0〕命名：程式畫面、安裝程式、SKILL、README 不再出現以下說法（設定值、旗標、帳號／金鑰／條款、SDK、檔案表頭除外）
# 「送到 Anthropic 雲端」是 Claude 對話本身的說明（執行中補充 #1），不是 AI 校正的供應商稱呼
OLD_NAMES = ("Claude 或 OpenAI", "Anthropic 或 OpenAI", "OpenAI gpt-6.1-sol", "OpenAI `gpt-", "會送到 OpenAI", r"會送到 Anthropic(?! 雲端)",
             "要用 OpenAI", "將使用：OpenAI", "Claude／OpenAI")


@unittest.skipUnless(V24, "2.4.0 才有")
class Naming(unittest.TestCase):
    FILES = ("payload/runtime/mm-sendto.ps1", "payload/runtime/mm-dropped.sh", "install.ps1", "install.sh", "README.md",
             "payload/skill/meeting-minutes-pro/SKILL.md", "payload/skill/meeting-minutes-pro/references/custom-template-format.md",
             "payload/runtime/scripts/auto_correct.py", "payload/runtime/scripts/auto_minutes.py",
             "payload/runtime/scripts/transcribe.py", "payload/runtime/scripts/common.py")

    def test_no_old_names(self):
        hits = []
        for rel in self.FILES:
            for i, line in enumerate((VD / rel).read_text(encoding="utf-8-sig").splitlines(), 1):
                hits += [f"{rel}:{i}：{w}" for w in OLD_NAMES if re.search(w, line)]
        self.assertEqual(hits, [], "\n".join(hits))

    def test_labels(self):
        import auto_correct as ac
        self.assertEqual(ac.PROVIDER_LABEL, {"claude": "Claude", "openai": "GPT"})
        self.assertEqual(ac.VENDOR, {"claude": "Claude（Anthropic）", "openai": "GPT（OpenAI）"})
        self.assertEqual(ac.PROVIDER_NAME, {"claude": "Claude", "openai": "OpenAI"}, "檔案表頭格式凍結（1.1.0）")
        sendto = (RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        self.assertIn('$Vendor = @{ claude = "Claude（Anthropic）"; openai = "GPT（OpenAI）" }', sendto)
        self.assertIn('label = "GPT gpt-6.1-sol"', sendto)
        dropped = (RUNTIME / "mm-dropped.sh").read_text(encoding="utf-8")
        self.assertIn('"openai:gpt-6.1-sol|GPT gpt-6.1-sol|"', dropped)

    def test_common_comment(self):
        s = (SCRIPTS / "common.py").read_text(encoding="utf-8")
        self.assertIn("auto＝有已登入的 codex CLI 用 GPT，否則有 claude CLI 用 Claude", s)
        self.assertNotIn("auto＝有 claude CLI 用 Claude，否則有 codex CLI 用 OpenAI", s)
        self.assertIn("auto 的選法與 correction 相同（已登入的 codex 優先＝GPT）", s)


@unittest.skipUnless(V24, "2.4.0 才有")
class EntryStatic(unittest.TestCase):
    def test_marker_name_consistent(self):
        sendto = (RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        dropped = (RUNTIME / "mm-dropped.sh").read_text(encoding="utf-8")
        self.assertIn(f'$LocalOnlyMarker = "{common.LOCAL_ONLY_MARKER}"', sendto)
        self.assertIn(f'LOCAL_ONLY_MARKER="{common.LOCAL_ONLY_MARKER}"', dropped)

    def test_params(self):
        sendto = (RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("param([switch]$LocalOnly, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Files)", sendto)
        self.assertIn('if ($LocalOnly) { $argList += "--local-only" }', sendto)
        self.assertIn("if (-not $LoStart) {", sendto)                    # 本機限定時不偵測 CLI
        dropped = (RUNTIME / "mm-dropped.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "${1:-}" = "--local-only" ]; then LOCAL_ONLY=1; shift; fi', dropped)
        self.assertIn("if [ -n \"$LOCAL_ONLY\" ]; then args+=(--local-only); fi", dropped)
        self.assertIn('if [ -z "$LO_START" ]; then', dropped)
        for s in (sendto, dropped):
            self.assertIn("本機限定：沒有送出任何資料", s)
            self.assertIn("會議記錄校稿", s)

    def test_no_bypass_flag(self):
        for name in ("auto_correct.py", "auto_minutes.py", "transcribe.py"):
            s = (SCRIPTS / name).read_text(encoding="utf-8")
            self.assertNotRegex(s, r"--(no-local-only|allow-cloud|ignore-local-only|force-send)", name)


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


@unittest.skipUnless(V24 and os.name == "nt", "2.4.0、Windows 才有")
class SendToLinks(unittest.TestCase):
    """第二個右鍵入口：install.ps1 的 New-SendToLink 實跑（沙盒 SendTo），與 install.ps1 -Uninstall -TestRoot 移除兩個捷徑。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v240-lnk-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_create_both(self):
        src = INSTALL_PS1.read_text(encoding="utf-8-sig")
        fn = re.search(r"(?ms)^function New-SendToLink\(.*?^\}", src).group(0)
        calls = re.findall(r'(?m)^New-SendToLink \$SendToLnk(?:Local)? .*$', src)
        self.assertEqual(len(calls), 2)
        for sh in _shells():
            with self.subTest(shell=sh):
                d = self.root / sh
                (d / "SendTo").mkdir(parents=True)
                script = (f"$MMH = {_ps_quote(d / 'home')}\n$SendToLnk = {_ps_quote(d / 'SendTo' / '會議轉寫（Pro）.lnk')}\n"
                          f"$SendToLnkLocal = {_ps_quote(d / 'SendTo' / '會議轉寫（Pro，本機限定）.lnk')}\n"
                          + fn + "\n" + "\n".join(calls) + "\n"
                          "$ws = New-Object -ComObject WScript.Shell\n"
                          "$o = @(Get-ChildItem -LiteralPath (Split-Path $SendToLnk) -Filter *.lnk | Sort-Object Name | ForEach-Object {"
                          " $l = $ws.CreateShortcut($_.FullName); [ordered]@{ name = $_.Name; args = $l.Arguments;"
                          " desc = $l.Description; target = $l.TargetPath } })\n"
                          "[Console]::OutputEncoding = [Text.Encoding]::UTF8\nConvertTo-Json -InputObject $o -Compress\n")
                ps = d / "t.ps1"
                ps.write_text(script, encoding="utf-8-sig")
                r = subprocess.run([sh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr)
                links = {x["name"]: x for x in json.loads(r.stdout.strip().splitlines()[-1])}
                self.assertEqual(sorted(links), ["會議轉寫（Pro）.lnk", "會議轉寫（Pro，本機限定）.lnk"])
                n, lo = links["會議轉寫（Pro）.lnk"], links["會議轉寫（Pro，本機限定）.lnk"]
                self.assertTrue(n["args"].endswith('mm-sendto.ps1"'), n["args"])
                self.assertTrue(lo["args"].endswith('mm-sendto.ps1" -LocalOnly'), lo["args"])
                self.assertIn("本機限定", lo["desc"])
                self.assertTrue(lo["target"].lower().endswith("powershell.exe"))

    def test_uninstall_removes_both(self):
        for sh in _shells():
            with self.subTest(shell=sh):
                st = self.root / "SendTo"
                st.mkdir(exist_ok=True)
                for n in ("會議轉寫（Pro）.lnk", "會議轉寫（Pro，本機限定）.lnk", "其他.lnk"):
                    (st / n).write_bytes(b"x")
                env = {k: v for k, v in os.environ.items() if k != "MEETING_MINUTES_PRO_HOME"}
                r = subprocess.run([sh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1), "-Uninstall",
                                    "-TestRoot", str(self.root)], input="n\n", capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", env=env, timeout=120)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(sorted(p.name for p in st.iterdir()), ["其他.lnk"])
                self.assertIn("已移除右鍵「傳送到 → 會議轉寫（Pro，本機限定）」", r.stdout)


def _sh_parts() -> str:
    s = INSTALL_SH.read_text(encoding="utf-8")
    helpers = re.search(r"^c_cyan=.*?^fail\(\) \{.*?\n", s, re.S | re.M).group(0)
    un = re.search(r"^uninstall_proofread\(\) \{.*?\n\}\n\ndo_uninstall\(\) \{.*?\n\}\n", s, re.S | re.M).group(0)
    mk = re.search(r"^make_drop_app\(\) \{.*?^APPLESCRIPT\n\}\n", s, re.S | re.M).group(0)
    return helpers + un + mk


@unittest.skipUnless(V24 and GIT_BASH.exists(), "2.4.0、要有 Git Bash")
class DropApps(unittest.TestCase):
    """macOS 的第二個拖放入口：install.sh 的 make_drop_app（假的 osacompile 記下 AppleScript）與 do_uninstall（Git Bash 實跑）。"""

    def setUp(self):
        base = HERE / "_out" if (HERE / "_out").is_dir() else None
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v240-app-", dir=base))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def bash(self, body, inp=""):
        root = self.root.as_posix()
        script = ('osacompile() { mkdir -p "$2"; cat > "$2/script.applescript"; }\n' + _sh_parts()
                  + f'\nTEST_ROOT="{root}"; MMH="{root}/home"; SKILL_DST="{root}/skills/meeting-minutes-pro"\n'
                  f'APPS_DIR="{root}/Applications"; APP_DST="$APPS_DIR/會議轉寫（Pro）.app"; '
                  f'APP_DST_LOCAL="$APPS_DIR/會議轉寫（Pro，本機限定）.app"; LEGACY_APP="$APPS_DIR/y.app"\n'
                  f'UPLOAD_ZIP="{root}/Desktop/z.zip"; DESKTOP_DIR="{root}/Desktop"\n' + body)
        return subprocess.run([str(GIT_BASH), "-c", script], input=inp, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60)

    def test_make_and_remove(self):
        r = self.bash('make_drop_app "$APP_DST" "會議轉寫（Pro）" ""\n'
                      'make_drop_app "$APP_DST_LOCAL" "會議轉寫（Pro，本機限定）" "--local-only"\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        apps = self.root / "Applications"
        normal = (apps / "會議轉寫（Pro）.app" / "script.applescript").read_text(encoding="utf-8")
        local = (apps / "會議轉寫（Pro，本機限定）.app" / "script.applescript").read_text(encoding="utf-8")
        mm = (self.root / "home" / "mm-dropped.sh").as_posix()
        self.assertIn(f'    set cmd to quoted form of "{mm}"\n', normal)
        self.assertNotIn("--local-only", normal)
        self.assertIn(f'    set cmd to quoted form of "{mm}" & " --local-only"\n', local)
        self.assertIn('with title "會議轉寫（Pro，本機限定）"', local)
        (self.root / "skills" / "meeting-minutes-pro").mkdir(parents=True)
        (self.root / "home").mkdir()
        r = self.bash("do_uninstall\n", "n\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(list(apps.iterdir()), [])
        self.assertIn("已移除 會議轉寫（Pro，本機限定）.app", r.stdout)


if __name__ == "__main__":
    unittest.main()
