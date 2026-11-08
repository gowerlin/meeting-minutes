---
title: 升級與解除安裝
description: 從 1.x 升級到 2.0、從 2.1 升級到 2.2、從 2.2 升級到 2.3 要注意什麼、升級時保留哪些檔，以及怎麼解除安裝（含會議記錄校稿）。
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

2.1.x → 2.2.x：重新執行安裝程式即可，會自動安裝讀 PDF 用的 `pypdf`。`config.json` 會補上 `reference`、`consistency` 區塊（預設全開），既有的設定、詞表與輸出檔都不變。要注意的改變：

1. **AI 校正會送出影片截圖**（最多 8 張，縮小後），用來補上與會者全名與會議日期；不想送：`config.json` 的 `reference.frames` 改成 `false`（見[參考資料](/features/reference)）。
2. **入口可能多一題「背景說明（一行）」**：答應 AI 校正或摘要、而且錄音旁沒有說明檔時才問，直接按 Enter 跳過；不想被問：`reference.ask_context` 改成 `false`。
3. **新檔案**：輸出資料夾可能多 `reference.json`、`context.md`；校正版與會議記錄裡同一個英文名詞的寫法會[統一](/features/consistency)。

2.2.x → 2.3.x：重新執行安裝程式即可。`config.json` 的設定鍵沒有變（只更新 `runtime_version`），入口題目、詞表與輸出檔都不變。改變的地方：

1. **有定稿逐字稿時，會議摘要改用它**：用[會議記錄校稿](/features/proofread)定稿過的資料夾（有 `transcript.final.md`），重跑會議摘要時會依定稿整理，表頭寫「已人工校稿」。定稿比校正版舊（之後又重新轉寫或校正過）時，會改用校正版並印一行說明。
2. **新指令參數**：`auto_minutes.py --source final`（指定用定稿）、`--estimate-only`（只估費用、不呼叫模型、不寫檔）；完成時的結果多了實際費用。見[手動執行與參數](/usage/advanced)。
3. **解除安裝會一起移除會議記錄校稿**（有安裝的話），不會留下指向不存在檔案的右鍵選單。
4. **Claude 桌面 App 請改上傳新版的上傳檔**（桌面上的 zip 已換成新版）。

2.3.x → <MmVersion />：重新執行安裝程式即可。`config.json` 會補上 `privacy` 這一組設定（`local_only: false`，畫面寫「config.json 已補上新版設定鍵：privacy（既有的值不變）」）；詞表、對照表、GPU 與精度設定、輸出檔都不變。改變的地方：

1. **多一個右鍵入口「會議轉寫（Pro，本機限定）」**（macOS 多一個同名的 app）：機敏會議用，這一份什麼都不送 GPT 或 Claude（見[本機限定](/features/local-only)）。原本的「會議轉寫（Pro）」照舊。
2. **畫面上的供應商名稱改成 GPT／Claude**：例如「AI 校正：GPT gpt-6.1-sol（…）；逐字稿文字會送到 GPT（OpenAI）」「[Enter] 預設（GPT gpt-6.1-sol）」。設定值（`openai`、`claude`）、旗標（`--openai`、`--claude`）與輸出檔的表頭（例「自動整理：OpenAI gpt-6.1-sol low，…」）都不變。
3. **Claude 桌面 App 請改上傳新版的上傳檔**（桌面上的 zip 已換成新版）。
4. **會議記錄校稿建議一起升到 <MmVersion product="proofread" />**：才認得本機限定（舊版在本機限定的那一份按「重做」時會被 Pro 拒絕，不會送出，見[安裝會議記錄校稿 › 升級](/install/proofread#升級)）。

2.4.0 → 2.4.1（安全修正）：重新執行安裝程式即可，`config.json` 只更新 `runtime_version`。改變的地方：`config.json` 讀不了或 `privacy.local_only` 的值看不懂時，改成**當成本機限定**（2.4.0 會照常送出）；安裝程式遇到讀不了的 `config.json` 會停下、不再把它蓋掉（見[本機限定 › config.json 讀不了或值看不懂](/features/local-only#config-unreadable)）。Claude 桌面 App 請改上傳新版的上傳檔；會議記錄校稿建議一起升到 <MmVersion product="proofread" />。

從 2.0.x 直接升到 <MmVersion /> 也只要重新執行一次安裝程式，上面各段的改變都會一起套用。

會議記錄校稿的升級另外執行它自己的安裝程式，見[安裝會議記錄校稿 › 升級](/install/proofread#升級)。

各版改了什麼見[更版紀錄](/releases)。

## 解除安裝

- **Windows**：雙擊安裝資料夾裡的 `uninstall.cmd`，或執行 `install.cmd -Uninstall`。
- **macOS**：在 `uninstall.command` 上按右鍵 →「打開」，或在終端機執行 `./install.sh --uninstall`。
- **裝了[會議記錄校稿](/install/proofread)時**：Pro 2.3.0 以上的解除安裝會自動先移除它。**Pro 2.2.x 請先移除會議記錄校稿**（執行它安裝包裡的 `uninstall.cmd`／`uninstall.command`），再移除 Pro。

### 會移除

- Claude CLI 裡的 skill
- 轉寫入口（Windows 的右鍵「傳送到」捷徑、macOS 的「會議轉寫（Pro）」；2.4 起連同「會議轉寫（Pro，本機限定）」）
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
