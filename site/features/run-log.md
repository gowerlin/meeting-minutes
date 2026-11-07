---
title: 執行 log 與費用
description: 每次轉寫記下什麼、怎麼看彙整表、API 等價費用怎麼算，以及價格表怎麼更新。
---

# 執行 log 與費用

**這頁幫你做到**：知道一場會議實際花了多少時間、用了多少 token、換算成 API 大約多少錢。

## 每次記下什麼

| 檔案 | 內容 |
|---|---|
| `<檔名>_minutes/run_log.jsonl` | 這一場的明細：每個步驟（轉換音訊、截圖、說話者分離、語音辨識、分段標點、AI 校正與會議摘要的每一段）的開始、結束時間與耗時；每一次模型呼叫的供應商、模型、推理強度、token 與 API 等價費用；入口每一題等你回答的時間另外記 |
| runtime 資料夾的 `logs/runs.jsonl` | 每次一列摘要：總處理時間、各步驟時間、總 token、總費用、錄音長度、講者數、每小時錄音的費用，方便跨場次比較 |

**不記**：逐字稿文字、內容片段、金鑰、帳號資訊。只有檔名、數字、狀態與模型名稱。

每個事件都帶程式版號，模型呼叫另記 `claude`／`codex` 指令的版號，方便日後比較不同版本。

## 彙整成表

```powershell
& "$MMH\venv\Scripts\python.exe" "$MMH\scripts\runlog.py" summary     # Windows
```

```bash
"$MMH/venv/bin/python" "$MMH/scripts/runlog.py" summary               # macOS
```

輸出長這樣（數字是範例）：

```text
日期              來源    錄音     處理  轉寫  校正  摘要  等待  呼叫  token(入/出)   費用US$  每小時錄音US$  處理/錄音
2026-11-06 17:28  M1.wav  9:39     2:11  —     1:06  1:05  —     2     19,587/6,134   0.096    0.596          0.23

共 1 次、錄音 0.16 小時、處理 2:11、API 等價 US$0.096（每小時錄音 US$0.596）；訂閱通道是等價估算，不另計費
```

- `--last 10`：只列最後 10 次。
- `--csv runs.csv`：另存成 Excel 可以直接開的 CSV。
- 「分離」欄寫這次用的說話者分離引擎（`pyannote`／`sherpa`／`略過`；GPU 失敗改用 CPU 時是 `sherpa*`）。

## API 等價費用怎麼算

**token 數 × 價格表**。價格表是程式內附的 `scripts/pricing.json`，寫明來源與日期，單位是每百萬 token 的美元。

| 你用的通道 | log 裡的標示 | 實際會不會收費 |
|---|---|---|
| 訂閱（`claude`／`codex` 指令，以訂閱帳號登入） | 等價估算，不另計費 | 不另外收費，但會用掉方案額度 |
| API 金鑰（或 Codex 以 API 金鑰登入） | 依 API 用量計費（估算） | 會依用量收費，以供應商的帳單為準 |

Claude 的計算值和 Claude Code 自己回報的費用一致。log 的費用和實際帳單不同時，多半是價格表過時了。

## 價格表更新

價格變了或要加新模型時，在 runtime 資料夾建立 `pricing.json`，**只寫要改的項目**，同名項目會蓋過內建值（重新安裝不會覆蓋這個檔）：

```json
{"updated": "2027-01-01", "models": {"openai:gpt-6.1-sol": {"input": 1.5, "output": 8.0},
                                     "openai:gpt-7": {"ids": ["gpt-7"], "input": 3.0, "output": 12.0, "cache_read": 0.3}}}
```

欄位有 `input`、`output`、`cache_read`、`cache_write_5m`、`cache_write_1h`（上面的價格只是格式範例）。
