"""〔2.2.0〕全文用字統一（本機處理，不呼叫模型）：同一個名詞在全文用同一種寫法。

- 對象：拉丁字母名詞的寫法變體，只差大小寫、或中間有沒有空格／「.」／「-」（NotebookLM／notebookLM／notebook lm／
  Notebook-LM／notebook.lm）。中文詞的同義異寫不處理。
- 標準寫法的來源與優先序：
  ① 使用者提供的：glossary.txt ＞ corrections.tsv 的正確寫法 ＞ 說明檔與會議文件的名詞 ＞ reference.json 的名詞
  ② 本次校正名詞階段的用字表（correct.terms 的 high）
  ③ 全文出現最多、而且寫法有特徵（字中有大寫，或是 2 個字母以上的全大寫縮寫）的寫法；門檻見 build()
- 不改：一般英文單字（只差大小寫的 apple／Apple、go／Go、app 等，COMMON_WORDS）、網址、檔名、路徑、信箱、
  程式碼（`…`）、Markdown 連結網址；不同名詞不會合併（Notebook 與 NotebookLM 是兩個名詞）。
- 套用：transcript.corrected.md 本文（統一處加 {原文→統一} 標記）、meeting-minutes.md／notes.md（直接改寫；> 開頭的
  說明行不改）、transcript.corrected.srt（校正時隨校正版產生；單獨執行時直接改字幕文字，時間碼不動）。
  原始 transcript.md、transcript.srt、transcript.cues.srt 不改。
- 設定 consistency.enabled（預設 true）；run_log 只記組數與處數，不記名詞。

單獨執行（不呼叫模型；已經有的輸出資料夾）：
  python consistency.py <檔名>_minutes [--dry-run]
  改過的檔先改名備份（<檔名>.<時間>.bak<副檔名>）；有網頁版的一併重新產生。exit code：0 完成（含沒有要改的）、2 找不到資料夾。
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DEFAULTS, setting  # noqa: E402

TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
RUN_RE = re.compile(r"[A-Za-z0-9]+(?:[ .\-][A-Za-z0-9]+)*")
# 只有一邊是字母的分隔才拿掉：GPT-4＝GPT4、notebook lm＝notebooklm；數字之間的「.」保留（1.5 ≠ 15）
SEP_RE = re.compile(r"(?<=[A-Za-z])[ .\-](?=[A-Za-z0-9])|(?<=[0-9])[ .\-](?=[A-Za-z])")
MAX_TOKENS = 4
MIN_CANON = 2            # ③ 標準寫法至少出現 2 次
MIN_TOTAL = 3            # ③ 整組（含變體）至少出現 3 次
SHOW_GROUPS = 20         # 校正版〈校正摘要〉那一行最多列幾組
# 校正版的標記（與 auto_correct.MARK_RE 相同；tests 檢查兩邊一致。這裡不 import auto_correct，避免互相載入）
MARK_RE = re.compile(r"\{([^{}→\n]*)→([^{}\n]*)\}|\[\?([^\[\]｜\n]*?)(?:｜([^\[\]\n]*))?\]")
HEAD_RE = re.compile(r"^\*\*\[(\d{1,2}:\d{2}:\d{2})\] [^*\n]+\*\*：")
EXT = ("md|markdown|txt|pdf|docx?|pptx?|xlsx?|csv|tsv|json|jsonl|ya?ml|toml|ini|cfg|log|srt|vtt|html?|css|js|mjs|ts|tsx|jsx|"
       "py|ps1|sh|cmd|bat|exe|dll|zip|7z|rar|tar|gz|png|jpe?g|gif|webp|svg|mp3|mp4|m4a|wav|flac|mkv|mov|webm|avi|epub|"
       "com|org|net|io|ai|dev|app|tw|edu|gov|co|me|info|cn|jp|uk")
PROTECT_RE = re.compile("|".join([
    r"`[^`\n]*`",                                            # 程式碼
    r"(?:https?|ftp)://[^\s<>()（）「」，。、；]+",            # 網址
    r"\bwww\.[^\s<>()（）「」，。、；]+",
    r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+",                      # 信箱
    r"\]\([^)\n]*\)",                                        # Markdown 連結網址
    r"</?[A-Za-z][^>\n]*>",                                  # HTML 標籤
    r"(?:[A-Za-z]:)?[\w.\-]*[/\\][\w.\-/\\]*",               # 路徑（含 / 或 \）
    r"\b[\w\-]+(?:\.[\w\-]+)*\.(?:" + EXT + r")\b",          # 檔名、網域
]), re.IGNORECASE)
PROTECTED = "\x00"       # 保護區換成這個字元（長度不變），前後緊鄰的英文詞不改
MARK_CHAR = "\x01"       # 標記換成這個字元：算邊界，但緊鄰的詞照常處理
BAD_NEIGHBOR = set("_@#$%&~/\\" + PROTECTED)
BAD_LEFT = BAD_NEIGHBOR | set(".-")   # 「.pdf」「--pdf」：副檔名、旗標
# 只差大小寫時不改的一般英文單字（全小寫比對；只看單一個字的寫法）
COMMON_WORDS = frozenset("""
a an the and or but if of to in on at by for from with as is it its be am are was were been being do does did done
go goes going gone get gets got can could will would shall should may might must have has had not no yes ok okay so
up down out off over us we you he she they them me my our your his her their this that these those there here what
which who whom why how when where all any some one two three new old now then than also just very more most much many
each every both few other such only own same too again about after before into through between under above below
app apps apple apples word words line lines code codes text texts page pages image images file files data link links
note notes book books home work mail chat plus pro max mini team teams office edge drive docs doc sheet sheets slide
slides form forms studio cloud play store live meet keep photo photos map maps music news search open close start stop
run test set help info tool tools card cards box key keys view tab tabs menu list item items user users name names type
time date day week year part step steps use used make like good great best well really thank thanks hello hi bye sorry
please wow oh ah uh um hmm yeah yep nope let lets see look say said know think want need way thing things lot bit
single double multi full free smart quick easy simple power point share web site space base face air drop sign log back
front end top side light dark mode cool hot fire water sun star net world life story game class room video audio sound
voice screen shot print paper board pad pen show talk call phone watch wall door sales force people care health pay money
bank shop cart hub lab labs flow flows mind day night first last next main real big small high low long short
""".split())


def enabled(cfg: dict | None, warn=None) -> bool:
    """consistency.enabled（預設 true）。不認得的值當預設值並印一行提示（同 common.html_setting() 的做法）。"""
    default = DEFAULTS["consistency"]["enabled"]
    try:
        v = setting(cfg or {}, "consistency.enabled")
    except KeyError:
        v = default
    if isinstance(v, bool):
        return v
    msg = f"[!] consistency.enabled 的值 {v} 不認得，改用 {json.dumps(default)}"
    if warn is None:
        print(msg, file=sys.stderr, flush=True)
    else:
        warn(msg)
    return default


# ---------------------------------------------------------------- 寫法的比較
def key_of(form: str) -> str:
    """比對用的鍵：去掉字母旁的分隔、轉小寫。NotebookLM、notebook lm、Notebook-LM、notebook.lm → notebooklm。"""
    return SEP_RE.sub("", form).lower()


def _sepless(form: str) -> str:
    return SEP_RE.sub("", form)


def _marked_token(t: str) -> bool:
    letters = [c for c in t if c.isalpha()]
    return (len(letters) >= 2 and all(c.isupper() for c in letters)) or any(c.isupper() for c in t[1:])


def is_marked(form: str) -> bool:
    """寫法有特徵：某個字的字中有大寫（NotebookLM、iPhone、16K），或是 2 個字母以上的全大寫縮寫（AI、PDF）。"""
    return any(_marked_token(t) for t in TOKEN_RE.findall(form))


def changeable(form: str, canon: str) -> bool:
    """form 要不要改成 canon。一般英文單字不改；canon 沒有特徵（Google、Redis Sentinel）時只統一分隔（Redis-Sentinel），
    不改大小寫（google 不改）。"""
    if form == canon or key_of(form) != key_of(canon):
        return False
    toks = TOKEN_RE.findall(form)
    if len(toks) == 1 and toks[0].lower() in COMMON_WORDS:
        return False
    if len(toks) > 1 and form == form.lower() and all(t in COMMON_WORDS for t in toks):
        return False                       # 全小寫的一般片語（single file）不併成產品名（SingleFile）
    if is_marked(canon):
        return True
    return _sepless(form) == _sepless(canon)


def _seps(form: str) -> str:
    return "".join(c for c in form if c in " .-")


# ---------------------------------------------------------------- 文字的切分
def protect(s: str) -> str:
    """網址、檔名、路徑、信箱、程式碼、連結網址、HTML 標籤 → PROTECTED（長度不變）。"""
    return PROTECT_RE.sub(lambda m: PROTECTED * len(m.group(0)), s)


def visible(text: str) -> str:
    """校正版標記 → 讀者看到的文字：{a→b}→b、[?a｜b]→a。"""
    def sub(m):
        if m.group(3) is not None:
            return m.group(3)
        return m.group(2) or ""
    return MARK_RE.sub(sub, text)


def _runs(masked: str):
    """可處理的英文詞串：前後不緊鄰 _、@、#、/、\\、保護區，前面也不緊鄰「.」「-」。yield [(start, end), …]（每個字的位置）。"""
    for m in RUN_RE.finditer(masked):
        a, b = m.start(), m.end()
        if (a > 0 and masked[a - 1] in BAD_LEFT) or (b < len(masked) and masked[b] in BAD_NEIGHBOR):
            continue
        yield [(a + t.start(), a + t.end()) for t in TOKEN_RE.finditer(m.group(0))]


