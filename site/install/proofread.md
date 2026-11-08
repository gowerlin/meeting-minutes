---
title: 安裝會議記錄校稿
description: 會議記錄校稿是 meeting-minutes-pro 的附屬工具。這頁說明怎麼下載、安裝、升級與解除安裝，以及它需要哪一版的 Pro。
---

# 安裝會議記錄校稿

**這頁幫你了解**：怎麼安裝會議記錄校稿、它需要哪一版的 meeting-minutes-pro，以及升級、移除時要注意什麼。

會議記錄校稿是 meeting-minutes-pro（下稱 Pro）的**附屬工具**：在瀏覽器裡逐處確認 AI 校正的結果，產出定稿逐字稿與字幕。它裝在 Pro 的資料夾裡、用 Pro 已經裝好的 Python，**不多裝任何套件**，也不需要網路。功能介紹見[會議記錄校稿](/features/proofread)。

## 下載

<ReleaseDownload product="proofread" />

## 先確認已安裝 Pro

- 需要 **meeting-minutes-pro <MmVersion product="proofread-min-pro" /> 以上**，而且是用 Pro 的安裝程式裝在這部電腦上。
- 「用定稿重做會議記錄」這個選用功能需要 Pro **2.3.0 以上**；其他功能在 Pro 2.2.x 上都能用。
- 怎麼看 Pro 的版本：對錄音檔按右鍵轉寫時，視窗第一行會印「meeting-minutes-pro 2.x.x」；或看 [更版紀錄](/releases) 對照你下載的安裝包檔名。
- 還沒裝 Pro：先到[安裝](/install/)，裝好再回來。

## Windows 安裝步驟

1. **完整解壓縮**下載的安裝包（檔名是 `meeting-minutes-proofread-v` 加版號，再加 `-installer.zip`）。
2. 雙擊解開後資料夾裡的 `install.cmd`（不需要系統管理員）。
3. 看到「安裝完成」就好了，按任意鍵關閉視窗。

安裝畫面的樣子（路徑會是你的電腦上的位置）：

```text
==> 檢查 meeting-minutes-pro
    [OK] meeting-minutes-pro 2.3.0（最低 2.2.0；介面檢查通過）

==> 安裝會議記錄校稿 1.0.0 到 %LOCALAPPDATA%\meeting-minutes-pro\proofread

==> 建立右鍵「傳送到 → 會議記錄校稿」
    [OK] 對會議的輸出資料夾（<檔名>_minutes）按右鍵 → 傳送到 → 會議記錄校稿

==> 建立「會議記錄校稿.mmproof」的雙擊開啟
    [OK] 第一次開啟某份稿後，輸出資料夾裡會出現「會議記錄校稿.mmproof」，之後雙擊它就能接著校

==> 安裝完成（會議記錄校稿 1.0.0，搭配 meeting-minutes-pro 2.3.0）
```

裝好後多了兩件事：

- 對會議的輸出資料夾（`<檔名>_minutes`）按右鍵 →「傳送到」→「**會議記錄校稿**」。
- 雙擊輸出資料夾裡的「會議記錄校稿.mmproof」也會開啟（第一次開啟某份稿後才會出現這個小檔）。

只改目前使用者的設定（右鍵捷徑與 `.mmproof` 的開啟方式），不改系統設定。怎麼使用見[用會議記錄校稿確認逐字稿](/usage/proofread)。

## macOS 安裝步驟

::: warning 尚未在 macOS 實測
macOS 的安裝程式與入口照 Windows 版的流程寫好，也在測試環境驗證過步驟，但**還沒有在 Mac 實機上跑過**。遇到問題請到公開 repo 回報。
:::

1. 完整解壓縮下載的安裝包。
2. 在 `install.command` 上按右鍵 →「打開」（第一次會被 Gatekeeper 擋，用右鍵打開即可，與 Pro 的安裝相同）。
3. 安裝程式會建立 `~/Applications/會議記錄校稿.app`，並讓雙擊「會議記錄校稿.mmproof」用它開啟。
4. 使用時把輸出資料夾拖到「會議記錄校稿.app」上。

