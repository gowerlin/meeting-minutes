"""字幕（2.0.0，規格 §5）：transcript.cues.srt 與 transcript.corrected.srt。

- transcript.cues.srt：transcript.json segments 的文字（＝transcript.srt 的文字）依字幕規則重新切條，不經 AI（U5）。
- transcript.corrected.srt：transcript.corrected.md（AI 校正或對話補校）以「內容字元座標」對應回辨識段，
  再依字幕規則重新切條（U4）；待確認標記依 subtitles.uncertain 顯示（U6）。
  對應方法移植自 2.0.0 開發期的原型（規格 §5.2）：
    1. 依 transcribe.write_outputs() 的規則從 transcript.json 重建 transcript.md 的段落，記每個 segment 在段落
       內容字元（auto_correct.content_of：去空白與標點）裡的起訖。
    2. 校正版每一段依段首（時間＋講者）對回原段；S? 且時間相同＝前一段拆出來的。
    3. 標記外的內容字元必須與原段落逐字相同，逐字歸給所在的 segment；標點與空白歸給前一個字所在的 segment。
       {a→b}：b 整段放進 a 起點所在的 segment（a 跨兩個 segment 記「跨段標記」）；{a→} 刪除；{→b} 放進前一個字的 segment。
    4. 走完時位置不等於原段落內容字元數 → 該段對應失敗，該段用原文。
    5. 段首對不上 → 文件層級：整份依序走一次；也失敗 → 全部用原文（status: map_failed）。
    6. 被刪光的 segment 不輸出。段首「姓名（S#）」→ 字幕講者標籤用姓名（規格 §5.2）。
- 字幕規則（Netflix 繁中 TTSG，規格 §5.3）：每行 ≤ max_line_chars（顯示寬度：全形 1、半形 0.5）、最多 max_lines 行、
  每條 min_sec～max_sec 秒、每秒 max_cps 字只檢查；行尾不留「、，。」、行中「。」改全形空白；一條字幕不跨辨識段
  （太短的條才併到同講者的相鄰條）；一個辨識段切成多條時，時間依內容字元數比例分配（段首時間＝辨識段開頭）。
- 失敗不影響轉寫與校正（規格 §5.6）：write_cues()／write_corrected() 不丟例外，結果寫進 transcript.json meta.subtitles
  （只改這個鍵）、run_log 檢查點 subtitles 與 console 一行。

命令列（對話補校後重新產生字幕；都不給＝兩個都做）：
  python subtitles.py <輸出資料夾> [--cues] [--corrected] [--uncertain orig|guess|mark] [--no-recue]
  stdout 最後一行：{"subtitles": {...}}
"""
import argparse
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, print_banner, setting, utf8_console  # noqa: E402
import auto_correct as ac  # noqa: E402  content_of、MARK_RE（校正版標記與 §6.8 驗證的同一套定義）

CUES_NAME = "transcript.cues.srt"
CORRECTED_NAME = "transcript.corrected.srt"
CORRECTED_MD = "transcript.corrected.md"
HEAD = re.compile(r"^\*\*\[(\d{1,2}:\d{2}:\d{2})\] ([^*\n]+?)\*\*：")
CODE_RE = re.compile(r"^(?:(.*?)（)?(S\d+|S\?)）?$")
CJK = re.compile(r"[一-鿿，。！？、]")                 # 與 transcribe.write_outputs() 的接字規則相同
NL = "\n"
BREAK_STRONG = "。？！?!"
BREAK_WEAK = "，、；：,;:"
BREAKS = BREAK_STRONG + BREAK_WEAK
TOKEN_RE = re.compile(r"[^。？！?!，、；：,;:]+[。？！?!，、；：,;:]*|[。？！?!，、；：,;:]+")
UNCERTAIN = ("orig", "guess", "mark")
SPEAKER_LABEL = ("change", "always", "none")
MARK_Q = "\x00"            # 切條時〔?推測〕的「?」暫時換成這個字（「?」是句末標點，會被當成切點）
MIN_SPLIT_CHARS = 4          # 太長的條照字數平均切時，每條至少幾個內容字元（避免一字一條）
MERGE_MAX_GAP = 1.0          # 太短的條併到相鄰條時，兩條之間的停頓上限（秒）


