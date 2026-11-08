"""〔2.4.1〕config.json 讀不了或值看不懂時，全域本機限定當成「開」（規格 2.4.1）。不呼叫任何模型。

- Table：判定表每一列（不存在、true、false、沒有 privacy、空檔、只有空白、壞 JSON、非 UTF-8、BOM、最外層是陣列／字串／null、
  privacy 不是物件、local_only 是 "true"／1／0／null／"false"、資料夾、讀取時 PermissionError／其他 OSError（mock））；
  read_config() 的三種結果；load_config() 讀不了時回 {}；標記檔同時存在時來源 config-unreadable+marker；訊息內容
- Writers：upgrade_config()、save_config()、setup_gpu_diar.set_status() 遇到讀不了的檔丟 ConfigUnreadable、原檔逐位元不變；
  setup_gpu_diar.py --set-status 與 setup_backend.py（子行程）exit 5、原檔不變；值看不懂的檔讀得到，升級照常、值原樣保留；
  common.py check-config／local-only 命令列
- Refuse：auto_correct.py／auto_minutes.py 實跑（子行程）：讀不了或值看不懂 → exit 6、reason local_only、
  local_only_source config-unreadable、local_only_config_reason、假 claude／codex 被呼叫 0 次、run_log 的 privacy 事件
  （config_reason，不含路徑）；--estimate-only 的提醒寫出原因
- Transcribe：transcribe.main()（假 ASR）：開頭警告、轉寫照常、JSON 的 local_only 是 config-unreadable、管線內校正 0 次、
  明確 --correct 時 exit 6
- InstallerPs：install.ps1 -TestRoot（PowerShell 7／5.1 實跑）：壞檔時一開始就 exit 1、訊息有路徑與原因、原檔逐位元不變、
  沒有安裝任何東西；Test-ConfigFilePs（沒有 Python 時的退路）逐列
- InstallerSh：install.sh 的 assert_config_readable（Git Bash 實跑）
- EntryStatic／Docs：兩支入口改用 common.py local-only 判定、不再自己讀 privacy.local_only；README、SKILL 的說明
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
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402

V241 = _testenv.VER >= (2, 4, 1)
VD = _testenv.VERSION_DIR
SCRIPTS = _testenv.SCRIPTS
RUNTIME = _testenv.RUNTIME
INSTALL_PS1 = VD / "install.ps1"
INSTALL_SH = VD / "install.sh"
SKILL = VD / "payload" / "skill" / "meeting-minutes-pro" / "SKILL.md"
GIT_BASH = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))

if V241:
    import common  # noqa: E402
    import test_v240 as v240  # noqa: E402

# 讀不了的檔：(名稱, 內容 bytes, 原因代碼)
UNREADABLE = [
    ("empty", b"", "empty"),
    ("spaces", b"  \r\n\t ", "empty"),
    ("bad_json", b'{"backend": "ct2", "privacy": {"local_only": true},', "bad_json"),
    ("not_json", b"local_only = true", "bad_json"),
    ("not_utf8", '{"privacy": {"local_only": false}, "x": "會議"}'.encode("cp950"), "not_utf8"),
    ("bom", b"\xef\xbb\xbf" + b'{"privacy": {"local_only": false}}', "bad_json"),
    ("array", b'[{"privacy": {"local_only": false}}]', "not_object"),
    ("string", b'"privacy"', "not_object"),
    ("null", b"null", "not_object"),
]
# 讀得到但值看不懂：(名稱, config)
BAD_VALUE = [
    ("privacy_true", {"privacy": True}),
    ("privacy_null", {"privacy": None}),
    ("privacy_list", {"privacy": ["local_only"]}),
    ("str_true", {"privacy": {"local_only": "true"}}),
    ("str_false", {"privacy": {"local_only": "false"}}),
    ("one", {"privacy": {"local_only": 1}}),
    ("zero", {"privacy": {"local_only": 0}}),
    ("null", {"privacy": {"local_only": None}}),
]
# 關：(名稱, config)
OFF = [
    ("false", {"backend": "ct2", "privacy": {"local_only": False}}),
    ("no_privacy", {"backend": "ct2"}),
    ("empty_object", {}),
    ("privacy_empty", {"privacy": {}}),
    ("privacy_other_key", {"privacy": {"other": True}}),
]


def _ps_quote(p) -> str:
    return "'" + str(p).replace("'", "''") + "'"


def _shells():
    return [n for n in ("pwsh", "powershell") if shutil.which(n)]


class _Home(unittest.TestCase):
    """暫存的 MEETING_MINUTES_PRO_HOME（測試結束還原）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-v241-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._home = os.environ.get("MEETING_MINUTES_PRO_HOME")
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self.cfg = self.home / "config.json"

    def tearDown(self):
        if self._home is None:
            os.environ.pop("MEETING_MINUTES_PRO_HOME", None)
        else:
            os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, data):
        if isinstance(data, bytes):
            self.cfg.write_bytes(data)
        else:
            self.cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return self.cfg.read_bytes()


