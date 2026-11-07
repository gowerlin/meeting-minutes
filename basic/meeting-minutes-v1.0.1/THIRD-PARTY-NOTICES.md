# meeting-minutes 1.0.1 第三方元件與授權聲明

meeting-minutes（基本版）本身只包含安裝程式、轉寫腳本與 skill 文件。下列元件都不包含在安裝包內：Python 套件由安裝程式從 PyPI 安裝，模型在安裝時從各自的官方來源下載，FFmpeg 由 winget 或 Homebrew 另行安裝。各元件的授權以其官方來源公布的條款為準，本文件只是摘要。

## 推論引擎與函式庫

| 元件 | 用途 | 來源 | 授權 |
|---|---|---|---|
| OpenVINO／OpenVINO GenAI | 推論引擎（Windows：Intel NPU／GPU／CPU） | https://github.com/openvinotoolkit/openvino.genai | Apache-2.0 |
| faster-whisper／CTranslate2 | 推論引擎（Windows：NVIDIA；macOS：CPU） | https://github.com/SYSTRAN/faster-whisper | MIT |
| NVIDIA cuBLAS／cuDNN（pip 套件） | CUDA 函式庫（只在 Windows 且有 NVIDIA 顯示卡時安裝） | https://pypi.org/project/nvidia-cublas-cu12/ 、https://pypi.org/project/nvidia-cudnn-cu12/ | NVIDIA 授權 |
| MLX／mlx-whisper | 推論引擎（macOS：Apple GPU） | https://github.com/ml-explore/mlx 、https://github.com/ml-explore/mlx-examples/tree/main/whisper | MIT |
| sherpa-onnx | 說話者分離 | https://github.com/k2-fsa/sherpa-onnx | Apache-2.0 |
| OpenCC（Python 實作） | 簡繁轉換 | https://github.com/BYVoid/OpenCC | Apache-2.0 |
| FFmpeg | 音訊與影片處理（由 winget 或 Homebrew 另行安裝） | https://ffmpeg.org/ | LGPL／GPL |

## 模型（安裝時下載，不包含在安裝包內）

| 元件 | 用途 | 來源 | 授權 |
|---|---|---|---|
| Whisper large-v3-turbo（OpenVINO INT8、CTranslate2、MLX 版） | 語音辨識 | https://huggingface.co/OpenVINO/whisper-large-v3-turbo-int8-ov 、https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo 、https://huggingface.co/mlx-community/whisper-large-v3-turbo | MIT |
| pyannote segmentation 3.0（sherpa-onnx 轉換版） | 語音分段 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models | MIT |
| 3D-Speaker ERes2Net（中文聲紋） | 說話者分離 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models | Apache-2.0 |

選用 `-Whisper large-v3`（macOS `--whisper large-v3`）時，改下載 Whisper large-v3 的對應版本（https://huggingface.co/OpenVINO/whisper-large-v3-int8-ov 、https://huggingface.co/Systran/faster-whisper-large-v3 、https://huggingface.co/mlx-community/whisper-large-v3-mlx ；MIT）。安裝時的測速樣本（`0-four-speakers-zh.wav`）下載自 https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models ，只在安裝時用來比較各後端的速度。
