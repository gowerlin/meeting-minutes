# meeting-minutes-pro 2.1 規格（公開版）：會議記錄／筆記的網頁版（HTML）

> **公開版**：本檔是 meeting-minutes-pro **2.1.0** 規格的公開版，適用 2.1.x。內容是 **2.1.0 相對 2.0.2 的差異**；本檔沒有提到的行為一律照 2.0 規格
> （公開版 [`meeting-minutes-pro-2.0-spec.md`](meeting-minutes-pro-2.0-spec.md)，含附錄 G 的 2.0.1／2.0.2 修正；下稱「2.0 規格」）。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 §x.y」（例 `render_html.py` 的「規格 §5.3」）就是本檔的同一節。原規格裡屬於開發流程的段落（§10 工作拆分、撰寫時的試作檔與使用紀錄）在公開版省略，但保留章節號，後面的編號不變。
> 版本目錄 `V/`＝`pro/meeting-minutes-pro-v2.1.0/`（公開 repo 的路徑）。
> 標示：**〔規格確認〕**＝撰寫規格時以合成素材在瀏覽器實測的結果（附錄 A）；**〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節（附理由）；以「實作結果：」開頭的句子是 2.1.0 實作時補充或修訂的細節（正文與實作結果不一致時以實作結果為準）。
> 「需求第 n 點」指 §0.3 表裡的 8 點需求。「`$MMH`」＝`MEETING_MINUTES_PRO_HOME`（Windows 預設 `%LOCALAPPDATA%\meeting-minutes-pro`）。

---

## 0. 摘要

### 0.1 2.1.0 做什麼

| 功能 | 預設 | 一句話 | 章節 |
|---|---|---|---|
| 網頁版 | 開 | 會議 `meeting-minutes.md` → `meeting-minutes.html`；其他類型 `notes.md` → `notes.html`；`auto_minutes.py` 寫完 `.md` 就產生 | §2 |
| 補產生 | — | 新指令 `render_html.py <輸出資料夾>`：使用者手改 `.md` 之後重新產生，不呼叫模型 | §2.3、§6.2 |
| 版型 | — | 左側目錄（手機收合成頂端列）、scrollspy、預設深色＋淺色切換；樣板是本工具自己的一份檔案，執行時不依賴其他專案 | §4 |
| 章節 | — | 目錄與錨點由 Markdown h2／h3 產生，7 種類型與自訂範本共用一份程式 | §3.3、§3.4 |
| 會議摘要卡 | 會議才有 | 決議／待辦／待釐清問題各幾項，點了跳到該節 | §4.4 |
| 時間碼可點播放 | 開（找得到能播的媒體時） | `HH:MM:SS` 轉成按鈕；頁面內嵌原始錄音或影片（相對路徑），點了跳到該秒播放；找不到或不能播 → 純文字時間碼 | §5 |
| 完全離線 | — | 單一 HTML 檔、CSS／JS 內嵌、系統字型；CSP `default-src 'none'`；外部請求 0 | §4.1、§8 |
| 本機轉換 | — | 程式轉換，不呼叫模型；只支援輸出實際會用到的 Markdown 子集；所有內容 HTML 跳脫 | §3 |
| Claude App 模式 | — | upload zip 附同一支 `render_html.py`；沙盒能執行 Python 時照樣產生 `.html` 檔交付 | §7.4 |

### 0.2 不做什麼

- 逐字稿（`transcript.md`／`transcript.corrected.md`）的網頁版、基本版 `meeting-minutes` 的網頁版：後續候選（§11）。
- 在網頁上編輯、存回 `.md`；網頁版是 `.md` 的**衍生檔**，內容以 `.md` 為準。
- 關鍵畫面（`frames/`）縮圖、Mermaid 畫圖（需要圖片或外部程式庫）：後續候選（§11）。
- 在網頁裡顯示外部連結的可點連結（§3.2 第 6 點）。
- 報告型版面的元件（證據標籤、風險分級、結論卡、事件時間軸、程式碼對照、SVG 圖）。
- 入口（右鍵／拖放）不加新題目；不自動用瀏覽器開啟網頁版。

### 0.3 需求對照表

| # | 需求 | 規格章節 |
|---|---|---|
| 1 | 預設產出：`meeting-minutes.md` → `meeting-minutes.html`、其他類型 `notes.md` → `notes.html`；config 可關（鍵名由規格定） | §2.1（檔名）、§2.2（產生時機）、§6.1（`html.enabled`，預設 `true`）、§6.2（`--no-html`） |
| 2 | 版型：左側 sticky 目錄、< 1024px 收合成頂端列、scrollspy（`IntersectionObserver`）、預設深色＋淺色切換、CSS token；樣板是本工具自己的檔案、執行時不依賴其他專案；報告型元件不沿用 | §4.1（樣板檔與取捨表）、§4.2（目錄與 scrollspy）、§4.5（主題）、§0.2 |
| 3 | 章節由 Markdown h2／h3 產生目錄與錨點，7 種類型與自訂範本共用；頁首放標題、日期、與會者／講者、「自動整理｜未經人工確認」表頭；會議另有摘要卡（決議／待辦／待釐清各幾項，點了跳到該節） | §3.3（頁首與章節切分）、§3.4（錨點）、§4.3（頁首）、§4.4（摘要卡） |
| 4 | 時間碼可點播放；找得到原始媒體時內嵌 `<audio>`／`<video>`（相對路徑），點了跳到該秒；找不到或副檔名不能播 → 純文字時間碼；媒體定位方式與搬移資料夾後的行為由規格定並寫理由 | §5.1（辨識）、§5.2（定位與理由）、§5.3（格式表）、§5.4（退回）、§5.5（播放列）、§5.6（鍵盤與無障礙） |
| 5 | 完全離線：單一檔、CSS／JS 內嵌、不得有任何外部請求、改用系統字型 | §4.1、§8.1（CSP 與檢查方式）、§9.3（自動檢查） |
| 6 | 本機程式轉換、不呼叫模型；只支援實際用到的 Markdown 子集，其他照原文跳脫；所有內容 HTML 跳脫 | §3.1、§3.2、§8.2 |
| 7 | 可對既有輸出資料夾重新產生（手改 `.md` 之後）；指令形式由規格定 | §2.3、§6.2（`render_html.py`，〔規格決定〕與理由） |
| 8 | 版號 2.1.0；凍結介面不改名不移除 | §6.5（凍結介面：沒有改名或移除）、§6.6（版號） |

---

## 1. 流程與插入點

```text
transcribe.py ──→ （入口詢問）auto_correct.py ──→ （入口詢問）auto_minutes.py
                                                     │ 寫 meeting-minutes.md／notes.md（＋notes.json）
                                                     ▼
                                          render_html.render()      ← 2.1.0 新增（html.enabled，預設開）
                                                     │ 寫 meeting-minutes.html／notes.html
                                                     ▼
                                          失敗：只記 log、印一行提示；.md 與 exit code 不受影響

auto_minutes.py --render-only（notes.json → notes.md）──→ render_html.render()   ← 同上
render_html.py <輸出資料夾>（使用者手改 .md 之後）──→ render_html.render()       ← 2.1.0 新增
```

| 檔案（`V/payload/…`） | 2.1.0 改動 |
|---|---|
| `runtime/scripts/render_html.py`（新） | 轉換、媒體定位、寫檔、`run_log`；CLI（§6.2）；**只用標準函式庫**（Claude App 沙盒也要能跑，§7.4） |
| `runtime/scripts/html_template.html`（新） | 頁面樣板（CSS、JS、骨架與替換標記，§4.1） |
| `runtime/scripts/auto_minutes.py` | `_run()` 寫完 `.md` 後、`render_only()` 寫完 `notes.md` 後呼叫 `render_html.render()`；`--no-html`；stdout 與 `auto_minutes.json` 加 `html`（§2.2、§6） |
| `runtime/scripts/common.py` | `VERSION = "2.1.0"`；`DEFAULTS["html"]`；`upgrade_config()` 補 `html` 區塊（§6.1） |
| `runtime/scripts/runlog.py` | 階段名 `html`（顯示「網頁版」）；`summary` 不加欄位（§6.4） |
| `runtime/mm-sendto.ps1`、`runtime/mm-dropped.sh` | 結束畫面列出 `.html`、下一步改成「打開 .html」（§7.1） |
| `skill/meeting-minutes-pro/SKILL.md`、`references/*` | 網頁版說明、補產生指令、App 模式（§7.2～§7.4） |
| `skill/meeting-minutes-pro/scripts/render_html.py`、`html_template.html`（新，**打包時複製**） | 與 runtime 同一份（§7.4；`tools/make_dist.py` 檢查逐位元相同） |
| `meeting-minutes-pro-upload.zip` | 重新產生（多 `scripts/` 兩檔） |

---

## 2. 輸出檔與產生時機

### 2.1 檔名

