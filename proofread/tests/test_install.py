"""安裝與移除的沙盒測試：install.ps1／uninstall.ps1（PowerShell 7 與 Windows PowerShell 5.1）、install.sh／uninstall.sh（Git Bash）。

  python -B test_install.py          （或經由 run_tests.py）

全部在系統暫存區的沙盒裡跑（安裝程式的測試模式 -TestRoot／--test-root）：Pro 的資料夾是沙盒裡的假 $MMH（Pro 2.2.0 的 scripts 複製一份、
用 `python -m venv --without-pip` 建的空 venv），右鍵捷徑寫到沙盒的 SendTo、登錄寫到 HKCU\\Software\\Classes\\MMProofTest\\<沙盒名>（測試結束刪除），
不碰使用者真正的安裝。另跑 repo 內 meeting-minutes-pro 2.3.0 的解除安裝（測試模式），確認它以 -Quiet／--quiet 呼叫本工具的移除程式時不詢問。
"""
import ctypes
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

sys.dont_write_bytecode = True
TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
VDIR = ROOT / "meeting-minutes-proofread-v1.0.0"
APP = VDIR / "payload" / "app"
SKILLS = ROOT.parent
PRO_SKILL = SKILLS / "meeting-minutes-pro-skill"
PRO22_SCRIPTS = PRO_SKILL / "meeting-minutes-pro-v2.2.0" / "payload" / "runtime" / "scripts"
PRO23 = PRO_SKILL / "meeting-minutes-pro-v2.3.0"
IS_WIN = sys.platform == "win32"
TOOL = "會議記錄校稿"
QUIET_KEPT = "保留最近的稿清單（安靜模式，不詢問）"
WORK = Path(tempfile.mkdtemp(prefix="mmproof-inst-"))


def git_bash():
    env = os.environ.get("MMPROOF_GIT_BASH")
    if env:
        return Path(env) if Path(env).exists() else None
    if not IS_WIN:
        return Path(shutil.which("bash")) if shutil.which("bash") else None
    try:
        exec_path = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    # Git for Windows：<Git>/mingw64/libexec/git-core → <Git>/bin/bash.exe（不用 System32 的 WSL bash）
    cand = Path(exec_path).parents[2] / "bin" / "bash.exe" if exec_path else None
    return cand if cand and cand.exists() else None


GIT_BASH = git_bash()
PS_SHELLS = [s for s in ("pwsh", "powershell") if IS_WIN and shutil.which(s)]


# ------------------------------------------------------------------ 沙盒
_BASE_VENV = {}


def base_venv() -> Path:
    if "p" not in _BASE_VENV:
        v = WORK / "_venv"
        subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(v)], check=True, capture_output=True, timeout=300)
        _BASE_VENV["p"] = v
    return _BASE_VENV["p"]


def mixed(p: Path) -> str:
    return str(p).replace("\\", "/")


