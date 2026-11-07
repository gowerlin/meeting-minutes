"""tools/make_dist.py 的測試。

- 〔2.0.0〕模型權重檢查（規格 §9.5）：版本目錄內有 `pytorch_model.bin`、`*.npz` 就 exit 2、不產生檔案。
- 〔2.0.2〕`--product basic`（基本版）：產品表的常數、版號檢查用基本版的 SKILL 版本註解、預設版本目錄、
  在暫存的 git repo 實際打包（發行檔名、zip 根目錄、執行權限、README.txt），Pro 預設不變。

只在暫存目錄建假的版本目錄，不寫 dist/、不呼叫 git 以外的任何外部程式、不呼叫模型。
"""
import contextlib
import io
import subprocess
import sys
import zipfile
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402

sys.path.insert(0, str(HERE.parent / "tools"))
import make_dist  # noqa: E402


def make_version_dir(root: Path, version: str = "9.9.9") -> Path:
    """版號一致的最小版本目錄（common.py＋SKILL.md）。"""
    vd = root / f"meeting-minutes-pro-v{version}"
    (vd / "payload" / "runtime" / "scripts").mkdir(parents=True)
    (vd / "payload" / "skill" / "meeting-minutes-pro").mkdir(parents=True)
    (vd / "payload" / "runtime" / "scripts" / "common.py").write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    (vd / "payload" / "skill" / "meeting-minutes-pro" / "SKILL.md").write_text(
        f"<!-- meeting-minutes-pro-version: {version} -->\n", encoding="utf-8")
    return vd


class WeightCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vd = make_version_dir(self.root)
        self.dist_before = sorted(p.name for p in make_dist.DIST_DIR.iterdir()) if make_dist.DIST_DIR.is_dir() else None

    def tearDown(self):
        self.tmp.cleanup()
        dist_after = sorted(p.name for p in make_dist.DIST_DIR.iterdir()) if make_dist.DIST_DIR.is_dir() else None
        self.assertEqual(dist_after, self.dist_before)          # 失敗的打包不動 dist/

    def run_main(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = make_dist.main([str(self.vd)])
        return code, err.getvalue()

    def test_clean_dir_has_no_weights(self):
        self.assertEqual(make_dist.find_weights(self.vd), [])
        make_dist.check_no_weights(self.vd)                     # 不丟例外

    def test_pytorch_model_bin_exit_2(self):
        p = self.vd / "payload" / "runtime" / "models" / "seg" / "pytorch_model.bin"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"\0" * 16)
        self.assertEqual(make_dist.find_weights(self.vd), ["payload/runtime/models/seg/pytorch_model.bin"])
        code, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("模型權重", err)
        self.assertIn("pytorch_model.bin", err)

    def test_npz_exit_2(self):
        for rel in ("plda/plda.npz", "plda/XVEC_TRANSFORM.NPZ"):
            p = self.vd / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"PK")
        self.assertEqual(make_dist.find_weights(self.vd), ["plda/XVEC_TRANSFORM.NPZ", "plda/plda.npz"])
        code, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("plda/plda.npz", err)

    def test_weight_check_before_git(self):
        """權重檢查在 git ls-files 之前：不在 git 裡的暫存目錄也是以權重為理由停止。"""
        (self.vd / "pytorch_model.bin").write_bytes(b"x")
        code, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("模型權重", err)
        self.assertNotIn("git", err)

    def test_similar_names_not_weights(self):
        for name in ("pytorch_model.bin.md", "npz-notes.txt", "model.onnx"):
            (self.vd / name).write_text("x", encoding="utf-8")
        self.assertEqual(make_dist.find_weights(self.vd), [])


class RealVersionDir(unittest.TestCase):
    def test_version_dir_has_no_weights(self):
        self.assertEqual(make_dist.find_weights(_testenv.VERSION_DIR), [])


# ---------------------------------------------------------------- 〔2.0.2〕--product basic

