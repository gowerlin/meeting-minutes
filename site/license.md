---
title: 授權與第三方元件
description: meeting-minutes 的授權（MIT）、用到的第三方元件與授權，以及模型與權重不在安裝包內的說明。
---

# 授權與第三方元件

## 本程式的授權

meeting-minutes-pro 與基本版 meeting-minutes 以 **MIT License** 授權，全文見 repo 的 <RepoLink path="LICENSE">LICENSE</RepoLink>。

安裝包本身只有安裝程式、轉寫腳本與 skill 文件。**下列元件都不包含在安裝包內**：Python 套件由安裝程式從 PyPI 安裝，模型在安裝時從各自的官方來源下載，FFmpeg 由 winget 或 Homebrew 另行安裝。完整的來源、授權與標示見 <RepoLink path="THIRD-PARTY-NOTICES.md">THIRD-PARTY-NOTICES.md</RepoLink>（安裝時也會複製到 runtime 資料夾）。

## 推論引擎與函式庫

| 元件 | 用途 | 授權 |
|---|---|---|
| [OpenVINO / OpenVINO GenAI](https://github.com/openvinotoolkit/openvino.genai) | 推論引擎（Windows：Intel NPU／GPU／CPU） | Apache-2.0 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / CTranslate2 | 推論引擎（Windows：NVIDIA；macOS：CPU） | MIT |
| NVIDIA cuBLAS / cuDNN（pip 套件） | CUDA 函式庫（只在 Windows 且有 NVIDIA 顯示卡時安裝） | NVIDIA 授權 |
| [MLX](https://github.com/ml-explore/mlx) / mlx-whisper | 推論引擎（macOS：Apple GPU） | MIT |
| [optimum-intel](https://github.com/huggingface/optimum-intel) | Breeze 轉換成 OpenVINO 格式（只在安裝時暫用；Pro） | Apache-2.0 |
| [Transformers](https://github.com/huggingface/transformers)、[PyTorch](https://github.com/pytorch/pytorch)（CPU 版）、[CTranslate2](https://github.com/OpenNMT/CTranslate2) 轉換工具 | Breeze-ASR-26 轉換成 CTranslate2 格式（只在安裝時暫用；Pro 2.5） | Apache-2.0、BSD-3-Clause、MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | 說話者分離、標點模型的執行 | Apache-2.0 |
| [OpenCC](https://github.com/BYVoid/OpenCC)（Python 實作） | 簡繁轉換 | Apache-2.0 |
| [FFmpeg](https://ffmpeg.org/) | 音訊與影片處理（另行安裝） | LGPL／GPL |
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) | AI 校正的 Claude API 通道（選用；Pro） | Apache-2.0 |
| [OpenAI Python SDK](https://github.com/openai/openai-python) | AI 校正的 OpenAI API 通道（選用；Pro） | Apache-2.0 |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) | GPU 說話者分離（選用；Pro，已關閉它的使用統計） | MIT |
| [PyTorch](https://pytorch.org/)（CUDA 版） | 同上 | BSD-3-Clause |

## 模型（安裝時下載，不在安裝包內）

| 元件 | 用途 | 授權 |
|---|---|---|
| Whisper large-v3-turbo（OpenVINO INT8、CTranslate2、MLX 版） | 語音辨識 | MIT |
| [Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25)（含 CTranslate2、MLX 版；選裝，Pro） | 台灣華語／中英夾雜語音辨識 | Apache-2.0 |
| [MediaTek Research Breeze-ASR-26](https://huggingface.co/MediaTek-Research/Breeze-ASR-26)（官方權重，revision `7b992682e7f5ceedd0a41ebec240f01ba469d19e`；選裝，Pro 2.5） | 台語語音辨識（輸出台灣華語文字）；安裝時在使用者電腦上轉換，原始權重轉完刪除，本專案不散布權重 | Apache-2.0 |
| pyannote segmentation 3.0（sherpa-onnx 轉換版） | 語音分段 | MIT |
| 3D-Speaker ERes2Net | 中文聲紋（說話者分離） | Apache-2.0 |
| CT-Transformer 標點模型（Alibaba 通義實驗室 FunASR；sherpa-onnx int8 版；Pro） | 本機分段標點 | FunASR Model Open Source License 1.1 |
| [pyannote speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 權重（選用；Pro） | GPU 說話者分離 | CC-BY-4.0 |

- **pyannote 的權重由你自己下載**：要用你自己的 Hugging Face 帳號同意作者的使用條件後下載，本程式不代為同意、不散布（見 [Hugging Face 白話引導](/install/hugging-face)）。
- **CT-Transformer 標點模型**的授權要求標示來源、作者與模型名稱，並有免責條文，全文標示見 THIRD-PARTY-NOTICES.md。

## AI 服務

AI 校正與會議摘要的訂閱通道，使用你自己電腦上已安裝的 Claude Code（`claude` 指令）或 Codex（`codex` 指令）。本程式不安裝、不散布它們；使用時適用各自的服務條款。

## 合成素材

repo 的測試素材（講稿）是自寫、虛構的內容，以本程式相同的 MIT License 提供。合成語音由使用者自己用 edge-tts 重建，repo 不散布合成出來的音檔（見[給開發者](/developer#重建合成素材)）。
