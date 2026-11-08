# meeting-minutes-pro 2.4 規格（公開版）：本機限定（機敏會議）、供應商名稱統一

> **公開版**：本檔是 meeting-minutes-pro **2.4.0** 規格的公開版，適用 2.4.x。內容是 **2.4.0 相對 2.3.0 的差異**；本檔沒有提到的行為一律照 2.3 規格
> （公開版 [`meeting-minutes-pro-2.3-spec.md`](meeting-minutes-pro-2.3-spec.md)；下稱「2.3 規格」）與 2.3.0 的程式。
> 搭配：會議記錄校稿 1.1 規格（公開版 [`meeting-minutes-proofread-1.1-spec.md`](meeting-minutes-proofread-1.1-spec.md)）。
> **2.4.1 修正**（`config.json` 讀不了或值看不懂時當成本機限定、寫入端不覆寫）見 [`meeting-minutes-pro-2.4.1-spec.md`](meeting-minutes-pro-2.4.1-spec.md)。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 2.4.0 §x.y」就是本檔的同一節。
> 版本目錄 `V/`＝`pro/meeting-minutes-pro-v2.4.0/`（公開 repo 的路徑）。
> 標示：**〔實測〕**＝實作時以合成素材實測的結果（附錄 A）；**〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節（附理由）。
> 「`$MMH`」＝`MEETING_MINUTES_PRO_HOME`；「輸出資料夾」＝`<檔名>_minutes/`；「本機限定」＝本版新增的機敏會議模式。

---

## 0. 摘要

### 0.1 2.4.0 做什麼

| 功能 | 一句話 | 章節 |
|---|---|---|
| 本機限定（兩種開法） | 全域 `config.json` 的 `privacy.local_only: true`，或輸出資料夾的標記檔 `local-only.json`（第二個右鍵／拖放入口寫入）；任一成立就是本機限定 | §2.1、§2.2 |
| 拒絕送出 | `auto_correct.py`、`auto_minutes.py`、`transcribe.py` 管線內校正：exit 6、`reason: local_only`、固定訊息（為何、如何解除）；沒有旗標可以略過 | §2.3 |
| 本機步驟照常 | 轉寫、對照表與詞表、分段標點、字幕、網頁版、`refs.py plan`、`consistency.py`、`--estimate-only`、`--render-only` | §2.4 |
| `run_log` 欄位 | `privacy` 事件；`run_summary`／`runs.jsonl` 只在本機限定時多 `local_only`、`local_only_source` | §2.5 |
| 入口 | 「會議轉寫（Pro，本機限定）」：不偵測 CLI、不問 AI，結束畫面「本機限定：沒有送出任何資料」＋提示會議記錄校稿 | §3 |
| 安裝程式 | 建立／移除第二個 SendTo 捷徑（macOS：第二個 `.app`）；升級補 `privacy` 區塊、保留既有值；安裝摘要一行 | §4 |
| SKILL | 〈0.1 本機限定〉：讀逐字稿**之前**提醒「在對話中讀逐字稿＝送到 Anthropic 雲端」並等使用者明確同意；不跑兩支腳本 | §2.6 |
| 供應商名稱 | 畫面、訊息、README、SKILL 統一為 GPT／Claude（GPT 在前）；設定值、旗標、檔案表頭格式不變 | §5 |
| `common.py` 註解 | `provider: auto` 的註解改成實際行為（已登入的 codex＝GPT 優先） | §5.3 |
| 雲端說明 | README 第 7 行、架構圖節點、SKILL 第 9 行：對話中讀到的逐字稿與截圖會送到 Anthropic 雲端、沒有送出前確認 | §6 |
| 〈會議記錄校稿相容性〉 | 本版沒有改校稿規格 §2.2 的介面與標記格式；校稿 1.1.0 認得本機限定 | §7 |

### 0.2 不做什麼

