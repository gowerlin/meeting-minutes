#!/bin/bash
# meeting-minutes 1.0.1 一鍵安裝程式（macOS Apple Silicon）
#   - 共用 runtime：~/Library/Application Support/meeting-minutes（venv、模型、腳本、glossary、config）
#   - 目標 CLI ：複製 skill 到 ~/.claude/skills/meeting-minutes（Claude CLI 與桌面版 Code 分頁共用）
#   - 目標 App ：在桌面產生上傳用 skill zip（Claude App 對話 / Cowork）
#   - 都會建立 ~/Applications/會議轉寫（基本版）.app（把錄音檔拖上去即可在本機轉寫）
# 用法：./install.command                 互動選單
#       ./install.sh --target both        不詢問，直接安裝（cli / app / both）
#       ./install.sh --uninstall          解除安裝
# 其他：--whisper turbo|large-v3   --backend mlx:gpu|ct2:cpu（跳過偵測）   --keep-all
#       --test-root <資料夾>（1.0.1；僅供開發測試：runtime、skill、app、桌面都改放到這個資料夾底下）
# 硬體只在安裝時偵測一次，結果寫入 config.json；轉寫時不再偵測。
# 註：macOS 內建 bash 3.2，本腳本避免使用 bash 4 以上語法。

set -eo pipefail

VERSION="1.0.1"
HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/payload"
export PYTHONUTF8=1

TARGET=""; WHISPER="turbo"; BACKEND=""; KEEP_ALL=""; UNINSTALL=""; TEST_ROOT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --target)    TARGET="$(echo "$2" | tr '[:upper:]' '[:lower:]')"; shift 2 ;;
        --whisper)   WHISPER="$2"; shift 2 ;;
        --backend)   BACKEND="$2"; shift 2 ;;
        --keep-all)  KEEP_ALL=1; shift ;;
        --test-root) TEST_ROOT="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        *) echo "未知參數：$1"; exit 2 ;;
    esac
done

MMH="$HOME/Library/Application Support/meeting-minutes"
SKILL_DST="$HOME/.claude/skills/meeting-minutes"
APPS_DIR="$HOME/Applications"
DESKTOP_DIR="$HOME/Desktop"
if [ -n "$TEST_ROOT" ]; then
    # 1.0.1：僅供開發測試。所有寫入位置都放到 TEST_ROOT 底下，不碰使用者真正的安裝（runtime、skill、app、桌面）
    mkdir -p "$TEST_ROOT"; TEST_ROOT="$(cd "$TEST_ROOT" && pwd)"
    MMH="$TEST_ROOT/home"; SKILL_DST="$TEST_ROOT/skills/meeting-minutes"
    APPS_DIR="$TEST_ROOT/Applications"; DESKTOP_DIR="$TEST_ROOT/Desktop"
    mkdir -p "$APPS_DIR" "$DESKTOP_DIR"
    export MEETING_MINUTES_HOME="$MMH"   # 讓 runtime 的 Python 腳本（模型、config.json）也寫到測試位置
fi
VPY="$MMH/venv/bin/python"
APP_DST="$APPS_DIR/會議轉寫（基本版）.app"
LEGACY_APP="$APPS_DIR/會議轉寫.app"   # 舊版名稱（未標示版本）
UPLOAD_ZIP="$DESKTOP_DIR/meeting-minutes-skill-upload.zip"

c_cyan=$'\033[36m'; c_green=$'\033[32m'; c_yellow=$'\033[33m'; c_red=$'\033[31m'; c_off=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$c_cyan" "$1" "$c_off"; }
ok()   { printf '    %s[OK]%s %s\n' "$c_green" "$c_off" "$1"; }
warn() { printf '    %s[!]%s %s\n' "$c_yellow" "$c_off" "$1"; }
fail() { printf '\n%s[錯誤]%s %s\n' "$c_red" "$c_off" "$1"; exit 1; }

# ------------------------------------------------------------------ platform
[ "$(uname -s)" = "Darwin" ] || fail "這是 macOS 安裝程式；Windows 請執行 install.cmd"
if [ "$(sysctl -n hw.optional.arm64 2>/dev/null || echo 0)" != "1" ]; then
    fail "目前只支援 Apple Silicon（M 系列）Mac；Intel Mac 尚未支援"
fi

