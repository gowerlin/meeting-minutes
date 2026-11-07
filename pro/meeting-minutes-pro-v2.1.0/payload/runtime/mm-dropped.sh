#!/bin/bash
# macOS：拖放到「會議轉寫（Pro）.app」或以它開啟檔案時，在「終端機」中執行的轉寫腳本（meeting-minutes-pro 2.1.0）
# 流程（1.2.0）：先問轉寫要用的資訊 → 轉寫 → 逐字稿完成後依序問「要做 AI 校正嗎？」「要產生會議摘要嗎？」（按 Enter＝是）
# 〔1.2.2〕每次詢問（含最後的「按 Enter 關閉」）前先清空鍵盤緩衝（flush_input）
# 〔2.0.0〕轉寫前的提問：內容類型（含自訂範本；記住上次，$MMH/state.json）→ 講者人數／s 略過 → 專有名詞 → Breeze（規格 §7.1、§7.2）；
#         整理的題目與輸出依類型（會議：meeting-minutes.md；其他：notes.md）；結束畫面列字幕、說話者分離退回與零星講者（§7.4）
# 〔2.1.0〕網頁版（規格 2.1.0 §7.1）：不加題目；auto_minutes.py 會接著產生 meeting-minutes.html／notes.html。結束畫面讀
#         auto_minutes.json 的 html：產生成功才列 .html（括號依 media：found／explicit「時間碼可點播放」，其他「時間碼為文字」），
#         「下一步」改成打開 .html；網頁版失敗時多一行說明（原因與 render_html.py 補做的指令）
# 本腳本由安裝程式放在 runtime 根目錄；讓轉寫腳本用同一個位置（也支援 MEETING_MINUTES_PRO_HOME 改放的位置）
MMH="$(cd "$(dirname "$0")" && pwd)"
export MEETING_MINUTES_PRO_HOME="$MMH"
PY="$MMH/venv/bin/python"
SCR="$MMH/scripts"
export PYTHONUTF8=1
# 〔1.2.0〕標題列與第一行顯示版號：取 scripts/common.py 的 VERSION，讀不到時用 config.json 的 runtime_version；不一致時兩個都印
VER_CODE="$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$SCR/common.py" 2>/dev/null | head -n 1)"
VER_CFG="$(sed -n 's/.*"runtime_version": *"\([^"]*\)".*/\1/p' "$MMH/config.json" 2>/dev/null | head -n 1)"
if [ -n "$VER_CODE" ]; then VER_LINE="meeting-minutes-pro $VER_CODE"
elif [ -n "$VER_CFG" ]; then VER_LINE="meeting-minutes-pro $VER_CFG（取自 config.json）"
else VER_LINE="meeting-minutes-pro（版號不明）"; fi
if [ -n "$VER_CODE" ] && [ -n "$VER_CFG" ] && [ "$VER_CODE" != "$VER_CFG" ]; then
    VER_LINE="$VER_LINE（config.json 的 runtime_version 是 $VER_CFG，版號不一致：請重新執行安裝程式）"
fi
printf '\033]0;會議轉寫（Pro）%s\007' "$VER_LINE"
printf '\033[35m==== 會議轉寫（Pro）　%s ====\033[0m\n' "$VER_LINE"
[ -x "$PY" ] && "$PY" -c 'import json,sys; c=json.load(open(sys.argv[1], encoding="utf-8")); print("後端：%s / %s　模型：%s" % (c["backend"], c["device"], c["whisper"]))' "$MMH/config.json" 2>/dev/null

# 〔1.2.2〕詢問前清掉終端機裡已輸入、還沒被讀走的字元：轉寫或 AI 處理中誤按的 Enter 會留在緩衝區，
# 被下一題或最後的「按 Enter 關閉」吃掉（視窗直接關閉、題目被誤答）。
# stdin 不是終端機（管線、測試）時略過。bash 3.2（macOS 內建）沒有小數秒的 read -t，-t 0 也不是「只檢查有無輸入」（4.0 才有），
# 所以改用 stty 暫時關掉整行模式、設成「沒有輸入就立刻回傳」，用 cat 讀到空為止，再還原終端機設定；任何一步失敗都略過、不得讓入口出錯。
flush_input() {
    [ -t 0 ] || return 0
    local old
    old="$(stty -g 2>/dev/null)" || return 0
    [ -n "$old" ] || return 0
    if stty -icanon min 0 time 0 2>/dev/null; then
        cat >/dev/null 2>&1
    fi
    stty "$old" 2>/dev/null
    return 0
}

if [ ! -x "$PY" ]; then
    echo "尚未安裝 runtime，請重新執行 install.command"
    flush_input; read -r -p "按 Enter 關閉" _; exit 1
fi
if [ "$#" -eq 0 ]; then
    echo "請把會議錄音或錄影檔拖曳到「會議轉寫（Pro）」圖示上"
    flush_input; read -r -p "按 Enter 關閉" _; exit 1
fi

cfg_get() {   # 讀 config.json 的值（點分隔路徑）；true/false 輸出 1/0，沒有就輸出空字串
    "$PY" -c 'import json,sys
c = json.load(open(sys.argv[1], encoding="utf-8"))
for k in sys.argv[2].split("."):
    c = c.get(k) if isinstance(c, dict) else None
print("" if c is None else ("1" if c is True else ("0" if c is False else c)))' "$MMH/config.json" "$1" 2>/dev/null || true
}
find_cli() {   # 只找執行檔（不呼叫模型），印出路徑；$1=名稱 $2=設定的 cli_path，其餘=固定位置（從 Finder 啟動時 PATH 不含 ~/.local/bin）
    local name="$1" cfgp="$2" f; shift 2
    if [ -n "$cfgp" ] && [ -x "$cfgp" ]; then echo "$cfgp"; return 0; fi
    if command -v "$name" >/dev/null 2>&1; then command -v "$name"; return 0; fi
    for f in "$@"; do if [ -x "$f" ]; then echo "$f"; return 0; fi; done
    return 1
}
codex_logged_in() {   # codex login status（不耗額度，與 Python 腳本的判斷相同：exit 0＝已登入）；不印、不存輸出
    env -u OPENAI_API_KEY -u CODEX_API_KEY "$1" login status >/dev/null 2>&1
}
now_iso() { date "+%Y-%m-%dT%H:%M:%S%z"; }
ASK_ANS=""; ASK_T0=""; ASK_T1=""
ask() {   # $1＝提示；答案放 ASK_ANS，開始／結束時間放 ASK_T0／ASK_T1（等待時間寫進執行 log，不算處理時間）
    flush_input   # 〔1.2.2〕先清掉處理中誤按的鍵，等待時間從清完開始算
    ASK_T0="$(now_iso)"; read -r -p "$1" ASK_ANS; ASK_T1="$(now_iso)"; ASK_ANS="${ASK_ANS%$'\r'}"
}
log_wait() {   # $1＝輸出資料夾 $2＝名稱 $3＝開始 $4＝結束
    [ -d "$1" ] && "$PY" "$SCR/runlog.py" wait "$1" --name "$2" --start "$3" --end "$4" >/dev/null 2>&1
    return 0
}

echo "要轉寫的檔案："
for f in "$@"; do echo "  $f"; done
echo
PRE_WAITS=()
# ------------------------------------------------------------------ 〔2.0.0〕內容類型（規格 §7.1、§7.2）
# 7 種內建類型：代號|名稱|筆記稱呼|人數題是否把「s＝略過」寫進主句（與 scripts/content_types.py 的 TYPES 一致；tests 檢查）
# macOS 內建 bash 3.2：不用關聯陣列，用 case 與一般陣列
TYPE_CODES="meeting course interview tutorial panel workshop requirements"
type_info() {
    case "$1" in
        meeting)      echo "會議（含業務／客戶會議）|會議摘要|0" ;;
        course)       echo "課程（含演講／專題分享）|課程筆記|1" ;;
        interview)    echo "訪談節目（Podcast、專訪）|訪談筆記|0" ;;
        tutorial)     echo "操作教學／示範|操作教學筆記|1" ;;
        panel)        echo "座談／論壇／研討會|座談筆記|0" ;;
        workshop)     echo "腦力激盪／工作坊／回顧|工作坊筆記|0" ;;
        requirements) echo "客戶／需求訪談|需求訪談筆記|0" ;;
    esac
}
STATE="$MMH/state.json"
I_KEY=(); I_TYPE=(); I_MENU=(); I_NAME=(); I_NOUN=(); I_SKIP=(); I_TPL=(); I_TSP=()
for c in $TYPE_CODES; do
    info="$(type_info "$c")"; lab="${info%%|*}"; rest="${info#*|}"
    I_KEY+=("$c"); I_TYPE+=("$c"); I_MENU+=("$lab"); I_NAME+=("${lab%%（*}"); I_NOUN+=("${rest%%|*}"); I_SKIP+=("${rest#*|}")
    I_TPL+=(""); I_TSP+=("")
