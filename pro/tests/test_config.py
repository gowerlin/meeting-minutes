"""設定：setting() 與 upgrade_config()（規格 §3.1、§3.4）。每個測試用自己的暫存 home。

另可對真實 1.0.0 config.json 的「副本」驗證：把 MMP_V100_CONFIG 設成副本路徑（測試只讀它，在暫存 home 裡升級）。
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import _testenv  # noqa: F401
import common

V100_CONFIG = {   # 1.0.0 安裝後的 config.json 形狀（硬體資訊為虛構）
    "backend": "openvino", "device": "NPU", "compute_type": "default", "whisper": "turbo",
    "detected_at": "2026-11-01T08:00:00",
    "profiles": {"breeze": {"backend": "openvino", "device": "CPU", "compute_type": "default", "rtf": 0.16}},
    "hardware": {"os": "win32", "machine": "AMD64", "cpu": "Example CPU", "video": [], "nvidia": [], "openvino": {}},
    "bench": [{"backend": "openvino", "device": "NPU", "compute_type": "default", "rtf": 0.05, "ok": True,
               "error": None}],
}


class TempHome(unittest.TestCase):
    def setUp(self):
        self._old = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = tempfile.mkdtemp(prefix="mmp-cfg-")
        os.environ["MEETING_MINUTES_PRO_HOME"] = self.home

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._old   # _testenv 保證一定有值
        shutil.rmtree(self.home, ignore_errors=True)

    def write(self, cfg):
        Path(self.home, "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")


class Setting(TempHome):
    def test_defaults_and_override(self):
        self.assertEqual(common.VERSION, _testenv.VERSION)
        self.assertIs(common.setting({}, "punctuation.enabled"), True)
        self.assertEqual(common.setting({}, "punctuation.paragraph_gap"), 2.0)
        self.assertIs(common.setting({}, "correction.enabled"), False)
        self.assertEqual(common.setting({}, "correction.provider"), "auto")
        self.assertEqual(common.setting({}, "correction.claude.model"), "opus")             # 1.1.0 起
        self.assertEqual(common.setting({}, "correction.claude.effort"), "medium")   # C4
        self.assertEqual(common.setting({}, "correction.openai.model"), "gpt-6.1-sol")     # 1.1.0 起
        self.assertEqual(common.setting({}, "correction.openai.effort"), "low")
        self.assertEqual(common.setting({}, "correction.corrections_auto.mode"), "off")   # 1.1.0 起
        self.assertEqual(common.setting({}, "correction.corrections_auto.models"), ["claude:sonnet", "claude:opus", "openai:gpt-6.1-sol"])   # 1.1.0 起
        self.assertEqual(common.setting({}, "correction.claude.api_model_ids.sonnet"), "claude-sonnet-5-5")
        cfg = {"punctuation": {"paragraph_gap": 3.5}, "correction": {"claude": {"model": "opus"}}}
        self.assertEqual(common.setting(cfg, "punctuation.paragraph_gap"), 3.5)
        self.assertEqual(common.setting(cfg, "punctuation.paragraph_max_chars"), 200)  # 區塊在、鍵不在 → 預設
        self.assertEqual(common.setting(cfg, "correction.claude.model"), "opus")
        self.assertEqual(common.setting(cfg, "correction.claude.effort"), "medium")    # 巢狀區塊在、鍵不在 → 預設
        self.assertIsNone(common.setting({}, "correction.claude.cli_path"))
        with self.assertRaises(KeyError):
            common.setting({}, "no.such.key")
        with self.assertRaises(KeyError):
            common.setting({}, "claude.enabled")   # 舊鍵已改名（1.1.0）

    def test_no_write_back(self):
        self.write(V100_CONFIG)
        before = Path(self.home, "config.json").read_bytes()
        common.setting(common.load_config(), "punctuation.enabled")
        self.assertEqual(Path(self.home, "config.json").read_bytes(), before)

    def test_returns_copy(self):
        v = common.setting({}, "correction.claude.api_model_ids")
        v["sonnet"] = "x"
        self.assertEqual(common.DEFAULTS["correction"]["claude"]["api_model_ids"]["sonnet"], "claude-sonnet-5-5")


class Upgrade(TempHome):
    def check_upgrade(self, old: dict, **kw):
        self.write(old)
        new = common.upgrade_config(**kw)
        on_disk = json.loads(Path(self.home, "config.json").read_text(encoding="utf-8"))
        self.assertEqual(new, on_disk)
        for k, v in old.items():
            if k not in ("runtime_version", "claude"):
                self.assertEqual(on_disk[k], v, f"舊鍵 {k} 被改了")
        self.assertEqual(on_disk["runtime_version"], _testenv.VERSION)
        for k in ("punctuation", "opencc_keep", "correction"):
            self.assertIn(k, on_disk)
        self.assertNotIn("claude", on_disk)
        return on_disk

    def test_from_v100(self):
        cfg = self.check_upgrade(copy.deepcopy(V100_CONFIG))
        self.assertEqual(cfg["punctuation"], common.DEFAULTS["punctuation"])
        self.assertEqual(cfg["correction"], common.DEFAULTS["correction"])
        self.assertIs(cfg["correction"]["enabled"], False)

    def test_keeps_user_values(self):
        old = dict(copy.deepcopy(V100_CONFIG), runtime_version="1.0.9",
                   punctuation={"enabled": False, "paragraph_gap": 3.0},
                   correction={"enabled": True, "openai": {"model": "gpt-6.1-terra"}})
        cfg = self.check_upgrade(old)
        self.assertEqual(cfg["punctuation"], {"enabled": False, "paragraph_gap": 3.0})   # 整塊存在就不補
        self.assertEqual(cfg["correction"], {"enabled": True, "openai": {"model": "gpt-6.1-terra"}})
        self.assertEqual(common.setting(cfg, "punctuation.paragraph_max_chars"), 200)   # 讀取時由預設補
        self.assertEqual(common.setting(cfg, "correction.openai.effort"), "low")

    def test_installer_answer(self):
        self.write(copy.deepcopy(V100_CONFIG))
        cfg = common.upgrade_config(correction={"enabled": True, "provider": "openai",
                                                "openai": {"model": "gpt-6.1-terra", "effort": "medium"}})
        self.assertIs(cfg["correction"]["enabled"], True)
        self.assertEqual(cfg["correction"]["provider"], "openai")
        self.assertEqual(cfg["correction"]["openai"], {"model": "gpt-6.1-terra", "effort": "medium", "cli_path": None})
        self.assertEqual(cfg["correction"]["claude"]["model"], "opus")         # 巢狀合併，不整塊覆蓋（1.1.0 起預設 opus）
        cfg = common.upgrade_config(correction={"enabled": False})               # 重新安裝改答案
        self.assertIs(cfg["correction"]["enabled"], False)
        self.assertEqual(cfg["correction"]["openai"]["model"], "gpt-6.1-terra")

    def test_migrate_s2a_claude_block(self):
        # 1.1.0 開發期（S2a）寫進 config.json 的 claude 區塊 → correction
        old = dict(copy.deepcopy(V100_CONFIG), claude={
            "enabled": True, "channel": "cli", "model": "opus", "effort": "medium", "chunk_chars": 3000,
            "timeout_sec": 600, "confirm_over_minutes": 90, "cli_path": None,
            "api_model_ids": {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}})
        cfg = self.check_upgrade(old)
        c = cfg["correction"]
        self.assertIs(c["enabled"], True)
        self.assertEqual(c["provider"], "claude")          # 舊設定明確開啟 Claude：不讓 auto 改送 OpenAI
        self.assertEqual((c["chunk_chars"], c["confirm_over_minutes"]), (3000, 90))
        self.assertEqual((c["claude"]["model"], c["claude"]["effort"]), ("opus", "medium"))
        self.assertEqual(c["openai"], common.DEFAULTS["correction"]["openai"])
        self.assertEqual(c["corrections_auto"]["mode"], "off")

    def test_migrate_disabled_claude_block_keeps_auto(self):
        old = dict(copy.deepcopy(V100_CONFIG), claude={"enabled": False, "channel": "cli", "model": "sonnet"})
        cfg = self.check_upgrade(old)
        self.assertEqual(cfg["correction"]["provider"], "auto")
        self.assertIs(cfg["correction"]["enabled"], False)

    def test_migrate_when_correction_exists(self):
        old = dict(copy.deepcopy(V100_CONFIG), claude={"enabled": True, "model": "opus"},
                   correction={"enabled": False})
        cfg = self.check_upgrade(old)
        self.assertEqual(cfg["correction"], {"enabled": False})      # 新區塊優先，舊鍵只刪除

    def test_idempotent(self):
        self.write(dict(copy.deepcopy(V100_CONFIG), claude={"enabled": True}))
        a = common.upgrade_config()
        b = common.upgrade_config()
        self.assertEqual(a, b)

    def test_no_config(self):
        cfg = common.upgrade_config()
        self.assertEqual(cfg["runtime_version"], _testenv.VERSION)

    @unittest.skipUnless(os.environ.get("MMP_V100_CONFIG"), "沒有設定 MMP_V100_CONFIG（真實 1.0.0 config.json 的副本）")
    def test_real_v100_copy(self):
        old = json.loads(Path(os.environ["MMP_V100_CONFIG"]).read_text(encoding="utf-8"))
        self.assertNotIn("punctuation", old)
        cfg = self.check_upgrade(old)
        print(f"\n  真實 1.0.0 config 副本：舊鍵 {sorted(old)} 保留；新增 "
              f"{sorted(set(cfg) - set(old))}")


class ForceKeepsBench(TempHome):
    """〔1.1.0〕setup_backend.py --force（不測速）保留 config.json 既有的 bench、detected_at；真的重新偵測時照常覆寫。

    下載、硬體盤點、測速都換成假的（不下載、不載入模型、不碰已安裝的 runtime）。
    """
    INV = {"os": "win32", "machine": "AMD64", "cpu": "Example CPU", "video": [], "nvidia": [],
           "openvino": {"NPU": "Example NPU", "CPU": "Example CPU"}}

    def setUp(self):
        super().setUp()
        import types
        from unittest import mock
        import setup_backend as sb
        self.sb = sb
        fake_dl = types.SimpleNamespace(ensure_common=lambda: None, ensure_punct=lambda archive=None: True,
                                        ensure_whisper=lambda *a, **k: None, remove_backend_models=lambda be: None)
        self.patches = [mock.patch.dict(sys.modules, {"download_models": fake_dl}),
                        mock.patch.object(sb, "inventory", lambda: dict(self.INV)),
                        mock.patch.object(sb, "load_sample", lambda seconds: ([0.0] * 16000, 16000)),
                        mock.patch.object(sb, "bench_one", lambda be, dev, ct, audio, sr, model: {
                            "rtf": {"NPU": 0.04, "CPU": 0.09}[dev], "load_s": 1, "asr_s": 1, "text": "假的辨識結果一二三四五六七八"})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        super().tearDown()

    def main(self, *argv):
        import contextlib
        import io
        with mock_argv(["setup_backend.py", *argv]), contextlib.redirect_stdout(io.StringIO()):
            self.sb.main()
        return json.loads(Path(self.home, "config.json").read_text(encoding="utf-8"))

    def test_detection_fields(self):
        old = {"bench": [{"backend": "openvino", "device": "NPU", "rtf": 0.05, "ok": True}], "detected_at": "2026-11-01T08:00:00"}
        self.assertEqual(self.sb.detection_fields([], True, old), {"bench": old["bench"], "detected_at": old["detected_at"]})
        self.assertEqual(self.sb.detection_fields([], True, {}), {"bench": [], "detected_at": None})
        self.assertEqual(self.sb.detection_fields([], True, {"bench": []}), {"bench": [], "detected_at": None})
        new = self.sb.detection_fields([{"backend": "openvino", "device": "CPU", "compute_type": "default", "rtf": 0.1,
                                         "ok": True, "text": "x", "desc": "d"}], False, old)
        self.assertEqual(new["bench"], [{"backend": "openvino", "device": "CPU", "compute_type": "default", "rtf": 0.1,
                                         "ok": True, "error": None}])
        self.assertNotEqual(new["detected_at"], old["detected_at"])

    def test_force_keeps_existing_bench(self):
        self.write(V100_CONFIG)
        cfg = self.main("--force", "openvino:NPU")
        self.assertEqual(cfg["bench"], V100_CONFIG["bench"])
        self.assertEqual(cfg["detected_at"], V100_CONFIG["detected_at"])
        self.assertEqual((cfg["backend"], cfg["device"]), ("openvino", "NPU"))
        self.assertEqual(cfg["profiles"], V100_CONFIG["profiles"])                  # 同一後端的 Breeze profile 保留

    def test_force_without_config(self):
        cfg = self.main("--force", "openvino:CPU")
        self.assertEqual((cfg["bench"], cfg["detected_at"]), ([], None))
        self.assertEqual((cfg["backend"], cfg["device"]), ("openvino", "CPU"))

    def test_redetect_overwrites(self):
        self.write(V100_CONFIG)
        cfg = self.main()
        self.assertEqual([(r["device"], r["rtf"]) for r in cfg["bench"]], [("NPU", 0.04), ("CPU", 0.09)])
        self.assertNotEqual(cfg["detected_at"], V100_CONFIG["detected_at"])
        self.assertEqual((cfg["backend"], cfg["device"]), ("openvino", "NPU"))


def mock_argv(argv):
    from unittest import mock
    return mock.patch.object(sys, "argv", argv)



# 〔2.0.0〕U-1（規格 §9.1、§10.2）：1.0.0／1.1.0／1.2.2 的 config.json 經 upgrade_config()
V2 = _testenv.VER >= (2, 0, 0)
V21 = _testenv.VER >= (2, 1, 0)
V22 = _testenv.VER >= (2, 2, 0)
# 〔2.1.0〕升級時另補 html 區塊（規格 2.1.0 §6.1）；2.0.x 只補 2.0 的五塊；〔2.2.0〕另補 reference 區塊（規格 2.2.0 §8.1）
V2_BLOCKS = ["content_type", "diarization", "keyframes", "content_types", "subtitles"] + (["html"] if V21 else []) + \
    (["reference", "consistency"] if V22 else [])   # 〔2.2.0〕consistency：全文用字統一
V110_CONFIG = dict(copy.deepcopy(V100_CONFIG), runtime_version="1.1.0",
                   punctuation={"enabled": True, "model": "ct-transformer-int8", "paragraph_gap": 2.5,
                                "paragraph_max_chars": 200, "whisper_density": 20},
                   opencc_keep={"enabled": False},
                   correction={"enabled": False, "provider": "claude", "channel": "cli", "chunk_chars": 3500,
                               "timeout_sec": 600, "confirm_over_minutes": 120, "claude": {"model": "sonnet"}})
V122_CONFIG = dict(copy.deepcopy(V110_CONFIG), runtime_version="1.2.2",
                   minutes={"ask_default": False, "provider": "openai", "channel": "cli", "chunk_chars": 9000,
                            "timeout_sec": 900, "claude": {"model": "opus", "effort": "medium"},
                            "openai": {"model": "gpt-6.1-sol", "effort": "low"}})


@unittest.skipUnless(V2, "2.0.0 才有")
class UpgradeTo200(TempHome):
    def upgrade(self, before):
        self.write(before)
        after = common.upgrade_config()
        self.assertEqual(json.loads(Path(self.home, "config.json").read_text(encoding="utf-8")), after)
        return after

    def test_from_each_version(self):
        for name, before, extra in (("1.0.0", V100_CONFIG, ["punctuation", "opencc_keep", "correction", "minutes"]),
                                    ("1.1.0", V110_CONFIG, ["minutes"]), ("1.2.2", V122_CONFIG, [])):
            with self.subTest(version=name):
                after = self.upgrade(copy.deepcopy(before))
                for k, v in before.items():                         # 舊鍵與值不變
                    if k != "runtime_version":
                        self.assertEqual(after[k], v, k)
                for k in V2_BLOCKS:                                  # 新塊補上＝預設值
                    self.assertEqual(after[k], common.DEFAULTS[k], k)
                self.assertEqual(after["diarization"]["pyannote"]["status"], "none")
                self.assertEqual(after["content_types"]["panel"]["diarize_engine"], "sherpa")   # 〔2.0.0〕座談預設 sherpa
                self.assertEqual(common.type_setting(after, "panel", "diarize_engine"), "sherpa")
                self.assertEqual(common.type_setting(after, "meeting", "diarize_engine"), "auto")
                self.assertEqual(after["runtime_version"], _testenv.VERSION)   # 〔2.0.1〕取測試的版本目錄
                self.assertEqual(common.added_config_keys(before, after), extra + V2_BLOCKS)

    def test_message_matches_spec(self):
        after = self.upgrade(copy.deepcopy(V122_CONFIG))
        added = common.added_config_keys(V122_CONFIG, after)
        msg = "config.json 已補上新版設定鍵：{0}（既有的值不變）".format("、".join(added))
        self.assertEqual(msg, "config.json 已補上新版設定鍵：content_type、diarization、keyframes、content_types、subtitles"
                         + ("、html" if V21 else "") + ("、reference、consistency" if V22 else "") + "（既有的值不變）")

    def test_partial_blocks(self):
        before = dict(copy.deepcopy(V122_CONFIG), runtime_version="2.0.0",
                      diarization={"engine": "sherpa", "cluster_threshold": 0.85, "pyannote": {"status": "ready"}},
                      content_types={"course": {"cluster_threshold": 1.1}},
                      subtitles={"uncertain": "mark"})
        after = self.upgrade(copy.deepcopy(before))
        d = after["diarization"]
        self.assertEqual((d["engine"], d["cluster_threshold"], d["pyannote"]["status"]), ("sherpa", 0.85, "ready"))
        self.assertEqual(d["min_vram_mib"], 4096)                               # 缺的鍵逐鍵補
        self.assertEqual(d["pyannote"]["timeout_min_sec"], 600)
        self.assertEqual(after["content_types"], {"course": {"cluster_threshold": 1.1}})   # 使用者增刪的區塊不補
        self.assertEqual(common.type_setting(after, "panel", "diarize_engine"), "sherpa")   # 〔2.0.0〕沒有 panel → 共用鍵（此例 sherpa）
        self.assertEqual(after["subtitles"]["uncertain"], "mark")
        self.assertEqual(after["subtitles"]["max_line_chars"], 16)
        added = common.added_config_keys(before, after)
        for k in ("content_type", "keyframes", "diarization.min_vram_mib", "diarization.pyannote.timeout_min_sec",
                  "subtitles.max_line_chars"):
            self.assertIn(k, added)
        self.assertFalse([k for k in added if k.startswith("content_types")])
        self.assertNotIn("diarization.engine", added)
        again = self.upgrade(copy.deepcopy(after))                               # 再升級一次：沒有變化
        self.assertEqual(again, after)
        self.assertEqual(common.added_config_keys(after, again), [])

    def test_new_defaults(self):
        self.assertEqual(common.setting({}, "diarization.engine"), "auto")
        self.assertEqual(common.setting({}, "diarization.cluster_threshold"), 0.9)
        self.assertEqual(common.setting({}, "diarization.minor_speaker_note_sec"), 10)
        self.assertEqual(common.setting({}, "content_type.default"), "meeting")
        self.assertIs(common.setting({}, "content_type.remember_last"), True)
        self.assertEqual(common.setting({}, "keyframes.max_frames"), 60)
        self.assertEqual(common.state_path(), Path(self.home, "state.json"))
        self.assertEqual(common.templates_dir(), Path(self.home, "templates"))
        self.assertEqual(common.pyannote_model_dir(), Path(self.home, "models", "pyannote-speaker-diarization-community-1"))
        self.assertEqual(common.gpu_diar_python().parent.parent, Path(self.home, "venv-gpu-diar"))


@unittest.skipUnless(V21, "2.1.0 才有")
class UpgradeTo210(TempHome):
    """H-11（規格 2.1.0 §6.1）：upgrade_config() 補 html 區塊；只有部分鍵時逐鍵補；不認得的值保留原樣，讀取時用預設並印提示。"""

    def upgrade(self, before):
        self.write(before)
        return common.upgrade_config()

    def test_defaults(self):
        self.assertEqual(common.DEFAULTS["html"], {"enabled": True, "media": "auto", "theme": "dark"})
        for k, v in common.DEFAULTS["html"].items():
            self.assertEqual(common.html_setting({}, k), v)

    def test_no_html_block(self):
        before = dict(copy.deepcopy(V122_CONFIG), runtime_version="2.0.2")
        after = self.upgrade(copy.deepcopy(before))
        self.assertEqual(after["html"], common.DEFAULTS["html"])
        self.assertIs(after["html"]["enabled"], True)                          # 〔2.1.0〕升級上來的使用者也預設產出（規格 2.1.0 §6.1）
        self.assertEqual(after["runtime_version"], _testenv.VERSION)
        self.assertIn("html", common.added_config_keys(before, after))

    def test_partial_keys(self):
        before = dict(copy.deepcopy(V122_CONFIG), runtime_version="2.0.2", html={"enabled": False})
        after = self.upgrade(copy.deepcopy(before))
        self.assertEqual(after["html"], {"enabled": False, "media": "auto", "theme": "dark"})   # 既有值不變、缺的逐鍵補
        self.assertEqual([k for k in common.added_config_keys(before, after) if k.startswith("html")], ["html.media", "html.theme"])
        again = self.upgrade(copy.deepcopy(after))
        self.assertEqual(again, after)

    def test_unknown_values(self):
        before = dict(copy.deepcopy(V122_CONFIG), html={"enabled": "yes", "media": "yes", "theme": "blue"})
        after = self.upgrade(copy.deepcopy(before))
        self.assertEqual(after["html"], {"enabled": "yes", "media": "yes", "theme": "blue"})   # 使用者寫的值不改
        msgs = []
        self.assertIs(common.html_setting(after, "enabled", warn=msgs.append), True)
        self.assertEqual(common.html_setting(after, "media", warn=msgs.append), "auto")
        self.assertEqual(common.html_setting(after, "theme", warn=msgs.append), "dark")
        self.assertEqual(msgs, ["[!] html.enabled 的值 yes 不認得，改用 true", "[!] html.media 的值 yes 不認得，改用 auto",
                                "[!] html.theme 的值 blue 不認得，改用 dark"])
        import io
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(common.html_setting({"html": {"media": 1}}, "media"), "auto")
        self.assertIn("[!] html.media 的值 1 不認得，改用 auto", err.getvalue())
        self.assertIs(common.html_setting({"html": {"enabled": False}}, "enabled", warn=msgs.append), False)


if __name__ == "__main__":
    unittest.main()