def log_default(msg: str):
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- 設定
def options(cfg: dict | None, **override) -> dict:
    """subtitles.* 設定（逐鍵 common.setting()，不合法的值退回預設）＋單次覆寫（值為 None 的忽略）。"""
    cfg = cfg or {}
    o = {}
    for k in ("cues_srt", "corrected_srt", "recue", "max_line_chars", "max_lines", "min_sec", "max_sec", "max_cps",
              "speaker_label", "uncertain"):
        o[k] = setting(cfg, f"subtitles.{k}")
    o.update({k: v for k, v in override.items() if v is not None})
    d = lambda k: setting({}, f"subtitles.{k}")  # noqa: E731
    for k, typ, lo in (("max_line_chars", float, 4), ("max_lines", int, 1), ("min_sec", float, 0.0),
                       ("max_sec", float, 1.0), ("max_cps", float, 1.0)):
        try:
            o[k] = typ(o[k])
            if o[k] < lo:
                raise ValueError
        except (TypeError, ValueError):
            o[k] = d(k)
    if o["speaker_label"] not in SPEAKER_LABEL:
        o["speaker_label"] = d("speaker_label")
    if o["uncertain"] not in UNCERTAIN:
        o["uncertain"] = d("uncertain")
    for k in ("cues_srt", "corrected_srt", "recue"):
        o[k] = bool(o[k])
    return o


# ---------------------------------------------------------------- 共用小工具
def srt_ts(sec: float) -> str:
    """SRT 時間；與 transcribe.ts(srt=True) 相同（毫秒捨去），段首時間與 transcript.srt 逐字相同。"""
    sec = max(sec, 0.0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"


def md_ts(sec: float) -> str:
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d}"


def width(s: str) -> float:
    """顯示寬度：全形 1、半形 0.5。"""
    return sum(0.5 if ord(c) < 0x2E80 else 1 for c in s)


def content(s: str) -> str:
    return ac.content_of(s)


def split_speaker(s: str) -> tuple:
    """段首講者 → (代號 S#／S?／None, 姓名或 None)。「王小明（S1）」→ ("S1", "王小明")；「S2」→ ("S2", None)；「王小明」→ (None, "王小明")。"""
    s = s.strip()
    m = CODE_RE.match(s)
    if m and (m.group(1) is None) == (not s.endswith("）")):
        name = (m.group(1) or "").strip() or None
        return m.group(2), name
    return None, s or None


# ---------------------------------------------------------------- 對應（規格 §5.2）
def md_paragraphs(doc: dict) -> list:
    """重建 transcript.md 的段落（transcribe.write_outputs() 的規則）：[{time, spk, segs: [index], text}]。"""
    segs, frames = doc.get("segments") or [], doc.get("keyframes") or []
    events = sorted([(s["start"], "seg", i) for i, s in enumerate(segs)] + [(k["time"], "frame", None) for k in frames],
                    key=lambda x: x[0])
    out, cur = [], None
    for _t, kind, i in events:
        if kind == "frame":
            cur = None
            continue
        s = segs[i]
        para = s.get("para")
        if cur is None or s["speaker"] != cur["spk"] or (para is not None and para != cur["para"]):
            cur = {"time": md_ts(s["start"]), "spk": s["speaker"], "para": para, "segs": [], "pieces": []}
            out.append(cur)
        sep = "" if not cur["pieces"] or CJK.match(s["text"][:1]) else " "
        cur["pieces"].append(sep + s["text"])
        cur["segs"].append(i)
    for p in out:
        p["text"] = "".join(p.pop("pieces"))
    return out


def corrected_paragraphs(text: str) -> list:
    """校正版本文（第一個 --- 之後）：[{time, code, name, text}]；畫面行、> ⚠ 註記行、標題行略過。"""
    lines = text.replace("\r\n", "\n").split("\n")
    if "---" in lines:
        lines = lines[lines.index("---") + 1:]
    out = []
    for line in lines:
        m = HEAD.match(line)
        if m:
            t = m.group(1)
            code, name = split_speaker(m.group(2))
            out.append({"time": t if len(t) == 8 else "0" + t, "code": code, "name": name,
                        "text": line[m.end():].strip()})
        elif out and line.strip() and not line.startswith(">") and not line.startswith("#"):
            out[-1]["text"] += line.strip()                 # 手動改過、段落被換行時接回同一段（同 auto_correct.parse_md）
    return out