## 升級

**重新執行新版的安裝程式就是升級。**

- 正在校稿的分頁會先自動存檔，服務關閉後換成新版程式。
- 最近的稿清單、每份稿的校稿進度（各輸出資料夾的 `.proofread`）都保留，下次開啟接著校。

**Pro 升級之後**，會議記錄校稿還在：Pro 的安裝程式不會動 `proofread` 資料夾，右鍵與 `.mmproof` 繼續有效。每次開啟都會重新檢查與 Pro 的相容性，不相容時會提示到這頁下載相容的版本。Pro 重建了 Python 環境而且位置改變時，請重新執行會議記錄校稿的安裝程式。

## 解除安裝

- **Windows**：雙擊安裝包裡的 `uninstall.cmd`。安裝包已經刪掉時，對 `%LOCALAPPDATA%\meeting-minutes-pro\proofread\uninstall.ps1` 按右鍵 →「用 PowerShell 執行」。
- **macOS**：在安裝包裡的 `uninstall.command` 上按右鍵 →「打開」。

| 會移除 | 不會移除 |
|---|---|
| 程式本身與設定 | 各輸出資料夾的 `.proofread`（校稿進度） |
| 右鍵「傳送到 → 會議記錄校稿」（macOS：`會議記錄校稿.app`） | 定稿檔 `transcript.final.md`、`transcript.final.srt` |
| 雙擊 `.mmproof` 的開啟方式 | Pro 的錯誤對照表 `corrections.tsv`、詞表 `glossary.txt` 與 `backups` |
| 最近的稿清單（**會先問你**，預設保留） | Pro 本身 |

::: tip 要移除 Pro 時
**Pro 2.3.0 以上**的解除安裝會自動先移除會議記錄校稿。**Pro 2.2.x 請先移除會議記錄校稿，再移除 Pro**；順序反過來的話，右鍵「傳送到」與 `.mmproof` 的開啟方式會留下來、指向已經不存在的檔。
:::

## 版本相容表

| 會議記錄校稿 | Pro 最低版本 | Pro 建議版本 | 「用定稿重做會議記錄」 |
|---|---|---|---|
| <MmVersion product="proofread" />（目前版本） | <MmVersion product="proofread-min-pro" /> | 2.3.0 | 需要 Pro 2.3.0 以上；Pro 2.2.x 時按鈕停用 |

安裝程式與每次開啟都會檢查 Pro 的版本與它的介面（標記格式、會用到的 Pro 模組）。不相容時會停下並提示，不會用錯的格式寫檔。之後 Pro 改了標記格式時，更版紀錄會寫明哪一版的會議記錄校稿可以用。

## 安裝失敗怎麼辦

| 畫面上的訊息 | 原因 | 怎麼做 |
|---|---|---|
| 「請先安裝 meeting-minutes-pro 2.2.0 以上」 | 這部電腦上找不到 Pro（或 Pro 裝在別的位置） | 先[安裝 Pro](/install/)。Pro 裝在自訂位置時，確認環境變數 `MEETING_MINUTES_PRO_HOME` 指向 Pro 的資料夾 |
| 「meeting-minutes-pro 版本 X 太舊，請先升級到 2.2.0 以上」 | Pro 版本低於最低需求 | 下載新版 Pro 重新執行安裝程式（見[升級與解除安裝](/install/upgrade)），再裝一次會議記錄校稿 |
| 「這版會議記錄校稿與目前的 meeting-minutes-pro X 不相容」 | Pro 改了標記格式或會用到的模組 | 回到這頁，下載與你的 Pro 相容的會議記錄校稿（看上面的相容表與[更版紀錄](/releases)） |
| 「找不到安裝檔 payload\app」 | zip 沒有完整解壓縮，直接在壓縮檔裡執行 | 先把 zip 解壓縮到一個資料夾，再執行解開後的 `install.cmd` |

上面這幾種情況，安裝程式都會在寫入任何檔案**之前**停下，不會留下半套安裝。
