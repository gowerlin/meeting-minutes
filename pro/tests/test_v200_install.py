"""〔2.0.0〕入口、安裝程式、GPU 說話者分離選用套件（規格 §7、§8、§9.5、§10.2 E-1 的單元部分、§10.4）。

- setup_gpu_diar.py：Hugging Face 引導（可開瀏覽器、白話說明）、登入、下載、實測、config.json 狀態。
  huggingface_hub、瀏覽器、`hf auth login` 一律用假的（不連網、不開瀏覽器、不碰任何帳號）；HF_HOME／HF_HUB_CACHE
  指向空的暫存目錄、HF_TOKEN 不設定。
- 安裝程式：版號四處一致、新參數、GPU 原因說明表與 setup_gpu_diar.py 一致、install.ps1／install.sh 內嵌「更新設定」片段寫入
  diarization.pyannote.status（macOS 一律 none）、install.sh 沒有 GPU 安裝且維持 bash 3.2 語法。
- 入口：兩支入口的類型表與 content_types.py 一致。
- upload zip：內容與 payload/skill 一致。
不呼叫任何模型。
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
import types
import unittest
import unittest.mock
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402

V200 = _testenv.VER >= (2, 0, 0)
VD = _testenv.VERSION_DIR
RUNTIME = _testenv.RUNTIME
INSTALL_PS1 = VD / "install.ps1"
INSTALL_SH = VD / "install.sh"
SKILL_DIR = VD / "payload" / "skill" / "meeting-minutes-pro"


# ---------------------------------------------------------------- 假的 huggingface_hub
class FakeHub:
    """state：logged_in（True／False／None＝連不上）、approved、download（"ok"｜"gated"｜"net"）、login_ok（hf auth login 之後是否登入）。"""

    def __init__(self, logged_in=False, approved=True, download="ok", login_ok=True, approve_on_retry=False):
        self.logged_in, self.approved, self.download = logged_in, approved, download
        self.login_ok, self.approve_on_retry = login_ok, approve_on_retry
        self.calls = []
        errors = types.ModuleType("huggingface_hub.errors")

        class HfHubHTTPError(Exception):
            def __init__(self, msg="", status=None):
                super().__init__(msg)
                self.response = types.SimpleNamespace(status_code=status)

        class LocalTokenNotFoundError(EnvironmentError):
            pass

        class GatedRepoError(HfHubHTTPError):
            pass

        errors.HfHubHTTPError, errors.LocalTokenNotFoundError, errors.GatedRepoError = (
            HfHubHTTPError, LocalTokenNotFoundError, GatedRepoError)
        hub = types.ModuleType("huggingface_hub")
        hub.errors = errors
        outer = self

        class HfApi:
            def whoami(self):
                outer.calls.append("whoami")
                if outer.logged_in is None:
                    raise ConnectionError("offline")
                if not outer.logged_in:
                    raise LocalTokenNotFoundError("no token")
                return {"name": "someone"}

            def model_info(self, repo):
                return types.SimpleNamespace(sha="abc123")

        def snapshot_download(repo, local_dir=None):
            outer.calls.append("download")
            if outer.download == "net":
                raise ConnectionError("net")
            if not outer.approved:
                if outer.approve_on_retry:
                    outer.approved = True
                raise GatedRepoError("Access denied", 403)
            d = Path(local_dir)
            for f in ("config.yaml", "segmentation/pytorch_model.bin", "embedding/pytorch_model.bin",
                      "plda/plda.npz", "plda/xvec_transform.npz"):
                (d / f).parent.mkdir(parents=True, exist_ok=True)
                (d / f).write_bytes(b"x")
            return str(d)

        hub.HfApi, hub.snapshot_download = HfApi, snapshot_download
        self.modules = {"huggingface_hub": hub, "huggingface_hub.errors": errors}

    def hf_login(self):
        self.calls.append("hf_login")
        if self.login_ok:
            self.logged_in = True


@unittest.skipUnless(V200, "2.0.0 才有")
class SetupGpuDiar(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-gpu-"))
        self.env = {k: os.environ.get(k) for k in ("MEETING_MINUTES_PRO_HOME", "HF_HOME", "HF_HUB_CACHE", "HF_TOKEN")}
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.tmp / "home")
        os.environ["HF_HOME"] = str(self.tmp / "hf")                   # 空的 HF_HOME，不沿用使用者的登入
        os.environ["HF_HUB_CACHE"] = str(self.tmp / "hf" / "hub")
        os.environ.pop("HF_TOKEN", None)
        import setup_gpu_diar
        self.m = setup_gpu_diar
        self.opened = []

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_prepare(self, hub: FakeHub, answers, open_ok=True):
        def fake_open(url):
            self.opened.append(url)
            return open_ok
        err = io.StringIO()
        saved = {k: sys.modules.get(k) for k in hub.modules}
        sys.modules.update(hub.modules)
        try:
            with contextlib.redirect_stderr(err), \
                    unittest.mock.patch.object(self.m, "open_url", fake_open), \
                    unittest.mock.patch.object(self.m, "run_hf_login", hub.hf_login), \
                    unittest.mock.patch.object(sys, "stdin", io.StringIO("".join(a + "\n" for a in answers))):
                reason, extra = self.m.prepare()
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        self.out = err.getvalue()
        return reason, extra

    def test_already_logged_in_no_guide(self):
        """已登入且已同意 → 不印引導，直接下載。"""
        hub = FakeHub(logged_in=True)
        reason, extra = self.run_prepare(hub, [])
        self.assertIsNone(reason)
        self.assertEqual(extra, {"model": "downloaded"})
        self.assertIn("已登入，正在下載權重（約 33 MB）", self.out)
        self.assertNotIn("Hugging Face 是放 AI 模型的網站", self.out)
        self.assertEqual(self.opened, [])
        src = json.loads((self.m.pyannote_model_dir() / ".mmp-source.json").read_text(encoding="utf-8"))
        self.assertEqual((src["repo"], src["revision"], src["license"]), (self.m.REPO, "abc123", "cc-by-4.0"))
        self.assertRegex(src["downloaded_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_browser_guide_then_login(self):
        """沒登入 → 開瀏覽器（沒有帳號：註冊頁）→ 同意頁 → 存取碼頁 → 登入 → 下載。"""
        hub = FakeHub(logged_in=False)
        # 開瀏覽器？Y；有帳號？n；註冊頁 Enter；同意頁 Enter；存取碼頁 Enter；現在登入？Enter
        reason, _ = self.run_prepare(hub, ["", "n", "", "", "", ""])
        self.assertIsNone(reason)
        self.assertEqual(self.opened, [self.m.JOIN_URL, self.m.REPO_URL, self.m.TOKENS_URL])
        self.assertEqual(hub.calls, ["whoami", "hf_login", "whoami", "download"])
        for s in ("Hugging Face 是放 AI 模型的網站", "步驟 1／4", "步驟 2／4", "步驟 3／4", "步驟 4／4",
                  "個人使用填「個人」或「Personal」", "Company/university", "Meeting note taker", "貼上時畫面不會顯示任何字，這是正常的", "Ctrl＋V", "滑鼠右鍵",
                  "How would you like to log in?", "Paste an access token", "直接按數字 2", "選「Read」", "meeting-minutes-pro",
                  "已在瀏覽器開啟", "已登入，正在下載權重（約 33 MB）", "可能偶爾寄送 pyannote 的消息"):
            self.assertIn(s, self.out)
        self.assertNotIn("someone", self.out)                          # 不印帳號資訊
        # mock 情境的主控台畫面全文（MMP_SHOW_GUIDE=1 時印出）
        if os.environ.get("MMP_SHOW_GUIDE"):
            print("\n" + "----- guide transcript -----\n" + self.out + "----- end -----")

    def test_have_account_skips_join(self):
        hub = FakeHub(logged_in=False)
        reason, _ = self.run_prepare(hub, ["", "", "", "", ""])
        self.assertIsNone(reason)
        self.assertEqual(self.opened, [self.m.REPO_URL, self.m.TOKENS_URL])

    def test_no_browser_prints_urls(self):
        hub = FakeHub(logged_in=False)
        reason, _ = self.run_prepare(hub, ["n", ""])
        self.assertIsNone(reason)
        self.assertEqual(self.opened, [])
        for u in (self.m.JOIN_URL, self.m.REPO_URL, self.m.TOKENS_URL):
            self.assertIn(f"網址：{u}", self.out)

    def test_browser_open_fails_prints_urls(self):
        hub = FakeHub(logged_in=False)
        reason, _ = self.run_prepare(hub, ["", "", "", "", ""], open_ok=False)
        self.assertIsNone(reason)
        self.assertIn("沒辦法自動開啟瀏覽器", self.out)
        self.assertIn(f"網址：{self.m.TOKENS_URL}", self.out)

    def test_decline_login(self):
        hub = FakeHub(logged_in=False)
        reason, _ = self.run_prepare(hub, ["n", "n"])
        self.assertEqual(reason, "hf_not_logged_in")
        self.assertNotIn("hf_login", hub.calls)
        self.assertIn("install.cmd -GpuDiar", self.out)
        self.assertIn("說話者分離照舊用 CPU", self.out)

    def test_login_fails(self):
        hub = FakeHub(logged_in=False, login_ok=False)
        reason, _ = self.run_prepare(hub, ["n", ""])
        self.assertEqual(reason, "hf_not_logged_in")
        self.assertIn("還是沒有登入", self.out)

    def test_not_approved(self):
        """登入了但沒同意：再給一次機會（開同意頁），還是沒同意 → hf_not_approved，白話說明要等幾分鐘。"""
        hub = FakeHub(logged_in=True, approved=False)
        reason, _ = self.run_prepare(hub, ["", ""])
        self.assertEqual(reason, "hf_not_approved")
        self.assertEqual(hub.calls.count("download"), 2)
        self.assertEqual(self.opened, [self.m.REPO_URL])
        self.assertIn("剛按完、作者那邊還要幾分鐘才生效", self.out)
        self.assertIn("install.cmd -GpuDiar", self.out)

    def test_approved_on_retry(self):
        hub = FakeHub(logged_in=True, approved=False, approve_on_retry=True)
        reason, _ = self.run_prepare(hub, ["n", "", ""])
        self.assertIsNone(reason)
        self.assertEqual(self.opened, [])

    def test_download_failed(self):
        hub = FakeHub(logged_in=True, download="net")
        reason, _ = self.run_prepare(hub, [])
        self.assertEqual(reason, "download_failed")
        self.assertIn("install.cmd -GpuDiar 再試一次", self.out)

    def test_offline(self):
        hub = FakeHub(logged_in=None)
        reason, _ = self.run_prepare(hub, [])
        self.assertEqual(reason, "download_failed")
        self.assertIn("連不上 Hugging Face", self.out)

    def test_model_present_skips_login(self):
        d = self.m.pyannote_model_dir()
        for f in self.m.PYANNOTE_MODEL_FILES:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_bytes(b"x")
        hub = FakeHub(logged_in=False)
        reason, extra = self.run_prepare(hub, [])
        self.assertIsNone(reason)
        self.assertEqual(extra, {"model": "present"})
        self.assertEqual(hub.calls, [])

    def test_set_status_and_upgrade(self):
        """--set-status 只改 pyannote 的兩個鍵；之後 upgrade_config() 補齊其餘鍵、不覆蓋狀態。"""
        import common
        cfg_path = common.config_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"backend": "ct2", "runtime_version": "1.2.2"}), encoding="utf-8")
        self.m.set_status("incomplete", "hf_not_logged_in")
        cfg = common.upgrade_config()
        self.assertEqual(cfg["diarization"]["pyannote"]["status"], "incomplete")
        self.assertEqual(cfg["diarization"]["pyannote"]["reason"], "hf_not_logged_in")
        self.assertEqual(cfg["diarization"]["engine"], "auto")
        self.m.set_status("ready", "x")
        self.assertIsNone(json.loads(cfg_path.read_text(encoding="utf-8"))["diarization"]["pyannote"]["reason"])

    def test_cli_json_and_smoke_missing_sample(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        script = str(_testenv.SCRIPTS / "setup_gpu_diar.py")
        p = subprocess.run([sys.executable, "-B", script, "--smoke"], capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 1)
        j = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])["gpu_diar"]
        self.assertEqual((j["status"], j["reason"], j["detail"]), ("incomplete", "smoke_failed", "sample_missing"))
        p = subprocess.run([sys.executable, "-B", script, "--set-status", "none"], capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0)
        cfg = json.loads((Path(os.environ["MEETING_MINUTES_PRO_HOME"]) / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["diarization"]["pyannote"], {"status": "none", "reason": None})
        self.assertEqual(p.stdout.decode("utf-8").count("\n"), 1)        # stdout 只有最後一行 JSON

    def test_check_torch_variants(self):
        fake = types.ModuleType("torch")
        fake.__version__ = "2.11.0+cpu"
        fake.cuda = types.SimpleNamespace(is_available=lambda: False, get_device_capability=lambda: (12, 0),
                                          get_device_name=lambda i: "GPU")
        with unittest.mock.patch.dict(sys.modules, {"torch": fake}):
            self.assertEqual(self.m.check_torch()["reason"], "torch_cpu")
            fake.__version__ = "2.11.0+cu128"
            self.assertEqual(self.m.check_torch()["reason"], "cuda_unavailable")
            fake.cuda.is_available = lambda: True
            r = self.m.check_torch()
            self.assertTrue(r["ok"])
            self.assertEqual(r["capability"], [12, 0])

    def test_no_secret_reads(self):
        """不讀權杖值：程式裡不碰 HF_TOKEN 的值、不讀 token 檔、不印 whoami 的結果。"""
        src = (_testenv.SCRIPTS / "setup_gpu_diar.py").read_text(encoding="utf-8")
        self.assertNotRegex(src, r"environ(\.get)?\(?\[?[\"']HF_TOKEN")
        self.assertNotIn("get_token", src)
        self.assertNotRegex(src, r"huggingface[/\\]+token")
        self.assertRegex(src, r"api\.whoami\(\)\s+# 回傳的帳號資訊不印、不存")


@unittest.skipUnless(V200, "2.0.0 才有")
class Installers(unittest.TestCase):
    def test_version_everywhere(self):
        v = _testenv.VERSION
        self.assertIn(f'$Version   = "{v}"', INSTALL_PS1.read_text(encoding="utf-8-sig"))
        self.assertIn(f'VERSION="{v}"', INSTALL_SH.read_text(encoding="utf-8"))
        self.assertIn(f"<!-- meeting-minutes-pro-version: {v} -->", (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn(f"> 版本 {v}", (VD / "README.md").read_text(encoding="utf-8"))
        import common
        self.assertEqual(common.VERSION, v)
        for n in ("mm-sendto.ps1", "mm-dropped.sh"):
            self.assertIn(f"meeting-minutes-pro {v}）", (RUNTIME / n).read_text(encoding="utf-8-sig").splitlines()[0 if n.endswith(".ps1") else 1])

    def test_ps1_params_and_gpu_steps(self):
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        for k in ("[switch]$GpuDiar", "[switch]$NoGpuDiar", "[switch]$RemoveGpuDiar", "-GpuDiar 與 -NoGpuDiar 只能擇一",
                  "--index-url $idx", "-c $cons --extra-index-url $idx", 'Invoke-GpuSetup @("--prepare")',
                  'Invoke-GpuSetup @("--smoke")', 'Invoke-GpuSetup @("--check-torch")', "是否安裝 GPU 說話者分離？[y/N]",
                  "約 5 GB", "互有勝負", "刪除自訂範本 {0} 份？[y/N]", "meeting-minutes-pro-templates-備份",
                  "hf auth logout"):
            self.assertIn(k, s)
        self.assertNotIn("一律較準", s)
        # 實測在「硬體偵測、下載模型」之後（範例音檔由那一步下載）
        self.assertLess(s.index('Step "硬體偵測、下載模型與實測'), s.index('Invoke-GpuSetup @("--smoke")'))
        self.assertLess(s.index('Step "偵測到 NVIDIA 顯示卡，安裝 CUDA 後端'), s.index("$GpuResult = Install-GpuDiar"))

    def test_ps1_reason_table_matches(self):
        import setup_gpu_diar
        s = INSTALL_PS1.read_text(encoding="utf-8-sig")
        block = re.search(r"\$GpuReasonText = @\{(.*?)\n\}", s, re.S).group(1)
        got = dict(re.findall(r'(\w+) = "([^"]*)"', block))
        self.assertEqual(got, setup_gpu_diar.REASON_TEXT)

    def test_constraints_pin_torch(self):
        cons = (RUNTIME / "constraints-gpu-diar.txt").read_text(encoding="utf-8")
        req = (RUNTIME / "requirements-gpu-diar.txt").read_text(encoding="utf-8")
        self.assertIn("torch==2.11.0+cu128", cons)
        self.assertIn("torchaudio==2.11.0+cu128", cons)
        self.assertIn("pyannote.audio==4.0.7", req)
        self.assertIn("huggingface_hub>=0.30,<3", req)                  # 〔2.0.0〕上限：登入畫面依版本而變
        self.assertNotIn("torch", re.sub(r"#.*", "", req))              # torch 只在 constraints

    def test_sh_no_gpu_and_bash32(self):
        s = INSTALL_SH.read_text(encoding="utf-8")
        code = "\n".join(line for line in s.splitlines() if not line.lstrip().startswith("#"))
        for k in ("pip install torch", "pyannote.audio", "venv-gpu-diar", "hf auth"):
            self.assertNotIn(k, code)
        self.assertIn("""MMP_GPU_DIAR='{"status": "none", "reason": null}'""", s)
        for f in (INSTALL_SH, RUNTIME / "mm-dropped.sh"):
            t = f.read_text(encoding="utf-8")
            for bad in (r"declare\s+-A", r"\$\{\w+,,\}", r"\$\{\w+\^\^\}", r"\bmapfile\b", r"\breadarray\b", r"local\s+-n\b"):
                self.assertNotRegex(t, bad, f"{f.name}：bash 3.2 不支援 {bad}")
            bash = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))   # 不要用 System32 的 WSL bash
            if bash.exists():
                p = subprocess.run([str(bash), "-n", f.as_posix()], capture_output=True)
                self.assertEqual(p.returncode, 0, p.stderr)


def _snippet(path: Path, pattern: str) -> str:
    return re.search(pattern, path.read_text(encoding="utf-8-sig"), re.S).group(1)


@unittest.skipUnless(V200, "2.0.0 才有")
class InstallerConfigGpu(unittest.TestCase):
    """安裝程式內嵌的「更新設定」片段：MMP_GPU_DIAR 寫 diarization.pyannote（規格 §8.2 步驟 8、§8.10）。"""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="mmp-inst-gpu-"))

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def run_snippet(self, code, cfg, extra):
        (self.home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        env = dict(os.environ, MEETING_MINUTES_PRO_HOME=str(self.home), MMP_SCRIPTS=str(RUNTIME / "scripts"),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", **extra)
        if "MMP_GPU_DIAR" not in extra:
            env.pop("MMP_GPU_DIAR", None)
        p = subprocess.run([sys.executable, "-B", "-"], input=code.encode("utf-8"), capture_output=True, env=env, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        return json.loads((self.home / "config.json").read_text(encoding="utf-8")), p.stdout.decode("utf-8")

    def test_ps1(self):
        code = _snippet(INSTALL_PS1, r"\$upgradePy = @'\n(.*?)\n'@")
        old = {"backend": "ct2", "runtime_version": "1.2.2"}
        cfg, out = self.run_snippet(code, old, {"MMP_CORRECTION": "null",
                                                "MMP_GPU_DIAR": json.dumps({"status": "incomplete", "reason": "hf_not_logged_in"})})
        self.assertEqual(cfg["diarization"]["pyannote"]["status"], "incomplete")
        self.assertEqual(cfg["diarization"]["pyannote"]["reason"], "hf_not_logged_in")
        self.assertEqual(cfg["diarization"]["engine"], "auto")
        # added_keys 仍是整塊（GPU 狀態在升級之後才寫，不影響「已補上新版設定鍵」的訊息）
        self.assertIn("diarization", json.loads(out.strip().splitlines()[-1])["added_keys"])
        cfg, _ = self.run_snippet(code, cfg, {"MMP_CORRECTION": "null"})          # 沒有結果時不改
        self.assertEqual(cfg["diarization"]["pyannote"]["status"], "incomplete")

    def test_sh_always_none(self):
        code = _snippet(INSTALL_SH, r"<<'PY'\n(.*?)\nPY\n")
        cfg, _ = self.run_snippet(code, {"backend": "mlx", "diarization": {"pyannote": {"status": "ready"}}},
                                  {"MMP_GPU_DIAR": '{"status": "none", "reason": null}'})
        self.assertEqual(cfg["diarization"]["pyannote"]["status"], "none")


@unittest.skipUnless(V200, "2.0.0 才有")
class EntryTables(unittest.TestCase):
    """兩支入口寫死的 7 種類型（名稱、筆記稱呼、s 寫進主句）與 content_types.py 一致；runlog 有字幕階段。"""

    def test_ps1(self):
        import content_types as ct
        s = (RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        rows = re.findall(r'@\{ code = "(\w+)";\s+label = "([^"]+)";\s+noun = "([^"]+)";\s+skipMain = \$(true|false) \}', s)
        self.assertEqual([r[0] for r in rows], list(ct.CODES))
        for code, label, noun, skip in rows:
            self.assertEqual((label, noun, skip == "true"), (ct.label_of(code), ct.noun_of(code), ct.TYPES[code]["skip_in_prompt"]))

    def test_sh(self):
        import content_types as ct
        s = (RUNTIME / "mm-dropped.sh").read_text(encoding="utf-8")
        rows = re.findall(r'^\s+(\w+)\)\s+echo "([^|"]+)\|([^|"]+)\|([01])" ;;', s, re.M)
        self.assertEqual([r[0] for r in rows], list(ct.CODES))
        for code, label, noun, skip in rows:
            self.assertEqual((label, noun, skip == "1"), (ct.label_of(code), ct.noun_of(code), ct.TYPES[code]["skip_in_prompt"]))

    def test_runlog_subtitles_stage(self):
        import runlog
        o = runlog.STAGE_ORDER
        self.assertLess(o.index("write_outputs"), o.index("subtitles"))
        self.assertLess(o.index("subtitles"), o.index("correct"))
        self.assertEqual(runlog.STAGE_NAME["subtitles"], "字幕")

    def test_templates_readme(self):
        import templates
        p = RUNTIME / "templates" / "README.md"
        self.assertTrue(p.is_file())
        self.assertEqual(templates.list_all(p.parent), [])                 # README.md 不算範本


class RealInstallGuard(unittest.TestCase):
    """〔2.0.0〕_testenv 的防呆：真實安裝的 config.json 一有變動就偵測得到；測試 home 不是真實安裝的位置。"""

    def test_stamp_detects_change(self):
        d = Path(tempfile.mkdtemp(prefix="mmp-guard-"))
        try:
            f = d / "config.json"
            self.assertIsNone(_testenv.file_stamp(f))
            f.write_text('{"a": 1}', encoding="utf-8")
            a = _testenv.file_stamp(f)
            f.write_text('{"a": 1 }', encoding="utf-8")
            self.assertNotEqual(a, _testenv.file_stamp(f))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_test_home_is_not_real(self):
        self.assertNotEqual(Path(os.environ["MEETING_MINUTES_PRO_HOME"]).resolve(), _testenv.real_home().resolve())
        self.assertFalse(_testenv.real_install_changed())


@unittest.skipUnless(V200, "2.0.0 才有")
class UploadZip(unittest.TestCase):
    def test_matches_payload_skill(self):
        z = zipfile.ZipFile(VD / "payload" / "meeting-minutes-pro-upload.zip")
        names = sorted(n for n in z.namelist() if not n.endswith("/"))
        want = sorted("meeting-minutes-pro/" + p.relative_to(SKILL_DIR).as_posix() for p in SKILL_DIR.rglob("*") if p.is_file())
        self.assertEqual(names, want)
        for n in names:
            self.assertEqual(z.read(n), (SKILL_DIR / n.split("/", 1)[1]).read_bytes(), n)


@unittest.skipUnless(_testenv.VER >= (2, 0, 1), "2.0.1 才有")
class NoRedTextInTry(unittest.TestCase):
    """〔2.0.1〕try { … } 裡讀檔、查詢的 cmdlet 一律 -ErrorAction Stop：它們的「非終止錯誤」try/catch 抓不到，
    會在主控台印紅字（2.0.0 第一次執行時 state.json 不存在；全新安裝時 config.json 不存在）。實際畫面由 entry_harness 檢查。"""
    CMDLETS = ("Get-Content", "Select-String", "Get-Item", "Get-ChildItem", "Remove-Item", "Copy-Item", "Move-Item",
               "Start-Transcript", "Get-CimInstance", "Get-AppxPackage")

    def test_cmdlets_in_try_stop(self):
        for f in (RUNTIME / "mm-sendto.ps1", INSTALL_PS1):
            for no, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):
                if not re.search(r"\btry\s*\{", line):
                    continue
                for c in self.CMDLETS:
                    if re.search(rf"\b{c}\b", line):
                        self.assertRegex(line, r"-ErrorAction\s+(Stop|SilentlyContinue)", f"{f.name}:{no} {c}")

    def test_read_state_checks_path_first(self):
        src = (RUNTIME / "mm-sendto.ps1").read_text(encoding="utf-8-sig")
        body = re.search(r"function Read-State \{(.*?)\n\}", src, re.S).group(1)
        self.assertLess(body.index("Test-Path -LiteralPath $StatePath"), body.index("Get-Content"))


if __name__ == "__main__":
    unittest.main()
