"""ASR backends. Each exposes .transcribe(chunk: np.ndarray[float32, 16 kHz]) -> str.

- openvino : OpenVINO GenAI WhisperPipeline，device = NPU / GPU（Intel）/ CPU（任何 x86-64）
- ct2      : faster-whisper（CTranslate2），device = cuda（NVIDIA）或 cpu（macOS），compute_type 依硬體
- mlx      : mlx-whisper，device = gpu（Apple Silicon，Metal）
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import whisper_dir, whisper_ready  # noqa: E402


def _add_nvidia_dll_dirs():
    """pip 安裝的 nvidia-cublas-cu12 / nvidia-cudnn-cu12 DLL 不在 PATH 上，Windows 需手動加入。"""
    if sys.platform != "win32":
        return
    import site
    roots = [Path(p) for p in site.getsitepackages()] + [Path(site.getusersitepackages())]
    for root in roots:
        nv = root / "nvidia"
        if not nv.is_dir():
            continue
        for bin_dir in nv.glob("*/bin"):
            try:
                os.add_dll_directory(str(bin_dir))
            except (OSError, AttributeError):
                pass
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


class OpenVINOBackend:
    name = "openvino"

    def __init__(self, model: str, device: str, language: str | None, hotwords: str | None):
        import openvino_genai as ov_genai
        self.device = device
        self.pipe = ov_genai.WhisperPipeline(str(whisper_dir("openvino", model)), device)
        self.kw = {"task": "transcribe"}
        if language:
            self.kw["language"] = f"<|{language}|>"
        if hotwords:
            self.kw["hotwords"] = hotwords

    def transcribe(self, chunk) -> str:
        try:
            res = self.pipe.generate(chunk.tolist(), **self.kw)
        except Exception:  # noqa: BLE001 - 部分裝置不接受 hotwords，退回不帶提示
            self.kw.pop("hotwords", None)
            res = self.pipe.generate(chunk.tolist(), **self.kw)
        return str(res.texts[0]).strip()


class CT2Backend:
    name = "ct2"

    def __init__(self, model: str, device: str, language: str | None, hotwords: str | None,
                 compute_type: str = "default"):
        _add_nvidia_dll_dirs()
        from faster_whisper import WhisperModel
        self.device = device
        dev, _, idx = device.partition(":")          # "cuda" 或 "cuda:1"
        threads = 0 if dev == "cuda" else max(1, min(8, os.cpu_count() or 4))
        self.model = WhisperModel(str(whisper_dir("ct2", model)), device=dev, device_index=int(idx or 0),
                                  compute_type=compute_type, cpu_threads=threads)
        self.kw = {"language": language, "beam_size": 5, "vad_filter": False,
                   "condition_on_previous_text": False, "without_timestamps": True}
        if hotwords:
            self.kw["hotwords"] = hotwords

    def transcribe(self, chunk) -> str:
        segments, _ = self.model.transcribe(chunk, **self.kw)
        return "".join(s.text for s in segments).strip()


class MLXBackend:
    name = "mlx"
    PROMPT_MAX = 200   # Whisper prompt 有長度上限，過長的詞表也容易誘發幻覺

    def __init__(self, model: str, device: str, language: str | None, hotwords: str | None):
        import mlx_whisper
        self.device = device
        self._tx = mlx_whisper.transcribe
        self.path = str(whisper_dir("mlx", model))
        self.kw = {"verbose": None, "condition_on_previous_text": False}
        if language:
            self.kw["language"] = language
        if hotwords:   # mlx-whisper 沒有 hotwords，改用 initial_prompt 提示專有名詞
            self.kw["initial_prompt"] = (hotwords if len(hotwords) <= self.PROMPT_MAX
                                         else hotwords[: self.PROMPT_MAX].rsplit(",", 1)[0])
        import numpy as np
        self._tx(np.zeros(16000, dtype=np.float32), path_or_hf_repo=self.path, **self.kw)  # 預先載入模型

    def transcribe(self, chunk) -> str:
        return str(self._tx(chunk, path_or_hf_repo=self.path, **self.kw)["text"]).strip()


def create(backend: str, model: str, device: str, language: str | None = "zh",
           hotwords: str | None = None, compute_type: str = "default"):
    if not whisper_ready(backend, model):
        raise FileNotFoundError(f"缺少 {backend} 的 Whisper 模型（{model}），請重新執行 install.cmd")
    if backend == "openvino":
        return OpenVINOBackend(model, device, language, hotwords)
    if backend == "ct2":
        return CT2Backend(model, device, language, hotwords, compute_type)
    if backend == "mlx":
        return MLXBackend(model, device, language, hotwords)
    raise ValueError(f"未知的 backend：{backend}")
