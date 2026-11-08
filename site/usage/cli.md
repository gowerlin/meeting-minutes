---
title: Claude CLI／Code 分頁
description: 在 Claude Code（終端機或 Claude 桌面版的 Code 分頁）裡，怎麼請 Claude 轉寫並整理會議記錄、常用說法。
---

# Claude CLI／Code 分頁

**這頁幫你做到**：用一句話請 Claude 從轉寫到會議記錄全部做完。

適用：Claude Code（終端機裡的 `claude` 指令），以及 Claude 桌面版的「Code」分頁。安裝時要選 [1] 或 [3]。

## 怎麼說

直接跟 Claude 說，例如：

```text
用 meeting-minutes-pro 整理 D:\會議\2026-10-12 示範專案週會.mp4，與會 4 人：王小明、李小華、陳大文、客戶窗口。這是技術會議，中英夾雜很多
```

macOS 的路徑寫法例如 `~/Documents/會議/0912.m4a`。

Claude 會依序：

1. 在你的電腦上轉寫（技術會議會建議改用 Breeze）。
2. 讀逐字稿與影片截圖（有 `reference.json` 時用它的整理結果），把 S1、S2 對應到與會者姓名。
3. 校正字詞，產出 `transcript.corrected.md` 與 `meeting-minutes.md`。
4. 列出建議加進[對照表](/features/accuracy#固定錯誤對照表)的項目，請你確認後才寫入。

::: warning 逐字稿會送到雲端
第 1 步在你的電腦上做，音檔不會送出；第 2、3 步 Claude 讀到的逐字稿與截圖，會送到 Anthropic 的雲端由 Claude 處理。對話中沒有「要送出嗎？」這一步，有機敏內容時請不要在對話中讀逐字稿。
:::

## 給的資訊越多越準

| 你提供 | 幫助 |
|---|---|
| 與會人數 | 說話者分離更準（見[講者人數](/features/diarization)） |
| 與會者姓名與角色 | Claude 比較能把 S1、S2 對應到正確的人 |
| 會議性質（「技術會議」「中英夾雜」「課程」） | Claude 會決定要不要用 Breeze、選哪一種[內容類型](/features/content-types) |
| 會出現的專有名詞 | 辨識與校正都會更準 |

## 常用說法

| 你說 | Claude 做 |
|---|---|
| 「用 sonnet 自動校正」「用 GPT 校正」 | 這次指定 AI 校正的模型或供應商 |
| 「這次不要自動校正」 | 這次跳過自動校正，改在對話中校正 |
| 「這是課程，整理成課程筆記」 | 用課程類型整理 |
| 「S5、S6 是 S2」 | 合併被分錯的講者 |
| 「用 meeting-minutes-pro 檢查這份會議記錄」（附上檔案） | 把既有的會議記錄當草稿查證、補講者姓名，不從頭重寫 |

## 和自動校正的分工

| 有沒有自動校正版 | 對話中 Claude 做什麼 |
|---|---|
| 有（安裝時開啟了自動校正，或這次有指定） | 只處理待確認的地方、講者對應、從截圖或與會者資訊發現的新錯誤，然後寫會議記錄；不重做全文校正 |
| 沒有 | 讀 `transcript.md`，在對話中完成全文校正 |

自動校正的開關在安裝時決定，之後要改就重新執行安裝程式加 `-Correct`／`-NoCorrect`（macOS：`--correct`／`--no-correct`）。

::: tip 同時裝了基本版
用名稱指定比較明確，例如「用 meeting-minutes-pro 整理…」。提到校正版逐字稿、Breeze 或對照表時，Claude 會選 Pro 版。
:::
