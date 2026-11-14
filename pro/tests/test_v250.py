"""〔2.5.0〕Breeze-ASR-26「台語／華台混講」選項（規格 2.5.0）。不呼叫任何模型、不下載任何東西、不需要 GPU。

- Models：WHISPER_MODELS 三個後端的 breeze26（ct2、openvino 有；mlx 沒有）、目錄名稱、model_supported()；
  whisper_ready() 對半成品（缺 tokenizer.json、缺 model.bin、只有暫存資料夾）判定未就緒，mlx 一律未就緒；顯示名稱；
  breeze26 的分段標點同 Breeze-ASR-25（整段交給 CT-Transformer）
- Convert：breeze.convert_ct2_26()／ensure()（下載、雜湊、暫時 venv、轉換器都用假的）：成功時才搬進 models/、記錄來源與雜湊、
  暫存資料夾刪掉；磁碟空間不足（不下載）、雜湊不符、大小不符、轉換器失敗、少 tokenizer.json → 丟錯、models/ 沒有半成品、
  暫存資料夾刪掉；已有的完整模型在轉換失敗時不被動到；mlx 不提供
- SetupBackend：setup_backend.main()（假下載、假實測）：--breeze26 只新增 profiles.breeze26、profiles.breeze 與其他鍵不變；
  沒有 --breeze26（＝-NoBreeze26）時既有的 profiles.breeze26 保留；--breeze26 失敗不中止安裝（exit 0、breeze26_error）、
  config 不變；--breeze26-only 失敗 exit 1；mlx 略過；--remove-breeze26 只移除 26
- InstallerPs：install.ps1 的 Breeze-ASR-26 詢問區塊（PowerShell 7／5.1 實跑，Read-Host 用假的）：不指定時問、預設 N、
  y 才裝；-Breeze26／-NoBreeze26 不問；兩個都給＝不裝；已裝過不問、保留；轉成 setup_backend.py --breeze26
- InstallerSh：install.sh 的 --breeze26／--no-breeze26（macOS 不提供：不問、不轉給 setup_backend.py）
- Vad：CT2Backend 的 vad_filter 只有 breeze26（ct2）而且有說話者分離時開；略過說話者分離、turbo、Breeze-ASR-25 都關
- Transcribe：transcribe.main()（假 backends.create、假說話者分離）：--whisper breeze26 用 profiles.breeze26 的後端與精度、語言 zh、
  run_log 的 asr 檢查點與 runs.jsonl 的 asr_model、meta.model；有說話者分離時 vad_filter 開（多一欄）、略過時關並印雜訊提醒；
  turbo 與 25 沒有 vad_filter 欄、沒有提醒
- Estimate：auto_minutes --estimate-only 對 breeze26 的輸出資料夾照常預估（與 ASR 模型無關）
- EntryStatic、Docs：入口改成「辨識模型」選擇題（ask_whisper）、SKILL、README、THIRD-PARTY-NOTICES
入口選擇題的四種安裝組合在 entry_harness.py 的 v25_scenarios（PowerShell 7／5.1／Git Bash 實跑）。
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402

V25 = _testenv.VER >= (2, 5, 0)
VD = _testenv.VERSION_DIR
INSTALL_PS1 = VD / "install.ps1"
INSTALL_SH = VD / "install.sh"
SKILL = VD / "payload" / "skill" / "meeting-minutes-pro" / "SKILL.md"
GIT_BASH = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))
OV26 = True    # 〔2.5.0〕OpenVINO（CPU）實測可用 → 提供（規格 2.5.0 §2.1）

if V25:
    import common  # noqa: E402


def _shells():
    return [n for n in ("pwsh", "powershell") if shutil.which(n)]


class _Home(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-v250-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_cfg(self, cfg):
        (self.home / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    def read_cfg(self):
        return json.loads((self.home / "config.json").read_text(encoding="utf-8"))


@unittest.skipUnless(V25, "2.5.0 才有")
class Models(_Home):
    def test_registry(self):
        wm = common.WHISPER_MODELS
        self.assertEqual(wm["ct2"]["breeze26"], "local/breeze-asr-26-ct2")
        self.assertEqual("breeze26" in wm["openvino"], OV26)
        self.assertNotIn("breeze26", wm["mlx"])
        self.assertEqual(wm["ct2"]["breeze"], "shdennlin/breeze-asr-25-ct2")              # 25 不變
        self.assertEqual(common.whisper_dir("ct2", "breeze26"), self.home / "models" / "ct2" / "breeze-asr-26-ct2")
        self.assertNotEqual(common.whisper_dir("ct2", "breeze26"), common.whisper_dir("ct2", "breeze"))   # 與 25 分開
        self.assertTrue(common.model_supported("ct2", "breeze26"))
        self.assertFalse(common.model_supported("mlx", "breeze26"))
        self.assertEqual(common.BREEZE26_SOURCE, "MediaTek-Research/Breeze-ASR-26")
        self.assertRegex(common.BREEZE26_REVISION, r"^[0-9a-f]{40}$")
        self.assertEqual(sum(s for s, _ in common.BREEZE26_WEIGHTS.values()), 6173369672)
        self.assertEqual(common.BREEZE_FAMILY, ("breeze", "breeze26"))

    def test_ready_partial(self):
        d = common.whisper_dir("ct2", "breeze26")
        self.assertFalse(common.whisper_ready("ct2", "breeze26"))
        d.mkdir(parents=True)
        (d / "model.bin").write_bytes(b"x")
        self.assertFalse(common.whisper_ready("ct2", "breeze26"), "缺 tokenizer.json")
        (d / "model.bin").unlink()
        (d / "tokenizer.json").write_text("{}", encoding="utf-8")
        self.assertFalse(common.whisper_ready("ct2", "breeze26"), "缺 model.bin")
        (d / "model.bin").write_bytes(b"x")
        self.assertTrue(common.whisper_ready("ct2", "breeze26"))
        # 轉換中的暫存資料夾（_convert-breeze26/out）有完整檔也不算
        shutil.rmtree(d)
        w = self.home / "_convert-breeze26" / "out"
        w.mkdir(parents=True)
        (w / "model.bin").write_bytes(b"x")
        (w / "tokenizer.json").write_text("{}", encoding="utf-8")
        self.assertFalse(common.whisper_ready("ct2", "breeze26"))

    def test_mlx_never_ready(self):
        d = self.home / "models" / "mlx" / "breeze26"
        d.mkdir(parents=True)
        (d / "config.json").write_text("{}", encoding="utf-8")
        (d / "weights.safetensors").write_bytes(b"x")
        self.assertFalse(common.whisper_ready("mlx", "breeze26"))

    def test_display_and_punct(self):
        import punctuate as pu
        import transcribe as tr
        self.assertEqual(tr.asr_display_name("breeze26"), "Breeze-ASR-26（台語）")
        self.assertEqual(tr.asr_display_name("breeze"), "Breeze-ASR-25")
        segs = [{"start": 0.0, "end": 2.0, "speaker": "S1", "text": "今天開會。我們先看預算，然後再看人力。"},
                {"start": 2.0, "end": 4.0, "speaker": "S1", "text": "好的。"}]
        paras = [{"segments": (0, 1), "speaker": "S1"}]

        class P:
            calls = 0

            def __call__(self, texts):
                P.calls += 1
                return texts
        for alias, ct in (("breeze26", True), ("breeze", True), ("turbo", False)):
            s2 = [dict(x) for x in segs]
            r = pu.punctuate_paragraphs([dict(p) for p in paras], s2, alias, None, 20)
            self.assertEqual(r["by_source"]["none"] > 0, ct, (alias, r))   # 沒有標點模型：Breeze 家族整段 none，turbo 沿用 Whisper

    def test_missing_message(self):
        import backends
        with self.assertRaises(FileNotFoundError) as cm:
            backends.create("ct2", "breeze26", "cuda")
        self.assertIn("setup_backend.py --breeze26-only", str(cm.exception))
        with self.assertRaises(FileNotFoundError) as cm:
            backends.create("mlx", "breeze26", "gpu")
        self.assertIn("本版不提供 mlx 後端的 Breeze-ASR-26", str(cm.exception))


# ---------------------------------------------------------------- 轉換（全部用假的）
def _fake_weights(names_sizes: dict) -> tuple:
    """假的官方權重內容 → (檔名: bytes, 檔名: (大小, sha256))。"""
    data = {n: (n * 7).encode() for n in names_sizes}
    meta = {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in data.items()}
    return data, meta


@unittest.skipUnless(V25, "2.5.0 才有")
class Convert(_Home):
    NAMES = {"model-00001-of-00002.safetensors": 0, "model-00002-of-00002.safetensors": 0}

    def setUp(self):
        super().setUp()
        import breeze
        self.bz = breeze
        self.data, self.meta = _fake_weights(self.NAMES)
        self.calls = []
        self.fail = None          # converter｜tokenizer｜download_bad_hash｜download_bad_size
        self.sp = [mock.patch.object(breeze, "BREEZE26_WEIGHTS", self.meta),
                   mock.patch.object(breeze, "download_official_26", self.fake_download),
                   mock.patch.object(breeze, "_make_venv", self.fake_venv),
                   mock.patch.object(breeze, "_tool_versions", lambda vpy, mods: {"ctranslate2": "fake"}),
                   mock.patch.object(breeze.subprocess, "run", self.fake_run),
                   mock.patch.dict(sys.modules, {"ctranslate2": types.SimpleNamespace(__version__="9.9.9")}),
                   contextlib.redirect_stdout(io.StringIO())]
        for p in self.sp:
            p.__enter__()

    def tearDown(self):
        for p in reversed(self.sp):
            p.__exit__(None, None, None)
        super().tearDown()

    def fake_download(self, dst: Path, env: dict):
        self.calls.append(("download", str(dst)))
        dst.mkdir(parents=True, exist_ok=True)
        for n, b in self.data.items():
            if self.fail == "download_bad_hash" and n.startswith("model-00002"):
                b = b[:-1] + b"!"
            if self.fail == "download_bad_size" and n.startswith("model-00002"):
                b = b + b"!"
            (dst / n).write_bytes(b)
        for n in ("config.json", "vocab.json"):
            (dst / n).write_text("{}", encoding="utf-8")

    def fake_venv(self, work, pkgs, env, what):
        self.calls.append(("venv", pkgs))
        v = work / "venv"
        v.mkdir(parents=True)
        return v

    def fake_run(self, cmd, **kw):
        cmd = [str(c) for c in cmd]
        self.calls.append(("run", cmd))
        if "ct2-transformers-converter" in Path(cmd[0]).name:
            if self.fail == "converter":
                raise subprocess.CalledProcessError(1, cmd)
            out = Path(cmd[cmd.index("--output_dir") + 1])
            out.mkdir(parents=True)
            for n in ("model.bin", "config.json", "vocabulary.json", "preprocessor_config.json"):
                (out / n).write_bytes(b"converted " + n.encode())
        elif "-c" in cmd and "WhisperTokenizerFast" in cmd[cmd.index("-c") + 1]:
            if self.fail != "tokenizer":
                Path(cmd[-1]).write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def dst(self):
        return self.home / "models" / "ct2" / "breeze-asr-26-ct2"

    def assert_clean(self):
        self.assertFalse((self.home / "_convert-breeze26").exists(), "暫存資料夾（原始權重、暫時 venv）已刪除")

    def test_success(self):
        self.bz.ensure("ct2", "int8_float16", "breeze26")
        self.assertTrue(common.whisper_ready("ct2", "breeze26"))
        src = json.loads((self.dst() / "breeze26-source.json").read_text(encoding="utf-8"))
        self.assertEqual((src["revision"], src["quantization"], src["license"]), (common.BREEZE26_REVISION, "int8_float16", "Apache-2.0"))
        self.assertEqual(src["weights_sha256"], {n: m[1] for n, m in self.meta.items()})
        self.assertEqual(src["model_bin_sha256"], hashlib.sha256(b"converted model.bin").hexdigest())
        conv = next(c[1] for c in self.calls if c[0] == "run" and "ct2-transformers-converter" in c[1][0])
        self.assertEqual(conv[conv.index("--quantization") + 1], "int8_float16")
        self.assertIn("--low_cpu_mem_usage", conv)
        pkgs = next(c[1] for c in self.calls if c[0] == "venv")
        self.assertIn("ctranslate2==9.9.9", pkgs)                       # 對齊主環境的 CTranslate2
        self.assertIn("transformers==4.57.6", pkgs)
        self.assert_clean()
        n = len(self.calls)
        self.bz.ensure("ct2", "int8_float16", "breeze26")                # 已存在：不再下載
        self.assertEqual(len(self.calls), n)

    def test_quantization_rule_same_as_25(self):
        for ct, want in (("float16", "float16"), ("int8_float32", "int8"), ("default", "int8"), ("int8", "int8")):
            with self.subTest(ct=ct):
                shutil.rmtree(self.dst(), ignore_errors=True)
                self.calls.clear()
                self.bz.ensure("ct2", ct, "breeze26")
                conv = next(c[1] for c in self.calls if c[0] == "run" and "ct2-transformers-converter" in c[1][0])
                self.assertEqual(conv[conv.index("--quantization") + 1], want)
                self.assertEqual(self.bz.ct2_subfolder(ct), want)

    def _fails(self, fail, msg):
        self.fail = fail
        with self.assertRaises(Exception) as cm:
            self.bz.ensure("ct2", "int8_float16", "breeze26")
        self.assertFalse(self.dst().exists(), "models/ 沒有半成品")
        self.assertFalse(common.whisper_ready("ct2", "breeze26"))
        self.assert_clean()
        if msg:
            self.assertIn(msg, str(cm.exception))
        return cm.exception

    def test_converter_fails(self):
        self._fails("converter", None)

    def test_tokenizer_missing(self):
        self._fails("tokenizer", "轉換結果缺少 tokenizer.json")

    def test_bad_hash(self):
        self._fails("download_bad_hash", "SHA-256 不符")
        self.assertFalse(any(c[0] == "venv" for c in self.calls), "雜湊不符就不建轉換環境")

    def test_bad_size(self):
        self._fails("download_bad_size", "大小不符")

    def test_disk_space(self):
        du = types.SimpleNamespace(total=10**12, used=0, free=5 * 10**9)
        with mock.patch.object(self.bz.shutil, "disk_usage", return_value=du):
            ex = self._fails(None, "磁碟空間不足")
        self.assertIsInstance(ex, self.bz.Breeze26Error)
        self.assertIn("需要約 10 GB", str(ex))
        self.assertIn("6.2 GB", str(ex))
        self.assertIn("setup_backend.py --breeze26-only", str(ex))
        self.assertFalse(any(c[0] == "download" for c in self.calls), "空間不夠就不下載")

    def test_existing_model_kept_on_failure(self):
        self.bz.ensure("ct2", "int8_float16", "breeze26")
        before = {p.name: p.read_bytes() for p in self.dst().iterdir()}
        with mock.patch.object(self.bz, "convert_ct2_26", side_effect=AssertionError("已存在就不該轉換")):
            self.bz.ensure("ct2", "int8_float16", "breeze26")
        self.fail = "converter"
        with self.assertRaises(subprocess.CalledProcessError):
            self.bz.convert_ct2_26("int8_float16")                       # 強制重轉失敗：既有完整模型不動
        self.assertEqual({p.name: p.read_bytes() for p in self.dst().iterdir()}, before)
        self.assert_clean()

    def test_mlx_not_provided(self):
        with self.assertRaises(self.bz.Breeze26Error) as cm:
            self.bz.ensure("mlx", "default", "breeze26")
        self.assertIn("本版不提供 mlx", str(cm.exception))
        self.assertEqual(self.calls, [])

    def test_breeze25_path_unchanged(self):
        with mock.patch.object(self.bz, "fetch_ct2") as f, mock.patch.object(self.bz, "convert_ct2_26") as c26:
            with self.assertRaises(RuntimeError):            # 假的 fetch 沒有產生檔案 → 準備失敗（照 2.4.1）
                self.bz.ensure("ct2", "int8_float16")
        f.assert_called_once_with("int8_float16")
        c26.assert_not_called()

    def test_download_models_routes(self):
        import download_models as dl
        with mock.patch.object(self.bz, "ensure") as e:
            dl.ensure_whisper("ct2", "breeze26", "int8_float16")
            dl.ensure_whisper("ct2", "breeze", "int8_float16")
        self.assertEqual(e.call_args_list, [mock.call("ct2", "int8_float16", "breeze26"), mock.call("ct2", "int8_float16", "breeze")])


# ---------------------------------------------------------------- setup_backend.py
def fake_dl(fail=None):
    m = types.ModuleType("download_models")
    m.calls = []
    m.ensure_common = lambda: m.calls.append("common")
    m.ensure_punct = lambda archive=None: True

    def ensure_whisper(backend, model, compute_type="default"):
        m.calls.append(("whisper", backend, model, compute_type))
        if model == "breeze26" and fail:
            raise RuntimeError(fail)
    m.ensure_whisper = ensure_whisper
    m.remove_backend_models = lambda be: m.calls.append(("remove", be))
    return m


@unittest.skipUnless(V25, "2.5.0 才有")
class SetupBackend(_Home):
    B25 = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "rtf": 0.0418}
    OLD = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "whisper": "turbo",
           "bench": [{"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "rtf": 0.02, "ok": True}],
           "detected_at": "2026-11-01T10:00:00", "glossary_note": "保留", "privacy": {"local_only": False},
           "profiles": {"breeze": B25}}

    def setUp(self):
        super().setUp()
        import numpy as np
        import setup_backend
        self.sb, self.np = setup_backend, np

    def run_main(self, cfg, *argv, fail=None):
        if cfg is not None:
            self.write_cfg(cfg)
        dl = fake_dl(fail)
        inv = {"cpu": "fake", "machine": "AMD64", "video": [], "openvino": {}, "nvidia": []}
        out = io.StringIO()
        code = 0
        with mock.patch.dict(sys.modules, {"download_models": dl}), \
                mock.patch.object(self.sb, "inventory", return_value=inv), \
                mock.patch.object(self.sb, "load_sample", return_value=(self.np.zeros(16000, dtype="float32"), 16000)), \
                mock.patch.object(self.sb, "bench_one", return_value={"rtf": 0.0661, "text": "這是測試用的一段很長的文字輸出"}), \
                mock.patch.object(sys, "argv", ["setup_backend.py", *argv]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                self.sb.main()
            except SystemExit as ex:
                code = ex.code
        lines = out.getvalue().strip().splitlines()
        last = json.loads(lines[-1]) if lines and lines[-1].startswith("{") else None
        return code, last, out.getvalue(), dl

    def test_add_breeze26_keeps_others(self):
        code, last, _, dl = self.run_main(self.OLD, "--force", "ct2:cuda", "--breeze26")
        self.assertEqual(code, 0)
        cfg = self.read_cfg()
        self.assertEqual(cfg["profiles"]["breeze"], self.B25, "profiles.breeze 不變")
        self.assertEqual(cfg["profiles"]["breeze26"], {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16",
                                                       "rtf": 0.0661})
        for k in ("backend", "device", "compute_type", "bench", "detected_at", "glossary_note", "privacy"):
            self.assertEqual(cfg[k], self.OLD[k], k)
        self.assertEqual(last["breeze26"], cfg["profiles"]["breeze26"])
        self.assertIsNone(last["breeze26_error"])
        self.assertIn(("whisper", "ct2", "breeze26", "int8_float16"), dl.calls)

    def test_without_flag_keeps_existing_breeze26(self):
        old = json.loads(json.dumps(self.OLD))
        old["profiles"]["breeze26"] = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "rtf": 0.07}
        code, last, _, dl = self.run_main(old, "--force", "ct2:cuda")     # 安裝程式 -NoBreeze26 / 不加裝
        self.assertEqual(code, 0)
        self.assertEqual(self.read_cfg()["profiles"], old["profiles"])
        self.assertFalse(any(c[2] == "breeze26" for c in dl.calls if isinstance(c, tuple) and c[0] == "whisper"))
        self.assertIsNone(last["breeze26"])

    def test_failure_does_not_abort_install(self):
        code, last, text, _ = self.run_main(self.OLD, "--force", "ct2:cuda", "--breeze26", fail="磁碟空間不足：測試")
        self.assertEqual(code, 0)
        self.assertEqual(last["breeze26"], None)
        self.assertIn("磁碟空間不足：測試", last["breeze26_error"])
        self.assertIn("[!] Breeze-ASR-26 沒有安裝：磁碟空間不足：測試", text)
        self.assertNotIn("breeze26", self.read_cfg()["profiles"])
        self.assertEqual(self.read_cfg()["profiles"]["breeze"], self.B25)

    def test_only_failure_exit1(self):
        self.write_cfg(self.OLD)
        before = (self.home / "config.json").read_bytes()
        code, last, text, _ = self.run_main(None, "--breeze26-only", fail="下載失敗")
        self.assertEqual(code, 1)
        self.assertEqual((last["breeze26"], last["reason"]), (None, "failed"))
        self.assertIn("[錯誤] Breeze-ASR-26 沒有安裝：下載失敗", text)
        self.assertEqual((self.home / "config.json").read_bytes(), before, "config.json 不變")

    def test_only_success(self):
        code, last, _, _ = self.run_main(self.OLD, "--breeze26-only")
        self.assertEqual(code, 0)
        self.assertEqual(set(self.read_cfg()["profiles"]), {"breeze", "breeze26"})
        self.assertEqual(last["breeze26"]["rtf"], 0.0661)

    def test_mlx_skipped(self):
        old = dict(self.OLD, backend="mlx", device="gpu", compute_type="default", profiles={})
        code, last, text, dl = self.run_main(old, "--breeze26-only")
        self.assertEqual((code, last["reason"]), (1, "unsupported"))
        self.assertIn("本版不提供 mlx 後端的 Breeze-ASR-26", text)
        self.assertEqual(dl.calls, [])
        self.assertEqual(self.read_cfg()["profiles"], {})

    def test_remove(self):
        old = json.loads(json.dumps(self.OLD))
        old["profiles"]["breeze26"] = {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "rtf": 0.07}
        d26, d25 = common.whisper_dir("ct2", "breeze26"), common.whisper_dir("ct2", "breeze")
        for d in (d26, d25):
            d.mkdir(parents=True)
            (d / "model.bin").write_bytes(b"x")
        code, last, _, _ = self.run_main(old, "--remove-breeze26")
        self.assertEqual(code, 0)
        self.assertEqual(last, {"removed_models": ["ct2"], "removed_profile": True})
        self.assertFalse(d26.exists())
        self.assertTrue((d25 / "model.bin").exists(), "Breeze-ASR-25 的模型不動")
        cfg = self.read_cfg()
        self.assertEqual(cfg["profiles"], {"breeze": self.B25})
        self.assertEqual({k: v for k, v in cfg.items() if k != "profiles"}, {k: v for k, v in old.items() if k != "profiles"})


# ---------------------------------------------------------------- 安裝程式
@unittest.skipUnless(V25 and _shells(), "2.5.0 才有；要有 PowerShell")
class InstallerPs(unittest.TestCase):
    """install.ps1 的 Breeze-ASR-26 詢問區塊（照原文抽出，Read-Host 與 Read-Config 換成假的）。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-v250-ps-"))
        src = INSTALL_PS1.read_text(encoding="utf-8-sig")
        block = src[src.index("# 〔2.5.0〕Breeze-ASR-26（規格 2.5.0 §4）"):src.index("if ($NoBreeze26) { $Breeze26 = $false }")]
        block += "if ($NoBreeze26) { $Breeze26 = $false }\n"
        getopt = re.search(r"(?ms)^function Get-Opt\(.*?^\}", src).group(0)
        sbline = next(ln for ln in src.splitlines() if ln.startswith('if ($Breeze26) { $sbArgs += "--breeze26" }'))
        self.ps = self.root / "t.ps1"
        self.ps.write_text(
            "param([switch]$Breeze26, [switch]$NoBreeze26, [string]$Cfg = '', [string]$Ans = '')\n"
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n$script:asked = @()\n"
            "function Read-Host([string]$p) { $script:asked += $p; return $Ans }\n"
            "function Read-Config { if ($Cfg) { return (Get-Content $Cfg -Raw -Encoding UTF8 | ConvertFrom-Json) }; return $null }\n"
            + getopt + "\n" + block + "$sbArgs = @()\n" + sbline + "\n"
            "Write-Output ('RESULT ' + (@{ b26 = [bool]$Breeze26; asked = @($script:asked); args = @($sbArgs) } | ConvertTo-Json -Compress))\n",
            encoding="utf-8-sig")
        self.installed = self.root / "installed.json"
        self.installed.write_text(json.dumps({"profiles": {"breeze26": {"backend": "ct2"}}}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_ps(self, sh, *args):
        r = subprocess.run([sh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.ps), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        line = next(ln for ln in r.stdout.splitlines() if ln.startswith("RESULT "))
        return json.loads(line[7:]), r.stdout

    def test_cases(self):
        Q = "  是否安裝 Breeze-ASR-26（台語或華台混講；暫時下載約 6.2 GB，轉換後佔 1.6 GB）？[y/N]"
        cases = [((), True, False), (("-Ans", "y"), True, True), (("-Ans", "Y"), True, True), (("-Ans", "n"), True, False),
                 (("-Ans", "yes"), True, True), (("-Ans", "x"), True, False),
                 (("-Breeze26",), False, True), (("-NoBreeze26",), False, False), (("-Breeze26", "-NoBreeze26"), False, False),
                 (("-Cfg", "INSTALLED"), False, False), (("-Cfg", "INSTALLED", "-NoBreeze26"), False, False),
                 (("-Cfg", "INSTALLED", "-Breeze26"), False, True)]
        for sh in _shells():
            for args, asked, b26 in cases:
                with self.subTest(shell=sh, args=args):
                    a = [str(self.installed) if x == "INSTALLED" else x for x in args]
                    got, out = self.run_ps(sh, *a)
                    self.assertEqual(bool(got["asked"]), asked, out)
                    if asked:
                        self.assertEqual(got["asked"], [Q] if isinstance(got["asked"], list) else Q)
                        self.assertIn("需要約 10 GB 可用空間", out)
                        self.assertIn("台語會翻成華語文字（不是台語漢字）", out)
                    self.assertEqual(got["b26"], b26)
                    self.assertEqual(got["args"] or [], ["--breeze26"] if b26 else [])
                    if "INSTALLED" in args and not asked:
                        self.assertIn("已安裝，保留", out) if "-NoBreeze26" not in args and "-Breeze26" not in args else None

    def test_static(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        self.assertIn("[switch]$Breeze26,", s)
        self.assertIn("[switch]$NoBreeze26,", s)
        self.assertIn("-Breeze26 / -NoBreeze26", s)
        self.assertIn('Write-Host "    Breeze-26：$($b.backend) / $($b.device)（RTF $($b.rtf)）', s)
        self.assertIn("$choice.breeze26_error", s)
        self.assertNotIn("remove-breeze26", s, "安裝程式不移除已裝的 Breeze-ASR-26")


@unittest.skipUnless(V25, "2.5.0 才有")
class InstallerSh(unittest.TestCase):
    def test_flags(self):
        s = INSTALL_SH.read_text(encoding="utf-8")
        self.assertIn("--breeze26)    BREEZE26=1; shift ;;", s)
        self.assertIn("--no-breeze26) BREEZE26=0; shift ;;", s)
        self.assertIn("macOS 本版不提供 Breeze-ASR-26", s)
        self.assertNotIn("sb_args+=(--breeze26)", s, "macOS 不轉給 setup_backend.py")
        self.assertNotIn("是否安裝 Breeze-ASR-26", s, "macOS 不詢問")

    @unittest.skipUnless(GIT_BASH.exists(), "要有 Git Bash")
    def test_parse_runs(self):
        """實跑參數解析＋略過說明（把 install.sh 截到「自動校正」之前，換掉會安裝東西的部分）。"""
        s = INSTALL_SH.read_text(encoding="utf-8")
        head = s[:s.index("MMH=\"${MEETING_MINUTES_PRO_HOME")]
        warn = s[s.index("# 〔2.5.0〕Breeze-ASR-26（台語）：macOS"):s.index("# ------------------------------------------------------------------ 自動校正")]
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.sh"
            f.write_text(head + "warn() { echo \"WARN $1\"; }\n" + warn + "echo \"B26=[$BREEZE26]\"\n", encoding="utf-8", newline="\n")
            for args, want, warned in ((["--breeze26"], "1", True), (["--no-breeze26"], "0", False), ([], "", False)):
                with self.subTest(args=args):
                    r = subprocess.run([str(GIT_BASH), f.as_posix(), *args], capture_output=True, text=True, encoding="utf-8",
                                       timeout=60)
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn(f"B26=[{want}]", r.stdout)
                    self.assertEqual("WARN macOS 本版不提供 Breeze-ASR-26" in r.stdout, warned, r.stdout)


# ---------------------------------------------------------------- vad_filter
@unittest.skipUnless(V25, "2.5.0 才有")
class Vad(_Home):
    def test_only_breeze26_ct2(self):
        self.assertEqual(common.ASR_VAD_FILTER, {("breeze26", "ct2")})
        self.assertTrue(common.asr_vad_filter("breeze26", "ct2"))
        self.assertTrue(common.asr_vad_filter("breeze26", "ct2", diarized=True))
        self.assertFalse(common.asr_vad_filter("breeze26", "ct2", diarized=False), "略過說話者分離時不開（規格 2.5.0 §6）")
        self.assertEqual(common.BREEZE26_NO_DIAR_NOTE, "沒有說話者分離時，長段雜訊或音樂可能被辨識成句子")
        for m, b in (("turbo", "ct2"), ("breeze", "ct2"), ("large-v3", "ct2"), ("breeze26", "openvino"), ("breeze26", "mlx")):
            self.assertFalse(common.asr_vad_filter(m, b), (m, b))

    def test_ct2_backend_kw(self):
        import backends
        made = []

        class FakeWM:
            def __init__(self, path, **kw):
                made.append(path)
        fw = types.SimpleNamespace(WhisperModel=FakeWM)
        for alias in ("breeze26", "breeze", "turbo"):
            d = common.whisper_dir("ct2", alias)
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.bin").write_bytes(b"x")
            (d / "tokenizer.json").write_text("{}", encoding="utf-8")
        with mock.patch.dict(sys.modules, {"faster_whisper": fw}):
            got = {a: backends.create("ct2", a, "cuda", "zh", None, "int8_float16").kw for a in ("breeze26", "breeze", "turbo")}
            off = backends.create("ct2", "breeze26", "cuda", "zh", None, "int8_float16", vad_filter=False).kw
            forced = backends.create("ct2", "turbo", "cuda", "zh", None, "int8_float16", vad_filter=False).kw
        self.assertFalse(off["vad_filter"], "transcribe.py 略過說話者分離時明確傳 False")
        self.assertFalse(forced["vad_filter"])
        self.assertTrue(got["breeze26"]["vad_filter"])
        self.assertFalse(got["breeze"]["vad_filter"])
        self.assertFalse(got["turbo"]["vad_filter"])
        for kw in got.values():   # 其他參數與 2.4.1 相同
            self.assertEqual({k: kw[k] for k in ("language", "beam_size", "condition_on_previous_text", "without_timestamps")},
                             {"language": "zh", "beam_size": 5, "condition_on_previous_text": False, "without_timestamps": True})


# ---------------------------------------------------------------- transcribe.py
@unittest.skipUnless(V25, "2.5.0 才有")
class Transcribe(_Home):
    def setUp(self):
        super().setUp()
        import numpy as np
        import soundfile as sf
        import backends
        import transcribe as tr
        self.tr, self.backends = tr, backends
        self.src = self.tmp / "meet.wav"
        rng = np.random.default_rng(0)
        sf.write(str(self.src), (rng.standard_normal(16000 * 12) * 0.1).astype(np.float32), 16000)
        self._run_id = os.environ.pop("MMP_RUN_ID", None)
        self.created = []
        test = self

        class FakeASR:
            def transcribe(self, audio):
                return "今天社區發展協會開月會，先報告上個月的收支"

        def fake_create(backend, model, device, language="zh", hotwords=None, compute_type="default", vad_filter=None):
            test.created.append((backend, model, device, language, compute_type))
            test.vads.append(vad_filter)
            return FakeASR()

        def fake_diar_run(choice, audio, wav, out_dir, duration, n, threshold, cfg, log=None, warn=None):
            meta = {"engine": "sherpa", "device": "cpu", "gpu_name": None, "engine_reason": "test", "fallback": None,
                    "setting": "auto", "n": None, "cluster_threshold": threshold, "speakers_raw": 2, "speakers": 2,
                    "top_n_merged_sec": 0.0, "pyannote": None}
            return {"segs": [(0.0, 6.0, 0), (6.0, duration, 1)], "meta": meta, "pyannote_sec": None}
        self.vads = []
        self.sp = [mock.patch.object(tr, "to_wav", lambda s, d: shutil.copyfile(s, d)),
                   mock.patch.object(backends, "create", fake_create),
                   mock.patch.object(tr.diar, "run", fake_diar_run),
                   mock.patch.object(tr.diar, "choose_engine", lambda cfg, eng, ctype=None: {"engine": "sherpa"})]
        for p in self.sp:
            p.__enter__()

    def tearDown(self):
        for p in reversed(self.sp):
            p.__exit__(None, None, None)
        if self._run_id is not None:
            os.environ["MMP_RUN_ID"] = self._run_id
        super().tearDown()

    CFG = {"backend": "ct2", "device": "cpu", "compute_type": "int8", "whisper": "turbo",
           "profiles": {"breeze": {"backend": "ct2", "device": "cuda", "compute_type": "float16", "rtf": 0.04},
                        "breeze26": {"backend": "ct2", "device": "cuda", "compute_type": "int8_float16", "rtf": 0.066}}}

    def main(self, *extra, diarize=False):
        self.write_cfg(self.CFG)
        out = self.tmp / f"out{len(list(self.tmp.glob('out*')))}"
        argv = sys.argv
        sys.argv = ["transcribe.py", str(self.src), "--out-dir", str(out), "--no-corrections", "--no-correct",
                    "--no-keyframes", *([] if diarize else ["--no-diarize"]), *extra]
        so, se = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                self.tr.main()
        finally:
            sys.argv = argv
        self.err = se.getvalue()
        return out

    def asr_ev(self, out):
        evs = [json.loads(x) for x in (out / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
        return next(e for e in evs if e.get("event") == "checkpoint" and e.get("name") == "asr")

    NOTE = "沒有說話者分離時，長段雜訊或音樂可能被辨識成句子"

    def test_breeze26_skip_diarize(self):
        """略過說話者分離：vad_filter 關、stderr 印雜訊提醒（規格 2.5.0 §6）。"""
        out = self.main("--whisper", "breeze26")
        self.assertEqual(self.created, [("ct2", "breeze26", "cuda", "zh", "int8_float16")])   # profiles.breeze26、語言 zh
        self.assertEqual(self.vads, [False])
        self.assertIn(self.NOTE, self.err)
        self.assertNotIn("vad_filter 開", self.err)
        self.assertNotIn("vad_filter", self.asr_ev(out))
        self.assertNotIn("vad_filter", json.loads((out / "transcript.json").read_text(encoding="utf-8"))["meta"])
        self.assertEqual(self.asr_ev(out)["asr_model"], "breeze26")

    def test_breeze26(self):
        out = self.main("--whisper", "breeze26", diarize=True)
        self.assertEqual(self.created, [("ct2", "breeze26", "cuda", "zh", "int8_float16")])   # profiles.breeze26、語言 zh
        self.assertEqual(self.vads, [True])
        self.assertIn("Breeze-ASR-26（台語） 載入：ct2 / cuda", self.err)
        self.assertIn("vad_filter 開：略過非人聲", self.err)
        self.assertNotIn(self.NOTE, self.err)
        ev = self.asr_ev(out)
        self.assertEqual((ev["asr_model"], ev.get("vad_filter")), ("breeze26", True))
        meta = json.loads((out / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual((meta["model"], meta["language"], meta.get("vad_filter")), ("breeze26", "zh", True))
        runs = [json.loads(x) for x in (self.home / "logs" / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(runs[-1]["asr_model"], "breeze26")
        self.assertEqual(meta["punctuation"]["by_segment"].get("whisper", 0), 0, "Breeze 家族不沿用 Whisper 標點")

    def test_turbo_and_breeze_unchanged(self):
        for dz in (False, True):
            out = self.main(diarize=dz)
            self.assertEqual(self.created[-1], ("ct2", "turbo", "cpu", "zh", "int8"))
            self.assertEqual(self.vads[-1], False)
            self.assertNotIn("vad_filter", self.asr_ev(out))
            self.assertNotIn("vad_filter", json.loads((out / "transcript.json").read_text(encoding="utf-8"))["meta"])
            self.assertNotIn("vad_filter", self.err)
            self.assertNotIn(self.NOTE, self.err)
            out = self.main("--whisper", "breeze", diarize=dz)
            self.assertEqual(self.created[-1], ("ct2", "breeze", "cuda", "zh", "float16"))
            self.assertEqual(self.vads[-1], False)
            self.assertNotIn("vad_filter", self.asr_ev(out))
            self.assertIn("Breeze-ASR-25 載入", self.err)
            self.assertNotIn(self.NOTE, self.err)


@unittest.skipUnless(V25, "2.5.0 才有")
class Estimate(unittest.TestCase):
    def test_estimate_only_breeze26_folder(self):
        from test_auto_minutes import Base   # noqa: F401  （確認匯入路徑）
        import test_v230 as v230
        t = v230.EstimateRun("test_no_call_no_write")
        t.setUp()
        try:
            v230.write_out(t.out, v230.PARAS)
            tj = t.out / "transcript.json"
            doc = json.loads(tj.read_text(encoding="utf-8"))
            doc.setdefault("meta", {})["model"] = "breeze26"
            tj.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            boom = v230._Boom()
            t.use(boom)
            r = v230.am.estimate(t.out, v230.EstimateRun.REQ, cfg={})
            self.assertEqual(r["status"], "ok", r)
            self.assertEqual(boom.calls, 0)
            self.assertGreater(r["estimate"]["chars"], 0)
        finally:
            t.tearDown()


# ---------------------------------------------------------------- 入口、文件
@unittest.skipUnless(V25, "2.5.0 才有")
class EntryStatic(unittest.TestCase):
    def test_entries(self):
        for f in ("mm-sendto.ps1", "mm-dropped.sh"):
            s = (_testenv.RUNTIME / f).read_text(encoding="utf-8-sig")
            with self.subTest(f=f):
                self.assertNotIn('sk "使用 Breeze-ASR-25？', s)            # 舊的 y/N 題（Ask／ask）已經拿掉
                self.assertNotIn('"ask_breeze"', s)
                self.assertNotIn("ask_breeze|", s)
                self.assertIn("ask_whisper", s)
                self.assertIn("辨識模型：", s)
                self.assertIn("Enter＝預設（turbo）", s)
                self.assertIn("b＝Breeze-ASR-25（中英夾雜很重的技術會議）", s)
                self.assertIn("t＝Breeze-ASR-26（台語或華台混講，輸出華語文字）", s)
                self.assertIn("台語會翻成華語文字；人名、機關名、否定句請人工核對", s)
                self.assertIn("沒有說話者分離時，長段雜訊或音樂可能被辨識成句子", s)
                self.assertIn("breeze26", s)


@unittest.skipUnless(V25, "2.5.0 才有")
class Docs(unittest.TestCase):
    def test_skill(self):
        s = SKILL.read_text(encoding="utf-8")
        desc = re.search(r"^description: (.*)$", s, re.M).group(1)
        self.assertLessEqual(len(desc), 1024)
        self.assertIn("Breeze-ASR-26", desc)
        self.assertIn("--whisper breeze26", s)
        self.assertIn("profiles.breeze26.rtf", s)
        self.assertIn("華語文字", s)
        self.assertIn("--breeze26-only", s)

    def test_readme_notices(self):
        r = (VD / "README.md").read_text(encoding="utf-8")
        for t in ("Breeze-ASR-26", "--whisper breeze26", "-Breeze26", "--breeze26-only", "--remove-breeze26", "華語文字",
                  "約三成", "合成台語", "10 GB", "mlx", "正式逐字紀錄"):
            self.assertIn(t, r, t)
        n = (VD / "THIRD-PARTY-NOTICES.md").read_text(encoding="utf-8")
        self.assertIn("Breeze-ASR-26", n)
        self.assertIn(common.BREEZE26_REVISION, n)
        self.assertIn("https://huggingface.co/MediaTek-Research/Breeze-ASR-26", n)
        self.assertIn("Apache-2.0", n)


if __name__ == "__main__":
    unittest.main()
