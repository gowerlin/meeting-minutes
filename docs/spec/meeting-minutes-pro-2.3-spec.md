# meeting-minutes-pro 2.3 規格（公開版）：配合會議記錄校稿（定稿逐字稿、費用預估、移除連動）

> **公開版**：本檔是 meeting-minutes-pro **2.3.0** 規格的公開版，適用 2.3.x。內容是 **2.3.0 相對 2.2.0 的差異**；本檔沒有提到的行為一律照 2.2 規格
> （公開版 [`meeting-minutes-pro-2.2-spec.md`](meeting-minutes-pro-2.2-spec.md)；下稱「2.2 規格」）與 2.2.0 的程式。
> 來源：會議記錄校稿 1.0 規格（公開版 [`meeting-minutes-proofread-1.0-spec.md`](meeting-minutes-proofread-1.0-spec.md)；下稱「校稿規格」）§10.1 的 P1～P5，另併入兩個小修（測試預設版號、入口 `--hotwords` 引號）。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 2.3.0 §x.y」就是本檔的同一節。
> 版本目錄 `V/`＝`pro/meeting-minutes-pro-v2.3.0/`（公開 repo 的路徑）。
> 標示：**〔實測〕**＝實作時以合成素材實測的結果（附錄 A）；**〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節（附理由）。
> 「`$MMH`」＝`MEETING_MINUTES_PRO_HOME`；「輸出資料夾」＝`<檔名>_minutes/`；「定稿」＝會議記錄校稿產生的 `transcript.final.md`。

---

## 0. 摘要

### 0.1 2.3.0 做什麼