- 不提供「這次送出」之類的命令列旗標（避免誤用）；解除只能改設定或刪標記檔（使用者自己做）。
- 不在本機限定時「降級」成其他雲端服務、本地模型摘要等（沒有 AI 摘要，改用會議記錄校稿人工校稿）。
- 全域設定不寫標記檔（關掉全域設定＝使用者決定恢復，舊的輸出資料夾跟著恢復）〔規格決定〕。
- 說明網站（Portal）的說明另外更新：設計理念加〈本機限定：機敏會議不上雲〉一節、新增〈本機限定（機敏會議）〉功能頁。
- 不改既有輸出檔的表頭格式（`transcript.corrected.md` 的「校正：自動（<供應商> …）」、會議記錄的「AI 自動整理（…）」與〈轉寫品質備註〉：1.1.0 起凍結，仍寫 `OpenAI`／`Claude`）〔規格決定，§5.2〕。

### 0.3 對照表

| 項目 | 本規格 | 實作 | 測試（`tests/`） |
|---|---|---|---|
| 設定鍵、升級保留 | §2.1、§4.3 | `common.py`：`DEFAULTS["privacy"]`、`V24_BLOCKS`、`upgrade_config()` | `test_v240.Config`；`test_config`、`test_v122` 的補鍵清單 |
| 標記檔、判定、訊息 | §2.2、§2.3 | `common.py`：`LOCAL_ONLY_MARKER`、`LOCAL_ONLY_EXIT`、`write_local_only_marker()`、`local_only_state()`、`local_only_message()` | `MarkerAndState` |
| 拒絕送出 | §2.3 | `auto_correct.py`：`refuse_local_only()`、`run()`、`main()`、`EXIT`；`auto_minutes.py`：`run()`、`main()`；`transcribe.py`：`--local-only`、`main()` | `RefuseCorrect`、`RefuseMinutes`（子行程實跑、假 CLI 計次）、`TranscribeLocalOnly` |
| 本機步驟照常 | §2.4 | 同上 | `EstimateAndRender`、`TranscribeLocalOnly` |
| `run_log` | §2.5 | `runlog.py`：`RunLog.privacy()`、`summarize()` | `RunLogPrivacy`、`TranscribeLocalOnly` |
| SKILL 提醒 | §2.6 | `SKILL.md` §0.1 | `Docs` |
| 入口 | §3 | `mm-sendto.ps1`（`-LocalOnly`）、`mm-dropped.sh`（`--local-only`） | `EntryStatic`；`entry_harness.py` 的 `local_only_*` 三情境 × 3 shell |
| 安裝程式 | §4 | `install.ps1`：`$SendToLnkLocal`、`New-SendToLink`、`Do-Uninstall`、安裝摘要；`install.sh`：`APP_DST_LOCAL`、`make_drop_app()`、`do_uninstall()`、安裝摘要 | `SendToLinks`（pwsh、PS 5.1 實跑）、`DropApps`（Git Bash、假 `osacompile`） |
| 名稱統一 | §5 | 畫面字串（下表）、README、SKILL | `Naming`；舊測試改用 `_testenv.vendor()`；`entry_harness.nm()` |
| 雲端說明 | §6 | README、SKILL | `Docs.test_cloud_wording` |

---

## 1. 版號與檔案

版號 2.4.0：`common.VERSION`、`render_html.FALLBACK_VERSION`（runtime 與 skill 兩份）、`install.ps1` `$Version`、`install.sh` `VERSION`、SKILL.md 版本註解、README「版本 2.4.0」、兩支入口第一行、`THIRD-PARTY-NOTICES.md` 標題。`make_dist.py` 的版號檢查照舊。

| 檔案 | 改了什麼 |
|---|---|
| `payload/runtime/scripts/common.py` | `privacy` 區塊、本機限定函式、`provider: auto` 註解；版號 |
| `payload/runtime/scripts/auto_correct.py`、`auto_minutes.py`、`transcribe.py` | §2.3；畫面名稱（§5） |
| `payload/runtime/scripts/runlog.py` | §2.5 |
| `payload/runtime/scripts/render_html.py`（＋skill 內一份） | 版號（一行） |
| `payload/runtime/mm-sendto.ps1`、`mm-dropped.sh` | §3；§5 |
| `install.ps1`、`install.sh` | §4；§5 |
| `payload/skill/meeting-minutes-pro/SKILL.md`、`references/custom-template-format.md`、`references/corrected-transcript-format.md` | §2.6、§5、§6 |
| `README.md`、`THIRD-PARTY-NOTICES.md` | 〈17. 本機限定（機敏會議）（2.4.0）〉、2.4.0 新功能、輸出檔案、設定鍵、疑難排解、解除安裝、macOS 未實測附錄；名稱；雲端說明 |
| `payload/meeting-minutes-pro-upload.zip` | `make_dist.py --sync-skill` 重產 |

