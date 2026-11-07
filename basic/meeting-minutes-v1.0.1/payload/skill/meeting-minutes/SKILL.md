---
name: meeting-minutes
description: 把會議錄音、錄影或逐字稿整理成繁體中文會議記錄（摘要、決議、待辦、待釐清問題，附時間碼）。本機有 runtime 時，用 Whisper（安裝時依硬體選定 Intel NPU/GPU、NVIDIA CUDA、Apple Silicon GPU 或 CPU；支援 Windows 與 macOS）加說話者分離在本機轉寫；在 Claude App 沙盒中則讀取使用者附上的 transcript.md。當使用者要分析會議錄音或錄影、產生會議記錄、逐字稿、meeting minutes 或 transcript 時使用。
---
<!-- meeting-minutes-version: 1.0.1 -->

# 會議記錄

音檔不上傳：轉寫在使用者電腦上完成，Claude 只讀逐字稿與截圖。

## 0. 判斷執行模式

先確認本機 runtime 是否存在：

```bash
# macOS（zsh/bash）與 Windows（Git Bash，Claude CLI 在 Windows 上的預設）通用
if [ "$(uname -s)" = "Darwin" ]; then
  MMH="$HOME/Library/Application Support/meeting-minutes"; PY="$MMH/venv/bin/python"
else
  MMH="$(cygpath -u "$LOCALAPPDATA" 2>/dev/null)/meeting-minutes"; PY="$MMH/venv/Scripts/python.exe"
fi
test -x "$PY" && echo LOCAL || echo NO_RUNTIME
```

```powershell
# Windows PowerShell
$MMH = "$env:LOCALAPPDATA\meeting-minutes"; $PY = "$MMH\venv\Scripts\python.exe"; Test-Path $PY
```

macOS 的路徑含空白（`Application Support`），之後的指令一律以雙引號包住 `"$MMH"`、`"$PY"`。

| 結果 | 模式 | 做法 |
|---|---|---|
| `LOCAL` | **本機模式**（Claude CLI、桌面版 Code 分頁） | 從步驟 1 開始 |
| 沒有 runtime，但使用者附了 `transcript.md` 或 `transcript.json` | **逐字稿模式**（Claude App 對話／Cowork 沙盒） | 直接跳到步驟 3 |
| 沒有 runtime，使用者附的是音檔或影片 | 請使用者先在本機轉寫 | 見下方說明 |

使用者附的是音檔或影片時，**不要**在沙盒裡安裝 Whisper（沒有 NPU、很慢，且常連不到 Hugging Face）。請使用者這樣做：

> - **Windows**：在檔案總管對錄音檔按右鍵 →「傳送到」→「會議轉寫（基本版）」。
> - **macOS**：把錄音檔拖曳到「應用程式」裡的「會議轉寫（基本版）」圖示上（或在 Finder 按右鍵 →「打開檔案的應用程式」→「會議轉寫（基本版）」）。
>
> 完成後把輸出資料夾 `<檔名>_minutes` 裡的 `transcript.md` 附上來；影片可以一併附上 `frames` 資料夾裡的截圖。還沒安裝的話，先執行安裝包裡的 `install.cmd`（Windows）或 `install.command`（macOS）。

如果 Cowork 已連結使用者電腦並可存取該資料夾，可以直接讀取 `<檔名>_minutes/transcript.md`。

## 1. 開始前確認（本機模式；缺什麼才問，一次問完）

- 會議檔案路徑（必要）
- 與會人數，對應參數 `--speakers N`。強烈建議提供，說話者分離準確度差很多
- 與會者姓名、會議名稱與日期，用來把 S1、S2 對應到真人
- 本次特有的專有名詞，對應參數 `--hotwords`。常用名詞放在 `$MMH/glossary.txt`，預設會自動套用

## 2. 本機轉寫

```bash
PYTHONUTF8=1 "$PY" "$MMH/scripts/transcribe.py" "<檔案>" --speakers 4 --hotwords "名詞1, 名詞2"
```

- 後端、裝置與模型寫在 `$MMH/config.json`，由安裝程式偵測硬體並實測後選定。**轉寫時不會再偵測，也不需要指定 `--backend`／`--device`**。若載入失敗，請使用者重新執行 `install.cmd`（macOS：`install.command`）重新偵測，不要自行改用其他裝置重試。
- 1 小時的錄音約需數分鐘到十幾分鐘。請用背景執行，或把 timeout 設到 600000 ms 以上，不要中途重跑。
- 影片會自動擷取畫面變化（簡報翻頁、切換共享畫面）存到 `frames/`；加 `--no-keyframes` 可關閉。
- 只有一個人講話，或分離結果很亂時，加 `--no-diarize`。
- 輸出在 `<檔名>_minutes/`：
  - `transcript.md`：閱讀用，含時間碼、講者與畫面標記
  - `transcript.json`、`transcript.srt`
  - `frames/`：影片截圖
- stdout 最後一行是 JSON 摘要。

## 3. 閱讀與校正

1. 讀 `transcript.md`。會議超過約 2 小時就分段讀（Read 的 offset/limit），每段先做重點筆記再合併。
2. 影片：讀 `frames/` 中與議題相關的截圖。檔名含時間碼，例如 `frame_0003_001523.jpg` 代表 00:15:23。把簡報標題、數字、架構圖的內容補進對應議題。截圖很多時，只挑議題轉換點附近的。
3. 講者對應：依自我介紹、稱呼（例如「小明你那邊…」）和角色發言內容，把 S# 對應到姓名。無法確定就保留 S#，並在品質備註寫明依據。
4. ASR 校正：逐字稿是 ASR 原始結果，已做過 OpenCC 繁體轉換和幻覺過濾。依上下文修正明顯的同音錯字和專有名詞，例如「是範證券」改為「示範證券」、「酷伯內蒂斯」改為「Kubernetes」（範例名稱都是虛構或通用技術詞）。**不得杜撰**沒聽到的內容；不確定的片段標註時間碼，列入品質備註。

## 4. 產出會議記錄

- 依 `references/minutes-template.md` 的結構，用繁體中文（台灣用語）撰寫。
- 每個決議、待辦、問題都附時間碼，方便回聽查證。
- 待辦必須有負責人；逐字稿沒講到期限就寫「未定」，不要推測。
- 只寫會議中實際提到的內容。Claude 自己的建議放在獨立的「補充建議」段落。
- 存放位置：本機模式存成 `<檔名>_minutes/meeting-minutes.md`；在 App 中依該環境的慣例交付文件。
- 流程圖和時序圖一律用 Mermaid。

## 5. 後續（使用者要求時）

- 把 Action Items 轉成工單、任務清單或 email 草稿。
- 與前次會議記錄比對，追蹤待辦完成狀況。

## 疑難排解（本機模式）

| 狀況 | 處理 |
|---|---|
| 換了硬體、更新驅動或系統，或載入失敗 | 重新執行 `install.cmd`／`install.command`，或 `"$PY" "$MMH/scripts/setup_backend.py"` 重新偵測並寫入 config |
| 講者數不對 | 指定 `--speakers N`；未知人數時調整 `--cluster-threshold`，數值越大人數越少，預設 0.8 |
| 專有名詞錯 | 加到 `$MMH/glossary.txt`，或用 `--hotwords` |
| 想要更高的準確度 | `"$PY" "$MMH/scripts/download_models.py" --whisper large-v3`，轉寫時加 `--whisper large-v3`（較慢） |
| 找不到 ffmpeg | 重新執行安裝程式；或 Windows：`winget install Gyan.FFmpeg`，macOS：`brew install ffmpeg`，再開新的終端機 |
