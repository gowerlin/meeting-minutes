---
title: 安裝
description: 下載哪個檔、Windows 與 macOS 的安裝步驟、安裝選單每一項的意思，以及安裝完成後會看到什麼。
---

# 安裝

**這頁幫你做到**：把 meeting-minutes-pro（以下簡稱 Pro 版）裝到自己的電腦上。照著步驟做，大約 5～15 分鐘，大部分時間花在下載模型（語音辨識用的 AI 檔案）。

只想用功能比較少、比較簡單的基本版？看[基本版](/basic)。兩版的安裝方式相同。

## 下載哪個檔

<ReleaseDownload product="pro" />

發行檔有兩個 zip，名稱寫出了用途：

| 檔案 | 給誰 | 怎麼用 |
|---|---|---|
| `…-installer.zip`（安裝包） | 要在自己電腦上轉寫的人（右鍵轉寫、拖放轉寫、Claude CLI） | **完整解壓縮**後執行安裝程式，步驟見下面 |
| `…-claude-app-upload.zip`（上傳檔） | 要在 Claude 桌面 App 使用的人 | **不要解開**，直接上傳到 Claude App（見[安裝完成以後](#安裝完成以後)） |

::: tip 用 Claude 桌面 App 的人，兩個檔通常都要
Claude App 裡的 skill 在雲端的沙盒裡執行，用不到你電腦的顯示卡，所以**轉寫還是要在你的電腦上做**：安裝包裝在電腦上負責轉寫，上傳檔給 App 負責整理。其實安裝完成後，桌面上也會出現一份同樣的上傳檔。
:::

## 系統需求

| 項目 | Windows | macOS |
|---|---|---|
| 作業系統 | Windows 10 22H2 或 Windows 11（x64） | macOS 13.5 以上（建議 14 Sonoma 以上） |
| 處理器 | 任何 x86-64 CPU（Intel 或 AMD） | Apple Silicon（M1 以後） |
| 記憶體 | 16 GB 以上 | 16 GB 以上 |
| 磁碟 | 約 3 GB；有 NVIDIA 顯示卡時，安裝過程最多約 6 GB | 約 4 GB |
| 需要先裝的東西 | 不用（Windows 內建的 `winget` 會自動裝好 Python 與 ffmpeg） | [Homebrew](https://brew.sh)（Mac 的軟體安裝工具，要先自己裝；之後會自動裝好 Python 與 ffmpeg） |
| 網路 | 安裝時要連網下載套件與模型；之後轉寫可以完全離線（選用的 AI 校正、會議摘要要連網） | 同左 |

**不支援**：Intel 晶片的 Mac、Windows ARM（Snapdragon）電腦，安裝程式會直接停止。AMD 的 Radeon 顯示卡與 Ryzen AI NPU 目前沒有對應的加速方式，會改用 CPU 轉寫（一樣能用，只是比較慢）。

### 安裝程式會替你挑最快的硬體

安裝時，程式會把你電腦上能用的轉寫方式（例如 Intel NPU、Intel 內顯、NVIDIA 顯示卡、Apple Silicon 的 GPU、CPU）都拿同一段中文錄音試跑一次，選最快的那個記下來。之後每次轉寫都直接用它，不會再重新偵測。

| 硬體 | 用什麼轉寫 |
|---|---|
| Intel 或 AMD 的 CPU（Windows） | OpenVINO CPU（所有 Windows 電腦的保底選項） |
| Intel 內顯、Arc 顯示卡 | OpenVINO GPU |
| Intel NPU（Core Ultra） | OpenVINO NPU（工作管理員「效能」頁籤要看得到 NPU） |
| NVIDIA 顯示卡（Pascal 以後、顯示記憶體 3 GB 以上） | faster-whisper CUDA（驅動要支援 CUDA 12） |
| Apple Silicon GPU | MLX |
| Apple Silicon CPU | faster-whisper CPU（和 MLX 一起試跑，選快的） |

換了顯示卡或更新驅動之後，重新執行一次安裝程式就會重新試跑。

## Windows 安裝步驟

1. 下載安裝包（**meeting-minutes-pro-v<MmVersion />-installer.zip**）。
2. 在檔案上按右鍵 →「**解壓縮全部**」，解到任意資料夾（例如「下載」）。會解出 **meeting-minutes-pro-v<MmVersion />** 資料夾。
   - 一定要**完整解壓縮**，不要在壓縮檔裡直接雙擊執行。
3. 打開解出來的資料夾，雙擊 **`install.cmd`**。
4. 出現黑色視窗與選單，輸入數字選擇安裝目標（見下面〈[安裝選單](#安裝選單)〉），按 Enter。
5. 照畫面回答幾個問題（都有預設值，不確定就直接按 Enter），等待安裝完成。
6. 視窗最後會列出「安裝摘要」，看完按 Enter 關閉。

::: warning 看到 Windows 的藍色警告視窗？
「Windows 已保護您的電腦」：按「其他資訊」→「仍要執行」。這是因為安裝程式是從網路下載的腳本。
:::

## macOS 安裝步驟

1. 先安裝 [Homebrew](https://brew.sh)（已經裝過就跳過）：照它首頁的說明，把那一行指令貼到「終端機」執行。
2. 下載安裝包，在 Finder 雙擊解壓縮，會解出 **meeting-minutes-pro-v<MmVersion />** 資料夾。
3. 在 **`install.command`** 上**按右鍵 →「打開」**，再按一次「打開」。
   - 第一次執行時，macOS 會擋下從網路下載的腳本；用右鍵開啟才能放行。
   - 還是打不開：到「系統設定 → 隱私權與安全性」，按「強制打開」。
4. 終端機視窗出現選單，輸入數字選擇安裝目標，照畫面回答問題，等待安裝完成。

## 安裝選單

```text
  [1] Claude CLI（含桌面版 Code 分頁）：本機轉寫 + 自動產出會議記錄
  [2] Claude App（對話 / Cowork）：右鍵（Windows）或拖放（macOS）轉寫 + 上傳 skill 整理會議記錄
  [3] 兩者都裝（建議）
  [4] 解除安裝
```

| 選項 | 白話說明 |
|---|---|
| **1** | 你平常用 Claude Code（終端機裡的 `claude`，或 Claude 桌面版的「Code」分頁）。Claude 會自己幫你轉寫、整理。 |
| **2** | 你平常用 Claude 桌面 App 的對話。安裝程式會在檔案總管加上右鍵「傳送到 → 會議轉寫（Pro）」與機敏會議用的「會議轉寫（Pro，本機限定）」（macOS 是「應用程式」裡的這兩個 app），並在桌面放一份要上傳到 App 的 zip。 |
| **3** | 兩種都裝。不確定就選這個。 |
| **4** | 解除安裝（見[升級與解除安裝](/install/upgrade#解除安裝)）。 |

選完之後會依序問：

1. **要不要安裝 Breeze-ASR-25**（預設安裝）：一個對台灣華語、中英夾雜的技術會議比較準的辨識模型，速度比預設模型慢好幾倍。裝了之後每次轉寫可以選要不要用（見[提升準確度](/features/accuracy#breeze-asr-25)）。
1. **要不要安裝 Breeze-ASR-26**（2.5 起，**預設不裝**；macOS 不問）：會議有人講台語、華台混講時用的模型，台語會翻成華語文字（見[提升準確度 › Breeze-ASR-26](/features/accuracy#breeze-asr-26-台語)）。

   ```text
     Breeze-ASR-26（MediaTek，台語語音辨識，Apache-2.0）
     - 會議有人講台語、華台混講時用；台語會翻成華語文字（不是台語漢字），人名、機關名、否定句要人工核對
     - 需要約 10 GB 可用空間；安裝時下載官方權重並轉換，多花約 5~20 分鐘
     是否安裝 Breeze-ASR-26（台語或華台混講；暫時下載約 6.2 GB，轉換後佔 1.6 GB）？[y/N]
   ```

   - 要約 **10 GB** 可用空間（裝 runtime 的那顆磁碟）：暫時下載官方權重約 6.2 GB，在你的電腦上轉換後只留約 1.6 GB，暫存檔會刪掉。空間不夠、下載或轉換失敗時，畫面寫原因，其他部分照常裝完。
   - 已經裝過的不會再問，重新安裝也會保留。不詢問直接裝：`install.cmd -Target Both -Breeze26`。
   - 之後才想裝（不用重跑整個安裝）：`"%LOCALAPPDATA%\meeting-minutes-pro\venv\Scripts\python.exe" "%LOCALAPPDATA%\meeting-minutes-pro\scripts\setup_backend.py" --breeze26-only`；移除：同一支加 `--remove-breeze26`。
2. **要不要開啟自動校正**（預設不開，只在第一次安裝時問）：這只影響 Claude CLI 對話裡的行為。右鍵與拖放轉寫**每次轉寫完都會問你**，跟這裡的答案無關。畫面會寫出偵測到哪個 AI 工具、會送到哪一家（找得到已登入的 `codex` 時用 GPT（OpenAI），否則用 Claude（Anthropic））：

   ```text
     自動校正（選用）
     - 偵測：claude CLI 已找到…
     - 偵測：codex CLI  已找到…，登入：是（ChatGPT 帳號）
     - 將使用：GPT（gpt-6.1-sol，透過 Codex）。開啟後，逐字稿文字與影片截圖會送到 GPT（OpenAI）（音檔不會；要關掉截圖：config 的 reference.frames 改成 false）
     是否開啟自動校正？[y/N]
   ```

   沒有已登入的 `codex`、改用 Claude 時，這一行是「將使用：Claude（opus）。開啟後，逐字稿文字與影片截圖會送到 Claude（Anthropic）（…）」。

3. **有 NVIDIA 顯示卡時**：要不要安裝 GPU 說話者分離（預設不裝）。說明見 [GPU 說話者分離（選用）](/install/gpu)。

## 安裝完成以後

安裝摘要會列出選定的硬體、裝了哪些模型與功能。2.4 起另有一行本機限定的狀態：

```text
    本機限定：關（機敏會議用右鍵「會議轉寫（Pro，本機限定）」；整部電腦都不送雲端：config.json 的 privacy.local_only 改成 true）
```

整部電腦開了本機限定時寫「本機限定：開（…）」（見[本機限定](/features/local-only)）。升級時這個設定會保留：從 2.3 升級會補上 `privacy` 這一組設定（預設 `false`，畫面寫「config.json 已補上新版設定鍵：privacy（既有的值不變）」），你改過的值不會被蓋掉。

接下來：

- **選了 1 或 3（Claude CLI）**：skill 已經放進 Claude Code，直接跟 Claude 說「用 meeting-minutes-pro 整理 …」就可以（見 [Claude CLI](/usage/cli)）。
- **選了 2 或 3（Claude App）**：
  1. 在 Windows 檔案總管對錄音檔按右鍵，會看到「傳送到 → 會議轉寫（Pro）」與「會議轉寫（Pro，本機限定）」；macOS 的「應用程式」裡會有這兩個 app（見[右鍵「傳送到」與拖放](/usage/send-to)；本機限定給機敏會議用，見[本機限定](/features/local-only)）。
  2. 桌面上多了 `meeting-minutes-pro-skill-upload.zip`。到 Claude App 依序點「**自訂（Customize）** →「**Skills**」→「**＋**」→「**Create skill**」→「**Upload a skill**」，上傳這個 zip（**不要解開**）。
  3. App 要先在「設定 → Capabilities」開啟程式碼執行功能。
- **想在瀏覽器裡逐處確認 AI 校正的結果**：另外安裝附屬工具[會議記錄校稿](/install/proofread)（選用，需要 Pro <MmVersion product="proofread-min-pro" /> 以上）。

::: danger 不要把安裝包上傳到 Claude App
安裝包裡面還有 zip，Claude App 會擋下並顯示「Zip cannot contain nested zip files」。請上傳桌面上的 `meeting-minutes-pro-skill-upload.zip`，或 Release 的 `…-claude-app-upload.zip`（兩者內容相同）。
:::

## 安裝失敗怎麼辦

- 安裝紀錄在 runtime 資料夾的 `install.log`（Windows：`%LOCALAPPDATA%\meeting-minutes-pro\install.log`；macOS：`~/Library/Application Support/meeting-minutes-pro/install.log`）。
- 公司網路有 proxy 時，先設定 `HTTPS_PROXY` 環境變數再重新安裝。
- 找不到 ffmpeg：開一個新的終端機（Windows 可能要登出再登入），讓系統路徑生效後重新執行安裝程式。
- **一開始就停下，寫「config.json 讀不了」**（2.4.1 起）：`config.json` 壞掉時安裝程式不會蓋掉它，在選單之前就停下、什麼都不寫，以免把你的設定（包括[本機限定](/features/local-only#config-unreadable)）洗掉：

  ```text
  [錯誤] config.json 讀不了：不是合法的 JSON（第 210 行第 1 欄）：%LOCALAPPDATA%\meeting-minutes-pro\config.json
  為了不覆寫你的設定（包括本機限定 privacy.local_only），這次沒有寫入任何東西，檔案沒有被改動。
  請修好這個檔（UTF-8 的 JSON 物件，例如用記事本打開找出錯誤），或刪掉它，然後重新執行。…
  ```

  照原因修好後重新執行；或刪掉 `config.json` 再重新執行（會重新偵測硬體，本機限定是關）。
- 其他狀況見[常見問題與疑難排解](/faq#疑難排解)。

想用命令列一次指定所有選項（不顯示選單），見[手動執行與參數](/usage/advanced#安裝程式的參數)。