---

## 2. 本機限定

### 2.1 兩種開法

| 開法 | 範圍 | 寫在哪裡 |
|---|---|---|
| 全域 | 這部電腦的每一份 | `config.json` 的 `"privacy": {"local_only": true}`（預設 `false`）。只有 JSON 的 `true` 算數（`"true"`、`1` 都不算）〔規格決定：寧可明確〕 |
| 每份會議 | 這一份 | 輸出資料夾的標記檔 `local-only.json`（§2.2）。只看「存在」：空檔或內容讀不懂也算〔規格決定：寧可多擋〕 |

判定：`common.local_only_state(out_dir, cfg)` → 不是時 `None`；是時 `{"local_only": true, "sources": [...], "source": "config"|"marker"|"config+marker"}`。

### 2.2 標記檔 `local-only.json`〔規格決定〕

- 名稱：`local-only.json`（不用 `.local-only`：macOS Finder 不顯示點開頭的檔，使用者要刪才能解除，看得到比較好）。
- 誰寫：`transcribe.py --local-only`（「會議轉寫（Pro，本機限定）」入口一律加；命令列也能用）。在建立輸出資料夾之後、轉寫之前寫，所以轉寫中途失敗也已標記。已存在時不覆寫。
- 內容（UTF-8 JSON，不含任何逐字稿內容或檔名）：

  ```json
  {"local_only": true, "created_at": "2026-11-08T14:30:22+08:00", "source": "sendto", "version": "2.4.0",
   "note": "本機限定：這份不送 GPT 或 Claude。要解除，刪除這個檔案。"}
  ```

  `source`：環境變數 `MMP_LOCAL_ONLY_SOURCE`（右鍵入口 `sendto`、拖放入口 `dropped`），沒有時 `transcribe`。`created_at` 取系統時間。

### 2.3 拒絕送出

| 程式 | 本機限定時 | exit | stdout 最後一行 |
|---|---|---|---|
| `auto_correct.py` | `run()` 一開始就拒絕：不找 CLI、不讀逐字稿、不寫 `auto_correct.json`、不改 `transcript.json`；只在 `run_log` 記 `privacy` 與 `result`（`reason: local_only`）。`main()` 在解析供應商參數之前就判定（參數矛盾也照樣 6） | **6** | `{"correction": {"status": "skipped", "reason": "local_only", "local_only_source": "...", …}}` |
| `auto_minutes.py`（正式執行，含 `--force`、`--claude`／`--openai`、`--source`、`--context`、`--type`） | 同上（不寫 `auto_minutes.json`、`context.md`） | **6** | `{"minutes": {"status": "skipped", "reason": "local_only", "local_only_source": "...", …}}` |
| `transcribe.py` 管線內校正 | 轉寫照常完成；校正不執行，`correction` 為 `skipped`／`local_only`；步驟數 `[1/4]` | 命令列明確要求（`--correct`／`--claude`／`--openai`）：**6**（轉寫結果照常寫出）；只是 `correction.enabled: true`：0〔規格決定：前者是明確要送卻被擋，要讓呼叫端知道；後者是設定衝突，轉寫本身成功〕 | 多 `"local_only": "<source>"` |

- 固定訊息（stderr，`common.local_only_message()`）：「本機限定（<原因>）：<AI 校正／AI 整理（會議摘要／筆記）>會把內容送到 GPT 或 Claude，已拒絕，沒有送出任何資料。要解除：<把 <config.json 路徑> 的 privacy.local_only 改成 false／刪除 <輸出資料夾>/local-only.json>。」
- `EXIT["local_only"] = 6`（`common.LOCAL_ONLY_EXIT`）；既有 exit code 0／2～5 的意思不變。
- **沒有任何旗標可以略過**（測試 `EntryStatic.test_no_bypass_flag` 檢查沒有 `--no-local-only` 這類旗標；`RefuseCorrect.test_no_flag_bypasses` 以五組旗標＋假的 API 金鑰實跑都 6）。

