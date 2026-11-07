# meeting-minutes-pro 測試

這個目錄不在版本目錄裡，不會進安裝包。合成音檔、轉寫輸出、下載的模型都放在 `_out/`（`.gitignore` 排除）。
素材全部自寫、虛構，**不得放入真實會議內容**。

## 原則

- **不碰已安裝的 runtime**：一律用 `MEETING_MINUTES_PRO_HOME` 指向測試 home。單元測試沒設定時會自己建暫存 home。
- 可以**唯讀**使用已安裝 runtime 的 venv 執行（加 `-B` 與 `PYTHONDONTWRITEBYTECODE=1`，不在 venv 裡寫 `__pycache__`）。
- 不要對測試 home 用 junction／symlink 指到已安裝的模型目錄；要用就複製。

## 檔案

| 檔案 | 內容 |
|---|---|
| `_testenv.py` | 把版本目錄（預設 v2.1.0；`MMP_TEST_VERSION=2.0.2`、`1.2.2` 等改測舊版，新版才有的測試會略過）的 `scripts/` 放上 `sys.path`、設定測試 home；`VER`（版號 tuple）、`CHUNK_UNIT`（分段單位：1.2.2 起「段」，以前「塊」） |
| `test_opencc_keep.py` | 規格 §4.6 K1～K6（全詞典掃描、該保護／該轉／不誤傷、停用、與對照表／glossary 共存），以及 `corrections.py add` 的回復表提示 |
| `test_punctuate.py` | 分段規則、Whisper 標點整理、標點密度判斷、CT-Transformer 對齊（假模型）、缺模型時的退回；測試 home 有模型時另跑真模型 |
| `test_regression.py` | R 回歸（單元層級）：分段標點關閉時 `transcript.md` 本文與 `.srt` 和 1.0.0 的 `write_outputs()` 相同。1.0.0 的函式放在固定夾具 `fixtures/v100_outputs.py`，沒有舊版目錄也能跑；有 `meeting-minutes-pro-v1.0.0` 目錄時另驗夾具與原檔相同 |
| `test_config.py` | `setting()`、`upgrade_config()`、`correction` 鍵與 S2a `claude` 區塊的遷移（1.1.0）；`MMP_V100_CONFIG` 指向真實 1.0.0 `config.json` 的**副本**時另驗副本；〔2.1.0〕`UpgradeTo210`（H-11）：`html` 區塊的補齊、部分鍵逐鍵補、不認得的值保留原樣、`html_setting()` 讀取時改用預設並印提示 |
| `test_auto_correct.py` | 自動校正（1.1.0）：`provider: auto` 三種情境、切塊、§6.8 驗證、四個呼叫函式的錯誤對應（CLI 用假的 subprocess 結果、API 用假的 SDK 模組）、`run()` 整體流程與錯誤表、條件式自動寫入的五個條件與撤銷；**不呼叫任何模型** |
| `test_runlog.py` | 執行 log（1.2.0）：token 正規化、價格表與費用、檢查點與等待、`MMP_RUN_ID` 的歸屬、`runs.jsonl` 摘要、`wait`／`finish`／`summary` 命令列、log 不含逐字稿片段與金鑰；〔2.1.0〕`HtmlLog`（H-10）：網頁版 checkpoint 欄位、`html` 階段名「網頁版」、summary 不加欄位、log 不含 `.md` 的 6 字片段與媒體檔名；**不呼叫任何模型** |
| `test_auto_minutes.py` | 會議摘要（1.2.0）：讀校正版、分段、彙整、程式合併、部分失敗、錯誤表、輸出格式、紀錄檔不含逐字稿；〔1.2.1〕`V121Boundary`：分段前後文、分段／彙整 prompt 的分段雜訊規則、待辦表時間碼欄與範本一致；〔2.1.0〕`Html`（H-8）：寫完 `.md` 後產生網頁版、`partial`、`--no-html`、`html.enabled: false`、`--render-only`、網頁版丟例外／樣板不存在／寫檔失敗時 `.md`、status、exit code 不變、stdout 與 `auto_minutes.json` 的 `html`；**不呼叫任何模型** |
| `test_setup_backend.py` | 〔1.2.1〕`setup_backend.py --force` 升級保留精度：同後端同裝置沿用既有 `compute_type`、`--compute-type` 照指定、不同時用預設；安裝程式的 `-ComputeType`／`--compute-type` 轉送；假下載、不碰已安裝的 runtime |
| `test_v122.py` | 〔1.2.2〕入口詢問前清空鍵盤緩衝（靜態檢查；PowerShell 7／5.1 在隱藏的新主控台用 `WriteConsoleInput` 注入按鍵實測，含對照組；bash 管線，有 WSL 時在 pty 實測）、待釐清問題規則與例句不取自素材、使用者可見字串沒有「塊」、安裝中的版號提示與「更新設定」措辭（直接執行安裝程式內嵌的 Python 片段）；**不呼叫任何模型**。沒有 WSL 時 pty 實測略過（`MMP_TEST_NO_WSL=1` 也可略過） |
| `test_diarize.py` | 〔2.0.0〕說話者分離（規格 §4）：保留前 N 位（D-3）、講者統計與表頭行（D-4）、引擎選擇與退回（D-5：status、假的 `nvidia-smi`、VRAM、macOS、假子行程的各種 reason、逾時、壞 JSON）、主行程不 import torch 與子行程環境變數（D-6）、`transcribe.py` 整個流程（假 ASR／sherpa／子行程）、類型與範本的優先序、`content_types` 骨架、`type_setting()`；log 不含逐字稿與子行程 stderr（L-1 分離部分）；**不呼叫任何模型、不需要 GPU** |
| `test_templates.py` | 〔2.0.0〕自訂範本（規格 §3.8）：驗證表每一列（TP-1：`parse_error`、`missing_key`、`bad_base`、`unknown_key` 整份不載入、`bad_value`、`bad_file`、`secret_like`、`not_found`）、設定區的有限語法、整理重點只取第一個 `## ` 之後、2,000 字截斷、`labels` 可用的鍵、`templates.py list`／`check`、`transcribe.load_template()` 的介面；**不呼叫任何模型** |
| `fake_diarize_pyannote.py` | 〔2.0.0〕假的 `diarize_pyannote.py`（`FAKE_PYANNOTE_MODE`＝ok／`fail:<reason>`／sleep／badjson／nojson／wrongshape／empty／overlap／noisy；`FAKE_PYANNOTE_RECORD` 記下收到的參數與環境變數） |
| `eval_diar.py` | 〔2.0.0〕說話者分離實測與計分（D-1～D-4、D-6）：`sherpa`（類型門檻＋保留前 N 位）、`pyannote`（GPU 子行程，與產品同一條路徑）、`gpu-release`（子行程結束後 `nvidia-smi` 的計算行程）、`report`（判定表）。計分由 2.0.0 開發期的研究腳本移來：`diar_sweep.py` 的段落標籤正確率、`diar_eval.py` 的 DER／講者混淆（collar 0.25 s） |
| `entry_harness.py` | 入口（`mm-sendto.ps1`／`mm-dropped.sh`）流程實測：假 runtime＋假 `claude`／`codex`，13 個情境（1.2.1 另加 `sonnet_notes`：摘要選單 sonnet「較快」、校正選單「準確率較低」）× PowerShell 7／5.1／Git Bash；**不呼叫任何模型**。Git Bash 要用不在 Temp 底下的 `--work`（例 `_out/entry`）。〔2.0.0〕規格 §10.2 E-1：1.x 的情境在答案最前面自動補一個 Enter（類型＝會議）；2.0 另加 11 個情境：`upgraded_122`（1.2.2 設定升級後 4 次 Enter＝會議＋1.2.2 結果）、`type_course_skip`（課程＋`s`）、`template_menu`／`template_skip_default`（有效與無效範本、範本人數當預設）、`remember_last`（同一個 runtime 跑兩次，第二次 Enter＝上次）、`remember_off`、`remember_template_gone`、`state_unwritable`（`state.json` 是資料夾）、`bad_inputs`、`speakers_number`、`end_screen_v2`（字幕條數、退回 CPU 的原因、零星講者）；並檢查 `wait` 有 `ask_type`。〔2.0.1〕另加 3 個情境：`first_run_no_state`（沒有 `state.json`）、`state_broken_json`、`state_empty`（Enter＝會議，照常寫入這次的選擇）；2.0.1 起**每個情境**都檢查主控台與 stderr 沒有錯誤訊息（`ERROR_MARKERS`），`MMP_TEST_NOERR=1` 可對舊版開啟當對照組。`--work` 要給絕對路徑（相對路徑會讓 Windows PowerShell 5.1 因 `USERPROFILE` 不是絕對路徑而起不來）。〔2.1.0〕網頁版（規格 2.1.0 §7.1）：假 `auto_minutes.py` 在 runtime 有 `common.html_setting` 時照真的程式寫 `auto_minutes.json` 的 `html` 與 `.html`（讀 `html.enabled`、`--no-html`；`FAKE_HTML`＝`found`／`explicit`／`none`／`unsupported`／`off`／`failed:<reason>`）；另加 11 個情境：`html_found`、`html_explicit`（時間碼可點播放）、`html_text_none`／`_unsupported`／`_off`（時間碼為文字）、`html_course`（`notes.html`）、`html_disabled`（`html.enabled: false` 不列）、`html_failed`／`html_failed_internal`（黃字原因與 `render_html.py` 補做指令）、`html_minutes_no`（沒整理不列）、`upgraded_202`（2.0.2 的 `config.json` 升級後全部按 Enter）；新檢查 `rows`（結束畫面的檔案列，依序）：1.x／2.0.x 升級的情境在 2.1.0 只多 `.html` 一列（測 2.0.2 時同一份清單去掉 `.html`），`cfg_html`（升級後 `html.enabled`） |
| `test_subtitles.py` | 〔2.0.0〕字幕（規格 §5）：對應（修改、刪除、補字、跨段、S? 拆段、姓名、文件層級、手改退回）、字幕規則、U6 三種顯示、`transcript.srt` 與 1.2.2 逐位元相同、失敗退回、`transcribe.main()`／`auto_correct` 接線；**不呼叫任何模型**。計分指令：`map <資料夾…>`（S-1）、`rules <srt…>`、`timing <素材> <srt…>`（S-2）、`derive <來源> <目的> names\|merged\|edited`（做 S-1 變化案例）；例：`oracle_correct.py` 產生理想校正 → `test_subtitles.py map` |
| `test_v200_install.py` | 〔2.0.0〕入口與安裝程式（規格 §7、§8、§9.5、§10.4）：`setup_gpu_diar.py` 的 Hugging Face 引導（開瀏覽器 Y／n／開不了、有沒有帳號、未登入、登入失敗、未同意＋重試、下載失敗、連不上、權重已在）——`huggingface_hub`、瀏覽器、`hf auth login` 全部用假的，`HF_HOME`／`HF_HUB_CACHE` 指向空的暫存目錄、不設 `HF_TOKEN`；`--check-torch`（假 torch）、`--smoke` 缺範例音檔、`--set-status` 與 `upgrade_config()`；安裝程式版號四處一致、新參數、GPU 原因表與 `setup_gpu_diar.REASON_TEXT` 一致、內嵌「更新設定」片段寫入 `diarization.pyannote`（`install.sh` 一律 `none`）、`install.sh` 沒有 GPU 安裝且是 bash 3.2 語法；兩支入口的類型表與 `content_types.py` 一致；`runlog` 字幕階段；upload zip 與 `payload/skill` 一致；〔2.0.1〕`NoRedTextInTry`：兩支 PowerShell 腳本 `try { … }` 同一行裡的讀檔／查詢 cmdlet 都有 `-ErrorAction Stop`（或 `SilentlyContinue`）、`Read-State` 先 `Test-Path`。`MMP_SHOW_GUIDE=1` 印出 mock 情境的引導畫面全文 |
| `test_render_html.py` | 〔2.1.0〕網頁版（規格 2.1.0 §9.1）：H-1 七種類型＋`base: meeting` 自訂範本（假呼叫器產生 `.md`／`.html`；目錄、錨點、時間碼、摘要卡；有 `meeting-minutes-pro-v2.0.2` 目錄時 `.md` 與 2.0.2 逐位元比對）、H-2 Markdown 子集與不完整寫法、H-3 注入、H-4 錨點、H-5 時間碼、H-6 媒體定位、H-7 外部請求 0 的檢查函式 `assert_offline()`（每份輸出都跑）、H-9 `render_html.py` 命令列 exit code、`--md` 不寫 log、沙盒（沒有 `common.py`）、不 import 會呼叫模型的模組、H-12 CSP 雜湊；**不呼叫任何模型**。H-13（`make_dist`）在 `test_make_dist.py` |
| `test_asr_message.py` | 〔2.1.0〕`transcribe.load_asr()` 的 console 訊息印實際模型名（2.1.0 的載入訊息修正）：選 Breeze 時成功／失敗訊息寫「Breeze-ASR-25」不寫「Whisper」；Whisper 別名印完整模型名（`turbo` →「Whisper large-v3-turbo」）、不在對照表上的值印「Whisper <原值>」、每個 `WHISPER_MODELS` 別名都有顯示名稱；後端與裝置照舊附在後面。用假的 `backends` 模組，不載入真模型、不需要 GPU；2.1.0 以前的版本整個略過 |
| `test_make_dist.py` | 〔2.0.0〕`tools/make_dist.py` 的模型權重檢查（規格 §9.5）：暫存目錄的假版本目錄有 `pytorch_model.bin`、`*.npz`（不分大小寫）→ exit 2、印出路徑、不動 `dist/`；檢查在 `git ls-files` 之前；名稱相近的檔不算；目前版本目錄沒有權重。〔2.0.2〕`--product basic`。〔2.1.0〕H-13（`SkillScriptsCheck`、`RealHtmlVersionDir`）：`render_html.FALLBACK_VERSION`＝`common.VERSION`、skill 內 `scripts/` 兩檔與 runtime 逐位元相同，不符合 exit 2、不動 `dist/`；沒有網頁版的版本目錄與基本版不查；`--sync-skill` 複製兩檔並重產 payload zip（含 `scripts/`）；暫存 git repo 實際打包；真的 2.1.0 目錄通過 |
| `eval_minutes.py` | 會議摘要的實測與計分（1.2.0 起）：`prepare`、`run`（有呼叫上限）、`score`（涵蓋率、杜撰候選、時間碼、耗時、token、費用；〔1.2.2〕待釐清問題的必列／選列涵蓋與逐列清單） |
| `eval_modes.py` | 〔2.0.0〕內容類型筆記的實測與計分（T-1、T-2、F-1、TP-2）：`prepare`、`run`（有呼叫上限，同 `eval_minutes.py`）、`score`（涵蓋率、別處、時間碼、杜撰候選、引述逐字比對；讀產品的 `notes.json`）、`frames`（TU1.mp4 的畫面偵測張數與掛到的步驟對不對）、`inject`（最長相同片段、假列、工具項目）。計分由 2.0.0 開發期的研究腳本移來 |
| `materials/minutes-ref.json` | 會議摘要的計分基準：M1、M2 講稿的決議、待辦、議題、下次會議（M3＝M1 ∪ M2）；〔1.2.2〕`questions`：會中有人提出、到最後沒有答覆或決定的問題（`optional: true` 為選列） |
| `test_download.py` | 標點模型下載：失敗模擬；`MMP_PUNCT_ARCHIVE` 指向真的壓縮檔時驗 SHA-256 與離線安裝 |
| `materials/M1-tech-meeting.txt` | M1 技術會議講稿（4 位講者，約 10 分鐘）＝基準稿 |
| `materials/M2-business-meeting.txt` | M2 一般業務會議講稿（3 位講者，約 17.5 分鐘）＝基準稿 |
| `materials/M3-long-meeting.txt` | M3 長會議講稿（4 位講者，約 79 分鐘；由 `make_m3.py` 從 M1、M2 改寫拼接產生，不要手改） |
| `make_m3.py` | 產生 M3 講稿（之後照 `make_materials.py M3` 合成） |
| `materials/CL1-course-lecture.txt` | 〔2.0.0〕課程講稿（講師＋2 位學員、3 次提問，約 12.7 分鐘）＝基準稿；2.0 內容類型「課程」 |
| `materials/CL2-course-long.txt` | 〔2.0.0〕長課程（約 64 分鐘）：`@include` CL1 五輪（第二輪起換數字與名稱），給長錄音的說話者分離與分段摘要用；不另做摘要基準 |
| `materials/IV1-interview-show.txt` | 〔2.0.0〕訪談節目講稿（主持人＋2 位來賓，約 15 分鐘）＝基準稿 |
| `materials/TU1-tutorial-demo.txt` | 〔2.0.0〕操作教學講稿（講師＋助教，約 5.6 分鐘）；`eval_modes.py frames` 用的 `_out/TU1.mp4` 是另外配上每步換一次的投影片做成的（2.0.0 開發期的研究腳本，不在本目錄） |
| `materials/PN1-panel-forum.txt` | 〔2.0.0〕座談講稿（主持人＋3 位與談人＋1 位觀眾，約 5.4 分鐘） |
| `materials/WS1-workshop-retro.txt` | 〔2.0.0〕衝刺回顧講稿（引導者＋3 位成員，約 4.9 分鐘） |
| `materials/RQ1-requirements-interview.txt` | 〔2.0.0〕需求訪談講稿（顧問＋客戶 2 位，約 5.2 分鐘） |
| `materials/content-modes-ref.json` | 〔2.0.0〕2.0 內容類型筆記的計分基準（CL1、IV1、TU1、PN1、WS1、RQ1；鍵＝範本草案的欄位）；計分程式 `tests/eval_modes.py`（〔2.0.0〕由研究目錄移來） |
| `make_materials.py` | edge-tts 合成 → `_out/<名稱>.wav`、`_out/<名稱>.ref.json`（需要網路與 ffmpeg）。預設全部素材；〔2.0.0〕講稿可用 `@include <名稱> [gap=秒] [舊=新 …]` 拼接另一份講稿；`<秒數>` 只能寫在段首（段中會報錯）；edge-tts 180 秒沒回應就重試 |
| `run_matrix.py` | 跑轉寫：turbo／Breeze、R 用的 `--no-punct --no-opencc-keep --no-correct`、1.0.0。預設用 `meeting-minutes-pro-v1.1.0` 的 scripts，`--scripts` 可指定其他版本；目錄不存在時印出原因後結束（exit 0） |
| `eval_materials.py` | P1～P4、K7、R 的數字（讀 `_out/runs/`）；`--repunct` 不重跑辨識、用目前的 `punctuate.py` 重新分段標點後再評估 |
| `eval_correct.py` | 自動校正的實測與計分（C1～C5、C1-O）：`prepare`（重新標點、換成素材自己的專有名詞）、`errors`（已知錯誤清單）、`run`（有呼叫上限）、`score`（1.1.0 起另列「修對＋推測對」與逐段退回率 `c2`） |

