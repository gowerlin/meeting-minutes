---
title: 本機限定（機敏會議）
description: 2.4 起的本機限定：機敏會議什麼都不送 GPT 或 Claude。何時用、兩種開法、會做什麼與不做什麼、local-only.json、被拒絕時的訊息（exit 6）、怎麼解除、config.json 讀不了時也當成本機限定（2.4.1）、與會議記錄校稿的關係、執行 log 的欄位。
---

# 本機限定（機敏會議）

**這頁幫你做到**：會議內容不能離開這部電腦時，確定**沒有任何資料會送到 GPT 或 Claude**，而且不會因為一時手滑送出去。

::: tip 一句話
本機限定的那一份，只做在這部電腦上完成的步驟：轉寫、字幕、網頁版都照常；**AI 校正與 AI 整理一律拒絕**，沒有任何旗標可以略過。要整理，改用[會議記錄校稿](/features/proofread)人工校稿。（Pro 2.4.0 起）
:::

## 什麼時候用

會議裡有不能交給雲端服務的內容，例如：

- 客戶的個資、合約與報價
- 人事、考績、薪資
- 還沒公開的財務數字或技術資料
- 公司規定不得使用雲端 AI 的會議

不確定能不能送雲端時，就用本機限定：之後確認可以送，再解除也來得及（見[怎麼解除](#怎麼解除)）。

## 兩種開法

任一成立就是本機限定。

### 每份會議：本機限定的入口

只有這一份本機限定，其他會議照常。

- **Windows**：對錄音檔按右鍵 →「傳送到」→「**會議轉寫（Pro，本機限定）**」。
- **macOS**：拖到「應用程式」裡的「**會議轉寫（Pro，本機限定）**」（Mac 上尚未實測）。
- **命令列**：`transcribe.py <檔案> --local-only`。

輸出資料夾會多一個標記檔 `local-only.json`，之後這一份的任何步驟都照本機限定處理。

### 整部電腦：全域設定

這部電腦的每一份都本機限定：把 runtime 資料夾裡 `config.json` 的

```json
"privacy": {"local_only": false}
```

改成 `true`。安裝摘要會列「本機限定：開／關」。

### 小提醒

- 右鍵入口裝好就有，兩個入口並列：「會議轉寫（Pro）」與「會議轉寫（Pro，本機限定）」（見[右鍵「傳送到」與拖放](/usage/send-to#本機限定的入口)）。
- 全域設定要寫 JSON 的 `true`（不加引號）。2.4.1 起，寫成 `"true"`、`1` 這類看不懂的值，或 `config.json` 整個讀不了時，也**當成本機限定**，畫面會寫原因（見 [config.json 讀不了或值看不懂](#config-unreadable)）；2.4.0 會當成沒開。
- 全域設定不會在輸出資料夾寫標記檔：之後把全域設定關掉，舊的輸出資料夾也跟著恢復。
- 用一般入口重新轉寫一份之前用本機限定轉過的錄音，輸出資料夾裡的標記檔還在，這一份仍是本機限定。

## 會做什麼、不做什麼

| | 本機限定時 |
|---|---|
| 轉寫（語音辨識、說話者分離、分段標點、繁體與用語回復、影片截圖） | ✅ 照常（本來就在本機） |
| 錯誤對照表與詞表替換 | ✅ 照常 |
| 字幕 `transcript.cues.srt` | ✅ 照常 |
| 網頁版、全文用字統一、`refs.py plan`、`auto_minutes.py --estimate-only`（只預估）、`--render-only` | ✅ 照常（本機處理，不呼叫模型） |
| 右鍵入口問「要做 AI 校正嗎？」「要產生會議摘要嗎？」 | ❌ **不問**，也不偵測 `claude`／`codex` |
| `auto_correct.py`（AI 校正） | ❌ **拒絕送出**（exit 6） |
| `auto_minutes.py`（會議摘要與其他筆記） | ❌ **拒絕送出**（exit 6） |
| `transcribe.py --correct`（含 `--claude`／`--openai`） | ❌ 校正被拒絕（exit 6），**轉寫照常完成** |

所以本機限定的那一份**沒有 AI 摘要**，也沒有 AI 校正版逐字稿。這是刻意的：不會偷偷改用別的雲端服務或本地模型代替（為什麼不用本地模型，見[設計理念](/design/#_11-為什麼不用本地-ai-模型做校正與整理)）。

### 右鍵入口的畫面

開頭是黃字：

```text
==== 會議轉寫（Pro，本機限定）　meeting-minutes-pro 2.4.0 ====
本機限定（本機限定的右鍵入口）：這次不會把任何資料送到 GPT 或 Claude；轉寫與字幕都在這部電腦完成，不做 AI 校正與整理
```

轉寫完不問 AI 校正與整理，結束畫面：

```text
本機限定：不做 AI 校正與會議摘要，不會送出任何資料
完成：…\會議_minutes
  transcript.md              逐字稿（原稿）
  transcript.srt             字幕檔（一段一條）
  transcript.cues.srt        字幕（依字幕規則切條，不經 AI）（135 條）
  local-only.json            本機限定標記（刪掉這個檔＝解除這一份的本機限定）
本機限定：沒有送出任何資料（沒有 AI 校正，也沒有 AI 整理）。
下一步：要人工校稿，對這個輸出資料夾按右鍵 → 傳送到 → 會議記錄校稿（Pro 的附屬工具，另外安裝）；校稿得到的經驗匯入對照表與詞表後，下次轉寫更準。
要解除本機限定（之後才能用 AI 校正與整理）：這一份：刪除輸出資料夾裡的 local-only.json
```

全域設定開著時，第一行改成「本機限定（config.json 的 privacy.local_only）：…」，最後一行改成「全部：把 …config.json 的 privacy.local_only 改成 false」。

## 標記檔 `local-only.json` {#marker}

從本機限定入口轉寫時，程式在建立輸出資料夾之後、開始轉寫之前寫入（轉寫中途失敗也已經標記）。內容只有標記本身，不含逐字稿內容或檔名：

```json
{
  "local_only": true,
  "created_at": "2026-11-08T15:22:01+08:00",
  "source": "sendto",
  "version": "2.4.0",
  "note": "本機限定：這份不送 GPT 或 Claude。要解除，刪除這個檔案。"
}
```

- `source`：`sendto`＝Windows 右鍵入口、`dropped`＝macOS 拖放入口、`transcribe`＝命令列。
- 程式只看**檔案存不存在**：內容是空的、或被改壞了也算本機限定（寧可多擋）。
- 檔名不用點開頭，是為了讓它在 Finder 與檔案總管都看得到：要解除時你得找得到它。

## 被拒絕時的訊息（exit 6）

本機限定時執行 `auto_correct.py` 或 `auto_minutes.py`（不管加了什麼旗標），畫面寫明為什麼與怎麼解除，exit code 是 **6**：

```text
[!] 本機限定（輸出資料夾有標記檔 local-only.json）：AI 校正會把內容送到 GPT 或 Claude，已拒絕，沒有送出任何資料。要解除：刪除 …\會議_minutes\local-only.json。
```

```text
[!] 本機限定（config.json 的 privacy.local_only 是 true）：AI 整理（會議摘要／筆記）會把內容送到 GPT 或 Claude，已拒絕，沒有送出任何資料。要解除：把 …\config.json 的 privacy.local_only 改成 false。
```

stdout 最後一行的 JSON（給程式讀的）：

```json
{"minutes": {"status": "skipped", "reason": "local_only", "local_only_source": "marker", …}}
```

| 項目 | 值 |
|---|---|
| exit code | `6`（其他 exit code 的意思不變） |
| `reason` | `local_only` |
| `local_only_source` | `marker`（標記檔）、`config`（全域設定）、`config+marker`（兩者都有）；2.4.1 起另有 `config-unreadable`（`config.json` 讀不了或值看不懂，可能再加 `+marker`） |
| `local_only_config_reason` | 2.4.1 起，來源是 `config-unreadable` 時才有：`bad_json`、`empty`、`not_utf8`、`not_object`、`permission`、`os_error`、`is_dir`、`bad_value` |

被拒絕時，程式在找 `claude`／`codex` 之前就停下來：不讀逐字稿、不寫 `auto_correct.json`／`auto_minutes.json`，也不跑任何模型指令。

## 為什麼沒有「這次送出」的旗標

本機限定是**拒絕，而不是提醒**。如果有一個「這次仍然送出」的旗標，就可能在趕時間、複製別人的指令、或讓 AI 代為執行時被加上去，而那正是機敏會議最不能發生的事。所以要解除，只能你自己動手改設定或刪標記檔，程式不提供任何捷徑，也不會替你刪。

## 怎麼解除

| 要解除的範圍 | 做法 |
|---|---|
| 這一份 | 刪除輸出資料夾裡的 `local-only.json` |
| 全部（全域） | 把 `config.json` 的 `privacy.local_only` 改回 `false` |

兩種都開著時，兩個都要做。解除之後，這一份就能照常做 [AI 校正與會議摘要](/features/ai-correction)（例如用 `auto_minutes.py "<檔名>_minutes"` 補做）。

## config.json 讀不了或值看不懂（2.4.1） {#config-unreadable}

`config.json` 讀不了的時候，程式沒辦法知道你有沒有開全域本機限定。2.4.1 起一律**當成本機限定**（寧可多擋，不外送）；2.4.0 會當成沒開、照常送出。

| `config.json` 的狀態 | 全域 |
|---|---|
| 不存在 | 關 |
| 讀得到，沒有 `privacy`，或 `privacy.local_only` 是 `false` | 關 |
| `privacy.local_only` 是 `true` | 開 |
| 存在但讀不了：沒有權限、被別的程式鎖住、不是 UTF-8、不是合法的 JSON（含開頭有 BOM）、空檔、最外層不是 `{ … }` | **開** |
| `privacy` 不是 `{ … }`，或 `local_only` 是 `true`／`false` 以外的值（`"true"`、`1`、`null`…）；畫面的原因寫「值看不懂」 | **開** |

常見的原因是手改 `config.json` 時多打或少打了一個逗號、引號，或用了會加 BOM 的編輯器存檔。

**畫面**：右鍵（拖放）入口開頭的黃字寫出原因與恢復方法，接著照本機限定處理（不問 AI 校正與整理）：

```text
本機限定（config.json 讀不了：不是合法的 JSON（第 210 行第 1 欄）；為了不外送，已當成本機限定）：這次不會把任何資料送到 GPT 或 Claude；…
要恢復：修好 %LOCALAPPDATA%\meeting-minutes-pro\config.json（存成 UTF-8 的 JSON 物件）；或刪掉它再重新執行安裝程式（重建的 config.json 本機限定是關）
```

值看不懂時寫「config.json 的值看不懂：privacy.local_only 是 "true"，只認得 true 或 false」。`auto_correct.py`、`auto_minutes.py` 一樣 exit 6，訊息是同樣的原因與恢復方法。

**其他設定**：讀不了的時候，後端、詞表這些設定都用預設值（和 2.4.0 相同），轉寫開頭多一行警告：

```text
  [!] config.json 讀不了：不是合法的 JSON（第 210 行第 1 欄）：…\config.json。這次的設定都用預設值（暫以 openvino/CPU 執行），而且當成本機限定（不送 GPT 或 Claude）；請修好它，或刪掉後重新執行安裝程式
```

安裝時選的是 NVIDIA 或 Apple Silicon 的電腦，預設的 openvino/CPU 模型通常沒有下載，轉寫會停在「無法以 openvino/CPU 載入 Whisper」：先把 `config.json` 修好。

**安裝程式不會蓋掉它**：安裝程式（與 `setup_backend.py`、`setup_gpu_diar.py`）遇到讀不了的 `config.json` 會在一開始就停下，什麼都不寫，檔案原封不動（2.4.0 會把整份設定洗掉、連本機限定一起改回 `false`）。見[安裝 › 安裝失敗怎麼辦](/install/#安裝失敗怎麼辦)。值看不懂的檔讀得到，安裝照常、值原樣保留。

**恢復**：修好 `config.json`（UTF-8、JSON 物件，`privacy.local_only` 只寫 `true` 或 `false`），重新整理或重新執行就恢復；或刪掉它再重新執行安裝程式（重建的 `config.json` 本機限定是關，硬體會重新偵測）。只用本機限定的右鍵入口（標記檔）的那幾份不受這個問題影響。

## 沒有 AI 摘要，怎麼整理 {#no-ai-minutes}

用附屬工具[會議記錄校稿](/features/proofread)（另外安裝）人工校稿：

1. 對輸出資料夾按右鍵 →「傳送到」→「會議記錄校稿」。沒有 AI 校正版也可以，直接校 `transcript.md`：選取文字就能改。
2. 校完按「定稿…」，產生定稿逐字稿 `transcript.final.md` 與定稿字幕。
3. 常錯的詞在「經驗整理」勾選後匯入對照表與詞表，**下次轉寫就會更準**。

會議記錄校稿 1.1.0 起認得本機限定：頁首檔名旁有「**本機限定**」標示，首頁清單在那一份旁也標示；「**用定稿重做會議記錄**」停用並寫明原因（那一步會把內容送給 AI）。人工修改、定稿、經驗匯入都照常。1.1.1 起 Pro 的 `config.json` 讀不了或值看不懂時也一樣，首頁標題旁寫「本機限定（config.json 讀不了）」。見[用會議記錄校稿確認逐字稿 › 本機限定的稿](/usage/proofread#本機限定的稿)。

## 在 Claude 對話中

**Claude 對話本身就是上雲**：在 Claude Code 或 Claude 桌面 App 的對話中讀逐字稿，逐字稿與截圖會送到 Anthropic 的雲端由 Claude 處理（音檔不送），而且對話中沒有「要送出嗎？」這一步。

所以 2.4 的 skill 遇到本機限定（全域設定或標記檔）時：

- 讀逐字稿**之前**先提醒你「在這個對話裡讀逐字稿＝送到 Anthropic 雲端」，**等你明確回答要繼續**才讀。
- 不執行 `auto_correct.py`、`auto_minutes.py`，轉寫也不加 `--correct`。
- 不替你刪標記檔或改設定。
- 2.4.1 起用 `common.py local-only` 判定（`config.json` 讀不了也算本機限定）；這個判定本身失敗時，也照本機限定處理。
- Claude 桌面 App 裡，檔案在你**附上的那一刻就已經送出**了；機敏會議的逐字稿請不要附到 App。

機敏內容請不要在 Claude 對話中整理，改用上面的人工校稿。

## 執行 log 的欄位

本機限定時，[執行 log](/features/run-log) 多記一筆事件，摘要多兩欄；不是本機限定時與 2.3 完全相同。

| 位置 | 內容 |
|---|---|
| `run_log.jsonl` 的 `privacy` 事件 | `{"event": "privacy", "local_only": true, "local_only_source": "marker"}`：轉寫判定後，以及 AI 校正、整理被拒絕時各寫一筆。2.4.1 起來源是 `config-unreadable` 時另記 `config_reason`（原因代碼，不記路徑與內容） |
| 被拒絕的步驟 | `result` 事件的 `status: skipped`、`reason: local_only`；沒有任何 `call`（模型呼叫）事件 |
| `run_summary`、runtime 的 `logs/runs.jsonl` | 只在本機限定時多 `local_only: true`、`local_only_source` |

要確認一份會議真的沒有送出任何東西：看它的 `run_log.jsonl` 裡沒有 `"event": "call"`。
