# meeting-minutes-pro 2.4.1 規格（公開版）：config.json 讀不了時當成本機限定（安全修正）

> **公開版**：本檔是 meeting-minutes-pro **2.4.1** 規格的公開版。內容是 **2.4.1 相對 2.4.0 的差異**（修正版，只修一類問題）；本檔沒有提到的行為一律照
> 2.4 規格（公開版 [`meeting-minutes-pro-2.4-spec.md`](meeting-minutes-pro-2.4-spec.md)；下稱「2.4 規格」）與 2.4.0 的程式。
> 搭配：會議記錄校稿 1.1.1 規格（公開版 [`meeting-minutes-proofread-1.1.1-spec.md`](meeting-minutes-proofread-1.1.1-spec.md)），判定表與本檔 §2.2 相同。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 2.4.1 §x.y」就是本檔的同一節。
> 版本目錄 `V/`＝`pro/meeting-minutes-pro-v2.4.1/`（公開 repo 的路徑）。
> 標示：**〔實測〕**＝實作時以合成素材實測的結果（附錄 A）；**〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節（附理由）。
> 「`$MMH`」＝`MEETING_MINUTES_PRO_HOME`；「全域本機限定」＝2.4 規格 §2.1 的第二種開法（`config.json` 的 `privacy.local_only`）。

---

## 0. 摘要

### 0.1 問題

| # | 2.4.0 的行為 | 後果 |
|---|---|---|
| 1 | `common.load_config()` 遇到任何例外都回 `{}`，`local_only_state()` 因此判定「不是本機限定」；會議記錄校稿 1.1.0 `mmproof_pro.local_only_state()` 也是 `(OSError, ValueError)` 時當成 `{}` | 使用者開了全域本機限定，`config.json` 卻因為手改出錯、編碼不對、被鎖住而讀不了時，AI 校正與整理照常**送出** |
| 2 | `save_config()`（`setup_backend.py` 用）、`upgrade_config()`（安裝程式用）先 `load_config()` 再整份寫回 | `config.json` 一讀不了，重新安裝或後端設定就把整份設定洗掉，連帶把 `privacy.local_only: true` 改回 `false` |
| 3 | 只有 `is True` 算開；`"true"`、`1`、`null`、`privacy` 不是物件都當成關 | 使用者手打 `"true"`（字串）時以為開了、其實沒開 |

### 0.2 2.4.1 做什麼

- `config.json` 讀取分成**不存在／讀得到／讀不了（附原因）**三種結果（§2.1）；全域本機限定照 §2.2 的判定表：**讀不了或值看不懂一律當成開**（新來源 `config-unreadable`）。
- 新來源接到所有地方：拒絕訊息、`run_log` 的 `privacy` 事件、`runs.jsonl`、`auto_correct.py`／`auto_minutes.py` 的 JSON、`transcribe.py`、兩支入口的黃字與結束畫面、`--estimate-only` 的提醒、安裝摘要、SKILL（§4、§5）。
- **寫入端**遇到讀不了的檔一律不寫：丟 `ConfigUnreadable`、安裝程式 exit 非 0，原檔逐位元不變（§3）。
- 其他設定（後端、詞表…）在讀不了時照舊用預設值，`transcribe.py` 開頭多印一行警告（§3.3）。

### 0.3 不做什麼

- 不改 2.4.0 的設定鍵、旗標、輸出檔與入口題目；不改 `local-only.json`（標記檔只看存在，照 2.4 規格 §2.2）。
- 不自動修復或改寫壞掉的 `config.json`（只有使用者自己修好或刪掉）。
- 讀得到、值看不懂的檔（`privacy.local_only: "true"` 等）**不算讀不了**：寫入端照常寫、值原樣保留（§3.2）。

---

## 1. 版號與檔案

