"""Breeze-ASR-25 的安裝時準備：各後端取得可用的模型格式。

- ct2      ：下載 shdennlin/breeze-asr-25-ct2 中對應精度的子資料夾
- mlx      ：下載 BRlin/Breeze-ASR-25-mlx-fp16，並把 model.safetensors 改名為 mlx-whisper 0.4.x 要的 weights.safetensors
- openvino ：沒有現成版本 → 建立暫時 venv，用 optimum-intel 把原始模型轉成 OpenVINO INT8，轉完刪除暫時環境

只在安裝時執行；轉寫時不會觸發任何下載或轉換。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BREEZE_SOURCE, data_home, whisper_dir, whisper_repo  # noqa: E402


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


def convert_openvino():
    """暫時 venv + optimum-intel 轉換；openvino / openvino-tokenizers 版本對齊主環境，避免 IR 版本不相容。"""
    import openvino
    ov_ver = openvino.__version__.split("-")[0]           # 例：2026.4.1
    dst = whisper_dir("openvino", "breeze")
    work = data_home() / "_convert"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    env = dict(os.environ, HF_HOME=str(work / "hf"), PYTHONUTF8="1")
    try:
        log("  建立暫時轉換環境（optimum-intel + PyTorch CPU，約 1GB，完成後會刪除）")
        venv = work / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        vpy = str(_venv_python(venv))
        subprocess.run([vpy, "-m", "pip", "install", "-q", "-U", "pip", "--disable-pip-version-check"], check=True)
        pkgs = ["optimum-intel[openvino]", f"openvino=={ov_ver}", f"openvino-tokenizers=={ov_ver}.*"]
        # Windows 的 PyPI torch 本來就是 CPU 版；Linux 才需指定 CPU index，避免下載數 GB 的 CUDA 版
        if sys.platform.startswith("linux"):
            subprocess.run([vpy, "-m", "pip", "install", "-q", "torch", "--index-url",
                            "https://download.pytorch.org/whl/cpu", "--disable-pip-version-check"], check=True, env=env)
        subprocess.run([vpy, "-m", "pip", "install", "-q", *pkgs, "--disable-pip-version-check"], check=True, env=env)

        out = work / "out"
        log("  下載原始模型並轉換為 OpenVINO INT8（約 3GB 下載，需 10~20 分鐘）")
        subprocess.run([str(_venv_bin(venv, "optimum-cli")), "export", "openvino", "--model", BREEZE_SOURCE,
                        "--task", "automatic-speech-recognition-with-past", "--weight-format", "int8", str(out)],
                       check=True, env=env)
        if not (out / "openvino_tokenizer.xml").exists():   # WhisperPipeline 需要 tokenizer IR
            subprocess.run([str(_venv_bin(venv, "convert_tokenizer")), BREEZE_SOURCE, "--with-detokenizer",
                            "-o", str(out)], check=True, env=env)
        for need in ("openvino_encoder_model.xml", "openvino_decoder_model.xml", "openvino_tokenizer.xml",
                     "openvino_detokenizer.xml"):
            if not (out / need).exists():
                raise RuntimeError(f"轉換結果缺少 {need}")
        shutil.rmtree(dst, ignore_errors=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(out), str(dst))
        log(f"  [OK] 轉換完成：{dst}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def ensure(backend: str, compute_type: str = "default"):
    from common import whisper_ready
    if whisper_ready(backend, "breeze"):
        log(f"[OK] Breeze-ASR-25 [{backend}] 已存在")
        return
    if backend == "ct2":
        fetch_ct2(compute_type)
    elif backend == "mlx":
        fetch_mlx()
    elif backend == "openvino":
        convert_openvino()
    else:
        raise ValueError(backend)
    if not whisper_ready(backend, "breeze"):
        raise RuntimeError(f"Breeze-ASR-25 [{backend}] 準備失敗")
    log(f"[OK] Breeze-ASR-25 [{backend}]：{whisper_dir(backend, 'breeze')}")
