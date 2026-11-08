"""〔1.2.2〕1.2.2 的四項修正：

1. 入口詢問前清空鍵盤緩衝（mm-sendto.ps1 的 Clear-KeyBuffer、mm-dropped.sh 的 flush_input）：
   - 每一個 Read-Host／read -p 前面都有清緩衝（靜態檢查）；
   - PowerShell 7／5.1：開一個隱藏的新主控台，用 WriteConsoleInput 把「處理中誤按的 Enter」放進主控台輸入緩衝，
     清完後緩衝是空的、接下來的 Read-Host 讀到的是之後才輸入的答案（對照組不清：Read-Host 讀到空字串）；
     stdin 被導向時直接略過、不吃掉 stdin 的資料；
   - bash：stdin 不是終端機時略過、不吃掉管線資料（Git Bash）；有 WSL 時在真的 pty 裡實測（對照組同上），並確認終端機設定還原。
2. 會議摘要〈待釐清問題〉規則：單段／分段（_RULES_COMMON 規則 6）與彙整（SYSTEM_MERGE 第 9 條）；
   prompt 的例句不得取自測試素材（避免實測被題目帶著走）。
3. 使用者看得到的字串不再用「塊」當分段單位（「區塊」不算）。
4. 安裝 log：MMP_INSTALLING=1 時版號提示改印「升級中」；「更新設定」依實際補上的鍵印「已補上新版設定鍵：…」或「設定鍵無變更」
   （直接執行 install.ps1／install.sh 內嵌的 Python 片段，暫存 home）。

不呼叫任何模型；不碰已安裝的 runtime。1.2.1 以前（MMP_TEST_VERSION）整個略過。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
import unittest
from pathlib import Path

import _testenv

V122 = _testenv.VER >= (1, 2, 2)
VD = _testenv.VERSION_DIR
RUNTIME = _testenv.RUNTIME
SENDTO = RUNTIME / "mm-sendto.ps1"
DROPPED = RUNTIME / "mm-dropped.sh"
INSTALL_PS1 = VD / "install.ps1"
INSTALL_SH = VD / "install.sh"
MATERIALS = Path(__file__).resolve().parent / "materials"
GIT_BASH = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))
SYSROOT = Path(os.environ.get("SystemRoot", r"C:\Windows"))
PS51 = SYSROOT / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"

# 1.2.1 的 auto_minutes.py（SYSTEM_MERGE 原文比對用；公開 repo 沒有舊版目錄時略過那一項）
V121_AUTO_MINUTES = _testenv.HERE.parent / "meeting-minutes-pro-v1.2.1" / "payload" / "runtime" / "scripts" / "auto_minutes.py"
# 1.2.1 的 config.json（setup_backend 寫過、upgrade_config 補齊之後的樣子）
CFG_121 = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "whisper": "turbo",
           "runtime_version": "1.2.1",
           "punctuation": {"enabled": True}, "opencc_keep": {"enabled": True},
           "correction": {"enabled": False, "provider": "auto", "channel": "cli"},
           "minutes": {"provider": "auto", "channel": "cli"}}
CFG_110 = {"backend": "openvino", "device": "NPU", "whisper": "turbo", "runtime_version": "1.1.0",
           "punctuation": {"enabled": True}, "opencc_keep": {"enabled": True},
           "correction": {"enabled": False, "provider": "auto", "channel": "cli"}}


def _func(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.M | re.S)
    if not m:
        raise AssertionError(f"找不到函式：{pattern}")
    return m.group(0)


def ps_function() -> str:
    return _func(SENDTO.read_text(encoding="utf-8-sig"), r"^function Clear-KeyBuffer \{.*?^\}")


def sh_function() -> str:
    return _func(DROPPED.read_text(encoding="utf-8"), r"^flush_input\(\) \{.*?^\}")


# ---------------------------------------------------------------- 1. 鍵盤緩衝

@unittest.skipUnless(V122, "1.2.2 才有")
class KeyBufferStatic(unittest.TestCase):
    """每個 Read-Host／read -p 之前（同一行前段或上一個非空行）都有清緩衝。"""

    def check(self, path: Path, enc: str, ask: str, flush: str):
        lines = path.read_text(encoding=enc).splitlines()
        n = 0
        for i, line in enumerate(lines):
            code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
            if ask not in code:
                continue
            n += 1
            before = code[:code.index(ask)]
            prev = next((lines[j] for j in range(i - 1, -1, -1) if lines[j].strip()), "")
            self.assertTrue(flush in before or flush in prev, f"{path.name}:{i + 1} 的 {ask} 前沒有 {flush}：{line.strip()}")
        return n

    def test_sendto(self):
        self.assertEqual(self.check(SENDTO, "utf-8-sig", "Read-Host", "Clear-KeyBuffer"), 4)   # 兩個錯誤出口、Ask、結尾

    def test_dropped(self):
        self.assertEqual(self.check(DROPPED, "utf-8", "read -r -p", "flush_input"), 4)

    def test_safe_guards(self):
        f = ps_function()
        self.assertIn("[Console]::IsInputRedirected", f)
        self.assertEqual(f.count("try {"), 3)        # 每一步都包 try，不得讓入口出錯
        f = sh_function()
        self.assertIn("[ -t 0 ] || return 0", f)
        self.assertIn('stty "$old"', f)              # 還原終端機設定
        self.assertNotRegex(f, r"read\s[^\n]*-t\s*0?\.\d")   # bash 3.2 沒有小數秒的 read -t


PS_CONSOLE_TEST = r'''
param([string]$Src, [string]$Out, [string]$Mode)
$r = [ordered]@{ mode = $Mode }
try {
    $code = Get-Content -LiteralPath $Src -Raw -Encoding UTF8
    $m = [regex]::Match($code, '(?ms)^function Clear-KeyBuffer \{.*?^\}')
    Invoke-Expression $m.Value
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class MmpKeys {
    [StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
    public struct KEY_EVENT_RECORD {
        [FieldOffset(0)] public int bKeyDown; [FieldOffset(4)] public ushort wRepeatCount;
        [FieldOffset(6)] public ushort wVirtualKeyCode; [FieldOffset(8)] public ushort wVirtualScanCode;
        [FieldOffset(10)] public char UnicodeChar; [FieldOffset(12)] public uint dwControlKeyState;
    }
    [StructLayout(LayoutKind.Explicit)]
    public struct INPUT_RECORD { [FieldOffset(0)] public ushort EventType; [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent; }
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GetStdHandle(int n);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool WriteConsoleInputW(IntPtr h, INPUT_RECORD[] r, uint n, out uint w);
    public static uint Press(char c, ushort vk) {
        var r = new INPUT_RECORD[2];
        for (int i = 0; i < 2; i++) {
            r[i].EventType = 1; r[i].KeyEvent.bKeyDown = (i == 0) ? 1 : 0; r[i].KeyEvent.wRepeatCount = 1;
            r[i].KeyEvent.wVirtualKeyCode = vk; r[i].KeyEvent.UnicodeChar = c;
        }
        uint w; WriteConsoleInputW(GetStdHandle(-10), r, 2, out w); return w;
    }
}
"@
    $r.redirected = [Console]::IsInputRedirected
    $r.written = [MmpKeys]::Press([char]13, 13)        # 處理中誤按的 Enter
    $r.before = [Console]::KeyAvailable
    if ($Mode -eq "flush") { Clear-KeyBuffer }
    $r.after = [Console]::KeyAvailable
    [void][MmpKeys]::Press([char]'y', 0x59)              # 題目出現後才輸入的答案
    [void][MmpKeys]::Press([char]13, 13)
    $r.answer = Read-Host "q"
} catch { $r.error = "$_" }
$r | ConvertTo-Json | Set-Content -LiteralPath $Out -Encoding UTF8
'''

PS_REDIRECTED_TEST = r'''
param([string]$Src)
$code = Get-Content -LiteralPath $Src -Raw -Encoding UTF8
$m = [regex]::Match($code, '(?ms)^function Clear-KeyBuffer \{.*?^\}')
Invoke-Expression $m.Value
Clear-KeyBuffer
Write-Output ("redirected=" + [Console]::IsInputRedirected)
Write-Output ("got=[" + [Console]::In.ReadLine() + "]")
'''


@unittest.skipUnless(V122 and os.name == "nt", "1.2.2、Windows 才有")
class KeyBufferPowerShell(unittest.TestCase):
    """真的主控台：隱藏的新主控台視窗（CREATE_NEW_CONSOLE＋SW_HIDE），不導向 stdin。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="mmp-kb-"))
        (cls.tmp / "console.ps1").write_text(PS_CONSOLE_TEST, encoding="utf-8-sig")
        (cls.tmp / "redirected.ps1").write_text(PS_REDIRECTED_TEST, encoding="utf-8-sig")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def shells(self):
        out = []
        if shutil.which("pwsh"):
            out.append(("pwsh", shutil.which("pwsh")))
        if PS51.exists():
            out.append(("powershell", str(PS51)))
        if not out:
            self.skipTest("找不到 PowerShell")
        return out

    def run_console(self, exe: str, mode: str) -> dict:
        res = self.tmp / f"{Path(exe).stem}-{mode}.json"
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0   # SW_HIDE
        p = subprocess.Popen([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.tmp / "console.ps1"),
                              str(SENDTO), str(res), mode], creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)
        p.wait(timeout=120)
        return json.loads(res.read_text(encoding="utf-8-sig"))

    def test_flush_in_real_console(self):
        for name, exe in self.shells():
            with self.subTest(shell=name):
                r = self.run_console(exe, "flush")
                self.assertNotIn("error", r)
                self.assertFalse(r["redirected"])
                self.assertEqual(r["written"], 2)
                self.assertTrue(r["before"])                 # 誤按的 Enter 在緩衝區
                self.assertFalse(r["after"])                 # 清掉了
                self.assertEqual(r["answer"], "y")           # 讀到的是之後輸入的答案

    def test_control_without_flush(self):
        """對照組：不清 → Read-Host 直接吃到處理中誤按的 Enter（1.2.1 的「視窗直接關閉」）。"""
        for name, exe in self.shells():
            with self.subTest(shell=name):
                r = self.run_console(exe, "none")
                self.assertNotIn("error", r)
                self.assertTrue(r["after"])
                self.assertEqual(r["answer"], "")

    def test_redirected_stdin_untouched(self):
        for name, exe in self.shells():
            with self.subTest(shell=name):
                p = subprocess.run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.tmp / "redirected.ps1"),
                                    str(SENDTO)], input=b"abc\n", capture_output=True, timeout=120)
                out = p.stdout.decode("utf-8", "replace")
                self.assertEqual(p.returncode, 0, out + p.stderr.decode("utf-8", "replace"))
                self.assertIn("redirected=True", out)
                self.assertIn("got=[abc]", out)


