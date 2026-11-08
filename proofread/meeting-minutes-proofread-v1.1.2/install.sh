#!/bin/bash
# 會議記錄校稿 1.1.2 安裝程式（macOS；meeting-minutes-pro 的附屬工具）
#   - 需要先安裝 meeting-minutes-pro 2.2.0 以上（~/Library/Application Support/meeting-minutes-pro，
#     或環境變數 MEETING_MINUTES_PRO_HOME）
#   - 把程式複製到 <Pro 的資料夾>/proofread/app（升級時整個換新；最近的稿清單 state/ 與 config.json 保留）
#   - 建立 ~/Applications/會議記錄校稿.app：把輸出資料夾拖上去就開始校稿；雙擊「會議記錄校稿.mmproof」也用它開啟
#   - 不安裝任何套件：用 Pro 已裝好的 Python（只用標準函式庫）
# 用法：./install.command（Finder 雙擊）或 ./install.sh
# 其他：--test-root <資料夾>（僅供開發測試：Pro 的資料夾與 .app 都改到這個資料夾底下；沒有 osacompile 的環境只寫出 .app 的腳本）
# 結束代碼：0 完成；2 沒有 Pro、Pro 太舊或不相容（沒有寫入任何檔案）；1 其他錯誤
# 註：macOS 內建 bash 3.2，本腳本避免使用 bash 4 以上語法。

set -o pipefail

VERSION="1.1.2"
MIN_PRO="2.2.0"
TOOL_NAME="會議記錄校稿"
UTI="local.meeting-minutes-proofread.mmproof"
BUNDLE_ID="local.meeting-minutes-proofread"
HERE="$(cd "$(dirname "$0")" && pwd)"
if command -v cygpath >/dev/null 2>&1; then HERE="$(cygpath -m "$HERE")"; fi   # Windows 的 Git Bash（測試）：原生 Python 看得懂的路徑
APP_SRC="$HERE/payload/app"
PLISTBUDDY="/usr/libexec/PlistBuddy"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1   # 不在 Pro 的 scripts/ 與本程式資料夾留下 __pycache__

TEST_ROOT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --test-root) TEST_ROOT="$2"; shift 2 ;;
        *) echo "未知參數：$1"; exit 1 ;;
    esac
done

c_cyan=$'\033[36m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'; c_off=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$c_cyan" "$1" "$c_off"; }
ok()   { printf '    %s[OK]%s %s\n' "$c_green" "$c_off" "$1"; }
warn() { printf '    %s[!]%s %s\n' "$c_yellow" "$c_off" "$1"; }
stop_with() { printf '\n%s[錯誤]%s %s\n' "$c_red" "$c_off" "$2"; exit "$1"; }

setup_paths() {
    MMH="${MEETING_MINUTES_PRO_HOME:-$HOME/Library/Application Support/meeting-minutes-pro}"
    APPS_DIR="$HOME/Applications"
    if [ -n "$TEST_ROOT" ]; then
        # 僅供開發測試：同 Pro 的測試模式（<TEST_ROOT>/home）
        mkdir -p "$TEST_ROOT" || exit 1
        TEST_ROOT="$(cd "$TEST_ROOT" && pwd)"
        if command -v cygpath >/dev/null 2>&1; then TEST_ROOT="$(cygpath -m "$TEST_ROOT")"; fi   # Windows 的 Git Bash（測試）
        MMH="$TEST_ROOT/home"
        APPS_DIR="$TEST_ROOT/Applications"
    fi
    DST="$MMH/proofread"
    APP_DST="$DST/app"
    STATE_DIR="$DST/state"
    PY="$MMH/venv/bin/python"
    LAUNCHER="$APP_DST/mmproof_launcher.py"
    MAC_APP="$APPS_DIR/$TOOL_NAME.app"
}

# ------------------------------------------------------------------ 1. 偵測 Pro（規格 §2.2）
check_pro() {
    step "檢查 meeting-minutes-pro"
    [ -f "$APP_SRC/mmproof_launcher.py" ] || stop_with 1 "找不到安裝檔 payload/app。請先把下載的 zip 完整解壓縮，再執行解開後資料夾裡的 install.command"
    if [ ! -f "$MMH/config.json" ] || [ ! -f "$MMH/scripts/common.py" ] || [ ! -x "$PY" ]; then
        stop_with 2 "請先安裝 meeting-minutes-pro $MIN_PRO 以上。安裝方法見 meeting-minutes Portal 的「安裝」頁。（找不到 $MMH 裡的 Pro）"
    fi
    # 版號與介面檢查：用 Pro 的 Python 執行這個安裝包裡的檢查程式（只讀，不寫任何檔）
    local out rc=0 parsed
    out="$(MEETING_MINUTES_PRO_HOME="$MMH" "$PY" -B "$APP_SRC/mmproof_pro.py" --check --home "$MMH" 2>/dev/null)" || rc=$?
    parsed="$(printf '%s' "$out" | "$PY" -B -c '
import json, sys
d = None
for line in reversed(sys.stdin.read().strip().splitlines()):
    if line.strip().startswith("{"):
        d = json.loads(line)
        break
print("ok" if d and d.get("ok") else ("bad" if d else "none"))
print((d or {}).get("version") or "")
print((d or {}).get("message") or "")
' 2>/dev/null)" || parsed="none"
    local kind ver msg
    kind="$(printf '%s\n' "$parsed" | sed -n 1p)"
    ver="$(printf '%s\n' "$parsed" | sed -n 2p)"
    msg="$(printf '%s\n' "$parsed" | sed -n 3p)"
    case "$kind" in
        ok) ;;
        bad) stop_with 2 "$msg" ;;
        *) stop_with 2 "無法檢查 meeting-minutes-pro（Pro 的 Python 回報 exit $rc）。請重新執行 Pro 的安裝程式後再試一次" ;;
    esac
    PRO_VERSION="$ver"
    ok "meeting-minutes-pro $PRO_VERSION（最低 $MIN_PRO；介面檢查通過）"
}

