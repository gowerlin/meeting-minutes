#!/bin/bash
# meeting-minutes-pro 2.4.0 一鍵安裝程式（macOS Apple Silicon）
#   - 共用 runtime：~/Library/Application Support/meeting-minutes-pro（venv、模型、腳本、glossary、config）
#     設定環境變數 MEETING_MINUTES_PRO_HOME 可改放到其他位置
#   - 目標 CLI ：複製 skill 到 ~/.claude/skills/meeting-minutes-pro（Claude CLI 與桌面版 Code 分頁共用）
#   - 目標 App ：在桌面產生上傳用 skill zip（Claude App 對話 / Cowork）
#   - 都會建立 ~/Applications/會議轉寫（Pro）.app（把錄音檔拖上去即可在本機轉寫）
#   - 〔2.4.0〕另建 ~/Applications/會議轉寫（Pro，本機限定）.app（機敏會議：不做 AI 校正與整理，輸出資料夾寫入標記檔 local-only.json；
#     macOS 未實測）；config.json 的 privacy.local_only（預設 false；升級時保留既有的值）
# 用法：./install.command                 互動選單
#       ./install.sh --target both        不詢問，直接安裝（cli / app / both）
#       ./install.sh --uninstall          解除安裝
# 其他：--whisper turbo|large-v3   --backend mlx:gpu|ct2:cpu（跳過偵測；後端與裝置和既有設定相同時沿用既有精度，1.2.1）   --keep-all
#       --compute-type int8|float32|…（搭配 --backend，明確指定精度）
#       --breeze / --no-breeze（是否安裝 Breeze-ASR-25；不指定時會詢問）
#       --correct / --no-correct（在 Claude CLI 對話或命令列轉寫時是否自動校正；不指定時，第一次安裝會詢問一次。
#                                  拖放入口不受影響：1.2.0 起每次轉寫完都會問要不要做 AI 校正與會議摘要）
#       --correct-provider auto|claude|openai   --correct-model <模型>   --correct-channel cli|api
#       --test-root <資料夾>（僅供開發測試：runtime、skill、app、桌面都改放到這個資料夾底下）
# 硬體只在安裝時偵測一次，結果寫入 config.json；轉寫時不再偵測。
# 〔2.0.0〕GPU 說話者分離（pyannote）只支援 Windows＋NVIDIA；macOS 說話者分離一律用 CPU（sherpa），
#         config.json 的 diarization.pyannote.status 寫 none（規格 §8.10）。自訂範本目錄：$MMH/templates。
# 註：macOS 內建 bash 3.2，本腳本避免使用 bash 4 以上語法。

set -eo pipefail

VERSION="2.4.0"
HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/payload"
export PYTHONUTF8=1

TARGET=""; WHISPER="turbo"; BACKEND=""; COMPUTE_TYPE=""; KEEP_ALL=""; UNINSTALL=""; BREEZE=""; TEST_ROOT=""
CORRECT=""; C_PROVIDER=""; C_MODEL=""; C_CHANNEL=""
while [ $# -gt 0 ]; do
    case "$1" in
        --target)    TARGET="$(echo "$2" | tr '[:upper:]' '[:lower:]')"; shift 2 ;;
        --whisper)   WHISPER="$2"; shift 2 ;;
        --backend)   BACKEND="$2"; shift 2 ;;
        --compute-type) COMPUTE_TYPE="$2"; shift 2 ;;
        --keep-all)  KEEP_ALL=1; shift ;;
        --breeze)    BREEZE=1; shift ;;
        --no-breeze) BREEZE=0; shift ;;
        --correct)   [ "$CORRECT" = "0" ] && { echo "--correct 與 --no-correct 只能擇一"; exit 2; }; CORRECT=1; shift ;;
        --no-correct) [ "$CORRECT" = "1" ] && { echo "--correct 與 --no-correct 只能擇一"; exit 2; }; CORRECT=0; shift ;;
        --correct-provider) C_PROVIDER="$2"; shift 2 ;;
        --correct-model)    C_MODEL="$2"; shift 2 ;;
        --correct-channel)  C_CHANNEL="$2"; shift 2 ;;
        --test-root) TEST_ROOT="$2"; shift 2 ;;
        --uninstall) UNINSTALL=1; shift ;;
        *) echo "未知參數：$1"; exit 2 ;;
    esac
done
case "$C_PROVIDER" in ""|auto|claude|openai) ;; *) echo "--correct-provider 只能是 auto、claude 或 openai"; exit 2 ;; esac
case "$C_CHANNEL" in ""|cli|api) ;; *) echo "--correct-channel 只能是 cli 或 api"; exit 2 ;; esac

