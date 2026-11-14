# meeting-minutes-pro 2.5 規格（公開版）：台語／華台混講選項（Breeze-ASR-26）

> **公開版**：本檔是 meeting-minutes-pro **2.5.0** 規格的公開版，適用 2.5.x。內容是 **2.5.0 相對 2.4.1 的差異**；本檔沒有提到的行為一律照
> 2.4.1 規格（公開版 [`meeting-minutes-pro-2.4.1-spec.md`](meeting-minutes-pro-2.4.1-spec.md)）、2.4 規格（公開版 [`meeting-minutes-pro-2.4-spec.md`](meeting-minutes-pro-2.4-spec.md)）與 2.4.1 的程式。
> **章節號與開發用的原規格相同**：程式註解寫的「規格 2.5.0 §x.y」就是本檔的同一節。
> 版本目錄 `V/`＝`pro/meeting-minutes-pro-v2.5.0/`（公開 repo 的路徑）。
> 標示：**〔實測〕**＝實作時以合成或公開素材實測的結果（附錄 A）；**〔開發前評估〕**＝開發前比較 Breeze-ASR-25、Breeze-ASR-26、Whisper large-v3-turbo 的評估（主要數字見 Portal〈提升準確度 › 辨識模型怎麼選〉）；
> **〔推論〕**＝未直接驗證；**〔規格決定〕**＝本規格自行決定的細節（附理由）。
> 「`$MMH`」＝`MEETING_MINUTES_PRO_HOME`；「26」＝Breeze-ASR-26；「25」＝Breeze-ASR-25。

---

## 0. 摘要

### 0.1 2.5.0 做什麼

| 功能 | 一句話 | 章節 |
|---|---|---|
| 模型別名 `breeze26` | 顯示名稱「Breeze-ASR-26（台語）」；ct2、openvino 提供，mlx 不提供；語言沿用 `zh`；與 25 目錄分開 | §2 |
| 安裝時轉換 | 官方只有 F32 權重：查磁碟 → 固定 revision 下載 → 驗大小與 SHA-256 → 暫時 venv 轉換 → 檢查齊全才搬進 `models/` → 刪原始權重與暫時 venv；失敗不留半成品 | §3 |
| 安裝旗標與詢問 | `-Breeze26`／`-NoBreeze26`（`install.sh` `--breeze26`／`--no-breeze26`）；不指定時問一次、預設 N；已裝過不問、保留；`profiles.breeze26` | §4 |
| 加裝與移除 | `setup_backend.py --breeze26-only`、`--remove-breeze26` | §4.3 |
| 入口選擇題 | 「使用 Breeze-ASR-25？[y/N]」改成「辨識模型」選擇題，只列出已安裝的；`t`＝26，選 `t` 印一行提醒（又略過說話者分離時多一行雜訊提醒）；`preWaits` 鍵名 `ask_whisper` | §5 |
| 雜訊幻聽處置 | 26（ct2）在**有說話者分離時**開 faster-whisper `vad_filter`；略過說話者分離時不開、改印提醒；量測表與判定 | §6 |
| SKILL | 「會議有人講台語、華台混講」→ `--whisper breeze26`，先說明限制；預估用 `profiles.breeze26.rtf` | §7 |
| 授權與文件 | `THIRD-PARTY-NOTICES.md`、README 新段〈3.1 Breeze-ASR-26〉 | §9 |

### 0.2 不做什麼

- 不取代 25、不改 turbo 與 25 的行為（`vad_filter`、標點、入口預設、安裝預設都照舊）。
- 不依素材自動切換模型（沒有可靠的台語偵測；〔開發前評估〕）。
- 不提供 mlx 版（社群 MLX 版 `fredchu/breeze-asr-26-mlx-fp16` 未驗證）；macOS 安裝程式不問，入口也不會出現 `t`。
- 不用社群 CTranslate2 轉換版（非官方；〔開發前評估〕建議自己由官方權重轉換）。
- 不散布模型權重或轉換結果（安裝包、公開 repo、Release 都沒有）。
- 不改會議記錄校稿（§8.2）。

### 0.3 對照表

| 項目 | 本規格 | 實作（`V/payload/runtime/`） | 測試（`tests/`） |
|---|---|---|---|
| 模型別名、就緒判定、顯示名稱、標點 | §2 | `scripts/common.py`：`WHISPER_MODELS`、`BREEZE26_*`、`BREEZE_FAMILY`、`model_supported()`、`whisper_ready()`；`transcribe.py` `ASR_DISPLAY`；`punctuate.py` | `test_v250.Models`；`test_asr_message`（每個別名都有顯示名稱） |
| 安裝時轉換 | §3 | `scripts/breeze.py`：`convert_ct2_26()`、`convert_openvino_26()`、`check_disk_26()`、`verify_weights_26()`、`_install_dir()`、`ensure(..., alias)`；`download_models.ensure_whisper()` | `test_v250.Convert`（下載、雜湊、venv、轉換器都用假的） |
| 安裝旗標、`profiles.breeze26` | §4 | `scripts/setup_backend.py`：`setup_breeze26()`、`remove_breeze26()`、`--breeze26`、`--breeze26-only`、`--remove-breeze26`；`install.ps1`、`install.sh` | `test_v250.SetupBackend`、`InstallerPs`（PowerShell 7／5.1 實跑詢問區塊）、`InstallerSh`（Git Bash） |
| 入口選擇題 | §5 | `mm-sendto.ps1`、`mm-dropped.sh` | `test_v250.EntryStatic`；`entry_harness.py` 的 `whisper_*` 13 情境 × 3 shell |
| `vad_filter` | §6 | `common.ASR_VAD_FILTER`、`asr_vad_filter()`；`backends.CT2Backend`；`transcribe.py`（載入訊息、`run_log`、`meta`） | `test_v250.Vad`、`Transcribe`；量測 `pro/tests/eval_breeze26_vad.py` |
| `transcribe.py --whisper breeze26`、runs.jsonl、`--estimate-only` | §2.4 | `transcribe.py`（profile、語言 zh）；`runlog.py` 不改 | `test_v250.Transcribe`、`Estimate` |
| SKILL | §7 | `skill/meeting-minutes-pro/SKILL.md`、`references/corrected-transcript-format.md` | `test_v250.Docs` |
| 文件 | §9 | `README.md`、`THIRD-PARTY-NOTICES.md` | `test_v250.Docs` |