@unittest.skipUnless(V241, "2.4.1 才有")
class Table(_Home):
    def test_missing(self):
        self.assertEqual(common.read_config()["status"], "missing")
        self.assertIsNone(common.local_only_state())
        self.assertEqual(common.load_config(), {})

    def test_true(self):
        self.write({"privacy": {"local_only": True}})
        st = common.local_only_state()
        self.assertEqual((st["source"], st["sources"]), ("config", ["config"]))
        self.assertNotIn("config_problem", st)

    def test_off_rows(self):
        for name, cfg in OFF:
            with self.subTest(name):
                self.write(cfg)
                self.assertEqual(common.read_config()["status"], "ok")
                self.assertIsNone(common.local_only_state())
                self.assertEqual(common.load_config(), cfg)

    def test_unreadable_rows(self):
        for name, data, reason in UNREADABLE:
            with self.subTest(name):
                self.write(data)
                rc = common.read_config()
                self.assertEqual((rc["status"], rc["reason"], rc["config"]), ("unreadable", reason, {}))
                self.assertEqual(common.load_config(), {}, "一般設定照舊用預設值")
                st = common.local_only_state()
                self.assertEqual((st["local_only"], st["source"]), (True, "config-unreadable"))
                self.assertEqual((st["config_problem"]["reason"], st["config_problem"]["path"]), (reason, str(self.cfg)))
                # 傳進 cfg（2.4.0 的呼叫方式，例 auto_correct 先 load_config()）也一樣：檔案讀不了就是開
                self.assertEqual(common.local_only_state(None, {})["source"], "config-unreadable")
                self.assertEqual(common.local_only_state(None, {"privacy": {"local_only": False}})["source"],
                                 "config-unreadable")

    def test_bom_detail(self):
        self.write(b"\xef\xbb\xbf{}")
        self.assertIn("BOM", common.read_config()["detail"])

    def test_bad_value_rows(self):
        for name, cfg in BAD_VALUE:
            with self.subTest(name):
                self.write(cfg)
                self.assertEqual(common.read_config()["status"], "ok", "值看不懂不是讀不了")
                st = common.local_only_state()
                self.assertEqual((st["source"], st["config_problem"]["reason"]), ("config-unreadable", "bad_value"))
                self.assertIn("只認得 true 或 false" if isinstance(cfg["privacy"], dict) else "privacy 應該是物件",
                              st["config_problem"]["detail"])

    def test_directory(self):
        self.cfg.mkdir()
        rc = common.read_config()
        self.assertEqual((rc["status"], rc["reason"]), ("unreadable", "is_dir"))
        self.assertEqual(common.local_only_state()["source"], "config-unreadable")

    def test_permission_error_mock(self):
        self.write({"privacy": {"local_only": False}})
        real = Path.read_bytes

        def deny(p, *a, **k):
            if Path(p) == self.cfg:
                raise PermissionError(13, "Permission denied")
            return real(p, *a, **k)
        with mock.patch.object(Path, "read_bytes", deny):
            rc = common.read_config()
            st = common.local_only_state()
        self.assertEqual((rc["status"], rc["reason"]), ("unreadable", "permission"))
        self.assertEqual(st["source"], "config-unreadable")

    def test_other_oserror_mock(self):
        """被別的程式鎖住（Windows sharing violation）等其他 OSError。"""
        self.write({"privacy": {"local_only": False}})
        with mock.patch.object(Path, "read_bytes", side_effect=OSError(32, "The process cannot access the file")):
            rc = common.read_config()
        self.assertEqual((rc["status"], rc["reason"]), ("unreadable", "os_error"))
        self.assertIn("cannot access", rc["detail"])

    def test_file_not_found_is_missing(self):
        """不存在（FileNotFoundError）照舊是關，與讀不了分開。"""
        with mock.patch.object(Path, "read_bytes", side_effect=FileNotFoundError(2, "No such file")):
            self.assertEqual(common.read_config()["status"], "missing")
            self.assertIsNone(common.local_only_state())

    def test_with_marker(self):
        out = self.tmp / "out"
        common.write_local_only_marker(out, "test")
        self.write(b"{")
        self.assertEqual(common.local_only_state(out)["source"], "config-unreadable+marker")
        self.write({"privacy": {"local_only": "yes"}})
        self.assertEqual(common.local_only_state(out)["sources"], ["config-unreadable", "marker"])
        self.write({"privacy": {"local_only": False}})
        self.assertEqual(common.local_only_state(out)["source"], "marker")

    def test_message(self):
        self.write(b'{"privacy": ')
        st = common.local_only_state()
        m = common.local_only_message(st, "AI 校正")
        for s in ("本機限定", "config.json 讀不了", "不是合法的 JSON", "第 1 行第", "為了不外送，已當成本機限定", "AI 校正",
                  "已拒絕，沒有送出任何資料", "要解除：修好", str(self.cfg), "或刪掉它再重新執行安裝程式",
                  "重建的 config.json 本機限定是關"):
            self.assertIn(s, m)
        self.write({"privacy": {"local_only": "true"}})
        m = common.local_only_message(common.local_only_state(), "AI 整理（會議摘要／筆記）")
        for s in ('config.json 的值看不懂：privacy.local_only 是 "true"，只認得 true 或 false', "privacy.local_only 只能是 true 或 false",
                  str(self.cfg)):
            self.assertIn(s, m)

    def test_sources_constant(self):
        self.assertEqual(common.LOCAL_ONLY_SOURCES, ("config", "config-unreadable", "marker"))