### 2.4 本機步驟照常

轉寫（含錯誤對照表與詞表替換、分段標點、OpenCC 詞彙回復、說話者分離、截圖、字幕 `transcript.cues.srt`）、`refs.py plan`、`consistency.py`、`render_html.py`、`auto_minutes.py --render-only` 都照常（本機處理）。`auto_minutes.py --estimate-only` 不送內容（只跑 `--version`／`login status`），照常，另在 stderr 印「本機限定：這裡只有預估（沒有送出任何資料）；正式執行會被拒絕」。

### 2.5 `run_log`

- 事件 `{"event": "privacy", "local_only": true, "local_only_source": "config"|"marker"|"config+marker"}`：`transcribe.py`（判定後）、兩支腳本的拒絕時寫。
- `run_summary` 與 `$MMH/logs/runs.jsonl`：**只在本機限定時**多 `local_only: true`、`local_only_source`；不是本機限定時與 2.3.0 相同（`RunLogPrivacy` 比對其他欄位逐一相同）。

### 2.6 SKILL（Claude 對話）

SKILL.md 新增〈0.1 本機限定（機敏會議）（2.4）〉：何時用、兩種開法、會做什麼與不做什麼、怎麼解除，以及：

1. 開始前檢查全域設定與標記檔（附指令）；使用者附上的檔案有 `local-only.json` 或說是機敏會議也照本機限定處理。
2. **讀逐字稿內容之前**先說「這份是本機限定。在這個對話裡讀逐字稿＝逐字稿與截圖會送到 Anthropic 雲端（Claude）。要繼續嗎？…」，**等使用者明確回答要繼續**才讀。
3. 不執行 `auto_correct.py`、`auto_minutes.py`，轉寫不加 `--correct`／`--claude`／`--openai`。
4. Claude App 沙盒：附上的檔案在附上時已送出，看到 `local-only.json` 時提醒並請使用者確認。
5. 不替使用者刪標記檔或改設定。

步驟 2 的結果表與疑難排解各加一列 `local_only`（exit 6）。description 加「機敏會議可用本機限定…」與觸發詞「本機限定、機敏會議」（793 字，上限 1,024）。

---

## 3. 入口

| | Windows `mm-sendto.ps1` | macOS `mm-dropped.sh`〔推論：macOS 未實測〕 |
|---|---|---|
| 本機限定入口 | `param([switch]$LocalOnly, …$Files)`；捷徑 Arguments 結尾 ` -LocalOnly` | 第一個參數 `--local-only`（`.app` 的 AppleScript 加 `& " --local-only"`） |
| 標題與第一行 | 「會議轉寫（Pro，本機限定）」 | 同左 |
| 本機限定的開始條件 | `-LocalOnly` 或全域 `privacy.local_only` → 開頭黃字「本機限定（<原因>）：這次不會把任何資料送到 GPT 或 Claude…」；**不偵測 claude／codex**（不執行任何指令） | 同左 |
| 轉寫 | 本機限定入口加 `--local-only`，設 `MMP_LOCAL_ONLY_SOURCE=sendto`（macOS `dropped`） | 同左 |
| 轉寫後 | 本機限定，或這份的輸出資料夾已有 `local-only.json`（一般入口重轉之前標記過的）→ **不問** AI 校正與整理、不跑 `refs.py plan`；印「本機限定：不做 AI 校正與<整理稱呼>，不會送出任何資料」 | 同左 |
| 結束畫面 | 檔案列多 `local-only.json`；「本機限定：沒有送出任何資料（沒有 AI 校正，也沒有 AI 整理）。」；下一步：用會議記錄校稿人工校稿（附屬工具，另外安裝），經驗匯入讓下次更準；要解除（這一份／全部，只列適用的）；**不提示**在 Claude 中整理 | 同左（下一步寫「拖到會議記錄校稿.app」） |

沒有本機限定時入口行為與 2.3.0 相同，只有供應商名稱字樣不同（§5；`entry_harness.py` 既有 166 個情境在 2.4.0 照跑，舊字串由 `nm()` 換成新說法）。

---

## 4. 安裝程式

### 4.1 Windows（`install.ps1`）