| 項目 | 內容 |
|---|---|
| 版號 | 2.4.1：`common.VERSION`、`render_html.FALLBACK_VERSION`（runtime 與 skill 兩份）、SKILL 版本註解、`install.ps1` `$Version`、`install.sh` `VERSION`、README「版本」與下載表、兩支入口檔頭、`THIRD-PARTY-NOTICES.md` 標題 |
| 改動的程式 | `scripts/common.py`、`transcribe.py`、`auto_correct.py`、`auto_minutes.py`、`runlog.py`、`setup_backend.py`、`setup_gpu_diar.py`；`mm-sendto.ps1`、`mm-dropped.sh`；`install.ps1`、`install.sh` |
| 改動的文件 | README（開頭〈2.4.1 安全修正〉、§17〈config.json 讀不了或值看不懂〉）、SKILL §0.1（判定改用 `common.py local-only`）；upload zip 重新產生（只有 SKILL 不同） |
| 退出碼 | 拒絕送出照舊 `6`（`LOCAL_ONLY_EXIT`）；新增 `5`（`CONFIG_UNREADABLE_EXIT`）：`common.py check-config`、`setup_backend.py`、`setup_gpu_diar.py`（會寫入的用法）遇到讀不了的檔 |

## 2. 判定

### 2.1 讀取的三種結果（`common.read_config()`）

`read_config()` 不丟例外，回傳 `{"status", "config", "path", "reason", "detail"}`：

| status | 條件 | config | reason（原因代碼） | 畫面文字（`CONFIG_PROBLEM_TEXT`） |
|---|---|---|---|---|
| `missing` | `FileNotFoundError` | `{}` | — | — |
| `ok` | 讀得到，UTF-8，合法 JSON，最外層是物件 | 內容 | — | — |
| `unreadable` | `PermissionError`（不是資料夾時） | `{}` | `permission` | 沒有讀取權限 |
| 〃 | 其他 `OSError`（例：被別的程式鎖住） | `{}` | `os_error` | 讀取失敗（附系統訊息） |
| 〃 | 是資料夾（`IsADirectoryError`，或 Windows 對資料夾回的 `PermissionError`） | `{}` | `is_dir` | 是資料夾，不是檔案 |
| 〃 | 空檔或只有空白 | `{}` | `empty` | 是空檔 |
| 〃 | 不是 UTF-8 | `{}` | `not_utf8` | 不是 UTF-8 編碼（附第幾個位元組） |
| 〃 | 不是合法 JSON；**開頭有 BOM**〔規格決定〕 | `{}` | `bad_json` | 不是合法的 JSON（附第幾行第幾欄；BOM 時附「開頭有 BOM，請存成不含 BOM 的 UTF-8」） |
| 〃 | 最外層不是物件（陣列、字串、數字、`null`…） | `{}` | `not_object` | 最外層不是 JSON 物件（附「是陣列」等） |

- **BOM 歸「不是合法的 JSON」**〔規格決定〕：2.4.0 的 `load_config()`（`encoding="utf-8"`）讀到 BOM 也會失敗、整份設定用預設值，所以這類檔在 2.4.0 本來就沒有生效；照判定表當成讀不了，最保守，訊息直接說怎麼存。安裝程式與 Python 都不會寫出 BOM（PowerShell 端不寫 `config.json`）。
- `load_config()` 改成 `read_config()["config"]`：不存在或讀不了都回 `{}`（一般設定照舊用預設值）；2.4.0 對「最外層是陣列」會回陣列（之後 `.get()` 出錯），2.4.1 回 `{}`。
- 要分辨不存在與讀不了，一律用 `read_config()`。

### 2.2 判定表（全域本機限定；Pro 與會議記錄校稿一致）

| config.json 狀態 | 全域本機限定 | 來源 |
|---|---|---|
| 不存在（`FileNotFoundError`） | 關（照舊） | — |
| 讀得到、最外層是物件，且 `privacy` 不存在，或 `privacy.local_only` 不存在或是 `false` | 關 | — |
| `privacy.local_only` 是 `true` | 開（照舊） | `config` |
| 存在但讀不了（§2.1 的 `unreadable`：權限、被鎖、其他 `OSError`、資料夾、不是 UTF-8、不是合法 JSON、空檔、最外層不是物件） | **開** | `config-unreadable` |
| `privacy` 不是物件，或 `local_only` 是 `true`／`false` 以外的值（字串、數字、`null`…） | **開**（原因「值看不懂」，代碼 `bad_value`） | `config-unreadable` |