done
# 自訂範本：templates.py list（JSON 一行）→ 每列「有效|代號|名稱|base|speakers|訊息」（空欄寫 -）
BAD_TPL=()
while IFS="$(printf '\t')" read -r v code name base sp msg; do
    [ -n "$v" ] || continue
    if [ "$v" = "1" ]; then
        info="$(type_info "$base")"; [ -n "$info" ] || continue
        lab="${info%%|*}"; rest="${info#*|}"; [ "$sp" = "-" ] && sp=""
        I_KEY+=("template:$code"); I_TYPE+=("$base"); I_MENU+=("$name［自訂：${lab%%（*}］"); I_NAME+=("$name")
        I_NOUN+=("〈$name〉${rest%%|*}"); I_SKIP+=("${rest#*|}"); I_TPL+=("$code"); I_TSP+=("$sp")
    else
        BAD_TPL+=("$msg")
    fi
done <<EOF_TPL
$("$PY" -B "$SCR/templates.py" list 2>/dev/null | tail -n 1 | "$PY" -c 'import json,sys
try:
    rows = json.loads(sys.stdin.read())
except Exception:
    rows = []
for r in rows:
    f = ["1" if r.get("valid") else "0"] + [str(r.get(k)) if r.get(k) not in (None, "") else "-" for k in ("code", "name", "base", "speakers", "message")]
    print("\t".join(x.replace("\t", " ") for x in f))' 2>/dev/null)
EOF_TPL

DEF_CODE="$(cfg_get content_type.default)"; DEF_CODE="${DEF_CODE:-meeting}"
if [ -z "$(type_info "$DEF_CODE")" ]; then
    echo "config.json 的 content_type.default「$DEF_CODE」不是內建類型，改用 meeting"; DEF_CODE=meeting
fi
DEF=0; i=0
while [ "$i" -lt "${#I_KEY[@]}" ]; do [ "${I_KEY[$i]}" = "$DEF_CODE" ] && DEF=$i; i=$((i + 1)); done
DEF_LAST=""; LAST_NOTE=""
if [ "$(cfg_get content_type.remember_last)" != "0" ]; then
    LAST="$("$PY" -c 'import json,sys
try:
    print(json.load(open(sys.argv[1], encoding="utf-8-sig")).get("content_type_last") or "")
except Exception:
    print("")' "$STATE" 2>/dev/null)"
    if [ -n "$LAST" ]; then
        hit=""; i=0
        while [ "$i" -lt "${#I_KEY[@]}" ]; do [ "${I_KEY[$i]}" = "$LAST" ] && hit=$i; i=$((i + 1)); done
        if [ -n "$hit" ]; then DEF=$hit; DEF_LAST=1
        else case "$LAST" in template:*) LAST_NOTE="上次選的自訂範本 ${LAST#template:} 已不存在或無法載入，預設改回〈${I_NAME[$DEF]}〉" ;; esac; fi
    fi