## 執行（Windows，Git Bash）

```bash
PY="$LOCALAPPDATA/meeting-minutes-pro/venv/Scripts/python.exe"   # 已安裝 runtime 的 venv，唯讀使用
export PYTHONDONTWRITEBYTECODE=1
HOME_T="<暫存目錄>/mmh"     # 測試 home：放 config.json 副本、glossary／corrections 範例、模型（複製，不要連結）

# 單元測試（K1～K6、分段標點、R、設定、下載）；_testenv 預設 2.1.0；舊版：MMP_TEST_VERSION=2.0.2（新版才有的測試會略過）
cd tests
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B -m unittest -v

# 標點模型下載到測試 home（驗 SHA-256）
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B ../meeting-minutes-pro-v2.1.0/payload/runtime/scripts/download_models.py --punct-only

# 素材、轉寫、評估（P1～P4、K7、R）
"$PY" -B make_materials.py
"$PY" -B run_matrix.py --home "$HOME_T" --v100 "<1.0.0 的 scripts 目錄>"   # 需要 v1.1.0 與 1.0.0 的目錄（公開 repo 只有最新版，見表格）
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_materials.py

# 自動校正實測（會呼叫 claude -p／codex exec，耗用訂閱額度；只用合成素材）
OUT="<暫存目錄>/c"
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_correct.py prepare M1 "$OUT/M1-base"
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_correct.py errors M1 "$OUT/M1-base"
cp -r "$OUT/M1-base" "$OUT/M1-sonnet"
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_correct.py run "$OUT/M1-sonnet" --budget-file "$OUT/budget.json"     --tool claude --max 30 --provider claude --model sonnet --effort medium
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_correct.py score M1 "$OUT/M1-sonnet"
```