PTY_PROG = r'''
import json, os, pty, select, sys, time
FUNC = %r
MODE = %r
script = FUNC + "\nsleep 0.8\ns0=\"$(stty -g)\"\n" + ("flush_input\n" if MODE == "flush" else "") + \
    's1="$(stty -g)"\n[ "$s0" = "$s1" ] && echo STTY_SAME\nIFS= read -r -p "close> " ans\nprintf "\\nGOT[%%s]\\n" "$ans"\n'
pid, fd = pty.fork()
if pid == 0:
    os.execvp("bash", ["bash", "--norc", "--noprofile", "-c", script])
time.sleep(0.3)
os.write(fd, b"\r")          # 處理中誤按的 Enter
time.sleep(1.5)
os.write(fd, b"real\r")      # 題目出現後才輸入的答案
out = b""
while True:
    r, _, _ = select.select([fd], [], [], 5)
    if not r:
        break
    try:
        d = os.read(fd, 1024)
    except OSError:
        break
    if not d:
        break
    out += d
os.waitpid(pid, 0)
print(json.dumps(out.decode("utf-8", "replace")))
'''


@unittest.skipUnless(V122, "1.2.2 才有")
class KeyBufferBash(unittest.TestCase):
    def test_not_a_tty_is_skipped(self):
        """stdin 是管線（Git Bash）：flush_input 回傳 0、不吃掉管線裡的資料。"""
        bash = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
        if not bash:
            self.skipTest("找不到 bash")
        script = sh_function() + '\nflush_input; echo "rc=$?"\nIFS= read -r x\necho "GOT[$x]"\n'
        p = subprocess.run([bash, "--norc", "--noprofile", "-c", script], input=b"abc\n", capture_output=True, timeout=60)
        out = p.stdout.decode("utf-8", "replace")
        self.assertIn("rc=0", out)
        self.assertIn("GOT[abc]", out)

    def wsl(self):
        if os.environ.get("MMP_TEST_NO_WSL") or os.name != "nt" or not shutil.which("wsl.exe"):
            self.skipTest("沒有 WSL（或 MMP_TEST_NO_WSL）：pty 實測略過")
        p = subprocess.run(["wsl.exe", "-e", "python3", "-c", "import pty"], capture_output=True, timeout=60)
        if p.returncode != 0:
            self.skipTest("WSL 沒有 python3")

    def run_pty(self, mode: str) -> str:
        prog = PTY_PROG % (sh_function(), mode)
        p = subprocess.run(["wsl.exe", "-e", "python3", "-"], input=prog.encode("utf-8"), capture_output=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        return json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])

    def test_pty_flush(self):
        self.wsl()
        out = self.run_pty("flush")
        self.assertIn("GOT[real]", out)
        self.assertIn("STTY_SAME", out)

    def test_pty_control_without_flush(self):
        self.wsl()
        self.assertIn("GOT[]", self.run_pty("none"))


