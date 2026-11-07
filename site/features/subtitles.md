---
title: 字幕
description: 三個字幕檔的差別、字幕規則（每行字數、時長）、待確認的字在字幕裡怎麼顯示，以及已知限制。
---

# 字幕

**這頁幫你做到**：知道輸出資料夾裡三個 `.srt` 字幕檔的差別，挑對要用的那一個。

`.srt` 是最常見的字幕格式，大多數影片播放器（例如 VLC、PotPlayer）與剪輯軟體都能直接讀。

## 三個字幕檔

| 檔案 | 內容 | 什麼時候產生 |
|---|---|---|
| `transcript.srt` | 辨識結果原樣，一段一條 | 每次轉寫 |
| `transcript.cues.srt` | 同樣的文字（已做繁體轉換、對照表替換、標點），**不經 AI**，照字幕規則重新切條 | 每次轉寫 |
| `transcript.corrected.srt` | **AI 校正後**的文字，對回原本的時間軸再切條 | 有做 AI 校正時 |

- 要給人看：用 `transcript.corrected.srt`（有校正時）或 `transcript.cues.srt`。
- `transcript.srt` 一段可能很長，比較適合拿來對照時間。

結束畫面會列出條數，例如：

```text
transcript.cues.srt 字幕（依字幕規則切條，不經 AI）（133 條）
transcript.corrected.srt 校正版字幕（133 條，對應失敗 0 段）
```

## 字幕規則

參考 Netflix 繁體中文字幕規範（Timed Text Style Guide）：

| 規則 | 值 |
|---|---|
| 每行最多 | 16 字 |
| 每條最多 | 2 行 |
| 每條長度 | 5/6 秒～7 秒 |
| 閱讀速度 | 每秒最多 9 字（只檢查，不強制） |
| 行尾 | 不留「，、。」 |
| 講者 | 換人時在字幕前加講者（可改成每條都加或都不加） |

## 待確認的字

AI 校正拿不準的地方會標成待確認。在字幕裡預設顯示**原文**，也可以改成顯示推測，或兩者都顯示（適合給人校稿）。設定鍵是 `config.json` 的 `subtitles.uncertain`：`orig`（原文，預設）、`guess`（推測）、`mark`（原文〔?推測〕）。

## 在 Claude 裡補校之後

在 Claude 對話中改過校正版逐字稿後，重新產生校正版字幕（Claude CLI 模式會自動做）：

```powershell
& "$MMH\venv\Scripts\python.exe" "$MMH\scripts\subtitles.py" "<檔名>_minutes" --corrected
```

對不回時間軸的段落會用原文，結束畫面寫「對應失敗 N 段」。

## 已知限制

- 一段裡面切開的時間點是**依字數估算**的；略過說話者分離或操作示範時誤差比較大。合成素材上，開說話者分離時段首誤差的中位數約 0.1 秒，略過時約 0.8 秒。
- 沒有標點的長句，可能切在詞的中間。
- 講者標籤不算進每行字數。
- 操作示範類的錄音，有些條會超過 7 秒（合成素材上約 3 成）。
- Claude 桌面 App 中沒辦法產生字幕（字幕在你的電腦上產生）。

不要產生某個字幕檔：`config.json` 的 `subtitles.cues_srt` 或 `subtitles.corrected_srt` 設成 `false`；單次轉寫可以加 `--no-cues`。
