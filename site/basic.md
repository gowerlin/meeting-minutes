---
title: 基本版
description: 基本版 meeting-minutes 能做什麼、與 Pro 版的差異、可以和 Pro 版並存、下載。
---

# 基本版 meeting-minutes

**這頁幫你做到**：決定要不要用功能比較少、比較單純的基本版。

基本版做的事情很單純：在你的電腦上把錄音轉成逐字稿，再讓 Claude 整理成繁體中文會議記錄（摘要、議題、決議、待辦、待釐清問題，每一項附時間碼）。音檔不上傳；整理在 Claude 對話中做，Claude 讀到的逐字稿和影片截圖會送到 Anthropic 的雲端處理。對話中沒有「要送出嗎？」這一步，有機敏內容時請不要在對話中讀逐字稿。

<ReleaseDownload product="basic" />

## 基本版能做什麼

| 功能 | 說明 |
|---|---|
| 本機語音辨識 | Whisper large-v3-turbo；安裝時自動挑出你電腦上最快的硬體 |
| 說話者分離 | 把逐字稿分成 S1、S2…（CPU） |
| 影片截圖 | 偵測畫面變化，自動擷取簡報翻頁與共享畫面 |
| 繁體輸出 | 轉成台灣用語的繁體中文；專有名詞清單裡的詞保持原樣 |
| 專有名詞提示 | `glossary.txt` 與單次的 `--hotwords` |
| 幻覺過濾 | 刪掉語音辨識常見的幻覺句、壓縮跳針重複 |
| 會議記錄 | 在 Claude 對話中依範本整理，並依上下文校正同音錯字；沒聽到的不杜撰 |

支援的電腦、安裝步驟、安裝選單都和 Pro 版相同（見[安裝](/install/)），只是沒有 Breeze、自動校正與 GPU 說話者分離的詢問。右鍵選單的名稱是「**會議轉寫（基本版）**」。

## 和 Pro 版的差異

| | 基本版 | Pro 版 |
|---|---|---|
| 本機轉寫、說話者分離、截圖、繁體輸出 | ✅ | ✅ |
| 在 Claude 裡整理成會議記錄 | ✅ | ✅ |
| 固定錯誤對照表（越用越準） | — | ✅ |
| 校正版逐字稿（標出每一處修改） | — | ✅ |
| Breeze-ASR-25（中英夾雜比較準） | — | ✅ 選裝 |
| 本機分段標點、OpenCC 詞彙回復表 | — | ✅ |
| 轉寫後自動 AI 校正與會議摘要 | — | ✅ 選用 |
| 7 種內容類型、自訂範本 | — | ✅ |
| 字幕（照字幕規則切條） | — | ✅ |
| 會議記錄網頁版（時間碼點了播放） | — | ✅ |
| AI 校正參考影片截圖、背景說明與會議文件（補與會者全名、會議日期） | — | ✅ |
| 全文用字統一（英文名詞的大小寫與空格） | — | ✅ |
| GPU 說話者分離 | — | ✅ 選用（Windows＋NVIDIA） |
| 執行 log 與費用 | — | ✅ |

**選基本版**：只需要逐字稿，再自己請 Claude 整理；想要最少的設定與詢問。
**選 Pro 版**：常開會、專有名詞多、要整理課程或訪談、要字幕，或希望轉寫完就自動拿到會議記錄。

## 和 Pro 版並存

兩版可以同時安裝，互不影響：

| 項目 | 基本版 | Pro 版 |
|---|---|---|
| Skill 名稱 | `meeting-minutes` | `meeting-minutes-pro` |
| 資料夾（Windows） | `%LOCALAPPDATA%\meeting-minutes` | `%LOCALAPPDATA%\meeting-minutes-pro` |
| 資料夾（macOS） | `~/Library/Application Support/meeting-minutes` | `~/Library/Application Support/meeting-minutes-pro` |
| 右鍵選單／應用程式 | 會議轉寫（基本版） | 會議轉寫（Pro） |
| 環境變數 | `MEETING_MINUTES_HOME` | `MEETING_MINUTES_PRO_HOME` |

- 兩版各有一份模型，同時安裝會多佔約 2～4 GB；想省空間可以只留 Pro 版。
- 兩版的 `glossary.txt` 各自獨立。從基本版改用 Pro 版時，把檔案複製到 Pro 版的資料夾即可。
- 在 Claude 裡用名稱指定比較明確，例如「用 meeting-minutes 整理…」或「用 meeting-minutes-pro 整理…」。
- 兩版的輸出資料夾都叫 `<檔名>_minutes/`。對同一個檔先後用兩版轉寫，後跑的會覆蓋逐字稿。

## 使用方式

- **Claude CLI**：跟 Claude 說「用 meeting-minutes 整理 D:\會議\0912.m4a，與會 4 人」。
- **Claude 桌面 App**：右鍵「傳送到 → 會議轉寫（基本版）」轉寫，再把 `transcript.md` 附到 App，說「用 meeting-minutes 整理成會議記錄」。上傳 skill 的方式和 Pro 版相同（見 [Claude 桌面 App](/usage/claude-app)），上傳檔是桌面的 `meeting-minutes-skill-upload.zip`。
- **解除安裝**：雙擊 `uninstall.cmd`（macOS：`uninstall.command`）。

基本版的更版紀錄見[更版紀錄 › 基本版](/releases#meeting-minutes-基本版)。