---

## 1. 版號與檔案

版號 2.5.0：`common.VERSION`、`render_html.FALLBACK_VERSION`（runtime 與 skill 兩份）、`install.ps1` `$Version`、`install.sh` `VERSION`、SKILL.md 版本註解、README「版本 2.5.0」與下載表、兩支入口第一行、`THIRD-PARTY-NOTICES.md` 標題。

| 檔案 | 改了什麼 |
|---|---|
| `payload/runtime/scripts/common.py` | `WHISPER_MODELS` 的 `breeze26`（ct2、openvino）、`BREEZE26_SOURCE`／`_REVISION`／`_WEIGHTS`／`_DISK_NEED`、`BREEZE_FAMILY`、`ASR_VAD_FILTER`、`model_supported()`、`asr_vad_filter()`、`whisper_ready()`（不提供的後端一律未就緒）；版號 |
| `payload/runtime/scripts/breeze.py` | 26 的轉換（§3）；25 的流程不變（OpenVINO 轉換抽成 `_make_venv()`／`_export_openvino()`，訊息與順序同 2.4.1） |
| `payload/runtime/scripts/download_models.py` | `ensure_whisper()` 把 `breeze26` 交給 `breeze.ensure()` |
| `payload/runtime/scripts/setup_backend.py` | §4 |
| `payload/runtime/scripts/backends.py` | `CT2Backend(vad_filter=)`、`create()` 依 `asr_vad_filter()`；26 沒裝或不提供時的訊息 |
| `payload/runtime/scripts/transcribe.py` | `ASR_DISPLAY`；載入訊息、`run_log` 的 `asr` 檢查點與 `meta` 在 `vad_filter` 開時多一欄 |
| `payload/runtime/scripts/punctuate.py` | Breeze 家族（`breeze`、`breeze26`）整段交給 CT-Transformer |
| `payload/runtime/scripts/render_html.py`（＋skill 內一份） | 版號（一行） |
| `payload/runtime/mm-sendto.ps1`、`mm-dropped.sh` | §5 |
| `install.ps1`、`install.sh` | §4 |
| `payload/skill/meeting-minutes-pro/SKILL.md`、`references/corrected-transcript-format.md` | §7 |
| `README.md`、`THIRD-PARTY-NOTICES.md` | §9 |
| `payload/meeting-minutes-pro-upload.zip` | `make_dist.py --sync-skill` 重產 |

---

## 2. 模型別名 `breeze26`

### 2.1 後端對照

| 後端 | `WHISPER_MODELS[後端]["breeze26"]` | 模型目錄（`$MMH/models/…`） | 就緒判定（`whisper_ready()`） |
|---|---|---|---|
| ct2（faster-whisper；NVIDIA CUDA） | `local/breeze-asr-26-ct2` | `ct2/breeze-asr-26-ct2/` | `model.bin` 與 `tokenizer.json` 都在（同 2.4.1 的 ct2 規則） |
| openvino（Intel NPU／GPU／CPU） | `local/breeze-asr-26-int8-ov` | `openvino/breeze-asr-26-int8-ov/` | `openvino_encoder_model.xml` 在（同 2.4.1） |
| mlx（Apple GPU） | 不提供 | — | 一律 `False`（`model_supported()` 為 `False`）〔規格決定：目錄碰巧存在也不算，避免手放的社群版被當成可用〕 |

- `local/` 前綴＝沒有現成的 Hugging Face 版本、安裝時在本機產生（同 25 的 openvino）。
- openvino 是否提供：〔實測〕用 CPU 實測一次（附錄 A.3）：轉換成功、華台混合 MX 與台語廣播 EY 的字錯率與 ct2 同級 → **提供**。
- 與 25 共存：目錄分開，轉寫一次只載入一個；兩個都裝時多約 1.6 GB 磁碟。

### 2.2 顯示名稱、語言、標點

- 顯示名稱（`transcribe.ASR_DISPLAY`）：`breeze26` →「Breeze-ASR-26（台語）」。例：「Breeze-ASR-26（台語） 載入：ct2 / cuda（1.3s；vad_filter 開：略過非人聲）」。
- 語言：沿用 `transcribe.py --language` 的預設 `zh`〔開發前評估：`zh` 在純靜音不出字；`en` 的唯一優點是雜訊被 logprob 過濾擋掉，但產品沒有那道過濾〕。
- 標點：26 和 25 一樣幾乎不輸出標點（〔開發前評估〕），`punctuate.py` 以 `common.BREEZE_FAMILY` 判斷，整段交給 CT-Transformer〔規格決定：同架構、同輸出風格；開發前評估的 CER 去標點計算，不受影響〕。
- 數字：26 傾向照念法寫中文數字（「四千三百六十萬」），本版不轉換（〔開發前評估〕；對摘要與校稿的影響列為後續觀察）。

