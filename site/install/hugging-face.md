---
title: Hugging Face 白話引導
description: 為什麼 GPU 說話者分離需要 Hugging Face 帳號，註冊、同意條件、建立存取碼、hf auth login 每個畫面怎麼回答。
---

# Hugging Face 白話引導

**這頁幫你做到**：第一次碰到 Hugging Face 也能把 GPU 說話者分離的模型下載好。只有要裝 [GPU 說話者分離](/install/gpu) 的人需要看這頁。

## 為什麼要帳號

- **Hugging Face** 是放 AI 模型的網站，像是模型的「應用程式商店」。
- GPU 說話者分離用的模型（pyannote 的 `speaker-diarization-community-1`）由作者放在那裡。作者要求下載的人**先登入、同意使用條件**，才能下載。帳號免費。
- 本程式**不代你同意**條件，也**不散布**這個模型：模型由你自己的帳號下載到你的電腦。
- 本程式只用帳號來下載模型，**不會讀取或保存你的帳號資料與存取碼**。下載完之後，轉寫時不需要登入，也不連網。

## 步驟

安裝程式問「要幫你開啟瀏覽器嗎？」時按 Enter，它會依序幫你打開下面的網頁；每做完一步回到安裝視窗按 Enter，再進下一步。

### 1. 註冊或登入

- 網址：<https://huggingface.co/join>（已經有帳號就直接登入）。
- 註冊時填電子郵件與密碼，再到信箱點確認信。

### 2. 同意模型的使用條件

- 網址：<https://huggingface.co/pyannote/speaker-diarization-community-1>
- 頁面上方會寫「You need to agree to share your Hugging Face information to access this model」（要同意分享你的 Hugging Face 資料才能使用這個模型）。填兩欄後，按同意的按鈕（英文，例如 Agree…）：

| 欄位 | 意思 | 怎麼填 |
|---|---|---|
| Company/university | 公司或學校 | 個人使用填「個人」或「Personal」即可 |
| Use case | 用途（下拉選單） | 會議記錄選「Meeting note taker …」；整理課程可以選「Training and development …」；不確定就選「Other」 |

- 你填的資料會交給模型作者（pyannote）。作者說明可能偶爾寄送 pyannote 的消息、付費服務的試用邀請等資訊。
- 同意後通常立刻可以下載，偶爾要等幾分鐘。

### 3. 建立「存取碼」（Access Token）

存取碼是一組像密碼的字串，讓本程式代你下載模型。

1. 網址：<https://huggingface.co/settings/tokens>
2. 按「**Create new token**」。
3. 類型（Token type）選「**Read**」（唯讀，只能下載、不能改你的帳號）。
4. 名稱隨意填，例如 `meeting-minutes-pro`，按建立。
5. 按複製鈕，複製那串 `hf_` 開頭的字。**它只會顯示一次**；忘了也沒關係，再建一個就好。

::: warning 存取碼就像密碼
不要貼到聊天室、Email 或任何文件裡。只貼進下一步的安裝視窗。
:::

### 4. 把存取碼貼進安裝程式

安裝程式問「現在登入？[Y/n]」時按 Enter，接著出現 Hugging Face 的登入程式（`hf auth login`）：

```text
How would you like to log in?
```

（要怎麼登入？）

1. 按方向鍵 ↓ 選「**Paste an access token**」（貼上存取碼）再按 Enter，或直接按數字 **2**。
2. 出現下面這行時，貼上存取碼：

   ```text
   Enter your token (input will not be visible):
   ```

   - Windows Terminal：按 **Ctrl＋V**。
   - 舊式黑色視窗：按**滑鼠右鍵**。
3. **貼上時畫面不會顯示任何字，這是正常的**（為了不讓旁人看到）。貼完直接按 Enter。

另一個選項「Log in with your browser」（用瀏覽器登入）會給你一個網址和代碼，在瀏覽器登入後輸入代碼即可，不必自己建存取碼。不過這個方式還沒實測過，不確定能不能下載需要同意條件的模型；建議用貼存取碼的方式。

### 5. 等它下載完

畫面出現「已登入，正在下載權重（約 33 MB）」→ 下載完成後，安裝程式用範例錄音實測一次。安裝摘要寫「說話者分離：GPU（pyannote，可用…）」就完成了。

沒有成功？看 [GPU 說話者分離 › 裝失敗也沒關係](/install/gpu#裝失敗也沒關係) 的原因表。

## 登出

登出不影響使用：權重已經在你的電腦上，之後轉寫不需要登入。要登出的話，二選一：

- 執行 `"%LOCALAPPDATA%\meeting-minutes-pro\venv-gpu-diar\Scripts\hf.exe" auth logout`
- 刪除 `%USERPROFILE%\.cache\huggingface\token` 這個檔（有設定 `HF_HOME` 環境變數時，在那個資料夾裡）

也可以到 <https://huggingface.co/settings/tokens> 把建立的存取碼刪掉。

::: info 給進階使用者
畫面上的英文提示（「How would you like to log in?」等）會隨 `huggingface_hub` 套件的版本改變。安裝程式限定了相容的版本範圍；本頁照目前實測的版本畫面寫。
:::
