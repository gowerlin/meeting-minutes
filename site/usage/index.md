---
title: 使用方式總覽
description: 三種用法比較：右鍵「傳送到」與拖放、Claude CLI／Code 分頁、Claude 桌面 App。
---

# 使用方式總覽

**這頁幫你做到**：挑一種最適合你的用法。

同一套安裝可以用三種方式。三種的轉寫都在你的電腦上進行，差別在「誰來整理成會議記錄」。

| 用法 | 怎麼開始 | 誰來整理 | 適合 |
|---|---|---|---|
| [右鍵「傳送到」與拖放](/usage/send-to) | Windows：對錄音檔按右鍵 →「傳送到」→「會議轉寫（Pro）」；macOS：把錄音檔拖到「會議轉寫（Pro）」 | 轉寫完選擇讓程式自動做 AI 校正與會議摘要；也可以之後在 Claude 裡整理 | **大多數人**：不必打字，回答幾個問題就好 |
| [Claude CLI／Code 分頁](/usage/cli) | 跟 Claude 說「用 meeting-minutes-pro 整理 …」 | Claude 在對話中從頭做到尾，最後請你確認對照表 | 已經在用 Claude Code 的人 |
| [Claude 桌面 App](/usage/claude-app) | 先用右鍵或拖放轉寫，再把逐字稿附到 App 對話裡 | Claude App（用上傳的 skill） | 平常用 Claude App 對話的人 |

想用命令列自己控制每個參數，見[手動執行與參數](/usage/advanced)。

## 一場會議的流程

<StepFlow :steps="[
  { title: '轉寫（本機）', text: '轉檔、說話者分離、語音辨識、繁體轉換、對照表替換、分段標點、截圖。' },
  { title: 'AI 校正（選用）', text: '只送逐字稿文字給 Claude 或 OpenAI，產出校正版逐字稿與對照表建議。' },
  { title: '整理（選用）', text: '會議記錄或課程、訪談等筆記，每一項附時間碼。' },
  { title: '你確認', text: '對照時間碼回聽決議與待辦；確認對照表建議，下次更準。' }
]" />

## 輸出在哪裡

錄音檔旁邊會出現一個 `<檔名>_minutes` 資料夾，例如 `0912.m4a` 的輸出在 `0912_minutes/`。主要的檔：

| 檔案 | 用途 |
|---|---|
| `transcript.md` | 閱讀用逐字稿：時間碼、講者、畫面標記。交給 Claude 的就是這個 |
| `transcript.corrected.md` | 校正版逐字稿（有做 AI 校正時） |
| `meeting-minutes.md` 或 `notes.md` | 會議記錄或筆記（有做會議摘要時） |
| `transcript.cues.srt`、`transcript.corrected.srt` | 字幕（見[字幕](/features/subtitles)） |
| `frames/` | 影片截圖，檔名裡的 `001523` 代表 00:15:23 |

完整的檔案清單見[右鍵「傳送到」與拖放 › 輸出資料夾](/usage/send-to#輸出資料夾裡有什麼)。