### 2.3 來源與授權

| 項目 | 值 |
|---|---|
| 來源 | `MediaTek-Research/Breeze-ASR-26`（`common.BREEZE26_SOURCE`） |
| revision | `7b992682e7f5ceedd0a41ebec240f01ba469d19e`（`common.BREEZE26_REVISION`） |
| 權重 | `model-00001-of-00002.safetensors` 4,992,706,480 bytes `78e177c9a5228eed20f1f33485f8288bda5308a077fa7758281088c2a3100535`；`model-00002-of-00002.safetensors` 1,180,663,192 bytes `9c1f45081c3a2a606a1dc75e02653770956279d2942015587cf4880879952a7e`（`common.BREEZE26_WEIGHTS`；取自 Hugging Face 該 revision 的 LFS 資訊，與開發前評估時下載的檔案相同） |
| 授權 | Apache-2.0 |
| 下載的檔 | `*.json`、`*.txt`、`*.safetensors`（不下載 `training_args.bin`、`README.md`） |

### 2.4 命令列、`run_log`、runs.jsonl、`--estimate-only`

- `transcribe.py --whisper breeze26`：`profiles.breeze26` 存在而且沒有明確給 `--backend`／`--device`／`--compute-type` 時，用 profile 的後端、裝置、精度（同 2.4.1 對 `profiles.<別名>` 的處理，程式不變）。
- 沒裝時：`backends.create()` 丟「沒有安裝 Breeze-ASR-26（ct2）；加裝：setup_backend.py --breeze26-only」，`transcribe.py` 照舊印「無法以 ct2/cuda 載入 Breeze-ASR-26（台語）：…」並結束；不提供的後端：「本版不提供 mlx 後端的 Breeze-ASR-26」。
- `run_log` 的 `asr` 檢查點、`info` 事件、`run_summary` 與 `$MMH/logs/runs.jsonl` 的 `asr_model` 寫 `breeze26`（欄位不變，值多一種）；`vad_filter` 開時 `asr` 檢查點與 `transcript.json` 的 `meta` 多一欄 `vad_filter: true`（turbo、25 的 log 與 `meta` 逐欄不變）。
- `--estimate-only`：只有 `auto_minutes.py` 有（2.3 規格 §3），預估的是 AI 摘要的費用與時間，與 ASR 模型無關；對 `breeze26` 的輸出資料夾照常預估（`test_v250.Estimate`）。轉寫時間的預估由 SKILL 用 `profiles.breeze26.rtf` 計算（§7）。

---

## 3. 安裝時轉換（`breeze.py`）

### 3.1 流程（ct2）

1. **查磁碟**：`$MMH` 所在磁碟可用空間 < `BREEZE26_DISK_NEED`（10 GB：暫時下載約 6.2 GB＋轉換環境約 1.5 GB＋轉換後約 1.6 GB，取整數）→ 丟 `Breeze26Error`，什麼都不下載。訊息：「磁碟空間不足：<路徑> 所在的磁碟剩 X GB，安裝 Breeze-ASR-26 需要約 10 GB（暫時下載官方權重約 6.2 GB＋轉換環境約 1.5 GB＋轉換後約 1.6 GB；完成後暫存檔會刪除，只留約 1.6 GB）。請清出空間後執行 setup_backend.py --breeze26-only 加裝」。
2. **暫存資料夾** `$MMH/_convert-breeze26/`（先刪掉上次殘留的）；子行程的 `HF_HOME` 指向裡面，Hugging Face 的快取也留在裡面。
3. **下載**：子行程 `snapshot_download(BREEZE26_SOURCE, revision=BREEZE26_REVISION, local_dir=<暫存>/official, allow_patterns=…)`。
4. **驗證**：兩個權重檔的大小與 SHA-256 等於 `BREEZE26_WEIGHTS`，不符就停（不建轉換環境）。
5. **暫時 venv**：`ctranslate2==<主環境的版本>`、`transformers==4.57.6`（固定為本版實測的版本，讓轉換結果可重現）、`torch`（Windows 的 PyPI 版就是 CPU 版）。
6. **轉換**：`ct2-transformers-converter --model <official> --output_dir <暫存>/out --quantization <q> --low_cpu_mem_usage --copy_files tokenizer_config.json preprocessor_config.json added_tokens.json special_tokens_map.json vocab.json merges.txt normalizer.json generation_config.json`。`<q>` 的規則與 25 相同（`breeze.ct2_subfolder()`）：`float16`、`int8_float16` 照用，其他（`int8`、`int8_float32`、`float32`、`default`）用 `int8`。
7. **tokenizer.json**：官方沒有，用暫時 venv 的 `WhisperTokenizerFast.from_pretrained(<official>).backend_tokenizer.save(<out>/tokenizer.json)`（與 25 的詞表、特殊詞相同，〔開發前評估〕）。
8. **檢查齊全**：`model.bin`、`config.json`、`vocabulary.json`、`tokenizer.json`、`preprocessor_config.json` 都在，少一個就停。
9. **記錄**：`<out>/breeze26-source.json`：`model`、`source`、`revision`、`license`、`weights_sha256`、`backend`、`quantization`、`model_bin_sha256`、`tools`（暫時 venv 的 ctranslate2／transformers／torch 版本）、`converted_at`。
10. **搬進 `models/`**：同一顆磁碟內改名；原本有舊目錄時先改名成 `.old`、搬好後刪掉。
11. **刪暫存**：不論成功或失敗都刪 `$MMH/_convert-breeze26/`（原始權重、暫時 venv、快取）；刪不乾淨（檔案被占用）時印路徑請使用者手動刪。