MMH="${MEETING_MINUTES_PRO_HOME:-$HOME/Library/Application Support/meeting-minutes-pro}"
SKILL_DST="$HOME/.claude/skills/meeting-minutes-pro"
APPS_DIR="$HOME/Applications"
DESKTOP_DIR="$HOME/Desktop"
if [ -n "$TEST_ROOT" ]; then
    # 僅供開發測試：所有寫入位置都放到 TEST_ROOT 底下，不碰使用者真正的安裝
    mkdir -p "$TEST_ROOT"; TEST_ROOT="$(cd "$TEST_ROOT" && pwd)"
    MMH="$TEST_ROOT/home"; SKILL_DST="$TEST_ROOT/skills/meeting-minutes-pro"
    APPS_DIR="$TEST_ROOT/Applications"; DESKTOP_DIR="$TEST_ROOT/Desktop"
    mkdir -p "$APPS_DIR" "$DESKTOP_DIR"
fi
export MEETING_MINUTES_PRO_HOME="$MMH"   # 讓 runtime 的 Python 腳本與本程式用同一個位置
VPY="$MMH/venv/bin/python"
APP_DST="$APPS_DIR/會議轉寫（Pro）.app"
# 〔2.4.0〕第二個拖放入口：本機限定（規格 2.4.0 §2.2、§4；macOS 未實測）。從這裡轉寫的輸出資料夾寫入標記檔 local-only.json
APP_DST_LOCAL="$APPS_DIR/會議轉寫（Pro，本機限定）.app"
LEGACY_APP="$APPS_DIR/會議轉寫 Pro.app"   # 舊版名稱（未標示版本）
UPLOAD_ZIP="$DESKTOP_DIR/meeting-minutes-pro-skill-upload.zip"

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
# 〔2.3.0〕會議記錄校稿（Pro 的附屬工具，另外安裝在 $MMH/proofread）：Pro 解除安裝時，它的移除程式存在就先以安靜模式
# 執行（--quiet：不詢問、保留最近的稿清單；測試模式另傳 --test-root），再處理 Pro 自己的檔案與 runtime（規格 2.3.0 §4）。
# 沒裝校稿時什麼都不做；移除程式失敗只提示，不中止 Pro 的解除安裝。
uninstall_proofread() {
    local u="$MMH/proofread/uninstall.sh" rc=0
    [ -f "$u" ] || return 0
    echo "    先移除會議記錄校稿（Pro 的附屬工具）..."
    if [ -n "$TEST_ROOT" ]; then
        bash "$u" --quiet --test-root "$TEST_ROOT" || rc=$?
    else
        bash "$u" --quiet || rc=$?
    fi
    if [ "$rc" -eq 0 ]; then ok "已移除會議記錄校稿"
    else warn "會議記錄校稿的移除程式回報錯誤（exit $rc）；之後可手動執行 $u"; fi
}

