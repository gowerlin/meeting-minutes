# 會議記錄校稿（meeting-minutes-proofread）1.1.1 規格（公開版）：Pro 的 config.json 讀不了時當成本機限定（安全修正）

> **公開版**：本檔是會議記錄校稿 **1.1.1** 規格的公開版。內容是 **1.1.1 相對 1.1.0 的差異**（修正版）；本檔沒有提到的行為一律照
> 1.1 規格（公開版 [`meeting-minutes-proofread-1.1-spec.md`](meeting-minutes-proofread-1.1-spec.md)；下稱「1.1 規格」）與 1.1.0 的程式。
> 搭配：meeting-minutes-pro 2.4.1 規格（公開版 [`meeting-minutes-pro-2.4.1-spec.md`](meeting-minutes-pro-2.4.1-spec.md)，下稱「Pro 2.4.1 規格」）§2。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 1.1.1 §x.y」就是本檔的同一節。
> 版本目錄 `V/`＝`proofread/meeting-minutes-proofread-v1.1.1/`（公開 repo 的路徑）。
> 標示：**〔實測〕**＝實作時以合成素材實測的結果（附錄 A）；**〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節。

---

## 0. 摘要

| 項目 | 1.1.0 | 1.1.1 |
|---|---|---|
| Pro 的 `config.json` 讀不了（權限、被鎖、不是 UTF-8、不是合法 JSON、空檔、最外層不是物件） | 當成 `{}` → 不是本機限定，「用定稿重做」可用（會送出） | **當成本機限定**（來源 `config-unreadable`），重做停用 |
| `privacy.local_only` 是 `true`／`false` 以外的值、`privacy` 不是物件 | 不是本機限定 | **當成本機限定**（同上，原因「值看不懂」） |
| 首頁卡片「本機限定」標示的滑鼠提示 | 一律寫「這份不送 GPT 或 Claude（輸出資料夾有 local-only.json）」，只有全域設定時也這樣寫（1.1.0 發版實測時發現） | 依來源寫：標記檔、全域設定、config.json 讀不了 |

最低 Pro 版本維持 **2.2.0**（不 import Pro 的新函式；搭 Pro 2.2～2.4.0 時也用本版的判定表）。

## 1. 判定（`mmproof_pro.py`）

- `read_pro_config(home)`：同 Pro 2.4.1 `common.read_config()`（不 import Pro）：`missing`／`ok`／`unreadable`，原因代碼與畫面文字 `CONFIG_PROBLEM_TEXT` 和 Pro 2.4.1 逐字相同（tests 比對 Pro 的原始碼）。
- `config_local_only(home)`：Pro 2.4.1 規格 §2.2 的判定表。
- `local_only_state(home, folder)`：來源 `config`、`config-unreadable`、`marker`（以「+」連起來）；有 `config-unreadable` 時另有 `config_problem`（`reason`、`detail`、`path`）。`message` 的句型照 1.1 規格 §1：

```text
本機限定（meeting-minutes-pro 的 config.json 讀不了：不是合法的 JSON（第 1 行第 2 欄）；為了不外送，已當成本機限定）：這份不送 GPT 或 Claude，「用定稿重做」會送出內容，所以停用。要解除：修好 meeting-minutes-pro 的 config.json（<路徑>；存成 UTF-8 的 JSON 物件）；或刪掉它再重新執行 meeting-minutes-pro 的安裝程式（重建的 config.json 本機限定是關）
```

  值看不懂時是「meeting-minutes-pro 的 config.json 的值看不懂：privacy.local_only 是 "true"，只認得 true 或 false；為了不外送，已當成本機限定」，解除句的括號改成「privacy.local_only 只能是 true 或 false」。
- 每次請求都重新判定（照 1.1 規格）：使用者修好 `config.json` 後重新整理頁面就恢復。

## 2. 伺服器（`mmproof_server.py`）

| API | 1.1.1 |
|---|---|
| `GET /api/docs`（首頁） | 每份的 `local_only`（布林，照舊）之外，本機限定時多 `local_only_source`、`local_only_message`（每份各自判定：全域＋那份的標記檔）；全域本機限定時多 `local_only_global_source`、`local_only_global_message`。1.1.0 的欄位都不變 |
| `GET /api/docs/<id>`（頁面） | `local_only` 物件多 `config_problem`；`redo.reason` 是 §1 的訊息 |
| `POST …/redo` | 本機限定時照舊 **409 `local_only`**，`message` 是 §1 的訊息（含原因與路徑） |

## 3. 畫面（`static/app.js`）

