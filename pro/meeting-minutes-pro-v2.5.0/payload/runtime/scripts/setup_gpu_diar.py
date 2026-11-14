"""〔2.0.0〕GPU 說話者分離（pyannote，選用安裝）的 Hugging Face 引導、權重下載與實測（規格 §8.2 步驟 4～7、§8.3、§8.4）。

在 GPU venv（$MMH/venv-gpu-diar）執行；安裝程式（install.ps1）建好 venv、裝好 PyTorch 與 pyannote 之後呼叫：

  venv-gpu-diar\\Scripts\\python.exe -B setup_gpu_diar.py --check-torch   # 步驟 4：PyTorch 是不是 CUDA 版、抓不抓得到顯示卡
  venv-gpu-diar\\Scripts\\python.exe -B setup_gpu_diar.py --prepare       # 步驟 5～6：Hugging Face 登入與條件、下載權重
  venv-gpu-diar\\Scripts\\python.exe -B setup_gpu_diar.py --smoke         # 步驟 7：用範例音檔實跑一次 diarize_pyannote.py
  venv-gpu-diar\\Scripts\\python.exe -B setup_gpu_diar.py                 # 單獨執行：補做 5～7，並把結果寫進 config.json
  python -B setup_gpu_diar.py --set-status none|incomplete|ready [--reason <代碼>]   # 只改 config.json（任何 venv 都可以）

- 給人看的訊息一律寫 stderr；stdout 只有最後一行 JSON（安裝程式讀這一行）：
  {"gpu_diar": {"status": "ready"|"incomplete"|"ok", "reason": <代碼或 null>, "step": …, …}}
  exit 0＝這一步成功；1＝未完成（reason 見規格 §8.5）；2＝參數錯誤。
- 不讀、不印、不保存 Hugging Face 權杖：登入與否只用 huggingface_hub 的 whoami() 判斷（權杖由 huggingface_hub 自己讀），
  不讀 HF_TOKEN 的值；登入交給 `hf auth login` 在同一個主控台自己讀取權杖。不印帳號資訊。
- 權重已經完整在本機（例如之前下載過）→ 不需要登入，直接略過登入與下載（2.0.0 與規格草案的差異）。
- 〔2.0.0〕給非技術人員的引導：沒登入時先白話說明，可開瀏覽器一步一步完成（帳號 → 同意條件 → 存取碼 → 貼上）；
  已登入且已同意時不印引導，直接下載。開瀏覽器（open_url）與 hf auth login（run_hf_login）可在測試中換成假的。
- 只用 Python 標準函式庫與 huggingface_hub（GPU venv 有）；不 import 主 runtime 的套件（common.py 只用標準函式庫）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import (CONFIG_UNREADABLE_EXIT, PYANNOTE_MODEL_FILES,  # noqa: E402
                    config_path, config_write_refused_message, load_config_for_write, pyannote_model_dir,
                    read_config, sample_wav, utf8_console)

REPO = "pyannote/speaker-diarization-community-1"
REPO_URL = f"https://huggingface.co/{REPO}"
TOKENS_URL = "https://huggingface.co/settings/tokens"
SOURCE_FILE = ".mmp-source.json"
STATUSES = ("none", "incomplete", "ready")
REASON_TEXT = {      # 規格 §8.5（安裝摘要與入口共用的中文說明）
    "driver_too_old": "顯示卡驅動太舊（需要 570 以上）", "low_disk": "磁碟空間不足（需要 8 GB 以上）",
    "no_nvidia_smi": "找不到 nvidia-smi", "pip_failed": "PyTorch 或 pyannote 安裝失敗",
    "torch_cpu": "裝到的 PyTorch 不是 CUDA 版", "cuda_unavailable": "PyTorch 抓不到顯示卡",
    "hf_not_logged_in": "還沒有登入 Hugging Face", "hf_not_approved": "還沒有在 Hugging Face 同意模型的使用條件",
    "download_failed": "權重下載失敗", "model_incomplete": "權重檔不完整", "smoke_failed": "實測失敗",
}
SMOKE_TIMEOUT = 600


def say(msg: str = ""):
    print(msg, file=sys.stderr, flush=True)


def result(step: str, status: str, reason: str | None = None, code: int | None = None, **extra) -> int:
    """印最後一行 JSON，回傳 exit code。"""
    print(json.dumps({"gpu_diar": dict({"status": status, "reason": reason, "step": step}, **extra)}, ensure_ascii=False),
          flush=True)
    if code is not None:
        return code
    return 0 if reason is None else 1


def model_missing(d: Path | None = None) -> list:
    """權重目錄缺的檔（不存在或 0 位元組）。"""
    d = d or pyannote_model_dir()
    return [f for f in PYANNOTE_MODEL_FILES if not (d / f).is_file() or (d / f).stat().st_size == 0]


# ---------------------------------------------------------------- 步驟 4：PyTorch
def check_torch() -> dict:
    try:
        import torch
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "reason": "pip_failed", "torch": None, "detail": type(ex).__name__}
    ver = str(torch.__version__)
    info = {"torch": ver, "cuda": False, "capability": None, "gpu_name": None}
    if not ver.endswith("+cu128"):
        return dict(info, ok=False, reason="torch_cpu")
    try:
        ok = bool(torch.cuda.is_available())
        if ok:
            info.update(cuda=True, capability=list(torch.cuda.get_device_capability()),
                        gpu_name=torch.cuda.get_device_name(0))
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        return dict(info, ok=False, reason="cuda_unavailable")
    return dict(info, ok=True, reason=None)


# ---------------------------------------------------------------- 步驟 5：Hugging Face 登入（不讀權杖值）
def logged_in(api) -> bool | None:
    """True＝已登入；False＝沒登入；None＝連不上（網路問題，無法判斷）。"""
    from huggingface_hub.errors import HfHubHTTPError, LocalTokenNotFoundError
    try:
        api.whoami()                                   # 回傳的帳號資訊不印、不存
        return True
    except LocalTokenNotFoundError:
        return False
    except HfHubHTTPError as ex:
        status = getattr(getattr(ex, "response", None), "status_code", None)
        return False if status in (401, 403) else None
    except OSError:                                    # requests 的連線錯誤是 OSError 的子類
        return None


def hf_cli() -> list:
    """`hf` 指令：GPU venv 的 Scripts／bin 裡的 hf(.exe)；找不到就用 python -m huggingface_hub.cli.hf。"""
    d = Path(sys.executable).parent
    for name in ("hf.exe", "hf"):
        if (d / name).is_file():
            return [str(d / name)]
    return [sys.executable, "-m", "huggingface_hub.cli.hf"]


def ask(prompt: str) -> str | None:
    """印提示、讀一行。沒有輸入可讀（stdin 已結束，例如無人值守的安裝）回傳 None。"""
    sys.stderr.write(prompt)
    sys.stderr.flush()
    try:
        line = sys.stdin.readline()
    except (OSError, ValueError):
        line = ""
    if not line:
        say("（沒有輸入，當作 n）")
        return None
    return line.strip()


def yes(prompt: str) -> bool:
    """[Y/n]：Enter＝是；沒有輸入可讀時當作否（不在無人值守時開瀏覽器或登入）。"""
    a = ask(prompt)
    return a is not None and a[:1] not in ("n", "N")


def open_url(url: str) -> bool:
    """〔2.0.0〕用預設瀏覽器開網址（不帶任何帳號資訊）；開不了回傳 False。測試時換成假的函式。"""
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001
        return False


def run_hf_login() -> None:
    """執行 hf auth login：權杖由 hf 自己讀取並存到 Hugging Face 的預設位置；本程式不擷取它的輸入。
    stdout 導到 stderr：安裝程式只讀本程式的 stdout。測試時換成假的函式。"""
    try:
        subprocess.run(hf_cli() + ["auth", "login"], stdout=sys.stderr, check=False)
    except OSError as ex:
        say(f"    [!] 無法執行 hf auth login（{type(ex).__name__}）")


# 〔2.0.0〕給非技術人員的引導（白話、每步一行、編號；規格 §8.3 的擴充）
INTRO = [
    "  ── 下載 GPU 說話者分離的模型（需要 Hugging Face 帳號，免費）──",
    "  Hugging Face 是放 AI 模型的網站。這個模型的作者要求使用者先登入、同意使用條件，才能下載，",
    "  所以需要你自己的帳號（免費）。本程式只用來下載模型，不會讀取或保存你的帳號資料。",
]
STEP_ACCOUNT = [
    "  步驟 1／4　註冊或登入 Hugging Face",
    "    已經有帳號就直接登入；沒有帳號：填電子郵件與密碼註冊，再到信箱點確認信。",
]
# 表單欄位依模型卡的 extra_gated_fields（2.0.0 實作時查：Company/university 文字、Use case 下拉選單）；畫面上的按鈕文字未實際確認
STEP_CONSENT = [
    "  步驟 2／4　同意模型的使用條件",
    "    在模型頁面上方找到「You need to agree to share your Hugging Face information to access this model」那一區，填兩欄：",
    "    - Company/university（公司或學校）：個人使用填「個人」或「Personal」即可",
    "    - Use case（用途，下拉選單）：選「Meeting note taker …」（會議記錄）；整理課程可選「Training and development …」，",
    "      不確定就選「Other」",
    "    填好後按同意的按鈕（英文，例如 Agree…）。",
    "    你填的資料會交給模型作者（pyannote）；作者說明可能偶爾寄送 pyannote 的消息與付費服務資訊。",
    "    同意後通常立刻可以下載；偶爾要等幾分鐘。",
]
STEP_TOKEN = [
    "  步驟 3／4　建立「存取碼」（Hugging Face 叫它 Access Token，是一組像密碼的字串，用來讓本程式代你下載模型）",
    "    按「Create new token」→ 類型（Token type）選「Read」→ 名稱填例如 meeting-minutes-pro → 按建立。",
    "    畫面會顯示一串 hf_ 開頭的字：按旁邊的複製鈕複製起來（只會顯示一次；忘了可以再建一個）。",
]
STEP_PASTE = [   # huggingface_hub 2.x 的 hf auth login：先問登入方式（方向鍵選單），再問存取碼（2.0.0 實作時讀 2.4.0 原始碼確認）
    "  步驟 4／4　登入（把存取碼貼進來）",
    "    接下來 Hugging Face 的登入程式會問「How would you like to log in?」（要怎麼登入）：",
    "    - 按方向鍵 ↓ 選「Paste an access token」（貼上存取碼）再按 Enter；也可以直接按數字 2",
    "    - 出現「Enter your token (input will not be visible):」時貼上存取碼：Windows Terminal 按 Ctrl＋V；舊式黑色視窗按滑鼠右鍵",
    "    - 貼上時畫面不會顯示任何字，這是正常的；貼完直接按 Enter",
    "    （另一個選項「Log in with your browser」會給一個網址和代碼，在瀏覽器登入後輸入代碼即可，不必自己建存取碼；",
    "      這個方式本程式還沒實測，不確定能不能下載需要同意條件的模型）",
    "    存取碼只由 Hugging Face 的登入程式保存在你的電腦；本程式不會讀取或保存它。",
]
JOIN_URL = "https://huggingface.co/join"


def show(lines):
    for line in lines:
        say(line)


def visit(url: str, browser: bool, lines: list):
    """印出這一步的說明與網址；要開瀏覽器時開啟並等使用者按 Enter。"""
    show(lines)
    opened = browser and open_url(url)
    if opened:
        say(f"    已在瀏覽器開啟：{url}")
    else:
        if browser:
            say("    沒辦法自動開啟瀏覽器，請自己開啟下面的網址：")
        say(f"    網址：{url}（Windows Terminal 可按住 Ctrl 點網址開啟，或複製到瀏覽器）")
    if browser:
        ask("    完成後按 Enter 繼續 ")
    say("")


def guide_login(api) -> str | None:
    """沒登入：說明 → 可開瀏覽器（帳號 → 同意 → 存取碼）→ hf auth login。回傳 None＝已登入；否則 reason。"""
    show(INTRO)
    browser = yes("  要幫你開啟瀏覽器，一步一步完成嗎？[Y/n] ")
    say("")
    if browser and not yes("  已經有 Hugging Face 帳號了嗎？[Y/n] "):
        visit(JOIN_URL, True, STEP_ACCOUNT)
    elif not browser:
        show(STEP_ACCOUNT)
        say(f"    網址：{JOIN_URL}")
        say("")
    visit(REPO_URL, browser, STEP_CONSENT)
    visit(TOKENS_URL, browser, STEP_TOKEN)
    show(STEP_PASTE)
    if not yes("  現在登入？[Y/n] "):
        say("    [!] 沒有登入：GPU 說話者分離這次沒有完成，說話者分離照舊用 CPU（不影響其他功能）。")
        say("        之後照上面的步驟完成，再執行 install.cmd -GpuDiar 即可補上。")
        return "hf_not_logged_in"
    run_hf_login()
    if logged_in(api) is True:
        return None
    say("    [!] 還是沒有登入（可能存取碼沒有貼完整，或按了 Ctrl＋C）：GPU 說話者分離這次沒有完成，說話者分離照舊用 CPU。")
    say("        之後執行 install.cmd -GpuDiar 再試一次（只會補做登入與下載）。")
    return "hf_not_logged_in"


def ensure_login(api) -> str | None:
    """回傳 None＝已登入；否則回傳 reason。已登入時不印引導。"""
    state = logged_in(api)
    if state is None:
        say("    [!] 連不上 Hugging Face（https://huggingface.co）：請確認網路可以連線，之後執行 install.cmd -GpuDiar 再試一次。")
        say("        這次說話者分離照舊用 CPU（不影響其他功能）。")
        return "download_failed"
    if state is False:
        reason = guide_login(api)
        if reason:
            return reason
    return None


# ---------------------------------------------------------------- 步驟 6：下載權重
NOT_APPROVED = [
    "    [!] 還沒辦法下載：還沒按同意使用條件，或剛按完、作者那邊還要幾分鐘才生效。",
    f"        請確認已在 {REPO_URL} 填表並按同意，過幾分鐘後執行 install.cmd -GpuDiar 再試一次。",
    "        這次說話者分離照舊用 CPU（不影響其他功能）。",
]


def fetch(dest: Path) -> str | None:
    """snapshot_download 一次。回傳 None＝成功；否則 reason。"""
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError
    try:
        snapshot_download(REPO, local_dir=str(dest))
    except GatedRepoError:
        return "hf_not_approved"
    except HfHubHTTPError as ex:
        status = getattr(getattr(ex, "response", None), "status_code", None)
        if status in (401, 403):
            return "hf_not_approved"
        say(f"    [!] 模型下載失敗（伺服器回應 {status}）")
        return "download_failed"
    except (OSError, ValueError) as ex:
        say(f"    [!] 模型下載失敗（{type(ex).__name__}，多半是網路中斷）")
        return "download_failed"
    return None


def download(api, dest: Path) -> str | None:
    say("    [OK] 已登入，正在下載權重（約 33 MB）…")
    reason = fetch(dest)
    if reason == "hf_not_approved":
        # 登入了但還沒同意：再給一次機會（可開瀏覽器到同意頁），按完 Enter 重試一次
        say("    還沒辦法下載：這個模型要先在網頁上同意使用條件。")
        if yes("  要幫你開啟同意頁面嗎？[Y/n] "):
            visit(REPO_URL, True, STEP_CONSENT)
        else:
            visit(REPO_URL, False, STEP_CONSENT)
            ask("    同意好了按 Enter 再試一次 ")
        say("    再試一次下載 …")
        reason = fetch(dest)
        if reason == "hf_not_approved":
            show(NOT_APPROVED)
            return reason
    if reason == "download_failed":
        say("        之後確認網路可以連線，執行 install.cmd -GpuDiar 再試一次；這次說話者分離照舊用 CPU（不影響其他功能）。")
        return reason
    missing = model_missing(dest)
    if missing:
        say(f"    [!] 權重檔不完整（缺 {'、'.join(missing)}）；之後執行 install.cmd -GpuDiar 再試一次")
        return "model_incomplete"
    revision = None
    try:
        revision = api.model_info(REPO).sha
    except Exception:  # noqa: BLE001  拿不到 revision 不影響使用
        pass
    src = {"repo": REPO, "revision": revision,
           "downloaded_at": datetime.now().astimezone().isoformat(timespec="seconds"), "license": "cc-by-4.0"}
    (dest / SOURCE_FILE).write_text(json.dumps(src, ensure_ascii=False, indent=1), encoding="utf-8")
    say("    [OK] 權重已存在本機，之後轉寫不需要登入；要登出可執行 hf auth logout（不影響使用）")
    return None


def prepare() -> tuple:
    """步驟 5～6。回傳 (reason 或 None, extra)。"""
    dest = pyannote_model_dir()
    if not model_missing(dest):
        say(f"    [OK] 權重已存在本機：{dest}（不需要 Hugging Face 登入）")
        return None, {"model": "present"}
    try:
        from huggingface_hub import HfApi
    except Exception as ex:  # noqa: BLE001
        say(f"    [!] GPU venv 沒有 huggingface_hub（{type(ex).__name__}）；執行 install.cmd -GpuDiar 重新安裝")
        return "pip_failed", {}
    api = HfApi()
    reason = ensure_login(api)
    if reason:
        return reason, {}
    dest.mkdir(parents=True, exist_ok=True)
    reason = download(api, dest)
    return reason, ({"model": "downloaded"} if reason is None else {})


# ---------------------------------------------------------------- 步驟 7：實測
def smoke() -> tuple:
    """用 sherpa 範例音檔跑一次 diarize_pyannote.py（離線、關閉遙測）。回傳 (reason 或 None, extra)。"""
    wav = sample_wav()
    if not wav.is_file():
        say(f"    [!] 找不到範例音檔 {wav}，無法實測；重新執行 install.cmd -GpuDiar")
        return "smoke_failed", {"detail": "sample_missing"}
    if model_missing():
        return "model_incomplete", {}
    out = pyannote_model_dir().parent / "gpu-diar-smoke.json"
    env = dict(os.environ, HF_HUB_OFFLINE="1", PYANNOTE_METRICS_ENABLED="0", PYTHONDONTWRITEBYTECODE="1")
    cmd = [sys.executable, "-B", str(HERE / "diarize_pyannote.py"), "--wav", str(wav),
           "--model-dir", str(pyannote_model_dir()), "--out", str(out), "--device", "cuda"]
    say("    實測：用範例音檔跑一次 GPU 說話者分離 …")
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=SMOKE_TIMEOUT)
        code = p.returncode
    except subprocess.TimeoutExpired:
        code = "timeout"
    sec = round(time.perf_counter() - t0, 1)
    data = {}
    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    finally:
        try:
            out.unlink()
        except OSError:
            pass
    if code == 0 and data.get("ok") and data.get("segments"):
        extra = {"smoke_sec": sec, "speakers": data.get("speakers"), "gpu_name": data.get("gpu_name"),
                 "torch": data.get("torch"), "pyannote": data.get("pyannote")}
        say(f"    [OK] 實測通過（{sec} 秒，{data.get('gpu_name') or 'GPU'}）")
        return None, extra
    detail = data.get("reason") or ("timeout" if code == "timeout" else f"exit {code}")
    say(f"    [!] 實測失敗（{detail}）；說話者分離照舊用 CPU。詳見 install.log，或回報問題")
    return "smoke_failed", {"detail": detail, "smoke_sec": sec}


# ---------------------------------------------------------------- config.json
def set_status(status: str, reason: str | None = None) -> dict:
    """只改 diarization.pyannote.status／reason（其他鍵不動；區塊不存在時只建這兩個鍵，其餘由 upgrade_config() 補）。
    〔2.4.1〕config.json 存在但讀不了 → 丟 ConfigUnreadable，不寫（原檔不動）。"""
    cfg = load_config_for_write()
    d = cfg.setdefault("diarization", {})
    if not isinstance(d, dict):
        d = cfg["diarization"] = {}
    p = d.setdefault("pyannote", {})
    if not isinstance(p, dict):
        p = d["pyannote"] = {}
    p["status"] = status
    p["reason"] = reason if status != "ready" else None
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def main(argv=None) -> int:
    utf8_console()
    ap = argparse.ArgumentParser(description="GPU 說話者分離（pyannote）的登入引導、權重下載與實測")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check-torch", action="store_true")
    g.add_argument("--prepare", action="store_true")
    g.add_argument("--smoke", action="store_true")
    g.add_argument("--set-status", choices=STATUSES)
    ap.add_argument("--reason", default=None)
    args = ap.parse_args(argv)
    if not (args.check_torch or args.prepare or args.smoke):   # 〔2.4.1〕會寫 config.json 的兩種用法：讀不了就先停
        rc = read_config()
        if rc["status"] == "unreadable":
            say("    [錯誤] " + config_write_refused_message(rc))
            return result("set_status" if args.set_status else "all", "incomplete", "config_unreadable",
                          code=CONFIG_UNREADABLE_EXIT)
    if args.set_status:
        p = set_status(args.set_status, args.reason)
        return result("set_status", p["status"], None, code=0, saved_reason=p["reason"])
    if args.check_torch:
        info = check_torch()
        return result("check_torch", "ok" if info["ok"] else "incomplete", info["reason"],
                      **{k: v for k, v in info.items() if k not in ("ok", "reason")})
    if args.prepare:
        reason, extra = prepare()
        return result("prepare", "ok" if reason is None else "incomplete", reason, **extra)
    if args.smoke:
        reason, extra = smoke()
        return result("smoke", "ready" if reason is None else "incomplete", reason, **extra)
    # 單獨執行：補做步驟 5～7，寫進 config.json
    reason, extra = prepare()
    if reason is None:
        reason, extra2 = smoke()
        extra.update(extra2)
    status = "ready" if reason is None else "incomplete"
    set_status(status, reason)
    say(f"    config.json：diarization.pyannote.status = {status}" + (f"（{reason}：{REASON_TEXT.get(reason, reason)}）"
                                                                      if reason else ""))
    return result("all", status, reason, **extra)


if __name__ == "__main__":
    sys.exit(main())
