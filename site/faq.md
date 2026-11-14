---
title: 常見問題與疑難排解
description: 音檔會上傳嗎、機敏會議能不能完全不上雲、要不要付費、準確度與限制、proxy，以及常見狀況的處理方式。
---

# 常見問題與疑難排解

**這頁幫你做到**：先找找你的問題是不是已經有答案。

## 常見問題

### 我的錄音會被上傳嗎？

不會。語音辨識、說話者分離、分段標點都在你的電腦上完成，音檔一律不送。你選擇做 AI 校正或會議摘要時，**逐字稿文字**會送到你選的 GPT（OpenAI）或 Claude（Anthropic）。2.2 起，AI 校正另外會送**影片截圖**（最多 8 張，縮小後），以及你放的背景說明與會議文件的名詞和段落；會議摘要不送截圖。每次送出前都會先問你，詢問行寫明這次要送什麼。不想送截圖：`config.json` 的 `reference.frames` 改成 `false`。詳見 [AI 校正與會議摘要](/features/ai-correction#送出去的是什麼)與[參考資料](/features/reference)。

在 Claude 裡整理（Claude Code、Claude 桌面 App，基本版的整理也是）時，你附上或讓 Claude 讀取的逐字稿與截圖會送到 Anthropic 的雲端由 Claude 處理；音檔不會送出。對話中沒有「要送出嗎？」這一步，有機敏內容時請不要在對話中讀逐字稿，改用[本機限定](/features/local-only)。

### 機敏會議可以完全不上雲嗎？

可以，用[本機限定](/features/local-only)（Pro 2.4.0 起）：

- **這一份**：對錄音檔按右鍵 →「傳送到」→「**會議轉寫（Pro，本機限定）**」（macOS 拖到「會議轉寫（Pro，本機限定）」）。輸出資料夾會多一個 `local-only.json`。
- **整部電腦**：`config.json` 的 `privacy.local_only` 改成 `true`。

本機限定時轉寫、字幕、網頁版照常，**不問** AI 校正與會議摘要，之後誰要送都會被拒絕（exit 6）。沒有 AI 摘要，要整理就用[會議記錄校稿](/features/proofread)人工校稿，常錯的詞匯入對照表後下次更準。

另外記得：在 Claude 對話（Claude Code、Claude 桌面 App）裡讀逐字稿，本身就會送到 Anthropic 的雲端。skill 遇到本機限定會先問你，但機敏內容最好不要在對話中整理。

### 為什麼沒有「這次送出」的旗標？

刻意的。本機限定是**拒絕，而不是提醒**：旗標可能在趕時間、複製別人的指令、或讓 AI 代為執行時被加上去，而機敏內容送出一次就收不回來。要解除只能自己動手：這一份刪掉輸出資料夾裡的 `local-only.json`，全部則把 `privacy.local_only` 改回 `false`（見[怎麼解除](/features/local-only#怎麼解除)）。

### 要付費嗎？

- 程式本身免費（MIT 授權）。
- 轉寫在本機進行，不需要任何付費服務。
- 選用的 AI 校正與會議摘要預設透過你自己的 ChatGPT 或 Claude 訂閱（用 Codex 或 Claude Code），**不另外收費，但會用掉方案額度**。改用 API 金鑰時依用量計費。畫面上的「API 等價費用」是換算成 API 大約要多少錢，方便比較。

### 會議記錄校稿是什麼？要另外付錢嗎？

會議記錄校稿是 Pro 的附屬工具：在瀏覽器裡一處一處確認 AI 校正的結果、直接改錯字，校完產出定稿逐字稿與字幕，並把常錯的詞匯入對照表。它免費（MIT 授權），要另外下載安裝，而且要先裝好 Pro。唯一會花費的是選用的「用定稿重做會議記錄」，費用與 Pro 整理會議記錄相同，而且按下前會先顯示預估費用。見[會議記錄校稿](/features/proofread)。

### 校稿工具會上傳逐字稿嗎？

不會。會議記錄校稿在你的電腦上執行，服務只接受這部電腦本身的連線，頁面不連任何外部網站。只有你按「用定稿重做會議記錄」並確認時，定稿逐字稿才會送到 Pro 設定的 AI 供應商。見[會議記錄校稿 › 資料存在哪裡](/features/proofread#資料存在哪裡)。

### 沒有網路可以用嗎？

可以。安裝時需要網路下載套件與模型；之後轉寫可以完全離線。AI 校正與會議摘要需要網路。

### 不用 AI 校正，逐字稿可以用嗎？

可以。`transcript.md` 是完整的逐字稿，也可以之後自己附到 Claude 對話裡整理（附上的逐字稿會送到 Anthropic 的雲端）。純華語、收音清楚的錄音，錯誤率大約一成以內，可以直接閱讀。

### 準確度怎麼樣？有什麼限制？

| 情境 | 預期表現 |
|---|---|
| 純華語、收音清楚 | 錯誤率大約一成以內 |
| 中英夾雜的技術討論 | 錯誤率明顯上升；用[專有名詞清單](/features/accuracy#專有名詞清單)、Breeze 與 AI 校正補強 |
| 遠距收音、多人搶話 | 錯誤率上升，講者也容易分錯 |
| 台語、華台混講 | 預設模型不支援；Pro 2.5 起選裝 Breeze-ASR-26（見下一題） |

另外：

- S1、S2 只是依聲音分群，對應到姓名要靠 AI 從內容推斷，或由你提供與會名單。
- AI 校正拿不準的地方會標成待確認；GPT 比較少標待確認，看校正摘要時請多留意。
- 會議的待釐清問題有程式輔助，但不保證不漏；長會議請對照議題查看。
- 說話者分離與各項預設值只用合成素材實測過，真實錄音的效果還沒驗證（見[研究方法](/design/research#已知限制)）。

### 會議有人講台語怎麼辦？

Pro 2.5 起可以選裝台語用的辨識模型 **Breeze-ASR-26**（MediaTek Research，Apache-2.0；見[提升準確度 › Breeze-ASR-26](/features/accuracy#breeze-asr-26-台語)）：

- 安裝時回答「是否安裝 Breeze-ASR-26」選 `y`（預設不裝），或之後執行 `setup_backend.py --breeze26-only` 加裝。要約 10 GB 可用空間（暫時下載約 6.2 GB，轉換後佔約 1.6 GB）。NVIDIA 與 Intel／CPU 的電腦可以用，**macOS 不提供**。
- 右鍵轉寫時「辨識模型」題選 `t`；Claude CLI 模式說「會議有人講台語」。
- 實測真人台語約**三成字錯**（預設模型與 Breeze-ASR-25 是五到八成，多半看不懂）。人名、機關名、否定句容易錯，而且讀起來很通順，**不適合直接當正式逐字紀錄**，請人工核對（可以用[會議記錄校稿](/features/proofread)）。
- 基本版不支援台語。

### 台語會變成台語漢字嗎？

**不會。** Breeze-ASR-26 會把台語**翻成台灣華語文字**，例如台語「自細漢爸母就過身矣」會寫成「從小父母就過世了」。華語讀者看得懂，但不是原話的逐字紀錄（不是台語漢字，也不是台羅拼音）。同一句台語翻成華語可以有好幾種說法，人名、數字、否定的地方請對照錄音確認。

### 雜訊或音樂被辨識成句子？

Breeze-ASR-26 遇到長段雜訊、音樂時，可能會編出通順的句子（例如「老闆 老闆娘」），舊的幻覺過濾擋不住。Pro 2.5.0 的處理：

- **有說話者分離時**（預設）：自動開啟語音偵測，略過非人聲的部分。開發時實測白雜訊被辨識成句子的段數從 2 降到 0，真語音結果不變。只限 NVIDIA 的版本；Intel／CPU 的版本沒有這一層。
- **略過說話者分離時**（講者人數輸入 `s`）：不開（實測會讓真人台語多約 1 個百分點的字錯），入口會多印一行「沒有說話者分離時，長段雜訊或音樂可能被辨識成句子」。錄音有長段音樂或雜訊時，請不要略過說話者分離；看到逐字稿在沒人講話的地方出現句子，對照錄音刪掉即可。
- 預設模型與 Breeze-ASR-25 的行為不變。

### 基本版和 Pro 版可以一起裝嗎？

可以，兩版的 skill 名稱、資料夾、右鍵選單都不同，互不影響。同時安裝會多佔約 2～4 GB。見[基本版](/basic#和-pro-版並存)。

### 我的 Mac 是 Intel 晶片 / 我的電腦是 Windows ARM，可以用嗎？

不行，安裝程式會直接停止。目前支援 Windows x64 與 Apple Silicon Mac。

### 錄音很長（例如 3 小時以上）可以嗎？

可以。轉寫時間大致和錄音長度成正比。AI 校正與會議摘要會分段處理再彙整；錄音超過 2 小時時，題目前會多一行提醒，寫明預估時間與費用。

### 公司網路有 proxy，安裝失敗？

先設定 `HTTPS_PROXY` 環境變數，再重新執行安裝程式。安裝紀錄在 runtime 資料夾的 `install.log`。

## 疑難排解

### 安裝

| 狀況 | 處理 |
|---|---|
| pip 安裝失敗 | 看 `install.log`；有 proxy 時先設定 `HTTPS_PROXY` |
| 找不到 ffmpeg | 開新的終端機（Windows 可能要登出再登入）讓路徑生效，再重新執行安裝程式 |
| macOS 顯示「無法打開，因為它來自未識別的開發者」 | 對 `install.command` 按右鍵 →「打開」；或到「系統設定 → 隱私權與安全性」按「強制打開」 |
| 找不到 Homebrew（macOS） | 照 <https://brew.sh> 安裝後，開新的終端機再執行 `install.command` |
| 候選硬體裡沒有 NPU | 確認工作管理員看得到 NPU，更新 Intel NPU 驅動後重新執行 `install.cmd` |
| 候選硬體裡沒有 NVIDIA | 確認 `nvidia-smi` 可以執行、驅動支援 CUDA 12，且顯示記憶體至少 3 GB |
| 候選硬體裡沒有 MLX（macOS） | 確認是 Apple Silicon Mac，且 Python 是 arm64 原生版（不是 Rosetta），再重新執行 `install.command` |
| Breeze 安裝或轉換失敗 | 看 `install.log`；常見原因是連不到 `huggingface.co`／`pypi.org`，或磁碟空間不足。之後可以用 `setup_backend.py --breeze-only` 重試 |
| Breeze-ASR-26 沒有裝成（「磁碟空間不足」或下載、轉換失敗） | 2.5 起安裝畫面會寫原因，其他部分照常裝完。清出約 10 GB 可用空間（或確認連得到 `huggingface.co`／`pypi.org`）後執行 `setup_backend.py --breeze26-only`；暫存檔會自動刪掉，不會留下轉到一半的模型 |
| GPU 說話者分離沒有裝好 | 看[原因表](/install/gpu#裝失敗也沒關係)，補完後執行 `install.cmd -GpuDiar` |
| 安裝一開始就停下：「config.json 讀不了：…為了不覆寫你的設定…這次沒有寫入任何東西」 | 2.4.1 起，`config.json` 壞掉時安裝程式不會蓋掉它（以免連本機限定一起洗掉）。照畫面上的原因修好它（例如少了逗號、多了逗號、存成了 BOM），或刪掉它再重新執行安裝程式（會重新偵測硬體、本機限定是關）。見[本機限定 › config.json 讀不了或值看不懂](/features/local-only#config-unreadable) |

### 轉寫

| 狀況 | 處理 |
|---|---|
| Windows 右鍵沒有「會議轉寫（Pro）」 | Windows 11 要先點「顯示其他選項」；還是沒有就重新執行 `install.cmd` |
| 右鍵沒有「會議轉寫（Pro，本機限定）」 | 2.4.0 起才有：用 2.4.0 以上的安裝包重新執行 `install.cmd`（macOS `install.command`），升級時會自動建立 |
| macOS 拖放後沒有反應 | 到「系統設定 → 隱私權與安全性 → 自動化」，允許「會議轉寫（Pro）」控制「終端機」 |
| 轉寫時顯示「無法以 … 載入 Whisper」 | 硬體、驅動或系統變了，重新執行安裝程式重新偵測。開頭同時寫「config.json 讀不了…這次的設定都用預設值」時，是 `config.json` 壞了、改用預設的 openvino/CPU：先修好 `config.json`（見下一列） |
| 轉寫開頭寫「config.json 讀不了：…這次的設定都用預設值…而且當成本機限定」 | `config.json` 讀不了（2.4.1 起也當成本機限定）。照訊息修好它，或刪掉後重新執行安裝程式。見[本機限定 › config.json 讀不了或值看不懂](/features/local-only#config-unreadable) |
| 輸出是簡體字 | 確認沒有加 `--no-opencc` |
| 專有名詞一直錯 | 加到 [`glossary.txt`](/features/accuracy#專有名詞清單)；固定的錯法加到[對照表](/features/accuracy#固定錯誤對照表) |
| 「權限」變「許可權」這類用詞被改掉 | 用 `opencc_keep.py test "句子"` 試，再把詞加到 `opencc_keep.tsv`（見 [OpenCC 詞彙回復表](/features/accuracy#opencc-詞彙回復表)） |
| 對照表替換錯了 | `corrections.py remove "錯誤寫法"`；原文在 `transcript.json` 的 `raw` 欄位 |
| `transcript.md` 開頭寫「標點模型未安裝」 | 執行 `setup_backend.py --punct-only` 補裝 |
| 分段不理想 | 調 `--paragraph-gap`／`--paragraph-max-chars`，或改 `config.json` 的 `punctuation.*` |
| 講者太多或兩人被併成一個 | 見[說話者分離 › 講者太多或太少](/features/diarization#講者太多或太少) |
| GPU 說話者分離沒有用到 | 看 `transcript.json` 的 `meta.diarization.engine_reason`：`not_installed`＝沒裝好、`no_gpu`＝找不到顯示卡、`low_vram`＝顯示記憶體被其他程式占用、`type`＝座談預設 CPU、`timeout`／`oom`／`cuda_error`＝這次失敗已改用 CPU |
| 類型選錯了 | 逐字稿不受影響，用 `auto_minutes.py --type <代號> --force` 重做筆記（見[內容類型](/features/content-types#選錯了怎麼辦)） |
| 自訂範本沒出現在選單 | 選單下方會印原因；或執行 `templates.py check` |
| 字幕對應失敗 | 那幾段用原文；補校後執行 `subtitles.py "<檔名>_minutes" --corrected` |

### AI 校正與會議摘要

| 狀況 | 處理 |
|---|---|
| 入口沒有問「要做 AI 校正嗎？」 | 本機限定（從「會議轉寫（Pro，本機限定）」轉寫、輸出資料夾有 `local-only.json`、`privacy.local_only` 是 `true`，或 2.4.1 起 `config.json` 讀不了）時不問，這是設計如此；否則是找不到 `claude`／`codex` 指令，或 `codex` 沒登入又沒有 `claude`，結束畫面會寫原因與安裝、登入方式 |
| 突然變成本機限定、AI 不送出：入口不問 AI，或結束碼 6，訊息寫「config.json 讀不了」或「config.json 的值看不懂」 | 2.4.1 起，`config.json` 讀不了（手改時打錯逗號或引號、存成 BOM、檔案被鎖住或沒有權限）或 `privacy.local_only` 寫成 `"true"`、`1` 這類值時，一律當成本機限定，以免把機敏會議送出去。照訊息寫的原因修好 `config.json`（`privacy.local_only` 只寫 `true` 或 `false`，不加引號），或刪掉它再重新執行安裝程式。見[本機限定 › config.json 讀不了或值看不懂](/features/local-only#config-unreadable) |
| `auto_correct.py`／`auto_minutes.py` 結束碼 6，訊息「本機限定（…）：…已拒絕，沒有送出任何資料」 | 這一份是[本機限定](/features/local-only)，拒絕送出是設計如此、沒有旗標可以略過。確定可以送時才解除：刪除輸出資料夾裡的 `local-only.json`，或把 `config.json` 的 `privacy.local_only` 改回 `false`，再重新執行 |
| 自動校正沒跑 | 看輸出資料夾 `auto_correct.json` 的 `reason`：`cli_not_found`＝找不到指令、`auth_failed`＝沒登入、`api_key_missing`＝API 通道沒設定金鑰；本機限定時不寫 `auto_correct.json`，看 `run_log.jsonl` 裡 `reason: local_only` 的事件 |
| `auth_failed`（GPT） | 在終端機執行 `codex login` 登入；`codex login status` 可以確認（不耗額度） |
| `auth_failed`（Claude） | 在終端機執行 `claude`，輸入 `/login` 登入，再用 `auto_correct.py` 補做 |
| 會議摘要沒跑或不完整 | 看 `auto_minutes.json` 的 `reason` 與 `parts`；修好後 `auto_minutes.py "<檔名>_minutes" --force` |
| 自動校正改錯了 | `transcript.md` 沒有被改動，可以直接用它；不想再自動校正就重新執行安裝程式加 `-NoCorrect` |
| 對照表被自動寫入不想要的項目 | `corrections.py auto-undo "錯誤寫法"`（或 `--all`）；不想再自動寫入就把 `correction.corrections_auto.mode` 改回 `"off"` |
| log 的費用和帳單不同 | 訂閱通道不另計費，log 是等價估算；價格變了就[更新價格表](/features/run-log#價格表更新) |

### Claude App

| 狀況 | 處理 |
|---|---|
| 上傳 skill 失敗 | 上傳桌面的 `meeting-minutes-pro-skill-upload.zip` 或 Release 的上傳檔（不要自己重新壓縮），並確認已開啟程式碼執行功能 |
| 出現「Zip cannot contain nested zip files」 | 上傳到的是安裝包，改上傳上傳檔 |
| Claude Code 裡出現兩個 meeting-minutes-pro | App 上傳的 skill 同步過來了，兩者內容相同，留一個即可 |

找不到答案？到 <RepoLink path="">GitHub repo</RepoLink> 開 issue（請不要附真實會議的錄音或逐字稿）。