fi
if [ -n "$DEF_LAST" ]; then DEF_NAME="上次：${I_NAME[$DEF]}"; else DEF_NAME="${I_NAME[$DEF]}"; fi
N_ITEMS=${#I_KEY[@]}
echo; echo "內容類型（Enter＝$DEF_NAME）"
i=0
while [ "$i" -lt "$N_ITEMS" ]; do echo "  $((i + 1)) ${I_MENU[$i]}"; i=$((i + 1)); done
for m in "${BAD_TPL[@]}"; do echo "  ⚠ $m"; done
[ -n "$LAST_NOTE" ] && echo "  $LAST_NOTE"
SEL=""; T_A=""; tries=0
while [ -z "$SEL" ]; do
    ask "請選擇："; [ -z "$T_A" ] && T_A="$ASK_T0"; T_B="$ASK_T1"; tries=$((tries + 1))
    a="$(printf '%s' "$ASK_ANS" | tr -d ' ')"
    case "$a" in
        '') SEL=$((DEF + 1)) ;;
        *[!0-9]*) ;;
        *) if [ "$((10#$a))" -ge 1 ] && [ "$((10#$a))" -le "$N_ITEMS" ]; then SEL=$((10#$a)); fi ;;
    esac
    if [ -z "$SEL" ]; then
        if [ "$tries" -lt 2 ]; then echo "沒有這個選項，請輸入 1～$N_ITEMS，或直接按 Enter"
        else SEL=$((DEF + 1)); echo "沒有這個選項，使用〈${I_NAME[$DEF]}〉"; fi
    fi
done
S=$((SEL - 1))
PRE_WAITS+=("ask_type|$T_A|$T_B")
# 記住上次的類型：寫入失敗只略過（規格 §7.2）；時間取系統時間
"$PY" -c 'import json,sys
try:
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump({"content_type_last": sys.argv[2], "updated_at": sys.argv[3]}, f, ensure_ascii=False)
except Exception:
    pass' "$STATE" "${I_KEY[$S]}" "$(date '+%Y-%m-%dT%H:%M:%S%z' | sed 's/\([0-9][0-9]\)$/:\1/')" >/dev/null 2>&1
echo "內容類型：${I_MENU[$S]}"
SEL_TYPE="${I_TYPE[$S]}"; SEL_TPL="${I_TPL[$S]}"; TSP="${I_TSP[$S]}"

# 講者人數（規格 §4.4、§4.6、§7.1）：空白＝範本值或自動；1～20＝N；s＝略過說話者分離
case "$TSP" in
    skip) ENTER_TXT="Enter＝略過（範本設定）"; ENTER_SHORT="略過（範本設定）" ;;
    ''|*[!0-9]*) TSP=""; ENTER_TXT="Enter＝自動判斷"; ENTER_SHORT="自動判斷" ;;
    *) ENTER_TXT="Enter＝$TSP 位（範本設定）"; ENTER_SHORT="$TSP 位（範本設定）" ;;
esac
if [ "${I_SKIP[$S]}" = "1" ]; then
    SPK_Q="講者人數（$ENTER_TXT；填實際人數，不確定就留空；只有一位講者可輸入 s＝略過說話者分離：較快，但字幕時間較不準、提問的學員不會分出來）："
else
    SPK_Q="講者人數（$ENTER_TXT；填實際人數，不確定就留空；輸入 s＝略過說話者分離）："
fi
SPK="-"; T_A=""; tries=0
while [ "$SPK" = "-" ]; do
    ask "$SPK_Q"; [ -z "$T_A" ] && T_A="$ASK_T0"; T_B="$ASK_T1"; tries=$((tries + 1))
    a="$(printf '%s' "$ASK_ANS" | tr -d ' ')"
    case "$a" in
        '') SPK="$TSP" ;;
        s|S) SPK=skip ;;
        *[!0-9]*) ;;
        *) if [ "$((10#$a))" -ge 1 ] && [ "$((10#$a))" -le 20 ]; then SPK="$((10#$a))"; fi ;;
    esac
    if [ "$SPK" = "-" ]; then
        if [ "$tries" -lt 2 ]; then echo "請輸入 1～20 的人數、s（略過說話者分離），或直接按 Enter"
        else SPK="$TSP"; echo "沒有這個選項，使用$ENTER_SHORT"; fi
    fi