do_uninstall() {
    step "解除安裝 meeting-minutes-pro"
    uninstall_proofread
    [ -d "$SKILL_DST" ]  && rm -rf "$SKILL_DST"  && ok "已移除 Claude CLI skill：$SKILL_DST"
    [ -d "$APP_DST" ]    && rm -rf "$APP_DST"    && ok "已移除 會議轉寫（Pro）.app"
    [ -d "$APP_DST_LOCAL" ] && rm -rf "$APP_DST_LOCAL" && ok "已移除 會議轉寫（Pro，本機限定）.app"
    [ -d "$LEGACY_APP" ] && rm -rf "$LEGACY_APP" && ok "已移除舊名稱的 app"
    [ -f "$UPLOAD_ZIP" ] && rm -f "$UPLOAD_ZIP"  && ok "已移除桌面上的上傳用 zip"
    if [ -d "$MMH" ]; then
        n_tpl=0
        for t in "$MMH/templates"/*.md; do [ -f "$t" ] && [ "$(basename "$t")" != "README.md" ] && n_tpl=$((n_tpl + 1)); done
        echo "    runtime（$MMH）裡有：venv、模型（含 1.1.0 的標點模型）、腳本、glossary.txt、corrections.tsv、"
        echo "    opencc_keep.tsv、自動校正的建議歷史與對照表備份、config.json、THIRD-PARTY-NOTICES.md"
        echo "    〔2.0〕自訂範本（templates，$n_tpl 份）、記住上次類型的 state.json"
        read -r -p "    是否一併刪除 runtime 與模型（約 2GB）？[y/N] " ans
        case "$ans" in
            [yY]*)
                # 〔2.0.0 規格 §8.9〕自訂範本是使用者寫的檔案：先問，預設保留並移到桌面
                if [ "$n_tpl" -gt 0 ]; then
                    read -r -p "    刪除自訂範本 $n_tpl 份？[y/N] " a2
                    case "$a2" in
                        [yY]*) ;;
                        *)
                            bk="$DESKTOP_DIR/meeting-minutes-pro-templates-備份"
                            [ -e "$bk" ] && bk="$bk-$(date +%Y%m%d-%H%M%S)"
                            mkdir -p "$bk"
                            for t in "$MMH/templates"/*.md; do [ "$(basename "$t")" != "README.md" ] && cp "$t" "$bk/"; done
                            ok "自訂範本 $n_tpl 份已移到 $bk" ;;
                    esac
                fi
                rm -rf "$MMH"; ok "已刪除 $MMH" ;;
            *) warn "保留 $MMH（含 glossary.txt、corrections.tsv、opencc_keep.tsv 與模型，以及自訂範本）" ;;
        esac
    fi
    echo "    不會變更 Claude Code、Codex 本身與它們的登入；各會議的輸出資料夾（<檔名>_minutes）也不會刪除。"
    warn "若曾上傳到 Claude App，請到 App 的「自訂 (Customize) → Skills」手動刪除 meeting-minutes-pro。"
    exit 0
}
[ -n "$UNINSTALL" ] && do_uninstall

# ------------------------------------------------------------------ menu
[ -d "$PAYLOAD" ] || fail "找不到 payload 資料夾，請先把整個 zip 解壓縮再執行"
if [ -z "$TARGET" ]; then
    has_cli="未偵測到"; { command -v claude >/dev/null 2>&1 || [ -d "$HOME/.claude" ]; } && has_cli="已安裝"
    has_app="未偵測到"; [ -d "/Applications/Claude.app" ] || [ -d "$HOME/Applications/Claude.app" ] && has_app="已安裝"
    echo
    echo "  meeting-minutes-pro $VERSION 會議記錄 skill 安裝程式（macOS）"
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
if [ -z "$BREEZE" ]; then
    echo
    echo "  Breeze-ASR-25（MediaTek，台灣華語／中英夾雜特化，Apache-2.0）"
    echo "  - 適合中英夾雜很重的技術會議；比 turbo 準，但慢數倍；額外約 3GB"
    read -r -p "  是否安裝 Breeze-ASR-25？[Y/n] " ans
    case "$ans" in [nN]*) BREEZE=0 ;; *) BREEZE=1 ;; esac
fi

# ------------------------------------------------------------------ 自動校正（選用）：偵測與詢問（只問一次）
model_provider() {   # sonnet/opus/haiku/claude-* -> claude；gpt-*/o<數字>* -> openai
    case "$1" in
        "") echo "" ;;
        sonnet|opus|haiku|claude-*) echo claude ;;
        gpt-*|o[0-9]*) echo openai ;;
        *) echo "?" ;;
    esac
}
M_PROV="$(model_provider "$C_MODEL")"
[ "$M_PROV" = "?" ] && fail "無法判斷 --correct-model $C_MODEL 屬於哪一家，請加 --correct-provider claude 或 openai"
if [ -n "$M_PROV" ]; then
    case "$C_PROVIDER" in
        ""|auto) C_PROVIDER="$M_PROV" ;;
        "$M_PROV") ;;
        *) fail "--correct-model $C_MODEL 不是 $C_PROVIDER 的模型" ;;
    esac
fi

cfg_get() {   # 讀既有 config.json 的值（點分隔路徑）；沒有 config 或 venv 時輸出空字串
    [ -x "$VPY" ] && [ -f "$MMH/config.json" ] || return 0
    "$VPY" -c 'import json,sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
for k in sys.argv[2].split("."):
    c = c.get(k) if isinstance(c, dict) else None
print("" if c is None else ("1" if c is True else ("0" if c is False else c)))' "$MMH/config.json" "$1" 2>/dev/null || true
}
# 依序找：設定的 cli_path → PATH → 固定位置（從 Finder 啟動時 PATH 不含 ~/.local/bin）；--version 成功才算找到
find_cli() {   # $1=名稱 $2=設定的 cli_path，其餘=固定位置；輸出兩行：路徑、版本
    local name="$1" cfgp="$2"; shift 2
    local c v
    for c in "$cfgp" "$(command -v "$name" 2>/dev/null || true)" "$@"; do
        [ -n "$c" ] && [ -x "$c" ] || continue
        v="$("$c" --version 2>/dev/null | head -n 1)" || continue
        [ -n "$v" ] && { printf '%s\n%s\n' "$c" "$v"; return 0; }
    done
    return 0
}
HAS_CORRECTION_KEY=""
[ -n "$(cfg_get correction)" ] && HAS_CORRECTION_KEY=1
CLAUDE_CLI="$(find_cli claude "$(cfg_get correction.claude.cli_path)" \
    "$HOME/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude)"
CODEX_CLI="$(find_cli codex "$(cfg_get correction.openai.cli_path)" \
    "$HOME/.local/bin/codex" "$HOME/.codex/packages/standalone/current/bin/codex" /opt/homebrew/bin/codex /usr/local/bin/codex)"
