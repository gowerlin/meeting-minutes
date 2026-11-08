"""會議記錄校稿：標記解析、校稿決定、人工修改、接續帶入、定稿、經驗整理、名詞同步。

只用標準函式庫，不做任何檔案 I/O 以外的事；與 meeting-minutes-pro（下稱 Pro）的接點都由呼叫端傳入
（mmproof_pro.Pro 提供 key_of、COMMON_WORDS、對照表、OpenCC 回復表等），所以這個模組可以單獨測試。

標記格式與 Pro 2.2.0 的 auto_correct.MARK_RE／consistency.MARK_RE 逐字相同（啟動時由 mmproof_pro 比對）：
  {原文→修正}  校正（原文、修正都非空）       {原文→}  刪除       {→補字}  補字
  {原文→統一}  用字統一（只差大小寫、空格、「.」「-」）
  [?原文｜推測] 或 [?原文]  待確認
"""
import hashlib
import re
from datetime import datetime

TOOL_VERSION = "1.1.2"
SESSION_PREFIX = "mm-proofread-session/"
SESSION_MAJOR = 1
SESSION_FORMAT = f"{SESSION_PREFIX}{SESSION_MAJOR}"

MARK_PATTERN = r"\{([^{}→\n]*)→([^{}\n]*)\}|\[\?([^\[\]｜\n]*?)(?:｜([^\[\]\n]*))?\]"
MARK_RE = re.compile(MARK_PATTERN)
HEAD_RE = re.compile(r"^\*\*\[(\d{1,2}:\d{2}:\d{2})\] ([^*\n]+?)\*\*：")
# 用字統一的比對鍵：與 Pro consistency.SEP_RE／key_of 相同。正式執行時一律用 Pro 傳入的 key_of，這裡只是沒有 Pro 時的同義實作
_SEP_RE = re.compile(r"(?<=[A-Za-z])[ .\-](?=[A-Za-z0-9])|(?<=[0-9])[ .\-](?=[A-Za-z])")
PUNCT = set("，。、！？；：「」『』（）《》〈〉…—,.!?;:()[]\"' 　\t")
BAD_VALUE_RE = re.compile(r"[{}\n\r]|\[\?")
MIN_LEN = 2               # 原文至少 2 字才建議進對照表（同 Pro corrections.MIN_LEN）
MIN_COUNT = 2             # 本場至少出現幾次（Pro correction.corrections_auto.min_count 的預設值）
HISTORY_KEEP = 200
LOG_KEEP = 500
CHOICES = ("suggest", "orig", "guess", "free")
STATES = ("pending", "accepted", "edited", "rejected")
KIND_LABEL = {"fix": "校正", "unify": "用字統一", "uncertain": "待確認", "insert": "補字", "delete": "刪除",
              "manual": "人工修改"}
MINUTES_FILES = ("meeting-minutes.md", "notes.md")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def stamp() -> str:
    """備份檔名用的時間（同 Pro：YYYYMMDD-HHMMSS）。"""
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def local_key_of(form: str) -> str:
    return _SEP_RE.sub("", form).lower()


def content(s: str) -> str:
    """去掉空白與標點後的內容字元。"""
    return "".join(c for c in s if c not in PUNCT and not c.isspace())


def bad_value(v) -> bool:
    """自由輸入與人工修改的值不能含標記符號或換行。"""
    return not isinstance(v, str) or bool(BAD_VALUE_RE.search(v))


# ---------------------------------------------------------------- 解析
def classify(m, key_of=local_key_of) -> dict:
    if m.group(3) is not None:
        return {"kind": "uncertain", "orig": m.group(3), "sugg": None, "guess": m.group(4) or None}
    a, b = m.group(1) or "", m.group(2) or ""
    if not a:
        kind = "insert"
    elif not b:
        kind = "delete"
    elif a != b and key_of(a) == key_of(b):
        kind = "unify"
    else:
        kind = "fix"
    return {"kind": kind, "orig": a, "sugg": b, "guess": None}


