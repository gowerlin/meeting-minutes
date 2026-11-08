# 會議記錄校稿（meeting-minutes-proofread）1.1 規格（公開版）：認得本機限定；測試可攜

> **公開版**：本檔是會議記錄校稿 **1.1.0** 規格的公開版，適用 1.1.x。內容是 **1.1.0 相對 1.0.0 的差異**；本檔沒有提到的行為一律照
> 1.0 規格（公開版 [`meeting-minutes-proofread-1.0-spec.md`](meeting-minutes-proofread-1.0-spec.md)；下稱「1.0 規格」）與 1.0.0 的程式。
> 搭配：meeting-minutes-pro 2.4 規格（公開版 [`meeting-minutes-pro-2.4-spec.md`](meeting-minutes-pro-2.4-spec.md)，下稱「Pro 2.4 規格」）§2、§7。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 1.1.0 §x.y」就是本檔的同一節。
> 版本目錄 `V/`＝`proofread/meeting-minutes-proofread-v1.1.0/`（公開 repo 的路徑）。
> 標示：**〔實測〕**＝實作時實測的結果（附錄 A）；**〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節。

---

## 0. 摘要

| 項目 | 一句話 | 章節 |
|---|---|---|
| 認得本機限定 | Pro 的 `config.json` 的 `privacy.local_only: true`，或輸出資料夾的 `local-only.json` → 這份是本機限定 | §1 |
| 重做停用 | 「用定稿重做會議記錄／筆記」停用並寫原因（本機限定、會送到 GPT 或 Claude、怎麼解除）；API 409 `local_only`，連費用估算也不做 | §2 |
| 標示 | 頁首檔名旁「本機限定」標示（滑鼠移上去看原因）、頁面上方一行說明；首頁清單在那一份旁標示，全域設定時首頁標題旁「本機限定（整部電腦）」 | §3 |
| 其他照常 | 人工修改、定稿、定稿字幕、名詞同步、經驗匯入、復原 | §2 |
| 相容 | 搭 Pro 2.2／2.3 時只認標記檔與（設定裡有的話）全域鍵；不 import Pro 的新函式 | §4 |
| 測試可攜 | Pro 位置：環境變數 → 開發用 repo 的 `meeting-minutes-pro-skill/` → 公開 repo 的 `pro/`，取最新版本目錄；以 Pro 2.2.x 為前提的斷言依實際版號；沒有 Pro ≥ 2.3.0 的目錄時略過連動測試並寫原因；`test_exec_bit_in_index` 只在開發 repo | §5 |

不做：不改標記解析、存檔格式（`session.json` 格式不變，1.0.0 開得起 1.1.0 存的稿）、安裝與移除流程（只改版號）、Pro 的任何檔。

---

## 1. 判定（`mmproof_pro.py`）

- `LOCAL_ONLY_MARKER = "local-only.json"`（與 Pro 2.4.0 `common.LOCAL_ONLY_MARKER` 相同；`test_units.test_marker_name_matches_pro` 檢查）。
- `local_only_state(home, folder=None)`：讀 `<$MMH>/config.json`，`privacy.local_only` 是 JSON `true` → `config`；`folder/local-only.json` 存在 → `marker`。
  回傳 `None` 或 `{"sources", "source", "message"}`。`message`＝「本機限定（<原因>）：這份不送 GPT 或 Claude，「用定稿重做」會送出內容，所以停用。要解除：<…>」。
  設定檔讀不到或壞掉當作沒有全域鍵；標記檔只看存在。
- `Pro.local_only(folder)` 包一層。每次讀取時判定（不快取），使用者刪掉標記檔後重新整理頁面就恢復〔規格決定〕。
- 自己讀檔、不呼叫 Pro 的 `common.local_only_state()`〔規格決定：Pro 2.2／2.3 沒有這個函式，介面檢查表（1.0 規格 §2.2）也不必改〕。

## 2. 伺服器（`mmproof_server.py`）

| API | 1.1.0 |
|---|---|
| `GET /api/doc/<id>/data` | 新增 `local_only`（判定結果或 `null`）；`redo.available` ＝ Pro ≥ 2.3.0 **且**不是本機限定；`redo.reason` 本機限定時是 `local_only.message`（優先於「升級 Pro」），否則同 1.0；`redo.local_only`（布林） |
| `POST /api/doc/<id>/redo`（含 `dry_run`） | 本機限定 → **409 `local_only`**（訊息＝`message`），不跑 `auto_minutes.py --estimate-only`、不寫任何檔 |
| `GET /api/docs` | `open[]`、`recent[]` 每一項多 `local_only`；頂層多 `local_only_global` |
| 其他（存檔、定稿、同步、經驗匯入、復原、媒體） | 不變 |

## 3. 畫面（`static/app.js`、`app.css`）

- `loTag(text, title)`：`<span class="tag lo">本機限定</span>`（`--warn` 色、粗體、文字寫明，不只靠顏色；與相鄰元素間距 8px）。
- 頁首：檔名後面一個 `loTag`，`title` 是原因與解除方法。頂端列在 1440px 仍一行〔實測：瀏覽器測試〕。
- 提示列（`bn('info', …)`）：「本機限定：這份不送 GPT 或 Claude。人工修改、定稿、經驗匯入照常；「用定稿重做會議記錄」停用。」
- 定稿側欄的重做區塊沿用 1.0 的「目前不能用：<reason>。」與按鈕停用。
- 首頁：卡片名稱旁 `loTag`；全域設定時標題旁「本機限定（整部電腦）」。