| 來源 `.md` | 網頁版 | 說明 |
|---|---|---|
| `meeting-minutes.md` | `meeting-minutes.html` | 會議（含 `base: meeting` 的自訂範本） |
| `notes.md` | `notes.html` | 其他 6 種類型與其自訂範本 |
| 其他 `.md`（`render_html.py --file X.md`） | `X.html` | 使用者另存的版本、備份檔（例 `meeting-minutes.20261108-101500.bak.md` → 同名 `.html`） |

- 網頁版放在 `.md` 旁邊（同一個輸出資料夾）。媒體路徑是相對於網頁版所在資料夾的相對路徑（§5.2），所以**不能**改放到別處。
- 已有同名 `.html` 時直接覆寫，**不備份**〔規格決定〕：網頁版是衍生檔，任何時候都能從 `.md` 重新產生；`auto_minutes.py --force` 已經把舊的 `.md` 改名備份，需要舊網頁版時對備份 `.md` 執行 `render_html.py --file`。
- 寫檔用暫存檔＋`os.replace()`（原子替換），寫到一半失敗不會留下半個 `.html`。編碼 UTF-8（不加 BOM）、換行 `\n`。

### 2.2 產生時機（`auto_minutes.py`）

1. `_run()`：`.md` 寫入成功之後（狀態 `ok` 或 `partial`；`partial` 的 `.md` 開頭有「⚠ 這段未能自動整理」，網頁版照樣顯示成提醒框），`html.enabled` 為真且沒有 `--no-html` → 呼叫
   `render_html.render(out_dir, md_name, cfg=cfg, run_log=rl)`。`skipped`／`failed`（沒有寫 `.md`）時不呼叫。
2. `render_only()`（`--render-only`）：寫完 `notes.md` 後同樣呼叫（同一個開關）。
3. `render()` **不丟例外**（內部全部接住），回傳 `{"status": ok|failed|skipped, "reason", "output", "media", "timecodes", …}`（欄位同 §6.4 的 checkpoint）。
4. 失敗時：console 印 `  [!] 網頁版未產生（<reason>）；<md 檔名> 不受影響，可執行 render_html.py 補做`；`auto_minutes.py` 的 `status`、`reason`、exit code **都不變**
   （網頁版是附加產物，不能讓整理結果被判成失敗）。
5. 結果寫進 stdout 最後一行 JSON 的 `minutes.html`（新鍵：`{"status", "reason", "output", "media"}`；沒產生時 `status: "skipped"`、`reason: "disabled"`）與 `auto_minutes.json` 的 `html`（同欄位）。
   實作結果：整理本身 `skipped`／`failed`（沒有寫 `.md`，例如已有 `.md` 沒加 `--force`）時是 `status: "skipped"`、`reason: "no_md"`；`disabled` 只用在設定關或 `--no-html`。

`reason` 代碼：`disabled`（設定關或 `--no-html`）、`no_md`（找不到 `.md`）、`template_missing`（找不到 `html_template.html`）、`write_failed`（寫檔失敗，含權限）、`internal_error`（其他例外，附例外類別名，不附訊息全文）。

### 2.3 補產生（使用者手改 `.md` 之後）〔規格決定：獨立的 `render_html.py`〕

```bash
"$PY" "$MMH/scripts/render_html.py" "<檔名>_minutes"                 # 有 meeting-minutes.md 就轉它，否則 notes.md
"$PY" "$MMH/scripts/render_html.py" "<檔名>_minutes" --file notes.md # 指定檔名（只限輸出資料夾內的 .md）
"$PY" "$MMH/scripts/render_html.py" --md "<檔案>.md" [--out "<檔案>.html"]   # 沒有輸出資料夾（App 沙盒、單獨一份 .md）
```

理由：

- 補產生**不需要**供應商、模型、金鑰、類型或範本；放在 `auto_minutes.py` 會讓旗標組合變多（`--html-only` 與 `--force`、`--type`、`--minutes-*` 同時給時的語意都要定），
  也會讓「不呼叫模型」這件事要靠旗標保證。獨立程式從結構上就不會呼叫模型。
- Claude App 沙盒只需要這一支（＋樣板），不必帶整個 runtime（§7.4）。
- `auto_minutes.py --render-only` 照舊只管 `notes.json → notes.md`，之後自動接 `render_html`，使用者不用記第二個指令。

`render_html.py` 會議與筆記都支援（會議沒有 `notes.json`，所以網頁版一律從 `.md` 轉，§3）。exit code：`0` 產生成功；`2` 跳過（找不到 `.md`、參數錯誤）；`1` 失敗。stdout 最後一行 `{"html": {…}}`（§6.4 的欄位）。

---

## 3. Markdown → HTML 轉換規則

### 3.1 為什麼從 `.md` 轉（而不是 `notes.json`）

- 會議沒有結構化 JSON；使用者與對話中的 Claude 改的是 `.md`（SKILL.md §4.2：直接改 `notes.md` 並把表頭改成「經對話確認」）。從 `.md` 轉，手改後補產生的結果才會一致。
- 輸入是 2.0.2 的 `render_markdown()`／`render_notes()` 產生的固定版面，加上使用者小幅手改；所以只支援這兩支函式**實際用到的子集**（§3.2），其餘照原文跳脫，不做通用 Markdown。

### 3.2 支援的子集

| Markdown | 輸出 | 用在哪裡（2.0.2） |
|---|---|---|
| `# 標題`（第一個） | 頁首 `<h1>` 與 `<title>` | 兩種版面的第一行 |
| `## 標題` | `<section id>` ＋ `<h2>`；目錄第一層 | 各節 |
| `### 標題` | `<h3 id>`；目錄第二層 | 會議議題 `2.1 …`、筆記章節 `1.1 …` |
| `####`～`######` | `<h4>`（不進目錄、不給 id） | 不使用；使用者手改才有 |
| 第二個以後的 `# 標題` | 當成 `##` | 不使用 |
| 段落（連續非空行） | `<p>`，行與行之間以空白接起 | 摘要 |
| `> 引用`（連續行） | 頁首：狀態列與提醒（§4.3）；正文：提醒框 `.callout` | 「> 自動整理：…」「> ⚠ …」 |
| 表格（`|` 開頭、第二行是 `|---|` 分隔列） | `.tbl` 容器內的 `<table>`；第一欄標題是 `#` 或 `項目` 時第一欄用 `<th scope="row">`；欄名是「時間碼」的欄加 `num`（等寬數字、不換行） | 決議、待辦、待釐清、筆記各表；頁首「項目｜內容」表 |
| 清單 `- `、`* `、`1. `（縮排 ≥ 2 格＝第二層，只支援兩層） | `<ul>` | 議題的背景／意見／結論、轉寫品質備註、課程章節重點 |
| `---` 單獨一行 | 不輸出（版面已分節） | 〈轉寫品質備註〉前 |
| 一行剛好是 `<details><summary>文字</summary>`，與一行剛好是 `</details>` | `<details class="quality" id>`；目錄最後一項 | 〈轉寫品質備註〉（**唯一**放行的 HTML，只認這兩種整行寫法；summary 文字 ≤ 80 字、不得含 `<` `>`） |
| ```` ``` ```` 程式碼區塊（含 ```` ```mermaid ````） | `<pre class="code" role="region" tabindex="0">`，內容跳脫；mermaid 的 `aria-label` 寫「Mermaid 圖的原始碼（網頁版離線顯示，不畫圖）」 | 不使用；SKILL 對話中寫的會議記錄可能有 Mermaid |
| 行內 `` `程式碼` `` | `<code>`；內容是 `[HH:MM:SS]` 時當時間碼（§5.1） | 時間碼 `` `[00:12:34]` ``、檔名 |
| 行內 `**粗體**` | `<strong>` | 「**未經人工確認**」 |
| 行內 `[文字](連結)` | 連結是 `#錨點` 或相對路徑（沒有 scheme、不是 `//` 開頭）→ `<a href>`；其他（`http:`、`https:`、`mailto:`、`javascript:`…）→ 純文字「文字（連結）」，不做成連結 | 不使用；使用者手改才有 |
| 其他（斜體、圖片 `![]()`、HTML 標籤、註腳…） | 原文跳脫後當文字輸出 | — |

- 第 6 列的外部連結〔規格決定〕：會議記錄與筆記來自語音，幾乎不會有連結；做成純文字可以讓「外部請求 0」的自動檢查（§9.3）簡單而且沒有例外，也從結構上擋掉 `javascript:` 連結。點開外部連結本身不是頁面的請求，若之後要可點，另開單評估（§11）。
- 每一個區塊都要能處理「不完整」的寫法而不丟例外：沒有分隔列的 `|` 行當段落；欄數不足的表格列補空白、多的截掉；沒有成對的 `</details>` 時在文末自動關閉。

### 3.3 頁首與章節切分