- 實作：`common.config_local_only(cfg=None)` 回傳 `None`、`{"source": "config"}` 或 `{"source": "config-unreadable", "reason", "detail", "path"}`；`local_only_state(out_dir, cfg)` 把它與標記檔合在一起。
- **`cfg` 參數**（2.4.0 的呼叫方式，例 `auto_correct.run(cfg=load_config())`）：檔案讀得到時照 `cfg` 的值判斷（相容既有呼叫與測試）；**檔案讀不了時一律是 `config-unreadable`**，不看傳進來的 `cfg`（傳進來的通常就是讀不了時的 `{}`）。
- `LOCAL_ONLY_SOURCES` ＝ `("config", "config-unreadable", "marker")`；與標記檔同時成立時 `source` 是 `config-unreadable+marker`。
- `local_only_state()` 的回傳多一個鍵 `config_problem`（`reason`、`detail`、`path`），只在來源有 `config-unreadable` 時出現。

### 2.3 新來源值與相容性

- 新來源值只有 `config-unreadable` 一個（讀不了與值看不懂共用；原因代碼分開記）。
- `runs.jsonl`、`run_summary` 的欄位不變（`local_only`、`local_only_source`），只多一種值；2.4.0 的讀法（`local_only_source` 用 `+` 拆開）照樣能讀：`config-unreadable` 不含 `+`。
- `auto_correct.py`／`auto_minutes.py` 的 JSON、`transcribe.py` 的 JSON 欄位名稱不變（`local_only_source`、`local_only`），只新增 `local_only_config_reason`（§4）。

### 2.4 訊息原文

拒絕送出（`local_only_message()`，stderr；「AI 校正」處依步驟換成「AI 整理（會議摘要／筆記）」）：

```text
本機限定（config.json 讀不了：不是合法的 JSON（第 3 行第 5 欄）；為了不外送，已當成本機限定）：AI 校正會把內容送到 GPT 或 Claude，已拒絕，沒有送出任何資料。要解除：修好 %LOCALAPPDATA%\meeting-minutes-pro\config.json（存成 UTF-8 的 JSON 物件）；或刪掉它再重新執行安裝程式（重建的 config.json 本機限定是關）。
本機限定（config.json 的值看不懂：privacy.local_only 是 "true"，只認得 true 或 false；為了不外送，已當成本機限定）：AI 整理（會議摘要／筆記）會把內容送到 GPT 或 Claude，已拒絕，沒有送出任何資料。要解除：修好 %LOCALAPPDATA%\meeting-minutes-pro\config.json（privacy.local_only 只能是 true 或 false）；或刪掉它再重新執行安裝程式（重建的 config.json 本機限定是關）。
```

- 原因句（`local_only_why()`）：`config.json 讀不了：<CONFIG_PROBLEM_TEXT>（<detail>）；為了不外送，已當成本機限定`；值看不懂是 `config.json 的值看不懂：<detail>；為了不外送，已當成本機限定`。`privacy` 不是物件時 detail 是「privacy 應該是物件（{ … }），現在是 true」。
- 解除句（`local_only_how()`）：如上；`config` 與 `marker` 兩種來源的句子與 2.4.0 相同。
- 「刪掉等於回到預設」寫成「刪掉它再重新執行安裝程式（重建的 config.json 本機限定是關）」〔規格決定〕：刪掉 `config.json` 後後端設定也跟著沒了（轉寫會改用 openvino/CPU），要重新執行安裝程式才完整；只說「刪掉就恢復」會誤導。

寫入端拒絕（`config_write_refused_message()`；安裝程式與 `setup_*.py` 印出）：

```text
config.json 讀不了：不是合法的 JSON（第 3 行第 5 欄）：%LOCALAPPDATA%\meeting-minutes-pro\config.json
為了不覆寫你的設定（包括本機限定 privacy.local_only），這次沒有寫入任何東西，檔案沒有被改動。
請修好這個檔（UTF-8 的 JSON 物件，例如用記事本打開找出錯誤），或刪掉它，然後重新執行。刪掉的話，重新執行安裝程式會建立新的 config.json（本機限定是關，硬體重新偵測）。
```

## 3. 寫入端與其他設定

### 3.1 盤點（〔實測〕搜尋整個版本目錄：`load_config`、`save_config`、`upgrade_config`、`config_path`、`config.json`、`json.dump`）