### 3.2 openvino

步驟 1～4、9～11 同上；5～8 改成：暫時 venv 裝 `optimum-intel[openvino]`、`openvino==<主環境版本>`、`openvino-tokenizers==<主環境版本>.*`（同 25），`optimum-cli export openvino --model <official> --task automatic-speech-recognition-with-past --weight-format int8`，缺 `openvino_tokenizer.xml` 時用 `convert_tokenizer <official> --with-detokenizer` 補；檢查四個 IR 檔。來源是驗過雜湊的本機權重（25 是直接給 Hugging Face 的模型名稱）。

### 3.3 失敗處理

| 情況 | 結果 |
|---|---|
| 磁碟空間不足 | 不下載；`Breeze26Error`（訊息見 §3.1） |
| 下載失敗、權重大小或 SHA-256 不符 | 停；不建轉換環境 |
| 建立暫時 venv、轉換器、tokenizer 失敗，或結果不齊全 | 停 |
| 上述任一 | `models/` 底下沒有 26 的目錄（或原本完整的目錄原封不動）；`whisper_ready()` 為 `False`；暫存資料夾已刪 |
| 已經就緒 | 不下載、不轉換（「[OK] Breeze-ASR-26 [ct2] 已存在」） |

---

## 4. 安裝程式與 `setup_backend.py`

### 4.1 Windows（`install.ps1`）

- 參數 `-Breeze26`、`-NoBreeze26`；兩個都給＝不裝（同 `-NoBreeze` 的優先序）。
- 不指定時（在 25 的詢問之後）：
  - `config.json` 已有 `profiles.breeze26` → 不問，印「Breeze-ASR-26（台語或華台混講）：已安裝，保留（要重新實測請加 -Breeze26）」〔規格決定：預設 N 時每次升級都問會讓人誤以為按 Enter 會移除〕。
  - 沒有 → 印三行說明後問「是否安裝 Breeze-ASR-26（台語或華台混講；暫時下載約 6.2 GB，轉換後佔 1.6 GB）？[y/N]」，`y` 開頭（不分大小寫）才裝，其他（含 Enter）不裝。
- 要裝時轉成 `setup_backend.py --breeze26`。
- `-NoBreeze26` 與「不裝」**都不移除**已裝的 26：`setup_backend.py` 只在換後端時才刪掉不同後端的 profile 與模型（2.4.1 的規則，25 也一樣）。
- 失敗不中止安裝〔規格決定：主模型與其他設定此時已寫好，26 是選用模型；中止會讓 skill、捷徑、`runtime_version` 停在舊版〕：`setup_backend.py` 最後一行 JSON 的 `breeze26_error` 有值時，黃字「Breeze-ASR-26 沒有安裝：<原因>」＋加裝指令，其他步驟照常。
- 安裝摘要多一行（有 `profiles.breeze26` 時）：「Breeze-26：ct2 / cuda（RTF 0.0xx）　轉寫時加 --whisper breeze26（台語或華台混講）」。

### 4.2 macOS（`install.sh`）〔推論：未實測〕

- 接受 `--breeze26`／`--no-breeze26`；**不詢問**；`--breeze26` 只印「macOS 本版不提供 Breeze-ASR-26（台語或華台混講），這次略過；其他設定照常安裝」，不轉給 `setup_backend.py`。

### 4.3 `setup_backend.py`

| 用法 | 行為 | exit |
|---|---|---|
| `--breeze26`（安裝程式用） | 主模型選定、`config.json` 寫好之後（在 `--breeze` 之後）準備 26 並實測；失敗只印「[!] Breeze-ASR-26 沒有安裝：…」，最後一行 JSON 多 `breeze26`（profile 或 `null`）、`breeze26_error` | 0 |
| `--breeze26-only` | 沿用 `config.json` 既有的後端，加裝 26 | 成功 0；失敗或後端不提供 1（JSON：`breeze26: null`、`breeze26_error`、`reason: failed｜unsupported`） |
| `--remove-breeze26` | 刪各後端的 26 模型目錄與 `profiles.breeze26`；其他鍵、`profiles.breeze`、25 的模型不動 | 0 |

- 實測：與 25 相同（`breeze_tries()`：主裝置 → ct2 再試 `cpu`／`int8`，openvino 再試 `CPU`；30 秒範例音檔；輸出少於 10 字算失敗）。
- `profiles.breeze26`＝`{"backend", "device", "compute_type", "rtf"}`（與 `profiles.breeze` 同格式）。寫入時**重新讀** `config.json` 再只新增或更新 `breeze26` 這一個鍵（`--breeze` 剛寫過 `profiles.breeze`）。
- 2.4.1 的 `config.json` 讀不了時 exit 5（`--breeze26-only`、`--remove-breeze26` 也一樣，在 `main()` 一開始檢查）。