- **頁首**＝第一個 `#` 之後、第一個 `##` 之前的內容：
  - 引用行以 `自動整理後經對話確認：` 開頭 → 狀態徽章「自動整理後經對話確認」（實線、綠）；以 `自動整理：` 開頭 → 狀態徽章「自動整理｜未經人工確認」（虛線、黃），徽章後照印那一行全文；
    兩種都沒有 → 不顯示徽章〔規格決定：徽章反映 `.md` 自己的說法；程式產生的 `.md` 一定有這一行，沒有表示使用者刻意刪掉或改寫成自己確認過的版本，網頁版不替使用者加上或拿掉聲明〕。
  - 其他引用行（`⚠ …`）→ 頁首的提醒框。
  - 第一列是 `| 項目 | 內容 |` 的表格 → 頁首的資訊卡（`<dl>`；「日期時間」「與會者」／「講者」「類型」「記錄來源」／「來源」照原列順序）。
  - 其他段落照印在資訊卡之後。
- **章節**：每個 `##` 開一個 `<section>`，到下一個 `##` 或 `<details>` 為止。`<details>` 自成一節（目錄最後一項）。
- 7 種類型與自訂範本**共用同一份規則**，不為任何類型寫對應；自訂範本的 `labels` 只改 `##` 的文字，目錄跟著變。

### 3.4 錨點 id（中文標題）〔規格決定〕

```text
id = "h-" + slug(標題文字)；同一頁重複時依序加 "-2"、"-3"
slug：去掉結尾的時間碼（`[HH:MM:SS]`）→ NFKC 正規化 → 去掉 ` 與 * → 轉小寫
      → 連續的空白與標點 \s " ' < > & # % { } | \ ^ ` [ ] / ? ; : @ = + $ , ! * ( ) . （）「」『』、。，：；？！／〔〕【】·・ 換成一個 "-"
      → 去掉頭尾的 "-" → 取前 60 字 → 空字串時用 "sec"
```

| 標題 | id |
|---|---|
| `一、會議摘要` | `h-一-會議摘要` |
| `2.1 壓測結果與資料庫調整　` `` `[00:00:20]` `` | `h-2-1-壓測結果與資料庫調整` |
| `四、待辦事項（Action Items）` | `h-四-待辦事項-action-items` |
| `2. 關鍵概念` | `h-2-關鍵概念` |

理由：保留中文，網址的 `#` 片段看得懂（瀏覽器顯示時會解碼）；同一份 `.md` 重新產生時 id 不變，可以把「某一節」的連結傳給別人；加 `h-` 前綴避免以數字開頭，也不會和樣板內部的 id（`toc-drawer`、`media`、`dock`）撞名。只用流水號（`s1`、`s2`）會在使用者插入一節後全部位移，所以不用。

---

## 4. 版型

### 4.1 樣板檔與從參考樣板取了什麼

樣板 `V/payload/runtime/scripts/html_template.html`：完整 HTML 文件（`<!doctype html>`、`<html lang="zh-Hant-TW" data-theme>`、`<meta charset>`、viewport `viewport-fit=cover`、CSP meta、`<meta name="referrer" content="no-referrer">`），
一段 `<style>`、一段 `<script>`，以及替換標記 `{{CSP}} {{THEME}} {{TITLE}} {{TOC}} {{MASTHEAD}} {{BODY}} {{PLAYER}} {{FOOTER}}`。
替換**一次完成**（`re.sub(r"\{\{([A-Z]+)\}\}", …)` 對樣板做一次），內容裡出現的 `{{…}}` 不會被再替換。

| 參考樣板（一份長文報告網頁樣板） | 2.1.0 | 理由 |
|---|---|---|
| 顏色 token（深色在 bare `:root`、淺色在 `[data-theme="light"]`）、字級、行高、`.page` 寬度與留白、`.prose` 46em | **取** | 需求第 2 點 |
| 目錄 `<details>`（手機頂端列、桌機左側 sticky 欄）、子項 `height:0` 收合、鍵盤進目錄時全部展開、Esc 收合 | **取**（CSS 與 JS 原樣） | 同上；`layout-spec.md` §3 的無障礙要求 |
| Scrollspy：`IntersectionObserver`、判定線 25%、捲到底標示最後一項、`keepVisible()` | **取**（原樣） | 同上 |
| `.tbl`（窄螢幕在容器內水平捲動）、`th`／`td`、`.num`、`.callout`、`.note`、`footer.colophon`、`@media print`、`prefers-reduced-motion` | **取** | 版面需要 |
| Google Fonts `<link>`、`preconnect` | **拿掉**；字型只寫系統字型名稱（`"Noto Sans TC", "Microsoft JhengHei", "PingFang TC", system-ui, sans-serif` 等），不用 `@font-face` | 需求第 5 點 |
| `claude:viewport-fit-sides` meta、「Artifact 不寫 `<html>`」的骨架 | **拿掉**；改成完整 HTML 文件 | 網頁版是檔案，不是 Artifact |
| `.tag`／`.legend`（證據標籤）、`.verdict`、`.lv`（風險分級）、`.cards`、`.events`、`.codepair`、`.steps`、`figure`／SVG、`.refs`、`.mark` | **拿掉** | 需求第 2 點：報告型元件不沿用 |
| — | **新增**：頁首狀態徽章與資訊卡（§4.3）、摘要卡（§4.4）、主題切換鈕（§4.5）、時間碼與播放列（§5）、`details.quality`、`pre.code` | 需求第 3、4 點 |

token 只新增 `--warn`／`--warn-bg`（未經人工確認、提醒框）、`--ok`／`--ok-bg`（經對話確認）與 `--dock-h`（播放列高度），深淺兩組都要定義。元件規則不寫字面色值（播放列陰影的 `#000` 除外）。

### 4.2 目錄與 scrollspy

- 目錄第一層＝每個 `##`（顯示章節號＋名稱）與〈轉寫品質備註〉；第二層＝`###`（去掉結尾時間碼）。章節號：`一、` 這類中文數字或 `1.` 這類數字前綴拆成 `.no`，其餘（例「摘要」）`.no` 顯示 `·`（`aria-hidden`）。
- 點目錄裡的〈轉寫品質備註〉或網址的 `#` 指到它時，自動展開 `<details>`。
- 手機（< 1024px）：頂端列顯示「目錄 · 目前章節」，點選項目後收合（同樣板）。
- 沒有 JS：目錄是普通錨點、全部展開；不顯示目前章節（同樣板 `layout-spec.md` §10）。

### 4.3 頁首

由上而下：一行 eyebrow（`meeting-minutes-pro · 會議記錄`／`筆記`）＋主題切換鈕 → `<h1>`（`.md` 的第一個 `#`）→ 狀態徽章與狀態列（§3.3）→ 資訊卡（日期時間、與會者／講者、類型、來源）→ 頁首提醒框（`⚠` 行、媒體格式不能播的說明 §5.4）→ 會議的摘要卡（§4.4）。

- 頁首裡的時間值（例「長度 00:09:38」）**不做成播放按鈕**〔規格確認：撰寫規格時的試作把它做成按鈕，實測時改掉；長度不是播放位置〕。

### 4.4 會議摘要卡

- 只在會議（來源檔名是 `meeting-minutes.md`，或 h1 以「 會議記錄」結尾）顯示。三張卡依序：決議、待辦、待釐清問題；每張是 `<a href="#該節 id">`，顯示項數與名稱。
- 計數：在正文找表頭（不看節標題，節標題會被自訂範本的 `labels` 改掉）——第 2 欄是「決議」→ 決議表；第 2、3 欄是「事項」「負責人」→ 待辦表；第 2 欄以「問題」開頭 → 待釐清表。
  項數＝第一格不是 `—`／`-`／空白的資料列數（2.0.2 沒有項目時寫一列 `| — | （無） | …`）。找不到某張表就不顯示那張卡。
- 筆記（`notes.html`）不顯示摘要卡（需求只要求會議）；它的「待釐清」節照樣在目錄裡。

### 4.5 深淺主題與列印

- 預設深色（`<html data-theme="dark">`，值取 `html.theme`，§6.1）；頁首的切換鈕切換 `data-theme`，按鈕文字「改成淺色」／「改成深色」，`aria-label` 寫明目前主題。
- 使用者的選擇記在瀏覽器 `localStorage`（鍵 `mmp-theme`），讀寫都包 `try/catch`；讀不到時用產生時的預設。不跟隨系統主題（同參考樣板：使用者指定的偏好）。
- 列印：隱藏目錄、播放列、切換鈕；時間碼印成純文字；表格取消最小寬度、改成換行；列印前自動展開〈轉寫品質備註〉（`beforeprint`）。

### 4.6 頁尾

`由 meeting-minutes-pro 2.1.0 從 <code>meeting-minutes.md</code> 產生於 <產生時間，本機時區 ISO 8601>。內容以 meeting-minutes.md 為準；改過 .md 之後請重新產生網頁版。`
（產生時間由程式取系統時間；不寫路徑、不寫電腦名稱。）

---

## 5. 時間碼與媒體

### 5.1 辨識