- `$SendToLnkLocal = <SendTo>\會議轉寫（Pro，本機限定）.lnk`。建立改成函式 `New-SendToLink <path> <額外參數> <說明>`，建兩個：一般（與 2.3.0 相同）、本機限定（Arguments 加 ` -LocalOnly`、Description「會議轉寫（Pro，本機限定）：本機轉寫，這份不送 GPT 或 Claude」）。圖示相同。
- `Do-Uninstall` 另移除 `$SendToLnkLocal`。
- 安裝摘要多一行「本機限定：開／關（…）」。

### 4.2 macOS（`install.sh`）〔推論：未實測〕

- `APP_DST_LOCAL = ~/Applications/會議轉寫（Pro，本機限定）.app`；建立改成 `make_drop_app <dst> <名稱> <第一個參數>`，建兩個。`do_uninstall` 另移除它。安裝摘要同 Windows。

### 4.3 升級保留設定

`common.upgrade_config()` 的 `V24_BLOCKS = ("privacy",)`：整塊不存在才寫 `{"local_only": false}`；部分鍵時補缺的鍵；使用者寫的 `true` 一律保留。安裝畫面的「已補上新版設定鍵：…」因此在從 2.3.0 升級時多列 `privacy`（`test_v122` 實跑安裝程式內嵌片段）。

---

## 5. 供應商名稱統一（GPT／Claude）

### 5.1 規則

- 畫面、訊息、README、SKILL：模型家族名 **GPT**、**Claude**；GPT 在前；每份文件第一次寫「GPT（OpenAI）或 Claude（Anthropic）」。「會送到 …」寫 `GPT（OpenAI）`／`Claude（Anthropic）`。
- 照實保留：帳號／金鑰／條款（`OPENAI_API_KEY`、「Anthropic API 金鑰」、「Anthropic 的條款」、ChatGPT 訂閱）、指令名（`codex`、`claude`、Claude Code）、設定值與旗標（`openai`、`--openai`）、SDK 名稱、通道名（`CHANNEL_NAME` 的「OpenAI API」「Anthropic API」）、Claude 對話情境。

### 5.2 程式畫面（新字串）

| 位置 | 2.3.0 | 2.4.0 |
|---|---|---|
| `auto_correct.py` 開始校正的一行 | `自動校正（OpenAI gpt-6.1-sol low，Codex CLI）：…會送到 OpenAI` | `自動校正（GPT gpt-6.1-sol low，Codex CLI）：…會送到 GPT（OpenAI）` |
| `auto_minutes.py` 整理開始、預估 | `會議摘要（OpenAI …）…會送到 OpenAI`、`預估（OpenAI …）` | `會議摘要（GPT …）…會送到 GPT（OpenAI）`、`預估（GPT …）` |
| `auto_correct.py` 選項錯誤、退回說明 | `只有 OpenAI 可用`、`（要用 OpenAI：在終端機執行 codex login）`、`屬於 OpenAI` | `只有 GPT 可用`、`（要用 GPT：…）`、`屬於 GPT` |
| 兩支入口的詢問行 | `AI 校正：OpenAI gpt-6.1-sol（…）：…；逐字稿文字會送到 OpenAI` | `AI 校正：GPT gpt-6.1-sol（…）：…；逐字稿文字會送到 GPT（OpenAI）` |
| 入口選模型 | `[Enter] 預設（OpenAI gpt-6.1-sol）`、`[2] OpenAI gpt-6.1-sol` | `[Enter] 預設（GPT gpt-6.1-sol）`、`[2] GPT gpt-6.1-sol` |
| 入口背景說明題 | `…會一起送到 OpenAI，直接 Enter 跳過` | `…會一起送到 GPT（OpenAI），直接 Enter 跳過` |
| 入口 Codex 未登入 | `這次用 Claude（要用 OpenAI：在終端機執行 codex login）` | `…（要用 GPT：…）` |
| 入口找不到 AI 的提示 | `安裝 Claude Code（…）或 Codex（…）` | `安裝 Codex（…）或 Claude Code（…）` |
| 安裝程式自動校正題 | `用你的 Claude 或 ChatGPT 訂閱`、`將使用：OpenAI（gpt-6.1-sol，透過 Codex）。…會送到 OpenAI`、`會送到 Anthropic`、`要用 OpenAI 請先…` | `用你的 ChatGPT 或 Claude 訂閱`、`將使用：GPT（gpt-6.1-sol，透過 Codex）。…會送到 GPT（OpenAI）`、`會送到 Claude（Anthropic）`、`要用 GPT 請先…` |
| 安裝程式 API 選項（編號不變） | `[1] Anthropic（環境變數 ANTHROPIC_API_KEY）` `[2] OpenAI（…）` | `[1] Claude（Anthropic API 金鑰，環境變數 ANTHROPIC_API_KEY）` `[2] GPT（OpenAI API 金鑰，環境變數 OPENAI_API_KEY）` |
| 安裝摘要 | `自動校正…：開（OpenAI gpt-6.1-sol，…）；…會送到 OpenAI` | `…：開（GPT gpt-6.1-sol，…）；…會送到 GPT（OpenAI）` |
| argparse 說明、docstring | `（Claude 或 OpenAI）` | `（GPT 或 Claude）` |

