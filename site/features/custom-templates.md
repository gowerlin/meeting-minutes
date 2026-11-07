---
title: 自訂範本
description: 在 templates 資料夾放自己的範本，延伸內建的內容類型：放在哪、格式、範例、驗證錯誤怎麼看。
---

# 自訂範本

**這頁幫你做到**：做出自己團隊專用的筆記格式，例如「示範專案週會」，讓它出現在轉寫前的類型選單裡。

## 放在哪裡

在 runtime 資料夾的 `templates` 裡放 `.md` 檔：

| 系統 | 位置 |
|---|---|
| Windows | `%LOCALAPPDATA%\meeting-minutes-pro\templates\` |
| macOS | `~/Library/Application Support/meeting-minutes-pro/templates/` |

安裝時會在這個資料夾放一份 `README.md`（格式說明與範例）。放好之後，下一次轉寫的類型選單就會多一項，例如：

```text
  8 示範專案週會［自訂：會議］
```

## 範例

```markdown
---
name: 示範專案週會
base: meeting
description: 示範專案每週的進度會議
speakers: auto
labels:
  actions: 本週待辦
---

## 整理重點
- 每個子專案寫一個議題：進度百分比、遇到的阻礙、需要誰協助
```

| 欄位 | 必填 | 意思 |
|---|---|---|
| `name` | ✅ | 選單上顯示的名稱 |
| `base` | ✅ | 延伸哪一種內建類型（`meeting`、`course`、`interview`、`tutorial`、`panel`、`workshop`、`requirements`） |
| `description` | | 一句話說明 |
| `speakers` | | 講者人數的預設值：`auto`（自動判斷）、1～20、`skip`（略過說話者分離） |
| `cluster_threshold` | | CPU 說話者分離的分群門檻（數字越大，判斷出的講者越少） |
| `labels` | | 改節標題，例如把「待辦事項」改叫「本週待辦」 |
| `## 整理重點` | | 補一段給 AI 的整理說明，最多 2,000 字 |

欄位與版面沿用 `base` 那一種類型。每種類型可以改哪些節的名稱、全部錯誤訊息，見 skill 內附的 `references/custom-template-format.md`。

## 範本不能做的事

範本只能改「整理成什麼樣子」，不能改「程式怎麼執行」：

- 寫了模型、供應商、指令參數、要送出的檔案這類設定（例如 `model:`、`flags:`），**整份範本不會載入**。
- 「整理重點」只當格式說明。裡面若要求忽略規則、讀寫檔案、輸出整份逐字稿，AI 一律不照做。
- 看起來像金鑰的內容（`sk-…`、`hf_…`）會讓範本不載入。**範本裡不要放任何金鑰或密碼**。
- 執行 log 只記範本的代號、`base`、是否有效與整理重點的字數，不記範本內容。

## 驗證錯誤怎麼看

- 類型選單只列有效的範本。無效的會在選單下方印一行原因，例如：

  ```text
  ⚠ 自訂範本 old.md 沒有載入：不認得的設定 model。範本只能改名稱、講者設定與整理重點，模型、指令與送出的檔案由程式決定
  ```

- 自己檢查所有範本（Windows；macOS 把路徑換成 `venv/bin/python`）：

  ```powershell
  & "$MMH\venv\Scripts\python.exe" "$MMH\scripts\templates.py" check
  ```

- 轉寫時選的範本在整理前被刪掉或改壞了：程式改用 `base` 的內建類型，筆記表頭會註明「自訂範本 X 讀取失敗，改用內建〈…〉」。

## 從命令列指定

```powershell
& "$MMH\venv\Scripts\python.exe" "$MMH\scripts\transcribe.py" "會議.m4a" --template weekly
```

`weekly` 是範本的檔名（不含 `.md`）。升級時範本會保留；解除安裝刪除 runtime 時會先問要不要保留範本。