## 4. 相容（版本相容表，更新 1.0 規格 §2.4）

| 會議記錄校稿 | Pro 2.2.x | Pro 2.3.0 | Pro 2.4.0 |
|---|---|---|---|
| 1.0.0 | 可用；重做停用 | 全部可用 | 可用；不認得本機限定（本機限定的那份按重做時 Pro 拒絕，exit 6，不送出） |
| 1.1.0 | 可用；重做停用；認得標記檔與全域鍵 | 可用；本機限定時重做停用 | 全部可用；本機限定時重做停用 |

最低需求仍是 Pro 2.2.0（`MIN_PRO` 不變）；建議 Pro 2.4.0。整合測試以假的 Pro 2.2.0／2.3.0／2.4.0（由 repo 內最新 Pro 複製、只改版號）各跑：標記檔、全域、沒有本機限定三種〔實測〕。

## 5. 測試可攜

| 項目 | 1.1.0 |
|---|---|
| 位置 | 新檔 `tests/locate.py`：本工具＝tests 上一層版號最高的 `meeting-minutes-proofread-v<X.Y.Z>`；Pro scripts＝`MMPROOF_TEST_PRO_SCRIPTS`（scripts 目錄）→ `MMPROOF_TEST_PRO_DIR`（Pro 版本目錄）→ 開發用 repo 的 `meeting-minutes-pro-skill/` → 公開 repo `pro/`（版號最高）；Pro 版號讀 `common.py` 的 `VERSION` |
| 使用的地方 | `helpers.py`（`APP`、`PRO_SCRIPTS`、`PRO_VERSION`、`TOOL_VERSION`）、`test_dist.py`、`test_install.py`、`test_units.py`、`test_server.py`、`browser_check.mjs`（經 `python -c "import locate"` 取路徑） |
| 依版號判斷 | `test_units.test_real_pro_passes`（版號＝實際）、`test_redo_gate`（可用＝Pro ≥ 2.3.0）；`test_server` 的「重做停用」在 Pro ≥ 2.3.0 時改測「可用」，停用情境改用假的 Pro 2.2.0（本機限定一節）；`browser_check.mjs` 一律用假的 Pro 2.2.0（`materials.py --fake-pro`）測停用畫面 |
| 沙盒的假 Pro | `test_install.make_sandbox()` 從最新 Pro 複製 scripts，一律改成要測的版號 |
| 略過 | Pro 解除安裝連動（`install.ps1`／`install.sh` 的 `Uninstall-Proofread`）用 repo 內最新的 Pro；沒有 ≥ 2.3.0 的版本目錄時略過，原因「repo 內的 meeting-minutes-pro 是 X，沒有 2.3.0 以上的版本目錄（解除安裝連動從 2.3.0 開始）」 |
| 開發用 repo 才檢查 | `test_exec_bit_in_index`：`locate.IS_DEV_REPO`（有 `meeting-minutes-pro-skill/`）才跑；公開 repo 略過（公開 repo 的執行權限在發布時設定） |

說明網站〈給開發者〉同步拿掉「在公開 repo 跑測試的預期失敗」一段。

## 6. 版號與檔案

版號 1.1.0：`mmproof_model.TOOL_VERSION`、`install.ps1` `$Version`、`install.sh` `VERSION`、README「版本 1.1.0」、版本目錄名稱（`tools/make_dist.py` 檢查一致）；`app.js` 第一行、`uninstall.*` 標題。
README：開頭一段、〈5.1 本機限定（機敏會議）〉、版本相容表、隱私與安全一句、安裝包檔名。

---

## 附錄 A 實測（〔實測〕2026-11-08，Windows 11、Python 3.12.13）

| 配置 | `tests/run_tests.py` |
|---|---|
| 開發用 repo（Pro 取 repo 內最新 2.4.0） | **212/212 PASS**：單元 57、整合 78、安裝與移除 31、打包 10、瀏覽器 36 |
| 假裝公開 repo（暫存區 `git init`：`pro/meeting-minutes-pro-v2.4.0/`、`proofread/{meeting-minutes-proofread-v1.1.0, tests, tools, .gitattributes}`，從要匯出的檔 `git archive` 取出、`.cmd` 依 `.gitattributes` 重新 checkout 成 CRLF） | **211/211 PASS**：打包 9（`test_exec_bit_in_index` 依設計略過） |

- 整合：本機限定 4 項（標記檔、全域、沒有本機限定、其他功能照常）× 假的 Pro 2.2.0／2.3.0／2.4.0。
- 瀏覽器（Playwright＋本機 Chrome）：頁首「本機限定」標示與提示列、首頁只有放了標記檔的那份標示（標示與名稱間距 8.0 px、頂端列 1 行）；截圖 `tests/_out/screenshots/local-only-1440-dark.png`、`home-local-only-1440-dark.png`。
- 安裝包 `meeting-minutes-proofread-v1.1.0-installer.zip`：17 檔，86,564 bytes，SHA-256 `e9a60fb04a2b61b793128c76ce78011ee4368aad226c6502eb00a9d2224bb899`；解開後去識別掃描命中 0。
- 發版時的實機驗證（Pro 2.4.0＋本工具 1.1.0，合成素材）見 Pro 2.4 規格附錄 A.4：本機限定的那一份頁首與首頁標示、重做停用，重做 API（`dry_run`）回 409 `local_only`；人工修改後定稿成功。