def _cut_ok(masked: str, toks: list, i: int, j: int) -> bool:
    """第 i～j 個字能不能單獨拿出來比：用「.」「-」連著的一串（notebooklm.google、GPT-4o）只能整串比，不從中間切。"""
    return (i == 0 or masked[toks[i][0] - 1] == " ") and (j == len(toks) - 1 or masked[toks[j][1]] == " ")


def _ngrams(masked: str, s: str):
    """(start, end, form, 字數)：每串裡 1～MAX_TOKENS 個字的組合（不從「.」「-」中間切）。"""
    for toks in _runs(masked):
        for n in range(1, MAX_TOKENS + 1):
            for i in range(len(toks) - n + 1):
                if not _cut_ok(masked, toks, i, i + n - 1):
                    continue
                a, b = toks[i][0], toks[i + n - 1][1]
                yield a, b, s[a:b], n


def _usable_key(k: str) -> bool:
    return len(k) >= 2 and any(c.isalpha() for c in k)


def phrases(term: str) -> list:
    """使用者或用字表的一個詞 → 裡面的英文詞串（「Redis Sentinel 叢集」→ ["Redis Sentinel"]）；超過 4 個字的串不用。"""
    out = []
    for toks in _runs(protect(term or "")):
        if len(toks) <= MAX_TOKENS:
            out.append(term[toks[0][0]:toks[-1][1]])
    return out