@unittest.skipUnless(V241, "2.4.1 才有")
class Writers(_Home):
    def assert_refused(self, fn, before):
        with self.assertRaises(common.ConfigUnreadable) as cm:
            fn()
        self.assertEqual(self.cfg.read_bytes(), before, "原檔逐位元不變")
        s = str(cm.exception)
        for t in ("config.json 讀不了", str(self.cfg), "沒有寫入任何東西", "修好", "刪掉"):
            self.assertIn(t, s)

    def test_upgrade_and_save_refuse(self):
        import setup_gpu_diar
        for name, data, _ in UNREADABLE:
            with self.subTest(name):
                before = self.write(data)
                self.assert_refused(common.upgrade_config, before)
                self.assert_refused(lambda: common.upgrade_config(correction={"enabled": True}), before)
                self.assert_refused(lambda: common.save_config(backend="ct2"), before)
                self.assert_refused(lambda: setup_gpu_diar.set_status("none"), before)

    def test_directory_untouched(self):
        self.cfg.mkdir()
        with self.assertRaises(common.ConfigUnreadable):
            common.upgrade_config()
        self.assertTrue(self.cfg.is_dir())

    def test_bad_value_kept(self):
        """值看不懂的檔讀得到：升級照常、值原樣保留（使用者設的 "true" 不被改成 false，之後仍是本機限定）。"""
        for name, cfg in BAD_VALUE:
            with self.subTest(name):
                self.write(dict(cfg, backend="ct2"))
                after = common.upgrade_config()
                self.assertEqual(after["privacy"], cfg["privacy"])
                self.assertEqual(json.loads(self.cfg.read_text(encoding="utf-8"))["privacy"], cfg["privacy"])
                self.assertEqual(common.local_only_state()["source"], "config-unreadable")

    def test_missing_still_creates(self):
        cfg = common.upgrade_config()
        self.assertIs(cfg["privacy"]["local_only"], False)
        self.assertTrue(self.cfg.exists())

    def _run(self, *args):
        env = dict(os.environ, MEETING_MINUTES_PRO_HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-B", *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=120, stdin=subprocess.DEVNULL)

    def test_setup_scripts_exit5(self):
        before = self.write(b'{"backend": "ct2",')
        r = self._run(SCRIPTS / "setup_gpu_diar.py", "--set-status", "none")
        self.assertEqual(r.returncode, common.CONFIG_UNREADABLE_EXIT, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout.strip().splitlines()[-1])["gpu_diar"]["reason"], "config_unreadable")
        self.assertIn("config.json 讀不了", r.stderr)
        r = self._run(SCRIPTS / "setup_backend.py", "--force", "ct2:cpu")
        self.assertEqual(r.returncode, common.CONFIG_UNREADABLE_EXIT, r.stdout + r.stderr)
        self.assertIn("config.json 讀不了", r.stdout + r.stderr)
        self.assertEqual(self.cfg.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), ["config.json"], "沒有下載或寫入任何東西")

    def test_cli(self):
        before = self.write(b"[]")
        r = self._run(SCRIPTS / "common.py", "check-config")
        self.assertEqual(r.returncode, common.CONFIG_UNREADABLE_EXIT)
        self.assertEqual(json.loads(r.stdout)["reason"], "not_object")
        self.assertIn("沒有寫入任何東西", r.stderr)
        j = json.loads(self._run(SCRIPTS / "common.py", "local-only").stdout)
        self.assertEqual((j["local_only"], j["source"], j["config_problem"]["reason"]), (True, "config-unreadable", "not_object"))
        self.assertIn("為了不外送", j["why"])
        lines = self._run(SCRIPTS / "common.py", "local-only", "--lines").stdout.splitlines()
        self.assertEqual(lines[:2], ["1", "config-unreadable"])
        self.assertEqual(len(lines), 4)
        self.assertEqual(self.cfg.read_bytes(), before)
        self.write({"privacy": {"local_only": False}})
        self.assertEqual(self._run(SCRIPTS / "common.py", "check-config").returncode, 0)
        self.assertEqual(json.loads(self._run(SCRIPTS / "common.py", "local-only").stdout), {"local_only": False, "source": None})
        self.assertEqual(self._run(SCRIPTS / "common.py", "local-only", "--lines").stdout.splitlines()[:2], ["0", ""])
        self.cfg.unlink()
        self.assertEqual(json.loads(self._run(SCRIPTS / "common.py", "check-config").stdout)["status"], "missing")


