"""〔2.1.0〕transcribe.load_asr() 的 console 訊息印實際模型名稱：

- 選 Breeze 時成功訊息是「Breeze-ASR-25 載入：…」，失敗訊息是「無法以 …/… 載入 Breeze-ASR-25：…」，不寫「Whisper」
- Whisper 別名印完整模型名（turbo → 「Whisper large-v3-turbo」）；不在對照表上的值印「Whisper <原值>」
- 後端與裝置照舊附在後面

用假的 backends 模組（不載入真模型、不需要 GPU）。2.1.0 以前的版本（仍印「Whisper 載入」）整個略過。
"""
import contextlib
import io
import sys
import types
import unittest

import _testenv

V210 = _testenv.VER >= (2, 1, 0)
if V210:
    import transcribe as tr


class FakeBackends(types.ModuleType):
    """代替 backends 模組：記下 create() 的參數；fail 有值時丟出該例外。"""

    def __init__(self, fail: Exception | None = None):
        super().__init__("backends")
        self.fail = fail
        self.calls = []

    def create(self, backend, model, device, language=None, hotwords=None, compute_type="default", vad_filter=None):
        # 〔2.5.0〕load_asr() 多傳 vad_filter（規格 2.5.0 §6）；舊版不傳，預設 None
        self.calls.append((backend, model, device, compute_type))
        if self.fail is not None:
            raise self.fail
        return object()


@unittest.skipUnless(V210, "2.1.0 才有")
class LoadAsrMessage(unittest.TestCase):
    def setUp(self):
        self._saved = sys.modules.get("backends")

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("backends", None)
        else:
            sys.modules["backends"] = self._saved

    def load(self, backend, model, device, fail=None):
        """回傳 (stderr 文字, SystemExit 訊息或 None, 假後端)。"""
        fake = FakeBackends(fail)
        sys.modules["backends"] = fake
        err = io.StringIO()
        exit_msg = None
        with contextlib.redirect_stderr(err):
            try:
                tr.load_asr(backend, model, device, "default", "zh", None)
            except SystemExit as ex:
                exit_msg = str(ex.code)
        return err.getvalue(), exit_msg, fake

    # ---- 成功
    def test_breeze_success(self):
        out, exit_msg, fake = self.load("ct2", "breeze", "cuda")
        print(f"\n    [breeze 成功] {out.strip()}", file=sys.__stdout__)
        self.assertIsNone(exit_msg)
        self.assertEqual(fake.calls, [("ct2", "breeze", "cuda", "default")])
        self.assertRegex(out, r"^  Breeze-ASR-25 載入：ct2 / cuda（\d+\.\ds）\n$")
        self.assertNotIn("Whisper", out)

    def test_whisper_turbo_success(self):
        out, exit_msg, _ = self.load("openvino", "turbo", "NPU")
        print(f"\n    [turbo 成功] {out.strip()}", file=sys.__stdout__)
        self.assertIsNone(exit_msg)
        self.assertRegex(out, r"^  Whisper large-v3-turbo 載入：openvino / NPU（\d+\.\ds）\n$")

    def test_whisper_other_aliases(self):
        for model, name in (("large-v3", "Whisper large-v3"), ("base", "Whisper base"),
                            ("Systran/faster-whisper-small", "Whisper Systran/faster-whisper-small")):
            with self.subTest(model=model):
                out, exit_msg, _ = self.load("mlx", model, "gpu")
                self.assertIsNone(exit_msg)
                self.assertTrue(out.startswith(f"  {name} 載入：mlx / gpu（"), out)

    # ---- 失敗
    def test_breeze_failure(self):
        out, exit_msg, _ = self.load("openvino", "breeze", "GPU", fail=RuntimeError("裝置無回應"))
        print(f"\n    [breeze 失敗] {exit_msg.splitlines()[0]}", file=sys.__stdout__)
        self.assertEqual(out, "")
        first, second = exit_msg.splitlines()
        self.assertEqual(first, "無法以 openvino/GPU 載入 Breeze-ASR-25：裝置無回應")
        self.assertIn("請重新執行 install.cmd（或 setup_backend.py）重新偵測", second)
        self.assertNotIn("Whisper", exit_msg)

    def test_whisper_turbo_failure(self):
        out, exit_msg, _ = self.load("ct2", "turbo", "cuda:1", fail=OSError("找不到 CUDA"))
        print(f"\n    [turbo 失敗] {exit_msg.splitlines()[0]}", file=sys.__stdout__)
        self.assertEqual(out, "")
        self.assertEqual(exit_msg.splitlines()[0], "無法以 ct2/cuda:1 載入 Whisper large-v3-turbo：找不到 CUDA")

    def test_display_name_table(self):
        self.assertEqual(tr.asr_display_name("breeze"), "Breeze-ASR-25")
        self.assertEqual(tr.asr_display_name("turbo"), "Whisper large-v3-turbo")
        self.assertEqual(tr.asr_display_name("x"), "Whisper x")

    def test_every_alias_has_display_name(self):
        import common
        aliases = {a for models in common.WHISPER_MODELS.values() for a in models}
        self.assertEqual(aliases - set(tr.ASR_DISPLAY), set())


if __name__ == "__main__":
    unittest.main()