def group(md: list, cor: list) -> tuple:
    """校正版段落對回原段落：同時間＋同講者代號＝原段；S? 且時間相同＝前一段拆出來的；同段首再出現＝半段接回。
    代號沒寫（只寫姓名）時只比時間。回傳 (每個原段的 [part], 錯誤訊息)。"""
    groups, k = [[] for _ in md], -1
    for c in cor:
        code = c["code"]
        nxt = md[k + 1] if k + 1 < len(md) else None
        if nxt and c["time"] == nxt["time"] and code in (None, nxt["spk"]):
            k += 1
            groups[k].append(dict(c, code=code or nxt["spk"]))
        elif k >= 0 and code == "S?" and c["time"] == md[k]["time"]:
            groups[k].append(dict(c))
        elif k >= 0 and c["time"] == md[k]["time"] and code in (None, md[k]["spk"]):
            groups[k][-1] = dict(groups[k][-1], text=groups[k][-1]["text"] + c["text"])
        else:
            return None, f"unexpected paragraph [{c['time']}]"
    if k != len(md) - 1:
        return None, f"missing {len(md) - 1 - k} paragraph(s)"
    return groups, None


def map_paragraph(p: dict, parts: list, segs: list, mode: str, st: dict) -> dict | None:
    """一個原段落（或文件層級的全文）→ {segment index: {"text", "spk", "label"}}；對應失敗回傳 None。"""
    O = content(p["text"])
    bounds, pos = [], 0
    for i in p["segs"]:
        n = len(content(segs[i]["text"]))
        bounds.append((pos, pos + n, i))
        pos += n
    if pos != len(O):
        return None
    seg_starts = {a for a, b, i in bounds}

    def seg_at(q: int) -> int:
        for a, b, i in bounds:
            if a <= q < b:
                return i
        return bounds[-1][2]

    buf = {i: [] for i in p["segs"]}
    starts = []                                            # (校正段起點, part)
    cross = split_in = 0
    q = 0
    for pi, part in enumerate(parts):
        starts.append((q, part))
        if pi > 0 and part["code"] == "S?" and q not in seg_starts:
            split_in += 1                                  # 拆點在 segment 中間：該 segment 保留原講者
        text, last = part["text"], 0
        for m in list(ac.MARK_RE.finditer(text)) + [None]:
            lit = text[last:m.start()] if m else text[last:]
            for ch in lit:
                c = content(ch)
                if c:
                    if q >= len(O) or O[q] != c:
                        return None
                    buf[seg_at(q)].append(ch)
                    q += 1
                else:
                    buf[seg_at(max(q - 1, 0))].append(ch)
            if m is None:
                break
            last = m.end()
            if m.group(3) is not None or (m.group(1) is None and m.group(2) is None):   # [?a｜b]／[?a]
                a, b = m.group(3) or "", m.group(4)
                if mode == "guess":
                    shown = b if b else a
                elif mode == "mark":
                    shown = f"{a}〔?{b or ''}〕"
                else:
                    shown = a
            else:                                          # {a→b}
                a, shown = m.group(1) or "", m.group(2) or ""
            ca = content(a)
            if O[q:q + len(ca)] != ca:
                return None
            if ca:
                first, lastc = seg_at(q), seg_at(q + len(ca) - 1)
                if first != lastc:
                    cross += 1
                buf[first].append(shown)
            else:
                buf[seg_at(max(q - 1, 0))].append(shown)
            q += len(ca)
    if q != len(O):
        return None
    st["cross_segment_marks"] += cross
    st["split_in_segment"] += split_in
    out = {}
    for a, b, i in bounds:
        part = [pt for s0, pt in starts if s0 <= a][-1] if starts else None
        spk = segs[i]["speaker"]
        if part and part["code"] == "S?":                 # segment 開頭落在 S? 段裡 → 講者改 S?（拆點在段內的保留原講者）
            spk = "S?"
        label = spk
        if part and part.get("name") and part["code"] == spk:
            label = part["name"]
        out[i] = {"text": "".join(buf[i]).strip(), "spk": spk, "label": label}
    return out


