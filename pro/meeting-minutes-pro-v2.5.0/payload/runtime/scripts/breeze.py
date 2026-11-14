"""Breeze-ASR-25／Breeze-ASR-26 的安裝時準備：各後端取得可用的模型格式。

Breeze-ASR-25（alias breeze）：
- ct2      ：下載 shdennlin/breeze-asr-25-ct2 中對應精度的子資料夾
- mlx      ：下載 BRlin/Breeze-ASR-25-mlx-fp16，並把 model.safetensors 改名為 mlx-whisper 0.4.x 要的 weights.safetensors
- openvino ：沒有現成版本 → 建立暫時 venv，用 optimum-intel 把原始模型轉成 OpenVINO INT8，轉完刪除暫時環境

〔2.5.0〕Breeze-ASR-26（alias breeze26；台語 → 台灣華語文字；規格 2.5.0 §3）：
- 官方只有 F32 權重（約 6.2 GB）、沒有 CTranslate2 版與 tokenizer.json。先查磁碟空間（common.BREEZE26_DISK_NEED），
  在 $MMH/_convert-breeze26/ 裡：固定 revision 下載官方權重 → 驗大小與 SHA-256 → 暫時 venv 轉換 →
  轉換結果檢查齊全後才搬到 models/ 底下 → 刪掉整個暫存資料夾（原始權重、暫時 venv）。
  任何一步失敗都不會在 models/ 留下半成品（whisper_ready() 不會誤判為可用），暫存資料夾也會刪掉。
- ct2      ：ct2-transformers-converter，精度規則同 Breeze-ASR-25（ct2_subfolder()）；用 transformers 產生 tokenizer.json
- openvino ：同 Breeze-ASR-25 的 optimum-intel 轉換，來源改用驗過雜湊的本機權重
- mlx      ：不提供

只在安裝時執行；轉寫時不會觸發任何下載或轉換。
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BREEZE26_DISK_NEED, BREEZE26_REVISION, BREEZE26_SOURCE, BREEZE26_WEIGHTS,  # noqa: E402
                    BREEZE_SOURCE, data_home, model_supported, whisper_dir, whisper_repo)

LABEL = {"breeze": "Breeze-ASR-25", "breeze26": "Breeze-ASR-26"}


def log(msg):
    print(msg, flush=True)


def ct2_subfolder(compute_type: str) -> str:
    if compute_type in ("float16", "int8_float16"):
        return compute_type
    return "int8"   # int8 / int8_float32 / float32（CTranslate2 會在載入時轉成指定精度）


def fetch_ct2(compute_type: str):
    from huggingface_hub import hf_hub_download, snapshot_download
    dst = whisper_dir("ct2", "breeze")
    sub = ct2_subfolder(compute_type)
    with tempfile.TemporaryDirectory(dir=data_home()) as td:
        log(f"  下載 Breeze-ASR-25（CTranslate2 / {sub}）")
        snapshot_download(whisper_repo("ct2", "breeze"), allow_patterns=[f"{sub}/*"], local_dir=td)
        src = Path(td) / sub
        if not (src / "model.bin").exists():
            raise RuntimeError(f"下載內容缺少 {sub}/model.bin")
        shutil.rmtree(dst, ignore_errors=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    for f in ("tokenizer.json", "preprocessor_config.json"):
        if not (dst / f).exists():
            hf_hub_download(BREEZE_SOURCE, f, local_dir=str(dst))


def fetch_mlx():
    from huggingface_hub import snapshot_download
    dst = whisper_dir("mlx", "breeze")
    log("  下載 Breeze-ASR-25（MLX fp16，約 3GB）")
    snapshot_download(whisper_repo("mlx", "breeze"), local_dir=str(dst))
    if not (dst / "weights.safetensors").exists() and (dst / "model.safetensors").exists():
        (dst / "model.safetensors").rename(dst / "weights.safetensors")


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _venv_bin(venv: Path, name: str) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin") / (name + (".exe" if sys.platform == "win32" else ""))


def _make_venv(work: Path, pkgs: list, env: dict, what: str) -> Path:
    log(f"  建立暫時轉換環境（{what}，完成後會刪除）")
    venv = work / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    vpy = str(_venv_python(venv))
    subprocess.run([vpy, "-m", "pip", "install", "-q", "-U", "pip", "--disable-pip-version-check"], check=True)
    # Windows 的 PyPI torch 本來就是 CPU 版；Linux 才需指定 CPU index，避免下載數 GB 的 CUDA 版
    if sys.platform.startswith("linux"):
        subprocess.run([vpy, "-m", "pip", "install", "-q", "torch", "--index-url",
                        "https://download.pytorch.org/whl/cpu", "--disable-pip-version-check"], check=True, env=env)
    subprocess.run([vpy, "-m", "pip", "install", "-q", *pkgs, "--disable-pip-version-check"], check=True, env=env)
    return venv


def _export_openvino(venv: Path, model_ref: str, out: Path, env: dict):
    subprocess.run([str(_venv_bin(venv, "optimum-cli")), "export", "openvino", "--model", model_ref,
                    "--task", "automatic-speech-recognition-with-past", "--weight-format", "int8", str(out)],
                   check=True, env=env)
    if not (out / "openvino_tokenizer.xml").exists():   # WhisperPipeline 需要 tokenizer IR
        subprocess.run([str(_venv_bin(venv, "convert_tokenizer")), model_ref, "--with-detokenizer",
                        "-o", str(out)], check=True, env=env)
    for need in ("openvino_encoder_model.xml", "openvino_decoder_model.xml", "openvino_tokenizer.xml",
                 "openvino_detokenizer.xml"):
        if not (out / need).exists():
            raise RuntimeError(f"轉換結果缺少 {need}")


def _openvino_pkgs() -> list:
    """openvino / openvino-tokenizers 版本對齊主環境，避免 IR 版本不相容。"""
    import openvino
    ov_ver = openvino.__version__.split("-")[0]           # 例：2026.4.1
    return ["optimum-intel[openvino]", f"openvino=={ov_ver}", f"openvino-tokenizers=={ov_ver}.*"]


def convert_openvino():
    """暫時 venv + optimum-intel 轉換；openvino / openvino-tokenizers 版本對齊主環境，避免 IR 版本不相容。"""
    pkgs = _openvino_pkgs()
    dst = whisper_dir("openvino", "breeze")
    work = data_home() / "_convert"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    env = dict(os.environ, HF_HOME=str(work / "hf"), PYTHONUTF8="1")
    try:
        venv = _make_venv(work, pkgs, env, "optimum-intel + PyTorch CPU，約 1GB")
        out = work / "out"
        log("  下載原始模型並轉換為 OpenVINO INT8（約 3GB 下載，需 10~20 分鐘）")
        _export_openvino(venv, BREEZE_SOURCE, out, env)
        shutil.rmtree(dst, ignore_errors=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dst))
        log(f"  [OK] 轉換完成：{dst}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- 〔2.5.0〕Breeze-ASR-26
B26_WORK = "_convert-breeze26"                     # $MMH 底下的暫存資料夾（與 Breeze-ASR-25 的 _convert 分開）
B26_PATTERNS = ["*.json", "*.txt", "*.safetensors"]  # 不下載 training_args.bin、README.md
B26_TRANSFORMERS = "transformers==4.57.6"          # 固定為 2.5.0 實測的版本，讓轉換結果可重現
B26_CT2_COPY = ("tokenizer_config.json", "preprocessor_config.json", "added_tokens.json", "special_tokens_map.json",
                "vocab.json", "merges.txt", "normalizer.json", "generation_config.json")
B26_CT2_NEED = ("model.bin", "config.json", "vocabulary.json", "tokenizer.json", "preprocessor_config.json")
B26_SOURCE_FILE = "breeze26-source.json"           # 記錄來源 revision、原始權重雜湊、轉換工具版本
GB = 10**9


class Breeze26Error(RuntimeError):
    """Breeze-ASR-26 準備失敗（訊息給使用者看）。"""


def b26_work_dir() -> Path:
    return data_home() / B26_WORK


def check_disk_26(need: int = BREEZE26_DISK_NEED) -> int:
    """可用空間不夠就丟 Breeze26Error（還沒下載任何東西）。回傳可用位元組。"""
    root = data_home()
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    if free < need:
        raise Breeze26Error(
            f"磁碟空間不足：{root} 所在的磁碟剩 {free / GB:.1f} GB，安裝 Breeze-ASR-26 需要約 {need / GB:.0f} GB"
            "（暫時下載官方權重約 6.2 GB＋轉換環境約 1.5 GB＋轉換後約 1.6 GB；完成後暫存檔會刪除，只留約 1.6 GB）。"
            "請清出空間後執行 setup_backend.py --breeze26-only 加裝")
    return free


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_weights_26(d: Path) -> dict:
    """官方權重的大小與 SHA-256 要等於 common.BREEZE26_WEIGHTS；回傳 {檔名: sha256}。"""
    got = {}
    for name, (size, sha) in BREEZE26_WEIGHTS.items():
        f = d / name
        if not f.is_file():
            raise Breeze26Error(f"下載內容缺少 {name}")
        if f.stat().st_size != size:
            raise Breeze26Error(f"{name} 大小不符（{f.stat().st_size} bytes，預期 {size}）")
        digest = sha256_file(f)
        if digest != sha:
            raise Breeze26Error(f"{name} 的 SHA-256 不符（{digest[:16]}…，預期 {sha[:16]}…）")
        got[name] = digest
    log("  [OK] 官方權重的大小與 SHA-256 驗證通過")
    return got


def download_official_26(dst: Path, env: dict):
    """在子行程下載（HF_HOME 指向暫存資料夾，快取也留在裡面、一起刪掉）。"""
    log(f"  下載 Breeze-ASR-26 官方權重（{BREEZE26_SOURCE}，revision {BREEZE26_REVISION[:12]}，約 6.2 GB；轉換後會刪除）")
    code = ("import sys\nfrom huggingface_hub import snapshot_download\n"
            "snapshot_download(sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3], allow_patterns=sys.argv[4:])\n")
    subprocess.run([sys.executable, "-c", code, BREEZE26_SOURCE, BREEZE26_REVISION, str(dst), *B26_PATTERNS],
                   check=True, env=env)


def _install_dir(out: Path, dst: Path):
    """轉換結果齊全後才搬進 models/（同一顆磁碟內改名）；原本有舊的目錄先改名、搬好後刪掉。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    old = dst.with_name(dst.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if dst.exists():
        os.replace(dst, old)
    shutil.move(str(out), str(dst))
    shutil.rmtree(old, ignore_errors=True)


def _write_source(out: Path, backend: str, weights: dict, tools: dict, extra: dict):
    info = {"model": "Breeze-ASR-26", "source": BREEZE26_SOURCE, "revision": BREEZE26_REVISION,
            "license": "Apache-2.0", "weights_sha256": weights, "backend": backend, **extra, "tools": tools,
            "converted_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    (out / B26_SOURCE_FILE).write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")


def _tool_versions(vpy: str, mods: tuple) -> dict:
    code = ("import importlib, json, sys\n"
            "print(json.dumps({m: importlib.import_module(m).__version__ for m in sys.argv[1:]}))\n")
    try:
        r = subprocess.run([vpy, "-c", code, *mods], check=True, capture_output=True, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:  # noqa: BLE001
        return {}


def convert_ct2_26(compute_type: str = "default"):
    import ctranslate2
    quant = ct2_subfolder(compute_type)
    dst = whisper_dir("ct2", "breeze26")
    work = b26_work_dir()
    check_disk_26()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    env = dict(os.environ, HF_HOME=str(work / "hf"), PYTHONUTF8="1", HF_HUB_DISABLE_TELEMETRY="1")
    try:
        src = work / "official"
        download_official_26(src, env)
        weights = verify_weights_26(src)
        venv = _make_venv(work, [f"ctranslate2=={ctranslate2.__version__}", B26_TRANSFORMERS, "torch"], env,
                          "CTranslate2 轉換工具 + PyTorch CPU，約 1.5GB")
        out = work / "out"
        log(f"  轉換為 CTranslate2（{quant}，與 Breeze-ASR-25 相同精度規則；約 1 分鐘）")
        subprocess.run([str(_venv_bin(venv, "ct2-transformers-converter")), "--model", str(src), "--output_dir", str(out),
                        "--quantization", quant, "--low_cpu_mem_usage", "--copy_files", *B26_CT2_COPY],
                       check=True, env=env)
        # 官方沒有 tokenizer.json（whisper_ready() 與 faster-whisper 要它）：用 transformers 從同一份 vocab 產生
        code = ("import sys\nfrom transformers import WhisperTokenizerFast\n"
                "WhisperTokenizerFast.from_pretrained(sys.argv[1]).backend_tokenizer.save(sys.argv[2])\n")
        vpy = str(_venv_python(venv))
        subprocess.run([vpy, "-c", code, str(src), str(out / "tokenizer.json")], check=True, env=env)
        missing = [n for n in B26_CT2_NEED if not (out / n).is_file()]
        if missing:
            raise Breeze26Error(f"轉換結果缺少 {'、'.join(missing)}")
        _write_source(out, "ct2", weights, _tool_versions(vpy, ("ctranslate2", "transformers", "torch")),
                      {"quantization": quant, "model_bin_sha256": sha256_file(out / "model.bin")})
        _install_dir(out, dst)
        log(f"  [OK] 轉換完成：{dst}")
    finally:
        _cleanup_26(work)


def convert_openvino_26():
    pkgs = _openvino_pkgs()
    dst = whisper_dir("openvino", "breeze26")
    work = b26_work_dir()
    check_disk_26()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    env = dict(os.environ, HF_HOME=str(work / "hf"), PYTHONUTF8="1", HF_HUB_DISABLE_TELEMETRY="1")
    try:
        src = work / "official"
        download_official_26(src, env)
        weights = verify_weights_26(src)
        venv = _make_venv(work, pkgs, env, "optimum-intel + PyTorch CPU，約 1.5GB")
        out = work / "out"
        log("  轉換為 OpenVINO INT8（需 10~20 分鐘）")
        _export_openvino(venv, str(src), out, env)
        _write_source(out, "openvino", weights,
                      _tool_versions(str(_venv_python(venv)), ("optimum.intel", "openvino", "transformers", "torch")),
                      {"weight_format": "int8"})
        _install_dir(out, dst)
        log(f"  [OK] 轉換完成：{dst}")
    finally:
        _cleanup_26(work)


def _cleanup_26(work: Path):
    shutil.rmtree(work, ignore_errors=True)
    if work.exists():
        log(f"  [!] 暫存資料夾沒有刪乾淨（可能有檔案被占用），可手動刪除：{work}")


def remove_26(backend: str) -> bool:
    """移除 Breeze-ASR-26 的模型目錄（回退用）；config.json 的 profiles.breeze26 由 setup_backend.py --remove-breeze26 處理。"""
    d = whisper_dir(backend, "breeze26")
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    return not d.exists()


def ensure(backend: str, compute_type: str = "default", alias: str = "breeze"):
    from common import whisper_ready
    label = LABEL[alias]
    if alias == "breeze26" and not model_supported(backend, alias):
        raise Breeze26Error(f"本版不提供 {backend} 後端的 Breeze-ASR-26（只提供 ct2 與 openvino）")
    if whisper_ready(backend, alias):
        log(f"[OK] {label} [{backend}] 已存在")
        return
    if alias == "breeze26":
        if backend == "ct2":
            convert_ct2_26(compute_type)
        else:
            convert_openvino_26()
    elif backend == "ct2":
        fetch_ct2(compute_type)
    elif backend == "mlx":
        fetch_mlx()
    elif backend == "openvino":
        convert_openvino()
    else:
        raise ValueError(backend)
    if not whisper_ready(backend, alias):
        raise RuntimeError(f"{label} [{backend}] 準備失敗")
    log(f"[OK] {label} [{backend}]：{whisper_dir(backend, alias)}")