# ---------------------------------------------------------------- 建表
class Unifier:
    """groups：{鍵: {"canon": 標準寫法, "tier": "user"|"terms"|"frequency"}}。apply 系列回傳 (新文字, hits)，
    hits＝[(原寫法, 標準寫法), …]（每處一筆）。"""

    def __init__(self, groups: dict):
        self.groups = groups

    def __bool__(self):
        return bool(self.groups)

    # ---- 套用
    def _replace(self, s: str, masked: str, mark: bool) -> tuple:
        hits, out, last = [], [], 0
        for toks in _runs(masked):
            i = 0
            while i < len(toks):
                step = 1
                for n in range(min(MAX_TOKENS, len(toks) - i), 0, -1):
                    if not _cut_ok(masked, toks, i, i + n - 1):
                        continue
                    a, b = toks[i][0], toks[i + n - 1][1]
                    form = s[a:b]
                    g = self.groups.get(key_of(form))
                    if g is None:
                        continue
                    step = n                       # 鍵對上了：這幾個字算處理過（不再拆開比對較短的組合）
                    if changeable(form, g["canon"]):
                        out.append(s[last:a])
                        out.append(f"{{{form}→{g['canon']}}}" if mark else g["canon"])
                        last = b
                        hits.append((form, g["canon"]))
                    break
                i += step
        out.append(s[last:])
        return "".join(out), hits

    def plain(self, s: str) -> tuple:
        """一般文字（會議記錄、筆記、字幕的一行）：直接改寫。"""
        if not self.groups or not s:
            return s, []
        return self._replace(s, protect(s), False)

    def marked(self, s: str) -> tuple:
        """校正版一段的本文：標記外的變體改成 {原文→統一}；{a→b} 的 b 統一（統一後等於 a → 換回 a）；[?…] 不動。"""
        if not self.groups or not s:
            return s, []
        marks = list(MARK_RE.finditer(s))
        masked = protect(s)
        for m in marks:
            masked = masked[:m.start()] + MARK_CHAR * (m.end() - m.start()) + masked[m.end():]
        text, hits = self._replace(s, masked, True)
        if not any(m.group(3) is None and m.group(2) for m in marks):
            return text, hits

        def fix(m):
            if m.group(3) is not None or not m.group(2):
                return m.group(0)
            b, h = self.plain(m.group(2))
            if not h:
                return m.group(0)
            hits.extend(h)
            return m.group(1) if b == m.group(1) else f"{{{m.group(1)}→{b}}}"
        return MARK_RE.sub(fix, text), hits

    def markdown(self, text: str) -> tuple:
        """meeting-minutes.md／notes.md：> 開頭的說明行、``` 區塊不改。"""
        if not self.groups:
            return text, []
        out, hits, fence = [], [], False
        for line in text.split("\n"):
            if line.lstrip().startswith("```"):
                fence = not fence
                out.append(line)
                continue
            if fence or line.lstrip().startswith(">"):
                out.append(line)
                continue
            new, h = self.plain(line)
            out.append(new)
            hits += h
        return "\n".join(out), hits

    def srt(self, text: str) -> tuple:
        """字幕：序號行與時間碼行不動，只改字幕文字。"""
        if not self.groups:
            return text, []
        out, hits = [], []
        for line in text.split("\n"):
            if not line.strip() or line.strip().isdigit() or "-->" in line:
                out.append(line)
                continue
            new, h = self.plain(line)
            out.append(new)
            hits += h
        return "\n".join(out), hits

    def corrected_md(self, text: str) -> tuple:
        """整份 transcript.corrected.md（單獨執行時用）：只改第一個 --- 之後的本文；表頭、校正摘要、講者對應、待確認不改。"""
        if not self.groups:
            return text, []
        lines = text.split("\n")
        if "---" not in lines:
            return text, []
        start = lines.index("---") + 1
        hits = []
        for i in range(start, len(lines)):
            line = lines[i]
            if not line.strip() or line.startswith(">") or line.startswith("#"):
                continue
            m = HEAD_RE.match(line)
            head = line[:m.end()] if m else ""
            new, h = self.marked(line[len(head):])
            lines[i] = head + new
            hits += h
        return "\n".join(lines), hits