**檔案表頭不變**〔規格決定〕：`transcript.corrected.md` 表頭「校正：自動（OpenAI gpt-6.1-sol low，Codex CLI，…）」、會議記錄／筆記的「AI 自動整理（…）」與〈轉寫品質備註〉沿用 `PROVIDER_NAME`（`OpenAI`／`Claude`）。理由：1.1.0 起格式凍結（SKILL `references/corrected-transcript-format.md` 已記載），既有檔與新檔維持同一寫法，摘要回歸測試逐位元比對不受影響。畫面另用 `PROVIDER_LABEL`。`references/corrected-transcript-format.md` 加註「GPT 在這裡照舊寫 `OpenAI`」。

### 5.3 `common.py` 註解

第 72 行 `provider` 註解改成「auto＝有已登入的 codex CLI 用 GPT，否則有 claude CLI 用 Claude」；第 98 行「auto 的選法與 correction 相同（已登入的 codex 優先＝GPT）」。

---

## 6. 雲端說明

| 位置 | 2.3.0 | 2.4.0 |
|---|---|---|
| README 第 7 行 | 音檔不上傳。Claude 只會讀到逐字稿和影片截圖。… | 音檔不上傳。在 Claude 對話（Claude Code、Claude 桌面 App）中讀到的逐字稿與影片截圖會送到 Anthropic 雲端處理；對話中讀檔前沒有另外的送出確認。…機敏內容用本機限定：什麼都不送，在 Claude 對話中也會先問你才讀。 |
| README 架構圖節點 `S2` | 已上傳的 meeting-minutes-pro skill（只讀逐字稿） | …（讀到的逐字稿與截圖在 Anthropic 雲端處理；不讀音檔） |
| SKILL 第 9 行 | 音檔不上傳：…，Claude 只讀逐字稿與截圖。… | 音檔不上傳：…。在 Claude 對話（Claude Code、Claude 桌面 App）中讀到的逐字稿與截圖會送到 Anthropic 雲端處理，對話中讀檔前沒有另外的送出確認。…〔2.4〕機敏內容用本機限定 |
| README〈17〉、SKILL〈0.1〉 | — | 同一說法呼應（「讀逐字稿＝逐字稿與截圖會送到 Anthropic 雲端」） |

---

## 7. 會議記錄校稿相容性

> 每一版 Pro 規格固定有這一節（校稿規格 §10.1 P5、§10.3）。

### 7.1 本版（2.4.0）結論

**校稿規格 §2.2 的介面與標記格式沒有改。** 會議記錄校稿 1.0.0 在 Pro 2.4.0 上全部功能可用（不認得本機限定：本機限定的那一份按「用定稿重做」時，Pro 的 `auto_minutes.py` 會拒絕 → 校稿顯示 Pro 的失敗訊息，**不會送出**）；會議記錄校稿 1.1.0 認得本機限定並事先停用重做。