| 程式 | 讀／寫 | 2.4.0 | 2.4.1 處置 |
|---|---|---|---|
| `common.save_config()` | 讀＋寫（整份寫回） | 讀不了 → `{}` 再寫回（洗掉設定） | `load_config_for_write()`：讀不了 → `ConfigUnreadable`，不寫 |
| `common.upgrade_config()` | 讀＋寫（整份寫回） | 同上 | 同上 |
| `setup_backend.py` | 讀（`load_config` ×3）＋寫（`save_config` ×2） | 同上 | `main()` 一開始 `read_config()`：讀不了 → 印 §2.4 訊息、exit 5，不下載、不實測、不寫；`--punct-only`（不碰設定）照常。`save_config()` 本身也會丟 |
| `setup_gpu_diar.py` `set_status()` | 讀＋寫 | 同上 | `load_config_for_write()` 丟 `ConfigUnreadable`；`main()` 的 `--set-status` 與預設流程先檢查，讀不了 → 印訊息、JSON `reason: config_unreadable`、exit 5；`--check-torch`／`--prepare`／`--smoke`（不碰設定）照常 |
| `install.ps1` 內嵌 Python（「更新設定」） | 讀＋寫（`upgrade_config`；之後 GPU 結果再整份寫一次） | 讀不了 → 洗掉後寫回 | 一開始的 `Assert-ConfigReadable`（§3.2）先擋；萬一途中變得讀不了，`upgrade_config()` 丟例外 → exit 5 → `Fail`（exit 1） |
| `install.ps1` `-RemoveGpuDiar` | 寫（`setup_gpu_diar.py --set-status none`） | 同上 | exit 5 → 黃字「config.json 讀不了，沒有更新（原檔沒有被改動…）」 |
| `install.ps1` `Read-Config`／摘要 | 讀（PowerShell `ConvertFrom-Json`） | 讀不了 → `$null`（預設） | 不變；摘要的「本機限定」改用 `common.py local-only`（§4） |
| `install.sh` 內嵌 Python、`cfg_get`、摘要 | 讀＋寫 | 同 `install.ps1` | 同 `install.ps1`：`assert_config_readable`、exit 5 → `fail`、摘要用 `common.py local-only --lines`〔推論：macOS 未實測〕 |
| `mm-sendto.ps1` | 讀（`ConvertFrom-Json`：顯示、`content_type.default`、CLI 路徑、`ask_default`…） | 讀不了 → `$null`（預設） | 不變；全域本機限定改由 `common.py local-only` 判定（§4） |
| `mm-dropped.sh` | 讀（`cfg_get`、`sed` 版號） | 同上 | 同上（`--lines`） |
| `transcribe.py` | 讀 | 讀不了 → 預設，印「找不到 config.json」 | 讀不了時改印 §3.3 的警告；判定照 §2.2 |
| `auto_correct.py`、`auto_minutes.py` | 讀 | 讀不了 → 不是本機限定 | 照 §2.2（exit 6） |
| `consistency.py`、`refs.py`、`subtitles.py`、`render_html.py`、`content_types.py`、`common.version_banner()` | 讀 | 讀不了 → 預設 | 不變（只讀一般設定） |
| SKILL §0.1（Claude 對話中的檢查指令） | 讀（`json.load`，讀不了時指令出錯） | 判定不明確 | 改用 `common.py local-only --out-dir …`；指令失敗也照本機限定處理（§5） |
| 其他寫入：`state.json`（入口）、`corrections.tsv`、歷史、`runs.jsonl`、標記檔 | — | — | 不是 `config.json`，不在本版範圍 |

### 3.2 寫入端處置

- 檔案**存在但讀不了**：一律不寫，丟 `ConfigUnreadable`（訊息 §2.4），原檔逐位元不變。**不存在**照舊建立；**讀得到、值看不懂**照常寫（`_fill_missing` 不動既有值，`privacy: true`、`local_only: "true"` 原樣保留，之後照 §2.2 當成開）。
- **安裝程式一開始就檢查**（`install.ps1` `Assert-ConfigReadable`、`install.sh` `assert_config_readable`），位置在選單、Breeze 與自動校正的詢問之前，也在複製任何檔之前：
  - 交給 payload 的 `scripts/common.py check-config`（只用標準函式庫）；Python 用已安裝的 venv（版本合格時），否則系統的 Python 3.10～3.13（`Find-Python`；macOS 依序找 `python3.12`…`python3`）。
  - exit 5 → `Fail`／`fail`（exit 1），訊息照 §2.4；其他非 0 → 「無法檢查 …。為了不覆寫設定，這次沒有安裝任何東西」並 exit 1（寧可停下）。
  - 找不到任何 Python 時：`install.ps1` 用 `Test-ConfigFilePs`（資料夾、讀取失敗、嚴格 UTF-8、空檔、BOM、最外層不是 `{`、`ConvertFrom-Json`）做同樣的分類〔規格決定：第一次安裝時通常還沒有 Python，但這時也不會有 `config.json`〕；`install.sh` 只檢查資料夾、讀不到、空檔。