def tokenize(pi: int, raw: str, key_of=local_key_of) -> list:
    toks, last, k = [], 0, 0
    for m in MARK_RE.finditer(raw):
        if m.start() > last:
            toks.append({"t": "text", "text": raw[last:m.start()]})
        d = classify(m, key_of)
        d.update(t="mark", id=f"m{pi}-{k}", src=m.group(0))
        toks.append(d)
        k += 1
        last = m.end()
    if last < len(raw):
        toks.append({"t": "text", "text": raw[last:]})
    return toks


def tok_src(t: dict) -> str:
    return t["src"] if t["t"] == "mark" else t["text"]


def para_raw(p: dict) -> str:
    """段落原始字串（校正版那一行的本文，含標記原樣）；人工修改的位置以它為準。"""
    return "".join(tok_src(t) for t in p["tokens"])


def parse_corrected(text: str, key_of=local_key_of) -> dict:
    """transcript.corrected.md（或 transcript.md）→ {title, header, speakers, body}。

    第一個單獨一行的 --- 之前是表頭；沒有 --- 時整份都是本文。本文的段落是 `**[HH:MM:SS] 講者**：本文`，
    被換行的段落接回同一段（同 Pro parse_md）；其他行（畫面行、註記、空行）原樣保留在原位置。"""
    lines = text.replace("\r\n", "\n").split("\n")
    cut = lines.index("---") if "---" in lines else -1
    header, body_lines = (lines[:cut], lines[cut + 1:]) if cut >= 0 else ([], lines)
    speakers, in_spk = [], False
    for ln in header:
        if ln.startswith("## "):
            in_spk = ln.strip() == "## 講者對應"
            continue
        if in_spk and ln.startswith("|") and not set(ln.strip()) <= set("|-: "):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if cells and cells[0] != "代號":
                speakers.append((cells + ["", "", ""])[:3])
    body, pi = [], 0
    for ln in body_lines:
        m = HEAD_RE.match(ln)
        if m:
            raw = ln[m.end():].strip()
            body.append({"t": "para", "i": pi, "time": m.group(1).zfill(8), "speaker": m.group(2).strip(),
                         "tokens": tokenize(pi, raw, key_of)})
            pi += 1
        elif body and body[-1]["t"] == "para" and ln.strip() and not ln.startswith(">") and not ln.startswith("#"):
            last = body[-1]
            last["tokens"] = tokenize(last["i"], para_raw(last) + ln.strip(), key_of)
        else:
            body.append({"t": "line", "text": ln})
    head_lines = header if cut >= 0 else lines
    title = next((ln[2:].strip() for ln in head_lines if ln.startswith("# ")), "")
    return {"title": title, "header": header, "speakers": speakers, "body": body}


def paragraphs(doc: dict) -> list:
    return [b for b in doc["body"] if b["t"] == "para"]


def all_marks(doc: dict) -> list:
    return [t for p in paragraphs(doc) for t in p["tokens"] if t["t"] == "mark"]


def original_paragraphs(text: str) -> list:
    """transcript.md 的段落本文（數「原文出現幾次」用）。"""
    out = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        m = HEAD_RE.match(ln)
        if m:
            out.append(ln[m.end():].strip())
        elif out and ln.strip() and not ln.startswith(">") and not ln.startswith("#") and not ln.startswith("- "):
            out[-1] += ln.strip()
    return out


# ---------------------------------------------------------------- 暫存（session.json）
def empty_session(src_name: str, src_text: str) -> dict:
    return {"format": SESSION_FORMAT, "tool_version": TOOL_VERSION, "rev": 0, "created_at": now_iso(),
            "saved_at": None, "source": {"file": src_name, "sha256": sha256_text(src_text)},
            "marks": {}, "manual": [], "history": [], "progress": None, "imports": [], "finalized": None,
            "redo": None, "log": []}


