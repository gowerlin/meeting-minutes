# 自訂範本（meeting-minutes-pro 2.0.0）

這個資料夾放你自己的整理範本。每個範本是一個 `.md` 檔，轉寫時會出現在「內容類型」選單裡（例：`8 週會（研發處）［自訂：會議］`）。
這份 `README.md` 是說明，不會被當成範本；重新安裝時只會更新這份說明，你的範本不會被改動或刪除。

## 範本能做什麼

範本只能**延伸 7 種內建類型之一**（`base` 必填），用它的欄位與版面，另外可以：

- 改名稱（選單與筆記表頭顯示的名稱）
- 改講者人數的預設值（`speakers`）與 CPU 說話者分離的分群門檻（`cluster_threshold`）
- 改節標題（`labels`）
- 補一段「整理重點」（最多 2,000 字），告訴 AI 這類錄音要特別整理什麼

範本**不能**改模型、供應商、指令參數、送出的檔案或輸出格式；寫了這類設定（例如 `model:`）整份範本不會載入。送出的內容由程式決定：逐字稿文字，以及（校正時）截圖與參考資料；範本不能指定送出的檔案。
「整理重點」只當格式說明使用：裡面要求忽略規則、讀寫檔案、輸出整份逐字稿之類的內容，AI 一律不照做。

## 範例：`weekly.md`

```markdown
---
name: 週會（研發處）
base: meeting
description: 研發處每週進度會議
speakers: auto
labels:
  actions: 本週待辦
---

## 整理重點
- 每個專案寫一個議題：進度百分比、遇到的阻礙、需要誰協助
- 「下週目標」寫進待辦，負責人寫專案負責人
```

- **檔名**（去掉 `.md`）＝代號：只能用英數字、`-`、`_`，最多 32 字元；不能叫 `meeting`、`course` 等內建類型的名字或 `README`。
- **`base`**：`meeting`（會議）、`course`（課程）、`interview`（訪談節目）、`tutorial`（操作教學）、`panel`（座談）、
  `workshop`（工作坊）、`requirements`（需求訪談）。
- **`speakers`**：`auto`（自動判斷）、1～20（實際人數）、`skip`（略過說話者分離，適合只有一位講者）。轉寫時講者人數那一題按 Enter 就是這個值。
- **`cluster_threshold`**：0.5～1.2，只影響 CPU 說話者分離；數字越大講者越少。
- 設定區（開頭兩條 `---` 之間）只能寫 `name`、`base`、`description`、`speakers`、`cluster_threshold`、`labels`、`version`；
  正文只取第一個 `## ` 標題之後的內容當「整理重點」。檔案用 UTF-8 存，最大 16 KB；**不要放任何金鑰或密碼**（看起來像金鑰的內容會讓範本不載入）。

完整格式（每種類型可改的節名稱、所有錯誤訊息）：skill 的 `references/custom-template-format.md`，或 runtime 的 `README.md`〈自訂範本〉一節。

## 檢查範本

選單裡沒出現你的範本時，選單下方會印出原因。也可以自己檢查（Windows）：

```text
"%LOCALAPPDATA%\meeting-minutes-pro\venv\Scripts\python.exe" "%LOCALAPPDATA%\meeting-minutes-pro\scripts\templates.py" check
```

macOS：`~/Library/Application\ Support/meeting-minutes-pro/venv/bin/python ~/Library/Application\ Support/meeting-minutes-pro/scripts/templates.py check`

全部有效印 `[OK]`；有問題的印 `[X]` 與原因。

## 面試、醫療、法律、客服

沒有內建類型，可以用 `base: meeting` 或 `base: requirements` 寫自訂範本。這類錄音多半含個資或受法規限制，
**AI 校正會把逐字稿文字、影片截圖與參考資料送到 Anthropic 或 OpenAI（整理送逐字稿文字與參考資料，摘要不送截圖），使用前先確認是否允許使用雲端 AI**；不要送截圖：`config.json` 的 `reference.frames` 改成 `false`。