done
PRE_WAITS+=("ask_speakers|$T_A|$T_B")
ask "本次專有名詞，逗號分隔（可留空）："; HOT="$ASK_ANS"; PRE_WAITS+=("ask_hotwords|$ASK_T0|$ASK_T1")
USE_BREEZE=""
if "$PY" -c 'import json,sys; c=json.load(open(sys.argv[1], encoding="utf-8")); sys.exit(0 if c.get("profiles", {}).get("breeze") else 1)' "$MMH/config.json" 2>/dev/null; then
    ask "使用 Breeze-ASR-25？（中英夾雜很重的技術會議較準，但較慢）[y/N] "; PRE_WAITS+=("ask_breeze|$ASK_T0|$ASK_T1")
    case "$ASK_ANS" in [yY]*) USE_BREEZE=1 ;; esac
fi
# 〔2.0.0〕依類型：transcribe.py／auto_minutes.py 的參數、整理的稱呼與輸出檔（規格 §6.2、§7.3）
if [ -n "$SEL_TPL" ]; then TYPE_ARGS=(--template "$SEL_TPL"); else TYPE_ARGS=(--type "$SEL_TYPE"); fi
MIN_LABEL="${I_NOUN[$S]}"
if [ "$SEL_TYPE" = "meeting" ]; then MIN_FILE=meeting-minutes.md; THING="會議記錄"
else MIN_FILE=notes.md; info="$(type_info "$SEL_TYPE")"; rest="${info#*|}"; THING="${rest%%|*}"; fi

# ------------------------------------------------------------------ 偵測可用的 AI（只找執行檔與 codex login status，不呼叫模型、不耗額度）
HAS_CLAUDE=""; HAS_CODEX=""; CODEX_OK=""
find_cli claude "$(cfg_get correction.claude.cli_path)" "$HOME/.local/bin/claude" /opt/homebrew/bin/claude /usr/local/bin/claude >/dev/null && HAS_CLAUDE=1
CODEX_EXE="$(find_cli codex "$(cfg_get correction.openai.cli_path)" "$HOME/.local/bin/codex" \
    "$HOME/.codex/packages/standalone/current/bin/codex" /opt/homebrew/bin/codex /usr/local/bin/codex)" && HAS_CODEX=1
if [ -n "$HAS_CODEX" ] && codex_logged_in "$CODEX_EXE"; then CODEX_OK=1; fi