- 規則：`(?<![\d:])(\d{1,2}):([0-5]\d):([0-5]\d)(?![\d:])`，比對**已跳脫的文字節點**（標題、段落、清單、表格儲存格、`` `[HH:MM:SS]` `` 行內程式碼）。不比對：頁首（§4.3）、程式碼區塊、連結的網址。
- 不認 `MM:SS`〔規格決定〕：會和「8:30 開會」這類時刻混淆；2.0.2 的輸出一律是 `HH:MM:SS`。
- 範圍：有 `transcript.json` 的 `meta.duration` 時，超過「錄音長度＋60 秒」的值照原文輸出、不做成時間碼（與 2.0.2 `auto_minutes.norm_time()` 相同的容許值），計入 `timecodes_out_of_range`。沒有長度（`--md` 單獨一份）時不限。
- 輸出：
  - 有播放器：`<button type="button" class="tc" data-t="<秒數>" aria-label="從 00:02:14 播放"><time datetime="PT0H2M14S">00:02:14</time></button>`
  - 沒有播放器：`<time class="tc-text" datetime="PT0H2M14S">00:02:14</time>`
  - 顯示一律補成 `HH:MM:SS`；`` `[00:02:14]` `` 的反引號與方括號不再顯示。

### 5.2 媒體定位〔規格決定〕

依序找，**第一個瀏覽器能播的**（§5.3 的表）就用；全部找完都沒有能播的、但有認得的媒體 → `unsupported`（§5.4）；什麼都沒有 → `none`。

| 順序 | 候選 | 依據 |
|---|---|---|
| ① | `<輸出資料夾>/../<meta.source>` | `transcribe.py` 預設把輸出資料夾建在原始檔旁邊（`src.with_name(src.stem + "_minutes")`），`transcript.json` 的 `meta.source` 是原始檔名（只有檔名、沒有路徑） |
| ② | `<輸出資料夾>/<meta.source>` | 使用者把原始檔搬進輸出資料夾一起保存 |
| ③ | `<輸出資料夾>/../<名稱>.<副檔名>`（輸出資料夾名以 `_minutes` 結尾時，`<名稱>`＝去掉 `_minutes`；副檔名依 §5.3 表的順序、不分大小寫） | `transcript.json` 不在或沒有 `source`；或使用者把 `.mov`／`.wma` 另存成 `.mp4`／`.mp3` 方便播放 |
| — | 命令列 `--media <檔案>` | 明確指定時跳過 ①～③（`media: explicit`）；`--no-media` 不放播放器（`media: off`） |

- 寫進頁面的是**相對於網頁版所在資料夾的相對路徑**（`os.path.relpath`，`/` 分隔，每段 `urllib.parse.quote`，例 `../M1.wav`、`../%E9%80%B1%E6%9C%83.m4a`）。**不寫絕對路徑、不寫 `file://`**。
- 理由：
  - 絕對路徑會把使用者名稱、資料夾結構寫進一份可能被轉寄的檔案（§8），換到別的電腦開啟時也找不到媒體。
  - 相對路徑在「整組一起搬」（原始檔＋`_minutes` 資料夾，或整個上層資料夾壓縮、複製到隨身碟）時照樣能播，這是使用者最常見的搬法。
  - `transcribe.py --out-dir` 指定到別處的輸出資料夾，①③ 都找不到；這種情況用 `render_html.py --media` 補。
- **搬移後的行為**：
  - 只搬 `_minutes` 資料夾、原始檔留在原處 → 頁面載入時媒體讀不到，觸發 §5.4 的執行時退回（播放列收起、時間碼變純文字），頁面其他部分正常。在新位置執行 `render_html.py`（找得到時）或加 `--media` 即可恢復。
  - 原始檔改名 → 同上（`meta.source` 對不到）；`render_html.py --media <新檔名>`。
- 不複製、不轉檔媒體〔規格決定〕：複製會讓輸出資料夾變大一倍；轉檔要 ffmpeg 與時間。不能播的格式只在頁首說明（§5.4）。

### 5.3 支援格式

判斷依副檔名（小寫）。表內「播放」欄是**〔推論〕**（各瀏覽器常見支援，未逐一實測；撰寫規格時在 Windows Chrome 實測 `.mp3`、`.wav`、`.mp4` 可播），所以一律再靠執行時退回（§5.4）兜底：表判斷錯了也不會顯示壞掉的播放器。

| 副檔名 | 元素 | 播放（Chrome／Edge、Firefox、Safari） | 處理 |
|---|---|---|---|
| `.mp3` `.m4a` `.aac` `.wav` `.flac` | `<audio>` | 三者都可 | 放播放器 |
| `.ogg` `.oga` `.opus` `.weba` | `<audio>` | Chrome、Firefox 可；Safari 較新版本才可 | 放播放器（不能播時執行時退回） |
| `.mp4` `.m4v` | `<video>` | 三者都可（H.264） | 放播放器 |
| `.webm` | `<video>` | Chrome、Firefox 可；Safari 較新版本才可 | 放播放器（同上） |
| `.mov` | `<video>` | Safari 可；Chrome 視編碼（H.264 多半可） | 放播放器（同上） |
| `.wma` `.wmv` `.avi` `.mkv` `.flv` `.amr` `.3gp` `.aif` `.aiff` `.mpg` `.mpeg` `.ts` `.mts` `.m2ts` `.ape` `.ac3` | — | 多半不能 | 不放播放器；`media: unsupported`（§5.4） |
| 其他 | — | — | 不當成媒體（③ 不找） |

### 5.4 退回行為

| 情況 | 產生時（`render_html`） | 開啟時（頁面 JS） |
|---|---|---|
| 找不到媒體（`none`）、`--no-media`、`html.media: off` | 不放播放器；時間碼是純文字 `<time>` | — |
| 找到但格式不能播（`unsupported`） | 同上；頁首加一行說明「原始檔格式 .wma 瀏覽器多半不能播放，時間碼以文字顯示。」 | — |
| 放了播放器，但開啟時讀不到（搬走、改名、格式其實不能播） | — | `<audio>`／`<video>` 的 `error` 事件（或載入時 `media.error` 已有值）→ 收起播放列（`hidden`）、把每個時間碼按鈕換回 `<time class="tc-text">`。**不顯示壞掉的播放器** |
| 點的時間碼超過媒體長度 | — | 跳到「媒體長度 − 1 秒」 |

〔規格確認〕三種情況都在 Chrome 實測（附錄 A.2）。

### 5.5 播放列位置（2.1.0 實作時修訂）

- **錄音**：固定在畫面底部的一列（桌機寬度最多 1280px 置中，手機滿寬），顯示「原始錄音：<檔名>」與 `<audio controls preload="metadata">`。
- **影片**：桌機（≥ 1024px）在右下角的小窗（寬 `min(400px, 100vw − 32px)`）；手機在底部滿寬。
  - 影片畫面的最大高度 `--video-max`：桌機 `min(225px, 100vh − 150px)`、手機 `min(30vh, 240px)`；播放列整體最高 `100vh`（桌機小窗 `100vh − 32px`）。
    **播放列含原生控制列一定完整放在視窗內**。
  - 標題列有三個鈕（有 JS 時才顯示）：「全螢幕」（`requestFullscreen()`，iOS 用 `webkitEnterFullscreen()`）、「收合影片／展開影片」、收合時才出現的「播放／暫停」。
  - **收合只藏影片畫面**（`display: none`），聲音照常播放；播放、暫停改用標題列的「播放／暫停」鈕。不再把影片縮成 40px 高。
  - 全螢幕：原生控制列的全螢幕鈕與標題列的「全螢幕」鈕都可用；收合中按「全螢幕」先展開再進入。進入時記下捲動位置，退出後捲回原位置；全螢幕期間不重新量播放列高度。
- **正文底部讓出空間**：JS 用 `ResizeObserver` 量播放列實際高度，設定 `--dock-h`＝播放列高度＋與視窗底的距離＋16px，正文底部留白＝原本的留白＋`--dock-h`；
  捲到底時最後一段與頁尾都在播放列上方（錄音、影片，桌機、手機一樣）。左側目錄的最大高度另扣 `--dock-bar`（底部整列才扣；桌機影片小窗不扣）。
  沒有 JS 時用 CSS 估計值（`:root:has(#dock…)`）。
- 播放列不是捲動容器（`overflow` 不設），不攔截頁面捲動；`wheel` 事件照常冒泡。
- 理由〔規格決定〕：底部固定列在捲到任何一節時都看得到、點了時間碼不用捲回頁首；放在頁首會在捲動後消失。影片在桌機用小窗，不擋左側目錄與正文的主要閱讀區（表格的最右欄被蓋住時，用收合）。
- `preload="metadata"`：開頁時只讀媒體的長度資訊，不整個載入（大檔也不拖慢開頁）。
- 只內嵌一個媒體；`<video>` 不加 `autoplay`、`loop`；加 `playsinline`（iOS 不自動進入全螢幕）。

**修訂理由（2.1.0 實作時以合成影片素材 TU1 在 Chrome 重現）**：

