#!/bin/bash
# macOS：在 Finder 雙擊執行，移除會議記錄校稿
cd "$(dirname "$0")" || exit 1
/bin/bash ./uninstall.sh "$@"
rc=$?
echo
read -r -p "按 Enter 關閉視窗" _
exit $rc