def build(texts, user_terms=(), stage_terms=()) -> Unifier:
    """texts：用來計數的文字（校正版本文請先 visible()；不要放表頭與說明行）。user_terms／stage_terms：依優先序排好的詞。

    ① user_terms ＞ ② stage_terms：同一個鍵先出現的為準；寫法沒有特徵時只統一分隔（見 changeable()）。
    ③ 其他鍵（從長的鍵開始）：同一個鍵至少兩種寫法；有特徵的寫法裡出現最多的當標準（同票：分隔少的、再來先出現的），
       標準寫法 ≥ MIN_CANON 次、整組 ≥ MIN_TOTAL 次，而且至少有一處要改。幾個字的組合若前後有字完全相同、
       不同處本身有特徵（「NotebookLM is」與「notebooklm is」），交給較短的組合處理。
    已經採用的組，所在位置不再算進較短的鍵（notebook lm 裡的 lm 不再算 lm 這組）。"""
    groups = {}
    for tier, terms in (("user", user_terms), ("terms", stage_terms)):
        for term in terms or ():
            for ph in phrases(term):
                k = key_of(ph)
                toks = TOKEN_RE.findall(ph)
                if k in groups or not _usable_key(k) or (len(toks) == 1 and toks[0].lower() in COMMON_WORDS):
                    continue
                groups[k] = {"canon": ph, "tier": tier}
    occ, first = {}, {}
    order = 0
    for li, s in enumerate(t for t in texts if t):
        for a, b, form, n in _ngrams(protect(s), s):
            k = key_of(form)
            if not _usable_key(k):
                continue
            occ.setdefault(k, []).append((li, a, b, form, n))
            first.setdefault(form, order)
            order += 1
    taken = {}

    def free(o):
        return not any(a < o[2] and o[1] < b for a, b in taken.get(o[0], ()))

    def take(k):
        for o in occ.get(k, ()):
            if free(o):
                taken.setdefault(o[0], []).append((o[1], o[2]))

    for k in sorted(groups, key=len, reverse=True):
        take(k)
    for k in sorted(occ, key=lambda x: (-len(x), x)):
        if k in groups:
            continue
        live = [o for o in occ[k] if free(o)]
        forms = Counter(o[3] for o in live)
        if len(forms) < 2:
            continue
        marked = [f for f in forms if is_marked(f)]
        if not marked:
            continue
        canon = max(marked, key=lambda f: (forms[f], -len(_seps(f)), -first[f]))
        if forms[canon] < MIN_CANON or sum(forms.values()) < MIN_TOTAL:
            continue
        if not any(changeable(f, canon) for f in forms):
            continue
        if _reducible(list(forms), canon):
            continue
        groups[k] = {"canon": canon, "tier": "frequency"}
        take(k)
    return Unifier(groups)