# ------------------------------------------------------------------ 2. 停止執行中的舊服務（先讓分頁存檔）
stop_old() {
    [ -f "$STATE_DIR/instance.json" ] || return 0
    step "停止執行中的會議記錄校稿服務"
    local st
    st="$(MEETING_MINUTES_PRO_HOME="$MMH" "$PY" -B "$APP_SRC/mmproof_launcher.py" --shutdown --home "$MMH" 2>/dev/null | tail -n 1)" || true
    case "$st" in
        *'"running": true'*'"stopped": false'*) warn "服務沒有在時限內結束；安裝繼續，下次開啟會改用新版" ;;
        *'"running": true'*) ok "已停止（開著的分頁已先存檔）" ;;
        *) ok "沒有執行中的服務" ;;
    esac
}

# ------------------------------------------------------------------ 3. 複製程式（升級：換掉 app/，保留 state/ 與 config.json）
copy_app() {
    step "安裝會議記錄校稿 $VERSION 到 $DST"
    local upgrade="" now u
    [ -f "$DST/version.json" ] && upgrade=1
    mkdir -p "$DST" || stop_with 1 "無法建立 $DST"
    rm -rf "$APP_DST" || stop_with 1 "無法刪除舊的 $APP_DST"
    cp -R "$APP_SRC" "$APP_DST" || stop_with 1 "複製檔案失敗"
    find "$APP_DST" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
    for u in uninstall.sh uninstall.ps1; do
        if [ -f "$HERE/$u" ]; then cp "$HERE/$u" "$DST/$u" || stop_with 1 "複製 $u 失敗"; fi
    done
    chmod 755 "$DST/uninstall.sh" 2>/dev/null
    mkdir -p "$STATE_DIR" || stop_with 1 "無法建立 $STATE_DIR"
    now="$(date "+%Y-%m-%dT%H:%M:%S%z" | sed 's/\([0-9][0-9]\)$/:\1/')"
    printf '{\n  "version": "%s",\n  "installed_at": "%s",\n  "pro_version_at_install": "%s"\n}\n' \
        "$VERSION" "$now" "$PRO_VERSION" > "$DST/version.json" || stop_with 1 "寫入 version.json 失敗"
    if [ -n "$upgrade" ]; then ok "已升級（最近的稿清單與各輸出資料夾的校稿進度都保留）"; else ok "已安裝"; fi
}

# ------------------------------------------------------------------ 4. ~/Applications/會議記錄校稿.app（拖放、雙擊 .mmproof）
applescript_source() {
    # 背景執行啟動器、輸出丟棄，不開「終端機」（規格 §3.3）
    cat <<APPLESCRIPT
on open theItems
    set args to ""
    repeat with f in theItems
        set args to args & " " & quoted form of POSIX path of f
    end repeat
    do shell script "MEETING_MINUTES_PRO_HOME=" & quoted form of "$MMH" & " " & quoted form of "$PY" & " -B " & quoted form of "$LAUNCHER" & args & " > /dev/null 2>&1 &"
end open

on run
    display dialog "把會議的輸出資料夾（<檔名>_minutes）拖到這個圖示上，就會開始校稿。之後也可以雙擊輸出資料夾裡的「$TOOL_NAME.mmproof」。" buttons {"好"} default button 1 with title "$TOOL_NAME"
end run
APPLESCRIPT
}

make_app() {
    step "建立「$TOOL_NAME.app」"
    mkdir -p "$APPS_DIR" || stop_with 1 "無法建立 $APPS_DIR"
    rm -rf "$MAC_APP"
    if command -v osacompile >/dev/null 2>&1; then
        applescript_source | osacompile -o "$MAC_APP" || stop_with 1 "osacompile 建立 .app 失敗"
    elif [ -n "$TEST_ROOT" ]; then
        # 僅供開發測試（沒有 osacompile 的環境）：只寫出 .app 的腳本，供測試檢查
        mkdir -p "$MAC_APP/Contents" && applescript_source > "$MAC_APP/Contents/mmproof-applescript.txt"
        warn "測試模式：沒有 osacompile，只寫出 .app 的腳本"
        return 0
    else
        stop_with 1 "找不到 osacompile（macOS 內建）；這個安裝程式只能在 macOS 執行"
    fi
    ok "已建立 $MAC_APP（把輸出資料夾拖到它上面就開始校稿）"
}

