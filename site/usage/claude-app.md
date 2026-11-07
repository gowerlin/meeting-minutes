---
title: Claude 桌面 App
description: 在 Claude 桌面 App（對話／Cowork）使用：上傳 skill、附上逐字稿，請 Claude 整理或檢查會議記錄。
---

# Claude 桌面 App

**這頁幫你做到**：在 Claude 桌面 App 的對話裡，把轉寫好的逐字稿整理成會議記錄。

## 為什麼要分兩步

Claude App 裡的 skill 在雲端的沙盒中執行，用不到你電腦的顯示卡或 NPU，也讀不到你的錄音檔。所以：

1. **轉寫在你的電腦上做**：用[右鍵「傳送到」或拖放](/usage/send-to)。
2. **整理在 Claude App 做**：把逐字稿附到對話裡。

## 第一次：上傳 skill

安裝時選 [2] 或 [3]，桌面上會出現 `meeting-minutes-pro-skill-upload.zip`。

1. Claude App 先到「設定 → Capabilities」，開啟程式碼執行功能。
2. 依序點「**自訂（Customize）**」→「**Skills**」→「**＋**」→「**Create skill**」→「**Upload a skill**」。
3. 選桌面上的 `meeting-minutes-pro-skill-upload.zip` 上傳，**不要解開**。也可以上傳 Release 的 `…-claude-app-upload.zip`，兩者內容相同。

網頁版的上傳頁面是 <https://claude.ai/customize/skills>。

::: danger 不要上傳安裝包
上傳 `…-installer.zip` 會出現「Zip cannot contain nested zip files」。請改上傳上面說的上傳檔。
:::

## 每次使用

### 轉寫時已經做了會議摘要

輸出資料夾裡有 `meeting-minutes.md`：

1. 先打開它（或用瀏覽器打開同一個資料夾裡的 `meeting-minutes.html`，點時間碼可以回聽），確認決議與待辦。
2. 要補講者姓名或修改：在 Claude App 附上 `meeting-minutes.md` 與 `transcript.corrected.md`（沒有就附 `transcript.md`），說：

   > **用 meeting-minutes-pro 檢查這份會議記錄**

   Claude 會當成草稿查證、補講者姓名、修正錯漏，不會從頭重寫。

### 轉寫時沒有做會議摘要

1. 附上 `transcript.md`（有 AI 校正時附 `transcript.corrected.md`）；影片可以一併附上 `frames` 資料夾裡的截圖。
2. 說：

   > **用 meeting-minutes-pro 整理成會議記錄，並產生校正版逐字稿**

### 對照表建議

Claude App 寫不到你的電腦，所以建議加進對照表的項目會以一段文字（TSV）給你，請自己貼到 runtime 資料夾的 `corrections.tsv`（見[固定錯誤對照表](/features/accuracy#固定錯誤對照表)）。

## App 裡做不到的事

- 轉寫、AI 校正、字幕：都在你的電腦上做，App 裡沒辦法。
- 讀取你電腦上的檔案：要自己附上。

## 疑難排解

| 狀況 | 處理 |
|---|---|
| 上傳 skill 失敗 | 確認上傳的是上傳檔（不要自己重新壓縮），並確認已開啟程式碼執行功能 |
| 出現「Zip cannot contain nested zip files」 | 上傳到的是安裝包，改上傳上傳檔 |
| Claude Code 裡出現兩個 meeting-minutes-pro | Claude Code 以 claude.ai 帳號登入時，App 上傳的 skill 會同步過去。兩者內容相同，可以留一個 |