def _reducible(forms: list, canon: str) -> bool:
    toks = {f: TOKEN_RE.findall(f) for f in forms}
    n = {len(t) for t in toks.values()}
    if len(n) != 1 or n == {1} or len({_seps(f) for f in forms}) != 1:
        return False
    rows = list(toks.values())
    m = len(rows[0])
    lo = 0
    while lo < m and len({r[lo] for r in rows}) == 1:
        lo += 1
    hi = m
    while hi > lo and len({r[hi - 1] for r in rows}) == 1:
        hi -= 1
    if lo == 0 and hi == m:
        return False
    core = toks[canon][lo:hi]
    return is_marked(" ".join(core)) or (len(core) == 1 and core[0].lower() in COMMON_WORDS)


# ---------------------------------------------------------------- 來源與結果
def user_terms(col: dict | None = None, ref: dict | None = None, out_dir=None, rm: dict | None = None) -> list:
    """①：glossary.txt ＞ corrections.tsv 的正確寫法 ＞ 說明檔與會議文件的名詞 ＞ reference.json 的名詞（依序；不丟例外）。
    col＝refs.collect() 的結果；rm＝摘要的參考資料（refs.for_minutes()）；ref＝reference.json（沒給且有 out_dir 時讀檔）。"""
    out = []
    try:
        from common import default_glossary
        p = default_glossary()
        if p.exists():
            out += [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
    except Exception:  # noqa: BLE001
        pass
    try:
        from corrections import load
        out += [r for _, r, _ in load()]
    except Exception:  # noqa: BLE001
        pass
    try:
        import refs
        src = col or rm or {}
        if src.get("context_text"):
            out += refs.latin_terms(src["context_text"])
        out += list(src.get("doc_terms") or [])
        if ref is None and rm is None and out_dir is not None:
            ref = refs.read_reference(out_dir)
        ref = ref if ref is not None else rm
        out += list((ref or {}).get("terms") or [])
    except Exception:  # noqa: BLE001
        pass
    return out


def summary(u: Unifier | None, hits: list, status: str = "ok") -> dict:
    """run_log／auto_*.json 用：只有數量。"""
    groups = {c for _, c in hits}
    tiers = Counter((u.groups[key_of(c)]["tier"] if u and key_of(c) in u.groups else "user") for c in groups)
    return {"status": status, "groups": len(groups), "edits": len(hits),
            "user": tiers.get("user", 0), "terms": tiers.get("terms", 0), "frequency": tiers.get("frequency", 0)}


def detail(hits: list, limit: int = SHOW_GROUPS) -> list:
    """[(標準寫法, [(原寫法, 次數), …]), …]，處數多的組在前。"""
    by = {}
    for f, c in hits:
        by.setdefault(c, Counter())[f] += 1
    rows = sorted(by.items(), key=lambda x: (-sum(x[1].values()), x[0].lower()))
    return [(c, cnt.most_common()) for c, cnt in rows[:limit]]


def summary_line(hits: list) -> str | None:
    """校正版〈校正摘要〉表格下的一行（沒有統一任何地方時 None）。"""
    if not hits:
        return None
    rows = detail(hits)
    body = "；".join(f"{c}（" + "、".join(f"{f} ×{n}" for f, n in fs) + "）" for c, fs in rows)
    more = len({c for _, c in hits}) - len(rows)
    return (f"全文用字統一（本機處理，未呼叫模型）：{len({c for _, c in hits})} 組、{len(hits)} 處，"
            "統一處以 {原文→統一} 標出：" + body + (f"；另 {more} 組" if more > 0 else ""))


def console_line(hits: list) -> str:
    """完成訊息一行。"""
    if not hits:
        return "用字統一：沒有要統一的寫法"
    names = [c for c, _ in detail(hits, 3)]
    n = len({c for _, c in hits})
    return f"用字統一：{n} 組、{len(hits)} 處（{'、'.join(names)}{'…' if n > 3 else ''}；本機處理）"


# ---------------------------------------------------------------- 流程接點（不丟例外）
def correct_stage(cfg: dict, para_out: list, stage_pairs=(), col: dict | None = None, ref: dict | None = None,
                  run_log=None, log=None) -> tuple:
    """auto_correct：para_out＝[[(時間, 講者, 本文), …], …]（已含模型的標記）。回傳 (新 para_out, info)；
    info＝{"summary", "unifier", "hits"}；關閉或失敗時 para_out 原樣回傳。"""
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    if not enabled(cfg, warn=log):
        info = {"summary": {"status": "off"}, "unifier": None, "hits": []}
        _cp(run_log, "correct.consistency", info["summary"])
        return para_out, info
    try:
        texts = [visible(txt) for outs in para_out for _, _, txt in outs]
        u = build(texts, user_terms(col, ref), [r for _, r in stage_pairs or ()])
        hits, new = [], []
        for outs in para_out:
            row = []
            for t, s, txt in outs:
                txt2, h = u.marked(txt)
                hits += h
                row.append((t, s, txt2))
            new.append(row)
        info = {"summary": summary(u, hits), "unifier": u, "hits": hits}
        _cp(run_log, "correct.consistency", info["summary"])
        return new, info
    except Exception as ex:  # noqa: BLE001  統一失敗不影響校正
        log(f"  [!] 用字統一失敗（{type(ex).__name__}），校正版不受影響")
        info = {"summary": {"status": "error", "reason": type(ex).__name__}, "unifier": None, "hits": []}
        _cp(run_log, "correct.consistency", info["summary"])
        return para_out, info


def minutes_stage(cfg: dict, text: str, transcript_texts: list, rm: dict | None = None, out_dir=None,
                  run_log=None, log=None) -> tuple:
    """auto_minutes：整理好的 meeting-minutes.md／notes.md 文字 → (新文字, summary)。transcript_texts＝摘要讀的逐字稿段落
    （校正版已經是看得到的文字）。關閉或失敗時原樣回傳。"""
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    if not enabled(cfg, warn=log):
        _cp(run_log, "minutes.consistency", {"status": "off"})
        return text, {"status": "off"}
    try:
        own = [l for l in text.split("\n") if not l.lstrip().startswith(">")]
        u = build(list(transcript_texts) + own, user_terms(rm=rm, out_dir=out_dir))
        new, hits = u.markdown(text)
        sm = summary(u, hits)
        _cp(run_log, "minutes.consistency", sm)
        if hits:
            log(f"  {console_line(hits)}")
        return new, sm
    except Exception as ex:  # noqa: BLE001
        log(f"  [!] 用字統一失敗（{type(ex).__name__}），內容不受影響")
        sm = {"status": "error", "reason": type(ex).__name__}
        _cp(run_log, "minutes.consistency", sm)
        return text, sm


def _cp(run_log, name: str, fields: dict):
    if run_log is None:
        return
    try:
        h = run_log.begin(name)
        run_log.end(h, **fields)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 單獨執行
MINUTES_FILES = ("meeting-minutes.md", "notes.md")


def _paragraph_texts(corrected: str | None, original: str | None) -> list:
    src, is_cor = (corrected, True) if corrected is not None else (original, False)
    if src is None:
        return []
    lines = src.split("\n")
    if is_cor and "---" in lines:
        lines = lines[lines.index("---") + 1:]
    out = []
    for line in lines:
        m = HEAD_RE.match(line)
        if m:
            out.append(visible(line[m.end():]) if is_cor else line[m.end():])
    return out


def run_folder(out_dir, cfg: dict | None = None, dry_run: bool = False, log=None, now: datetime | None = None) -> dict:
    """已經有的輸出資料夾：transcript.corrected.md、transcript.corrected.srt、meeting-minutes.md／notes.md（＋網頁版）。
    回傳 {"status", "groups", "edits", "files": {檔名: 處數}, "detail"}（detail 只給 console／報告，不寫 log）。"""
    out_dir = Path(out_dir)
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    if not out_dir.is_dir():
        return {"status": "failed", "reason": "no_folder", "groups": 0, "edits": 0, "files": {}}
    if cfg is None:
        from common import load_config
        cfg = load_config()

    def read(name):
        p = out_dir / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    cor, orig = read("transcript.corrected.md"), read("transcript.md")
    mins = {n: read(n) for n in MINUTES_FILES}
    texts = _paragraph_texts(cor, orig)
    for t in mins.values():
        if t is not None:
            texts += [l for l in t.split("\n") if not l.lstrip().startswith(">")]
    col = None
    try:
        import refs
        col = refs.collect(out_dir, None, cfg, frames=False, docs=True, context=True, warn=lambda m: None)
    except Exception:  # noqa: BLE001
        col = None
    u = build(texts, user_terms(col=col, out_dir=out_dir))
    results, all_hits = {}, []
    if cor is not None:
        results["transcript.corrected.md"] = u.corrected_md(cor)
        srt = read("transcript.corrected.srt")
        if srt is not None:
            results["transcript.corrected.srt"] = u.srt(srt)
    for n, t in mins.items():
        if t is not None:
            results[n] = u.markdown(t)
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    files = {}
    for name, (new, hits) in results.items():
        files[name] = len(hits)
        if name != "transcript.corrected.srt":
            all_hits += hits
        if hits and not dry_run:
            p = out_dir / name
            p.replace(out_dir / f"{p.stem}.{stamp}.bak{p.suffix}")
            p.write_text(new, encoding="utf-8", newline="\n")
    html = {}
    if not dry_run:
        for n in MINUTES_FILES:
            h = out_dir / (Path(n).stem + ".html")
            if files.get(n) and h.exists():
                try:
                    import render_html
                    r = render_html.render(out_dir, n, cfg=cfg)
                    html[h.name] = r.get("status")
                except Exception as ex:  # noqa: BLE001
                    html[h.name] = f"error:{type(ex).__name__}"
    res = {"status": "ok", "dry_run": dry_run, **{k: v for k, v in summary(u, all_hits).items() if k != "status"},
           "files": files, "html": html}
    try:
        import runlog
        rl = runlog.RunLog(out_dir, step="consistency")
        _cp(rl, "consistency", {k: v for k, v in res.items() if k not in ("files", "html", "dry_run")} | {"dry_run": dry_run})
        if rl.owns:
            rl.finish()
    except Exception:  # noqa: BLE001
        pass
    log(console_line(all_hits) + ("（試跑，沒有寫檔）" if dry_run and all_hits else ""))
    res["detail"] = detail(all_hits, 10 ** 6)
    return res


def main():
    try:
        from common import utf8_console
        utf8_console()
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="全文用字統一（本機處理，不呼叫模型）")
    ap.add_argument("out_dir", help="<檔名>_minutes 輸出資料夾")
    ap.add_argument("--dry-run", action="store_true", help="只列出會統一的寫法，不寫檔")
    a = ap.parse_args()
    res = run_folder(a.out_dir, dry_run=a.dry_run)
    for c, fs in res.get("detail") or []:
        print(f"  {c} ← " + "、".join(f"{f} ×{n}" for f, n in fs), file=sys.stderr)
    res.pop("detail", None)
    print(json.dumps({"consistency": res}, ensure_ascii=False))
    sys.exit(2 if res["status"] == "failed" else 0)


if __name__ == "__main__":
    main()