pname() { case "$1" in claude) echo Claude ;; *) echo OpenAI ;; esac; }
vendor() { case "$1" in claude) echo Anthropic ;; *) echo OpenAI ;; esac; }
# macOS 內建 bash 3.2：不用關聯陣列。每小時錄音的實測（README〈時間與費用〉）：分鐘下限 上限 API 等價美元下限 上限
# AI 校正：1.1.0 的合成素材實測；會議摘要：1.2.0 的合成素材實測（規格附錄 F）
rate_of() {   # $1＝correction|minutes $2＝<供應商>:<模型>；沒有實測的模型用同一家最寬的範圍
    case "$1:$2" in
        correction:claude:opus) echo "4.6 5.2 0.88 1.03" ;;
        correction:claude:sonnet) echo "2.8 4.6 0.4 0.55" ;;
        correction:openai:gpt-6.1-sol) echo "6.7 7.0 0.35 0.45" ;;
        correction:claude:*) echo "2.8 5.2 0.4 1.03" ;;
        correction:openai:*) echo "6.7 7.0 0.35 0.45" ;;
        minutes:claude:opus) echo "4.0 6.4 0.84 1.18" ;;
        minutes:claude:sonnet) echo "2.3 2.6 0.35 0.37" ;;
        minutes:openai:gpt-6.1-sol) echo "5.7 7.5 0.22 0.33" ;;
        minutes:claude:*) echo "2.3 6.4 0.35 1.18" ;;
        minutes:openai:*) echo "5.7 7.5 0.22 0.33" ;;
    esac
}
fmt_est() {   # $1～$4＝rate_of 的四個數字，$5＝小時（空＝量不到長度，列每小時的數字）
    "$PY" -c 'import sys
lo, hi, clo, chi = map(float, sys.argv[1:5])
h = sys.argv[5] if len(sys.argv) > 5 else ""
def r(x):
    return int(x + 0.5)
def span(a, b):
    if b < 1:
        return "不到 1 分鐘"
    a = max(1, r(a)); b = max(a, r(b))
    return f"約 {b} 分鐘" if a == b else f"約 {a}～{b} 分鐘"
def usd(a, b):
    a, b = f"{a:.2f}", f"{b:.2f}"
    return f"US${a}" if a == b else f"US${a}～{b}"
if h == "":
    print(f"每小時錄音{span(lo, hi)}、API 等價約 {usd(clo, chi)}")
else:
    h = float(h)
    print(f"{span(lo * h, hi * h)}、API 等價約 {usd(clo * h, chi * h)}")' "$@" 2>/dev/null
}
est_for() {   # $1＝correction|minutes $2＝<供應商>:<模型> $3＝小時
    local r; r="$(rate_of "$1" "$2")"
    if [ -z "$r" ]; then echo "沒有實測數字"; else fmt_est $r "$3"; fi
}
fmt_dur() {   # 秒 → 「1 小時 19 分」
    "$PY" -c 'import sys
d = float(sys.argv[1]); h, m = int(d // 3600), round((d % 3600) / 60)
if m >= 60:
    h, m = h + 1, 0
print(f"{h} 小時 {m} 分" if h else (f"{m} 分" if m >= 1 else "不到 1 分"))' "$1" 2>/dev/null
}

# 這一步（correction／minutes）的預設供應商與模型（與 auto_correct.select_backend 的規則相同）。
# 結果放在 AI_PROV AI_MODEL AI_CHAN AI_CAN_C AI_CAN_O AI_NOTE AI_WHY（AI_PROV 空＝不能用）
resolve_ai() {
    local sec="$1" prov chan m
    prov="$(cfg_get "$sec.provider")"; prov="${prov:-auto}"
    chan="$(cfg_get "$sec.channel")"; chan="${chan:-cli}"
    AI_CHAN="$chan"; AI_PROV=""; AI_MODEL=""; AI_NOTE=""; AI_WHY=""
    if [ "$chan" = "api" ]; then AI_CAN_C="${ANTHROPIC_API_KEY:+1}"; AI_CAN_O="${OPENAI_API_KEY:+1}"
    else AI_CAN_C="$HAS_CLAUDE"; AI_CAN_O="$CODEX_OK"; fi
    if [ "$prov" = "claude" ] && [ -n "$AI_CAN_C" ]; then AI_PROV=claude
    elif [ "$prov" = "openai" ] && [ -n "$AI_CAN_O" ]; then AI_PROV=openai
    else
        case "$prov" in claude|openai) AI_NOTE="設定的 $(pname "$prov") 這次不能用" ;; esac
        # 〔1.1.0〕OpenAI 優先：已登入的 codex（API 通道：OPENAI_API_KEY）→ OpenAI；否則 Claude
        if [ -n "$AI_CAN_O" ]; then AI_PROV=openai
        elif [ -n "$AI_CAN_C" ]; then
            AI_PROV=claude
            if [ "$chan" != "api" ] && [ -n "$HAS_CODEX" ]; then AI_NOTE="Codex 尚未登入，這次用 Claude（要用 OpenAI：在終端機執行 codex login）"; fi
        fi
    fi
    if [ -n "$AI_PROV" ]; then
        m="$(cfg_get "$sec.$AI_PROV.model")"
        if [ -z "$m" ]; then if [ "$AI_PROV" = "claude" ]; then m=opus; else m=gpt-6.1-sol; fi; fi   # 與 common.DEFAULTS 一致
        AI_MODEL="$m"
    elif [ "$chan" = "api" ]; then AI_WHY="沒有設定 OPENAI_API_KEY 或 ANTHROPIC_API_KEY"
    elif [ -n "$HAS_CODEX" ]; then AI_WHY="Codex 尚未登入（在終端機執行 codex login），也找不到 claude 指令"
    else AI_WHY="找不到 claude 或 codex 指令"; fi
}
resolve_ai correction; C_PROV="$AI_PROV"; C_MODEL="$AI_MODEL"; C_CHAN="$AI_CHAN"; C_CAN_C="$AI_CAN_C"; C_CAN_O="$AI_CAN_O"; C_NOTE="$AI_NOTE"; C_WHY="$AI_WHY"
resolve_ai minutes;    M_PROV="$AI_PROV"; M_MODEL="$AI_MODEL"; M_CHAN="$AI_CHAN"; M_CAN_C="$AI_CAN_C"; M_CAN_O="$AI_CAN_O"; M_NOTE="$AI_NOTE"; M_WHY="$AI_WHY"
CONFIRM_MIN="$(cfg_get correction.confirm_over_minutes)"; CONFIRM_MIN="${CONFIRM_MIN:-120}"