- `upgrade_config()`、`save_config()`、`setup_gpu_diar.set_status()` 的保護是第二道防線（安裝途中檔案被改壞、或使用者單獨執行 `setup_*.py`）。

### 3.3 其他設定（`transcribe.py`）

讀不了時一般設定照舊用預設值（後端 openvino/CPU 等），開頭印一行（取代 2.4.0 的「找不到 config.json」）：

```text
  [!] config.json 讀不了：不是合法的 JSON（第 1 行第 19 欄）：<路徑>。這次的設定都用預設值（暫以 openvino/CPU 執行），而且當成本機限定（不送 GPT 或 Claude）；請修好它，或刪掉後重新執行安裝程式
```

接著照 2.4.0 印本機限定行，`config-unreadable` 這個來源改寫出原因：`本機限定（config.json 讀不了：…；為了不外送，已當成本機限定）：不會送出任何資料到 GPT 或 Claude`（`config`、`marker` 照 2.4.0 的短稱「config.json」「標記檔」）。值看不懂時其他設定照讀，不印讀不了的警告。管線內校正照 2.4 規格 §2.3（明確 `--correct` exit 6；`correction.enabled` 開著 exit 0）。

### 3.4 入口（`mm-sendto.ps1`、`mm-dropped.sh`）

- 全域本機限定改由 `& $Py scripts\common.py local-only`（bash：`"$PY" "$SCR/common.py" local-only --lines`，4 行：`1`／`0`、來源、原因、解除方法）判定，不再自己讀 `privacy.local_only`（PowerShell 的 `-eq $true` 會把字串 `"true"` 當成真，bash 的 `cfg_get` 讀不了時是空字串，兩邊都和 Python 不一致）。
- 判定程式**沒有回應**（沒有 JSON）時也當成本機限定〔規格決定〕：原因「無法確認 config.json 的本機限定設定（scripts\common.py 沒有回應）」、解除「重新執行安裝程式」（來源 `check-failed`，只在入口畫面出現，不寫 log）。venv 不存在時入口照 2.4.0 直接結束（「尚未安裝 runtime」）。
- 畫面：來源是 `config` 時字串與 2.4.0 相同；`config-unreadable` 時黃字 `本機限定（<原因>）：這次不會把任何資料送到 GPT 或 Claude；…` 後面多一行黃字 `要恢復：<解除方法>`；**不問 AI 校正與整理、不偵測 CLI**（2.4 規格 §3）；結束畫面「要解除本機限定（之後才能用 AI 校正與整理）：全部：<解除方法>」。

## 4. `run_log`、JSON 與安裝摘要

| 位置 | 2.4.1 |
|---|---|
| `run_log.jsonl` 的 `privacy` 事件 | `local_only_source: "config-unreadable"`（或 `config-unreadable+marker`），另記 `config_reason`（§2.1 的代碼；不記路徑與內容） |
| `run_summary`、`$MMH/logs/runs.jsonl` | `local_only: true`、`local_only_source: "config-unreadable"`（欄位與 2.4.0 相同） |
| `auto_correct.py`／`auto_minutes.py` 的 stdout JSON | `reason: local_only`、`local_only_source: "config-unreadable"`，另加 `local_only_config_reason`；exit 6；不找 CLI、不讀逐字稿、不寫紀錄檔（照 2.4 規格 §2.3） |
| `transcribe.py` 的 stdout JSON | `local_only: "config-unreadable"` |
| `auto_minutes.py --estimate-only` | 照常預估（不送內容），提醒句末加原因：`本機限定：這裡只有預估（沒有送出任何資料）；正式執行會被拒絕（<原因>）` |
| 安裝摘要 | `common.py local-only`：`config` → 2.4.0 的字串；`config-unreadable` → `本機限定：開（<原因>；每一份都不送 GPT 或 Claude，…）` ＋ `要恢復：<解除方法>`（黃字）；否則「關」 |
| `common.py` 命令列 | `local-only [--out-dir 資料夾] [--lines]`（JSON：`local_only`、`source`、`sources`、`why`、`how`、`config_problem`；exit 0）、`check-config`（JSON：`status`、`reason`、`detail`、`path`；讀不了 exit 5） |