def session_major(sess: dict):
    """回傳 format 的主版號；格式不認得回傳 None。"""
    f = sess.get("format") if isinstance(sess, dict) else None
    if not isinstance(f, str) or not f.startswith(SESSION_PREFIX):
        return None
    try:
        return int(f[len(SESSION_PREFIX):].split(".")[0])
    except ValueError:
        return None


def normalize_session(sess: dict) -> dict:
    """補齊缺的欄位（同一個主版號內新增的欄位），不改既有內容。"""
    base = empty_session("", "")
    for k, v in base.items():
        if k not in sess:
            sess[k] = v
    for k in ("marks",):
        if not isinstance(sess.get(k), dict):
            sess[k] = {}
    for k in ("manual", "history", "imports", "log"):
        if not isinstance(sess.get(k), list):
            sess[k] = []
    if not isinstance(sess.get("rev"), int):
        sess["rev"] = 0
    return sess


def log_op(sess: dict, action: str, files: list, note: str = "") -> dict:
    """稿內操作紀錄：時間、動作、檔名、筆數。不記逐字稿文字、詞對內容、權杖。"""
    rec = {"at": now_iso(), "action": action, "files": list(files)}
    if note:
        rec["note"] = note
    sess.setdefault("log", []).append(rec)
    sess["log"] = sess["log"][-LOG_KEEP:]
    return rec


# ---------------------------------------------------------------- 狀態
def mark_state(m: dict, dec) -> str:
    """pending／accepted／edited／rejected（畫面：未處理／已確認／已改／已退回）。"""
    if m["kind"] == "manual":
        return "edited"
    if not dec:
        return "pending"
    ch = dec.get("choice")
    if ch == "free":
        return "edited"
    if ch == "orig":
        return "accepted" if m["kind"] == "uncertain" else "rejected"
    return "accepted"


def mark_value(m: dict, dec, final: bool = True) -> str:
    """這個標記在定稿裡的文字。未處理：校正類用修正；待確認寫「原文〔?推測〕」（final=False 時用原文）。"""
    if m["kind"] == "manual":
        return m["value"]
    if not dec:
        if m["kind"] == "uncertain":
            return f"{m['orig']}〔?{m['guess'] or ''}〕" if final else m["orig"]
        return m["sugg"]
    ch = dec.get("choice")
    if ch == "orig":
        return m["orig"]
    if ch == "guess":
        return m["guess"] or m["orig"]
    if ch == "free":
        return dec.get("value", "")
    return m["sugg"] if m["kind"] != "uncertain" else (m["guess"] or m["orig"])


def clean_decisions(doc: dict, marks) -> tuple:
    """只留這份稿裡存在的標記 id、合法的決定。回傳 (決定, 錯誤說明或 None)。"""
    ids = {m["id"] for m in all_marks(doc)}
    out = {}
    if not isinstance(marks, dict):
        return {}, None
    for k, v in marks.items():
        if k not in ids or not isinstance(v, dict) or v.get("choice") not in CHOICES:
            continue
        if v["choice"] == "free":
            if bad_value(v.get("value")):
                return {}, f"標記 {k} 的自由輸入不能含 {{ }}、[? 或換行"
            out[k] = {"choice": "free", "value": v["value"]}
        else:
            out[k] = {"choice": v["choice"]}
    return out, None


def text_runs(p: dict) -> list:
    """段落裡每個文字片段（標記以外）在段落原始字串中的 [起, 訖)。"""
    out, pos = [], 0
    for t in p["tokens"]:
        n = len(tok_src(t))
        if t["t"] == "text":
            out.append((pos, pos + n))
        pos += n
    return out