| 問題 | 原因（1.0 設計） | 修法 |
|---|---|---|
| (a) 播放器下方被遮一半 | 「收合影片」把 `<video>` 縮成 40px 高：Chrome 的原生控制列需要約 70px，40px 高只剩進度條，播放、音量、全螢幕鈕都被裁掉（實測截圖）；影片畫面高度也沒有依視窗高度設上限。未收合的小窗在 1440×900、1366×768、375×667 都完整在視窗內（實測），使用者看到的「下方被遮一半」與收合後的畫面相符〔推論〕 | 收合改成整個藏起影片畫面、另給播放鈕；影片畫面加 `--video-max`，播放列整體不超過視窗 |
| (b) 無法往下捲動（最後一段被蓋住） | 桌機影片小窗時 `--dock-h` 寫死 `0px`（以為小窗不佔底部），正文底部只留 96px，捲到底時頁尾與最後一段在 246px 高的小窗底下（1366×768 實測：頁尾底 672px、小窗頂 506px）；手機 `34vh` 也只是估計值 | 依播放列實際高度設定 `--dock-h`（四種視窗、收合與展開都實測） |
| (c) 無法全螢幕 | 收合狀態下原生全螢幕鈕被裁掉（同 (a)）；沒有收合時原生鈕可用，但小窗裡不明顯 | 標題列加「全螢幕」鈕；收合時按它先展開再進入；退出後回到原捲動位置 |

### 5.6 操作、鍵盤與無障礙

- 點時間碼：跳到該秒並開始播放（媒體資料還沒載入時等 `loadedmetadata` 再跳）；播放列狀態文字（`role="status"`、`aria-live="polite"`）更新為「從 00:04:58 播放」；最後點的那個時間碼加實線框（`.is-last`）。
- 時間碼是 `<button>`：Tab 可聚焦，Enter／Space 觸發；有 2px 主色 `:focus-visible` 外框；`aria-label`「從 HH:MM:SS 播放」。
- 不加全頁快捷鍵〔規格決定〕：避免和瀏覽器、螢幕報讀器的按鍵衝突；播放、暫停、音量用原生控制列（本身可用鍵盤操作）。
- 播放列 `<aside aria-label="原始錄音">`／「原始影片」。`prefers-reduced-motion: reduce` 時捲動不做平滑效果（同樣板）。

---

## 6. 設定鍵、旗標與紀錄

### 6.1 `config.json` 新鍵（`common.DEFAULTS`）

```jsonc
{
  "runtime_version": "2.1.0",
  "html": {
    "enabled": true,     // auto_minutes.py 寫完 .md 後產生網頁版（需求第 1 點：預設產出）
    "media": "auto",     // auto＝依 §5.2 找原始媒體並放播放器；off＝不放播放器（時間碼一律純文字）
    "theme": "dark"      // dark｜light：網頁版第一次開啟時的主題（之後依使用者在頁面上的選擇）
  }
}
```

- 讀取一律經 `common.setting()`（鍵不存在用 `DEFAULTS`，不寫回）。不認得的值（例 `media: "yes"`）當成預設值，console 印一行 `[!] html.media 的值 yes 不認得，改用 auto`。
  實作結果：由 `common.html_setting(cfg, key)` 負責（提示印到 stderr）；`upgrade_config()` 不改使用者寫的值（含不認得的值），只補缺的鍵。`render_html.py` 在沒有 `common.py` 的沙盒用檔內的同一組預設值。
- `upgrade_config()`：`html` 加進升級時補的區塊（與 2.0 的 `V2_BLOCKS` 相同做法：整塊不存在就寫入；部分鍵存在時逐鍵補）。1.x／2.0.x 升級上來的使用者得到 `enabled: true`（需求：預設產出）。
- 不做類型別設定（`content_types.<代號>` 不認 `html`）〔規格決定：網頁版與類型無關〕。

### 6.2 命令列

`render_html.py`（新）：

| 旗標 | 作用 |
|---|---|
| `<out_dir>` | 輸出資料夾；預設轉 `meeting-minutes.md`，沒有就 `notes.md`；都沒有 → exit 2（`no_md`） |
| `--file <名稱>.md` | 轉輸出資料夾內指定的 `.md`（不得含路徑分隔字元；不在資料夾內 → exit 2） |
| `--md <檔案> [--out <檔案>]` | 單獨一份 `.md`（不讀 `transcript.json`、不找媒體、時間碼不限範圍）；與 `<out_dir>` 互斥 |
| `--media <檔案>`／`--no-media` | 指定媒體／不放播放器（互斥）；`--media` 的檔案不存在 → exit 2 |
| `--theme dark\|light` | 本次的預設主題（不給＝`html.theme`） |

`render_html.py` 不讀 `html.enabled`（使用者明確要求產生），讀 `html.media`、`html.theme`。

`auto_minutes.py`（新增）：`--no-html`（本次不產生網頁版）。既有旗標、exit code 全部不變。

`transcribe.py`、`auto_correct.py`：不變。

### 6.3 優先序

命令列 > `config.json` 的 `html.*` > `common.DEFAULTS`。

### 6.4 `run_log`、`auto_minutes.json`、stdout

| 位置 | 新內容 |
|---|---|
| `run_log.jsonl`：`auto_minutes.py` 內 | `checkpoint` `minutes.html`（在 `minutes` 步驟內），欄位見下 |
| `run_log.jsonl`：單獨執行 `render_html.py` | `RunLog(out_dir, step="html")`；`checkpoint` `html`＋`result`；結束時 `runs.jsonl` 追加一列（`stages` 含 `html`）。`--md` 模式沒有輸出資料夾，不寫 log |
| checkpoint 欄位 | `status`（ok／failed／skipped）、`reason`、`source`（`.md` 檔名）、`output`（`.html` 檔名）、`bytes`、`headings`、`timecodes`、`timecodes_out_of_range`、`media`（`found`／`explicit`／`none`／`unsupported`／`off`）、`media_ext`、`escaped_html`（被跳脫的 HTML 標籤數）、`duration_ms` |
| `auto_minutes.json` | `html`：`{"status", "reason", "output", "media", "timecodes"}` |
| stdout 最後一行（`auto_minutes.py`） | `minutes.html`：`{"status", "reason", "output", "media"}` |
| `runlog.py summary` | 不加欄位；階段名 `html` 顯示「網頁版」 |

- 不記 `.md` 內容、標題、媒體**檔名**與任何路徑（媒體只記副檔名）〔規格決定：媒體檔名常是會議名稱，等同內容〕。`tests/test_runlog.py` 的 6 字片段檢查加網頁版的 log。
  實作結果：單獨執行 `render_html.py` 時不寫 `info` 事件（它帶 `meta.source`＝原始檔名）；`runs.jsonl` 該列的 `source` 因此是空的，`summary` 的「來源」欄照舊退回輸出資料夾名稱。
  `auto_minutes.py` 既有的 `info` 事件（2.0.2 起就有）不變。

### 6.5 凍結介面

| 介面 | 2.1.0 |
|---|---|
| 輸出檔名（`transcript.*`、`meeting-minutes.md`、`notes.md`、`notes.json`、`auto_*.json`、`run_log.jsonl`、字幕） | 全部保留、格式不變；只**新增** `meeting-minutes.html`、`notes.html` |
| `config.json` 鍵 | 全部保留、預設不變；只新增 `html` 區塊 |
| 各程式旗標與 exit code | 全部保留；只新增 `auto_minutes.py --no-html` 與新程式 `render_html.py` |
| stdout JSON、`auto_minutes.json`、`run_log` 事件、`runs.jsonl` | 鍵名全部保留；只新增 §6.4 的欄位與 checkpoint |
| 入口題目、`wait` 名稱、環境變數、安裝參數 | 不變 |
| SKILL 的「> 自動整理：…」表頭判斷 | 不變（網頁版也照這一行顯示徽章，§3.3） |

**沒有任何改名或移除**，不需要遷移。入口結束畫面的「下一步」文字改寫（§7.1）不是凍結介面。

### 6.6 版號

| 位置 | 值 |
|---|---|
| 目錄 | `meeting-minutes-pro-v2.1.0/`（由 v2.0.2 複製；舊版本目錄不改） |
| `common.VERSION` | `"2.1.0"` |
| `SKILL.md` 版本註解 | `<!-- meeting-minutes-pro-version: 2.1.0 -->` |
| `install.ps1` `$Version`、`install.sh` `VERSION`、兩支入口的檔頭註解 | 2.1.0 |
| README 標題下 | `> 版本 2.1.0`；加〈2.1.0 新功能：網頁版〉一節 |
| `render_html.py` 頁尾版號 | 取 `common.VERSION`；Claude App 沙盒沒有 `common.py` 時用檔內常數 `FALLBACK_VERSION = "2.1.0"`（`make_dist.py` 檢查兩者一致） |
| `payload/meeting-minutes-pro-upload.zip` | 重新產生 |

---

## 7. 入口、SKILL.md 與 Claude App

### 7.1 入口（`mm-sendto.ps1`／`mm-dropped.sh`）