CLAUDE_PATH="$(printf '%s\n' "$CLAUDE_CLI" | sed -n 1p)"; CLAUDE_VER="$(printf '%s\n' "$CLAUDE_CLI" | sed -n 2p)"
CODEX_PATH="$(printf '%s\n' "$CODEX_CLI" | sed -n 1p)";   CODEX_VER="$(printf '%s\n' "$CODEX_CLI" | sed -n 2p)"
CODEX_AUTH=""
if [ -n "$CODEX_PATH" ]; then   # codex login status：已登入 exit 0、未登入 exit 1；只看 exit code 與第一行，不顯示其他內容
    if login_out="$("$CODEX_PATH" login status 2>&1)"; then
        case "$(printf '%s\n' "$login_out" | head -n 1)" in *"API key"*) CODEX_AUTH=api_key ;; *) CODEX_AUTH=chatgpt ;; esac
    else
        CODEX_AUTH=none
    fi
    login_out=""
fi
resolve_provider() {   # $1=provider $2=channel -> claude|openai|空字串
    case "$1" in claude|openai) echo "$1"; return ;; esac
    if [ "$2" = "api" ]; then
        # 〔1.1.0〕API 通道也是 GPT（OpenAI）優先（與 auto_correct.select_backend 相同）
        if [ -n "${OPENAI_API_KEY:-}" ]; then echo openai; elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then echo claude; else echo ""; fi
        return
    fi
    # 〔1.1.0〕已登入的 codex 優先（gpt-6.1-sol 在實測較準、較便宜）；codex 沒登入時改用 claude
    if [ -n "$CODEX_PATH" ] && [ "$CODEX_AUTH" != "none" ]; then echo openai
    elif [ -n "$CLAUDE_PATH" ]; then echo claude
    elif [ -n "$CODEX_PATH" ]; then echo openai
    else echo ""; fi
}
cli_line() {   # $1=標籤 $2=路徑 $3=版本 $4=登入狀態
    if [ -z "$2" ]; then echo "  - 偵測：$1未找到"; return; fi
    local s="  - 偵測：$1已找到：$2（$3）"
    case "$4" in
        chatgpt) s="$s，登入：是（ChatGPT 帳號）" ;;
        api_key) s="$s，登入：是（API 金鑰，依 API 用量計費）" ;;
        none)    s="$s，登入：否" ;;
    esac
    echo "$s"
}

C_ENABLED=""
[ "$CORRECT" = "1" ] && C_ENABLED=true
[ "$CORRECT" = "0" ] && C_ENABLED=false
ASK_PROVIDER="${C_PROVIDER:-auto}"; ASK_CHANNEL="${C_CHANNEL:-cli}"
if [ "$CORRECT" = "1" ] && [ -z "$C_PROVIDER" ]; then
    # 不詢問直接開啟：寫入實際會用的供應商，之後不會因為新裝了另一家的 CLI 就改送到另一家
    C_PROVIDER="$(resolve_provider auto "$ASK_CHANNEL")"
fi
if [ -z "$CORRECT" ] && [ -z "$HAS_CORRECTION_KEY" ]; then
    PLAN="$(resolve_provider "$ASK_PROVIDER" "$ASK_CHANNEL")"
    echo
    echo "  自動校正（選用）"
    echo "  - 轉寫完成後，用你的 ChatGPT 或 Claude 訂閱（Codex 的 codex 指令，或 Claude Code 的 claude 指令）"
    echo "    自動修正同音錯字與專有名詞，產出 transcript.corrected.md；transcript.md 原稿不會被修改"
    cli_line "claude CLI " "$CLAUDE_PATH" "$CLAUDE_VER" ""
    cli_line "codex CLI  " "$CODEX_PATH" "$CODEX_VER" "$CODEX_AUTH"
    ASK_MODEL=""; if [ -n "$C_MODEL" ] && [ "$(model_provider "$C_MODEL")" = "$PLAN" ]; then ASK_MODEL="$C_MODEL"; fi
    case "$PLAN" in
        claude)
            echo "  - 將使用：Claude（${ASK_MODEL:-opus}）。開啟後，逐字稿文字與影片截圖會送到 Claude（Anthropic）（音檔不會；要關掉截圖：config 的 reference.frames 改成 false）"
            echo "    一小時會議約多花 5 分鐘，並用掉 Claude 訂閱額度；每次轉寫時可以改選模型"
            if [ -n "$CODEX_PATH" ] && [ "$CODEX_AUTH" = "none" ]; then echo "    （codex 已安裝但尚未登入，所以使用 Claude；要用 GPT 請先執行 codex login 再重新安裝並加 --correct --correct-provider openai）"; fi ;;
        openai)
            echo "  - 將使用：GPT（${ASK_MODEL:-gpt-6.1-sol}，透過 Codex）。開啟後，逐字稿文字與影片截圖會送到 GPT（OpenAI）（音檔不會；要關掉截圖：config 的 reference.frames 改成 false）"
            echo "    一小時會議約多花 7 分鐘，並用掉 ChatGPT 訂閱的 Codex 額度；每次轉寫時可以改選模型"
            if [ "$CODEX_AUTH" = "none" ]; then echo "    Codex 尚未登入：開啟後請在終端機執行 codex login 登入"; fi
            if [ "$CODEX_AUTH" = "api_key" ]; then echo "    Codex 目前以 API 金鑰登入，會依 API 用量計費"; fi ;;
        *)
            echo "  - 沒有找到 claude 或 codex 指令；回答 y 之後可以改用 API 金鑰（依用量付費）" ;;
    esac
    echo "  - 這一題只決定在 Claude CLI 對話中轉寫（或直接執行 transcribe.py）時要不要自動校正；"
    echo "    拖放到「會議轉寫（Pro）」時，每次轉寫完都會問要不要做 AI 校正與會議摘要（1.2.0），不受這一題影響"
    read -r -p "  是否開啟自動校正？[y/N] " ans
    case "$ans" in
        [yY]*)
            if [ -n "$PLAN" ]; then
                C_ENABLED=true; C_PROVIDER="$PLAN"; C_CHANNEL="$ASK_CHANNEL"
            else
                echo "  沒有找到 claude 或 codex CLI。改用 API 金鑰（需自行設定環境變數，依用量付費）？"
                echo "  [1] Claude（Anthropic API 金鑰，環境變數 ANTHROPIC_API_KEY）"
                echo "  [2] GPT（OpenAI API 金鑰，環境變數 OPENAI_API_KEY）"
                read -r -p "  請選擇 [1/2/N] " ans2
                case "$ans2" in
                    1) C_ENABLED=true; C_PROVIDER=claude; C_CHANNEL=api ;;
                    2) C_ENABLED=true; C_PROVIDER=openai; C_CHANNEL=api ;;
                    *) C_ENABLED=false
                       warn "未開啟。安裝 Claude Code 或 Codex 並登入後，重新執行 ./install.sh --correct 即可開啟" ;;
                esac
            fi ;;
        *) C_ENABLED=false ;;
    esac