---

## 5. 入口「辨識模型」選擇題

### 5.1 題目

在「本次專有名詞」之後（2.4.1「使用 Breeze-ASR-25？」的位置），只在 `config.json` 有 `profiles.breeze` 或 `profiles.breeze26` 時問：

```text
辨識模型：Enter＝預設（turbo）／b＝Breeze-ASR-25（中英夾雜很重的技術會議）／t＝Breeze-ASR-26（台語或華台混講，輸出華語文字）
```

| 已安裝 | 題目列出 | 可答 |
|---|---|---|
| 都沒裝 | 不問（同 2.4.1） | — |
| 只有 25 | Enter、`b` | Enter、`b`／`B`、`y`／`Y`〔規格決定：2.4.1 答 `y` 的習慣照舊有效＝25〕 |
| 只有 26 | Enter、`t` | Enter、`t`／`T` |
| 兩個都有 | Enter、`b`、`t` | Enter、`b`／`B`／`y`／`Y`、`t`／`T` |

- 其他答案（含沒有列出的鍵）：第一次印「請輸入 b、t，或直接按 Enter（turbo）」（只列已安裝的鍵）再問一次；第二次還是無效就「沒有這個選項，使用預設（turbo）」（同講者人數題的做法）。
- 對應：`b` → `--whisper breeze`、`t` → `--whisper breeze26`、Enter → 不加 `--whisper`（＝`config.json` 的 `whisper`，安裝時是 turbo）。
- 選 `t` 時接著印一行黃字：「台語會翻成華語文字；人名、機關名、否定句請人工核對」；講者人數答了 `s`（略過說話者分離）時再多一行「沒有說話者分離時，長段雜訊或音樂可能被辨識成句子」（§6.3）。
- 作答時間：`preWaits`／`PRE_WAITS` 的鍵名由 `ask_breeze` 改成 `ask_whisper`（兩次作答時，開始取第一次、結束取最後一次）。**相容性**：`run_log` 的 `wait` 事件只是名稱不同，`runlog.py summary` 與 `runs.jsonl` 的 `wait_sec` 是加總所有等待，不看名稱；2.4.1 以前的 log 照舊是 `ask_breeze`。
- macOS（`mm-dropped.sh`）邏輯相同；因為安裝程式不裝 26，實際上只會出現 Enter／`b`。

---

## 6. 雜訊幻聽處置（`vad_filter`）

### 6.1 背景

〔開發前評估〕26 用 `zh` 時，純白雜訊會被編成通順的句子，`avg_logprob`（-0.94／-0.96）高於 -1.0、`no_speech_prob` 恆為 0，
產品現有的防線（faster-whisper 預設的 no_speech 跳過、`clean()` 的幻覺詞與迴圈壓縮）都擋不住；純靜音不出字。
本版量測 faster-whisper `vad_filter=True`（只對 26）在「有說話者分離」「略過說話者分離」兩條路徑上的前後差異，依條件決定採用與否。

### 6.2 量測（〔實測〕`pro/tests/eval_breeze26_vad.py`）

- 方法：產品 2.5.0 的 `transcribe.py --whisper breeze26 --type meeting --local-only --no-keyframes`（整條路徑：轉檔、說話者分離、ASR、
  `clean()`、分段標點），測試 home 的 `config.json`：ct2／cuda／int8_float16、說話者分離 sherpa、不校正；兩條路徑（有說話者分離／
  `--no-diarize`）× `vad_filter` 關／開，開關的方法是子行程先改 `common.ASR_VAD_FILTER` 再 import `transcribe`（產品程式不加測試旗標）。
  faster-whisper 1.2.1 的 `vad_filter` 用預設參數（Silero VAD）。量測前 `nvidia-smi` 沒有 Type C 計算行程。
- 素材（〔開發前評估〕的素材）：SIL（40 秒數位靜音）、NOISE（40 秒白雜訊，振幅 0.03）、MX（華台混合，合成）、CV（純台語，真人朗讀）、
  EY（台語廣播，真人配音＋配樂）、M1、M2、M3（華語／華英，合成）。
- 指標：CER（開發前評估的計分程式：25 分鐘以下整份一次對齊、M3 每約 10 分鐘一窗；EY 也整份對齊——略過分離時 28 秒窗會跨好幾則廣告，
  逐則切窗會錯位）、數字寫法不計的 CER、整段漏掉（基準段落 10 字以上、時間範圍內完全沒有輸出）、漏句（窗內基準與輸出整串對齊，
  基準段落 10 字以上、70% 以上的字落在「刪除」區段）、SIL／NOISE 有文字的輸出段數。

**有說話者分離**（入口與命令列的預設）

| 素材 | CER（關 → 開） | 數字不計 CER | 整段漏掉 | 漏句 | 有文字的輸出段 |
|---|---|---|---|---|---|
| SIL | — | — | — | — | 0 → 0 |
| NOISE | — | — | — | — | **2 → 0** |
| MX | 4.8% → 4.8% | 5.2% → 5.2% | 0 → 0（/28） | 0 → 0 | 34 → 34 |
| CV | 33.7% → 33.7% | 33.8% → 33.8% | 0 → 0（/72） | 0 → 0 | 192 → 192 |
| EY | 34.8% → 34.8% | 34.3% → 34.3% | 0 → 0（/25） | 0 → 0 | 85 → 85 |
| M1 | 7.8% → 7.8% | 7.5% → 7.5% | 0 → 0（/46） | 0 → 0 | 65 → 65 |
| M2 | 11.5% → 11.5% | 4.0% → 4.0% | 0 → 0（/86） | 0 → 0 | 134 → 134 |
| M3 | 10.6% → 10.6% | 5.8% → 5.8% | 0 → 0（/396） | 0 → 0 | 499 → 499 |