# ---------------------------------------------------------------- 2. 待釐清問題規則

@unittest.skipUnless(V122, "1.2.2 才有")
class QuestionRules(unittest.TestCase):
    def setUp(self):
        import auto_minutes
        self.am = auto_minutes

    def test_single_and_part_have_rule(self):
        v2 = _testenv.VER >= (2, 0, 0)          # 〔2.0.0〕規格 2.0.0 §3.2.2：拿掉「〔1.2.2〕」、(a) 收窄
        for name in ("SYSTEM_MINUTES", "SYSTEM_PART"):
            s = getattr(self.am, name)
            with self.subTest(prompt=name):
                self.assertIn("6. 待釐清問題（questions）＝會中提出但沒有結論、要再確認的問題或風險", s)   # 原句保留
                if v2:
                    self.assertIn("）。下列都不列為待釐清問題", s)
                    self.assertNotIn("〔1.2.2〕", s)
                    for key in ("包括講好怎麼決定的有條件答覆", "卻沒有講好怎麼決定、由誰決定或什麼時候決定的，仍然要列"):
                        self.assertIn(key, s)
                else:
                    self.assertIn("〔1.2.2〕下列都不列為待釐清問題", s)
                    self.assertIn("包括有條件的答覆", s)
                for key in ("(b) 現況說明", "不要自己從內容推想出問題", "仍然要列"):
                    self.assertIn(key, s)

    def test_merge_rule_same_as_121(self):
        """〔1.2.2〕彙整 prompt 退回 1.2.1：只去分段雜訊與重複，不判斷有沒有人問（1.2.2 實測：彙整依內容刪除會把 M3 真的問題刪光）。"""
        s = self.am.SYSTEM_MERGE
        self.assertIn("只去掉重複，以及第 8 條的分段雜訊", s)
        self.assertIn("8. 〔1.2.1〕去掉因為分段才出現的待釐清問題", s)
        self.assertNotIn("〔1.2.2〕", s)
        self.assertNotIn("\n9. ", s)

    @unittest.skipUnless(V121_AUTO_MINUTES.is_file(), "需要 meeting-minutes-pro-v1.2.1 目錄（公開 repo 只有最新版）")
    def test_merge_rule_text_same_as_121_file(self):
        """SYSTEM_MERGE 與 1.2.1 原檔逐字相同（repo 裡有 1.2.1 目錄時才比）。"""
        s = self.am.SYSTEM_MERGE
        text = V121_AUTO_MINUTES.read_text(encoding="utf-8")
        i = text.index('SYSTEM_MERGE = """') + len('SYSTEM_MERGE = """')
        self.assertEqual(s, text[i:text.index('"""', i)])

    def test_examples_not_from_materials(self):
        """prompt 的例句不得出現在 M1／M2／M3 講稿裡（不能拿測試題目當例子）。"""
        mats = "".join(p.read_text(encoding="utf-8") for p in MATERIALS.glob("M*.txt"))
        for word in ("A/B 測試", "首頁", "改版", "出差", "線上表單"):
            with self.subTest(word=word):
                self.assertIn(word, self.am.SYSTEM_PART)
                self.assertNotIn(word, mats)