def map_corrected(doc: dict, corrected_text: str, mode: str = "orig") -> tuple:
    """回傳 (每個 segment 的 {"start","end","spk","label","text"}（被刪光的不列）, 統計)。"""
    segs = doc.get("segments") or []
    md = md_paragraphs(doc)
    cor = corrected_paragraphs(corrected_text)
    st = {"paragraphs": len(md), "map_failed_paragraphs": 0, "doc_level": False, "cross_segment_marks": 0,
          "split_in_segment": 0, "changed_segments": 0, "deleted_segments": 0, "map_failed": False}
    new = {}
    if md:
        groups, _err = group(md, cor)
        if groups is None:                                 # 段首對不上 → 文件層級
            st["doc_level"] = True
            whole = {"time": md[0]["time"], "spk": md[0]["spk"], "segs": [i for p in md for i in p["segs"]],
                     "text": "".join(p["text"] for p in md)}
            r = map_paragraph(whole, [dict(c, code=c["code"]) for c in cor], segs, mode, st) if cor else None
            if r is None:
                st["map_failed"] = True
                st["map_failed_paragraphs"] = len(md)
            else:
                new.update(r)
        else:
            for p, parts in zip(md, groups):
                r = map_paragraph(p, parts, segs, mode, st)
                if r is None:
                    st["map_failed_paragraphs"] += 1
                else:
                    new.update(r)
    cues = []
    for i, s in enumerate(segs):
        r = new.get(i) or {"text": s["text"], "spk": s["speaker"], "label": s["speaker"]}
        if r["text"] != s["text"]:
            st["changed_segments"] += 1
        if not content(r["text"]):
            st["deleted_segments"] += 1                    # 整段被刪掉（例如幻覺句）→ 字幕不輸出
            continue
        cues.append({"start": float(s["start"]), "end": float(s["end"]), "spk": r["spk"], "label": r["label"],
                     "text": r["text"], "seg": i})
    return cues, st


def segment_cues(doc: dict) -> list:
    return [{"start": float(s["start"]), "end": float(s["end"]), "spk": s["speaker"], "label": s["speaker"],
             "text": s["text"], "seg": i} for i, s in enumerate(doc.get("segments") or []) if content(s["text"])]


# ---------------------------------------------------------------- 字幕規則（規格 §5.3）
def clean_line(line: str) -> str:
    """行尾不留「、，。」；行中「。」改全形空白（TTSG I.12）。"""
    line = re.sub(r"[、，。]+$", "", line.strip())
    return line.replace("。", "　").strip()


def _inword(a: str, b: str) -> bool:
    return a.isascii() and a.isalnum() and b.isascii() and b.isalnum()


def wrap(text: str, max_line: float, max_lines: int, punct_only: bool = False) -> list | None:
    """切成最多 max_lines 行、每行（清掉行尾標點後）≤ max_line；做不到回傳 None。
    斷行點的優先序：標點之後 > 不切英數字中間 > 越接近中間 > 上短下長。punct_only：只在標點之後換行。"""
    text = text.strip()
    if width(clean_line(text)) <= max_line:
        return [clean_line(text)]
    if max_lines <= 1:
        return None
    total = width(text)
    if total - sum(text.count(c) for c in "、，。") > max_line * max_lines:   # 清掉行尾標點也放不下
        return None
    pw, inside, depth = [0.0], [], 0
    for ch in text:
        pw.append(pw[-1] + width(ch))
        depth += 1 if ch == "〔" else (-1 if ch == "〕" and depth else 0)
        inside.append(depth > 0)                           # 〔?推測〕標記中間不斷行

    def score(i):
        return (0 if text[i - 1] in BREAKS else 1, 1 if _inword(text[i - 1], text[i]) or inside[i - 1] else 0,
                abs(pw[i] - total / 2), 0 if pw[i] <= total / 2 else 1)
    best = None
    for i in sorted(range(1, len(text)), key=score):
        if pw[i] - max_line > 3:                           # 前一行（清掉行尾標點後）不可能放得下
            continue
        if punct_only and text[i - 1] not in BREAKS:
            continue
        head = clean_line(text[:i])
        if not content(head) or width(head) > max_line:
            continue
        rest = wrap(text[i:], max_line, max_lines - 1, punct_only)
        if rest is not None and content("".join(rest)):
            best = [head] + rest
            break
    return best


def fits(text: str, o: dict, punct_only: bool = False) -> bool:
    return wrap(text, o["max_line_chars"], o["max_lines"], punct_only) is not None