def check_manual(doc: dict, manual) -> str | None:
    """人工修改的四條規則：落在同一個標記以外的文字片段內、原文與檔案一致、同段不互相重疊、
    新文字不含標記符號與換行。回傳錯誤說明，沒有錯回傳 None。"""
    if not isinstance(manual, list):
        return "人工修改的格式不正確"
    paras = {p["i"]: p for p in paragraphs(doc)}
    seen, ids = {}, set()
    for u in manual:
        if not isinstance(u, dict):
            return "人工修改的格式不正確"
        uid = u.get("id")
        if not isinstance(uid, str) or not uid or uid in ids:
            return "人工修改的 id 不正確或重複"
        ids.add(uid)
        p = paras.get(u.get("para"))
        s, e = u.get("start"), u.get("end")
        if p is None or not isinstance(s, int) or not isinstance(e, int) or isinstance(s, bool) or s < 0 or s >= e:
            return f"人工修改 {uid} 的位置不正確"
        if not any(a <= s and e <= b for a, b in text_runs(p)):
            return f"人工修改 {uid} 的選取範圍跨到標記了"
        if para_raw(p)[s:e] != u.get("orig"):
            return f"人工修改 {uid} 的原文和稿件對不上（稿件可能已變更）"
        if bad_value(u.get("value")):
            return f"人工修改 {uid} 的新文字不能含 {{ }}、[? 或換行"
        for a, b in seen.get(u["para"], []):
            if s < b and a < e:
                return f"人工修改 {uid} 與同一段的其他修改重疊"
        seen.setdefault(u["para"], []).append((s, e))
    return None


def clean_manual(manual: list) -> list:
    return [{"id": u["id"], "para": u["para"], "start": u["start"], "end": u["end"], "orig": u["orig"],
             "value": u["value"]} for u in manual]


def with_manual(doc: dict, sess: dict) -> dict:
    """把人工修改切進文字片段，成為 kind=manual 的標記；回傳新的 doc（不改原物件）。"""
    by_para = {}
    for u in sess.get("manual", []):
        by_para.setdefault(u["para"], []).append(u)
    body = []
    for b in doc["body"]:
        if b["t"] != "para" or b["i"] not in by_para:
            body.append(b)
            continue
        toks, pos0 = [], 0
        for t in b["tokens"]:
            n = len(tok_src(t))
            if t["t"] != "text":
                toks.append(t)
                pos0 += n
                continue
            us = sorted([u for u in by_para[b["i"]] if pos0 <= u["start"] and u["end"] <= pos0 + n],
                        key=lambda u: u["start"])
            pos = 0
            for u in us:
                s, e = u["start"] - pos0, u["end"] - pos0
                if s > pos:
                    toks.append({"t": "text", "text": t["text"][pos:s]})
                seg = t["text"][s:e]
                toks.append({"t": "mark", "id": u["id"], "kind": "manual", "orig": seg, "sugg": u["value"],
                             "value": u["value"], "guess": None, "src": seg})
                pos = e
            if pos < len(t["text"]):
                toks.append({"t": "text", "text": t["text"][pos:]})
            pos0 += n
        body.append(dict(b, tokens=toks))
    return dict(doc, body=body)


def progress(doc: dict, sess: dict) -> dict:
    """doc 要是 with_manual() 之後的（人工修改也算一處，一律算完成）。"""
    st = {s: 0 for s in STATES}
    ms = all_marks(doc)
    for m in ms:
        st[mark_state(m, sess["marks"].get(m["id"]))] += 1
    st["total"] = len(ms)
    st["manual"] = sum(1 for m in ms if m["kind"] == "manual")
    st["done"] = st["total"] - st["pending"]
    return st


def first_pending(doc: dict, sess: dict):
    for m in all_marks(doc):
        if mark_state(m, sess["marks"].get(m["id"])) == "pending":
            return m["id"]
    return None