- **不加題目**〔規格決定〕：需求定為預設產出、可由設定關閉；網頁版不送任何資料、不花錢、產生不到 1 秒〔規格確認：兩份合成素材的網頁版各約 40 KB〕，沒有需要使用者當場決定的取捨。
- 整理步驟照舊執行 `auto_minutes.py`，網頁版由它接著產生；入口不另外呼叫 `render_html.py`。
- 結束畫面的檔案清單（2.0 規格 §7.4）加一列：`meeting-minutes.html`「會議記錄網頁版（用瀏覽器開；時間碼可點播放）」／`notes.html`「〈類型〉筆記網頁版（…）」；沒有原始媒體可播時括號改寫「時間碼為文字」（讀 `auto_minutes.json` 的 `html.media`）。
- 「下一步」：有 `.html` 時改成「打開 meeting-minutes.html（用瀏覽器）確認決議與待辦；…」（其餘原文不變）；網頁版失敗時多一行黃字「網頁版未產生（原因）；可執行 render_html.py 補做」。
- 不自動用瀏覽器開啟網頁版〔規格決定：使用者可能還要先看 console 的提示；自動開啟在測試與遠端環境都容易出問題〕。
- 實作結果：
  - 列 `.html` 的條件：`auto_minutes.json` 的 `html.status` 是 `ok`，而且 `html.output` 指的檔案在輸出資料夾裡（設定關、`--no-html`、失敗、沒有整理時都不列；之前留下的舊 `.html` 也不會被列出）。列在對應的 `.md` 下一列，說明是「會議記錄網頁版（用瀏覽器開；時間碼可點播放｜時間碼為文字）」／「〈類型〉筆記網頁版（…）」（〈類型〉＝入口既有的 `$Thing`，例「課程筆記網頁版」）。
  - 「下一步」：會議與筆記都改（`打開 meeting-minutes.html（用瀏覽器）確認決議與待辦；…`、`打開 notes.html（用瀏覽器）確認內容；…`），「附上 …」仍是 `.md`（Claude 要讀的是 `.md`）。
  - 黃字只在**這次有執行整理**、而且 `html.status` 是 `failed` 時顯示；原因譯成中文（`template_missing`「找不到網頁版樣板 html_template.html」、`write_failed`「寫入檔案失敗」、`internal_error`「程式錯誤」，其他照代碼），後面接補做的完整指令（`"<python>" "<scripts>/render_html.py" "<輸出資料夾>"`）。
  - `entry_harness.py` 的 11 個網頁版情境與 `rows` 檢查見附錄 B。

### 7.2 SKILL.md（本機模式）

| 段落 | 2.1.0 改法 |
|---|---|
| 開頭功能清單 | 加第 11 點「**網頁版**（2.1）：整理完同時產生 `meeting-minutes.html`／`notes.html`（左側目錄、深淺主題、時間碼點了播放原始錄音；單一檔、完全離線）」 |
| §2 輸出清單、§2.1 | 加 `.html`；stdout 的 `minutes.html` |
| §4.2 會議記錄／筆記 | 在對話中改了 `meeting-minutes.md`／`notes.md` 之後，執行 `"$PY" "$MMH/scripts/render_html.py" "<檔名>_minutes"` 重新產生網頁版（`--render-only` 會自動接著產生，不必再執行） |
| §6 後續 | 「把網頁版傳給別人」：說明時間碼播放要原始檔與 `_minutes` 資料夾一起給（相對路徑，§5.2）；只傳 `.html` 時時間碼會是文字 |
| 疑難排解 | 加：網頁版時間碼不能點（原始檔不在 `_minutes` 的上一層、格式不能播 → `render_html.py --media <檔案>`）；網頁版內容和 `.md` 不一樣（改過 `.md` 後沒重新產生）；不要網頁版（`config.json` 的 `html.enabled: false`） |
| 版本註解、description | 2.1.0；description 加「會議記錄與筆記的網頁版（時間碼可點播放）」 |

`references/minutes-template.md`、`references/content-types.md`：各加一句「網頁版由程式從本檔轉出；請維持標題、表頭與時間碼的寫法，網頁版的目錄、摘要卡與時間碼才會正確」。

實作結果：
- 第 11 點另加一句「你不手寫 HTML」；§7.3 寫進 §4.2 的新條目（指令、exit code、`--media`／`--no-media`／`--theme`、不必先問使用者）。§2.1 另加一條：`minutes.html` 各欄位與 `media` 值的意思、網頁版失敗不影響 `.md` 與 exit code。
- 疑難排解多兩列：「網頁版沒產生」（依 `html.reason` 分）、「不要網頁版」另寫 `html.media: off`（只不要播放器）。
- `minutes-template.md` 本身是範本，句子加在檔尾（`<!-- 以下是寫法說明，不要寫進會議記錄 -->` 之後），避免被抄進會議記錄的第一行（SKILL 依第一行「> 自動整理：…」判斷表頭）；`content-types.md` 加在開頭的說明區塊。

### 7.3 對話中寫會議記錄（本機模式，Claude 自己寫 `.md` 時）

Claude 在對話中寫完或修改 `meeting-minutes.md`／`notes.md`，存到輸出資料夾之後，執行 `render_html.py`（§7.2 §4.2）。Claude **不手寫 HTML**：網頁版只由 `render_html.py` 產生，版面與跳脫規則才一致。

### 7.4 Claude App 模式（沙盒）

- upload zip 內附 `meeting-minutes-pro/scripts/render_html.py` 與 `html_template.html`（打包時從 runtime 複製，§1；標準函式庫即可執行）。
- 使用者要網頁版時（或 Claude 寫完會議記錄後問一句「要不要順便產生網頁版？」〔規格決定：App 模式要多一個檔案下載，問一次；本機模式預設產生不問〕）：
  1. 把會議記錄存成沙盒裡的 `meeting-minutes.md`（或 `notes.md`）。
  2. 執行 `python <skill 目錄>/scripts/render_html.py --md meeting-minutes.md --out meeting-minutes.html`。
  3. 把 `meeting-minutes.html` 當成檔案交給使用者，並說明：沙盒裡沒有原始錄音，所以時間碼是文字；要點了播放，請在本機把 `.md` 放回 `<檔名>_minutes` 資料夾後執行 `render_html.py`。
- 沙盒不能執行 Python 時：**不要手寫 HTML 代替**（版面、跳脫、CSP 都可能不一致），告訴使用者在本機執行 `render_html.py`。
- 不發布成 Artifact〔規格決定〕：Artifact 是託管在 claude.ai 的頁面，不是使用者手上的離線檔案；只有使用者明確要求「做成 Artifact」時，才把同一份 HTML 發布（播放器在 Artifact 裡沒有媒體，時間碼同樣是文字）。
- 實作結果：SKILL.md 把本節寫在 §0〈逐字稿模式（Claude App 沙盒）的網頁版（2.1）〉（App 模式的其他說明也在 §0）；指令寫 `python <本 skill 目錄>/scripts/render_html.py --md meeting-minutes.md --out meeting-minutes.html`（App 的 skill 安裝路徑不固定，不寫死）。
  skill 內的 `scripts/` 兩檔由 `tools/make_dist.py --sync-skill` 從 runtime 複製並重產 payload zip（H-13）。在沒有 `common.py` 的暫存目錄以 `python -I` 執行 skill 內的 `render_html.py --md`：exit 0、頁尾版號 2.1.0（`FALLBACK_VERSION`）、`media: none`（附錄 B）。

---

## 8. 隱私與安全

### 8.1 沒有外部請求

1. **結構上**：樣板沒有 `<link>`、外部 `<script src>`、`<img>`、`@font-face`、`@import`、`url(…)`；轉換器不產生 `<img>`、`<iframe>`、`<object>`、`<embed>`、`<form>`、`<base>`；外部連結不做成 `<a>`（§3.2）。
   唯一的 `src` 是媒體的相對路徑（§5.2）。
2. **CSP**（`<meta http-equiv="Content-Security-Policy">`）：
   `default-src 'none'; style-src 'sha256-<樣板 style 雜湊>'; script-src 'sha256-<樣板 script 雜湊>'; media-src 'self' file:; img-src 'none'; base-uri 'none'; form-action 'none'`。
   雜湊由 `render_html` 對樣板 `<style>`／`<script>` 標籤之間的**完整內容**（含開頭換行）計算（SHA-256、base64）。這樣即使轉換器有漏洞讓內容混進 `<script>` 或外部資源，瀏覽器也不會執行或載入。
   〔規格確認〕Chrome 以 `file://` 開啟時樣式、程式、媒體都正常，console 沒有 CSP 違規（附錄 A.2）。
3. `<meta name="referrer" content="no-referrer">`；`localStorage` 只存主題（不是網路請求）。

### 8.2 跳脫

