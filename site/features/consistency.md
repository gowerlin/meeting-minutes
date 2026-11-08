---
title: 全文用字統一
description: 同一個英文名詞只差大小寫或空格的寫法，在校正版、字幕與會議記錄統一成一種（2.2）；本機處理，不呼叫模型、不送任何資料。
---

# 全文用字統一

**這頁幫你做到**：讓同一個名詞在整份校正版逐字稿與會議記錄裡只有一種寫法。

AI 校正是一段一段處理的，同一個名詞在各段常常寫成不同的大小寫與空格，例如 `NotebookLM` 之外還有 `notebooklm`、`notebookLM`、`notebook lm`，會議記錄也跟著不一致。2.2 起，程式在你的電腦上把同一個名詞統一成一種寫法：

- **在本機處理**：**不呼叫模型、不送任何資料**、不花費用。
- **預設開啟**：做 AI 校正或會議摘要時自動進行，入口不多問題目。

## 統一什麼

英文（含數字）名詞的寫法變體：只差大小寫，或字母旁有沒有空格、`.`、`-`。

| 會被統一成一種 | 不會合併 |
|---|---|
| `NotebookLM`、`notebooklm`、`notebook lm`、`Notebook-LM`、`notebook.lm` | `Notebook` 與 `NotebookLM`（兩個不同的名詞） |
| `GPT-4`、`GPT4` | `1.5` 與 `15`（數字之間的 `.` 保留） |

中文的同義異寫（「大語言模型」／「大型語言模型」）不處理。

## 標準寫法怎麼決定

依序取：

1. **你提供的寫法**：`glossary.txt` ＞ `corrections.tsv` 的正確寫法 ＞ [背景說明與會議文件](/features/reference)裡的名詞 ＞ `reference.json` 的名詞。
2. **這次 AI 校正名詞階段的用字表**（長會議分段校正時才有）。
3. **全文出現最多、而且寫法有特徵的寫法**：字中有大寫（`NotebookLM`、`iPhone`），或 2 個字母以上的全大寫縮寫（`AI`、`PDF`）。標準寫法至少要出現 2 次、整組至少 3 次才統一；同票時取分隔少的，再來取先出現的。全部小寫、或都沒有特徵時不統一（沒有依據判斷哪個對）。

想固定某個名詞的寫法，把它寫進[專有名詞清單](/features/accuracy#專有名詞清單) `glossary.txt` 就會優先採用。

## 不會改的地方

- **一般英文單字只差大小寫**：`apple`／`Apple`、`go`／`Go`、`app`、`it`／`IT`、`ok` 不改（程式內建約 350 個常用英文字）。
- **全小寫的一般片語**：`single file` 不會被併成 `SingleFile`。
- **網址、網域、檔名、路徑、信箱、程式碼**：`https://…`、`notebooklm.google.com`、`notes.md`、`C:/…`、`` `…` `` 整段不改；緊鄰 `_`、`/`、`#` 這類符號的英文詞（`notebooklm_id`、`#tag`、`--pdf`）也不改。
- **標準寫法沒有特徵時**（例你在 `glossary.txt` 寫 `Redis Sentinel`）：只統一分隔（`Redis-Sentinel` → `Redis Sentinel`），不改大小寫。

## 改在哪裡

| 檔案 | 怎麼改 |
|---|---|
| `transcript.corrected.md` | 統一處用 `{原文→統一}` 標出（例 `{notebook lm→NotebookLM}`），和 AI 的修改同一種標記；〈校正摘要〉表格下加一行「全文用字統一（本機處理，未呼叫模型）：N 組、M 處…」 |
| `transcript.corrected.srt` | 跟著校正版產生，時間碼不變 |
| `meeting-minutes.md`、`notes.md` 與網頁版 | 直接用統一後的寫法（`>` 開頭的說明行不改） |
| `transcript.md`、`transcript.srt`、`transcript.cues.srt` | **不改**（原始逐字稿永遠保持原樣） |

- 統一**不算進**校正摘要的「修改 N 處」，也**不會**寫進[對照表建議](/features/accuracy#固定錯誤對照表)：大小寫不同不是固定的誤辨識，寫進對照表會在轉寫時連一般單字一起換掉。
- 完成時畫面印一行，例 `用字統一：3 組、18 處（NotebookLM、PDF、GitHub；本機處理）`；沒有要統一的就不印。
- `run_log.jsonl`、`auto_*.json` 只記組數與處數，不記名詞。

## 已經有的輸出資料夾

2.2 以前的結果，或在對話中手改過之後，可以單獨執行：

```powershell
& "$MMH\venv\Scripts\python.exe" "$MMH\scripts\consistency.py" "<檔名>_minutes" --dry-run   # 只列出會統一的寫法，不寫檔
& "$MMH\venv\Scripts\python.exe" "$MMH\scripts\consistency.py" "<檔名>_minutes"             # 統一校正版、字幕、會議記錄或筆記
```

```bash
"$MMH/venv/bin/python" "$MMH/scripts/consistency.py" "<檔名>_minutes" --dry-run
"$MMH/venv/bin/python" "$MMH/scripts/consistency.py" "<檔名>_minutes"
```

試跑的畫面：

```text
用字統一：1 組、3 處（NotebookLM；本機處理）（試跑，沒有寫檔）
  NotebookLM ← notebooklm ×1、notebook lm ×1、notebookLM ×1
```

改過的檔會先改名備份（`<檔名>.<日期時間>.bak<副檔名>`）；有網頁版的一併重新產生。字幕直接改文字，序號與時間碼不動。

## 怎麼關

`config.json` 設 `"consistency": {"enabled": false}`。關閉時輸出與沒有這個功能時完全相同。這個步驟不送任何資料，所以沒有單次關閉的旗標。

## Claude 桌面 App

App 的沙盒不跑這支程式；Claude 整理時照同樣的規則讓全文同一個名詞用同一種寫法，校正版的統一處同樣標 `{原文→統一}`。
