# meeting-minutes

在**自己的電腦上**把會議錄音轉成逐字稿，再讓 AI 整理成繁體中文會議記錄（摘要、議題、決議、待辦、待釐清問題，每一項附時間碼）。**音檔不上傳。**

支援 Windows（x64）與 macOS（Apple Silicon）；可以用在 Claude CLI（含 Claude 桌面版的 Code 分頁）與 Claude 桌面 App。

📖 **說明網站**：<https://gowerlin.github.io/meeting-minutes/>

## 兩個版本

| | 基本版 `meeting-minutes` | Pro 版 `meeting-minutes-pro` |
|---|---|---|
| 本機轉寫、說話者分離、影片截圖、繁體輸出 | ✅ | ✅ |
| 在 Claude 裡整理成會議記錄 | ✅ | ✅ |
| 固定錯誤對照表、校正版逐字稿、Breeze-ASR-25 | — | ✅ |
| 轉寫後由 GPT（OpenAI）或 Claude（Anthropic）自動做 AI 校正與會議摘要（選用） | — | ✅ |
| 7 種內容類型（會議、課程、訪談、操作教學、座談、工作坊、需求訪談）、自訂範本 | — | ✅ |
| 字幕、網頁版、GPU 說話者分離（選用）、執行 log 與費用 | — | ✅ |
| AI 校正參考影片截圖與會議文件、全文用字統一 | — | ✅ |
| 下載 | [Releases（basic-v…）](https://github.com/gowerlin/meeting-minutes/releases) | [Releases（pro-v…，Latest）](https://github.com/gowerlin/meeting-minutes/releases/latest) |
| 說明 | [基本版](https://gowerlin.github.io/meeting-minutes/basic) | [功能總覽](https://gowerlin.github.io/meeting-minutes/features/) |

兩版可以同時安裝，互不影響。

## 附屬工具：會議記錄校稿

Pro 的附屬工具，另外下載：在瀏覽器裡逐處確認 AI 校正的結果、直接改錯字、自動存檔，產出定稿逐字稿與字幕，常錯的詞勾選後匯入 Pro 的對照表。全部在本機執行，不上傳；需要 Pro 2.2.0 以上（「用定稿重做會議記錄」需要 2.3.0 以上）。

- 下載：[Releases（proofread-v…）](https://github.com/gowerlin/meeting-minutes/releases)
- 說明：[會議記錄校稿](https://gowerlin.github.io/meeting-minutes/features/proofread)、[安裝](https://gowerlin.github.io/meeting-minutes/install/proofread)

## 快速開始

1. 到 [Releases](https://github.com/gowerlin/meeting-minutes/releases/latest) 下載 `…-installer.zip`（安裝包）。
2. **完整解壓縮**。
3. Windows 雙擊 `install.cmd`；macOS 先裝 [Homebrew](https://brew.sh)，再對 `install.command` 按右鍵 →「打開」。
4. 在選單選 `[3] 兩者都裝`，照畫面回答（都可以直接按 Enter），等 5～15 分鐘。
5. 對錄音檔按右鍵 →「傳送到」→「會議轉寫（Pro）」（macOS：把檔案拖到「會議轉寫（Pro）」）。

詳細步驟：[安裝](https://gowerlin.github.io/meeting-minutes/install/)。只用 Claude 桌面 App 的人，另外上傳 `…-claude-app-upload.zip`（不要解開）。

## 隱私

- 語音辨識、說話者分離、分段標點都在本機完成，音檔不會上傳。
- 選用的 AI 校正與會議摘要會把**逐字稿文字**送到你選的 AI（GPT 或 Claude），每次都會先問、寫明要送什麼。
- Pro 2.2 起，AI 校正另外送**影片截圖**（最多 8 張，縮小後）與你放的背景說明、會議文件的名詞和段落；會議摘要不送截圖；文件原檔不送。截圖可以在設定裡關掉（`reference.frames`）。
- 在 Claude 裡整理（Claude Code、Claude 桌面 App；基本版的整理也是）：你附上或讓 Claude 讀取的逐字稿與截圖會送到 Anthropic 的雲端由 Claude 處理；音檔不會送出。對話中沒有「要送出嗎？」這一步，有機敏內容時請不要在對話中讀逐字稿。
- 不記錄逐字稿內容、金鑰與帳號資訊。
- 會議記錄校稿只接受本機連線、不載入外部資源；只有選用的「用定稿重做會議記錄」會把定稿逐字稿送到 Pro 設定的供應商，而且先顯示預估費用、確認才送。

## 文件

- 說明網站：<https://gowerlin.github.io/meeting-minutes/>（安裝、功能、使用方式、常見問題、[更版紀錄](https://gowerlin.github.io/meeting-minutes/releases)、[設計理念與研究方法](https://gowerlin.github.io/meeting-minutes/design/)）
- 公開版規格：[`docs/spec/`](docs/spec/)
- 各版的 README：`pro/meeting-minutes-pro-v<版號>/README.md`、`basic/meeting-minutes-v<版號>/README.md`、`proofread/meeting-minutes-proofread-v<版號>/README.md`

## 給開發者

```text
pro/meeting-minutes-pro-v<版號>/   Pro 最新版（install.*、uninstall.*、README.md、payload/）
pro/tests/                         單元測試、計分程式、合成素材講稿
pro/tools/make_dist.py             打包工具（產生 Release 的兩個 zip）
basic/meeting-minutes-v<版號>/     基本版最新版
proofread/meeting-minutes-proofread-v<版號>/   會議記錄校稿最新版
proofread/tests/                   會議記錄校稿的測試（單元、整合、安裝、打包、瀏覽器）
proofread/tools/make_dist.py       會議記錄校稿的打包工具
docs/spec/                         公開版規格
site/                              說明網站（VitePress）
```

- 跑測試：`cd pro/tests && python -B -m unittest -v`（見 [`pro/tests/README.md`](pro/tests/README.md)）。
- 合成素材：repo 只放講稿，音檔用 `pro/tests/make_materials.py` 重建（需要網路、edge-tts 與 ffmpeg）。
- 打包：`python pro/tools/make_dist.py`。
- 會議記錄校稿：`MMPROOF_TEST_PRO_SCRIPTS=pro/meeting-minutes-pro-v<版號>/payload/runtime/scripts python -B proofread/tests/run_tests.py --only unit,server,dist,browser`（瀏覽器測試要 Playwright 與本機 Chrome；公開 repo 只有 Pro 最新版，有幾項以 Pro 2.2.x 為前提的測試會失敗，見 [給開發者](https://gowerlin.github.io/meeting-minutes/developer)）、打包 `python -B proofread/tools/make_dist.py`。
- 網站：`cd site && npm ci && npm run build`。
- 詳見 [給開發者](https://gowerlin.github.io/meeting-minutes/developer)。

## 開發方式

以 [Better Agent Terminal](https://gowerlin.github.io/better-agent-terminal/) ＋ [Control Tower](https://gowerlin.github.io/Control-Tower/) 協作開發：Control Tower 負責拆工單、派工與驗收紀錄，Better Agent Terminal 負責同時開多個 AI 工作分頁。

## 授權

MIT（[`LICENSE`](LICENSE)）。第三方元件見 [`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md)。語音辨識模型與 pyannote 權重**不在 repo 與安裝包內**：模型在安裝時從官方來源下載；pyannote 權重由使用者自己在 Hugging Face 同意條件後下載。