fi
# 要裝哪個 API SDK：只在選了 API 通道時裝，依供應商裝 anthropic 或 openai
API_PKGS=""
FINAL_CHANNEL="${C_CHANNEL:-$(cfg_get correction.channel)}"
if [ "$FINAL_CHANNEL" = "api" ]; then
    case "${C_PROVIDER:-$(cfg_get correction.provider)}" in
        claude) API_PKGS="anthropic" ;;
        openai) API_PKGS="openai" ;;
        *) API_PKGS="anthropic openai" ;;
    esac
fi

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
# 清掉舊版殘留腳本：只刪 scripts/。〔2.3.0〕$MMH 底下的其他資料夾（含會議記錄校稿的 proofread/、使用者的 templates/、
# 模型、venv）一律保留：不要改成清空 $MMH（tests/test_v230.py 檢查）
rm -rf "$MMH/scripts"
cp -R "$PAYLOAD/runtime/scripts" "$MMH/scripts"
cp "$PAYLOAD/runtime/mm-dropped.sh" "$PAYLOAD/runtime/requirements-mac.txt" "$HERE/README.md" "$MMH/"
if [ -f "$PAYLOAD/runtime/requirements-api.txt" ]; then cp "$PAYLOAD/runtime/requirements-api.txt" "$MMH/"; fi
if [ -f "$HERE/THIRD-PARTY-NOTICES.md" ]; then cp "$HERE/THIRD-PARTY-NOTICES.md" "$MMH/"; fi
chmod +x "$MMH/mm-dropped.sh"
if [ ! -f "$MMH/glossary.txt" ]; then
    cp "$PAYLOAD/runtime/glossary.txt" "$MMH/glossary.txt"; ok "已建立 glossary.txt（可自行編輯專有名詞）"
else
    ok "保留既有的 glossary.txt"
fi
if [ ! -f "$MMH/corrections.tsv" ]; then
    cp "$PAYLOAD/runtime/corrections.tsv" "$MMH/corrections.tsv"; ok "已建立 corrections.tsv（固定錯誤對照表）"
else
    ok "保留既有的 corrections.tsv"
fi
# 〔2.0.0 規格 §3.8.1、§9.2〕自訂範本目錄：已存在就不動使用者的範本，只更新 README.md
mkdir -p "$MMH/templates"
cp "$PAYLOAD/runtime/templates/README.md" "$MMH/templates/README.md"
ok "自訂範本目錄：$MMH/templates（格式說明見 README.md）"

if [ -x "$VPY" ] && ! py_ok "$VPY"; then
    warn "既有 venv 版本不符，重新建立"; rm -rf "$MMH/venv"
fi
[ -x "$VPY" ] || "$PY" -m venv "$MMH/venv" || fail "建立 venv 失敗"
"$VPY" -m pip install -U pip --disable-pip-version-check -q
"$VPY" -m pip install -U -r "$MMH/requirements-mac.txt" --disable-pip-version-check \
    || fail "安裝 Python 套件失敗，詳見 $MMH/install.log"
