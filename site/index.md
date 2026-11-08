---
layout: home
title: 首頁
description: 在自己的電腦上把會議錄音轉成逐字稿，再讓 AI 整理成繁體中文會議記錄；音檔不上傳。

hero:
  name: 會議錄音，交給自己的電腦
  text: 本機轉成逐字稿，AI 整理成會議記錄
  tagline: 錄音檔留在你的電腦上，不上傳。轉寫完成後，可以讓 GPT（OpenAI）或 Claude（Anthropic）校正錯字、整理出摘要、決議與待辦，每一項都附時間碼，方便回頭聽；兩者都能用時預設 GPT。
  image:
    src: /logo.svg
    alt: ''
  actions:
    - theme: brand
      text: 開始安裝
      link: /install/
    - theme: alt
      text: 我該選哪一版？
      link: '#which'
    - theme: alt
      text: 常見問題
      link: /faq

features:
  - icon: 🗂️
    title: 7 種內容類型
    details: 會議之外，也能整理課程、訪談節目、操作教學、座談、工作坊、需求訪談，各自產出合適的筆記；還能自己寫範本。
    link: /features/content-types
    linkText: 看看各類型的筆記
  - icon: ✍️
    title: 校正版逐字稿與字幕
    details: 原始逐字稿一字不改，另外產出標出每一處修改的校正版，以及照字幕規則切好的字幕檔，可以搭配影片回放。
    link: /features/ai-correction
    linkText: AI 校正怎麼運作
  - icon: 🧾
    title: 執行 log 與費用
    details: 每次轉寫都記下各步驟花了多久、模型用了多少 token、換算成 API 大約多少錢；不記逐字稿內容與金鑰。
    link: /features/run-log
    linkText: 看 log 能知道什麼
---

<div class="mm-home">

<ReleaseDownload product="pro" compact />

## 三步驟就能用

<StepFlow :steps="[
  { title: '下載並安裝', text: '下載安裝包、解開，雙擊 install.cmd（Windows）或 install.command（macOS）。第一次約 5～15 分鐘。' },
  { title: '對錄音檔按右鍵', text: 'Windows：右鍵 →「傳送到」→「會議轉寫（Pro）」。macOS：把檔案拖到「會議轉寫（Pro）」。' },
  { title: '回答幾個問題', text: '內容類型、講者人數都可以直接按 Enter。轉寫完再決定要不要做 AI 校正與會議摘要。' },
  { title: '打開輸出資料夾', text: '錄音檔旁邊會出現「檔名_minutes」資料夾，裡面有逐字稿、會議記錄（另有可點時間碼回聽的網頁版）與字幕。' }
]" />

## 會議記錄校稿（Pro 的附屬工具） {#proofread}

<ProofreadIntro />

## 你的錄音去了哪裡

- **轉寫全在你的電腦上**：語音辨識、說話者分離、分段標點都在本機完成，音檔不會上傳到任何地方。
- **選用的 AI 校正與會議摘要**：逐字稿**文字**送到你選的 AI（GPT 或 Claude），不送音檔。AI 校正另外送**影片截圖**（最多 8 張，縮小後）與你放的背景說明、會議文件的名詞和段落，用來補上與會者全名與會議日期；會議摘要不送截圖。每次都會先問你、寫明要送什麼，直接按 Enter 才會送出；截圖可以在設定裡關掉（[參考資料](/features/reference)）。
- **在 Claude 裡整理**（Claude Code、Claude 桌面 App）：你附上或讓 Claude 讀取的逐字稿與截圖，會送到 Anthropic 的雲端由 Claude 處理；音檔不會送出。對話中沒有「要送出嗎？」這一步，有機敏內容時請不要在對話中讀逐字稿。

詳細說明見[AI 校正與會議摘要](/features/ai-correction#送出去的是什麼)與[常見問題](/faq)。

## 我該選哪一版？ {#which}

| | 基本版 meeting-minutes | Pro 版 meeting-minutes-pro |
|---|---|---|
| 本機轉寫、說話者分離、影片截圖 | ✅ | ✅ |
| 在 Claude 裡整理成會議記錄 | ✅ | ✅ |
| 固定錯誤對照表、校正版逐字稿 | — | ✅ |
| 自動 AI 校正、自動會議摘要 | — | ✅（選用） |
| 7 種內容類型、自訂範本、字幕 | — | ✅ |
| 參考影片截圖與會議文件、全文用字統一 | — | ✅ |
| GPU 說話者分離（NVIDIA） | — | ✅（選用） |
| 執行 log 與費用 | — | ✅ |
| [會議記錄校稿](/features/proofread)（附屬工具，另外下載） | — | ✅（選用） |

- 第一次用、只想把會議錄音轉成逐字稿再請 Claude 整理：**基本版**就夠了（[基本版介紹](/basic)）。
- 想要準確度更高、自動校正、整理課程或訪談、要字幕：選 **Pro 版**。
- 兩版可以同時安裝，互不影響。

## 支援的電腦

| | Windows | macOS |
|---|---|---|
| 系統 | Windows 10 22H2 或 Windows 11（x64） | macOS 13.5 以上，Apple Silicon（M1 以後） |
| 記憶體 | 16 GB 以上 | 16 GB 以上 |
| 磁碟 | 約 3 GB（有 NVIDIA 顯示卡時，安裝過程最多約 6 GB） | 約 4 GB |

安裝時會自動找出你的電腦上最快的轉寫方式（Intel NPU／GPU、NVIDIA 顯示卡、Apple Silicon 或 CPU），不必自己設定。完整條件見[安裝](/install/#系統需求)。

## 開發方式 {#how-we-build}

meeting-minutes（Pro、基本版與會議記錄校稿）是用 <DevTools /> 協作開發的：Control Tower 負責把需求拆成工單、派工，並留下每一次的驗收紀錄；Better Agent Terminal 負責同時開好幾個 AI 工作分頁，讓不同的工作並行。兩個工具都有自己的介紹網站，想用同樣方式開發的人可以從上面的連結開始。

</div>
