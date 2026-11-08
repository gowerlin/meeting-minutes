---
title: 給開發者
description: 公開 repo 的結構、怎麼跑測試（Pro 與會議記錄校稿）、重建合成素材、打包發行檔、公開版規格，以及網站與去識別掃描。
---

# 給開發者

**這頁幫你做到**：從 repo 跑測試、重建素材、自己打包出和 Release 相同的 zip。一般使用者不需要這頁。

## repo 結構

```text
meeting-minutes/
├─ README.md、LICENSE、THIRD-PARTY-NOTICES.md
├─ pro/
│  ├─ meeting-minutes-pro-v<版號>/   ← Pro 最新版（install.*、uninstall.*、README.md、payload/）
│  ├─ tests/                         ← 單元測試、計分程式、合成素材的講稿
│  └─ tools/make_dist.py             ← 打包工具
├─ basic/
│  └─ meeting-minutes-v<版號>/       ← 基本版最新版
├─ proofread/
│  ├─ meeting-minutes-proofread-v<版號>/  ← 會議記錄校稿最新版
│  ├─ tests/                         ← 單元、整合、安裝、打包、瀏覽器測試
│  └─ tools/make_dist.py             ← 打包工具
├─ docs/spec/                        ← 公開版規格
├─ site/                             ← 這個網站（VitePress）
└─ .github/workflows/pages.yml       ← 建站與部署
```

- 只放**最新版**的目錄。目錄名保留版號（`meeting-minutes-pro-v<版號>/`），因為打包工具與測試從目錄名讀版號；每次發版 git 會看到一次目錄改名。
- 舊版的變化寫在[更版紀錄](/releases)。
- 規格：<RepoLink path="docs/spec/">docs/spec/</RepoLink>（章節號和程式註解裡的「規格 §x.y」對得上）。

## 跑測試

需要 Python 3.10～3.13。測試只用標準函式庫的 `unittest`，不會碰你真正的安裝：

```bash
cd pro/tests
python -B -m unittest -v
```

- 要讀舊版目錄的測試在公開 repo 裡會略過（輸出會列出略過的項目）。
- 需要真實 runtime 的測試，用環境變數 `MEETING_MINUTES_PRO_HOME` 指向測試用的 home。
- 會呼叫 `claude`／`codex` 指令的實測（AI 校正、會議摘要、內容類型筆記）會耗用訂閱額度，**只用合成素材**。各測試的用途與指令見 <RepoLink path="pro/tests/README.md">pro/tests/README.md</RepoLink>。

### 試裝而不碰真實安裝

```powershell
install.cmd -TestRoot <資料夾>
```

```bash
./install.sh --test-root <資料夾>
```

runtime、skill、右鍵捷徑（或 `.app`）、桌面上傳檔都改放到 `<資料夾>` 底下，也不會開啟檔案總管或 Finder；可以和 `-Uninstall` 一起用。

### 會議記錄校稿的測試

```bash
python -B proofread/tests/run_tests.py
```

- 會議記錄校稿要用 Pro 的模組讀寫標記、字幕與對照表，測試自動使用 repo 裡 `pro/` 的 Pro 最新版（唯讀），不碰你真正的安裝。要指定別的 Pro：環境變數 `MMPROOF_TEST_PRO_SCRIPTS` 指向 Pro 的 `scripts`。
- 以舊版 Pro（2.2.x）為前提的情境，測試會從最新版複製一份、只改版號的假 Pro 來測，所以公開 repo 只有最新版也能全部跑。
- 群組：單元、整合（不開瀏覽器）、安裝與移除（沙盒；Windows 另需 PowerShell 7、Windows PowerShell 5.1 與 Git Bash，缺的 shell 略過並列出）、打包、瀏覽器（Playwright＋本機 Chrome 與 Edge）。沒有 Playwright 時加 `--no-browser`；只跑某幾組用 `--only unit,server`。
- 打包群組的「git 執行權限位元」只在開發用的 repo 檢查，公開 repo 會略過（公開 repo 的 `.sh`、`.command` 在 git 裡已設成可執行，clone 下來就能直接執行）。
- 測試只在系統暫存區建假的 Pro 資料夾，不會動你的 `corrections.tsv`、`glossary.txt`。

## 重建合成素材

repo 只放講稿（`pro/tests/materials/`），**不放合成出來的音檔**：音檔由線上語音服務 edge-tts 產生，沒有評估過能否轉散布。用講稿重建：

```bash
cd pro/tests
python -B make_materials.py           # 全部素材；也可以只給名稱，例如 make_materials.py M1
```

- 需要網路、`edge-tts` 套件與 ffmpeg。輸出在 `pro/tests/_out/`（不進版控）。
- 固定亂數種子，重建出的音檔與實測用的逐位元組相同。
- 劣化版素材與操作教學影片要用研究用工具產生，公開 repo 裡沒有；依賴它們的測試會略過。

素材與計分方法見[研究方法](/design/research)。

## 打包發行檔

```bash
python pro/tools/make_dist.py
```

- 預設打包版號最高的版本目錄，產生到 `pro/dist/`（不進版控）：`…-installer.zip`、`…-claude-app-upload.zip` 各一個與各自的 `.sha256`。
- 會先檢查四處版號一致（`common.py` 的 `VERSION`、SKILL 的版本註解、`install.ps1`／`install.sh`、README 標題下的「版本 X」），不一致就停止。
- 版本目錄裡出現模型權重檔就停止：權重不得放進安裝包。
- 同一份 repo 打出的 zip，SHA-256 應與 Release 說明寫的相同。
- 會議記錄校稿：`python -B proofread/tools/make_dist.py`，產生到 `proofread/dist/`（只有安裝包一個 zip 與 `.sha256`）；打包前檢查版號、固定的檔案清單、`.cmd` 的換行與編碼，以及外部網址 0。

## 網站

```bash
cd site
npm ci
npm run dev        # 本機預覽
npm run build      # 建置到 site/.vitepress/dist
```

- 版號與 Release 附件集中在 `site/.vitepress/mm-release.json`，頁面透過元件讀取。
- 公開網址只寫在 `site/.vitepress/config.mts` 的常數裡。
- 推送到 `main` 且改到網站相關檔案時，GitHub Actions 會建站並部署到 GitHub Pages。

### 去識別掃描

`site/scripts/deid-scan.mjs` 掃描個人路徑、內網位址、權杖樣字串、Email 與私有詞表：

```bash
cd site
MM_DEID_TERMS=<私有詞表> MM_DEID_ALLOW=<允許清單> npm run deid        # 網站與建置產物
MM_DEID_TERMS=<私有詞表> MM_DEID_ALLOW=<允許清單> npm run deid:repo   # 整個 repo
```

私有詞表與允許清單由維護者另外保管，不放在 repo 裡；沒有給就不掃描（exit 2）。掃描只印「檔案:行:類別」，不印命中的原文。