**略過說話者分離**（`--no-diarize`，整檔切 28 秒窗）

| 素材 | CER（關 → 開） | 數字不計 CER | 整段漏掉 | 漏句 | 有文字的輸出段 |
|---|---|---|---|---|---|
| SIL | — | — | — | — | 0 → 0 |
| NOISE | — | — | — | — | **2 → 0** |
| MX | 5.2% → 4.6% | 5.7% → 5.1% | 0 → 0（/28） | 0 → 0 | 9 → 9 |
| CV | 33.5% → **34.7%（+1.2）** | 34.2% → 35.3% | 0 → 0（/72） | 0 → 0 | 45 → 45 |
| EY | 36.2% → 34.6% | 35.5% → 34.1% | 0 → 0（/25） | 0 → 0 | 36 → 36 |
| M1 | 6.5% → 6.4% | 6.4% → 6.3% | 0 → 0（/46） | 0 → 0 | 27 → 27 |
| M2 | 8.7% → 7.4% | 3.0% → 2.7% | 0 → 0（/86） | 0 → 0 | 47 → 47 |
| M3 | 9.5% → 9.6% | 6.5% → 6.5% | 0 → 0（/396） | 3 → 3 | 215 → 215 |

讀法：

- 有說話者分離時，sherpa 仍把 40 秒白雜訊切出 2 段送進 ASR，26 編出「老闆 老闆 老闆 老闆」「老闆 老闆娘，老闆娘。」；開 `vad_filter` 後歸零。
  真語音的段落本來就是人聲，VAD 不會再切掉東西，8 種素材的輸出**逐字相同**。
- 略過說話者分離時，VAD 會改變每個 28 秒窗實際送進模型的音訊，輸出整體上下浮動（MX、EY、M1、M2 變好，CV、M3 變差）。
  逐字比對 CV 另看到：開的時候有一窗少了一整句（約 11 字，「你兒子今年考上哪間大學」），關的時候有一窗輸出整串注音符號亂碼；
  兩者都沒被「整段漏掉」抓到（漏句指標以對齊估計，對這種窗內替換不靈敏）。
- OpenVINO（`WhisperPipeline`）沒有對應的 VAD 參數，不做。

### 6.3 判定與採用

採用條件（雜訊輸出降到 0、真語音 CER 退步 ≤ 1 個百分點、整句漏掉不增加）**逐條路徑判定**：

| 路徑 | 雜訊 → 0 | CER 退步 ≤ 1 | 漏掉不增加 | 結論 |
|---|---|---|---|---|
| 有說話者分離 | ✅ | ✅（逐字相同） | ✅ | **開** |
| 略過說話者分離 | ✅ | ❌（CV +1.2） | ✅ | **不開，改印提醒** |

- `common.ASR_VAD_FILTER = {("breeze26", "ct2")}`；`common.asr_vad_filter(model, backend, diarized)`：組合在表上**而且**有說話者分離才回 `True`。
  `transcribe.py` 依 `speakers_setting != "skip"` 決定，明確傳給 `backends.create(..., vad_filter=)`；`create()` 沒給時以「有說話者分離」為預設
  （`setup_backend.py` 的實測走這個預設）。turbo、25、openvino、mlx 一律不開。
- 開的時候：載入訊息「…（1.3s；vad_filter 開：略過非人聲）」、`run_log` 的 `asr` 檢查點與 `transcript.json` 的 `meta` 多 `vad_filter: true`。
- 略過說話者分離而且用 26 時：`transcribe.py` 在 stderr 印黃字「  [!] 沒有說話者分離時，長段雜訊或音樂可能被辨識成句子」
  （`common.BREEZE26_NO_DIAR_NOTE`）；入口選 `t` **而且**講者人數答 `s` 時，在「台語會翻成華語文字…」之後多印同一句。選 `b`、Enter，或沒有略過時都不印。
- README〈3.1〉與 Portal 常見問題寫明這個限制與做法（有長段音樂、雜訊的錄音不要略過說話者分離）。

---

## 7. SKILL（Claude 對話）

- description 加「會議有人講台語或華台混講可改用 Breeze-ASR-26（台語翻成華語文字）」與觸發詞「台語」「華台混講」（841 字，上限 1,024）。
- 〈模型選擇〉：`profiles.breeze26` 存在＝已裝 26。使用者說會議有人講台語、華台混講（社區、長輩、地方、基層訪談）→ `--whisper breeze26`，並先告訴使用者：台語會翻成華語文字（不是台語漢字）、真人台語約三成字錯、人名機關名否定句要人工核對、不適合直接當正式逐字紀錄；英文術語多的技術會議不用 26。判斷不了時附預估時間：錄音長度 × 對應 profile 的 `rtf`。沒裝時不提；使用者主動要求才說明加裝方式（macOS 不提供）。
- 命令列範例 `[--whisper breeze｜breeze26]`；〈轉寫品質備註〉的模型名稱多 `breeze26`；疑難排解加「加裝 Breeze-ASR-26」「移除 Breeze-ASR-26」兩列。
- `references/corrected-transcript-format.md` 表頭範例的模型：`<turbo/breeze/breeze26>`。

