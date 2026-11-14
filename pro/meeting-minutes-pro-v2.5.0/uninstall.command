#!/bin/bash
cd "$(dirname "$0")" || exit 1
/bin/bash ./install.sh --uninstall
echo
read -r -p "按 Enter 關閉視窗" _