## 5. SKILL（Claude 對話）

§0.1 的開始前檢查改成 `"$PY" "$MMH/scripts/common.py" local-only --out-dir "<檔名>_minutes"`：`local_only: true` 就照本機限定處理（`why`、`how` 照原文告訴使用者；`config.json` 讀不了或值看不懂時也是 `true`，`source` 是 `config-unreadable`）；**指令失敗或沒有印出 JSON 時也照本機限定處理**；不要自己讀 `config.json` 判斷。標記檔也由同一個指令判定（`--out-dir`）。

## 6. 會議記錄校稿

校稿 1.1.1（公開版規格 [`meeting-minutes-proofread-1.1.1-spec.md`](meeting-minutes-proofread-1.1.1-spec.md)）用同一張判定表（`mmproof_pro.local_only_state()`，不 import Pro）；介面檢查用到的 `common.load_config` 名稱不變，行為對校稿相同（讀不了回 `{}`）。最低 Pro 版本維持 2.2.0，建議 2.4.1。

## 7. 文件與發行檔

- README：開頭〈2.4.1 安全修正〉、§17 加〈config.json 讀不了或值看不懂〉（判定表、畫面、寫入端停下、恢復方法）。
- 發行檔：`tools/make_dist.py` 產生 `meeting-minutes-pro-v2.4.1-installer.zip`、`-claude-app-upload.zip`（附 `.sha256`）。
- 影響範圍（給更版紀錄）：只有**全域**本機限定（`config.json` 的 `privacy.local_only`）受影響；只用本機限定右鍵入口（標記檔）的那幾份不受影響。2.4.0 的 workaround：用本機限定的右鍵入口，或確認 `config.json` 用 UTF-8 存、`privacy.local_only` 寫 `true`（不加引號）。

---

## 附錄 A 實測（〔實測〕2026-11-08，Windows 11、Python 3.12.13）

### A.1 單元測試

- `tests/` 全部：**Ran 687，OK（skipped 3：沒有設定 `MMP_V100_CONFIG`、`MMP_PUNCT_ARCHIVE`，測試 home 沒有真的標點模型）**；已安裝 runtime 的 venv（唯讀）、`python -B`、不帶 `MMP_TEST_VERSION`（取到 2.4.1）。
- 新增 `tests/test_v241.py` 35 項：`Table`（判定表每一列：不存在、`true`、5 種關、9 種讀不了、8 種值看不懂、資料夾、`PermissionError`／其他 `OSError`／`FileNotFoundError`（mock）、與標記檔並存、訊息）、`Writers`（`upgrade_config`／`save_config`／`set_status` 丟錯且原檔逐位元不變、值看不懂照常升級並保留、`setup_gpu_diar.py`／`setup_backend.py` exit 5、`common.py` 命令列）、`Refuse`（兩支腳本子行程實跑 exit 6、假 CLI 0 次、`run_log` 只有代碼）、`Transcribe`（警告、JSON、exit 6、對照組）、`InstallerPs`（PowerShell 7／5.1 實跑 `install.ps1 -TestRoot` 4 種壞檔 exit 1、原檔不變、沒有安裝任何東西；`Test-ConfigFilePs` 逐列）、`InstallerSh`（Git Bash 實跑 `assert_config_readable`）、`EntryStatic`、`Docs`。
- 刻意改變而改寫的舊斷言 2 處（依版號判斷，舊版照舊）：`test_v240.Config.test_only_true_counts`（`"true"`、`1`、`"yes"`、`null` 由「關」改成 `config-unreadable`）、`test_v230.ProofreadInterface.test_files_unchanged_from_220`（`load_config` 的原始碼改了，改成比對行為：不存在 → `{}`、讀得到 → 原內容、讀不了 → `{}`）。