if V241:
    class _RefuseBase(v240._Folder):
        def raw(self, data: bytes):
            (self.home / "config.json").write_bytes(data)

        def check(self, r, j, key, source, reason):
            self.assertEqual(r.returncode, common.LOCAL_ONLY_EXIT, r.stdout + r.stderr)
            o = j.get(key) or {}
            self.assertEqual((o.get("status"), o.get("reason"), o.get("local_only_source"), o.get("local_only_config_reason")),
                             ("skipped", "local_only", source, reason))
            self.assertEqual(self.cli_calls(), [], "不得找 CLI 或執行 claude／codex")
            self.assertIn("為了不外送，已當成本機限定", r.stderr)
            self.assertIn("沒有送出任何資料", r.stderr)
            self.assertEqual(json.loads((self.out / "transcript.json").read_text(encoding="utf-8")), v240.TRANSCRIPT_JSON)
            pv = [e for e in self.events() if e["event"] == "privacy"]
            self.assertEqual([(e["local_only_source"], e.get("config_reason")) for e in pv], [(source, reason)])
            log = (self.out / "run_log.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("config.json", log, "run_log 只記代碼，不記路徑")
            self.assertFalse(any(e["event"] == "call" for e in self.events()))
            (self.out / "run_log.jsonl").unlink(missing_ok=True)
else:
    _RefuseBase = unittest.TestCase


@unittest.skipUnless(V241, "2.4.1 才有")
class Refuse(_RefuseBase):
    KEYS = {"auto_correct.py": ("correction", "auto_correct.json"), "auto_minutes.py": ("minutes", "auto_minutes.json")}

    def test_unreadable_exit6(self):
        for script, (key, rec) in self.KEYS.items():
            for name, data, reason in UNREADABLE:
                with self.subTest(script=script, case=name):
                    self.raw(data)
                    r, j = self.run_script(script, "--force", extra_env={"OPENAI_API_KEY": "sk-test-not-real"})
                    self.check(r, j, key, "config-unreadable", reason)
                    self.assertIn("config.json 讀不了", r.stderr)
                    self.assertFalse((self.out / rec).exists())

    def test_bad_value_exit6(self):
        for script, (key, _) in self.KEYS.items():
            for args in ([], ["--claude"], ["--openai"]):
                with self.subTest(script=script, args=args):
                    self.config(local_only="true")
                    r, j = self.run_script(script, *args)
                    self.check(r, j, key, "config-unreadable", "bad_value")
                    self.assertIn('privacy.local_only 是 "true"', r.stderr)

    def test_with_marker(self):
        self.raw(b"{")
        self.marker()
        r, j = self.run_script("auto_correct.py")
        self.check(r, j, "correction", "config-unreadable+marker", "bad_json")

    def test_estimate_only(self):
        self.raw(b"{")
        r, j = self.run_script("auto_minutes.py", "--estimate-only")
        self.assertIn("本機限定：這裡只有預估（沒有送出任何資料）；正式執行會被拒絕（config.json 讀不了", r.stderr)
        self.assertFalse((self.out / "auto_minutes.json").exists())

    def test_control_false_still_sends(self):
        """對照組：讀得到且 local_only: false 時照常找 CLI（證明 0 次不是假 CLI 沒接上）。"""
        self.config(local_only=False)
        r, j = self.run_script("auto_correct.py", "--claude")
        self.assertNotEqual((j.get("correction") or {}).get("reason"), "local_only", r.stdout + r.stderr)
        self.assertTrue(self.cli_calls(), r.stdout + r.stderr)


if V241:
    class _TranscribeBase(v240.TranscribeLocalOnly):
        pass
    for _n in [n for n in dir(v240.TranscribeLocalOnly) if n.startswith("test")]:
        setattr(_TranscribeBase, _n, None)              # 只借 setUp／main，不重跑 2.4.0 的測試
else:
    _TranscribeBase = unittest.TestCase


@unittest.skipUnless(V241, "2.4.1 才有")
class Transcribe(_TranscribeBase):
    def main_raw(self, data: bytes, *extra):
        """config.json 寫成指定的 bytes 後跑 main()（main() 自己寫 config.json 的那一次改成不寫）。"""
        orig = Path.write_text
        (self.home / "config.json").write_bytes(data)
        with mock.patch.object(Path, "write_text", lambda p, *a, **k: None if Path(p) == self.home / "config.json"
                               else orig(p, *a, **k)):
            return self.main(*extra)

    def test_warning_and_local_only(self):
        code, res, out, ev = self.main_raw(b'{"backend": "ct2",', "--no-correct")
        self.assertEqual(code, 0)
        self.assertIn("[!] config.json 讀不了：不是合法的 JSON", self.err)
        self.assertIn("這次的設定都用預設值", self.err)
        self.assertNotIn("找不到 config.json", self.err)
        self.assertIn("本機限定（config.json 讀不了：", self.err)
        self.assertIn("為了不外送，已當成本機限定）：不會送出任何資料到 GPT 或 Claude", self.err)
        self.assertTrue((out / "transcript.md").exists(), "轉寫照常")
        self.assertFalse((out / "local-only.json").exists(), "全域（config 讀不了）不寫標記檔")
        self.assertEqual(res["local_only"], "config-unreadable")
        self.assertEqual([(e["local_only_source"], e.get("config_reason")) for e in ev if e["event"] == "privacy"],
                         [("config-unreadable", "bad_json")])
        summ = [e for e in ev if e["event"] == "run_summary"][-1]
        self.assertEqual((summ["local_only"], summ["local_only_source"]), (True, "config-unreadable"))
        self.assertEqual(self.corr_calls, [])

    def test_explicit_correct_exit6(self):
        code, res, out, ev = self.main_raw(b"[]", "--claude")
        self.assertEqual(code, common.LOCAL_ONLY_EXIT)
        self.assertEqual(res["correction"]["reason"], "local_only")
        self.assertEqual(self.corr_calls, [])
        self.assertIn("已拒絕，沒有送出任何資料", self.err)

    def test_bad_value(self):
        code, res, out, ev = self.main(cfg={"privacy": {"local_only": 1}, "correction": {"enabled": True}})
        self.assertEqual(code, 0)
        self.assertEqual(res["local_only"], "config-unreadable")
        self.assertIn("config.json 的值看不懂：privacy.local_only 是 1", self.err)
        self.assertNotIn("這次的設定都用預設值", self.err, "值看不懂時其他設定照讀，不印讀不了的警告")
        self.assertEqual(self.corr_calls, [])

    def test_control_missing_config(self):
        """config.json 不存在：照 2.4.0（找不到的提示、不是本機限定）。"""
        orig = Path.write_text
        with mock.patch.object(Path, "write_text", lambda p, *a, **k: None if Path(p) == self.home / "config.json"
                               else orig(p, *a, **k)):
            code, res, out, ev = self.main("--correct")
        self.assertEqual(code, 0)
        self.assertIn("找不到 config.json", self.err)
        self.assertNotIn("local_only", res)
        self.assertEqual(len(self.corr_calls), 1)


@unittest.skipUnless(V241 and _shells(), "2.4.1 才有；要有 PowerShell")
class InstallerPs(unittest.TestCase):
    """install.ps1 -TestRoot 實跑：home\\config.json 讀不了 → 選單與任何寫入之前就 exit 1，原檔不變。"""

    CASES = [("bad_json", b'{"backend": "ct2", "privacy": {"local_only": true},', "不是合法的 JSON"),
             ("empty", b"", "是空檔"),
             ("array", b"[1]", "最外層不是 JSON 物件"),
             ("not_utf8", "{\"x\": \"會議\"}".encode("cp950"), "不是 UTF-8")]

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v241-ps-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_install(self, sh, root, *args):
        env = {k: v for k, v in os.environ.items() if k.upper() not in ("MEETING_MINUTES_PRO_HOME",)}
        env.update(PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL_PS1), "-TestRoot", str(root),
                               *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                              stdin=subprocess.DEVNULL, env=env)

    def test_stops_and_keeps_file(self):
        for sh in _shells():
            for name, data, why in self.CASES:
                with self.subTest(shell=sh, case=name):
                    root = self.root / f"{sh}-{name}"
                    (root / "home").mkdir(parents=True)
                    cfg = root / "home" / "config.json"
                    cfg.write_bytes(data)
                    r = self.run_install(sh, root, "-Target", "Both", "-NoBreeze", "-NoCorrect", "-NoGpuDiar")
                    out = r.stdout + r.stderr
                    self.assertNotEqual(r.returncode, 0, out)
                    self.assertEqual(cfg.read_bytes(), data, "原檔逐位元不變")
                    self.assertIn("config.json 讀不了", out)
                    self.assertIn(why, out)
                    self.assertIn("config.json", out)
                    self.assertIn("沒有寫入任何東西", out)
                    self.assertEqual(sorted(p.name for p in (root / "home").iterdir()), ["config.json"], "沒有安裝任何東西")
                    self.assertEqual([p for p in (root / "skills").rglob("*")] if (root / "skills").exists() else [], [])
                    self.assertEqual(list((root / "SendTo").iterdir()), [])

    def test_ps_fallback_function(self):
        """沒有 Python 時的退路 Test-ConfigFilePs：逐列與 common.read_config() 的分類一致（只比是否讀得了）。"""
        src = INSTALL_PS1.read_text(encoding="utf-8-sig")
        fn = re.search(r"(?ms)^function Test-ConfigFilePs\(.*?^\}", src).group(0)
        files = {}
        for name, data, _ in UNREADABLE:
            files[name] = data
        files.update(ok=b'{"privacy": {"local_only": false}}', badvalue=b'{"privacy": {"local_only": "true"}}')
        for n, data in files.items():
            (self.root / f"{n}.json").write_bytes(data)
        (self.root / "dir.json").mkdir()
        names = list(files) + ["dir"]
        script = (fn + "\n[Console]::OutputEncoding = [Text.Encoding]::UTF8\n$r = [ordered]@{}\n"
                  + "".join(f"$r[{_ps_quote(n)}] = Test-ConfigFilePs {_ps_quote(self.root / (n + '.json'))}\n" for n in names)
                  + "ConvertTo-Json -InputObject $r -Compress\n")
        ps = self.root / "t.ps1"
        ps.write_text(script, encoding="utf-8-sig")
        for sh in _shells():
            with self.subTest(shell=sh):
                r = subprocess.run([sh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps)], capture_output=True,
                                   text=True, encoding="utf-8", errors="replace", timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = json.loads(r.stdout.strip().splitlines()[-1])
                for n in names:
                    bad = n not in ("ok", "badvalue")
                    self.assertEqual(bool(got[n]), bad, (n, got[n]))
                self.assertIn("BOM", got["bom"])
                self.assertEqual(got["empty"], "是空檔")
                self.assertEqual(got["dir"], "是資料夾，不是檔案")


