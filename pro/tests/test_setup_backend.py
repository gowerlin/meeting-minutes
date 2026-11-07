"""〔1.2.1〕安裝程式以 -Backend（--backend）升級時保留既有精度。

setup_backend.py --force <backend>:<device> 不測速；1.2.0 沒給 --compute-type 時一律寫預設精度
（ct2:cuda → int8_float32），會把使用者原本的 int8_float16 改掉。1.2.1：後端與裝置和既有 config.json 相同 → 沿用既有
compute_type；--compute-type 明確指定 → 照指定；後端或裝置不同 → 照原本的預設。

main() 的測試用假的 download_models（不下載）與假的硬體盤點，只在暫存 home 寫 config.json；不碰已安裝的 runtime。
"""
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import _testenv

V121 = tuple(int(x) for x in _testenv.VERSION.split(".")) >= (1, 2, 1)
INSTALL_PS1 = _testenv.VERSION_DIR / "install.ps1"
INSTALL_SH = _testenv.VERSION_DIR / "install.sh"


def fake_dl():
    m = types.ModuleType("download_models")
    m.calls = []
    m.ensure_common = lambda: m.calls.append("common")
    m.ensure_punct = lambda archive=None: True
    m.ensure_whisper = lambda backend, model: m.calls.append(("whisper", backend, model))
    m.remove_backend_models = lambda be: m.calls.append(("remove", be))
    return m


@unittest.skipUnless(V121, "1.2.1 才有")
class ForcedComputeType(unittest.TestCase):
    def setUp(self):
        import setup_backend
        self.sb = setup_backend

    def test_keep_existing_when_same_backend_and_device(self):
        old = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16"}
        self.assertEqual(self.sb.forced_compute_type("ct2", "cuda", None, old), ("int8_float16", "kept"))
        old = {"backend": "openvino", "device": "NPU", "compute_type": "default"}
        self.assertEqual(self.sb.forced_compute_type("openvino", "npu", None, old), ("default", "kept"))   # 裝置不分大小寫

    def test_explicit_wins(self):
        old = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16"}
        self.assertEqual(self.sb.forced_compute_type("ct2", "cuda", "float16", old), ("float16", "explicit"))
        self.assertEqual(self.sb.forced_compute_type("ct2", "cuda", "int8_float32", {}), ("int8_float32", "explicit"))

    def test_default_when_different_or_missing(self):
        old = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16"}
        self.assertEqual(self.sb.forced_compute_type("ct2", "cpu", None, old), ("int8", "default"))          # 裝置不同
        self.assertEqual(self.sb.forced_compute_type("openvino", "CPU", None, old), ("default", "default"))  # 後端不同
        self.assertEqual(self.sb.forced_compute_type("ct2", "cuda", None, {}), ("int8_float32", "default"))  # 沒有既有設定
        self.assertEqual(self.sb.forced_compute_type("ct2", "cuda", None, {"backend": "ct2", "device": "cuda"}),
                         ("int8_float32", "default"))                                                        # 既有設定沒有精度


@unittest.skipUnless(V121, "1.2.1 才有")
class MainForce(unittest.TestCase):
    """setup_backend.main() 以 --force 跑一次（假下載、假硬體），檢查寫進 config.json 的 compute_type。"""

    def setUp(self):
        import setup_backend
        self.sb = setup_backend
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = Path(tempfile.mkdtemp(prefix="mmp-sb-home-"))
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.home, ignore_errors=True)

    def run_main(self, old_cfg: dict, *argv) -> dict:
        (self.home / "config.json").write_text(json.dumps(old_cfg), encoding="utf-8")
        inv = {"cpu": "fake", "machine": "AMD64", "video": [], "openvino": {}, "nvidia": []}
        with mock.patch.dict(sys.modules, {"download_models": fake_dl()}), \
                mock.patch.object(self.sb, "inventory", return_value=inv), \
                mock.patch.object(sys, "argv", ["setup_backend.py", *argv]), \
                mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            self.sb.main()
        return json.loads((self.home / "config.json").read_text(encoding="utf-8"))

    def test_upgrade_keeps_int8_float16(self):
        old = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "whisper": "turbo",
               "bench": [{"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "rtf": 0.05}],
               "detected_at": "2026-10-01T10:00:00", "correction": {"enabled": True}}
        cfg = self.run_main(old, "--whisper", "turbo", "--force", "ct2:cuda")
        self.assertEqual((cfg["backend"], cfg["device"], cfg["compute_type"]), ("ct2", "cuda", "int8_float16"))
        self.assertEqual((cfg["bench"], cfg["detected_at"], cfg["correction"]), (old["bench"], old["detected_at"], {"enabled": True}))

    def test_explicit_compute_type(self):
        old = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16"}
        cfg = self.run_main(old, "--force", "ct2:cuda", "--compute-type", "float16")
        self.assertEqual(cfg["compute_type"], "float16")

    def test_different_device_uses_default(self):
        old = {"backend": "openvino", "device": "NPU", "compute_type": "default"}
        cfg = self.run_main(old, "--force", "ct2:cuda")
        self.assertEqual((cfg["backend"], cfg["compute_type"]), ("ct2", "int8_float32"))


@unittest.skipUnless(V121, "1.2.1 才有")
class Installers(unittest.TestCase):
    """安裝程式把 -ComputeType／--compute-type 轉成 setup_backend.py --compute-type（只在有 -Backend 時）。"""

    def test_install_ps1(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        self.assertIn('[string]$ComputeType = ""', s)
        self.assertIn('if ($Backend) { $sbArgs += @("--compute-type", $ComputeType) }', s)
        self.assertIn("-ComputeType 要搭配 -Backend 使用", s)

    def test_install_sh(self):
        s = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn('--compute-type) COMPUTE_TYPE="$2"; shift 2 ;;', s)
        self.assertIn('if [ -n "$BACKEND" ]; then sb_args+=(--compute-type "$COMPUTE_TYPE")', s)


if __name__ == "__main__":
    unittest.main()
