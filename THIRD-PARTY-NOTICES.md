# meeting-minutes 第三方元件與授權聲明

本 repo 包含 meeting-minutes-pro（Pro 版）與 meeting-minutes（基本版）。兩版本身只包含安裝程式、轉寫腳本與 skill 文件，
以 MIT License 授權（見 [`LICENSE`](LICENSE)）。下列元件都**不包含**在 repo 與安裝包內：Python 套件由安裝程式從 PyPI 安裝，
模型在安裝時從各自的官方來源下載，FFmpeg 由 winget 或 Homebrew 另行安裝。各元件的授權以其官方來源公布的條款為準，本文件只是摘要。

「適用」欄：**兩版**＝Pro 與基本版都用到；**Pro**＝只有 Pro 版用到。各版本目錄另附自己的 `THIRD-PARTY-NOTICES.md`（安裝時複製到 runtime 資料夾）。

## 推論引擎與函式庫

| 元件 | 用途 | 來源 | 授權 | 適用 |
|---|---|---|---|---|
| OpenVINO／OpenVINO GenAI | 推論引擎（Windows：Intel NPU／GPU／CPU） | https://github.com/openvinotoolkit/openvino.genai | Apache-2.0 | 兩版 |
| faster-whisper／CTranslate2 | 推論引擎（Windows：NVIDIA；macOS：CPU） | https://github.com/SYSTRAN/faster-whisper | MIT | 兩版 |
| NVIDIA cuBLAS／cuDNN（pip 套件） | CUDA 函式庫（只在 Windows 且有 NVIDIA 顯示卡時安裝） | https://pypi.org/project/nvidia-cublas-cu12/ 、https://pypi.org/project/nvidia-cudnn-cu12/ | NVIDIA 授權 | 兩版 |
| MLX／mlx-whisper | 推論引擎（macOS：Apple GPU） | https://github.com/ml-explore/mlx 、https://github.com/ml-explore/mlx-examples/tree/main/whisper | MIT | 兩版 |
| optimum-intel | Breeze 轉換成 OpenVINO 格式（只在安裝時暫用） | https://github.com/huggingface/optimum-intel | Apache-2.0 | Pro |
| sherpa-onnx | 說話者分離；CT-Transformer 標點模型的執行 | https://github.com/k2-fsa/sherpa-onnx | Apache-2.0 | 兩版（標點只有 Pro） |
| OpenCC（Python 實作） | 簡繁轉換 | https://github.com/BYVoid/OpenCC | Apache-2.0 | 兩版 |
| FFmpeg | 音訊與影片處理（由 winget 或 Homebrew 另行安裝） | https://ffmpeg.org/ | LGPL／GPL | 兩版 |

## 模型（安裝時下載，不包含在安裝包內）

| 元件 | 用途 | 來源 | 授權 | 適用 |
|---|---|---|---|---|
| Whisper large-v3-turbo（OpenVINO INT8、CTranslate2、MLX 版） | 語音辨識 | https://huggingface.co/OpenVINO/whisper-large-v3-turbo-int8-ov 、https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo 、https://huggingface.co/mlx-community/whisper-large-v3-turbo | MIT | 兩版 |
| Breeze-ASR-25（原始版、CTranslate2 版、MLX 版；選裝） | 台灣華語／中英夾雜語音辨識 | https://huggingface.co/MediaTek-Research/Breeze-ASR-25 、https://huggingface.co/shdennlin/breeze-asr-25-ct2 、https://huggingface.co/BRlin/Breeze-ASR-25-mlx-fp16 | Apache-2.0 | Pro |
| pyannote segmentation 3.0（sherpa-onnx 轉換版） | 語音分段 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models | MIT | 兩版 |
| 3D-Speaker ERes2Net（中文聲紋） | 說話者分離 | https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models | Apache-2.0 | 兩版 |
| CT-Transformer 標點模型 | 本機分段標點 | 見下一節 | FunASR Model Open Source License 1.1 | Pro |

## CT-Transformer 標點模型（Pro；安裝時下載，不包含在安裝包內）

- 模型名稱：CT-Transformer 標點－中文－通用（`punc_ct-transformer_zh-cn-common-vocab272727-pytorch`）
- 作者與來源：Alibaba Group 通義實驗室（FunASR），ModelScope：https://modelscope.cn/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-pytorch
- 本程式使用的版本：k2-fsa/sherpa-onnx 轉換的 ONNX int8 版 `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8`，
  下載自 https://github.com/k2-fsa/sherpa-onnx/releases/tag/punctuation-models