| 功能 | 一句話 | 章節 |
|---|---|---|
| `auto_minutes.py --source final` | 讀定稿 `transcript.final.md`；`--source auto` 的順序改成 final ＞ corrected ＞ original；表頭與〈轉寫品質備註〉寫「`transcript.final.md`（已人工校稿）」；沒有定稿時與 2.2.0 逐位元相同 | §2 |
| `auto_minutes.py --estimate-only` | 不呼叫模型、不寫任何檔，stdout 最後一行印 `{"estimate": {"provider", "model", "usd_low", "usd_high", "chars", …}}` | §3 |
| 完成時的實際費用 | 正式執行完成時 stdout 的 `minutes` 加 `cost_usd`、`cost_basis`（本次 run_log 的 API 等價費用合計；沒有資訊時省略） | §3.5 |
| 解除安裝連動 | Pro 解除安裝時，`$MMH/proofread/uninstall.ps1`（`.sh`）存在就先以安靜模式執行，再處理 Pro 自己的檔案 | §4 |
| 安裝時保留 `$MMH/proofread/` | 現行行為（只刪 `scripts/`）寫進安裝程式註解與測試 | §5 |
| 入口 `--hotwords` 引號修正 | Windows PowerShell 5.1 的「本次專有名詞」含 `"` 或結尾 `\` 時改用 `Native-Arg`（2.2.0 已用在 `--context`） | §6 |
| 測試預設版號 | `tests/_testenv.py` 不帶 `MMP_TEST_VERSION` 時取最新的版本目錄（公開 repo 只有最新版也能直接跑） | §7 |
| 〈會議記錄校稿相容性〉 | 固定一節：本版是否動到校稿規格 §2.2 的介面或標記格式（本版：沒有） | §8 |

### 0.2 不做什麼

- 不在 Pro 裡加校稿功能、不在轉寫結束畫面提示校稿（校稿規格 §10.2、§14）；Pro 不依賴校稿是否安裝（校稿規格 §10.3 第 2 點）。
- 不改標記格式、`consistency.MARK_RE`、`key_of`、`subtitles.*`、`corrections.*`、`render_html.render`、`common.*` 的介面（§8）。
- 不新增設定鍵（`config.json` 不變）；入口題目不變。
- 不實作校稿工具自己的移除程式（`uninstall.ps1 -Quiet` 等由校稿工具實作，§4.3 是給它的介面）。

### 0.3 校稿規格 §10.1 與併入項目對照

| 項目 | 本規格 | 實作 | 測試（`tests/`） |
|---|---|---|---|
| P1 `--source final` | §2 | `auto_minutes.py`：`pick_source()`、`is_marked()`、`src_label()`、`made_by()`、`final_line()`、`_run()`、`render_only()`、`main()` | `test_v230.py`：`PickSource`、`FinalRun`、`RegressionV22` |
| P2 `--estimate-only` | §3 | `auto_minutes.py`：`USD_MODEL*`、`estimate_usd()`、`estimate()`、`main()` | `EstimateMath`、`EstimateRun`、`EstimateCli` |
| P3 移除連動 | §4 | `install.ps1` `Uninstall-Proofread`、`install.sh` `uninstall_proofread()` | `UninstallProofreadPs1`（pwsh、PS 5.1 實跑）、`UninstallProofreadSh`（Git Bash） |
| P4 保留 `proofread/` | §5 | 兩支安裝程式的註解 | `KeepProofreadOnInstall`（靜態＋把那幾行拿出來實跑） |
| P5 相容性一節 | §8 | 本檔 | `ProofreadInterface` |
| P6 完成時的實際費用（實作時追加） | §3.5 | `auto_minutes.py`：`_log_offset()`、`run_cost()`、`run()`、`main()` | `RunCost` |
| 測試預設版號 | §7 | `tests/_testenv.py` `latest_version()` | `TestEnvLatest` |
| 入口 `--hotwords` | §6 | `mm-sendto.ps1` | `EntryHotwords`（靜態）；`entry_harness.py` 情境 `hotwords_special_chars`、`hotwords_plain` |

---

## 1. 版號與檔案

版號 2.3.0：`common.VERSION`、`render_html.FALLBACK_VERSION`（runtime 與 skill 兩份）、`install.ps1` `$Version`、`install.sh` `VERSION`、SKILL.md 版本註解、README「版本 2.3.0」、兩支入口第一行、`THIRD-PARTY-NOTICES.md` 標題。`make_dist.py` 的版號檢查照舊（六處一致）。

| 檔案 | 改了什麼 |
|---|---|
| `payload/runtime/scripts/auto_minutes.py` | §2、§3 |
| `install.ps1`、`install.sh` | §4、§5；版號 |
| `payload/runtime/mm-sendto.ps1` | §6；版號 |
| `payload/runtime/mm-dropped.sh` | 版號（`--hotwords` 本來就用陣列原樣傳） |
| `payload/runtime/scripts/common.py`、`render_html.py` | 版號（各只改一行，§8） |
| `payload/skill/meeting-minutes-pro/SKILL.md`、`references/corrected-transcript-format.md`、`references/minutes-template.md` | 第 13 件事（定稿逐字稿）、步驟 0 的表、2.1 的來源順序與 `--estimate-only`、新的 3(c)、步驟 6、疑難排解；定稿格式；備註一行 |
| `README.md`、`THIRD-PARTY-NOTICES.md` | 2.3.0 新功能、§16〈定稿逐字稿與會議記錄校稿〉、輸出檔案表、解除安裝、疑難排解、發行檔名、macOS 未實測附錄 |
| `payload/meeting-minutes-pro-upload.zip` | `make_dist.py --sync-skill` 重產 |

---

## 2. 定稿逐字稿：`--source final`（P1）

### 2.1 選哪一份逐字稿

`--source` 的值：`auto`（預設）、`final`（新）、`corrected`、`original`。

| `--source` | 讀哪一份 |
|---|---|
| `final` | `transcript.final.md`；不存在 → `failed`、`reason: no_transcript`、訊息「找不到 transcript.final.md（定稿逐字稿）；請先用會議記錄校稿定稿，或改用 --source auto。」（exit 5）。**不退回**其他檔 |
| `auto` | 有定稿 → 定稿；否則與 2.2.0 相同（有 `transcript.corrected.md` 用它，否則 `transcript.md`） |
| `corrected`、`original` | 與 2.2.0 相同（不看定稿） |

**〔規格決定〕`auto` 不用過時的定稿**：定稿的修改時間比「2.2.0 會選的那份」（校正版，沒有就原稿）舊時，`auto` 不用定稿，改用那一份，console 印一行：
「transcript.final.md 比 transcript.corrected.md 舊（之後重新轉寫或校正過），這次改用 transcript.corrected.md；要用定稿請加 --source final」。
理由：右鍵入口對同一個媒體再轉寫一次時，`transcript.md` 被覆寫、校正版被重產，舊定稿卻留在資料夾裡；它對的是舊稿（時間碼、講者代號可能不同），默默拿來整理會讓會議記錄與目前的逐字稿對不上。
明確給 `--source final` 時照用定稿。校稿工具「重做會議記錄」一律給 `--source final`（校稿規格 §7.5），不受這條影響。

### 2.2 讀法

- `parse_paragraphs(text, corrected=True)`（校稿規格 §7.1）：只讀第一個 `---` 之後的本文；表頭、〈講者對應〉表不送；`>` 開頭的行（畫面行、註記）照 2.2.0 不送。定稿沒有標記，`resolve_marks()` 不會改任何字。
- 送出的內容、提示詞、分段、參考資料、用字統一、網頁版：與讀校正版時完全相同（只有逐字稿文字不同）。
- `--render-only`（非會議類型）：`notes.json` 的 `render.src` 是 `transcript.final.md` 時，同樣用 `corrected=True` 讀（用字統一的計數用）。

### 2.3 表頭與〈轉寫品質備註〉

讀定稿時（其他情況與 2.2.0 逐位元相同）：

| 位置 | 會議記錄 `meeting-minutes.md` | 筆記 `notes.md` |
|---|---|---|
| 表頭第二行 | `> 自動整理：…｜依據：`` `transcript.final.md` ``（已人工校稿）｜一次整理｜**未經人工確認**…` | 同左 |
| 資訊表 | 〈記錄來源〉`…本機 ASR（…）自動轉寫 + 人工校稿 + AI 自動整理` | 〈來源〉同左 |
| 〈轉寫品質備註〉 | 「校正版逐字稿：…」之後加一行「定稿逐字稿：`transcript.final.md`（已人工校稿），會議記錄校稿產生」；「會議記錄：自動整理（…），依據 `transcript.final.md`（已人工校稿），…」 | 同左；最後一行「〈類型〉筆記：自動整理（…），依據 `transcript.final.md`（已人工校稿）；…」 |
| console | `會議摘要（…）：依據 transcript.final.md（已人工校稿），約 N 字、…` | 同左 |

- 「未經人工確認」照寫：人工校的是逐字稿，會議記錄仍是 AI 整理。
- `auto_minutes.json`、`transcript.json` 的 `meta.minutes`、stdout 的 `minutes.source_file` 寫 `transcript.final.md`（欄位不變）。
- 網頁版由 `.md` 轉出，所以同樣顯示「已人工校稿」〔實測：`FinalRun.test_auto_uses_final_and_html`〕。

### 2.4 誰會用到

- 校稿工具「重做會議記錄（要花費）」：`auto_minutes.py <輸出資料夾> --source final --force`（校稿規格 §7.5）。
- 使用者校完稿後從右鍵重轉、或自己執行 `auto_minutes.py --force`：`auto` 會選定稿（§2.1）。入口的題目與詢問行不變（詢問行仍寫「依校正版逐字稿整理」；只影響摘要讀哪一份，〔規格決定〕不為此改入口，避免入口依賴校稿）。

---

## 3. 費用預估：`--estimate-only`（P2）

### 3.1 行為

- **不呼叫模型、不寫任何檔**：不寫 `run_log.jsonl`、`$MMH/logs/runs.jsonl`、`auto_minutes.json`，不改 `transcript.json`，`--context` 也不寫 `context.md`（已有的說明檔與 `context.md` 照讀）。
- 供應商與模型的選法同正式執行（`resolve_request()`、`select_backend()`；CLI 通道會執行 `claude --version`／`codex --version`／`codex login status`，不送任何內容）。
- 已有 `meeting-minutes.md`／`notes.md` 不影響（預估是給「重做」用的，不必加 `--force`）。
- 可與 `--source`、`--type`、`--template`、`--minutes-*`、`--claude`／`--openai`、`--refs`、`--no-refs`、`--no-context` 一起用；與 `--render-only` 互斥（exit 2）。

### 3.2 怎麼算〔規格決定〕

結構同 2.2 已有的時間預估（`estimate_sec()`，1.2.0 規格 §12.6）：

```
每段費用 ＝ 基本 ＋ 每千字 × 該段送出字數 ÷ 1000；分段時另加彙整 1 次
送出字數 ＝ 該段逐字稿內容字數 ＋ 前後文（分段時）＋ 參考資料段落（〈背景說明〉〈參考資料用字〉…）＋ 範本說明
```

係數（API 等價美元；下限、上限）由 1.2.0 附錄 F.3 的實測（M1 9.65 分鐘單段約 2.4 千字；M3 79.3 分鐘、18,288 字分 2 段＋彙整）定。F.3 早於 2.0.0 的待釐清補判（整理後最多再呼叫 1 次），所以「基本」的**上限**另含補判 1 次（〔實測〕附錄 A.2：sol 補判 US$0.015；2.2.0 實測 opus 補判 US$0.037），下限不含（附近都有待釐清問題時不呼叫）：

| 模型 | 基本 | 每千字 | 彙整 | M1 實測 → 預估 | M3 實測 → 預估 |
|---|---|---|---|---|---|
| `gpt-6.1-sol`（`low`） | 0.025～0.05 | 0.010～0.013 | 0.05～0.07 | 0.053 → 0.049～0.081 | 0.291～0.357 → 0.283～0.408 |
| `opus`（`medium`） | 0.08～0.17 | 0.035～0.045 | 0.15～0.25 | 0.190 → 0.164～0.278 | 1.110～1.216 → 0.950～1.413 |
| `sonnet`（`medium`） | 0.025～0.05 | 0.013～0.016 | 0.08～0.12 | 0.060 → 0.056～0.088 | 0.463 → 0.368～0.513 |

- 實測都落在預估範圍內（`EstimateMath.test_f3_measurements_inside_range`；另含有補判的兩筆：〔實測〕sol 427 字 US$0.0455、2.2.0 opus 約 2.5 千字＋參考資料 US$0.258）。
- **沒有實測的模型**：價格表（`pricing.json`，含 `$MMH/pricing.json` 覆寫）有這個模型 → 以同一家的參考模型（Claude `sonnet`、OpenAI `gpt-6.1-sol`）依「輸入＋輸出」單價等比例換算（`basis: scaled`；例 `haiku` × 0.05、`gpt-6-astra` × 5）；價格表也沒有 → 同一家最寬的範圍（`basis: fallback`）。
- effort 不同（例 opus `high`）時 token 會變多，係數沒有區分〔推論：預估偏低〕；預估只是確認框用的區間，實際費用以執行 log 為準。
- 時間（`sec_low`、`sec_high`）用 2.2 的 `estimate_sec()`。

### 3.3 輸出

stdout 最後一行（stderr 第一行照舊是版號，之後一行人看的說明「預估（…）：依據 …，送出約 N 字、M 段，API 等價約 US$a～b、約 x 分鐘（沒有呼叫模型）」）：

```json
{"estimate": {"provider": "openai", "model": "gpt-6.1-sol", "usd_low": 0.049, "usd_high": 0.081, "chars": 2400,
              "effort": "low", "channel": "cli", "basis": "measured", "cost_basis": "subscription_equivalent",
              "parts": 1, "sec_low": 62, "sec_high": 84, "source_file": "transcript.final.md", "content_type": "meeting"}}