| 校稿規格 §2.2 的介面 | 2.4.0 | 比對方式 |
|---|---|---|
| `consistency.{MARK_RE, key_of, COMMON_WORDS}` | 不變 | `consistency.py` 與 2.2.0 逐位元相同 |
| `corrections.{load, backup, append_rows, HEADER, MIN_LEN}` | 不變 | `corrections.py` 逐位元相同 |
| `subtitles.{map_corrected, recue, render_srt, options}` | 不變 | `subtitles.py` 逐位元相同 |
| `render_html.render` | 不變 | 只有 `FALLBACK_VERSION` 一行不同；`html_template.html` 逐位元相同 |
| `common.{VERSION, data_home, load_config, setting, default_glossary, corrections_path}` | 不變（`VERSION` 值改 2.4.0；只**新增**常數與函式、`DEFAULTS` 只新增 `privacy`） | `test_v230.ProofreadInterface`：介面函式原始碼逐字相同、2.2.0 的 `DEFAULTS` 每個鍵與值都還在 |
| 標記格式 | 不變 | 同上 |
| `auto_minutes.py --source final`／`--estimate-only` 與 stdout 欄位（2.3 規格 §8.2） | 不變；本機限定時正式執行回 `skipped`／`local_only`（exit 6），`--estimate-only` 照常 | `RefuseMinutes`、`EstimateAndRender` |

### 7.2 本版新增、校稿會用到的

| 介面 | 用在校稿的哪裡 |
|---|---|
| 標記檔 `local-only.json`（`common.LOCAL_ONLY_MARKER`） | 校稿 1.1.0 的本機限定判定（自己讀檔，搭 Pro 2.2／2.3 也認得） |
| `config.json` 的 `privacy.local_only` | 同上 |
| `auto_minutes.py` 的 exit 6、`reason: local_only` | 校稿 1.0.0 在本機限定的那一份按重做時的失敗原因（不會送出） |

### 7.3 版本相容表（更新校稿規格 §2.4）

| 會議記錄校稿 | Pro 2.2.x | Pro 2.3.0 | Pro 2.4.0 |
|---|---|---|---|
| 1.0.0 | 可用；重做停用 | 全部可用 | 可用；本機限定的那份按重做會被 Pro 拒絕（不送出） |
| 1.1.0 | 可用；重做停用；認得標記檔與全域鍵 | 可用；本機限定時重做停用 | 全部可用；本機限定時重做停用 |

---

## 8. 文件與發行檔

- SKILL、README：見 §2.6、§5、§6；README 新增〈17. 本機限定（機敏會議）（2.4.0）〉（何時用、兩種開法、會做什麼、不做什麼、改用人工校稿、在 Claude 對話中、怎麼解除）、2.4.0 新功能、輸出檔案表 `local-only.json`、設定鍵 `privacy.local_only`、疑難排解一列、解除安裝、macOS 2.4.0 未實測附錄。
- `make_dist.py --sync-skill` 重產 `payload/meeting-minutes-pro-upload.zip`；`make_dist.py` 產生 `dist/meeting-minutes-pro-v2.4.0-*`（附錄 A.4）。`make_dist.py` 本身不改。

---

## 附錄 A 實測（〔實測〕2026-11-08，Windows 11、Python 3.12.13）

環境：已安裝 runtime 的 venv 唯讀使用（`-B`、`PYTHONDONTWRITEBYTECODE=1`）；測試 home 在系統暫存區；不呼叫任何模型。

### A.1 單元測試

| 版本 | 結果 |
|---|---|
| 2.4.0（不帶 `MMP_TEST_VERSION`） | **Ran 652，OK（skipped 3）**＝2.3.0 時的 616＋`test_v240.py` 36 |
| 2.3.0（`MMP_TEST_VERSION=2.3.0`） | **Ran 652，OK（skipped 39）**：多出的 36 項是 2.4.0 才有的 |

`test_v240.py` 重點：`RefuseCorrect`／`RefuseMinutes` 子行程實跑，本機限定時假的 `claude.cmd`／`codex.cmd` 記錄檔 0 行（對照組：不是本機限定時同一組假 CLI 有被呼叫）；五組繞過旗標＋假的 `OPENAI_API_KEY`／`ANTHROPIC_API_KEY` 全部 exit 6。Pro 的版本目錄沒有留下 `__pycache__`。

### A.2 入口 harness