# 問一步並執行。$1＝correction|minutes $2＝輸出資料夾 $3＝秒數（量不到＝空）；其餘從 C_*／M_* 取
ai_step() {
    local sec="$1" out="$2" dur="$3" label q prov model chan canc cano note askdef yn yes key what est hours basis long
    if [ "$sec" = "correction" ]; then
        label="AI 校正"; q="要做 AI 校正嗎？"; prov="$C_PROV"; model="$C_MODEL"; chan="$C_CHAN"; canc="$C_CAN_C"; cano="$C_CAN_O"; note="$C_NOTE"
        basis="產出 transcript.corrected.md，原稿不改"
    else
        label="$MIN_LABEL"; q="要產生${MIN_LABEL}嗎？"; prov="$M_PROV"; model="$M_MODEL"; chan="$M_CHAN"; canc="$M_CAN_C"; cano="$M_CAN_O"; note="$M_NOTE"
        if [ -f "$out/transcript.corrected.md" ]; then basis="依校正版逐字稿整理"; else basis="依 transcript.md 整理"; fi
    fi
    askdef="$(cfg_get "$sec.ask_default")"
    hours=""; [ -n "$dur" ] && hours="$("$PY" -c 'import sys; print(float(sys.argv[1]) / 3600)' "$dur")"
    key="$prov:$model"; what="$(pname "$prov") $model"
    [ -n "$note" ] && echo "$note"
    est="$(est_for "$sec" "$key" "$hours")"
    echo
    long=""
    [ -n "$dur" ] && long="$("$PY" -c 'import sys; print("long" if float(sys.argv[1]) > float(sys.argv[2]) * 60 else "")' "$dur" "$CONFIRM_MIN" 2>/dev/null)"
    if [ -n "$long" ]; then
        # 1.1.0 在轉寫前做的長會議確認，1.2.0 改成在這裡把時間與費用寫清楚
        echo "⚠ 錄音長 $(fmt_dur "$dur")：$label：$what（$basis）：$est，會用掉較多額度；逐字稿文字會送到 $(vendor "$prov")"
    else
        echo "$label：$what（$basis）：$est；逐字稿文字會送到 $(vendor "$prov")"
    fi
    if [ "$askdef" = "0" ]; then yn="[y/N] "; yes=""; else yn="[Y/n] "; yes=1; fi
    ask "$q$yn"; log_wait "$out" "ask_$sec" "$ASK_T0" "$ASK_T1"
    case "$ASK_ANS" in [yY]*) yes=1 ;; [nN]*) yes="" ;; esac
    if [ -z "$yes" ]; then echo "略過$label"; STEP_STATUS=""; return 0; fi

    # 選模型：預設以外的推薦模型（順序：另一家的推薦模型 → Claude sonnet；只列能用的）
    local keys=() labels=() notes=() o k rest l n i idx
    # 〔1.2.1〕sonnet 的註記依步驟：校正是「準確率較低」（校正實測），摘要是「較快」（摘要實測，規格附錄 F.3）
    local snote="（準確率較低）"
    [ "$sec" = "minutes" ] && snote="（較快，約 sol 1/3 時間；可能漏 1～2 項待辦）"
    for o in "openai:gpt-6.1-sol|OpenAI gpt-6.1-sol|" "claude:opus|Claude opus|" "claude:sonnet|Claude sonnet|$snote"; do
        k="${o%%|*}"; rest="${o#*|}"; l="${rest%%|*}"; n="${rest#*|}"
        [ "$k" = "$key" ] && continue
        case "$k" in
            claude:*) [ -n "$canc" ] || continue ;;
            openai:*) [ -n "$cano" ] || continue ;;
        esac
        keys+=("$k"); labels+=("$l"); notes+=("$n")
    done
    if [ "${#keys[@]}" -gt 0 ]; then
        if [ -n "$hours" ]; then w="錄音 $(fmt_dur "$dur")"; else w="量不到錄音長度，以下是每小時錄音的數字"; fi
        echo "${label}用哪個模型？（$w；預估依合成素材實測，實際會議可能不同）"
        echo "  [Enter] 預設（$what）：$est"
        i=0
        while [ "$i" -lt "${#keys[@]}" ]; do
            echo "  [$((i + 2))] ${labels[$i]}${notes[$i]}：$(est_for "$sec" "${keys[$i]}" "$hours")"
            i=$((i + 1))
        done
        if [ "$chan" = "api" ]; then echo "  費用是 API 等價估算；API 通道依實際用量付費"
        else echo "  費用是 API 等價估算：用訂閱時不另計費，但會用掉額度"; fi
        ask "請選擇："; log_wait "$out" "choose_$sec" "$ASK_T0" "$ASK_T1"
        case "$ASK_ANS" in ''|*[!0-9]*) idx=-1 ;; *) idx=$((10#$ASK_ANS - 2)) ;; esac
        if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#keys[@]}" ]; then
            k="${keys[$idx]}"; prov="${k%%:*}"; model="${k#*:}"
        elif [ -n "$ASK_ANS" ]; then
            echo "沒有這個選項，使用預設"
        fi
    fi
    echo "$label：$(pname "$prov") $model；逐字稿文字會送到 $(vendor "$prov")"
    local args res last info st rs a b
    if [ "$sec" = "correction" ]; then args=("$SCR/auto_correct.py" "$out" --force --correct-provider "$prov" --correct-model "$model")
    else args=("$SCR/auto_minutes.py" "$out" --force "${TYPE_ARGS[@]}" --minutes-provider "$prov" --minutes-model "$model"); fi
    res="$("$PY" "${args[@]}")"          # 進度寫在 stderr（直接顯示）；stdout 最後一行是 JSON 摘要
    [ "$sec" = "minutes" ] && MINS_RAN=1   # 〔2.1.0〕這次有執行整理（結束畫面判斷要不要說明網頁版失敗）
    last="$(printf '%s\n' "$res" | tail -n 1)"
    info="$(printf '%s' "$last" | "$PY" -c 'import json,sys
try:
    j = json.loads(sys.stdin.read())
except Exception:
    j = {}
c = j.get(sys.argv[1]) or {}
ok = c.get("chunks_ok") if sys.argv[1] == "correction" else c.get("parts_ok")
n = c.get("chunks") if sys.argv[1] == "correction" else c.get("parts")
# 空欄位寫成 -（以 Tab 分隔時，連續的 Tab 會被 read 合併）
print("\t".join(str(x) for x in (c.get("status") or "-", c.get("reason") or "-", ok or 0, n or 0)))' "$sec" 2>/dev/null)"
    IFS="$(printf '\t')" read -r st rs a b <<< "$info"
    [ "$st" = "-" ] && st=""; [ "$rs" = "-" ] && rs=""
    STEP_STATUS="$st"
    # 〔2.0.0〕校正版字幕的條數（auto_correct.py 的 correction.subtitles；結束畫面用）
    if [ "$sec" = "correction" ]; then COR_NOTE="$(printf '%s' "$last" | "$PY" -c "$CUE_NOTE_PY" correction 2>/dev/null)"; fi
    if [ "$st" = "partial" ]; then
        if [ "$sec" = "correction" ]; then echo "AI 校正部分完成（$a/$b 段，原因：$rs），其餘段落保留原文"
        else echo "${MIN_LABEL}部分完成（$a/$b 段，原因：$rs），請看 $MIN_FILE 開頭的說明"; fi
    elif [ "$st" != "ok" ]; then
        if [ "$rs" = "auth_failed" ]; then
            if [ "$prov" = "openai" ]; then echo "Codex 尚未登入，${label}未完成：在終端機執行 codex login 後可再試"
            else echo "Claude Code 尚未登入，${label}未完成：在終端機執行 claude 並輸入 /login 後可再試"; fi
        else
            if [ "$sec" = "correction" ]; then j=auto_correct.json; else j=auto_minutes.json; fi
            echo "${label}未完成（${st:-?}：${rs:-?}），詳見輸出資料夾的 $j"
        fi
    fi
    return 0
}

# 字幕的條數說明（transcribe.py 的 subtitles.cues、auto_correct.py 的 correction.subtitles；規格 §7.4）
CUE_NOTE_PY='import json,sys
try:
    j = json.loads(sys.stdin.read())
except Exception:
    j = {}
s = ((j.get("subtitles") or {}).get("cues") if sys.argv[1] == "cues" else (j.get("correction") or {}).get("subtitles")) or {}
st = s.get("status")
if st in ("ok", "map_failed"):
    t = "%s 條" % s.get("cues")
    if sys.argv[1] == "correction":
        t += "，對應失敗，全部用原文" if st == "map_failed" else "，對應失敗 %d 段" % int(s.get("map_failed_paragraphs") or 0)
    print("（%s）" % t)
elif st and st != "skipped":
    print("（產生失敗：%s）" % s.get("reason"))'
FIRST=1
for f in "$@"; do
    RUN_ID="$("$PY" -c 'import uuid; print(uuid.uuid4().hex[:12])')"
    export MMP_RUN_ID="$RUN_ID"
    args=("$SCR/transcribe.py" "$f" --no-correct "${TYPE_ARGS[@]}")   # 1.2.0：校正改在轉寫完成後詢問
    if [ "$SPK" = "skip" ]; then args+=(--no-diarize)
    elif [[ "$SPK" =~ ^[0-9]+$ ]]; then args+=(--speakers "$SPK"); fi
    if [ -n "$HOT" ]; then args+=(--hotwords "$HOT"); fi
    if [ -n "$USE_BREEZE" ]; then args+=(--whisper breeze); fi
    echo; echo "=== $f ==="
    # 進度寫在 stderr（直接顯示）；stdout 最後一行是 JSON 摘要
    ok=1
    res="$("$PY" "${args[@]}")" || ok=""
    printf '%s\n' "$res" | sed '$d'
    last="$(printf '%s\n' "$res" | tail -n 1)"
    info="$(printf '%s' "$last" | "$PY" -c 'import json,sys
try:
    j = json.loads(sys.stdin.read())
except Exception:
    j = {}
d = j.get("duration")
print("\t".join(str(x) for x in (j.get("out_dir") or "-", "-" if d is None else d)))' 2>/dev/null)"
    IFS="$(printf '\t')" read -r out dur <<< "$info"
    CUE_NOTE="$(printf '%s' "$last" | "$PY" -c "$CUE_NOTE_PY" cues 2>/dev/null)"; COR_NOTE=""; MINS_RAN=""
    { [ -n "$out" ] && [ "$out" != "-" ]; } || out="${f%.*}_minutes"
    [ "$dur" = "-" ] && dur=""
    if [ -n "$FIRST" ]; then
        for w in "${PRE_WAITS[@]}"; do
            n="${w%%|*}"; rest="${w#*|}"; log_wait "$out" "$n" "${rest%%|*}" "${rest#*|}"
        done
        FIRST=""
    fi
    if [ -z "$ok" ]; then
        echo "轉寫失敗"
        "$PY" "$SCR/runlog.py" finish "$out" --run-id "$RUN_ID" >/dev/null 2>&1
        continue
    fi
    echo; echo "逐字稿完成：$out"
    if [ -z "$dur" ]; then
        dur="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$f" 2>/dev/null | tail -n 1)"
        case "$dur" in ''|*[!0-9.]*) dur="" ;; esac
    fi
    if [ -z "$C_PROV" ] && [ -z "$M_PROV" ]; then
        echo "$C_WHY：略過 AI 校正與${MIN_LABEL}。"
        echo "  要用 AI 校正與${MIN_LABEL}：安裝 Claude Code（claude 指令，執行 claude 後輸入 /login）或 Codex（codex 指令，執行 codex login），"
        echo "  之後可以對輸出資料夾執行 auto_correct.py、auto_minutes.py 補做；或在 Claude 對話中說「用 meeting-minutes-pro 整理這份${THING}」並附上 transcript.md。"
    else
        if [ -n "$C_PROV" ]; then ai_step correction "$out" "$dur"; else echo "$C_WHY：略過 AI 校正"; fi
        if [ -n "$M_PROV" ]; then ai_step minutes "$out" "$dur"; else echo "$M_WHY：略過${MIN_LABEL}"; fi
    fi
    "$PY" "$SCR/runlog.py" finish "$out" --run-id "$RUN_ID" >/dev/null 2>&1

    # ------------------------------------------------------------------ 結束畫面：產出的檔案與 log 位置
    echo; echo "完成：$out"
    # 〔2.1.0〕網頁版：auto_minutes.json 的 html（status ok 且檔案在才列；html.enabled 關或沒有產生時不列）
    hinfo="$("$PY" -c 'import json,sys
