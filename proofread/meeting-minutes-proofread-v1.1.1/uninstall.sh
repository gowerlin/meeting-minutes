#!/bin/bash
# 會議記錄校稿 1.1.1 移除程式（macOS）
#   - 停止執行中的服務（開著的分頁先存檔）；刪除程式（proofread/app）、version.json、config.json、移除程式本身、
#     ~/Applications/會議記錄校稿.app（含「.mmproof」的雙擊開啟）
#   - 詢問是否刪除最近的稿清單（proofread/state，預設保留）
#   - 不刪除：各輸出資料夾的 .proofread/（校稿進度）、定稿檔、meeting-minutes-pro 的 corrections.tsv、glossary.txt、backups/
# 用法：./uninstall.command（Finder 雙擊）或 bash uninstall.sh
# 參數：--quiet（不詢問：最近的稿清單照預設保留；meeting-minutes-pro 2.3.0 以上解除安裝時這樣呼叫）
#       --test-root <資料夾>（僅供開發測試，同安裝程式）
# 結束代碼：0 完成（或本來就沒有安裝）；1 有項目沒有刪除成功
# 註：全部寫在 main 裡、最後才呼叫：bash 先讀完整個函式，刪掉這個檔不影響執行。

TOOL_NAME="會議記錄校稿"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1

main() {
    local quiet="" test_root="" errors=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --quiet) quiet=1; shift ;;
            --test-root) test_root="$2"; shift 2 ;;
            *) echo "未知參數：$1"; return 1 ;;
        esac
    done
    local c_cyan=$'\033[36m' c_green=$'\033[32m' c_yellow=$'\033[33m' c_off=$'\033[0m'
    step() { printf '\n%s==> %s%s\n' "$c_cyan" "$1" "$c_off"; }
    ok()   { printf '    %s[OK]%s %s\n' "$c_green" "$c_off" "$1"; }
    warn() { printf '    %s[!]%s %s\n' "$c_yellow" "$c_off" "$1"; }

    local mmh="${MEETING_MINUTES_PRO_HOME:-$HOME/Library/Application Support/meeting-minutes-pro}"
    local apps="$HOME/Applications"
    if [ -n "$test_root" ]; then
        mkdir -p "$test_root" || return 1
        test_root="$(cd "$test_root" && pwd)"
        if command -v cygpath >/dev/null 2>&1; then test_root="$(cygpath -m "$test_root")"; fi   # Windows 的 Git Bash（測試）
        mmh="$test_root/home"
        apps="$test_root/Applications"
    fi
    local dst="$mmh/proofread"
    local app_dst="$dst/app" state="$dst/state" py="$mmh/venv/bin/python"
    local mac_app="$apps/$TOOL_NAME.app"

    rm_path() {   # rm_path <路徑> <說明>
        [ -e "$1" ] || return 0
        if rm -rf "$1" 2>/dev/null && [ ! -e "$1" ]; then ok "已刪除 $2"
        else errors=$((errors + 1)); warn "無法刪除 $2（$1）"; fi
    }

    step "移除 $TOOL_NAME"
    if [ ! -e "$dst" ] && [ ! -e "$mac_app" ]; then
        ok "沒有安裝 $TOOL_NAME（$dst 不存在），不需要移除"
        return 0
    fi

    # 1. 停止執行中的服務：請它先讓開著的分頁存檔再結束（規格 §3.8）
    if [ -f "$state/instance.json" ] && [ -f "$app_dst/mmproof_launcher.py" ] && [ -x "$py" ]; then
        local st
        st="$(MEETING_MINUTES_PRO_HOME="$mmh" "$py" -B "$app_dst/mmproof_launcher.py" --shutdown --home "$mmh" 2>/dev/null | tail -n 1)" || true
        case "$st" in
            *'"running": true'*'"stopped": false'*) warn "服務沒有在時限內結束；它會在閒置後自己結束" ;;
            *'"running": true'*) ok "已停止服務（開著的分頁已先存檔）" ;;
        esac
    fi

    # 2. 程式與設定、.app（含 .mmproof 的雙擊開啟）
    rm_path "$app_dst" "程式（proofread/app）"
    rm_path "$dst/version.json" "version.json"
    rm_path "$dst/config.json" "config.json"
    if [ -e "$mac_app" ]; then
        [ -x "$LSREGISTER" ] && "$LSREGISTER" -u "$mac_app" >/dev/null 2>&1
        rm_path "$mac_app" "$TOOL_NAME.app（含「.mmproof」的雙擊開啟）"
    fi

    # 3. 最近的稿清單（state/）：預設保留
    if [ -d "$state" ]; then
        local ans=""
        if [ -z "$quiet" ]; then read -r -p "    要刪除最近的稿清單嗎？[y/N] " ans; fi
        case "$ans" in
            [yY]*) rm_path "$state" "最近的稿清單（proofread/state）" ;;
            *) if [ -n "$quiet" ]; then ok "保留最近的稿清單（安靜模式，不詢問）：$state"; else ok "保留最近的稿清單（$state）"; fi ;;
        esac
    fi

    # 4. 移除程式本身
    rm_path "$dst/uninstall.sh" "uninstall.sh"
    rm_path "$dst/uninstall.ps1" "uninstall.ps1"
    rmdir "$dst" 2>/dev/null

    echo "    沒有刪除：各輸出資料夾的 .proofread/（校稿進度）、定稿檔（transcript.final.*）、"
    echo "    meeting-minutes-pro 的 corrections.tsv、glossary.txt 與 backups/。"
    if [ "$errors" -gt 0 ]; then
        warn "有 $errors 個項目沒有刪除成功（見上面的訊息）"
        return 1
    fi
    ok "已移除 $TOOL_NAME"
    return 0
}

main "$@"; exit $?