def make_sandbox(name: str, pro: str = "2.2.0", break_mark: bool = False, venv: str = "win") -> Path:
    """沙盒：<root>/home（假 Pro）、<root>/會議_minutes（輸出資料夾，含校稿進度與定稿檔）。pro=None：沒有 Pro。"""
    root = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=WORK))
    out = root / "會議_minutes"
    (out / ".proofread").mkdir(parents=True)
    (out / "transcript.md").write_text("# 逐字稿\n", encoding="utf-8")
    (out / ".proofread" / "session.json").write_text('{"format": "mm-proofread-session/1"}', encoding="utf-8")
    (out / "transcript.final.md").write_text("# 定稿\n", encoding="utf-8")
    if pro is None:
        return root
    home = root / "home"
    shutil.copytree(PRO22_SCRIPTS, home / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (home / "config.json").write_text(json.dumps({"runtime_version": pro}), encoding="utf-8")
    common = home / "scripts" / "common.py"
    if pro != "2.2.0":
        s = common.read_text(encoding="utf-8")
        common.write_text(re.sub(r'^VERSION\s*=\s*"[^"]+"', f'VERSION = "{pro}"', s, count=1, flags=re.M), encoding="utf-8")
    if break_mark:
        with (home / "scripts" / "consistency.py").open("a", encoding="utf-8") as f:
            f.write('\nimport re as _re_test\nMARK_RE = _re_test.compile(r"\\{changed\\}")\n')
    (home / "corrections.tsv").write_text("錯誤\t正確\t備註\n", encoding="utf-8")
    (home / "glossary.txt").write_text("星河物流\n", encoding="utf-8")
    (home / "backups").mkdir()
    (home / "backups" / "corrections.20260101-000000.tsv").write_text("x\n", encoding="utf-8")
    if venv == "win":
        shutil.copytree(base_venv(), home / "venv")
    elif venv == "posix":
        (home / "venv" / "bin").mkdir(parents=True)
        w = home / "venv" / "bin" / "python"
        w.write_text(f'#!/bin/sh\nexec "{mixed(Path(sys.executable))}" "$@"\n', encoding="utf-8", newline="\n")
        w.chmod(0o755)
    return root


def keep_files(root: Path) -> list:
    """移除後必須還在的檔。"""
    home = root / "home"
    return [home / "corrections.tsv", home / "glossary.txt", home / "backups" / "corrections.20260101-000000.tsv",
            root / "會議_minutes" / ".proofread" / "session.json", root / "會議_minutes" / "transcript.final.md"]


def tree_bytes(d: Path) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def payload_tree() -> dict:
    return {k: v for k, v in tree_bytes(APP).items() if "__pycache__" not in k}


def base_env(extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("MEETING_MINUTES_PRO_HOME", "MMPROOF_PRO_SCRIPTS", "MMPROOF_PRO_PYTHON")}
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    env.update(extra or {})
    return env


def run_ps(shell: str, script: Path, *args, stdin: str = "", noninteractive: bool = False):
    cmd = [shell, "-NoProfile"] + (["-NonInteractive"] if noninteractive else []) + \
          ["-ExecutionPolicy", "Bypass", "-File", str(script), *map(str, args)]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=base_env(), timeout=240)


def run_bash(script_or_code, *args, stdin: str = "", code: bool = False, extra: dict | None = None):
    env = base_env({"MMPROOF_PRO_PYTHON": sys.executable, **(extra or {})})
    cmd = [str(GIT_BASH), "-c", script_or_code] if code else [str(GIT_BASH), mixed(Path(script_or_code)), *map(str, args)]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, timeout=240)


def out_of(r) -> str:
    return (r.stdout or "") + (r.stderr or "")


# ------------------------------------------------------------------ Windows：登錄、捷徑、行程
def reg_base(root: Path) -> str:
    return "Software\\Classes\\MMProofTest\\" + re.sub(r"[^A-Za-z0-9_.-]", "_", root.name)


def reg_get(sub: str):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as k:
            return winreg.QueryValueEx(k, "")[0]
    except OSError:
        return None


def reg_exists(sub: str) -> bool:
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub).Close()
        return True
    except OSError:
        return False


def reg_delete_tree(sub: str):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                reg_delete_tree(sub + "\\" + child)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
    except OSError:
        pass


def cleanup_registry(root: Path):
    if not IS_WIN:
        return
    reg_delete_tree(reg_base(root))
    parent = "Software\\Classes\\MMProofTest"
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, parent) as k:
            winreg.EnumKey(k, 0)
    except OSError:
        reg_delete_tree(parent)


def read_lnk(path: Path) -> dict:
    code = ("$l = (New-Object -ComObject WScript.Shell).CreateShortcut($env:MMPROOF_LNK); "
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "[ordered]@{ target = $l.TargetPath; args = $l.Arguments; wd = $l.WorkingDirectory; icon = $l.IconLocation } | ConvertTo-Json -Compress")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", code], capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, MMPROOF_LNK=str(path)), timeout=60)
    return json.loads(r.stdout.strip().splitlines()[-1])


def pid_alive(pid: int) -> bool:
    if not IS_WIN:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(h)
    return code.value == 259                                     # STILL_ACTIVE