ok "Python 套件安裝完成（MLX：Apple GPU；faster-whisper：CPU）"

if [ -n "$API_PKGS" ]; then
    step "安裝自動校正 API 通道套件：$API_PKGS"
    specs=()
    for pkg in $API_PKGS; do
        line=""
        if [ -f "$MMH/requirements-api.txt" ]; then
            line="$(grep -E "^[[:space:]]*$pkg([[:space:]]*[<>=!~;[]|[[:space:]]*\$)" "$MMH/requirements-api.txt" | head -n 1 \
                    | sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//' || true)"
        fi
        specs+=("${line:-$pkg}")
    done
    if "$VPY" -m pip install -U "${specs[@]}" --disable-pip-version-check; then
        ok "已安裝 ${specs[*]}"
    else
        warn "API 套件安裝失敗；之後可執行 \"$VPY\" -m pip install -r \"$MMH/requirements-api.txt\""
    fi
fi

step "硬體偵測、下載模型與實測（只在安裝時進行一次）"
sb_args=("$MMH/scripts/setup_backend.py" --whisper "$WHISPER")
[ -n "$BACKEND" ]  && sb_args+=(--force "$BACKEND")
# 〔1.2.1〕--compute-type 明確指定精度；不指定時 setup_backend.py 在後端與裝置相同時沿用 config.json 既有的 compute_type
if [ -n "$COMPUTE_TYPE" ]; then
    if [ -n "$BACKEND" ]; then sb_args+=(--compute-type "$COMPUTE_TYPE")
    else warn "--compute-type 要搭配 --backend 使用（自動偵測時精度由實測決定），這次忽略"; fi
fi
[ -n "$KEEP_ALL" ] && sb_args+=(--keep-all)
[ "$BREEZE" = "1" ] && sb_args+=(--breeze)
SB_OUT="$MMH/.setup_backend.out"
# 〔1.2.2〕MMP_INSTALLING=1：config.json 的 runtime_version 要到「更新設定」才更新，這裡的版號提示改印「升級中」而不是「請重新執行安裝程式」
MMP_INSTALLING=1 "$VPY" "${sb_args[@]}" | tee "$SB_OUT" || { rm -f "$SB_OUT"; fail "硬體偵測或模型下載失敗（需可連線 huggingface.co 與 github.com），詳見 $MMH/install.log"; }
PUNCT_OK="$(tail -n 1 "$SB_OUT" | "$VPY" -c 'import json,sys
try: print(1 if json.loads(sys.stdin.read()).get("punct") else 0)
except Exception: print(0)' 2>/dev/null || echo 0)"
rm -f "$SB_OUT"
if [ "$PUNCT_OK" != "1" ]; then
    warn "標點模型未安裝：逐字稿仍會分段，turbo 沿用 Whisper 標點。之後可執行 \"$VPY\" \"$MMH/scripts/setup_backend.py\" --punct-only 補裝"
fi

step "更新設定（config.json）與 OpenCC 詞彙回復表"
# 〔2.0.0 規格 §8.10〕macOS 不提供 GPU 說話者分離：diarization.pyannote.status 一律寫 none
echo "    說話者分離：CPU（sherpa）。GPU 說話者分離（pyannote）只支援 Windows＋NVIDIA 顯示卡"
# 補上 1.1.0／1.2.0 新增的設定鍵（已存在的鍵與使用者改過的值一律保留）；建立使用者的 opencc_keep.tsv（不存在才建立）
if MMP_GPU_DIAR='{"status": "none", "reason": null}' MMP_SCRIPTS="$MMH/scripts" MMP_ENABLED="$C_ENABLED" MMP_PROVIDER="$C_PROVIDER" MMP_CHANNEL="$C_CHANNEL" MMP_MODEL="$C_MODEL" \
    "$VPY" -B - <<'PY'
import copy, json, os, sys
sys.path.insert(0, os.environ["MMP_SCRIPTS"])
import common
import opencc_keep

def merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge(dst[k], v)
        else:
            dst[k] = v

choice = {}
e, p, ch, m = (os.environ.get(k, "") for k in ("MMP_ENABLED", "MMP_PROVIDER", "MMP_CHANNEL", "MMP_MODEL"))
if e:
    choice["enabled"] = e == "true"
if p:
    choice["provider"] = p
if ch:
    choice["channel"] = ch
if m and p in ("claude", "openai"):
    choice[p] = {"model": m}
before = common.load_config()
cfg = common.upgrade_config()
added = common.added_config_keys(before, cfg)   # 〔1.2.2〕實際補上的鍵（不含安裝時的明確選擇與 runtime_version）
if choice:
    cur = cfg.get("correction")
    if not isinstance(cur, dict):
        cur = copy.deepcopy(common.DEFAULTS["correction"])
    merge(cur, choice)
    cfg = common.upgrade_config(correction=cur)
# 〔2.0.0 規格 §8.10〕GPU 說話者分離的狀態（macOS 一律 none；只有安裝程式寫 status）
gd = json.loads(os.environ.get("MMP_GPU_DIAR") or "null")
if gd:
    p = cfg.setdefault("diarization", {}).setdefault("pyannote", {})
    p["status"], p["reason"] = gd.get("status"), gd.get("reason")
    common.config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
_, user = common.opencc_keep_paths()
if not user.exists():
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text(opencc_keep.USER_TEMPLATE, encoding="utf-8")
    print("    [OK] 已建立 opencc_keep.tsv（OpenCC 詞彙回復表的使用者表，可自行加詞）")
else:
    print("    [OK] 保留既有的 opencc_keep.tsv")
# 〔1.2.2〕依實際情況：有補鍵時列出補了哪些，沒有補任何鍵時寫「設定鍵無變更」
if added:
    print("    [OK] config.json 已補上新版設定鍵：%s（既有的值不變）" % "、".join(added))
else:
    print("    [OK] config.json 設定鍵無變更（runtime_version 更新為 %s）" % common.VERSION)
PY
then :; else
    warn "更新 config.json 失敗；轉寫仍照 $VERSION 預設值執行。可重新執行安裝程式再試一次"
fi

step "建立拖放用的「會議轉寫（Pro）.app」與「會議轉寫（Pro，本機限定）.app」"
mkdir -p "$APPS_DIR"
if [ -d "$LEGACY_APP" ]; then rm -rf "$LEGACY_APP"; ok "已移除舊名稱「會議轉寫 Pro.app」（改為標示版本的名稱）"; fi
# 〔2.4.0〕兩個拖放入口（規格 2.4.0 §4）：$1＝.app 路徑 $2＝名稱 $3＝傳給 mm-dropped.sh 的第一個參數（本機限定：--local-only）
make_drop_app() {
    local dst="$1" name="$2" first="$3" prefix
    prefix="quoted form of \"$MMH/mm-dropped.sh\""
    [ -n "$first" ] && prefix="$prefix & \" $first\""
    rm -rf "$dst"
    osacompile -o "$dst" <<APPLESCRIPT
on open theItems
    set cmd to $prefix
    repeat with f in theItems
        set cmd to cmd & " " & quoted form of POSIX path of f
    end repeat
    tell application "Terminal"
        activate
        do script cmd
    end tell
end open

on run
    display dialog "請把會議錄音或錄影檔拖曳到「$name」圖示上，或在 Finder 對檔案按右鍵 →「打開檔案的應用程式」→「$name」。" buttons {"好"} default button 1 with title "$name"
end run
APPLESCRIPT
}
make_drop_app "$APP_DST" "會議轉寫（Pro）" ""
ok "已建立 $APP_DST（第一次使用時 macOS 會詢問是否允許控制「終端機」，請按允許）"
make_drop_app "$APP_DST_LOCAL" "會議轉寫（Pro，本機限定）" "--local-only"
ok "已建立 $APP_DST_LOCAL（機敏會議用：不做 AI 校正與整理，輸出資料夾會標記 local-only.json）"

# ------------------------------------------------------------------ targets
if [ "$TARGET" = "cli" ] || [ "$TARGET" = "both" ]; then
    step "安裝到 Claude CLI：$SKILL_DST"
    if [ -d "$SKILL_DST" ]; then
        bak="$MMH/backup/skill-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$MMH/backup"; mv "$SKILL_DST" "$bak"; ok "舊版已備份到 $bak"
    fi
    mkdir -p "$(dirname "$SKILL_DST")"
    cp -R "$PAYLOAD/skill/meeting-minutes-pro" "$SKILL_DST"
    ok "完成。Claude CLI 或桌面版 Code 分頁新開的 session 即可使用"
fi

if [ "$TARGET" = "app" ] || [ "$TARGET" = "both" ]; then
    step "準備 Claude App 上傳檔"
    cp "$PAYLOAD/meeting-minutes-pro-upload.zip" "$UPLOAD_ZIP"
    ok "已放到桌面：$UPLOAD_ZIP"
    echo "    請在 Claude App：左側「自訂 (Customize)」→「Skills」→「+」→「Create skill」→「Upload a skill」，選擇上面的 zip。"
    echo "    （需在「設定 → Capabilities」開啟程式碼執行。網頁版：https://claude.ai/customize/skills）"
    if [ -z "$TEST_ROOT" ]; then open -R "$UPLOAD_ZIP" || true; fi
fi

# ------------------------------------------------------------------ summary
step "安裝完成（meeting-minutes-pro $VERSION）"
"$VPY" - "$MMH/config.json" <<'PY'
import json, sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
print(f"    選定後端：{c['backend']} / {c['device']} / {c.get('compute_type', 'default')}　模型：{c['whisper']}")
b = c.get("profiles", {}).get("breeze")
if b:
    print(f"    Breeze  ：{b['backend']} / {b['device']}（RTF {b['rtf']}）　轉寫時加 --whisper breeze")
PY
echo "    runtime ：$MMH"
echo "    專有名詞：$MMH/glossary.txt"
echo "    對照表  ：$MMH/corrections.tsv"
if [ "$(cfg_get punctuation.enabled)" = "0" ]; then echo "    分段標點：關（config.json 的 punctuation.enabled）"
elif [ "$PUNCT_OK" = "1" ]; then echo "    分段標點：開（標點模型 OK）"
else echo "    分段標點：開（標點模型未安裝，目前只分段；執行 setup_backend.py --punct-only 補裝）"; fi
echo "    OpenCC 詞彙回復表：$MMH/opencc_keep.tsv"
echo "    說話者分離：CPU（sherpa）"
echo "    內容類型：預設 會議（轉寫時第一題可改選，會記住上次的選擇）；自訂範本目錄 $MMH/templates"
if [ "$(cfg_get correction.enabled)" = "1" ]; then
    ch="$(cfg_get correction.channel)"; ch="${ch:-cli}"
    p="$(resolve_provider "$(cfg_get correction.provider)" "$ch")"
    m=""; if [ -n "$p" ]; then m="$(cfg_get "correction.$p.model")"; fi
    case "$p" in
        claude) label=Claude; vendor="Claude（Anthropic）"; key=ANTHROPIC_API_KEY; m="${m:-opus}" ;;   # 與 common.DEFAULTS 一致
        openai) label=GPT; vendor="GPT（OpenAI）"; key=OPENAI_API_KEY; m="${m:-gpt-6.1-sol}" ;;          # 〔2.4.0〕GPT／Claude
        *) label="自動選擇"; vendor="所選的 AI"; key="ANTHROPIC_API_KEY 或 OPENAI_API_KEY" ;;
    esac
    if [ "$ch" = "api" ]; then how="API 通道（未實測），需環境變數 $key"
    elif [ "$p" = "claude" ] && [ -n "$CLAUDE_PATH" ]; then how="訂閱 CLI：$CLAUDE_PATH"
    elif [ "$p" = "openai" ] && [ -n "$CODEX_PATH" ]; then
        how="Codex CLI：$CODEX_PATH"
        if [ "$CODEX_AUTH" = "none" ]; then how="$how；尚未登入，請執行 codex login"; fi
    else how="找不到對應的 CLI，轉寫時會略過；安裝並登入後即可使用"; fi
    echo "    自動校正（CLI 對話與命令列）：開（$label $m，$how）；逐字稿文字與影片截圖會送到 $vendor"
    ca="$(cfg_get correction.corrections_auto.mode)"
    if [ -n "$ca" ] && [ "$ca" != "off" ]; then echo "    對照表自動寫入：$ca（config.json 的 correction.corrections_auto）"; fi
