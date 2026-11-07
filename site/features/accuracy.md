---
title: 提升準確度
description: 專有名詞清單、固定錯誤對照表、OpenCC 詞彙回復表、Breeze-ASR-25，以及辨識準確度的預期與限制。
---

# 提升準確度

**這頁幫你做到**：讓逐字稿越用越準，特別是人名、公司名、產品名這類專有名詞。

## 先知道預期

| 情境 | 預期表現 |
|---|---|
| 純華語、收音清楚 | 錯誤率大約一成以內，可以直接閱讀 |
| 中英夾雜的技術討論 | 語音辨識的弱點，錯誤率明顯上升；靠下面的方法與 AI 校正補強 |
| 遠距收音、多人搶話 | 錯誤率上升，講者也容易分錯 |
| 台語 | 不支援，辨識結果不可靠 |

`transcript.md` 是語音辨識的原始結果，只做過繁體轉換、對照表替換、幻覺過濾與分段標點，**沒有經過語意校正**。語意上的校正寫在校正版逐字稿與會議記錄裡（見 [AI 校正](/features/ai-correction)）。

下面四個方法，**效果最大的是第一個**。

## 專有名詞清單

編輯 runtime 資料夾裡的 `glossary.txt`（Windows：`%LOCALAPPDATA%\meeting-minutes-pro\glossary.txt`），一行一個詞，`#` 開頭是註解：

```text
# 會議常出現的專有名詞
Kubernetes
PostgreSQL
範例科技
DemoCRM
```

- 辨識時會提示模型優先辨識成這些拼法；轉成繁體時也會保持這些詞原樣。
- 只有這一場會議才有的詞：右鍵轉寫時「本次專有名詞」那一題輸入（逗號分隔），或命令列加 `--hotwords "名詞1, 名詞2"`。
- Apple Silicon（MLX）只取前約 200 個字元，詞多時把最重要的放前面。

## 固定錯誤對照表

有些詞**每次都被聽成同一種錯法**（例如「Kubernetes」總是被辨識成「酷伯內蒂斯」）。把它記進 `corrections.tsv`，之後每次轉寫都會自動替換：

- 格式：一行一筆，用 Tab 分隔「錯誤寫法、正確寫法、備註」，`#` 開頭是註解。
- 長的詞優先替換，整份逐字稿只掃一次，不會發生連鎖替換。
- 正確寫法也會自動加進辨識提示，讓模型下次直接聽對。
- **適合放**：固定的錯法。**不適合放**：要看上下文才知道對錯的同音字（例如「權限」和「全線」），這類交給 AI 校正。
- 原始辨識結果保留在 `transcript.json` 的 `raw` 欄位，替換錯了可以查回原文。

**預設不會自動寫入**：AI 校正會產生 `corrections.suggested.tsv`（建議），你確認後才加入。在 Claude 對話中整理時，Claude 也會列出建議並請你確認；Claude 桌面 App 寫不到你的電腦，會給你一段可以直接貼上的內容。

維護指令（`python` 要用 runtime 裡的 Python，見[手動執行與參數](/usage/advanced)）：

```bash
python corrections.py list                                   # 列出全部
python corrections.py add "酷伯內蒂斯" "Kubernetes" --note "技術週會"   # 新增
python corrections.py remove "酷伯內蒂斯"                     # 移除
python corrections.py test "我們的酷伯內蒂斯叢集"              # 試套用，不寫檔
```

單一字元、和既有項目衝突、錯誤寫法與正確寫法相同的項目，工具會拒絕寫入。

### 對照表自動寫入（選用，預設關）

把 `config.json` 的 `correction.corrections_auto.mode` 改成 `"on"` 之後，建議項目**同時符合**下列條件才會自動寫入，其他照舊留在建議檔：

| 條件 | 設定鍵（`correction.corrections_auto.`） | 預設 |
|---|---|---|
| 同一場裡同一個修正出現的次數 | `min_count` | 2 |
| 在幾場不同的會議都被建議同一個修正 | `min_meetings` | 2 |
| 只採用高信心、沒有標成待確認的項目 | （固定） | — |
| 只認清單內的模型產生的建議 | `models` | `claude:sonnet`、`claude:opus`、`openai:gpt-6.1-sol` |
| 每場最多寫入幾筆 | `max_per_run` | 5 |

自動寫入前會先備份；寫入的行在備註欄標 `auto:<日期>`。列出與撤銷：

```bash
python corrections.py auto-list                     # 列出所有自動寫入的項目
python corrections.py auto-undo "酷伯內蒂斯"         # 撤銷指定的項目
python corrections.py auto-undo --all               # 撤銷全部自動寫入的項目
```

撤銷過的詞之後不會再被自動寫入。

## OpenCC 詞彙回復表

辨識模型常輸出簡體字，程式用 OpenCC 轉成台灣用語的繁體。但這個轉換會把一些台灣本來就在用的詞換掉，例如「權限」變「許可權」、「分區」變「分割槽」、「帳號」變「賬號」。程式在轉換前先把這些詞保護起來：

- 內建的保護清單會隨版本更新；你自己的詞加在 runtime 資料夾的 `opencc_keep.tsv`（重新安裝不會覆蓋）。
- 格式：一行一筆，Tab 分隔「保留寫法、其他來源寫法（逗號分隔，可留空）、備註」；以 `-` 開頭的行（例如 `-數據`）停用內建的同名項目。
- 先試再加：`python opencc_keep.py test "要測試的句子"` 會顯示轉換前後與命中的詞。
- 「登錄」不在內建清單：辨識模型常把「登入」寫成「登录」，保留「登錄」反而會保護成錯字。你的會議常說「登錄」（登記的意思）而且要保留時，在 `opencc_keep.tsv` 加一行 `登錄`。
- 分工：OpenCC 改錯的詞放這裡；辨識模型本身聽錯的固定錯誤才放對照表。

## Breeze-ASR-25

[Breeze-ASR-25](https://huggingface.co/MediaTek-Research/Breeze-ASR-25) 是 MediaTek Research 以 Whisper 微調的台灣華語辨識模型（Apache-2.0）。在中英夾雜的評測資料上，錯誤率大約是 Whisper large-v3 的一半，但**速度比預設模型慢好幾倍**。

- 安裝時會問要不要裝（預設安裝）。之後補裝：`setup_backend.py --breeze-only`。
- 右鍵轉寫時會問這次要不要用；Claude CLI 模式下 Claude 會依你描述的會議類型判斷（例如「技術會議，中英夾雜很多」），判斷不了會先問你。
- 命令列：轉寫時加 `--whisper breeze`。
- 額外空間約 1.6～3 GB（依硬體而定）；Intel 電腦安裝時要多花 10～20 分鐘轉換格式。

## 換硬體或模型之後

- 不同硬體使用的模型格式不同，辨識結果可能有細微差異。
- 最快的裝置不一定是直覺上的那個（例如某些桌機的 NPU 算力有限，多核心 CPU 可能更快），這些都由安裝時的實測決定。
- 想用更準但更慢的 `large-v3`：先用 `download_models.py` 下載，再在轉寫時加 `--whisper large-v3`。