def _hard_split(tok: str, o: dict) -> list:
    """一個子句放不進一條：平均切成最少條（盡量不切英數字中間）；做不到就從前面取最長、放得進一條的部分。"""
    cap = o["max_line_chars"] * o["max_lines"]
    if fits(tok, o):
        return [tok]
    n = math.ceil(width(tok) / cap)
    for k in (n, n + 1):                                   # 平均切：每段目標寬度 total / k
        pw, cuts = 0.0, []
        targets = [width(tok) * j / k for j in range(1, k)]
        pos = []
        for i, ch in enumerate(tok):
            pw += width(ch)
            pos.append(pw)
        for t in targets:
            cand = [i + 1 for i in range(len(tok) - 1) if (not cuts or i + 1 > cuts[-1])]
            if not cand:
                break
            c = min(cand, key=lambda i: (abs(pos[i - 1] - t) + (1.5 if _inword(tok[i - 1], tok[i]) else 0)))
            cuts.append(c)
        parts = [tok[a:b] for a, b in zip([0] + cuts, cuts + [len(tok)])]
        if len(parts) == k and all(content(x) and fits(x, o) for x in parts):
            return parts
    out = []
    while tok and not fits(tok, o):
        k, w = 0, 0.0
        while k < len(tok) - 1 and w + width(tok[k]) <= cap:
            w += width(tok[k])
            k += 1
        k = max(k, 1)
        while k > 1 and not fits(tok[:k], o):
            k -= 1
        j = k
        while j > 1 and _inword(tok[j - 1], tok[j]):
            j -= 1                                         # 往前退到英數字詞的邊界
        if j > 1 and k - j <= 8:
            k = j
        out.append(tok[:k])
        tok = tok[k:]
    if tok:
        out.append(tok)
    return out


def split_text(text: str, o: dict) -> list:
    """一段文字切成字幕條：先在句末標點切、再在句中標點切；一個子句就放不進一條時硬切。"""
    out, cur = [], ""
    for tok in TOKEN_RE.findall(text):
        if fits(cur + tok, o, punct_only=bool(cur)):       # 併進前面的子句時只接受在標點處換行（TTSG：標點之後斷行）
            cur += tok
            if tok[-1:] in BREAK_STRONG and width(cur) >= o["max_line_chars"]:
                out.append(cur)
                cur = ""
            continue
        if cur:
            out.append(cur)
        pieces = _hard_split(tok, o)
        out += pieces[:-1]
        cur = pieces[-1] if pieces else ""
    if cur:
        out.append(cur)
    res = []
    for x in out:                                          # 句中標點不放在條首：移到前一條結尾（之後會被清掉）
        lead = re.match(r"^[，、；：,;:。]+", x)
        if lead and res:
            res[-1] += lead.group(0)
            x = x[lead.end():]
        if content(x):
            res.append(x)
        elif res:
            res[-1] += x
    return [x.strip() for x in res if content(x)]