def make_product_dir(root: Path, product, version: str = "9.9.9", marker: str | None = None) -> Path:
    """某個產品的最小版本目錄：common.py、SKILL.md（＋references）、install.sh、README.md、payload zip。"""
    vd = root / f"{product.dir_prefix}{version}"
    skill = vd / product.skill_dir
    (vd / "payload" / "runtime" / "scripts").mkdir(parents=True)
    (skill / "references").mkdir(parents=True)
    (vd / "payload" / "runtime" / "scripts" / "common.py").write_text(f'VERSION = "{version}"\n', encoding="utf-8")
    marker = marker or product.skill_version_label.split(":")[0].replace("<!--", "").strip()
    (skill / "SKILL.md").write_text(f"<!-- {marker}: {version} -->\n# skill\n", encoding="utf-8")
    (skill / "references" / "template.md").write_text("# 範本\n", encoding="utf-8")
    (vd / "install.sh").write_text(f'#!/bin/bash\nVERSION="{version}"\n', encoding="utf-8")
    (vd / "install.command").write_text("#!/bin/bash\n", encoding="utf-8")
    (vd / "payload" / "runtime" / "mm-dropped.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (vd / "README.md").write_text(f"# 標題\n\n> 版本 {version}\n", encoding="utf-8")
    with zipfile.ZipFile(vd / product.payload_zip, "w") as zf:
        for f in sorted(p for p in skill.rglob("*") if p.is_file()):
            zf.writestr(product.upload_root + f.relative_to(skill).as_posix(), f.read_bytes())
    return vd


class ProductTable(unittest.TestCase):
    def test_basic_constants(self):
        b = make_dist.PRODUCTS["basic"]
        self.assertEqual(b.dir_prefix, "meeting-minutes-v")
        self.assertEqual(b.skill_dir, "payload/skill/meeting-minutes")
        self.assertEqual(b.upload_root, "meeting-minutes/")
        self.assertEqual(b.payload_zip, "payload/meeting-minutes-upload.zip")
        self.assertEqual(b.skill_version_re.search("<!-- meeting-minutes-version: 1.0.1 -->").group(1), "1.0.1")
        self.assertIsNone(b.skill_version_re.search("<!-- meeting-minutes-pro-version: 1.0.1 -->"))
        self.assertEqual([p.name for p in b.root_candidates], ["meeting-minutes-skill", "basic"])
        self.assertEqual(make_dist.EXEC_SUFFIXES, (".sh", ".command"))     # 兩個產品共用

    def test_pro_is_default_and_unchanged(self):
        p = make_dist.PRODUCTS["pro"]
        self.assertEqual((p.dir_prefix, p.upload_root, p.payload_zip),
                         ("meeting-minutes-pro-v", "meeting-minutes-pro/", "payload/meeting-minutes-pro-upload.zip"))
        self.assertEqual((make_dist.DIR_PREFIX, make_dist.UPLOAD_ROOT, make_dist.SKILL_ROOT, make_dist.DIST_DIR),
                         (p.dir_prefix, p.upload_root, p.root(), p.root() / "dist"))
        self.assertEqual(make_dist.SKILL_ROOT, HERE.parent)


class BasicVersion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_version_basic_marker(self):
        vd = make_product_dir(self.root, make_dist.BASIC, "1.0.1")
        self.assertEqual(make_dist.read_version(vd, make_dist.BASIC), "1.0.1")

    def test_pro_marker_in_basic_dir_fails(self):
        vd = make_product_dir(self.root, make_dist.BASIC, "1.0.1", marker="meeting-minutes-pro-version")
        with self.assertRaises(make_dist.DistError) as cm:
            make_dist.read_version(vd, make_dist.BASIC)
        self.assertIn("meeting-minutes-version", str(cm.exception))

    def test_version_mismatch_fails(self):
        vd = make_product_dir(self.root, make_dist.BASIC, "1.0.1")
        (vd / "install.sh").write_text('VERSION="1.0.0"\n', encoding="utf-8")
        with self.assertRaises(make_dist.DistError) as cm:
            make_dist.read_version(vd, make_dist.BASIC)
        self.assertIn("install.sh VERSION 1.0.0", str(cm.exception))

    def test_default_dir_highest_and_ignores_pro(self):
        for v in ("1.0.0", "1.0.10", "1.0.9"):
            (self.root / f"meeting-minutes-v{v}").mkdir()
        (self.root / "meeting-minutes-pro-v9.0.0").mkdir()
        (self.root / "meeting-minutes-vnext").mkdir()
        self.assertEqual(make_dist.find_version_dir(None, make_dist.BASIC, self.root).name, "meeting-minutes-v1.0.10")
        self.assertEqual(make_dist.find_version_dir(None, make_dist.PRO, self.root).name, "meeting-minutes-pro-v9.0.0")


class BuildInTempRepo(unittest.TestCase):
    """在暫存的 git repo 實際打包（不碰真的 dist/）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        self.out = Path(self.tmp.name) / "out"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, product, version):
        vd = make_product_dir(self.root, product, version)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            code = make_dist.main(["--product", product.key, str(vd), "--out-dir", str(self.out)])
        self.assertEqual(code, 0, err.getvalue())
        return vd, out.getvalue()

    def check(self, product, version, prefix, desktop):
        vd, out = self.build(product, version)
        names = sorted(p.name for p in self.out.iterdir())
        inst, up = f"{prefix}{version}-installer.zip", f"{prefix}{version}-claude-app-upload.zip"
        self.assertEqual(names, sorted([inst, inst + ".sha256", up, up + ".sha256", "README.txt"]))
        with zipfile.ZipFile(self.out / inst) as zf:
            infos = {i.filename: i for i in zf.infolist()}
        self.assertTrue(all(n.startswith(f"{prefix}{version}/") for n in infos))
        for rel, mode in (("install.sh", 0o755), ("install.command", 0o755), ("payload/runtime/mm-dropped.sh", 0o755),
                          ("README.md", 0o644), (product.payload_zip, 0o644)):
            self.assertEqual((infos[f"{prefix}{version}/{rel}"].external_attr >> 16) & 0o777, mode, rel)
        self.assertEqual((self.out / up).read_bytes(), (vd / product.payload_zip).read_bytes())
        sha = (self.out / (inst + ".sha256")).read_text(encoding="ascii")
        self.assertEqual(sha, f"{make_dist.sha256_of(self.out / inst)}  {inst}\n")
        readme = (self.out / "README.txt").read_text(encoding="utf-8-sig")
        for s in (inst, up, desktop, f"{prefix}{version}\\install.cmd", f"{product.name} v{version}"):
            self.assertIn(s, readme)
        self.assertIn(f"版號 {version}", out)

    def test_basic(self):
        self.check(make_dist.BASIC, "1.0.1", "meeting-minutes-v", "meeting-minutes-skill-upload.zip")

    def test_pro(self):
        self.check(make_dist.PRO, "2.0.2", "meeting-minutes-pro-v", "meeting-minutes-pro-skill-upload.zip")

    def test_basic_upload_zip_out_of_date_fails(self):
        vd = make_product_dir(self.root, make_dist.BASIC, "1.0.1")
        (vd / make_dist.BASIC.skill_dir / "SKILL.md").write_text("<!-- meeting-minutes-version: 1.0.1 -->\n# 改過\n",
                                                                 encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = make_dist.main(["--product", "basic", str(vd), "--out-dir", str(self.out)])
        self.assertEqual(code, 2)
        self.assertIn("請先重新產生 payload zip", err.getvalue())
        self.assertFalse(self.out.exists())


@unittest.skipUnless(make_dist.BASIC.root().is_dir(), "沒有基本版目錄")
class RealBasicVersionDir(unittest.TestCase):
    def test_latest_basic_consistent(self):
        vd = make_dist.find_version_dir(None, make_dist.BASIC)
        version = make_dist.read_version(vd, make_dist.BASIC)
        self.assertEqual(vd.name, f"meeting-minutes-v{version}")
        self.assertEqual(make_dist.find_weights(vd), [])
        make_dist.check_upload_zip(vd / make_dist.BASIC.payload_zip, vd / make_dist.BASIC.skill_dir,
                                   make_dist.BASIC.upload_root)


if __name__ == "__main__":
    unittest.main()