# ---------------------------------------------------------------- 3. 「塊」→「段」

def _string_literals(path: Path) -> list:
    out = []
    with open(path, "rb") as f:
        for tok in tokenize.tokenize(f.readline):
            if tok.type == tokenize.STRING or getattr(tokenize, "FSTRING_MIDDLE", -1) == tok.type:
                out.append((tok.start[0], tok.string))
    return out


@unittest.skipUnless(V122, "1.2.2 才有")
class NoKuaiInOutput(unittest.TestCase):
    """使用者看得到的字串（Python 字串常值、入口腳本的非註解行）不用「塊」當單位；「區塊」不算。"""

    def test_python_strings(self):
        for name in ("auto_correct.py", "auto_minutes.py", "transcribe.py", "corrections.py", "common.py", "setup_backend.py"):
            for line, s in _string_literals(RUNTIME / "scripts" / name):
                if s.startswith(('"""', "'''", 'r"""')):
                    continue                     # docstring（註解性質）
                with self.subTest(file=name, line=line):
                    self.assertNotIn("塊", s.replace("區塊", ""))

    def test_entry_scripts(self):
        for path, enc in ((SENDTO, "utf-8-sig"), (DROPPED, "utf-8")):
            for i, line in enumerate(path.read_text(encoding=enc).splitlines(), 1):
                code = "" if line.lstrip().startswith("#") else line
                with self.subTest(file=path.name, line=i):
                    self.assertNotIn("塊", code.replace("區塊", ""))

    def test_new_wording(self):
        import auto_correct
        self.assertIn("剩下 {left} 段未校正", auto_correct.MESSAGES["rate_limited"])
        self.assertIn("剩下 {left} 段未校正", auto_correct.MESSAGES["quota_exhausted"])


