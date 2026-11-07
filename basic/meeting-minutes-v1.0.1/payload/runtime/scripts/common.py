"""Shared paths, model registry and config for the meeting-minutes runtime.

設計原則：硬體偵測與測速只在安裝時（setup_backend.py）做一次，結果寫進 config.json；
轉寫時（transcribe.py）只照 config 載入，不再即時偵測。
"""
import json
import os
import sys
from pathlib import Path

VERSION = "1.0.1"

# backend -> alias -> Hugging Face repo id
WHISPER_MODELS = {
    "openvino": {   # Intel NPU / Intel GPU / 任何 x86-64 CPU（含 AMD）
        "turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
        "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
        "base": "OpenVINO/whisper-base-int8-ov",
    },
    "ct2": {        # faster-whisper / CTranslate2：NVIDIA CUDA，或 macOS 上的 CPU（Apple Accelerate）
        "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "large-v3": "Systran/faster-whisper-large-v3",
        "base": "Systran/faster-whisper-base",
    },
    "mlx": {        # mlx-whisper：Apple Silicon GPU（Metal）
        "turbo": "mlx-community/whisper-large-v3-turbo",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "base": "mlx-community/whisper-base-mlx",
    },
}
BACKENDS = tuple(WHISPER_MODELS)
DEFAULT_WHISPER = "turbo"

SEG_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
EMB_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
SAMPLE_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
              "speaker-segmentation-models/0-four-speakers-zh.wav")


def utf8_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # Windows console (cp950) safety
        except Exception:  # noqa: BLE001
            pass


def data_home() -> Path:
    """Runtime root. Override with MEETING_MINUTES_HOME."""
    env = os.environ.get("MEETING_MINUTES_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "meeting-minutes"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "meeting-minutes"
    return Path.home() / ".cache" / "meeting-minutes"


def models_dir() -> Path:
    return data_home() / "models"


def whisper_repo(backend: str, alias_or_repo: str) -> str:
    return WHISPER_MODELS.get(backend, {}).get(alias_or_repo, alias_or_repo)


def whisper_dir(backend: str, alias_or_repo: str) -> Path:
    return models_dir() / backend / whisper_repo(backend, alias_or_repo).split("/")[-1]


def whisper_ready(backend: str, alias: str) -> bool:
    d = whisper_dir(backend, alias)
    if backend == "openvino":
        return (d / "openvino_encoder_model.xml").exists()
    if backend == "mlx":
        return (d / "config.json").exists() and any((d / w).exists() for w in ("weights.safetensors", "weights.npz"))
    return (d / "model.bin").exists()


def seg_model() -> Path:
    return models_dir() / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"


def emb_model() -> Path:
    return models_dir() / EMB_URL.rsplit("/", 1)[-1]


def sample_wav() -> Path:
    return data_home() / "samples" / "four-speakers-zh.wav"


def default_glossary() -> Path:
    return data_home() / "glossary.txt"


def config_path() -> Path:
    return data_home() / "config.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_config(**kw):
    cfg = load_config()
    cfg.update(kw)
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