@unittest.skipUnless(V241 and GIT_BASH.exists(), "2.4.1 才有；要有 Git Bash")
class InstallerSh(unittest.TestCase):
    """install.sh 的 assert_config_readable（macOS 未實測；在 Git Bash 實跑函式本身）。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v241-sh-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_fn(self, data):
        src = INSTALL_SH.read_text(encoding="utf-8")
        fn = re.search(r"(?ms)^assert_config_readable\(\) \{.*?^\}", src).group(0)
        home = self.root / "home"
        if home.exists():
            shutil.rmtree(home)
        home.mkdir()
        if data is not None:
            (home / "config.json").write_bytes(data)
        script = self.root / "t.sh"
        script.write_text("fail() { printf '[錯誤] %s\\n' \"$1\"; exit 1; }\n" + fn + "\nassert_config_readable\necho PASSED\n",
                          encoding="utf-8", newline="\n")
        env = dict(os.environ, MMH=home.as_posix(), PAYLOAD=(VD / "payload").as_posix(), VPY=(home / "venv/bin/python").as_posix(),
                   MEETING_MINUTES_PRO_HOME=home.as_posix(), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        r = subprocess.run([str(GIT_BASH), script.as_posix()], capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=env, timeout=120)
        return r, home / "config.json"

    def test_cases(self):
        for name, data, ok in (("missing", None, True), ("good", b'{"privacy": {"local_only": true}}', True),
                               ("badvalue", b'{"privacy": {"local_only": "true"}}', True),
                               ("bad_json", b'{"a":', False), ("empty", b"", False), ("array", b"[]", False)):
            with self.subTest(name):
                r, cfg = self.run_fn(data)
                out = r.stdout + r.stderr
                if ok:
                    self.assertEqual(r.returncode, 0, out)
                    self.assertIn("PASSED", out)
                else:
                    self.assertEqual(r.returncode, 1, out)
                    self.assertIn("config.json 讀不了", out)
                    self.assertNotIn("PASSED", out)
                    self.assertEqual(cfg.read_bytes(), data)


@unittest.skipUnless(V241, "2.4.1 才有")
class EntryStatic(unittest.TestCase):
    def test_entries_use_common(self):
        sendto = (RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        dropped = (RUNTIME / "mm-dropped.sh").read_text(encoding="utf-8")
        self.assertIn('(Join-Path $Scripts "common.py") local-only', sendto)
        self.assertIn('"$SCR/common.py" local-only --lines', dropped)
        self.assertNotIn("$cfg.privacy.local_only", sendto, "入口不得自己判斷 privacy.local_only")
        self.assertNotIn("cfg_get privacy.local_only", dropped)
        for s in (sendto, dropped):
            self.assertIn("check-failed", s, "判定程式沒有回應時也當成本機限定")
            self.assertIn("要恢復：", s)

    def test_installers(self):
        ps = INSTALL_PS1.read_text(encoding="utf-8-sig")
        sh = INSTALL_SH.read_text(encoding="utf-8")
        i_check, i_menu = ps.index("\nAssert-ConfigReadable"), ps.index("$hasCli = Detect-ClaudeCli")
        self.assertLess(i_check, i_menu, "在選單與任何寫入之前檢查")
        self.assertLess(sh.index("\nassert_config_readable"), sh.index('step "檢查 Python'))
        self.assertIn("check-config", ps)
        self.assertIn("check-config", sh)
        self.assertIn("local-only", ps)
        self.assertIn("local-only --lines", sh)


@unittest.skipUnless(V241, "2.4.1 才有")
class Docs(unittest.TestCase):
    def test_readme(self):
        rd = (VD / "README.md").read_text(encoding="utf-8")
        self.assertIn("**2.4.1 安全修正：config.json 讀不了時也當成本機限定**", rd)
        sec = rd[rd.index("### 17. 本機限定（機敏會議）"):rd.index("## 升級注意（1.x → 2.0）")]
        for t in ("**config.json 讀不了或值看不懂**（2.4.1）", "config-unreadable", "local_only_config_reason",
                  "安裝程式、`setup_backend.py`、`setup_gpu_diar.py` 遇到讀不了的 `config.json` 會停下"):
            self.assertIn(t, sec)

    def test_skill(self):
        s = SKILL.read_text(encoding="utf-8")
        sec = s[s.index("### 0.1 本機限定（機敏會議）（2.4）"):s.index("## 1. 開始前確認")]
        self.assertIn('"$PY" "$MMH/scripts/common.py" local-only --out-dir', sec)
        self.assertIn("這個指令失敗或沒有印出 JSON 時，也照本機限定處理", sec)
        self.assertNotIn("json.load(open(sys.argv[1]", sec, "不得再自己讀 config.json 判斷（讀不了時會當成關）")


if __name__ == "__main__":
    unittest.main()