def split_long(text: str, dur: float, o: dict) -> list:
    """顯示超過 max_sec 的條：依標點再切；沒有標點就照字數平均切（每條至少 MIN_SPLIT_CHARS 個字）。"""
    need = math.ceil(dur / o["max_sec"] - 1e-9)
    if need <= 1:
        return [text]
    cuts = [i + 1 for i, c in enumerate(text) if c in BREAKS and 0 < i + 1 < len(text) and content(text[i + 1:])]
    if cuts:
        total = len(content(text))
        chosen, last = [], 0
        for k in range(1, need):                           # 依字數比例找最接近的標點
            target = total * k / need
            cand = [c for c in cuts if c > last]
            if not cand:
                break
            c = min(cand, key=lambda c: abs(len(content(text[:c])) - target))
            if c not in chosen:
                chosen.append(c)
                last = c
        parts, a = [], 0
        for c in chosen + [len(text)]:
            if content(text[a:c]):
                parts.append(text[a:c])
            a = c
        parts = [p for p in parts if content(p)]
        if len(parts) > 1:
            return [q for p in parts for q in split_long(p, dur * len(content(p)) / max(total, 1), o)]
    n = len(content(text))
    k = min(need, n // MIN_SPLIT_CHARS)
    if k <= 1:
        return [text]
    parts, cur, seen = [], "", 0
    for ch in text:
        cur += ch
        if content(ch):
            seen += 1
            if len(parts) < k - 1 and seen >= n * (len(parts) + 1) / k:
                parts.append(cur)
                cur = ""
    if cur:
        if content(cur):
            parts.append(cur)
        else:
            parts[-1] += cur
    return parts


def recue(cues: list, o: dict) -> list:
    """辨識段（或校正後的辨識段）→ 字幕條（規格 §5.3）。每條：{start, end, spk, label, lines, text, seg}。"""
    out = []
    for c in cues:
        pieces = split_text(c["text"].replace("〔?", "〔" + MARK_Q), o)
        if not pieces:
            continue
        dur = max(c["end"] - c["start"], 0.0)
        total = sum(max(len(content(p)), 1) for p in pieces)
        final = []
        for p in pieces:                                   # 太長：依標點再切、或照字數平均切
            d = dur * max(len(content(p)), 1) / total
            final += split_long(p, d, o) if d > o["max_sec"] else [p]
        n = [max(len(content(p)), 1) for p in final]
        tot, acc = sum(n), 0
        for k, (p, w) in enumerate(zip(final, n)):
            a = c["start"] + dur * acc / tot
            acc += w
            b = c["end"] if k == len(final) - 1 else c["start"] + dur * acc / tot
            out.append({"start": a, "end": b, "spk": c["spk"], "label": c["label"], "text": p, "seg": c["seg"],
                        "seg_start": k == 0})
    o_min, o_max = o["min_sec"], o["max_sec"]
    merged = []                                            # 太短：併到同講者的相鄰條（放得進一條、不超過 max_sec 才併）
    for c in out:
        if merged:
            m = merged[-1]
            same = m["label"] == c["label"] and c["start"] - m["end"] <= MERGE_MAX_GAP
            short = (c["end"] - c["start"] < o_min) or (m["end"] - m["start"] < o_min)
            if same and short and c["end"] - m["start"] <= o_max and fits(m["text"] + c["text"], o):
                m["end"] = c["end"]
                m["text"] += c["text"]
                continue
        merged.append(dict(c))
    for k, a in enumerate(merged):                         # 還是太短：延長（先用到下一條前的空檔；不跨辨識段開頭）
        lack = o_min - (a["end"] - a["start"])
        if lack <= 0:
            continue
        b = merged[k + 1] if k + 1 < len(merged) else None
        if b is None:
            a["end"] += lack
            continue
        gap = max(b["start"] - a["end"], 0.0)
        ext = min(lack, gap)
        a["end"] += ext
        lack -= ext
        if lack > 1e-9 and not b["seg_start"] and b["end"] - b["start"] > o_min:   # 同一辨識段內：把下一條開頭往後推
            shift = min(lack, (b["end"] - b["start"]) - o_min)
            a["end"] += shift
            b["start"] += shift
    res = []
    for c in merged:
        lines = wrap(c["text"], o["max_line_chars"], o["max_lines"]) or [clean_line(c["text"])]
        lines = [ln for ln in lines if ln]
        if not lines or not content("".join(lines)):
            continue
        c["lines"] = [ln.replace(MARK_Q, "?") for ln in lines]
        c["text"] = c["text"].replace(MARK_Q, "?")
        res.append(c)
    return res


def plain_cues(cues: list) -> list:
    """subtitles.recue: false：一條對一條、只換文字（不切條、不清行尾標點）。"""
    return [dict(c, lines=[c["text"].strip()], seg_start=True) for c in cues if content(c["text"])]


def cue_stats(cues: list, o: dict) -> dict:
    lines = [ln for c in cues for ln in c["lines"]]
    durs = [c["end"] - c["start"] for c in cues]
    cps = [width(content("".join(c["lines"]))) / max(d, 0.01) for c, d in zip(cues, durs)]
    return {"cues": len(cues), "lines": len(lines),
            "over_line": sum(width(ln) > o["max_line_chars"] for ln in lines),
            "over_lines": sum(len(c["lines"]) > o["max_lines"] for c in cues),
            "over_max_sec": sum(d > o["max_sec"] + 1e-6 for d in durs),
            "under_min_sec": sum(d < o["min_sec"] - 1e-6 for d in durs),
            "over_cps": sum(s > o["max_cps"] for s in cps),
            "line_end_punct": sum(bool(re.search(r"[、，。]$", ln)) for ln in lines)}


def render_srt(cues: list, speaker_label: str) -> str:
    """UTF-8、\\n 換行、條號從 1 連續；講者標籤放第一行行首（規格 §5.4）。"""
    out, prev = [], None
    for k, c in enumerate(cues, 1):
        lines = list(c["lines"])
        if speaker_label == "always" or (speaker_label == "change" and c["label"] != prev):
            lines[0] = f"[{c['label']}] {lines[0]}"
        prev = c["label"]
        out.append(f"{k}\n{srt_ts(c['start'])} --> {srt_ts(c['end'])}\n" + NL.join(lines) + "\n\n")
    return "".join(out)


def _write(path: Path, text: str):
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    tmp.replace(path)


def update_meta(out_dir: Path, key: str, value: dict):
    """transcript.json 只改 meta.subtitles.<key>（同 auto_correct._update_meta 的寫法）。"""
    p = Path(out_dir) / "transcript.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    sub = doc.setdefault("meta", {}).get("subtitles")
    if not isinstance(sub, dict):
        sub = {}
    sub[key] = value
    doc["meta"]["subtitles"] = sub
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _checkpoint(rl, h, res: dict, which: str):
    if rl is None or h is None:
        return
    try:
        rl.end(h, status="error" if res.get("status") == "error" else "ok", file=which, result=res.get("status"),
               reason=res.get("reason"), cues=res.get("cues"), map_failed_paragraphs=res.get("map_failed_paragraphs"),
               doc_level=res.get("doc_level"))
    except Exception:  # noqa: BLE001
        pass


def _guard(out_dir: Path, which: str, rl, log, fn) -> dict:
    """執行 fn()；任何例外都變成 status: error（不丟出去），並刪掉可能過時的字幕檔。"""
    h = rl.begin("subtitles") if rl is not None else None
    name = CUES_NAME if which == "cues" else CORRECTED_NAME
    try:
        res = fn()
    except Exception as ex:  # noqa: BLE001  字幕失敗不影響轉寫與校正
        res = {"status": "error", "reason": type(ex).__name__}   # 只記例外類型（log 不記內容片段）
        try:
            (out_dir / name).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        log(f"  [!] 字幕：{name} 產生失敗（{type(ex).__name__}）；{'轉寫' if which == 'cues' else '校正'}結果不受影響")
    try:
        update_meta(out_dir, which, res)
    except Exception:  # noqa: BLE001
        pass
    _checkpoint(rl, h, res, which)
    return res


# ---------------------------------------------------------------- 對外介面
def write_cues(out_dir, cfg: dict | None = None, enabled: bool | None = None, recue_on: bool | None = None,
               run_log=None, log=None) -> dict:
    """transcript.cues.srt（規格 §5.1）。enabled：None＝照 subtitles.cues_srt；False＝--no-cues。不丟例外。"""
    out_dir, log = Path(out_dir), log or log_default
    try:
        o = options(cfg if cfg is not None else load_config(), recue=recue_on)
    except Exception:  # noqa: BLE001
        o = options({}, recue=recue_on)
    if enabled is None:
        enabled = o["cues_srt"]
    if not enabled:
        return {"status": "skipped", "reason": "disabled"}
    if not o["recue"]:                                     # 不切條時內容會與 transcript.srt 相同 → 不產生
        return {"status": "skipped", "reason": "recue_off"}

    def go():
        doc = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
        if not doc.get("segments"):
            return {"status": "skipped", "reason": "no_segments"}
        cues = recue(segment_cues(doc), o)
        _write(out_dir / CUES_NAME, render_srt(cues, o["speaker_label"]))
        st = cue_stats(cues, o)
        log(f"  字幕：{CUES_NAME} {st['cues']} 條")
        return {"status": "ok", "cues": st["cues"], "over_line": st["over_line"], "over_max_sec": st["over_max_sec"],
                "under_min_sec": st["under_min_sec"], "over_cps": st["over_cps"]}
    return _guard(out_dir, "cues", run_log, log, go)


def write_corrected(out_dir, cfg: dict | None = None, enabled: bool | None = None, uncertain: str | None = None,
                    recue_on: bool | None = None, run_log=None, log=None) -> dict:
    """transcript.corrected.srt（規格 §5.1、§5.2）。enabled：None＝照 subtitles.corrected_srt；False＝--no-corrected-srt。"""
    out_dir, log = Path(out_dir), log or log_default
    try:
        o = options(cfg if cfg is not None else load_config(), uncertain=uncertain, recue=recue_on)
    except Exception:  # noqa: BLE001
        o = options({}, uncertain=uncertain, recue=recue_on)
    if enabled is None:
        enabled = o["corrected_srt"]
    if not enabled:
        return {"status": "skipped", "reason": "disabled"}
    if not (out_dir / CORRECTED_MD).exists():
        return {"status": "skipped", "reason": "no_corrected"}

    def go():
        doc = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8"))
        if not doc.get("segments"):
            return {"status": "skipped", "reason": "no_segments"}
        cor = (out_dir / CORRECTED_MD).read_text(encoding="utf-8")
        mapped, mst = map_corrected(doc, cor, o["uncertain"])
        if o["recue"]:
            cues, label = recue(mapped, o), o["speaker_label"]
        else:                                              # 一條對一條、只換文字：講者標籤同 transcript.srt（每條都加）
            cues, label = plain_cues(mapped), ("none" if o["speaker_label"] == "none" else "always")
        _write(out_dir / CORRECTED_NAME, render_srt(cues, label))
        st = cue_stats(cues, o)
        note = ""
        if mst["map_failed"]:
            note = "（對應失敗，全部用原文）"
        elif mst["map_failed_paragraphs"]:
            note = f"（對應失敗 {mst['map_failed_paragraphs']} 段，該段用原文）"
        elif mst["doc_level"]:
            note = "（段首對不上，改用全文對應）"
        log(f"  字幕：{CORRECTED_NAME} {st['cues']} 條{note}")
        return {"status": "map_failed" if mst["map_failed"] else "ok", "cues": st["cues"],
                "paragraphs": mst["paragraphs"], "map_failed_paragraphs": mst["map_failed_paragraphs"],
                "doc_level": mst["doc_level"], "cross_segment_marks": mst["cross_segment_marks"],
                "split_in_segment": mst["split_in_segment"], "deleted_segments": mst["deleted_segments"],
                "uncertain": o["uncertain"], "recue": o["recue"],
                "over_line": st["over_line"], "over_max_sec": st["over_max_sec"],
                "under_min_sec": st["under_min_sec"], "over_cps": st["over_cps"]}
    return _guard(out_dir, "corrected", run_log, log, go)


def main():
    utf8_console()
    print_banner()
    ap = argparse.ArgumentParser(description="字幕：transcript.cues.srt（不經 AI）與 transcript.corrected.srt（校正版）")
    ap.add_argument("out_dir", help="轉寫輸出資料夾（<檔名>_minutes）")
    ap.add_argument("--cues", action="store_true", help="產生 transcript.cues.srt")
    ap.add_argument("--corrected", action="store_true", help="產生 transcript.corrected.srt（對話補校後重新產生）")
    ap.add_argument("--uncertain", choices=list(UNCERTAIN), default=None,
                    help="待確認標記的顯示：orig 原文（預設）、guess 推測、mark 原文〔?推測〕")
    ap.add_argument("--no-recue", action="store_true", help="不重新切條（transcript.corrected.srt 與 transcript.srt 一條對一條）")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    if not (out_dir / "transcript.json").exists():
        log_default(f"[!] 找不到 {out_dir / 'transcript.json'}")
        sys.exit(2)
    both = not args.cues and not args.corrected
    cfg = load_config()
    import runlog
    rl = runlog.RunLog(out_dir, step="subtitles")
    rl.info_from_transcript()
    recue_on = False if args.no_recue else None
    res = {}
    if args.cues or both:                                  # 明確要求就產生（不看 subtitles.cues_srt）
        res["cues"] = write_cues(out_dir, cfg, enabled=True, recue_on=recue_on, run_log=rl)
    if args.corrected or both:
        res["corrected"] = write_corrected(out_dir, cfg, enabled=True, uncertain=args.uncertain, recue_on=recue_on,
                                           run_log=rl)
    if rl.owns:
        rl.finish()
    print(json.dumps({"subtitles": res}, ensure_ascii=False))
    sys.exit(1 if any(r.get("status") == "error" for r in res.values()) else 0)


if __name__ == "__main__":
    main()