`entry_harness.py`（假 runtime＋假 CLI，不呼叫模型）：
- 2.4.0：**171/171**（pwsh 57、Windows PowerShell 5.1 57、Git Bash 57），含新情境 `local_only_entry`、`local_only_global`、`local_only_marker_existing` 三種 shell 都 PASS；舊情境的畫面字串在 2.4.0 由 `nm()` 換成新名稱（只有名稱不同，題目、呼叫參數、檔案列都與 2.3.0 相同）。
- 對照組 2.3.0（`MMP_TEST_VERSION=2.3.0`）：**162/162**（每個 shell 54），harness 的改動不影響舊版。

### A.3 發行檔

`make_dist.py`：版號一致、權重 0、H-13、參考資料檢查都過。

| 檔案 | 內容 | 大小 | SHA-256 |
|---|---|---|---|
| `meeting-minutes-pro-v2.4.0-installer.zip` | 51 檔 | 482,623 bytes | `daf145ecbe6efdd5376276a22218165bf24e1bbb7695ba03cc677d113ef036e9` |
| `meeting-minutes-pro-v2.4.0-claude-app-upload.zip` | 7 項 | 59,526 bytes | `8729c43cf8cb063017f11ede55f5305e158eefe055298cad6adbe942036b5921` |

兩個 zip 解開（連同校稿安裝包）跑 `deid-scan.mjs --internal-ids`＋私有詞表：81 檔命中 0；家目錄／信箱 grep 0。

### A.4 實機驗證（發版時，合成素材）

在一台 Windows 11（NVIDIA RTX 5060 Ti，ct2／cuda／int8_float16）上把已安裝的 2.3.0 升級到 2.4.0，以合成素材驗證：

| 項目 | 結果 |
|---|---|
| 升級 | Windows PowerShell 5.1 執行 `install.ps1 -Target Both -Backend ct2:cuda -NoBreeze -NoCorrect`：exit 0；`config.json` 只改 `runtime_version` 並補 `privacy.local_only: false`（畫面「已補上新版設定鍵：privacy（既有的值不變）」）；GPU、精度、詞表、對照表、`proofread/` 都不變；SendTo 多一個「會議轉寫（Pro，本機限定）」（Arguments 結尾 ` -LocalOnly`） |
| 本機限定入口（每份會議） | 「會議轉寫（Pro，本機限定）」捷徑的同一命令轉寫合成會議 M1（9 分 39 秒）：不問 AI 校正與整理；結束畫面「本機限定：沒有送出任何資料…」；輸出資料夾有 `local-only.json`（`source: sendto`）；`run_log` 有 `privacy` 事件 |
| 拒絕送出 | 對該輸出資料夾執行 `auto_correct.py`、`auto_correct.py --openai --force`、`auto_minutes.py`、`auto_minutes.py --claude --force --source original`：4 次都 exit 6、`reason: local_only`、訊息寫原因與解除方法 |
| 全域設定 | `privacy.local_only: true` 時一般入口「會議轉寫（Pro）」也不問 AI、開頭寫「本機限定（config.json 的 privacy.local_only）」、不寫標記檔；兩支腳本 exit 6。測完改回 `false`（`config.json` 與測試前逐位元相同） |
| 沒有送出 | 本機限定的整段測試期間（含會議記錄校稿）以行程監看每約 0.3 秒輪詢一次：新的 `codex`／`claude` 行程 **0**；三個輸出資料夾的 `run_log.jsonl` 都沒有 `call` 事件 |
| 一般流程（對照） | 一般入口、不是本機限定：畫面「會議摘要：GPT gpt-6.1-sol（依 transcript.md 整理）：…；逐字稿文字會送到 GPT（OpenAI）」「[Enter] 預設（GPT gpt-6.1-sol）」；會議摘要照常完成（`codex exec` 2 次：整理 1、待釐清補判 1；行程監看同樣抓到 2 個 `codex`）；檔案表頭照舊寫「自動整理：OpenAI gpt-6.1-sol low，Codex CLI，…」（§5.2） |
| 會議記錄校稿 1.1.0 | 本機限定的那一份：頁首「本機限定」標示、首頁清單標示、「用定稿重做會議記錄」停用並寫原因，直接呼叫重做 API（`dry_run`）回 409 `local_only`；人工修改 2 處後定稿成功（43 段、字幕 135 條，對應失敗 0 段） |

macOS 的第二個 `.app` 沒有在 Mac 實機驗證（見 README 附錄）。