# ------------------------------------------------------------------ uninstall
do_uninstall() {
    step "解除安裝 meeting-minutes"
    [ -d "$SKILL_DST" ]  && rm -rf "$SKILL_DST"  && ok "已移除 Claude CLI skill：$SKILL_DST"
    [ -d "$APP_DST" ]    && rm -rf "$APP_DST"    && ok "已移除 會議轉寫（基本版）.app"
    [ -d "$LEGACY_APP" ] && rm -rf "$LEGACY_APP" && ok "已移除舊名稱的 app"
    [ -f "$UPLOAD_ZIP" ] && rm -f "$UPLOAD_ZIP"  && ok "已移除桌面上的上傳用 zip"
    if [ -d "$MMH" ]; then
        read -r -p "    是否一併刪除 runtime 與模型（$MMH，約 2GB）？[y/N] " ans
        case "$ans" in
            [yY]*) rm -rf "$MMH"; ok "已刪除 $MMH" ;;
            *) warn "保留 $MMH（含 glossary.txt 與模型）" ;;
        esac
    fi
    warn "若曾上傳到 Claude App，請到 App 的「自訂 (Customize) → Skills」手動刪除 meeting-minutes。"
    exit 0
}
[ -n "$UNINSTALL" ] && do_uninstall

# ------------------------------------------------------------------ menu
[ -d "$PAYLOAD" ] || fail "找不到 payload 資料夾，請先把整個 zip 解壓縮再執行"
if [ -z "$TARGET" ]; then
    has_cli="未偵測到"; { command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; } && has_cli="已安裝"
    has_app="未偵測到"; [ -d "/Applications/Claude.app" ] || [ -d "$HOME/Applications/Claude.app" ] && has_app="已安裝"
    echo
    echo "  meeting-minutes $VERSION 會議記錄 skill 安裝程式（macOS）"
    echo "  ------------------------------------------------"
    echo "  偵測：Claude CLI $has_cli　Claude App $has_app"
    echo
    echo "  [1] Claude CLI（含桌面版 Code 分頁）：本機轉寫 + 自動產出會議記錄"
    echo "  [2] Claude App（對話 / Cowork）：拖放轉寫 + 上傳 skill 整理會議記錄"
    echo "  [3] 兩者都裝（建議）"
    echo "  [4] 解除安裝"
    echo "  [Q] 離開"
    echo
    read -r -p "  請選擇：" sel
    case "$sel" in
        1) TARGET="cli" ;;
        2) TARGET="app" ;;
        3) TARGET="both" ;;
        4) do_uninstall ;;
        *) exit 0 ;;
    esac
fi
case "$TARGET" in cli|app|both) ;; *) fail "--target 只能是 cli、app 或 both" ;; esac

mkdir -p "$MMH"
exec > >(tee -a "$MMH/install.log") 2>&1
echo "---- $(date '+%Y-%m-%d %H:%M:%S') install $VERSION target=$TARGET whisper=$WHISPER backend=${BACKEND:-auto}"
if [ -n "$TEST_ROOT" ]; then warn "測試模式（--test-root）：所有檔案寫到 $TEST_ROOT"; fi

# ------------------------------------------------------------------ prerequisites
step "檢查 Homebrew"
if ! command -v brew >/dev/null 2>&1; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        [ -x "$b" ] && eval "$("$b" shellenv)" && break
    done
fi
command -v brew >/dev/null 2>&1 || fail "找不到 Homebrew。請先到 https://brew.sh 依指示安裝（需要輸入管理者密碼），完成後再執行一次 install.command"
ok "brew：$(command -v brew)"

py_ok() {   # 3.10~3.13 且為 arm64 原生
    "$1" -c 'import sys,platform; v=sys.version_info; sys.exit(0 if (v.major==3 and 10<=v.minor<=13 and platform.machine()=="arm64") else 1)' >/dev/null 2>&1
}
find_python() {
    for p in python3.12 python3.13 python3.11 python3.10 \
             /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 python3; do
        if command -v "$p" >/dev/null 2>&1 && py_ok "$(command -v "$p")"; then command -v "$p"; return 0; fi
    done
    return 1
}

step "檢查 Python（3.10 ~ 3.13，arm64）"
PY="$(find_python || true)"
if [ -z "$PY" ]; then
    echo "    以 Homebrew 安裝 python@3.12 ..."
    brew install python@3.12
    PY="$(find_python || true)"
    [ -n "$PY" ] || fail "Python 安裝後仍找不到，請開新的終端機視窗後再執行一次"
fi
ok "使用 $PY（$("$PY" --version)）"

step "檢查 ffmpeg"
if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "    以 Homebrew 安裝 ffmpeg ..."
    brew install ffmpeg
fi
command -v ffmpeg >/dev/null 2>&1 || fail "ffmpeg 安裝失敗"
ok "ffmpeg：$(command -v ffmpeg)"

# ------------------------------------------------------------------ runtime
step "安裝 runtime $VERSION 到 $MMH"
rm -rf "$MMH/scripts"
cp -R "$PAYLOAD/runtime/scripts" "$MMH/scripts"
cp "$PAYLOAD/runtime/mm-dropped.sh" "$PAYLOAD/runtime/requirements-mac.txt" "$HERE/README.md" "$HERE/THIRD-PARTY-NOTICES.md" "$MMH/"
chmod +x "$MMH/mm-dropped.sh"
if [ ! -f "$MMH/glossary.txt" ]; then
    cp "$PAYLOAD/runtime/glossary.txt" "$MMH/glossary.txt"; ok "已建立 glossary.txt（可自行編輯專有名詞）"