---

## 8. 相容性

### 8.1 Pro

| 項目 | 2.5.0 |
|---|---|
| 2.4.1 的 `config.json` | 照舊可用；升級只改 `runtime_version`，選裝 26 時另外新增 `profiles.breeze26`（`upgrade_config()` 不補任何新鍵：`DEFAULTS` 沒有改） |
| `--whisper breeze`、turbo | 行為不變（`vad_filter` 關、標點、入口預設、安裝預設） |
| runs.jsonl、`run_log` | 欄位不變；`asr_model` 多一種值 `breeze26`；`vad_filter` 只在開時出現；入口的 `wait` 名稱 `ask_whisper`（§5） |
| 降回 2.4.1 | 2.4.1 不認得 `breeze26`（`--whisper breeze26` 會找不到模型）；`profiles.breeze26` 與模型目錄留著不影響 2.4.1 的其他功能，要清掉用 2.5.0 的 `--remove-breeze26` 或手動刪 |

### 8.2 會議記錄校稿

> 每一版 Pro 規格固定有這一節（校稿規格 §10.1 P5、§10.3）。

- **校稿不需改**：〔實測〕查過會議記錄校稿 1.1.2 的程式（`payload/app/*.py`、`static/*.js`），沒有寫死模型別名清單、沒有呼叫 `transcribe.py`、不顯示模型名稱；只讀 `transcript.json` 的 `meta.content_type`、`meta.source` 與找媒體用的 `meta`。
- 校稿規格 §2.2 的介面（`consistency`、`corrections`、`subtitles`、`render_html`、`common` 的那幾個函式、標記格式、`auto_minutes.py --source final`／`--estimate-only`）都沒有改；`common.DEFAULTS` 沒有改。
- 校稿的最低 Pro 版本維持 2.2.0。

| 會議記錄校稿 | Pro 2.4.x | Pro 2.5.0 |
|---|---|---|
| 1.1.x | 全部可用 | 全部可用（26 的逐字稿與其他模型的一樣處理） |

---

## 9. 文件與發行檔

- `THIRD-PARTY-NOTICES.md`：推論引擎表加 Transformers、PyTorch（CPU）、CTranslate2 轉換工具（只在安裝時暫用）；模型表加「MediaTek Research Breeze-ASR-26」；新節〈MediaTek Research Breeze-ASR-26〉：來源、revision、兩個權重的 SHA-256、Apache-2.0 全文連結、只在本機轉換、不散布、訓練資料全部是合成台語語音（官方說明約一萬小時）、輸出華語文字。
- README：開頭一句、功能清單第 3 項、〈2.5.0 新功能〉、功能表一列、新段〈3.1 Breeze-ASR-26（台語／華台混講，選裝，2.5.0）〉（何時用、準確度、限制、速度、安裝與空間、加裝、移除、選用方式、雜訊）、安裝詢問、流程圖、命令列參數、入口流程、`--whisper`、〈準確度與限制〉的台語列、疑難排解兩列、授權表、附錄〈macOS：2.5.0 不提供 Breeze-ASR-26〉。
- `make_dist.py --sync-skill` 重產 `payload/meeting-minutes-pro-upload.zip`；`make_dist.py` 產生 `dist/meeting-minutes-pro-v2.5.0-*`（附錄 A.5）。`make_dist.py` 本身不改。

---

## 附錄 A 實測（〔實測〕2026-11-14，Windows 11、Python 3.12.13、RTX 5060 Ti 16 GB）

環境：已安裝 runtime 的 venv 唯讀使用（`-B`、`PYTHONDONTWRITEBYTECODE=1`）；測試 home 在 repo 外；不呼叫任何雲端模型。

### A.1 單元測試與入口 harness

| 項目 | 結果 |
|---|---|
| Pro `tests/`（不帶 `MMP_TEST_VERSION`，＝2.5.0） | **Ran 723，OK（skipped 3）**＝2.4.1 時的 687＋`test_v250.py` 36（含改寫後的 `test_asr_message` 假模組：`create()` 多收 `vad_filter`） |
| `entry_harness.py`（pwsh 7／Windows PowerShell 5.1／Git Bash） | **219/219**，含新情境 `whisper_*` 14 個 × 3 shell（四種安裝組合、無效輸入、`y`、選 `t`／`b` 又略過說話者分離） |

### A.2 雜訊處置量測

見 §6.2（`pro/tests/eval_breeze26_vad.py`；8 種素材 × 2 條路徑 × 2 種設定，24 次執行都 exit 0）。

### A.3 OpenVINO（CPU）實測

- 暫存 home（`config.json`：openvino／CPU）執行 `setup_backend.py --breeze26-only`：真的下載官方權重（revision 固定、SHA-256 通過）、
  暫時 venv（optimum-intel、openvino 2026.4.1）轉換成 INT8，**5 分 31 秒**完成；轉換時印「Failed to build model wrapper.」與
  「model of type whisper to instantiate a model of type fun_asr」兩行警告，轉換結果齊全、可以載入。暫存資料夾已刪除。
  實測（範例音檔 30 秒）：`profiles.breeze26` = openvino／CPU／RTF 0.192。