else
    echo "    自動校正（CLI 對話與命令列）：關（要開啟：重新執行 ./install.sh --correct）"
fi
echo "    （硬體或系統更新後，重新執行 install.command 即可重新偵測）"
echo "    拖放入口：轉寫完會問「要做 AI 校正嗎？」「要產生會議摘要嗎？」（按 Enter＝是；config.json 的 correction.ask_default、minutes.ask_default）"
# 〔2.4.0〕本機限定（規格 2.4.0 §2）
if [ "$(cfg_get privacy.local_only)" = "1" ]; then
    echo "    本機限定：開（config.json 的 privacy.local_only；每一份都不送 GPT 或 Claude，拖放轉寫不問 AI 校正與整理）"
else
    echo "    本機限定：關（機敏會議拖到「會議轉寫（Pro，本機限定）」；整部電腦都不送雲端：config.json 的 privacy.local_only 改成 true）"
fi
echo "    執行 log：每個輸出資料夾的 run_log.jsonl；歷次摘要 $MMH/logs/runs.jsonl（彙整：scripts/runlog.py summary）"
[ "$TARGET" != "app" ] && echo "    CLI 用法：在 Claude CLI 說「用 meeting-minutes-pro 整理 ~/Documents/會議/0912.m4a，與會 5 人」"
[ "$TARGET" != "cli" ] && echo "    App 用法：把錄音檔拖到「會議轉寫（Pro）」→ 把 transcript.md（有自動校正時用 transcript.corrected.md）附到 Claude App →「整理成會議記錄」；轉寫完選了會議摘要時，另有 AI 整理的 meeting-minutes.md"
if [ "$TARGET" = "both" ]; then
    warn "若 Claude CLI 以 claude.ai 帳號登入，上傳到 App 的 skill 也會同步到 CLI；看到兩個 meeting-minutes-pro 時，兩者內容相同，用哪個都可以。"
fi
exit 0