| 位置 | 1.1.1 |
|---|---|
| 頁首「本機限定」標示（title） | §1 的訊息（照舊用伺服器給的 `message`） |
| 說明列 | 來源有 `config-unreadable` 時：「本機限定（meeting-minutes-pro 的 config.json 讀不了或值看不懂，為了不外送已當成本機限定；原因與恢復方法見頁首「本機限定」的說明）：這份不送 GPT 或 Claude。人工修改、定稿、經驗匯入照常；「用定稿重做會議記錄」停用。」；其他來源照 1.1.0 |
| 重做區塊 | 按鈕停用，原因寫 §1 的訊息（照舊用 `redo.reason`） |
| 首頁標題旁 | 全域 `config` → 「本機限定（整部電腦）」（照 1.1.0）；`config-unreadable` → 「**本機限定（config.json 讀不了）**」，title 是伺服器給的訊息 |
| 首頁卡片（`loTag()`）| title 依來源：`marker` →「這份不送 GPT 或 Claude（輸出資料夾有 local-only.json）」；`config` →「這份不送 GPT 或 Claude（meeting-minutes-pro 的 config.json 設了 privacy.local_only（整部電腦））」；`config-unreadable` →「這份不送 GPT 或 Claude（meeting-minutes-pro 的 config.json 讀不了或值看不懂，為了不外送已當成本機限定（整部電腦））」；多個來源以「；」連起來。卡片的文字照舊是「本機限定」 |

`loTitle(source)`、`LO_WHY` 是新函式與表；`loTag(text, title, source)` 多一個參數（title 沒給時用 `loTitle(source)`；source 沒給時當成 `marker`，與 1.1.0 相同）。

## 4. 相容（版本相容表，更新 1.1 規格 §4）

| 會議記錄校稿 | Pro 最低版本 | Pro 建議版本 | 「用定稿重做會議記錄」 |
|---|---|---|---|
| 1.1.1 | 2.2.0 | 2.4.1 | 需要 Pro 2.3.0 以上；Pro 2.2.x 時停用；本機限定時停用（任何 Pro 版本；config.json 讀不了或值看不懂也算） |
| 1.1.0 | 2.2.0 | 2.4.0 | 需要 Pro 2.3.0 以上；Pro 2.2.x 時停用；本機限定時停用（任何 Pro 版本） |

搭 Pro 2.4.0 時〔推論〕：校稿這邊依本版判定（`config.json` 讀不了時停用重做）；Pro 2.4.0 自己的 `auto_minutes.py` 仍照 2.4.0 判定，但校稿已不會呼叫它。建議 Pro 一起升到 2.4.1。

## 5. 版號與檔案

版號 1.1.1：`mmproof_model.TOOL_VERSION`、`install.ps1`／`install.sh`／`uninstall.ps1`／`uninstall.sh` 檔頭與版號、`app.js` 檔頭、README（版本、1.1.1 的改變、§2 安裝檔名、§5.1、§8 相容表）。安裝程式行為不變（升級保留 `state\` 與 `config.json`）。

---

## 附錄 A 實測（〔實測〕2026-11-08，Windows 11、Python 3.12.13）

- `tests/run_tests.py`（repo 內的 Pro 取最新版 2.4.1）：單元 **61/61**、整合 **79/79**、安裝與移除 **31/31**、打包 **10/10**、瀏覽器 **38/38**，合計 219/219。
  - 新增單元 4 項：`test_v111_table`（判定表每一列與訊息）、`test_v111_permission_and_oserror`（mock）、`test_v111_marker_combo`、`test_v111_same_as_pro`（原因文字與 Pro 2.4.1 原始碼相同；同一批 18 種檔案，校稿與 Pro 的判定逐一相同）。`test_local_only_state` 依版號改寫（`"true"`、`1`、`null`、壞 JSON 在 1.1.1 是 `config-unreadable`）。
  - 新增整合 1 項：壞 JSON 與值看不懂各一，服務啟動後才弄壞 → 首頁 `local_only_global_source`／訊息、每份來源（含 `config-unreadable+marker`）、頁面與重做原因、409 `local_only` 的訊息含原因與路徑、定稿照常、修好後恢復。
  - 新增瀏覽器 2 項：首頁卡片提示字依來源（標記檔、全域設定〔1.1.0 的誤寫已修〕、config.json 讀不了）與標題旁「本機限定（config.json 讀不了）」；頁首說明與說明列。
- 發行檔：`meeting-minutes-proofread-v1.1.1-installer.zip`，17 檔、89,135 bytes，SHA-256 `11e4cb1218d666c36e7e92ac925775a4a19b6bfa9237ff1b9aca548de11d132b`；`.cmd` CRLF＋ASCII、`.ps1` UTF-8 BOM、外部網址 0。
- 實機（真實安裝升級到 1.1.1，Pro 2.4.1；PowerShell 5.1 `install.ps1` exit 0，只換校稿自己的 7 檔，`state\`、`config.json`、Pro 不變）：指到暫存 `$MMH`（壞 JSON → 值看不懂），Playwright 無頭 Chrome 10 項全過：頁首標示、說明列、重做區塊停用與原因、`POST …/redo` 409 `local_only`（訊息含原因與路徑）、首頁標題旁「本機限定（config.json 讀不了）」、卡片提示字、外部請求 0、頁面錯誤 0。真實安裝的 `proofread\state\` 沒有被動到。