try:
    h = json.load(open(sys.argv[1], encoding="utf-8")).get("html") or {}
except Exception:
    h = {}
print("\t".join(str(h.get(k) or "-") for k in ("status", "reason", "output", "media")))' "$out/auto_minutes.json" 2>/dev/null)"
    IFS="$(printf '\t')" read -r h_st h_rs h_out h_media <<< "$hinfo"
    HTML_FILE=""; { [ "$h_st" = "ok" ] && [ -n "$h_out" ] && [ "$h_out" != "-" ] && [ -f "$out/$h_out" ]; } && HTML_FILE="$h_out"
    case "$h_media" in found|explicit) TC_NOTE="時間碼可點播放" ;; *) TC_NOTE="時間碼為文字" ;; esac
    for x in "meeting-minutes.md|會議記錄（AI 自動整理，未經人工確認）" "meeting-minutes.html|會議記錄網頁版（用瀏覽器開；$TC_NOTE）" \
             "notes.md|${THING}（AI 自動整理，未經人工確認）" "notes.html|${THING}網頁版（用瀏覽器開；$TC_NOTE）" \
             "notes.json|筆記的結構化資料（改過後執行 auto_minutes.py --render-only 重新產生 notes.md）" \
             "transcript.corrected.md|校正版逐字稿（AI 校正，標出每一處修改）" \
             "corrections.suggested.tsv|對照表建議（尚未生效）" "transcript.md|逐字稿（原稿）" "transcript.srt|字幕檔（一段一條）" \
             "transcript.cues.srt|字幕（依字幕規則切條，不經 AI）$CUE_NOTE" "transcript.corrected.srt|校正版字幕$COR_NOTE" \
             "frames|影片截圖"; do
        n="${x%%|*}"
        case "$n" in *.html) [ "$n" = "$HTML_FILE" ] || continue ;; esac
        [ -e "$out/$n" ] && printf '  %-26s %s\n' "$n" "${x#*|}"
    done
    echo "  執行 log：$out/run_log.jsonl"
    echo "  歷次執行摘要：$MMH/logs/runs.jsonl（彙整：\"$PY\" \"$SCR/runlog.py\" summary）"
    # 〔2.0.0〕說話者分離退回 CPU 的原因、零星講者（transcript.json 的 meta；規格 §4.5、§4.7、§7.4）
    extra="$("$PY" -c 'import json,sys