# ---------------------------------------------------------------- 校正版被重新產生：帶入決定
def carry_over(old_doc: dict, old_sess: dict, new_doc: dict) -> tuple:
    """標記決定以（段落時間、講者、種類、原文、建議、推測）完全相同才帶，同一組有多處時依出現順序一一對應；
    人工修改以同段（時間＋講者）內第一個相同原文、而且通過人工修改規則的位置帶入。
    回傳 (marks, manual, {marks, marks_total, manual, manual_total})。"""
    def key(p, t):
        return (p["time"], p["speaker"], t["kind"], t["orig"], t["sugg"], t["guess"])
    old_by, total = {}, 0
    for p in paragraphs(old_doc):
        for t in p["tokens"]:
            if t["t"] == "mark" and t["id"] in old_sess.get("marks", {}):
                old_by.setdefault(key(p, t), []).append(old_sess["marks"][t["id"]])
                total += 1
    marks, carried = {}, 0
    for p in paragraphs(new_doc):
        for t in p["tokens"]:
            if t["t"] == "mark" and old_by.get(key(p, t)):
                marks[t["id"]] = old_by[key(p, t)].pop(0)
                carried += 1
    old_paras = {p["i"]: p for p in paragraphs(old_doc)}
    new_by_head = {}
    for p in paragraphs(new_doc):
        new_by_head.setdefault((p["time"], p["speaker"]), p)
    manual, m_ok = [], 0
    for u in old_sess.get("manual", []):
        op = old_paras.get(u.get("para"))
        np_ = new_by_head.get((op["time"], op["speaker"])) if op else None
        if not np_:
            continue
        raw = para_raw(np_)
        s = raw.find(u["orig"])
        while s >= 0:
            cand = dict(u, para=np_["i"], start=s, end=s + len(u["orig"]))
            if check_manual(new_doc, manual + [cand]) is None:
                manual.append(cand)
                m_ok += 1
                break
            s = raw.find(u["orig"], s + 1)
    return marks, manual, {"marks": carried, "marks_total": total, "manual": m_ok,
                           "manual_total": len(old_sess.get("manual", []))}


# ---------------------------------------------------------------- 定稿
def final_paragraph(p: dict, sess: dict, final: bool = True) -> str:
    return "".join(t["text"] if t["t"] == "text" else mark_value(t, sess["marks"].get(t["id"]), final)
                   for t in p["tokens"])


def resolved_marked(p: dict, sess: dict) -> str:
    """定稿字幕對時用的段落：所有標記寫成 {原文→定稿文字}（人工修改也是），未處理的待確認保留原樣（字幕用原文）。
    標記以外的文字與 transcript.md 逐字相同，所以可以交給 Pro subtitles.map_corrected 對回辨識段。"""
    out = []
    for t in p["tokens"]:
        if t["t"] == "text":
            out.append(t["text"])
            continue
        dec = sess["marks"].get(t["id"])
        if t["kind"] == "uncertain" and not dec:
            out.append(t["src"])
        else:
            out.append("{" + (t["orig"] or "") + "→" + mark_value(t, dec) + "}")
    return "".join(out)


def resolved_corrected_text(doc: dict, sess: dict) -> str:
    out = ["---", ""]
    for p in paragraphs(doc):
        out += [f"**[{p['time']}] {p['speaker']}**：{resolved_marked(p, sess)}", ""]
    return "\n".join(out)


def source_title(doc: dict, fallback: str) -> str:
    t = doc.get("title") or ""
    return t.split("：", 1)[1].strip() if "：" in t else (t or fallback)