```

| 欄位 | 內容 |
|---|---|
| `provider`、`model`、`effort`、`channel` | 這次會用的供應商、模型、effort、通道（同正式執行） |
| `usd_low`、`usd_high` | API 等價美元（小數 3 位） |
| `chars` | 送出的總字數（§3.2，各段相加；分段時前後文重複計） |
| `basis` | `measured`／`scaled`／`fallback`（§3.2） |
| `cost_basis` | `subscription_equivalent`（CLI 訂閱：不另計費，但會用掉額度）／`api`（API 通道或 Codex 以 API 金鑰登入） |
| `parts`、`sec_low`、`sec_high` | 段數與預估秒數 |
| `source_file`、`content_type` | 會讀的逐字稿（§2.1）與內容類型 |

前五個欄位（`provider`、`model`、`usd_low`、`usd_high`、`chars`）是校稿規格 §10.1 P2 要求的；其他欄位只新增、校稿工具不依賴。

### 3.4 失敗

stdout 最後一行 `{"estimate": null, "status": "<skipped|failed>", "reason": "<代碼>"}`，訊息印在 stderr（`[!] …`）。exit code 同正式執行的對應（`auto_correct.exit_code()`）：找不到逐字稿／定稿 `no_transcript` → 5；找不到 CLI、沒有金鑰、參數錯誤、逐字稿沒有段落 → 2；Codex 沒登入 `auth_failed` → 3。

### 3.5 完成時的實際費用（P6，實作時追加）

- `auto_minutes.py` 正式執行完成時，stdout 最後一行的 `minutes` 加 `cost_usd`（本次 `run()` 寫進 `run_log.jsonl` 的 `call` 事件（同一個 `run_id`、本次開始之後新增的）的 `cost_usd` 合計，小數 6 位）與 `cost_basis`（各呼叫相同時照寫 `subscription_equivalent`／`api`，不同時 `mixed`）。與 `--estimate-only` 的 `usd_low`／`usd_high` 同單位（API 等價美元）。
- 沒有呼叫（例 `exists` 跳過、找不到 CLI）、或任何一次呼叫算不出費用（價格表沒有這個模型，`cost_usd: null`）→ **兩個欄位都不加**（不寫 0，避免把「不知道」顯示成「免費」）。
- `run()` 的回傳值同樣多這兩個鍵（`transcribe.py` 串接時不使用）；`auto_minutes.json`、`--render-only`、`--estimate-only` 的輸出不變。
- 用途：校稿工具「重做會議記錄」的結果畫面讀 `minutes.cost_usd` 顯示實際費用（校稿規格 §7.5）。
- 測試：`test_v230.RunCost`（結果與 stdout 的值＝`run_log` 的 `call` 合計；`--force` 第二次只算該次；未知模型與沒有呼叫時不加鍵）。

---

## 4. 解除安裝連動（P3）

### 4.1 Windows（`install.ps1 -Uninstall`，`Do-Uninstall` 第一步）

```powershell
$u = Join-Path $MMH "proofread\uninstall.ps1"
# 存在才做：
& <目前的 powershell.exe／pwsh.exe> -NoProfile -ExecutionPolicy Bypass -File $u -Quiet [-TestRoot <TestRoot>]
```

- 用目前執行安裝程式的同一個 PowerShell（`(Get-Process -Id $PID).Path`），另開行程（校稿的 `$ErrorActionPreference`、`exit` 不影響 Pro）。
- 環境變數 `MEETING_MINUTES_PRO_HOME` 已是 `$MMH`（安裝程式開頭就設定），子行程繼承。
- exit 0 → 「[OK] 已移除會議記錄校稿」；其他 → 「[!] 會議記錄校稿的移除程式回報錯誤（exit N）；之後可手動執行 <路徑>」，**繼續** Pro 的解除安裝。
- 之後才移除 Pro 的 skill、右鍵捷徑、上傳 zip，並問要不要刪除 runtime（與 2.2.0 相同）。

### 4.2 macOS（`install.sh --uninstall`，`do_uninstall` 第一步）

`bash "$MMH/proofread/uninstall.sh" --quiet [--test-root "$TEST_ROOT"]`，存在才做；結果處理同 §4.1。〔推論〕macOS 實機未測（只在 Windows 的 Git Bash 以假的移除程式實測；README 附錄寫了實機確認步驟）。

### 4.3 給會議記錄校稿移除程式的介面〔規格決定〕

校稿工具實作 `uninstall.ps1`／`uninstall.sh` 時要支援：

| 參數 | 意思 |
|---|---|
| `-Quiet`／`--quiet` | 不詢問、不等待按鍵：校稿規格 §2.5 的「要刪除最近的稿清單嗎？[y/N]」照預設 N（保留 `state/`）；其他照一般移除（停服務、刪 `app/`、`version.json`、`config.json`、`uninstall.*`、右鍵捷徑、`.mmproof` 關聯或 `.app`） |
| `-TestRoot <資料夾>`／`--test-root <資料夾>` | 與校稿安裝程式的測試模式相同（右鍵捷徑、登錄機碼等換到測試位置） |
| exit code | 0＝完成；其他＝有錯（Pro 只提示、不中止） |

保留 `state/` 的理由：Pro 接著會問要不要刪除整個 runtime；使用者選刪除時 `state/` 一起刪，選保留時最近清單也不會無聲消失。

### 4.4 沒裝校稿時

`$MMH/proofread/uninstall.*` 不存在 → 什麼都不做、不印任何字（〔實測〕`test_without_proofread_does_nothing`：輸出不含「會議記錄校稿」）。

---

## 5. 安裝時保留 `$MMH/proofread/`（P4）

- 現行行為：安裝程式只刪除並重建 `$MMH/scripts/`（`install.ps1` 的 `Remove-Item $scriptsDst`、`install.sh` 的 `rm -rf "$MMH/scripts"`），`$MMH` 底下其他資料夾（`proofread/`、`templates/`、模型、venv）都不動。
- 2.3.0 在這兩處加註解「不要改成清空 `$MMH`」，並加測試：① 安裝流程（解除安裝以外）沒有刪除 `$MMH` 本身的指令；② 把那幾行拿出來，對含 `proofread/app/`、`proofread/state/` 的暫存 `$MMH` 實跑（pwsh、PS 5.1、Git Bash），`proofread/` 原樣保留、`scripts/` 被換新。

---

## 6. 入口 `--hotwords` 引號修正

- 問題：Windows PowerShell 5.1（以及 PowerShell 7.2 以前的 Legacy 傳參數）把陣列參數傳給原生程式時，不跳脫雙引號與結尾的反斜線，「本次專有名詞」含 `"` 或以 `\` 結尾時，`transcribe.py` 收到的 `--hotwords` 會被弄壞〔實測：2.2.0 對照組，PS 5.1 收到 `Kafka, 含 引號 … 結尾"`〕。
- 修正：`mm-sendto.ps1` 改成 `$argList += @("--hotwords", (Native-Arg $hot))`（`Native-Arg` 是 2.2.0 為 `--context` 加的，依 Windows 命令列規則先跳脫；PowerShell 7.3 起的 Windows 模式原樣傳）。
- `mm-dropped.sh` 用 bash 陣列傳參數，本來就原樣，不改。

---

## 7. 測試預設版號

- `tests/_testenv.py`：`MMP_TEST_VERSION` 沒設定（或空字串）時，`VERSION = latest_version()`：`tests/` 的上一層（公開 repo 是 `pro/`）底下名稱是 `meeting-minutes-pro-v<X.Y.Z>` 的**資料夾**中，依數字比較最大的（`2.10.0` ＞ `2.9.0`；帶後綴、非數字、檔案都不算）；一個都沒有 → `RuntimeError`（訊息請用 `MMP_TEST_VERSION` 指定）。
- 公開 repo 只匯出最新版目錄，所以不帶 `MMP_TEST_VERSION` 就能跑；需要舊版目錄的比對測試（`RegressionV21`、`RegressionV22`、`ProofreadInterface.test_files_unchanged_from_220` 等）在沒有舊版目錄時略過（照既有做法）。
- `tests/README.md` 對齊（預設版號、2.3.0 的測試檔、入口情境）。

---

## 8. 會議記錄校稿相容性

> 之後每一版 Pro 規格都固定有這一節（校稿規格 §10.1 P5、§10.3）：寫明本版是否動到校稿規格 §2.2 列的介面或標記格式，以及會議記錄校稿哪個版本可以用。

### 8.1 本版（2.3.0）結論

**沒有動到。** 會議記錄校稿 1.0.0（最低需求 Pro 2.2.0）在 Pro 2.3.0 上全部功能可用，且「用定稿重做會議記錄」（需要 Pro ≥ 2.3.0，校稿規格 §2.4、§7.5）從本版開始可用。

| 校稿規格 §2.2 的介面 | 2.3.0 | 比對方式 |
|---|---|---|
| `consistency.{MARK_RE, key_of, COMMON_WORDS}`；`MARK_RE.pattern` 逐字相同 | 不變 | `consistency.py` 與 2.2.0 逐位元相同 |
| `corrections.{load, backup, append_rows, HEADER, MIN_LEN}` | 不變 | `corrections.py` 逐位元相同 |
| `subtitles.{map_corrected, recue, render_srt, options}` | 不變 | `subtitles.py` 逐位元相同 |
| `render_html.render` | 不變 | `render_html.py`（runtime 與 skill）只有 `FALLBACK_VERSION` 一行不同；`html_template.html` 逐位元相同 |
| `common.{VERSION, data_home, load_config, setting, default_glossary, corrections_path}` | 不變（`VERSION` 值改 2.3.0） | `common.py` 只有 `VERSION = …` 一行不同 |
| 標記格式（`{原文→修正}`、`{原文→}`、`{→補字}`、`[?原文｜推測]`、`{原文→統一}`） | 不變 | 由上面 `MARK_RE` 與 `consistency.py` 相同保證 |

- 自動檢查：`tests/test_v230.py` 的 `ProofreadInterface`（名稱都在；有 2.2.0 目錄時逐檔比對）。
- 會議記錄校稿：撰寫校稿規格時的試作程式（不公開）對本版 `scripts/` 的相容測試通過（附錄 A.3）；會議記錄校稿 1.0.0 的測試（公開 repo 的 `proofread/tests/`）也對本版通過。

### 8.2 本版新增、校稿會用到的

| 介面 | 用在校稿的哪裡 |
|---|---|
| `auto_minutes.py --source final` | 「重做會議記錄」（校稿規格 §7.5） |
| `auto_minutes.py --estimate-only` 的 `estimate.{provider, model, usd_low, usd_high, chars}` | 重做前的確認框（校稿規格 §7.5） |
| 正式執行 stdout 的 `minutes.cost_usd`、`minutes.cost_basis`（§3.5） | 重做完成的結果畫面（校稿規格 §7.5） |
| 解除安裝時呼叫 `$MMH/proofread/uninstall.{ps1,sh}` 的 `-Quiet`／`--quiet`、`-TestRoot`／`--test-root` | 校稿工具的移除程式要支援（§4.3） |

### 8.3 版本相容表（更新校稿規格 §2.4）

| 會議記錄校稿 | Pro 2.2.x | Pro 2.3.0 |
|---|---|---|
| 1.0.0 | 可用；「用定稿重做會議記錄」停用 | 全部可用 |

---

## 9. 文件與發行檔

- SKILL.md：第 13 件事「定稿逐字稿（2.3）」；步驟 0 的表加 `transcript.final.md`；2.1 的來源順序與 `--estimate-only`；新的 3(c)「已有定稿逐字稿：不再校正」；步驟 6 的校稿工具說明（附屬工具、另外安裝）；疑難排解一列。description 加「定稿逐字稿」（746 字，Claude App 上限 1,024）。
- `references/corrected-transcript-format.md` 加〈定稿逐字稿〉一節；`references/minutes-template.md` 的備註加定稿一行。
- README：版號、2.3.0 新功能、§16〈定稿逐字稿與會議記錄校稿〉、§7 的來源與單獨執行、輸出檔案表、解除安裝、疑難排解、發行檔名、macOS 未實測附錄、開發者測試表。
- `make_dist.py --sync-skill` 重產 `payload/meeting-minutes-pro-upload.zip`；`make_dist.py` 產生 `dist/meeting-minutes-pro-v2.3.0-installer.zip`、`dist/meeting-minutes-pro-v2.3.0-claude-app-upload.zip`（附錄 A.4）。`make_dist.py` 本身不改。

---

## 附錄 A 實測（〔實測〕2026-11-08，Windows 11、Python 3.12.13）

環境：已安裝 runtime 的 venv 唯讀使用（`-B`、`PYTHONDONTWRITEBYTECODE=1`）；`pypdf` 只裝在暫存區（`PYTHONPATH`）；測試 home 都在暫存區。

### A.1 單元測試

| 版本 | 結果 |
|---|---|
| 2.3.0（不帶 `MMP_TEST_VERSION`，`_testenv` 自動取 2.3.0） | **Ran 616，OK（skipped 5）**＝2.2.0 時的 572＋`test_v230.py` 44 |
| 2.2.0（`MMP_TEST_VERSION=2.2.0`） | **Ran 616，OK（skipped 47）**：多出的 42 項是 2.3.0 才有的（`TestEnvLatest` 2 項兩版都跑） |

### A.2 端到端（合成素材，`codex exec` 2 次）

- 素材：撰寫校稿規格時做的合成會議逐字稿 D1（會議，2 分 12 秒，12 段，14 處標記；不公開。公開 repo 的 `proofread/tests/materials.py` 產生的 D1 是同一份逐字稿，只差校正版表頭的兩行說明）複製到暫存區；以暫存區的小程式模擬校稿：校正與統一照建議、待確認接受推測、另做 2 處人工修改（「密等→冪等」「指數退幣→指數退避」），寫出校稿規格 §7.1 格式的 `transcript.final.md`。
- 呼叫上限：driver 包住 `auto_minutes.main()`（真的命令列流程），每次呼叫前在預算檔記一筆、達上限就拒絕。

| 步驟 | 結果 |
|---|---|
| `--source final --estimate-only`（上限 0） | exit 0；`{"estimate": {"provider": "openai", "model": "gpt-6.1-sol", "usd_low": 0.029, "usd_high": 0.041→（調整後）0.056, "chars": 427, …, "source_file": "transcript.final.md"}}`；呼叫 0 次、輸出資料夾檔案不變、沒有 `run_log.jsonl` |
| `--source final --force --openai`（上限 2） | `ok`，35.7 秒；呼叫 2 次：`minutes.part` 32.1 s（input 8,185／output 1,419，US$0.0306）、`minutes.recheck` 3.4 s（7,400／15，US$0.0150），合計 **US$0.0455** |
| 表頭與備註 | `依據：`` `transcript.final.md` ``（已人工校稿）`、`自動轉寫 + 人工校稿 + AI 自動整理`、「定稿逐字稿：…，會議記錄校稿產生」、「會議記錄：…依據 `transcript.final.md`（已人工校稿）」 |
| 內容 | 摘要與議題用了人工修改後的「冪等」「指數退避」；〈與會者〉王小明（S1）、李小華（S2）、陳大同（S3） |
| 網頁版 | `meeting-minutes.html`（`media: found`，時間碼可點播放）；頁面含「transcript.final.md」與「已人工校稿」 |
| 實跑後再預估（上限 0） | US$0.029～0.056 涵蓋實際 0.0455；`run_log.jsonl` 的 `call` 事件 2→2、行數 9→9、輸出資料夾檔案的 SHA-256 不變 |

- 第一次預估的上限 0.041 低於實際 0.0455：§3.2 的係數取自 1.2.0 實測，那時還沒有 2.0.0 的待釐清補判。改成「基本」的上限含補判 1 次（sol 0.035→0.05、opus 0.13→0.17、sonnet 0.035→0.05；下限不變），F.3 的實測仍在範圍內，並用本次實測與 2.2.0 的 opus 實測（part＋recheck US$0.258）加測試。

### A.3 會議記錄校稿相容測試

撰寫會議記錄校稿規格時的試作程式（不公開）以本版 `V/payload/runtime/scripts` 為 Pro 跑相容測試：**39/39 PASS**（標記解析、經驗整理、定稿字幕用 Pro `subtitles.map_corrected` 對應失敗 0 段、名詞同步、網頁版、接續、多份同時…）；Pro 的 `scripts/` 沒有留下 `__pycache__`。

### A.4 發行檔

`make_dist.py`：版號六處一致、權重 0、H-13、參考資料檢查都過。

| 檔案 | 內容 | 大小 | SHA-256 |
|---|---|---|---|
| `meeting-minutes-pro-v2.3.0-installer.zip` | 51 檔 | 469,065 bytes | `56169aa833c3f48422cc47a5cd1e9c247e37bf6f6e3ec2f7eb53fedb61315aea` |
| `meeting-minutes-pro-v2.3.0-claude-app-upload.zip` | 7 項（`SKILL.md`、`references/` 4 檔、`scripts/render_html.py`、`scripts/html_template.html`） | 57,794 bytes | `95de6970ea38e1110439ce21c263396715cb14b7bfab32f31cbf9646b022d51b` |

兩個 zip 解開（含 installer 內的 upload zip）跑 `deid-scan.mjs --internal-ids`＋私有詞表：71 檔命中 0；家目錄／信箱 grep 0。

### A.5 入口 harness

`entry_harness.py`（假 runtime＋假 CLI，不呼叫模型）2.3.0：**161/161**（pwsh 54、Windows PowerShell 5.1 54、Git Bash 53；bash 的 `paste_two_lines` 因沒有 WSL 略過，同 2.2.0），含新情境 `hotwords_special_chars`、`hotwords_plain` 三種 shell 都 PASS。對照組（`MMP_TEST_VERSION=2.2.0 MMP_TEST_HOTWORDS_CONTROL=1`）：PS 5.1 的 `hotwords_special_chars` **FAIL**（`transcribe.py` 收到 `Kafka, 含 引號 … 結尾"`），pwsh 與 Git Bash PASS。
