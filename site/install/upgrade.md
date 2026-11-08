---
title: 升級與解除安裝
description: 從 1.x 升級到 2.0、從 2.1 升級到 2.2 要注意什麼、升級時保留哪些檔，以及怎麼解除安裝。
---

# 升級與解除安裝

**這頁幫你做到**：安全地升級到新版，或把程式移除乾淨。

## 怎麼升級

**重新執行新版的安裝程式就是升級**：下載新版安裝包、解壓縮、雙擊 `install.cmd`（macOS：`install.command`），選和原本相同的安裝目標。

升級時會**保留**：

- 你的專有名詞清單 `glossary.txt`、固定錯誤對照表 `corrections.tsv`、OpenCC 詞彙回復表 `opencc_keep.tsv`
- 自訂範本（`templates` 資料夾）、自己的價格表 `pricing.json`、歷次執行紀錄 `logs/`
- `config.json` 裡既有的設定（只補上新版才有的設定鍵）、已下載的模型

舊版的 skill 會備份到 runtime 資料夾的 `backup/`。安裝畫面的「更新設定」那一步會寫明補了哪些設定鍵；沒有新鍵就寫「設定鍵無變更」。

## 從 1.x 升級到 2.0 要注意的事

1. **右鍵與拖放轉寫多一題「內容類型」**（第一題）。直接按 Enter＝會議；連按 Enter 的結果和 1.2.2 一樣。之後會記住你上次選的類型。
2. **講者人數的意思改了**：填 N 位，2.0 會「保留發言最多的 N 位」，不再「強制分成 N 群」。實測比較準，舊的行為不保留。**填實際人數，不確定就留空**。
3. **分群門檻預設從 0.8 改成 0.9**（課程 1.0、座談 0.8）：沒填人數時，判斷出的講者通常會少一些。要回到 1.2.2 的分法，轉寫時加 `--cluster-threshold 0.8`。
4. **影片截圖門檻**：操作教學自動調成比較靈敏的 0.1，其他類型照舊 0.3。
5. **新檔案**：輸出資料夾多了兩個字幕檔 `transcript.cues.srt`、`transcript.corrected.srt`，以及非會議類型的 `notes.md`、`notes.json`。原有檔案的格式不變。
6. **有 NVIDIA 顯示卡**：升級時會問一次要不要裝 [GPU 說話者分離](/install/gpu)（預設不裝）。

2.0.0 → 2.0.1 → 2.0.2：功能、設定鍵、輸出檔都相同，重新執行安裝程式即可。

2.0.x → 2.1.x：重新執行安裝程式即可。多了[網頁版](/features/web)（`meeting-minutes.html`／`notes.html`），`config.json` 會補上 `html` 區塊；既有的設定、詞表、輸出檔與入口題目都不變。

2.1.x → <MmVersion />：重新執行安裝程式即可，會自動安裝讀 PDF 用的 `pypdf`。`config.json` 會補上 `reference`、`consistency` 區塊（預設全開），既有的設定、詞表與輸出檔都不變。要注意的改變：

1. **AI 校正會送出影片截圖**（最多 8 張，縮小後），用來補上與會者全名與會議日期；不想送：`config.json` 的 `reference.frames` 改成 `false`（見[參考資料](/features/reference)）。
2. **入口可能多一題「背景說明（一行）」**：答應 AI 校正或摘要、而且錄音旁沒有說明檔時才問，直接按 Enter 跳過；不想被問：`reference.ask_context` 改成 `false`。
3. **新檔案**：輸出資料夾可能多 `reference.json`、`context.md`；校正版與會議記錄裡同一個英文名詞的寫法會[統一](/features/consistency)。

從 2.0.x 直接升到 <MmVersion /> 也只要重新執行一次安裝程式，上面兩段的改變都會一起套用。

各版改了什麼見[更版紀錄](/releases)。

## 解除安裝

- **Windows**：雙擊安裝資料夾裡的 `uninstall.cmd`，或執行 `install.cmd -Uninstall`。
- **macOS**：在 `uninstall.command` 上按右鍵 →「打開」，或在終端機執行 `./install.sh --uninstall`。

### 會移除

- Claude CLI 裡的 skill
- 轉寫入口（Windows 的右鍵「傳送到」捷徑、macOS 的「會議轉寫（Pro）」）
- 桌面上的上傳用 zip
- runtime 與模型（**會先問你**）。選擇刪除時，標點模型、OpenCC 回復表、對照表的自動寫入紀錄、GPU 說話者分離套件與權重也會一起刪除
- 有自訂範本時會再問「刪除自訂範本 N 份？[y/N]」：直接按 Enter＝保留，範本會先複製到桌面的 `meeting-minutes-pro-templates-備份` 資料夾

選擇保留 runtime 的話，`glossary.txt`、`corrections.tsv`、`opencc_keep.tsv`、自訂範本與模型都會留著，之後重新安裝可以直接沿用。

### 不會移除

- 每場會議的輸出資料夾（`<檔名>_minutes/`）：這些是你的資料
- Claude Code、Codex 本身與它們的登入狀態
- Hugging Face 的登入：要登出見 [Hugging Face 白話引導 › 登出](/install/hugging-face#登出)
- 上傳到 Claude App 的 skill：請到 App 的「自訂 → Skills」手動刪除
- 透過 winget 或 Homebrew 安裝的 Python 與 ffmpeg

## 把模型放到其他磁碟

系統磁碟空間不夠時，可以設定環境變數 `MEETING_MINUTES_PRO_HOME` 指向其他位置，再重新執行安裝程式，模型就會下載到新位置。