def final_markdown(doc: dict, sess: dict, src_name: str, when: str, fallback_title: str) -> str:
    """transcript.final.md：段落格式同校正版，沒有任何標記；不含〈校正摘要〉〈待確認〉；講者對應與其他本文行原樣保留。"""
    pg = progress(doc, sess)
    n_marks = pg["total"] - pg["manual"]
    edited_marks = pg["edited"] - pg["manual"]
    cor = f"`{src_name}`" if src_name != "transcript.md" else "（沒有校正版，直接校原始逐字稿）"
    lines = [f"# 定稿逐字稿：{source_title(doc, fallback_title)}", "",
             f"> 原始逐字稿：`transcript.md`（未修改）｜校正版：{cor}｜定稿：會議記錄校稿 {TOOL_VERSION}，{when}",
             f"> 校稿：標記 {n_marks} 處（確認 {pg['accepted']}、改 {edited_marks}、退回 {pg['rejected']}、"
             f"未處理 {pg['pending']}）、人工修改 {pg['manual']} 處", ""]
    if doc["speakers"]:
        lines += ["## 講者對應", "", "| 代號 | 姓名 | 依據 |", "|---|---|---|"]
        lines += ["| " + " | ".join(c) + " |" for c in doc["speakers"]]
        lines.append("")
    lines += ["---", ""]
    body = doc["body"]
    while body and body[0]["t"] == "line" and not body[0]["text"].strip():
        body = body[1:]
    for b in body:
        if b["t"] == "para":
            lines.append(f"**[{b['time']}] {b['speaker']}**：{final_paragraph(b, sess)}")
        else:
            lines.append(b["text"])
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------- 經驗整理
def is_latin_term(t: str) -> bool:
    """寫法有特徵的英文名詞：英數開頭、只含英數與 空格 . - + #，而且至少一個大寫字母（Redis、NotebookLM）。"""
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .\-+#]*", t)) and any(c.isupper() for c in t)


def decided_pairs(doc: dict, sess: dict) -> dict:
    """(原文, 定稿文字) → {count, kinds, first}：有決定（或人工修改）而且定稿文字≠原文的標記。
    不含用字統一（改進詞表）、補字（沒有原文）、退回與未處理。doc 要是 with_manual() 之後的。"""
    pairs = {}
    for p in paragraphs(doc):
        for t in p["tokens"]:
            if t["t"] != "mark" or t["kind"] in ("unify", "insert"):
                continue
            dec = sess["marks"].get(t["id"])
            if t["kind"] != "manual" and not dec:
                continue
            v = mark_value(t, dec)
            a = t["orig"] or ""
            if not a or v == a:
                continue
            e = pairs.setdefault((a, v), {"count": 0, "kinds": set(), "first": p["time"]})
            e["count"] += 1
            e["kinds"].add(t["kind"])
    return pairs


def experience(doc: dict, sess: dict, orig_paras: list, rows: list, gloss: set, keeps: set = frozenset(),
               common_words: frozenset = frozenset(), min_count: int = MIN_COUNT) -> dict:
    """對照表與詞表建議。每項有 checked（預設勾選）、why（不勾或不能勾的原因）、importable（能不能勾）。

    預設勾選＝全部符合：原文 ≥ 2 字、不是刪除、固定（每處都改成同一個寫法）、本場出現 ≥ min_count 次、不衝突、
    不在 OpenCC 回復表、不在詞表、不是一般英文單字。已在對照表、與對照表衝突的不能勾。"""
    orig_text = "\n".join(orig_paras)
    wrongs = {w: r for w, r, _ in rows}
    rights = {r for _, r, _ in rows}
    pairs = decided_pairs(doc, sess)
    by_a = {}
    for (a, v) in pairs:
        by_a.setdefault(a, set()).add(v)
    out = []
    for (a, v), e in sorted(pairs.items(), key=lambda x: (-x[1]["count"], x[1]["first"], x[0])):
        why = []
        total = orig_text.count(a)
        if len(a) < MIN_LEN:
            why.append("太短（少於 2 字）")
        if not v:
            why.append("刪除")
        if len(by_a[a]) > 1 or total != e["count"]:
            why.append(f"不是每處都改成這個寫法（原文 {total} 處、改 {e['count']} 處）")
        elif e["count"] < min_count:
            why.append(f"本場只出現 {e['count']} 次")
        blocked = None
        if wrongs.get(a) == v:
            why, blocked = ["已在對照表"], "已在對照表"
        elif a in wrongs:
            blocked = f"對照表已有「{a} → {wrongs[a]}」"
            why.append(blocked)
        elif v in wrongs or a in rights:
            blocked = "與對照表衝突"
            why.append(blocked)
        if blocked != "已在對照表":
            if a in keeps:
                why.append("OpenCC 回復表的詞")
            if a in gloss:
                why.append("詞表裡的詞")
            if a.lower() in common_words:
                why.append("一般英文單字")
        phrase = " " in a or " " in v or len(content(a)) >= 5
        out.append({"wrong": a, "right": v, "count": e["count"], "total": total, "first": e["first"],
                    "kind": "片語" if phrase else "詞", "source": sorted(KIND_LABEL[k] for k in e["kinds"]),
                    "checked": not why, "why": why, "importable": blocked is None})
    gl = {}
    for (a, v), e in pairs.items():
        if v and v not in gloss and len(content(v)) >= 2 and (is_latin_term(v) or "manual" in e["kinds"]):
            gl.setdefault(v, {"term": v, "count": 0, "from": "校稿決定"})["count"] += e["count"]
    for m in all_marks(doc):
        if m["kind"] == "unify" and mark_state(m, sess["marks"].get(m["id"])) == "accepted" and m["sugg"] not in gloss:
            gl.setdefault(m["sugg"], {"term": m["sugg"], "count": 0, "from": "用字統一"})["count"] += 1
    gls = []
    for g in sorted(gl.values(), key=lambda g: (-g["count"], g["term"])):
        latin = is_latin_term(g["term"])
        common = g["term"].lower() in common_words
        g["checked"] = latin and not common
        g["why"] = [] if g["checked"] else (["中文詞預設不勾，確認是專有名詞再勾"] if not latin else ["一般英文單字"])
        gls.append(g)
    return {"corrections": out, "glossary": gls}