# ---------------------------------------------------------------- 4. 安裝 log

@unittest.skipUnless(V122, "1.2.2 才有")
class VersionBanner(unittest.TestCase):
    def setUp(self):
        import common
        self.c = common
        self._env = os.environ.pop("MMP_INSTALLING", None)

    def tearDown(self):
        os.environ.pop("MMP_INSTALLING", None)
        if self._env is not None:
            os.environ["MMP_INSTALLING"] = self._env

    def test_normal_mismatch_kept(self):
        b = self.c.version_banner({"runtime_version": "1.2.1"})
        self.assertEqual(b, f"meeting-minutes-pro {self.c.VERSION}（config.json 的 runtime_version 是 1.2.1，版號不一致：請重新執行安裝程式）")

    def test_installing(self):
        os.environ["MMP_INSTALLING"] = "1"
        b = self.c.version_banner({"runtime_version": "1.2.1"})
        self.assertEqual(b, f"meeting-minutes-pro {self.c.VERSION}（升級中：1.2.1 → {self.c.VERSION}，安裝完成後更新 config.json 的 runtime_version）")
        self.assertNotIn("請重新執行安裝程式", b)

    def test_same_or_missing(self):
        os.environ["MMP_INSTALLING"] = "1"
        self.assertEqual(self.c.version_banner({"runtime_version": self.c.VERSION}), f"meeting-minutes-pro {self.c.VERSION}")
        self.assertEqual(self.c.version_banner({}), f"meeting-minutes-pro {self.c.VERSION}")

    def test_installers_set_flag_only_for_setup_backend(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        i = s.index('$env:MMP_INSTALLING = "1"')
        j = s.index("& $VenvPy @sbArgs", i)
        k = s.index("Remove-Item Env:MMP_INSTALLING", j)
        self.assertLess(k - j, 200)
        self.assertIn('if ($sbCode -ne 0) { Fail "硬體偵測', s)
        sh = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('MMP_INSTALLING=1 "$VPY" "${sb_args[@]}" | tee "$SB_OUT"', sh)
        self.assertNotIn("export MMP_INSTALLING", sh)
        for name in ("mm-sendto.ps1", "mm-dropped.sh"):
            self.assertNotIn("MMP_INSTALLING", (RUNTIME / name).read_text(encoding="utf-8-sig"))


@unittest.skipUnless(V122, "1.2.2 才有")
class AddedConfigKeys(unittest.TestCase):
    def setUp(self):
        import common
        self.c = common

    def test_cases(self):
        f = self.c.added_config_keys
        self.assertEqual(f({"a": 1, "runtime_version": "1.2.1"}, {"a": 2, "runtime_version": "1.2.2"}), [])
        self.assertEqual(f({}, {"runtime_version": "1.2.2"}), [])
        self.assertEqual(f({"a": 1}, {"a": 1, "minutes": {"x": 1}}), ["minutes"])           # 整塊新增只列區塊名
        self.assertEqual(f({"c": {"x": 1}}, {"c": {"x": 1, "y": 2, "z": {"k": 1}}}), ["c.y", "c.z"])
        self.assertEqual(f({"c": 1}, {"c": {"x": 1}}), [])                                   # 型別改變不算補鍵


def _snippet_ps1() -> str:
    s = INSTALL_PS1.read_text(encoding="utf-8-sig")
    return re.search(r"\$upgradePy = @'\n(.*?)\n'@", s, re.S).group(1)


def _snippet_sh() -> str:
    s = INSTALL_SH.read_text(encoding="utf-8")
    return re.search(r"<<'PY'\n(.*?)\nPY\n", s, re.S).group(1)


# 〔2.0.0 規格 §9.1〕從 1.x 升級時 upgrade_config() 另補 2.0 的五個區塊（1.2.2 目錄測試時是空的）
V2_KEYS = ["content_type", "diarization", "keyframes", "content_types", "subtitles"] if _testenv.VER >= (2, 0, 0) else []
V2_KEYS += ["html"] if _testenv.VER >= (2, 1, 0) else []      # 〔2.1.0〕upgrade_config() 另補 html 區塊（規格 2.1.0 §6.1）
V2_KEYS += ["reference", "consistency"] if _testenv.VER >= (2, 2, 0) else []  # 〔2.2.0〕另補 reference 區塊（規格 2.2.0 §8.1）與 consistency（全文用字統一）


@unittest.skipUnless(V122, "1.2.2 才有")
class InstallerConfigStep(unittest.TestCase):
    """直接執行安裝程式內嵌的「更新設定」Python 片段（暫存 home），檢查實際印出的措辭。"""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="mmp-inst-home-"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_snippet(self, code: str, cfg: dict, extra_env: dict) -> str:
        (self.home / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ, MEETING_MINUTES_PRO_HOME=str(self.home), MMP_SCRIPTS=str(RUNTIME / "scripts"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", **extra_env)
        p = subprocess.run([sys.executable, "-B", "-"], input=code.encode("utf-8"), capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        self.after = json.loads((self.home / "config.json").read_text(encoding="utf-8"))
        return p.stdout.decode("utf-8")

    def test_ps1_from_121_no_change(self):
        out = self.run_snippet(_snippet_ps1(), CFG_121, {"MMP_CORRECTION": "null"})
        self.assertEqual(json.loads(out.strip().splitlines()[-1])["added_keys"], V2_KEYS)
        self.assertEqual(self.after["runtime_version"], _testenv.VERSION)

    def test_ps1_from_110_lists_keys(self):
        out = self.run_snippet(_snippet_ps1(), CFG_110, {"MMP_CORRECTION": "null"})
        self.assertEqual(json.loads(out.strip().splitlines()[-1])["added_keys"], ["minutes"] + V2_KEYS)

    def test_ps1_explicit_choice_not_counted(self):
        out = self.run_snippet(_snippet_ps1(), CFG_121, {"MMP_CORRECTION": json.dumps({"openai": {"model": "x"}})})
        self.assertEqual(json.loads(out.strip().splitlines()[-1])["added_keys"], V2_KEYS)
        self.assertEqual(self.after["correction"]["openai"]["model"], "x")

    def test_sh_messages(self):
        out = self.run_snippet(_snippet_sh(), CFG_121, {})
        if V2_KEYS:                                       # 〔2.0.0〕1.2.1 → 2.0 會補上 2.0 的區塊
            self.assertIn(f"    [OK] config.json 已補上新版設定鍵：{'、'.join(V2_KEYS)}（既有的值不變）", out)
        else:
            self.assertIn(f"    [OK] config.json 設定鍵無變更（runtime_version 更新為 {_testenv.VERSION}）", out)
        self.assertNotIn("已補上 1.2.0", out)
        out = self.run_snippet(_snippet_sh(), CFG_110, {})
        self.assertIn(f"    [OK] config.json 已補上新版設定鍵：{'、'.join(['minutes'] + V2_KEYS)}（既有的值不變）", out)

    def test_ps1_message_lines(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        self.assertIn('Ok ("config.json 已補上新版設定鍵：{0}（既有的值不變）" -f ($added -join "、"))', s)
        self.assertIn('Ok "config.json 設定鍵無變更（runtime_version 更新為 $Version）"', s)
        self.assertNotIn("已補上 1.2.0 的設定鍵", s)


if __name__ == "__main__":
    unittest.main()