- 所有來自 `.md` 的文字一律 `html.escape(…, quote=True)` 後才組成 HTML；屬性值（`id`、`href`、`data-t`、`src`、`aria-label`）只由程式產生，同樣跳脫。
- 放行的 HTML 只有 §3.2 的 `<details><summary>…</summary>`／`</details>` 兩種整行寫法，而且 summary 文字是跳脫後輸出。
- 樣板替換一次完成（§4.1），`.md` 裡的 `{{BODY}}` 之類文字照字面顯示。
- 〔規格確認〕注入測試（附錄 A.3）：`<script>`、`<img onerror>`、`<iframe src="https://…">`、`<svg onload>`、`javascript:` 連結、屬性跳出（`" onmouseover="`）、程式碼區塊裡的 `</pre><script>`、`{{BODY}}`——輸出中沒有任何真正的標籤或事件屬性。

### 8.3 媒體與路徑

- 只寫相對路徑；不寫絕對路徑、使用者名稱、`file://`（§5.2）。頁尾不寫路徑（§4.6）。`run_log` 不記媒體檔名（§6.4）。
- 網頁版**內含**整份會議記錄內容（與 `.md` 相同的敏感程度）；README 與 SKILL 說明轉寄時的注意事項同 `.md`。

---

## 9. 測試計畫

### 9.1 單元測試（`tests/test_render_html.py`，新）

| # | 案例 | 預期 |
|---|---|---|
| H-1 | 7 種類型各一份 `.md`：會議用 2.0.2 `render_markdown()`、其他 6 種用 `render_notes()`，資料取 `tests/` 既有的合成固定資料（不呼叫模型）；另加 1 份 `base: meeting` 自訂範本（`labels` 改節名） | 每份：h2／h3 數＝目錄項數；每個目錄 `href` 都指得到 id；id 不重複；時間碼數＝`.md` 裡 `HH:MM:SS` 數（扣頭首）；會議有 3 張摘要卡且項數＝表格列數；自訂範本的節名出現在目錄 |
| H-2 | 子集逐項（§3.2 表的每一列）＋不完整寫法（沒有分隔列、欄數不符、沒有 `</details>`） | 輸出符合表；不丟例外 |
| H-3 | 注入（§8.2 的清單，＋`{{CSP}}`、超長 summary、`<details>` 寫在行中） | 輸出中 `<script` 只有樣板那一個；沒有 `on\w+=` 屬性；`href` 只有 `#…` 與相對路徑；`src` 只有媒體 |
| H-4 | 錨點：§3.4 表的 4 例、重複標題、全是標點的標題、超過 60 字 | id 符合；重複加 `-2`；空的變 `h-sec` |
| H-5 | 時間碼：範圍內、超過長度＋60 秒、`MM:SS`、`12:34:567`、`1:02:03`、頁首「長度」 | 只有合格的變成時間碼；`1:02:03` 顯示 `01:02:03`；頁首不轉 |
| H-6 | 媒體定位（暫存目錄）：① ② ③、大小寫副檔名、`--media`、`--no-media`、`html.media: off`、只有 `.wma`、`.mkv` 與 `.mp4` 同時存在、中文與空白檔名、`--out-dir` 在別處 | `media` 狀態與 `src` 相對路徑正確（中文與空白經 percent-encoding）；同時有能播與不能播時選能播的 |
| H-7 | 外部請求 0（§9.3 的檢查函式）對 H-1～H-6 的每一份輸出 | 全部通過 |
| H-8 | `auto_minutes` 整合（假呼叫器，沿用 `test_auto_minutes.py` 的做法）：`ok`、`partial`、`--no-html`、`html.enabled: false`、`--render-only`、`render_html` 丟例外、樣板不存在、輸出資料夾唯讀 | `.md` 照常寫入；`status`／exit code 不受網頁版影響；stdout 與 `auto_minutes.json` 的 `html` 正確；失敗時 console 一行提示 |
| H-9 | `render_html.py` CLI：exit 0／1／2 各情境；`--md` 模式不寫 log | 符合 §2.3 |
| H-10 | `run_log`：checkpoint 欄位齊全、不含 `.md` 內容 6 字片段與媒體檔名 | 通過（`test_runlog.py` 擴充） |
| H-11 | `upgrade_config()`：沒有 `html`、只有部分鍵、值不認得 | 補齊；不認得的值用預設並印提示 |
| H-12 | CSP 雜湊：對輸出重新計算 `<style>`／`<script>` 內容的 SHA-256 | 與 CSP 裡的值相同（樣板改了沒重算會被抓到） |
| H-13 | `make_dist`：skill 內的 `render_html.py`／樣板與 runtime 逐位元相同；`FALLBACK_VERSION`＝`common.VERSION` | 不同 → exit 2 |

實作結果：H-13 在 `tests/test_make_dist.py`（`SkillScriptsCheck` 9 項、`RealHtmlVersionDir` 1 項）。檢查只對 runtime 有 `render_html.py` 的 Pro 版本目錄（2.1.0 起）；基本版與 2.0.x 以前不查。
`make_dist.py --sync-skill`：複製兩檔到 `skill/meeting-minutes-pro/scripts/`、重產 `payload/meeting-minutes-pro-upload.zip`（依路徑排序、不含 `__pycache__`），複製後同樣跑 H-13（`FALLBACK_VERSION` 不一致照樣 exit 2），不產生 `dist/`。

### 9.2 瀏覽器實測（實作時，Windows 本機 Chrome；Edge 抽查）

用 H-1 的會議與課程輸出＋合成媒體（M1 錄音、TU1 影片；音檔由 `tests/` 的講稿重建）：

1. 1440px 與 375px、深色與淺色：目錄、scrollspy（捲到 3 個位置確認目前章節）、手機目錄展開與點選後收合、Esc 收合；`scrollWidth == clientWidth`（沒有水平捲動）。
2. 時間碼：點 3 個不同時間碼，`currentTime` 在該秒 ±1.5 秒內、開始播放；鍵盤 Tab 到時間碼按 Enter 同樣有效。
3. 退回：媒體搬走、`.wma`、沒有媒體三種，確認沒有播放器、時間碼是文字、console 沒有錯誤。
4. 外部請求：DevTools Network（或 `performance.getEntriesByType('resource')`）只有 `.html` 本身與媒體；console 沒有 CSP 違規。
5. 列印預覽：目錄與播放列不印、〈轉寫品質備註〉展開。
6. macOS（Safari）：沒有實機時記錄為未驗，靠 §5.4 的執行時退回兜底〔推論〕。

### 9.3 外部請求 0 的自動檢查（`tests/test_render_html.py` 的共用函式）

對輸出 HTML：

- 不得出現：`<link`、`<iframe`、`<object`、`<embed`、`<img`、`<base`、`<form`、`@import`、`url(`、`srcset=`、`poster=`。
- 所有 `src="…"`、`href="…"` 的值：`#` 開頭，或不含 scheme（`^[a-zA-Z][a-zA-Z0-9+.-]*:`）且不以 `//` 開頭。`src` 只能出現在 `<audio>`／`<video>`。
- 有 CSP meta，且含 `default-src 'none'`。
- 不含 `http://`、`https://` 的**標籤屬性**（文字內容裡的網址允許，例如使用者在 `.md` 裡寫了網址）。

撰寫規格時對兩份合成素材的網頁版以 `grep -nE 'https?://|//fonts|<link|src="http|@import|url\('` 檢查 0 筆（附錄 A.1）；正式測試用上列較完整的規則。

### 9.4 回歸

- 2.0.2 既有單元測試全過（網頁版只新增，不改 `.md` 輸出：`meeting-minutes.md`／`notes.md` 與 2.0.2 逐位元相同，以 H-1 的固定資料比對）。
- `entry_harness.py`：結束畫面多一列 `.html`；三種殼層全過。實作結果：見附錄 B。

---

## 10. （開發用的工作拆分，公開版省略）

原規格本節是實作工作的拆分與排程，屬開發流程，公開版不收；章節號保留，§11 的編號不變。

---

## 11. 後續候選（2.1.0 不做）

| 候選 | 說明 | 要先決定的事 |
|---|---|---|
| 逐字稿網頁版 | `transcript.corrected.md` → `transcript.html`：每段的時間碼可點播放、`{原文→修正}` 與 `[?…]` 標示成可切換的樣式 | 標記的顯示方式（只看修正後／對照）；長逐字稿（3 小時、上千段）的目錄與效能 |
| 基本版網頁版 | 基本版 `meeting-minutes` 也產生網頁版 | 基本版沒有 runtime 程式（只有 SKILL），要由 Claude 在對話中執行附帶的 `render_html.py`，與 §7.4 相同做法 |
| 關鍵畫面縮圖 | 操作教學的步驟旁顯示 `frames/` 截圖 | CSP 要放行 `img-src 'self' file:`；圖片相對路徑、隱私（截圖可能有畫面上的個資） |
| Mermaid 畫圖 | 對話中寫的流程圖顯示成圖 | 需要內嵌 Mermaid 程式庫（約 3 MB）或本機預先轉 SVG |
| 外部連結可點 | 使用者手寫的 `https://` 連結做成 `<a>`（`rel="noopener noreferrer"`） | 與「外部請求 0」檢查的界線（連結不是請求，但要放寬 §9.3 的規則） |
| 自動開啟網頁版 | 入口結束時用預設瀏覽器開 `.html` | 加設定鍵；遠端與測試環境要關 |

