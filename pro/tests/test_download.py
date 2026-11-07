"""標點模型下載（規格 §5.1）。每個測試用自己的暫存 home，不碰已安裝的 runtime。

- 失敗模擬：下載網址不存在、SHA-256 不符、壓縮檔內容不對 → ensure_punct() 回傳 False、不丟例外、不留暫存檔。
- 成功驗證：設定 MMP_PUNCT_ARCHIVE 指向真的 tar.bz2（約 65 MB）時，以離線安裝路徑驗 SHA-256 並解開。
"""
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

import _testenv
import common
import download_models as dl


class TempHome(unittest.TestCase):
    def setUp(self):
        self._old = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = tempfile.mkdtemp(prefix="mmp-dl-")
        os.environ["MEETING_MINUTES_PRO_HOME"] = self.home

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._old   # _testenv 保證一定有值
        shutil.rmtree(self.home, ignore_errors=True)

    def call(self, **kw):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = dl.ensure_punct(**kw)
        return ok, buf.getvalue()

    def leftovers(self):
        return [p.name for p in Path(self.home).rglob("*") if p.is_file()]


def fake_archive(path: Path, with_model: bool = True):
    with tarfile.open(path, "w:bz2") as tf:
        for name, data in ([("model.int8.onnx", b"x" * 1024)] if with_model else []) + [("README.md", b"hi")]:
            info = tarfile.TarInfo(f"{common.PUNCT_NAME}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


class Failures(TempHome):
    def test_bad_url(self):
        ok, out = self.call(url="http://127.0.0.1:9/does-not-exist.tar.bz2")
        self.assertFalse(ok)
        self.assertIn("標點模型下載失敗", out)
        self.assertIn("setup_backend.py --punct-only", out)
        self.assertEqual(self.leftovers(), [])
        self.assertFalse(common.punct_ready())

    def test_sha_mismatch_download_deleted(self):
        src = Path(self.home).parent / f"{Path(self.home).name}-src.tar.bz2"
        fake_archive(src)
        try:
            ok, out = self.call(url=src.as_uri())
            self.assertFalse(ok)
            self.assertIn("SHA-256 不符", out)
            self.assertEqual(self.leftovers(), [])   # 下載檔已刪
        finally:
            src.unlink(missing_ok=True)

    def test_sha_mismatch_local_archive_kept(self):
        src = Path(self.home) / "local.tar.bz2"
        fake_archive(src)
        ok, out = self.call(archive=src)
        self.assertFalse(ok)
        self.assertIn("SHA-256 不符", out)
        self.assertTrue(src.exists())                # 使用者給的檔不刪
        self.assertFalse(common.punct_model_dir().exists())

    def test_missing_local_archive(self):
        ok, out = self.call(archive=Path(self.home) / "nope.tar.bz2")
        self.assertFalse(ok)
        self.assertIn("找不到", out)

    def test_setup_backend_punct_only_failure_exit(self):
        """setup_backend.py --punct-only：失敗時 exit 1、最後一行 JSON punct=false，不丟 traceback。"""
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", MEETING_MINUTES_PRO_HOME=self.home)
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "setup_backend.py"), "--punct-only",
                            "--punct-archive", str(Path(self.home) / "nope.tar.bz2")],
                           env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 1)
        self.assertEqual(p.stdout.strip().splitlines()[-1], '{"punct": false}')
        self.assertNotIn("Traceback", p.stderr)

    def test_ready_threshold(self):
        d = common.punct_model_dir()
        d.mkdir(parents=True)
        (d / "model.int8.onnx").write_bytes(b"x" * 1024)
        self.assertFalse(common.punct_ready())      # 太小（< 50 MB）不算就緒


@unittest.skipUnless(os.environ.get("MMP_PUNCT_ARCHIVE"), "沒有設定 MMP_PUNCT_ARCHIVE（真的標點模型壓縮檔）")
class RealArchive(TempHome):
    def test_offline_install(self):
        arc = Path(os.environ["MMP_PUNCT_ARCHIVE"])
        self.assertEqual(arc.stat().st_size, common.PUNCT_SIZE)
        self.assertEqual(dl.sha256_of(arc), common.PUNCT_SHA256)
        ok, out = self.call(archive=arc)
        self.assertTrue(ok, out)
        self.assertIn("SHA-256 驗證通過", out)
        self.assertTrue(common.punct_ready())
        files = sorted(p.name for p in common.punct_model_dir().iterdir())
        self.assertEqual(files, sorted(common.PUNCT_FILES))   # 只解出三個檔
        self.assertTrue(arc.exists())
        ok, out = self.call(archive=arc)                      # 已就緒就跳過
        self.assertTrue(ok)
        self.assertNotIn("SHA-256", out)


if __name__ == "__main__":
    unittest.main()