sys.path.insert(0, sys.argv[2])
try:
    m = json.load(open(sys.argv[1], encoding="utf-8")).get("meta") or {}
except Exception:
    m = {}
fb = (m.get("diarization") or {}).get("fallback")
if fb:
    try:
        import diarize
        why = diarize.reason_text(fb)
    except Exception:
        why = fb
    print("說話者分離改用 CPU（sherpa）：%s" % why)
minor = [str(s.get("speaker")) for s in (m.get("speaker_stats") or []) if s.get("minor")]
if minor:
    print("講者 %s 發言很少，可能是分離誤判（見 transcript.md 表頭）；確定人數時可重跑並填人數" % "、".join(minor))' "$out/transcript.json" "$SCR" 2>/dev/null)"
    [ -n "$extra" ] && printf '%s\n' "$extra"
    if [ -f "$out/transcript.corrected.md" ]; then src=transcript.corrected.md; else src=transcript.md; fi
    # 〔2.1.0〕這次有整理、但網頁版沒產生（failed）：說明原因與補做的指令
    if [ -n "$MINS_RAN" ] && [ "$h_st" = "failed" ]; then
        case "$h_rs" in
            template_missing) hw="找不到網頁版樣板 html_template.html" ;;
            write_failed) hw="寫入檔案失敗" ;;
            internal_error) hw="程式錯誤" ;;
            *) hw="$h_rs" ;;
        esac
        echo "網頁版未產生（$hw）；可執行 render_html.py 補做：\"$PY\" \"$SCR/render_html.py\" \"$out\""
    fi
    if [ -f "$out/meeting-minutes.md" ]; then
        open_f="meeting-minutes.md "; [ "$HTML_FILE" = "meeting-minutes.html" ] && open_f="meeting-minutes.html（用瀏覽器）"
        echo "下一步：打開 ${open_f}確認決議與待辦；要補講者姓名或修改，在 Claude 中說「用 meeting-minutes-pro 檢查這份會議記錄」，附上 meeting-minutes.md 與 $src。"
    elif [ "$SEL_TYPE" != "meeting" ] && [ -f "$out/notes.md" ]; then
        open_f="notes.md "; [ "$HTML_FILE" = "notes.html" ] && open_f="notes.html（用瀏覽器）"
        echo "下一步：打開 ${open_f}確認內容；要補講者姓名或修改，在 Claude 中說「用 meeting-minutes-pro 檢查這份${THING}」，附上 notes.md 與 $src。"
    elif [ "$src" = "transcript.corrected.md" ]; then
        echo "下一步：在 Claude 中說「用 meeting-minutes-pro 整理這份${THING}」，附上 transcript.corrected.md（已自動校正，只剩待確認與講者對應；影片可一併附上 frames 內的截圖）。"
    else
        echo "下一步：在 Claude 中說「用 meeting-minutes-pro 整理這份${THING}，並產生校正版逐字稿」，附上 transcript.md（影片可一併附上 frames 內的截圖）。"
    fi
    [ -z "${MMP_TEST_NO_OPEN:-}" ] && open "$out"   # MMP_TEST_NO_OPEN：僅供開發測試，不開資料夾
done
unset MMP_RUN_ID
echo
flush_input   # 〔1.2.2〕處理中誤按的 Enter 不會讓視窗在結束時直接關閉
read -r -p "按 Enter 關閉" _