```bash
# 〔2.0.0〕說話者分離（sherpa 只用 CPU；pyannote 要 NVIDIA＋GPU venv＋本機權重，權重目錄與 venv 都只讀）
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_diar.py sherpa --out "$OUT/sherpa.json" PN1=0.8 IV1=0.8,0.9 CL2n=0.8,1.0 M1=0.8,0.9
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_diar.py pyannote --out "$OUT/d1.json" --python "<GPU venv>/Scripts/python.exe" \
    --model-dir "<權重目錄>" M1 M1:4 M3 M3:4 CL1 CL1:3 IV1 IV1:3
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_diar.py gpu-release --python … --model-dir … CL1
"$PY" -B eval_diar.py report "$OUT/d1.json" "$OUT/sherpa.json"
```
- pyannote 子行程一律 `HF_HUB_OFFLINE=1`、`PYANNOTE_METRICS_ENABLED=0`（不連網、不送使用統計、不需要權杖）；量 GPU 耗時前先看 `nvidia-smi` 有沒有其他計算行程。
- `eval_correct.py run` 每次實際呼叫前先在 budget 檔記一筆，達到 `--max` 就拒絕送出（`eval_minutes.py run` 相同）。

```bash
# 入口流程（不呼叫模型）
"$PY" -B entry_harness.py --work "$(cygpath -m "$(pwd)")/_out/entry"
# 會議摘要實測（會呼叫 claude -p／codex exec；只用合成素材）
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_minutes.py prepare M3 "$OUT/M3-sol"
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_minutes.py run "$OUT/M3-sol" --budget-file "$OUT/budget-codex.json" --tool codex --max 15 --model gpt-6.1-sol --effort low
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_minutes.py score M3 "$OUT/M3-sol"
```
- 計分的「已知錯誤」＝辨識結果與基準稿的取代區段，排除數字寫法（八百／800）、異體字（周／週、瞭／了、記／紀）、ASR 整段漏掉或多出的字；同一個英文字被切成好幾段時併成一處。