def start_service(root: Path, py: Path) -> int:
    """用安裝好的啟動器在背景帶起服務（只開首頁、不開瀏覽器），回傳服務的 pid。"""
    home = root / "home"
    env = base_env({"MEETING_MINUTES_PRO_HOME": str(home)})
    if py == Path(sys.executable):
        env["MMPROOF_PRO_PYTHON"] = sys.executable
    r = subprocess.run([str(py), "-B", str(home / "proofread" / "app" / "mmproof_launcher.py"), "--home", str(home),
                        "--no-browser", "--home-page"], capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    inst = json.loads((home / "proofread" / "state" / "instance.json").read_text(encoding="utf-8"))
    assert r.returncode == 0, out_of(r)
    return inst["pid"]


def kill(pid: int):
    if pid and pid_alive(pid):
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, 9)


# ------------------------------------------------------------------ PowerShell
class _PsBase:
    shell = ""

    def setUp(self):
        self.roots, self.pids = [], []

    def tearDown(self):
        for pid in self.pids:
            kill(pid)
        for r in self.roots:
            cleanup_registry(r)

    def sandbox(self, **kw) -> Path:
        r = make_sandbox(f"ps-{self.shell}", **kw)
        self.roots.append(r)
        return r

    def install(self, root: Path):
        return run_ps(self.shell, VDIR / "install.ps1", "-TestRoot", root)

    def assert_nothing_written(self, root: Path):
        self.assertFalse((root / "home" / "proofread").exists(), "不得寫入 proofread/")
        self.assertFalse((root / "SendTo" / f"{TOOL}.lnk").exists(), "不得建立右鍵捷徑")
        self.assertFalse(reg_exists(reg_base(root)), "不得寫登錄")

    def test_no_pro(self):
        root = self.sandbox(pro=None)
        r = self.install(root)
        self.assertEqual(r.returncode, 2, out_of(r))
        self.assertIn("請先安裝 meeting-minutes-pro 2.2.0 以上", r.stdout)
        self.assertIn("meeting-minutes Portal 的「安裝」頁", r.stdout)
        self.assertNotIn("http", r.stdout)
        self.assert_nothing_written(root)

    def test_pro_too_old(self):
        root = self.sandbox(pro="2.1.0")
        r = self.install(root)
        self.assertEqual(r.returncode, 2, out_of(r))
        self.assertIn("meeting-minutes-pro 版本 2.1.0 太舊，請先升級到 2.2.0 以上", r.stdout)
        self.assert_nothing_written(root)

    def test_pro_incompatible(self):
        root = self.sandbox(break_mark=True)
        r = self.install(root)
        self.assertEqual(r.returncode, 2, out_of(r))
        self.assertIn("這版會議記錄校稿與目前的 meeting-minutes-pro 2.2.0 不相容", r.stdout)
        self.assertNotIn("http", r.stdout)
        self.assert_nothing_written(root)

    def test_fresh_install(self):
        root = self.sandbox()
        home = root / "home"
        r = self.install(root)
        self.assertEqual(r.returncode, 0, out_of(r))
        dst = home / "proofread"
        self.assertEqual(tree_bytes(dst / "app"), payload_tree(), "app/ 要與安裝包的 payload/app 逐位元相同")
        vj = json.loads((dst / "version.json").read_text(encoding="utf-8"))   # 不能有 BOM
        self.assertEqual((vj["version"], vj["pro_version_at_install"]), ("1.0.0", "2.2.0"))
        self.assertRegex(vj["installed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        for u in ("uninstall.ps1", "uninstall.sh"):
            self.assertEqual((dst / u).read_bytes(), (VDIR / u).read_bytes())
        self.assertTrue((dst / "state").is_dir())
        lnk = read_lnk(root / "SendTo" / f"{TOOL}.lnk")
        self.assertEqual(Path(lnk["target"]), home / "venv" / "Scripts" / "pythonw.exe")
        self.assertEqual(lnk["args"], f'-B "{home / "proofread" / "app" / "mmproof_launcher.py"}"')
        self.assertEqual(Path(lnk["wd"]), home)
        self.assertTrue(lnk["icon"].lower().endswith("imageres.dll,290"), lnk["icon"])
        base = reg_base(root)
        self.assertEqual(reg_get(base + "\\.mmproof"), "MeetingMinutes.Proofread")
        self.assertEqual(reg_get(base + "\\MeetingMinutes.Proofread"), TOOL)
        self.assertEqual(reg_get(base + "\\MeetingMinutes.Proofread\\shell\\open\\command"),
                         f'"{home / "venv" / "Scripts" / "pythonw.exe"}" -B "{home / "proofread" / "app" / "mmproof_launcher.py"}" "%1"')
        self.assertTrue(reg_get(base + "\\MeetingMinutes.Proofread\\DefaultIcon").lower().endswith("imageres.dll,290"))
        self.assertFalse(list(home.rglob("__pycache__")), "不得在 Pro 的資料夾留下 __pycache__")
        self.assertIn("已安裝", r.stdout)
        self.assertIn("「用定稿重做會議記錄」需要 meeting-minutes-pro 2.3.0 以上", r.stdout)
        self.assertNotIn("http", r.stdout)

    def test_upgrade_keeps_state(self):
        root = self.sandbox()
        dst = root / "home" / "proofread"
        self.assertEqual(self.install(root).returncode, 0)
        (dst / "state" / "recent.json").write_text('[{"id": "abc123abc123"}]', encoding="utf-8")
        (dst / "config.json").write_text('{"idle_seconds": 60}', encoding="utf-8")
        (dst / "app" / "old_leftover.py").write_text("# 舊版殘留\n", encoding="utf-8")
        r = self.install(root)
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn("已升級", r.stdout)
        self.assertEqual((dst / "state" / "recent.json").read_text(encoding="utf-8"), '[{"id": "abc123abc123"}]')
        self.assertEqual((dst / "config.json").read_text(encoding="utf-8"), '{"idle_seconds": 60}')
        self.assertFalse((dst / "app" / "old_leftover.py").exists(), "升級要整個換掉 app/")
        self.assertEqual(tree_bytes(dst / "app"), payload_tree())

    def test_upgrade_stops_running_service(self):
        root = self.sandbox()
        home = root / "home"
        self.assertEqual(self.install(root).returncode, 0)
        pid = start_service(root, home / "venv" / "Scripts" / "python.exe")
        self.pids.append(pid)
        self.assertTrue(pid_alive(pid))
        r = self.install(root)
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn("已停止", r.stdout)
        t0 = time.time()
        while pid_alive(pid) and time.time() - t0 < 10:
            time.sleep(0.2)
        self.assertFalse(pid_alive(pid), "舊服務要結束")
        self.assertFalse((home / "proofread" / "state" / "instance.json").exists())

    def uninstall(self, root: Path, *args, stdin: str = "", noninteractive: bool = False):
        return run_ps(self.shell, root / "home" / "proofread" / "uninstall.ps1", *args, "-TestRoot", root,
                      stdin=stdin, noninteractive=noninteractive)

    def assert_removed(self, root: Path, state_kept: bool):
        dst = root / "home" / "proofread"
        for name in ("app", "version.json", "config.json", "uninstall.ps1", "uninstall.sh"):
            self.assertFalse((dst / name).exists(), f"{name} 要刪除")
        self.assertFalse((root / "SendTo" / f"{TOOL}.lnk").exists())
        self.assertFalse(reg_exists(reg_base(root)), "登錄要刪除")
        self.assertEqual((dst / "state" / "recent.json").exists(), state_kept)
        for p in keep_files(root):
            self.assertTrue(p.exists(), f"不得刪除 {p.name}")

    def test_uninstall_quiet(self):
        root = self.sandbox()
        self.assertEqual(self.install(root).returncode, 0)
        dst = root / "home" / "proofread"
        (dst / "state" / "recent.json").write_text("[]", encoding="utf-8")
        (dst / "config.json").write_text("{}", encoding="utf-8")
        r = self.uninstall(root, "-Quiet", noninteractive=True)       # -NonInteractive：只要詢問就會出錯
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn(QUIET_KEPT, r.stdout)
        self.assertIn(f"已移除 {TOOL}", r.stdout)
        self.assert_removed(root, state_kept=True)

    def test_uninstall_ask_yes_and_no(self):
        for ans, kept in (("n", True), ("y", False)):
            with self.subTest(answer=ans):
                root = self.sandbox()
                self.assertEqual(self.install(root).returncode, 0)
                (root / "home" / "proofread" / "state" / "recent.json").write_text("[]", encoding="utf-8")
                r = self.uninstall(root, stdin=ans + "\n")            # 輸入轉向時不顯示提示文字，以結果判斷
                self.assertEqual(r.returncode, 0, out_of(r))
                self.assertNotIn(QUIET_KEPT, r.stdout)
                self.assert_removed(root, state_kept=kept)
                self.assertEqual((root / "home" / "proofread").exists(), kept, "全部刪光時 proofread/ 一起刪")

    def test_uninstall_stops_running_service(self):
        root = self.sandbox()
        home = root / "home"
        self.assertEqual(self.install(root).returncode, 0)
        (home / "proofread" / "state" / "recent.json").write_text("[]", encoding="utf-8")
        pid = start_service(root, home / "venv" / "Scripts" / "python.exe")
        self.pids.append(pid)
        r = self.uninstall(root, "-Quiet", noninteractive=True)
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn("已停止服務", r.stdout)
        t0 = time.time()
        while pid_alive(pid) and time.time() - t0 < 10:
            time.sleep(0.2)
        self.assertFalse(pid_alive(pid))
        self.assert_removed(root, state_kept=True)

    def test_uninstall_not_installed(self):
        root = self.sandbox()
        r = run_ps(self.shell, VDIR / "uninstall.ps1", "-Quiet", "-TestRoot", root, noninteractive=True)
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn(f"沒有安裝 {TOOL}", r.stdout)

    @unittest.skipUnless((PRO23 / "install.ps1").is_file(), "repo 內沒有 meeting-minutes-pro 2.3.0")
    def test_pro230_uninstall_calls_quiet(self):
        """Pro 2.3.0 的解除安裝（測試模式）以 -Quiet 呼叫本工具的移除程式：不詢問、保留最近的稿清單。"""
        root = self.sandbox()
        self.assertEqual(self.install(root).returncode, 0)
        (root / "home" / "proofread" / "state" / "recent.json").write_text("[]", encoding="utf-8")
        (root / "skills" / "meeting-minutes-pro").mkdir(parents=True)
        r = run_ps(self.shell, PRO23 / "install.ps1", "-Uninstall", "-TestRoot", root, stdin="n\n")   # n：Pro 問的「刪除 runtime」
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn("已移除會議記錄校稿", r.stdout)
        self.assertIn(QUIET_KEPT, r.stdout)
        self.assert_removed(root, state_kept=True)
        self.assertFalse((root / "skills" / "meeting-minutes-pro").exists(), "Pro 自己的解除安裝照常")


@unittest.skipUnless("pwsh" in PS_SHELLS, "沒有 PowerShell 7（pwsh）")
class InstallPwsh(_PsBase, unittest.TestCase):
    shell = "pwsh"


@unittest.skipUnless("powershell" in PS_SHELLS, "沒有 Windows PowerShell 5.1")
class InstallWinPs51(_PsBase, unittest.TestCase):
    shell = "powershell"


# ------------------------------------------------------------------ Git Bash（install.sh／uninstall.sh）
def pro_sh_functions() -> str:
    """Pro 2.3.0 install.sh 的 step／ok／warn／fail 與 uninstall_proofread、do_uninstall（install.sh 在 macOS 以外一開始就停止，所以只取函式）。"""
    s = (PRO23 / "install.sh").read_text(encoding="utf-8")
    helpers = re.search(r"^c_cyan=.*?^fail\(\) \{.*?\n", s, re.S | re.M).group(0)
    funcs = re.search(r"^uninstall_proofread\(\) \{.*?\n\}\n\ndo_uninstall\(\) \{.*?\n\}\n", s, re.S | re.M).group(0)
    return helpers + funcs


@unittest.skipUnless(GIT_BASH, "沒有 Git Bash")
class InstallGitBash(unittest.TestCase):
    """install.sh 的測試模式在沒有 osacompile 的環境只寫出 .app 的 AppleScript（供檢查）；PlistBuddy／lsregister 略過。"""

    def setUp(self):
        self.roots, self.pids = [], []

    def tearDown(self):
        for pid in self.pids:
            kill(pid)

    def sandbox(self, **kw) -> Path:
        kw.setdefault("venv", "posix")
        r = make_sandbox("sh", **kw)
        self.roots.append(r)
        return r

    def install(self, root: Path):
        return run_bash(VDIR / "install.sh", "--test-root", mixed(root))

    def test_no_pro(self):
        root = self.sandbox(pro=None)
        r = self.install(root)
        self.assertEqual(r.returncode, 2, out_of(r))
        self.assertIn("請先安裝 meeting-minutes-pro 2.2.0 以上", r.stdout)
        self.assertFalse((root / "home" / "proofread").exists())
        self.assertFalse((root / "Applications").exists())

    def test_pro_too_old(self):
        root = self.sandbox(pro="2.1.0")
        r = self.install(root)
        self.assertEqual(r.returncode, 2, out_of(r))
        self.assertIn("meeting-minutes-pro 版本 2.1.0 太舊，請先升級到 2.2.0 以上", r.stdout)
        self.assertFalse((root / "home" / "proofread").exists())

    def test_pro_incompatible(self):
        root = self.sandbox(break_mark=True)
        r = self.install(root)
        self.assertEqual(r.returncode, 2, out_of(r))
        self.assertIn("不相容", r.stdout)
        self.assertFalse((root / "home" / "proofread").exists())

    def test_fresh_install(self):
        root = self.sandbox()
        home = root / "home"
        r = self.install(root)
        self.assertEqual(r.returncode, 0, out_of(r))
        dst = home / "proofread"
        self.assertEqual(tree_bytes(dst / "app"), payload_tree())
        vj = json.loads((dst / "version.json").read_text(encoding="utf-8"))
        self.assertEqual((vj["version"], vj["pro_version_at_install"]), ("1.0.0", "2.2.0"))
        self.assertRegex(vj["installed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")
        self.assertEqual((dst / "uninstall.sh").read_bytes(), (VDIR / "uninstall.sh").read_bytes())
        script = (root / "Applications" / f"{TOOL}.app" / "Contents" / "mmproof-applescript.txt").read_text(encoding="utf-8")
        self.assertIn("on open theItems", script)
        self.assertIn("quoted form of POSIX path of f", script)
        self.assertIn(f'quoted form of "{mixed(home)}/venv/bin/python" & " -B "', script)
        self.assertIn(f'quoted form of "{mixed(home)}/proofread/app/mmproof_launcher.py"', script)
        self.assertIn('" > /dev/null 2>&1 &"', script, "背景執行、輸出丟棄")
        self.assertNotIn("Terminal", script, "不開終端機")
        self.assertIn("display dialog", script)
        self.assertFalse(list(home.rglob("__pycache__")))
        self.assertNotIn("http", r.stdout)

    def test_upgrade_keeps_state_and_stops_service(self):
        root = self.sandbox()
        dst = root / "home" / "proofread"
        self.assertEqual(self.install(root).returncode, 0)
        (dst / "state" / "recent.json").write_text('[{"id": "abc123abc123"}]', encoding="utf-8")
        (dst / "config.json").write_text('{"idle_seconds": 60}', encoding="utf-8")
        (dst / "app" / "old_leftover.py").write_text("# 舊版殘留\n", encoding="utf-8")
        pid = start_service(root, Path(sys.executable))
        self.pids.append(pid)
        r = self.install(root)
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn("已停止", r.stdout)
        self.assertIn("已升級", r.stdout)
        t0 = time.time()
        while pid_alive(pid) and time.time() - t0 < 10:
            time.sleep(0.2)
        self.assertFalse(pid_alive(pid))
        self.assertEqual((dst / "state" / "recent.json").read_text(encoding="utf-8"), '[{"id": "abc123abc123"}]')
        self.assertEqual((dst / "config.json").read_text(encoding="utf-8"), '{"idle_seconds": 60}')
        self.assertFalse((dst / "app" / "old_leftover.py").exists())

    def assert_removed(self, root: Path, state_kept: bool):
        dst = root / "home" / "proofread"
        for name in ("app", "version.json", "config.json", "uninstall.ps1", "uninstall.sh"):
            self.assertFalse((dst / name).exists(), f"{name} 要刪除")
        self.assertFalse((root / "Applications" / f"{TOOL}.app").exists())
        self.assertEqual((dst / "state" / "recent.json").exists(), state_kept)
        for p in keep_files(root):
            self.assertTrue(p.exists(), f"不得刪除 {p.name}")

    def test_uninstall_quiet(self):
        root = self.sandbox()
        self.assertEqual(self.install(root).returncode, 0)
        dst = root / "home" / "proofread"
        (dst / "state" / "recent.json").write_text("[]", encoding="utf-8")
        (dst / "config.json").write_text("{}", encoding="utf-8")
        r = run_bash(dst / "uninstall.sh", "--quiet", "--test-root", mixed(root), stdin="y\n")   # 有讀輸入就會刪掉 state/
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn(QUIET_KEPT, r.stdout)
        self.assert_removed(root, state_kept=True)

    def test_uninstall_ask_yes(self):
        root = self.sandbox()
        self.assertEqual(self.install(root).returncode, 0)
        (root / "home" / "proofread" / "state" / "recent.json").write_text("[]", encoding="utf-8")
        r = run_bash(root / "home" / "proofread" / "uninstall.sh", "--test-root", mixed(root), stdin="y\n")
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertNotIn(QUIET_KEPT, r.stdout)
        self.assert_removed(root, state_kept=False)
        self.assertFalse((root / "home" / "proofread").exists())

    @unittest.skipUnless((PRO23 / "install.sh").is_file(), "repo 內沒有 meeting-minutes-pro 2.3.0")
    def test_pro230_uninstall_calls_quiet(self):
        root = self.sandbox()
        self.assertEqual(self.install(root).returncode, 0)
        (root / "home" / "proofread" / "state" / "recent.json").write_text("[]", encoding="utf-8")
        (root / "skills" / "meeting-minutes-pro").mkdir(parents=True)
        m = mixed(root)
        code = (pro_sh_functions() + f'\nTEST_ROOT="{m}"; MMH="{m}/home"; SKILL_DST="{m}/skills/meeting-minutes-pro"\n'
                f'APP_DST="{m}/Applications/x.app"; LEGACY_APP="{m}/Applications/y.app"; UPLOAD_ZIP="{m}/Desktop/z.zip"\n'
                f'DESKTOP_DIR="{m}/Desktop"\ndo_uninstall\n')
        r = run_bash(code, code=True, stdin="n\n")
        self.assertEqual(r.returncode, 0, out_of(r))
        self.assertIn("已移除會議記錄校稿", r.stdout)
        self.assertIn(QUIET_KEPT, r.stdout)
        self.assert_removed(root, state_kept=True)


class NoBytecode(unittest.TestCase):
    def test_zz_no_pycache_left(self):
        """repo 內的 Pro 2.2.0 scripts 與本工具版本目錄都沒有 __pycache__（全部測試跑完後檢查）。"""
        self.assertFalse(list(PRO22_SCRIPTS.rglob("__pycache__")))
        self.assertFalse(list(VDIR.rglob("__pycache__")))


def main() -> tuple:
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for cls in (InstallPwsh, InstallWinPs51, InstallGitBash, NoBytecode):
        suite.addTests(loader.loadTestsFromTestCase(cls))
    r = unittest.TextTestRunner(verbosity=2).run(suite)
    total = r.testsRun - len(r.skipped)
    bad = len(r.failures) + len(r.errors)
    shutil.rmtree(WORK, ignore_errors=True)
    return total, total - bad, [str(t) for t, _ in r.failures + r.errors], [f"{t}：{why}" for t, why in r.skipped]


if __name__ == "__main__":
    t, ok, bad, skipped = main()
    print(f"install {ok}/{t} PASS" + (f"；略過 {len(skipped)}" if skipped else ""))
    sys.exit(0 if ok == t and not skipped else 1)
