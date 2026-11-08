#!/bin/bash
# macOS：在 Finder 雙擊執行（第一次若被擋，請按右鍵 →「打開」）
cd "$(dirname "$0")" || exit 1
/bin/bash ./install.sh "$@"
rc=$?
echo
read -r -p "按 Enter 關閉視窗" _
exit $rc
