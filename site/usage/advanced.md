---
title: 手動執行與參數
description: 不經入口、直接用命令列執行轉寫與 AI 步驟；常用參數、設定鍵（config.json）、安裝程式的參數與檔案位置。
---

# 手動執行與參數

**這頁幫你做到**：用命令列精確控制每一步。一般使用不需要這頁，[右鍵或拖放](/usage/send-to)就夠了。

## 檔案位置

下面用 `$MMH` 代表 runtime 資料夾：

| 項目 | Windows | macOS |
|---|---|---|
| runtime 資料夾（`$MMH`） | `%LOCALAPPDATA%\meeting-minutes-pro\` | `~/Library/Application Support/meeting-minutes-pro/` |
| Python | `$MMH\venv\Scripts\python.exe` | `$MMH/venv/bin/python` |
| 腳本 | `$MMH\scripts\` | `$MMH/scripts/` |
| 專有名詞清單 | `$MMH\glossary.txt` | `$MMH/glossary.txt` |
| 固定錯誤對照表 | `$MMH\corrections.tsv` | `$MMH/corrections.tsv` |
| OpenCC 詞彙回復表 | `$MMH\opencc_keep.tsv` | `$MMH/opencc_keep.tsv` |
| 設定 | `$MMH\config.json` | `$MMH/config.json` |
| 安裝紀錄 | `$MMH\install.log` | `$MMH/install.log` |
| 歷次執行摘要 | `$MMH\logs\runs.jsonl` | `$MMH/logs/runs.jsonl` |
| 自訂範本 | `$MMH\templates\` | `$MMH/templates/` |
| Claude CLI skill | `%USERPROFILE%\.claude\skills\meeting-minutes-pro\` | `~/.claude/skills/meeting-minutes-pro/` |

環境變數 `MEETING_MINUTES_PRO_HOME` 可以把 runtime 換到其他位置（設定後重新執行安裝程式）。

## 轉寫

```powershell
# Windows（PowerShell）
$MMH = "$env:LOCALAPPDATA\meeting-minutes-pro"
& "$MMH\venv\Scripts\python.exe" "$MMH\scripts\transcribe.py" "D:\會議\0912.m4a" --speakers 4
```

```bash
# macOS
MMH="$HOME/Library/Application Support/meeting-minutes-pro"
"$MMH/venv/bin/python" "$MMH/scripts/transcribe.py" ~/Documents/會議/0912.m4a --speakers 4
```

### 常用參數

| 參數 | 說明 |
|---|---|
| `--type <代號>`／`--template <代號>` | 內容類型（`meeting`、`course`、`interview`、`tutorial`、`panel`、`workshop`、`requirements`）／自訂範本 |
| `--speakers N` | 講者人數（實際人數）＝保留發言最多的 N 位；不確定就不要給 |
| `--no-diarize` | 不做說話者分離 |
| `--diarize-engine auto\|sherpa\|pyannote` | 這次的說話者分離引擎（`pyannote` 要先裝 GPU 版） |
| `--cluster-threshold X` | 分群門檻，數值越大判斷出的人數越少（只影響 CPU） |
| `--whisper turbo\|breeze\|large-v3` | 辨識模型（breeze 要安裝時選裝；large-v3 要先下載） |
| `--hotwords "a, b"` | 這次的專有名詞 |
| `--language zh\|en\|auto` | 語言，預設 zh（中英夾雜也用 zh） |
| `--no-keyframes`、`--scene X` | 影片不截圖；畫面變化門檻（越小截越多） |
| `--no-corrections` | 這次不套用對照表 |
| `--no-opencc`、`--no-opencc-keep` | 不做簡繁轉換；不套用 OpenCC 詞彙回復表 |
| `--no-punct`、`--paragraph-gap SEC`、`--paragraph-max-chars N` | 關閉分段標點；停頓幾秒換段（預設 2.0）；滿幾字換段（預設 200） |
| `--no-cues` | 這次不產生 `transcript.cues.srt` |
| `--correct`／`--no-correct` | 這次開／關自動校正（`--correct` 代表你同意送出逐字稿文字與[參考資料](/features/reference)） |
| `--claude`／`--openai` | 這次用 Claude／OpenAI 自動校正 |
| `--correct-model M`、`--correct-effort E`、`--correct-channel cli\|api` | 這次的模型、推理強度、通道 |
| `--context "<一行>"` | 背景說明一行，寫進 `<檔名>_minutes/context.md`（已有就覆寫，舊檔改名備份）；`auto_correct.py`、`auto_minutes.py` 也有（2.2） |
| `--refs <檔或資料夾>` | 另外加入會議文件（PDF、PPTX、DOCX、TXT、MD；可重複）；三支程式都有（2.2） |
| `--no-refs`、`--no-context`、`--no-frames` | 這次不讀會議文件、不讀背景說明、不送截圖（`--no-frames` 只有 `transcribe.py`、`auto_correct.py`；見[參考資料](/features/reference#怎麼關)）（2.2） |

## 事後補做

```bash
"$MMH/venv/bin/python" "$MMH/scripts/auto_correct.py" "<檔名>_minutes" [--correct-model sonnet] [--correct-provider openai] [--force]
"$MMH/venv/bin/python" "$MMH/scripts/auto_minutes.py" "<檔名>_minutes" [--type <代號> | --template <代號>] [--openai | --claude] [--minutes-model opus] [--force]
"$MMH/venv/bin/python" "$MMH/scripts/auto_minutes.py" "<檔名>_minutes" --render-only   # 改過 notes.json 後重新產生 notes.md
"$MMH/venv/bin/python" "$MMH/scripts/auto_minutes.py" "<檔名>_minutes" --source final --estimate-only   # 用定稿整理的費用估算（2.3，不呼叫模型、不寫檔）
"$MMH/venv/bin/python" "$MMH/scripts/subtitles.py" "<檔名>_minutes" --corrected        # 改過校正版逐字稿後重新產生字幕
"$MMH/venv/bin/python" "$MMH/scripts/render_html.py" "<檔名>_minutes"                   # 手改 .md 後重新產生網頁版（2.1）
"$MMH/venv/bin/python" "$MMH/scripts/refs.py" plan "<檔名>_minutes" [--media <原始檔>]  # 會用到的說明檔、文件、截圖張數（2.2，不呼叫模型）
"$MMH/venv/bin/python" "$MMH/scripts/refs.py" show "<檔名>_minutes"                     # reference.json 的摘要（2.2）
"$MMH/venv/bin/python" "$MMH/scripts/consistency.py" "<檔名>_minutes" [--dry-run]       # 全文用字統一（2.2，不呼叫模型）
"$MMH/venv/bin/python" "$MMH/scripts/templates.py" check                              # 檢查自訂範本
"$MMH/venv/bin/python" "$MMH/scripts/runlog.py" summary                               # 執行 log 彙整
```

已有結果時要加 `--force`，舊檔會先改名備份。

`auto_minutes.py --source` 選要依據哪一份逐字稿（2.3）：`auto`（預設：有[會議記錄校稿](/features/proofread)的定稿 `transcript.final.md` 就用它，否則校正版、再否則原稿）、`final`（只用定稿，沒有就停下）、`corrected`、`original`。定稿比校正版舊時，`auto` 會改用校正版並印一行說明。`--estimate-only` 只算這次大約要送多少字、API 等價費用的區間，不呼叫模型、不寫任何檔；正式執行完成時，結果裡另有實際費用。

## 設定鍵（`config.json`）

安裝程式只補上不存在的鍵，你改過的值會保留；`config.json` 不存任何金鑰。只寫要改的鍵即可，例如重要會議提高 Claude 的推理強度、把分段門檻放寬到 3 秒：

```json
{
  "punctuation": {"paragraph_gap": 3.0},
  "correction": {"enabled": true, "provider": "claude", "claude": {"model": "opus", "effort": "high"}}
}
```

| 鍵 | 預設 | 說明 |
|---|---|---|
| `punctuation.enabled`、`.paragraph_gap`、`.paragraph_max_chars` | `true`、`2.0`、`200` | 本機分段標點與分段門檻 |
| `opencc_keep.enabled` | `true` | OpenCC 詞彙回復表 |
| `correction.enabled` | `false` | Claude CLI 對話與命令列的自動校正（入口每次都問，不看這個值） |
| `correction.ask_default`、`minutes.ask_default` | `true` | 入口兩題按 Enter 的答案（`false`＝Enter 是「否」） |
| `correction.provider`、`minutes.provider` | `auto` | `auto`／`claude`／`openai`；`auto` 時已登入的 `codex` 優先 |
| `correction.channel`、`minutes.channel` | `cli` | `cli`（訂閱指令）／`api`（SDK＋環境變數金鑰） |
| `correction.claude.model`／`.effort` | `opus`／`medium` | AI 校正用的 Claude 模型與推理強度 |
| `correction.openai.model`／`.effort` | `gpt-6.1-sol`／`low` | AI 校正用的 OpenAI 模型與推理強度 |
| `correction.confirm_over_minutes` | `120` | 錄音超過幾分鐘時多印一行時間與費用提醒 |
| `correction.corrections_auto.mode` | `"off"` | [對照表自動寫入](/features/accuracy#對照表自動寫入-選用-預設關) |
| `minutes.chunk_chars` | `12000` | 超過這個字數就分段整理再彙整 |
| `content_type.default`、`.remember_last` | `meeting`、`true` | 預設的內容類型；入口是否記住上次的選擇 |
| `diarization.engine` | `auto` | `auto`／`sherpa`（CPU）／`pyannote`（GPU） |
| `diarization.cluster_threshold` | `0.9` | CPU 說話者分離的分群門檻 |
| `diarization.minor_speaker_note_sec` | `10` | 總發言少於幾秒標 ⚠ |
| `content_types.<代號>.cluster_threshold`／`.scene`／`.diarize_engine` | 課程 1.0；座談 0.8、`sherpa`；操作教學截圖 0.1 | 各類型的值 |
| `keyframes.scene`／`.max_frames` | `0.3`／`60` | 影片截圖門檻與上限 |
| `subtitles.cues_srt`／`.corrected_srt` | `true`／`true` | 是否產生兩個新字幕檔 |
| `subtitles.speaker_label` | `change` | 講者標示：`change`（換人時）／`always`／`none` |
| `subtitles.uncertain` | `orig` | 待確認的字在字幕裡怎麼顯示：`orig`／`guess`／`mark` |
| `subtitles.max_line_chars`／`.max_lines`／`.min_sec`／`.max_sec`／`.max_cps` | `16`／`2`／`0.833`／`7.0`／`9` | 字幕規則 |
| `html.enabled`／`.media`／`.theme` | `true`／`auto`／`dark` | [網頁版](/features/web)：是否產生、是否放播放器（`off`＝時間碼一律文字）、第一次開啟的主題（2.1） |
| `reference.frames` | `true` | [參考資料](/features/reference)：AI 校正時送影片截圖（2.2） |
| `reference.max_frames`／`.frame_max_px` | `8`／`1280` | 截圖最多幾張、縮到長邊幾 px（`max_frames: 0` 等於不送）（2.2） |
| `reference.docs`／`.context` | `true`／`true` | 讀會議文件／讀說明檔與 `context.md`（2.2） |
| `reference.ask_context` | `true` | 入口問一行背景說明（`false`＝不問，檔案照讀）（2.2） |
| `reference.terms_max_chars`／`.paragraphs_max_chars` | `1500`／`4000` | 送出的文件名詞、段落字數上限（2.2） |
| `reference.doc_max_files`／`.doc_max_mb`／`.pdf_max_pages` | `10`／`50`／`200` | 文件份數、單檔大小、PDF 頁數上限（2.2） |
| `consistency.enabled` | `true` | [全文用字統一](/features/consistency)（本機處理，不呼叫模型）（2.2） |

## 安裝程式的參數

Windows：

```powershell
install.cmd -Target Both                        # 不顯示選單，直接安裝（CLI / App / Both）
install.cmd -Target CLI -Backend openvino:CPU   # 跳過偵測，直接指定（另有 openvino:NPU、openvino:GPU、ct2:cuda）
install.cmd -Target Both -Whisper large-v3      # 改用較準確但較慢的模型
install.cmd -Target Both -KeepAll               # 保留所有後端的模型與套件
install.cmd -Target Both -Breeze                # 安裝 Breeze-ASR-25，不詢問（-NoBreeze 則不安裝）
install.cmd -Target Both -Correct               # 開啟自動校正，不詢問（-NoCorrect 則關閉）
install.cmd -Target Both -Correct -CorrectProvider openai              # 指定供應商（auto / claude / openai）
install.cmd -Target Both -Correct -CorrectModel sonnet                 # 指定模型
install.cmd -Target Both -Correct -CorrectProvider claude -CorrectChannel api   # 改用 API 通道
install.cmd -Target Both -GpuDiar               # 安裝（或補完成）GPU 說話者分離
install.cmd -RemoveGpuDiar                      # 移除 GPU 說話者分離
install.cmd -Uninstall                          # 解除安裝
```

macOS：

```bash
./install.sh --target both                      # 不顯示選單，直接安裝（cli / app / both）
./install.sh --target cli --backend mlx:gpu     # 跳過偵測，直接指定（另有 ct2:cpu）
./install.sh --target both --breeze             # 安裝 Breeze-ASR-25（--no-breeze 則不安裝）
./install.sh --target both --correct --correct-provider openai --correct-model gpt-6.1-sol
./install.sh --uninstall
```

- 指定後端（`-Backend`）時不測速；後端與裝置和原本相同時沿用原本的精度，要改精度加 `-ComputeType`（`--compute-type`）。
- 換了硬體只想重新測速、不重裝：執行 `$MMH` 裡的 `scripts/setup_backend.py`。Windows 新加裝 NVIDIA 顯示卡時請重新執行 `install.cmd`（要先裝 CUDA 套件）。