---

## 附錄 A：撰寫規格時的瀏覽器實測（〔規格確認〕）

以合成素材（`tests/materials/` 的自寫、虛構講稿）產生兩份網頁版：會議（M1，**時間碼可點播放**，媒體為 M1 合成語音轉成的 MP3）與課程筆記（CL1，**沒有媒體 → 純文字時間碼**）。

### A.1 產生結果與外部請求檢查

| 網頁版 | bytes | 標題（id） | 時間碼 | 媒體 | 跳脫的 HTML |
|---|---|---|---|---|---|
| 會議 | 38,689 | 15 | 29（按鈕） | `explicit` `.mp3` | 0 |
| 課程筆記 | 40,084 | 17 | 32（純文字） | `none` | 0 |

- `grep -nE 'https?://|//fonts|<link|src="http|@import|url\('` 對兩份輸出與樣板 → **0 筆**。
- 所有 `href` 都是 `#h-…`；唯一的 `src` 是媒體的相對路徑。CSP meta 含 `default-src 'none'`。

### A.2 瀏覽器實測（Windows、Chrome，`file://` 直接開）

| 項目 | 結果 |
|---|---|
| 1440px 深色 | 左側目錄展開；捲到〈決議事項〉時目錄標示該項（`aria-current`）；摘要卡 5／11／2 |
| 1440px 淺色 | 切換鈕 → `data-theme="light"`、按鈕改「改成深色」；重新整理後保留（`localStorage`） |
| 375px | `scrollWidth == clientWidth == 375`（沒有水平捲動）；目錄收合成頂端列，點開後列出 h2／h3 |
| 時間碼點播 | 點 `00:04:58`（`data-t=298`）→ 1.5 秒後 `currentTime` 299.4、播放中、播放列顯示「從 00:04:58 播放」、該按鈕 `.is-last` |
| 頁首「長度」 | 試作第一版做成了播放按鈕 → 改成文字（§4.3） |
| 課程（沒有媒體） | 沒有播放列；32 個 `<time class="tc-text">`；沒有摘要卡；375px 無水平捲動 |
| 外部請求 | 只有 `.html` 與媒體（另有 Chrome 內建播放器圖示的 `data:` URI，不是頁面發出的）；`performance.getEntriesByType('resource')` 0 筆；console 0 則（含 CSP 違規 0） |
| 媒體定位 | a：`M1_minutes/../M1.wav` → `found .wav`、`src="../M1.wav"`，點 `00:02:14` → `currentTime` 135.1；b：只有 `../M1.mp3` → ③ 找到；c：只有 `../M1.wma` → `unsupported`、頁首說明；d：沒有媒體 → `none` |
| 執行時退回 | 把 a 的 `_minutes` 資料夾單獨搬走後開啟 → 播放列 `hidden`、時間碼全部換成文字、console 0 則 |
| 影片（TU1） | 桌機右下小窗、手機底部滿寬；點時間碼可播。試作第一版的根元素 class 與影片小窗元件同名，小窗樣式套到 `<html>` 讓版面縮成 19px 寬 → 實作時根元素 class 不得與元件 class 同名 |

### A.3 注入測試

輸入含 `<script>alert(1)</script>`（標題）、`<img src=x onerror=…>`（節標題）、`<iframe src="https://evil.example/">`、`{{BODY}}`、`[壞連結](javascript:alert(3))`、`[外部](https://example.com/…)`、表格裡的 `" onmouseover="…`、mermaid 區塊裡的 `</pre><script>…`、`<details>` 內的 `<svg onload=…>`：
輸出中內容區的 `<script` 0、`<img|iframe|svg` 0、事件屬性 0；`href` 只有 `#…`；`src` 0；`{{BODY}}` 照字面顯示（替換一次完成）。

---

## 附錄 B：實作與驗收結果（2.1.0）

### B.1 對應檔案

| 項目 | 檔案（`V/`＝`pro/meeting-minutes-pro-v2.1.0/`） |
|---|---|
| 轉換器與樣板 | `V/payload/runtime/scripts/render_html.py`、`html_template.html` |
| 整理後接著產生、`--no-html` | `V/payload/runtime/scripts/auto_minutes.py` |
| 版號、`html` 預設值、升級補鍵 | `V/payload/runtime/scripts/common.py` |
| 階段名「網頁版」 | `V/payload/runtime/scripts/runlog.py` |
| 入口結束畫面（§7.1） | `V/payload/runtime/mm-sendto.ps1`、`V/payload/runtime/mm-dropped.sh` |
| SKILL、references（§7.2～§7.4） | `V/payload/skill/meeting-minutes-pro/SKILL.md`、`references/minutes-template.md`、`references/content-types.md` |
| skill 內 `scripts/` 兩檔（打包複製） | `V/payload/skill/meeting-minutes-pro/scripts/{render_html.py,html_template.html}`（`tools/make_dist.py --sync-skill`） |
| README | `V/README.md`（功能第 13 點、〈2.1.0 新功能：網頁版〉、第 13 節網頁版、輸出檔、設定鍵 `html.*`、疑難排解、附錄 macOS Safari 未實測） |
| 測試 | `tests/test_render_html.py`（H-1～H-12）、`tests/test_make_dist.py`（H-13）、`tests/entry_harness.py` |

### B.2 測試

- 單元測試：2.1.0 `Ran 447 tests` OK（略過 5）；同一套測試對 2.0.2 也全過（2.1.0 才有的項目略過）。
- 入口測試（`entry_harness.py`，PowerShell 7／5.1／Git Bash）：2.1.0 **117/117**（39 情境 × 3 殼層），其中網頁版 11 情境：`html_found`、`html_explicit`（時間碼可點播放）、`html_text_none`／`_unsupported`／`_off`（時間碼為文字）、`html_course`（`notes.html`）、`html_disabled`、`html_failed`、`html_failed_internal`、`html_minutes_no`、`upgraded_202`。1.x／2.0.x 升級情境的結束畫面＝2.0.2 的清單多 `meeting-minutes.html` 一列；呼叫的程式、參數與題目和 2.0.2 相同。
- 沙盒：skill 內的 `render_html.py` 單獨放在沒有 `common.py` 的暫存目錄，`python -I … --md meeting-minutes.md --out meeting-minutes.html` → exit 0、`media: none`、頁尾版號 2.1.0（`FALLBACK_VERSION`）。
- 發行前的本機升級實測（Windows，2.0.2 → 2.1.0，合成素材 M1）：安裝畫面「升級中：2.0.2 → 2.1.0」、`config.json` 補上 `html` 區塊、既有設定與使用者詞表不變；入口做會議摘要後結束畫面列出 `meeting-minutes.html`，Chrome 開啟後目錄正確、點 3 個時間碼與鍵盤 Enter 都跳到該秒播放、console 0 則。

### B.3 2.1.0 修正：載入訊息印實際的模型名

- `transcribe.py` 的載入訊息原本不論模型都印「Whisper 載入：{後端} / {裝置}」，失敗時印「無法以 {後端}/{裝置} 載入 Whisper」；選 Breeze 時實際載入的是 Breeze-ASR-25（`run_log` 的 `asr_model: breeze` 正確），只有 console 訊息寫錯。
- 2.1.0 改印實際模型的顯示名稱，後端與裝置照舊附在後面。顯示名稱由 `transcribe.ASR_DISPLAY` 對照 config 的 `whisper` 值：

  | config `whisper` | 顯示名稱 |
  |---|---|
  | `breeze` | Breeze-ASR-25 |
  | `turbo` | Whisper large-v3-turbo |
  | `large-v3` | Whisper large-v3 |
  | `base` | Whisper base |
  | 其他值（例如 `--whisper` 直接給 Hugging Face repo） | Whisper ＋原值 |

  例：「  Breeze-ASR-25 載入：ct2 / cuda（3.2s）」、「無法以 openvino/GPU 載入 Breeze-ASR-25：…」、「  Whisper large-v3-turbo 載入：openvino / NPU（2.1s）」。
- Whisper 印完整模型名而不是別名：別名 `turbo` 單獨出現看不出是哪個模型；`large-v3-turbo` 是三個後端模型 repo 共同的名稱，對照 README 或 Hugging Face 都找得到。
- 其他行為不變：`run_log` 的 `asr_model`、輸出檔表頭的 `ASR：{model}`、`backends.create()` 的錯誤文字都照舊。測試：`tests/test_asr_message.py`（7 項；假的 `backends` 模組，不載入真模型）。

### B.4 已知限制

- 網頁版只在 Windows 的 Chrome（Edge 抽查）實測；**macOS（Safari）沒有實機驗證**，靠 §5.4 的執行時退回兜底〔推論〕。