def pick_imports(ex: dict, want_pairs, want_terms) -> tuple:
    """伺服器端重新計算後，只接受「目前建議清單中、可匯入」的項目；同一原文只寫第一組，其他列為略過。"""
    ok_pairs = {(c["wrong"], c["right"]) for c in ex["corrections"] if c["importable"]}
    ok_terms = {g["term"] for g in ex["glossary"]}
    pairs, skipped, seen = [], [], set()
    for x in want_pairs or []:
        if not isinstance(x, dict):
            continue
        k = (x.get("wrong"), x.get("right"))
        if k not in ok_pairs:
            continue
        if k[0] in seen:
            skipped.append(list(k))
            continue
        seen.add(k[0])
        pairs.append(k)
    terms = []
    for t in want_terms or []:
        if t in ok_terms and t not in terms:
            terms.append(t)
    return pairs, terms, skipped


def load_glossary(text: str) -> set:
    return {ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")}


# ---------------------------------------------------------------- 名詞同步到會議記錄／筆記
def sync_pairs(doc: dict, sess: dict) -> list:
    """校稿確認的寫法：有決定、定稿文字≠原文、原文 ≥ 2 字、不是刪除的標記與人工修改，加上已確認的用字統一；
    同一原文只取第一組。doc 要是 with_manual() 之後的。"""
    pairs = [(a, v) for (a, v) in decided_pairs(doc, sess) if v and len(a) >= MIN_LEN]
    for m in all_marks(doc):
        if m["kind"] == "unify" and mark_state(m, sess["marks"].get(m["id"])) == "accepted":
            pairs.append((m["orig"], m["sugg"]))
    seen, out = set(), []
    for a, v in pairs:
        if a not in seen:
            seen.add(a)
            out.append((a, v))
    return out


def apply_pairs(text: str, pairs: list) -> tuple:
    """單次掃描替換（長的先比，同 Pro corrections.Corrector）；> 開頭的說明行與 ``` 區塊不改。
    回傳 (新文字, {原文: 處數})。"""
    if not pairs:
        return text, {}
    mp = dict(pairs)
    rx = re.compile("|".join(re.escape(k) for k in sorted(mp, key=len, reverse=True)))
    hits, out, fence = {}, [], False
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```"):
            fence = not fence
            out.append(line)
            continue
        if fence or s.startswith(">"):
            out.append(line)
            continue

        def sub(m):
            hits[m.group(0)] = hits.get(m.group(0), 0) + 1
            return mp[m.group(0)]
        out.append(rx.sub(sub, line))
    return "\n".join(out), hits