register_mmproof() {
    # 雙擊 .mmproof 用這個 .app 開啟：Info.plist 加文件類型與匯出的類型宣告，再向 LaunchServices 註冊
    local pl="$MAC_APP/Contents/Info.plist"
    if [ ! -x "$PLISTBUDDY" ] || [ ! -f "$pl" ]; then
        warn "無法設定「.mmproof」的雙擊開啟（沒有 PlistBuddy 或 Info.plist）；請把輸出資料夾拖到「$TOOL_NAME.app」上開啟"
        return 0
    fi
    "$PLISTBUDDY" -c "Set :CFBundleIdentifier $BUNDLE_ID" "$pl" 2>/dev/null || "$PLISTBUDDY" -c "Add :CFBundleIdentifier string $BUNDLE_ID" "$pl"
    "$PLISTBUDDY" -c "Print :CFBundleDocumentTypes" "$pl" >/dev/null 2>&1 || {
        # 沒有文件類型（不應發生：有 on open 的 .app 都有）：補一個接受資料夾與任何檔案的
        "$PLISTBUDDY" -c "Add :CFBundleDocumentTypes array" -c "Add :CFBundleDocumentTypes:0 dict" \
            -c "Add :CFBundleDocumentTypes:0:CFBundleTypeOSTypes array" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeOSTypes:0 string ****" \
            -c "Add :CFBundleDocumentTypes:0:CFBundleTypeOSTypes:1 string fold" -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" "$pl"
    }
    # 插在第一個，保留 osacompile 原本的拖放類型（資料夾與檔案）
    if ! "$PLISTBUDDY" -c "Add :CFBundleDocumentTypes:0 dict" \
        -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string $TOOL_NAME" \
        -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Editor" \
        -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Owner" \
        -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes array" \
        -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string $UTI" \
        -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions array" \
        -c "Add :CFBundleDocumentTypes:0:CFBundleTypeExtensions:0 string mmproof" \
        -c "Add :UTExportedTypeDeclarations array" \
        -c "Add :UTExportedTypeDeclarations:0 dict" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeIdentifier string $UTI" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeDescription string $TOOL_NAME" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo array" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeConformsTo:0 string public.data" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification dict" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification:public.filename-extension array" \
        -c "Add :UTExportedTypeDeclarations:0:UTTypeTagSpecification:public.filename-extension:0 string mmproof" \
        "$pl"; then
        warn "無法設定「.mmproof」的雙擊開啟；請把輸出資料夾拖到「$TOOL_NAME.app」上開啟"
        return 0
    fi
    if [ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$MAC_APP" >/dev/null 2>&1; then
        ok "雙擊輸出資料夾裡的「$TOOL_NAME.mmproof」會用「$TOOL_NAME.app」開啟"
    else
        warn "向系統註冊「.mmproof」失敗；第一次雙擊時請選「$TOOL_NAME.app」開啟，或把輸出資料夾拖到它上面"
    fi
}

summary() {
    step "安裝完成（$TOOL_NAME $VERSION，搭配 meeting-minutes-pro $PRO_VERSION）"
    echo "    開啟方式：把會議的輸出資料夾（<檔名>_minutes）拖到 ~/Applications 的「$TOOL_NAME.app」上；"
    echo "              或雙擊輸出資料夾裡的「$TOOL_NAME.mmproof」。瀏覽器會自動開啟校稿頁，不需要打任何指令。"
    echo "    校稿進度存在各輸出資料夾的 .proofread/，關掉再開會接著校。"
    case "$PRO_VERSION" in
        2.2.*) echo "    「用定稿重做會議記錄」需要 meeting-minutes-pro 2.3.0 以上；目前的 $PRO_VERSION 可以校稿、定稿與經驗匯入。" ;;
    esac
    echo "    使用說明：安裝包裡的 README.md，或 meeting-minutes Portal 的「會議記錄校稿」使用方法頁。"
    echo "    移除：執行安裝包裡的 uninstall.command（或 bash \"$DST/uninstall.sh\"）。"
    echo "    要移除 meeting-minutes-pro 時：Pro 2.3.0 以上會自動先移除會議記錄校稿；Pro 2.2.x 請先移除會議記錄校稿。"
    if [ -n "$TEST_ROOT" ]; then warn "測試模式（--test-root）：所有檔案寫到 $TEST_ROOT"; fi
}

main() {
    if [ "$(uname -s)" != "Darwin" ] && [ -z "$TEST_ROOT" ]; then
        stop_with 1 "這是 macOS 安裝程式；Windows 請執行 install.cmd"
    fi
    setup_paths
    check_pro
    stop_old
    copy_app
    make_app
    register_mmproof
    summary
    exit 0
}

main
