"""打包（tools/make_dist.py）的測試：實際產生安裝包到暫存區並檢查內容，以及各項打包前檢查的反例。

  python -B test_dist.py          （或經由 run_tests.py）
"""
import hashlib
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
VDIR = ROOT / "meeting-minutes-proofread-v1.0.0"
spec = importlib.util.spec_from_file_location("make_dist", ROOT / "tools" / "make_dist.py")
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
WORK = Path(tempfile.mkdtemp(prefix="mmproof-dist-"))


class MakeDist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = WORK / "dist"
        cls.r = D.make(None, str(cls.out))

    def test_files_and_root(self):
        name = "meeting-minutes-proofread-v1.0.0-installer.zip"
        self.assertEqual(self.r["installer"].name, name)
        with zipfile.ZipFile(self.r["installer"]) as zf:
            names = sorted(n for n in zf.namelist() if not n.endswith("/"))
            self.assertEqual(names, sorted("meeting-minutes-proofread-v1.0.0/" + f for f in D.REQUIRED))
            for info in zf.infolist():
                mode = (info.external_attr >> 16) & 0o777
                want = 0o755 if info.filename.endswith((".sh", ".command")) else 0o644
                self.assertEqual(mode, want, info.filename)
                rel = info.filename.split("/", 1)[1]
                self.assertEqual(zf.read(info), (VDIR / rel).read_bytes(), "內容取自工作目錄")
            self.assertFalse([n for n in names if "__pycache__" in n or "/tests/" in n])

    def test_sha256_file(self):
        inst = self.r["installer"]
        line = (inst.parent / (inst.name + ".sha256")).read_text(encoding="ascii")
        self.assertEqual(line, f"{hashlib.sha256(inst.read_bytes()).hexdigest()}  {inst.name}\n")

    def test_cli_exit_0(self):
        out = WORK / "dist-cli"
        p = subprocess.run([sys.executable, "-B", str(ROOT / "tools" / "make_dist.py"), "--out-dir", str(out)],
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("版號 1.0.0", p.stdout)
        self.assertEqual((out / self.r["installer"].name).read_bytes(), self.r["installer"].read_bytes(),
                         "同樣的工作目錄產生同樣的安裝包")


def copy_vdir(tmp: Path) -> Path:
    dst = tmp / VDIR.name
    shutil.copytree(VDIR, dst, ignore=shutil.ignore_patterns("__pycache__"))
    return dst


class Checks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=WORK))

    def test_version_mismatch(self):
        v = copy_vdir(self.tmp)
        p = v / "install.sh"
        p.write_bytes(p.read_bytes().replace(b'VERSION="1.0.0"', b'VERSION="1.0.1"'))
        with self.assertRaisesRegex(D.DistError, "install.sh VERSION 1.0.1"):
            D.read_version(v)

    def test_dir_name_mismatch(self):
        v = copy_vdir(self.tmp)
        w = v.rename(self.tmp / "meeting-minutes-proofread-v9.9.9")
        with self.assertRaisesRegex(D.DistError, "版本目錄名稱"):
            D.read_version(w)

    def test_file_list(self):
        files = list(D.REQUIRED)
        D.check_file_list(files)
        with self.assertRaisesRegex(D.DistError, "缺少"):
            D.check_file_list([f for f in files if f != "uninstall.ps1"])
        with self.assertRaisesRegex(D.DistError, "清單以外"):
            D.check_file_list(files + ["notes.txt"])

    def test_encoding_checks(self):
        v = copy_vdir(self.tmp)
        files = list(D.REQUIRED)
        D.check_encoding(v, files)
        cases = (
            ("install.cmd", lambda b: b.replace(b"\r\n", b"\n"), "CRLF"),
            ("install.cmd", lambda b: b + "rem 中文\r\n".encode("utf-8"), "ASCII"),
            ("install.ps1", lambda b: b[3:], "BOM"),
            ("install.sh", lambda b: b.replace(b"\n", b"\r\n"), "CR"),
        )
        for name, f, msg in cases:
            with self.subTest(file=name, rule=msg):
                orig = (v / name).read_bytes()
                (v / name).write_bytes(f(orig))
                try:
                    with self.assertRaisesRegex(D.DistError, msg):
                        D.check_encoding(v, files)
                finally:
                    (v / name).write_bytes(orig)

    def test_url_check(self):
        v = copy_vdir(self.tmp)
        files = list(D.REQUIRED)
        self.assertEqual(D.check_urls(v, files), len(files))       # 本機網址（127.0.0.1）允許
        p = v / "README.md"
        p.write_text(p.read_text(encoding="utf-8") + "\n詳見 https://example.com/meeting-minutes/\n", encoding="utf-8")
        with self.assertRaisesRegex(D.DistError, "README.md:"):
            D.check_urls(v, files)


class RepoAttributes(unittest.TestCase):
    def test_cmd_crlf_attribute(self):
        """.gitattributes 讓 .cmd 固定 CRLF（重新 checkout 也不會變成 LF）。"""
        for name, want in (("install.cmd", "crlf"), ("uninstall.cmd", "crlf"), ("install.sh", "lf"), ("install.ps1", "lf")):
            out = subprocess.run(["git", "-C", str(VDIR), "check-attr", "eol", "--", name], capture_output=True, text=True).stdout
            self.assertTrue(out.strip().endswith(f"eol: {want}"), out)

    def test_exec_bit_in_index(self):
        out = subprocess.run(["git", "-C", str(VDIR), "ls-files", "-s", "--", "install.sh", "install.command", "uninstall.sh",
                              "uninstall.command"], capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(len(out), 4, out)
        self.assertTrue(all(line.startswith("100755") for line in out), out)


def main() -> tuple:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    r = unittest.TextTestRunner(verbosity=1).run(suite)
    total = r.testsRun - len(r.skipped)
    bad = len(r.failures) + len(r.errors)
    shutil.rmtree(WORK, ignore_errors=True)
    return total, total - bad, [str(t) for t, _ in r.failures + r.errors]


if __name__ == "__main__":
    t, ok, bad = main()
    print(f"dist {ok}/{t} PASS")
    sys.exit(0 if ok == t else 1)