else
    ok "保留既有的 glossary.txt"
fi

if [ -x "$VPY" ] && ! py_ok "$VPY"; then
    warn "既有 venv 版本不符，重新建立"; rm -rf "$MMH/venv"
fi
[ -x "$VPY" ] || "$PY" -m venv "$MMH/venv" || fail "建立 venv 失敗"
"$VPY" -m pip install -U pip --disable-pip-version-check -q
"$VPY" -m pip install -U -r "$MMH/requirements-mac.txt" --disable-pip-version-check \
    || fail "安裝 Python 套件失敗，詳見 $MMH/install.log"
ok "Python 套件安裝完成（MLX：Apple GPU；faster-whisper：CPU）"

step "硬體偵測、下載模型與實測（只在安裝時進行一次）"
sb_args=("$MMH/scripts/setup_backend.py" --whisper "$WHISPER")
[ -n "$BACKEND" ]  && sb_args+=(--force "$BACKEND")
[ -n "$KEEP_ALL" ] && sb_args+=(--keep-all)
"$VPY" "${sb_args[@]}" || fail "硬體偵測或模型下載失敗（需可連線 huggingface.co 與 github.com），詳見 $MMH/install.log"

step "建立拖放用的「會議轉寫（基本版）.app」"
mkdir -p "$APPS_DIR"
rm -rf "$APP_DST"
if [ -d "$LEGACY_APP" ]; then rm -rf "$LEGACY_APP"; ok "已移除舊名稱「會議轉寫.app」（改為標示版本的名稱）"; fi
osacompile -o "$APP_DST" <<APPLESCRIPT
on open theItems
    set cmd to quoted form of "$MMH/mm-dropped.sh"
    repeat with f in theItems
        set cmd to cmd & " " & quoted form of POSIX path of f
    end repeat
    tell application "Terminal"
        activate
        do script cmd
    end tell
end open

on run
    display dialog "請把會議錄音或錄影檔拖曳到「會議轉寫（基本版）」圖示上，或在 Finder 對檔案按右鍵 →「打開檔案的應用程式」→「會議轉寫（基本版）」。" buttons {"好"} default button 1 with title "會議轉寫（基本版）"
end run
APPLESCRIPT
ok "已建立 $APP_DST（第一次使用時 macOS 會詢問是否允許控制「終端機」，請按允許）"

# ------------------------------------------------------------------ targets
if [ "$TARGET" = "cli" ] || [ "$TARGET" = "both" ]; then
    step "安裝到 Claude CLI：$SKILL_DST"
    if [ -d "$SKILL_DST" ]; then
        bak="$MMH/backup/skill-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$MMH/backup"; mv "$SKILL_DST" "$bak"; ok "舊版已備份到 $bak"
    fi
    mkdir -p "$(dirname "$SKILL_DST")"
    cp -R "$PAYLOAD/skill/meeting-minutes" "$SKILL_DST"
    ok "完成。Claude CLI 或桌面版 Code 分頁新開的 session 即可使用"
fi

if [ "$TARGET" = "app" ] || [ "$TARGET" = "both" ]; then
    step "準備 Claude App 上傳檔"
    cp "$PAYLOAD/meeting-minutes-upload.zip" "$UPLOAD_ZIP"
    ok "已放到桌面：$UPLOAD_ZIP"
    echo "    請在 Claude App：左側「自訂 (Customize)」→「Skills」→「+」→「Create skill」→「Upload a skill」，選擇上面的 zip。"
    echo "    （需在「設定 → Capabilities」開啟程式碼執行。網頁版：https://claude.ai/customize/skills）"
    if [ -z "$TEST_ROOT" ]; then open -R "$UPLOAD_ZIP" || true; fi
fi

# ------------------------------------------------------------------ summary
step "安裝完成（meeting-minutes $VERSION）"
"$VPY" - "$MMH/config.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"    選定後端：{c['backend']} / {c['device']} / {c.get('compute_type', 'default')}　模型：{c['whisper']}")
PY
echo "    runtime ：$MMH"
echo "    專有名詞：$MMH/glossary.txt"
echo "    （硬體或系統更新後，重新執行 install.command 即可重新偵測）"
[ "$TARGET" != "app" ] && echo "    CLI 用法：在 Claude CLI 說「用 meeting-minutes 整理 ~/Documents/會議/0912.m4a，與會 5 人」"
[ "$TARGET" != "cli" ] && echo "    App 用法：把錄音檔拖到「會議轉寫（基本版）」→ 把 transcript.md 附到 Claude App →「整理成會議記錄」"
if [ "$TARGET" = "both" ]; then
    warn "若 Claude CLI 以 claude.ai 帳號登入，上傳到 App 的 skill 也會同步到 CLI；看到兩個 meeting-minutes 時，兩者內容相同，用哪個都可以。"
fi
exit 0
