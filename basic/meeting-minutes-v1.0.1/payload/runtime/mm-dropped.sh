#!/bin/bash
# macOS：拖放到「會議轉寫（基本版）.app」或以它開啟檔案時，在「終端機」中執行的轉寫腳本（meeting-minutes 1.0.1）
# 本腳本由安裝程式放在 runtime 根目錄（1.0.1 起以本腳本所在位置為準，--test-root 試裝時才會用到測試位置）
MMH="$(cd "$(dirname "$0")" && pwd)"
# 使用者自己設定了 MEETING_MINUTES_HOME 時照舊沿用；沒設定時讓轉寫腳本用本腳本所在的位置
[ -n "$MEETING_MINUTES_HOME" ] || export MEETING_MINUTES_HOME="$MMH"
PY="$MMH/venv/bin/python"
export PYTHONUTF8=1
printf '\033]0;會議轉寫（基本版）\007'
printf '\033[35m==== 會議轉寫（基本版）　skill：meeting-minutes ====\033[0m\n'
[ -x "$PY" ] && "$PY" -c 'import json,sys; c=json.load(open(sys.argv[1], encoding="utf-8")); print("後端：%s / %s　模型：%s" % (c["backend"], c["device"], c["whisper"]))' "$MMH/config.json" 2>/dev/null

if [ ! -x "$PY" ]; then
    echo "尚未安裝 runtime，請重新執行 install.command"
    read -r -p "按 Enter 關閉" _; exit 1
fi
if [ "$#" -eq 0 ]; then
    echo "請把會議錄音或錄影檔拖曳到「會議轉寫（基本版）」圖示上"
    read -r -p "按 Enter 關閉" _; exit 1
fi

echo "要轉寫的檔案："
for f in "$@"; do echo "  $f"; done
echo
read -r -p "與會人數（直接 Enter = 自動判斷）：" SPK
read -r -p "本次專有名詞，逗號分隔（可留空）：" HOT

for f in "$@"; do
    args=("$MMH/scripts/transcribe.py" "$f")
    if [[ "$SPK" =~ ^[0-9]+$ ]]; then args+=(--speakers "$SPK"); fi
    if [ -n "$HOT" ]; then args+=(--hotwords "$HOT"); fi
    echo; echo "=== $f ==="
    if "$PY" "${args[@]}"; then
        out="${f%.*}_minutes"
        echo; echo "完成：$out"
        echo "下一步：在 Claude 中說「用 meeting-minutes 整理這份會議記錄」，並附上 transcript.md（影片可一併附上 frames 內的截圖）。"
        # MM_TEST_NO_OPEN=1：僅供開發測試，完成後不開啟輸出資料夾（1.0.1）
        if [ "$MM_TEST_NO_OPEN" != "1" ]; then open "$out"; fi
    else
        echo "轉寫失敗"
    fi
done
echo
read -r -p "按 Enter 關閉" _