- `transcribe.py --whisper breeze26 --no-diarize`（OpenVINO／CPU）與 ct2 的同一路徑比較（vad 關）：

  | 素材 | OpenVINO／CPU | ct2／cuda | 耗時（OpenVINO，含載入） |
  |---|---|---|---|
  | MX（3.4 分） | CER 5.1%（數字不計 5.7%） | 5.2%（5.7%） | 69 秒 |
  | EY（13.4 分，整份對齊） | 34.2%（33.5%） | 36.2%（35.5%） | 239 秒 |

  準確度同級 → openvino **提供**（§2.1）。

### A.4 會議記錄校稿

查 1.1.2 的 `payload/app/*.py`：只讀 `transcript.json` 的 `meta.content_type`、`meta.source` 與 `render_html.find_media()` 需要的 `meta`，
沒有模型別名清單 → 不需改（§8.2）。

### A.5 發行檔

`make_dist.py`：版號一致、權重 0、H-13、參考資料檢查都過。

| 檔案 | 內容 | 大小 | SHA-256 |
|---|---|---|---|
| `meeting-minutes-pro-v2.5.0-installer.zip` | 51 檔 | 504,886 bytes | `619ada7b3be89ea363d86973f7c76f96c760c5cf6c987035abfc3d1e6b643693` |
| `meeting-minutes-pro-v2.5.0-claude-app-upload.zip` | 7 項 | 60,126 bytes | `0e620a1e37c08013c71f6c8dc0acebc12016842411d9b0b1f3f5f569b89e0d09` |

去識別掃描（`deid-scan.mjs --internal-ids`＋私有詞表）：版本目錄、`tests/`、`tools/`、兩個 zip，175 檔（zip 內 71）命中 0。

### A.6 本機升級（2.4.1 → 2.5.0，真實安裝）

- 升級：Windows PowerShell 5.1 執行 dist 解開後的 `install.ps1 -Target Both -Backend ct2:cuda -NoBreeze -NoCorrect -Breeze26`（不加 `-ComputeType`、`-GpuDiar`；stdin 空檔），**exit 0**，3 分 35 秒（含官方權重下載 1 分 34 秒、SHA-256 驗證、暫時 venv、轉換、實測）。
  畫面：「官方權重的大小與 SHA-256 驗證通過」「轉換為 CTranslate2（int8_float16…）」「[選定] Breeze-26：ct2 / cuda / int8_float16（RTF 0.072，約為 turbo 的 2.2 倍時間）」「config.json 設定鍵無變更（runtime_version 更新為 2.5.0）」，摘要多一行 Breeze-26。
- 轉換結果：`models/ct2/breeze-asr-26-ct2/` 13 檔、1,558 MB；`model.bin` SHA-256 `0c4c54c8defeedc9c5f950dc328b88267cd0c12dd14242c0b3dc421059a3faff`，**與開發前評估時自己轉換的模型逐位元相同**；`breeze26-source.json` 記錄 ctranslate2 4.8.5、transformers 4.57.6、torch 2.15.0+cpu。`$MMH/_convert-breeze26/` 已刪除（原始權重、暫時 venv 都不在）。
- `config.json`：只改 `runtime_version`（2.4.1 → 2.5.0）、新增 `profiles.breeze26`（ct2／cuda／int8_float16／RTF 0.0721）；`profiles.breeze`、後端、精度、`privacy.local_only: false`、`diarization.pyannote.status: ready` 都不變。
  詞表、對照表、`opencc_keep.tsv`、`state.json`、`logs/runs.jsonl`、`proofread\` 12 檔、三個 SendTo 捷徑、`venv-gpu-diar`：雜湊或檔數不變。
  `venv` 檔數不變（6,262），安裝程式原有的 `pip install -U -r requirements.txt` 把 `pypdf` 升到 7.1.0（與本版無關）。
- 實測（真實安裝的 2.5.0 scripts 與 venv；合成或公開素材；不呼叫雲端模型；輸出放 repo 外）：

  | 項目 | 結果 |
  |---|---|
  | MX（3.4 分，華台混合） | 說話者分離 pyannote／GPU；`vad_filter` 開；CER 4.6%；ASR 17.3 秒；VRAM 峰值增量 4,051 MiB（含 pyannote）；華語文字輸出 |
  | EY（13.4 分，台語廣播 25 則） | 同上；CER 34.4%；ASR 62.0 秒（每小時約 4.6 分鐘）；VRAM 峰值增量 4,051 MiB；量測前沒有 Type C 計算行程 |
  | `run_log`、runs.jsonl | `asr_model: breeze26`、`vad_filter: true` |
  | NOISE × 有說話者分離 | 0 段（pyannote 對純雜訊照 2.4.1 退回 sherpa） |
  | NOISE × `--no-diarize` | 印「[!] 沒有說話者分離時，長段雜訊或音樂可能被辨識成句子」；輸出 2 段（「鴿仔 鴿仔 鴿仔」，已知限制） |
  | 右鍵入口（本機限定入口，stdin 自動作答）`t` | `--whisper breeze26`、`vad_filter` 開、提醒一行、`wait ask_whisper` |
  | 同上 `b`／Enter | `breeze`／`turbo`，沒有提醒 |
  | 同上 `t`＋講者人數 `s` | `breeze26`、`vad_filter` 關、提醒兩行 |

- 收尾：`logs/runs.jsonl`、`state.json` 用備份還原（雜湊與升級前相同）；暫存素材、輸出、測試 home 都已刪除。