## 〔2.0.0〕會議待釐清的判準（C-M、C-M2）

- 必列（`minutes-ref.json` 的 `questions`，`optional` 以外）：M1 的 M1-Q1、M2 的 M2-Q1 與 M2-Q2、M3 的三題（M1 ∪ M2）。
  計「有沒有出現在〈五、待釐清問題與風險〉的一列」；寫在議題、決議或待辦只算「別處」，**仍算漏列**。
- **M2-Q2（夏季庫存出清後剩下約 300 萬怎麼處理）維持必列**：原話「要先收到應收帳款才行」「這個要一起考慮」只講了條件，
  沒有講好怎麼決定、由誰決定或什麼時候決定，屬規則 6 (a) 收窄後「仍然要列」的那一種。寫成議題結論而沒列進〈五〉＝漏列。基準不改。
- 門檻（規格 §10.2 C-M）：sol `low`、opus `medium` 各 2 次，任一次漏列即未達標；決議／待辦／議題不低於 1.2.2 規格附錄 H.2；杜撰 0（逐列人工判定）。

```bash
# 〔2.0.0〕內容類型筆記（會呼叫 claude -p／codex exec；只用合成素材）
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_modes.py prepare CL1 "$OUT/CL1-sol"
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_modes.py run "$OUT/CL1-sol" --type course --budget-file "$OUT/budget-codex.json"     --tool codex --max 24 --model gpt-6.1-sol --effort low
MEETING_MINUTES_PRO_HOME="$HOME_T" "$PY" -B eval_modes.py score CL1 "$OUT/CL1-sol"
# F-1：先用 2.0 transcribe.py 轉 TU1.mp4（--type tutorial，畫面門檻 0.1），整理成 notes.json 後
"$PY" -B eval_modes.py frames "$OUT/TU1-video"
```