- 授權：FunASR Model Open Source License Agreement, Version 1.1（https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE）
  - 使用、複製、修改、分享時須註明出處與作者資訊，並保留模型名稱（第 2.2 條）。
  - 免責（第 3 條原文）：「[FunASR Software] is provided for reference and learning purposes only, and Alibaba Group assumes
    no responsibility for any direct or indirect losses resulting from your use or modification of [FunASR Software].
    You should assume all risks associated with using and modifying [FunASR Software].」
  - 授權方可修訂條款，修訂版公布於 FunASR 官方 repository 後自動生效（第 6 條）。
- 備註：ModelScope 模型頁的授權欄標示為 Apache License 2.0；本程式採較嚴格的 FunASR Model License 1.1 標示，
  兩者要求的標示（來源、作者、模型名稱）都已在本節滿足。

## 自動校正的 API 通道套件（Pro；選用，只在安裝時選了 API 通道才安裝）

| 元件 | 用途 | 來源 | 授權 |
|---|---|---|---|
| Anthropic Python SDK（`anthropic`） | 自動校正：Claude API 通道 | https://github.com/anthropics/anthropic-sdk-python | Apache-2.0 |
| OpenAI Python SDK（`openai`） | 自動校正：OpenAI API 通道 | https://github.com/openai/openai-python | Apache-2.0 |

兩個 SDK 的授權依各自 repository 的 `LICENSE`（Apache License 2.0）與 PyPI 上的授權標示確認。

訂閱通道使用你自己電腦上已安裝的 Claude Code（`claude` 指令）或 Codex（`codex` 指令），本程式不安裝、不散布它們；使用時適用各自的服務條款。

## pyannote.audio（Pro；選用：GPU 說話者分離，安裝時詢問）

- 用途：在 NVIDIA 顯示卡上做說話者分離（只在安裝時回答要安裝，或執行 `install.cmd -GpuDiar` 時安裝）
- 來源：https://github.com/pyannote/pyannote-audio （PyPI：`pyannote.audio`）
- 授權：MIT License（Copyright (c) 2020 CNRS；依套件內附的 `LICENSE` 確認）
- 本程式關閉了 pyannote.audio 的使用統計（`PYANNOTE_METRICS_ENABLED=0`），轉寫時也不連網（`HF_HUB_OFFLINE=1`）

## PyTorch（Pro；選用：同上）

- 用途：pyannote.audio 的執行環境（CUDA 版，從 https://download.pytorch.org/whl/ 安裝）
- 來源：https://pytorch.org ／ https://github.com/pytorch/pytorch
- 授權：BSD-3-Clause（PyTorch 的 `LICENSE`，含 Caffe2 等貢獻者的版權聲明；依套件內附的 `LICENSE`、`NOTICE` 與套件資訊確認）

## pyannote speaker-diarization-community-1 模型權重（Pro；選用；由使用者自行同意條件並下載，不包含在 repo 與安裝包內）

- 模型：pyannote/speaker-diarization-community-1（https://huggingface.co/pyannote/speaker-diarization-community-1）
- 作者：pyannote（pyannoteAI）；內含模型的引用：
  - 分段：Alexis Plaquet, Hervé Bredin. Powerset multi-class cross entropy loss for neural speaker diarization. Proc. INTERSPEECH 2023.
  - 講者特徵：Wang et al. Wespeaker: A research and production oriented speaker embedding learning toolkit. ICASSP 2023.
  - 分群：Landini et al. Bayesian HMM clustering of x-vector sequences (VBx) in speaker diarization. 2022.
- 授權：Creative Commons Attribution 4.0 International（CC-BY-4.0，https://creativecommons.org/licenses/by/4.0/）
- 使用條件：下載前須在 Hugging Face 登入並同意作者的使用條件（填寫公司或學校與用途；作者說明可能寄送 pyannote 的消息）；
  本程式不代為同意、不散布權重。下載後在權重資料夾的 `.mmp-source.json` 記錄來源、版本與下載時間。
- 本程式沒有修改權重。

## 測試用的合成素材

- `pro/tests/materials/` 的講稿與計分基準是自寫、虛構的內容，以本 repo 的 MIT License 提供。
- 合成語音由 `pro/tests/make_materials.py` 呼叫 edge-tts（Microsoft Edge 線上朗讀服務）在使用者自己的電腦上產生；
  本 repo **不散布**產生出來的音檔，使用 edge-tts 時適用該服務的條款。