### A.2 入口 harness

`entry_harness.py`：**177/177 通過**（59 個情境 × PowerShell 7／5.1／Git Bash）。新增 `local_only_config_broken`、`local_only_config_badvalue`：一般入口不問 AI、假 CLI 0 次、黃字原因與「要恢復：…」、結束畫面「全部：修好 …」。既有情境（含 2.4.0 的 3 個本機限定情境）的畫面字串不變。

### A.3 發行檔

| 檔案 | 內容 | 大小 | SHA-256 |
|---|---|---|---|
| `meeting-minutes-pro-v2.4.1-installer.zip` | 51 檔 | 491,726 bytes | `1a56c56e3410b4e4d5d4516a83c424e13164f1a5f8513ca253dfc9cbcbb6c968` |
| `meeting-minutes-pro-v2.4.1-claude-app-upload.zip` | 7 項（無巢狀 zip） | 59,577 bytes | `c6196ff488695de464e921a8f555bf809f3335a3ea1c665f930d23d791f95921` |

`deid-scan --internal-ids`＋私有詞表掃版本目錄、`tests/`、`tools/` 與兩個 zip：216 檔（zip 內 88 個）命中 0。

### A.4 實機驗證（發版時，真實安裝升級到 2.4.1 後；合成素材 M1）

- **升級**：Windows PowerShell 5.1 `install.ps1 -Target Both -Backend ct2:cuda -NoBreeze -NoCorrect`，exit 0；`config.json` 只改 `runtime_version`（`設定鍵無變更`），GPU、精度、詞表、對照表、`state.json`、`proofread\`、三個右鍵捷徑都不變；開頭的 `Assert-ConfigReadable` 用已安裝的 venv 通過。
- **fail-closed**（暫存 `$MMH`；`scripts`、入口複製自真實安裝，venv、GPU venv、模型以 junction 唯讀共用；真實 `config.json` 沒有被改）：
  - `privacy.local_only: "true"`：一般入口第一段黃字「本機限定（config.json 的值看不懂：privacy.local_only 是 "true"，只認得 true 或 false；為了不外送，已當成本機限定）…」＋「要恢復：…」；**不問 AI**；pyannote／GPU 4 位講者、43 段；結束畫面「本機限定：沒有送出任何資料」與「全部：修好 …」。`auto_correct.py`、`auto_correct.py --openai --force`、`auto_minutes.py`、`auto_minutes.py --claude --force --source original` **全部 exit 6**，`local_only_source: config-unreadable`、`local_only_config_reason: bad_value`；`run_log` 的 `privacy` 事件 `config_reason: bad_value`。
  - 壞 JSON（最後一個 `}` 換成 `,`）：入口黃字「config.json 讀不了：不是合法的 JSON（第 210 行第 1 欄）…」、不問 AI；`transcribe.py` 開頭印 §3.3 的警告，照 2.4.0 用預設的 openvino/CPU，這台沒有 openvino 模型 → 「無法以 openvino/CPU 載入」、轉寫失敗（與 2.4.0 相同；沒有連網）。同一份逐字稿的副本上兩支腳本 4 種呼叫都 exit 6（`bad_json`）；`--estimate-only` 照常預估並在提醒句末寫原因。壞檔逐位元不變。
  - 寫入端：`upgrade_config()` 丟 `ConfigUnreadable`；`setup_gpu_diar.py --set-status none` exit 5；2.4.1 安裝程式 `-TestRoot`（壞檔）PowerShell 5.1／7 都 exit 1、什麼都沒裝、原檔不變。
  - 行程監看（約 4 分鐘，382 次輪詢）：新的 `codex` 行程 0；同時間有 2 個新的 `claude` 行程，是另一個終端機分頁啟動的，父行程不在測試的行程鏈上；三個測試資料夾的 `run_log` `call` 事件都是 0。
- **一般流程**（真實 `config.json`，沒有本機限定）：`auto_correct.py --openai` 對合成逐字稿照常送出：GPT gpt-6.1-sol（Codex CLI）1 段、68 秒，修改 53 處；`run_log` `call` 1 筆；行程監看 1 個 `codex.exe`。
