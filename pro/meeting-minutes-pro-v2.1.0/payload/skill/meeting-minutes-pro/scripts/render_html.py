"""〔2.1.0〕會議記錄／筆記的網頁版（規格 meeting-minutes-pro-v2.1.0-spec.md）：把 meeting-minutes.md／notes.md 轉成
單一檔案、完全離線的 HTML（左側目錄、scrollspy、深淺主題、會議摘要卡、時間碼點了播放原始錄音或影片）。

本機程式轉換，**不呼叫任何模型**（不 import auto_minutes／auto_correct 等會呼叫模型的模組）；只用標準函式庫，
Claude App 沙盒沒有 runtime 的其他檔案時也能執行（common.py、runlog.py 找不到就用檔內的預設值、不寫 log）。

  python render_html.py <輸出資料夾>                       有 meeting-minutes.md 就轉它，否則 notes.md
  python render_html.py <輸出資料夾> --file notes.md       指定輸出資料夾內的 .md
  python render_html.py --md <檔案>.md [--out <檔案>.html]  單獨一份 .md（不讀 transcript.json、不找媒體、不寫 log）
  共用旗標：--media <檔案> | --no-media、--theme dark|light

exit code：0 產生成功；2 跳過（找不到 .md、參數錯誤）；1 失敗。stdout 最後一行 {"html": {…}}。
auto_minutes.py 寫完 .md 後呼叫 render()（不丟例外；失敗不影響 .md 與 exit code）。
"""
import argparse
import base64
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
TEMPLATE_NAME = "html_template.html"
FALLBACK_VERSION = "2.1.0"          # Claude App 沙盒沒有 common.py 時的版號（tools/make_dist.py 檢查與 common.VERSION 一致）
FALLBACK_HTML = {"enabled": True, "media": "auto", "theme": "dark"}
FALLBACK_CHOICES = {"enabled": (True, False), "media": ("auto", "off"), "theme": ("dark", "light")}

try:                                 # runtime 內：版號、設定、log 都用共用模組
    import common as _common
    VERSION = _common.VERSION
except Exception:  # noqa: BLE001  沙盒：只有本檔與樣板
    _common = None
    VERSION = FALLBACK_VERSION

MEETING_MD, NOTES_MD = "meeting-minutes.md", "notes.md"

# 規格 §5.3：副檔名 → 元素（小寫比對）
AUDIO_EXT = (".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".weba")
VIDEO_EXT = (".mp4", ".m4v", ".webm", ".mov")
MEDIA_EXT = AUDIO_EXT + VIDEO_EXT
UNPLAYABLE_EXT = (".wma", ".wmv", ".avi", ".mkv", ".flv", ".amr", ".3gp", ".aif", ".aiff", ".mpg", ".mpeg", ".ts",
                  ".mts", ".m2ts", ".ape", ".ac3")

TC_RE = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d):([0-5]\d)(?![\d:])")
# 行內：`code`｜**粗體**｜圖片 ![…](…)（照原文跳脫，不做成連結）｜[文字](連結)
INLINE_RE = re.compile(r"(`[^`\n]+`)|(\*\*[^*\n]+?\*\*)|(!\[[^\]\n]*\]\([^)\s]*\))|(\[[^\]\n]+\]\([^)\s]+\))")
LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
NUM_H2 = re.compile(r"^([一二三四五六七八九十百]+)、\s*(.+)$|^(\d+)\.\s+(.+)$")
TAIL_TC = re.compile(r"[\s　]*`?\[\d{1,2}:\d{2}:\d{2}\]`?\s*$")
SLUG_DROP = re.compile(r"[\s\"'<>&#%{}|\\^`\[\]/?;:@=+$,!*().（）「」『』、。，：；？！／〔〕【】·・]+")
DETAILS_OPEN = re.compile(r"^<details><summary>([^<>]{1,80})</summary>$")
LIST_RE = re.compile(r"^\s*([-*]|\d+\.)\s+")
HR_RE = re.compile(r"^\s*(-{3,}|\*{3,})\s*$")
TAG_RE = re.compile(r"<[a-zA-Z/!]")
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z]+)\}\}")

REASONS = ("disabled", "no_md", "template_missing", "write_failed", "internal_error")


def esc(s) -> str:
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- 設定
def html_setting(cfg: dict | None, key: str):
    """html.<key>：有 common.py 時用 common.html_setting()（不認得的值改用預設並印提示）；沙盒用檔內預設值。"""
    if _common is not None and hasattr(_common, "html_setting"):
        return _common.html_setting(cfg or {}, key)
    v = ((cfg or {}).get("html") or {}).get(key, FALLBACK_HTML[key])
    ok = isinstance(v, bool) if key == "enabled" else v in FALLBACK_CHOICES[key]
    if not ok:
        print(f"[!] html.{key} 的值 {v} 不認得，改用 {FALLBACK_HTML[key]}", file=sys.stderr, flush=True)
        return FALLBACK_HTML[key]
    return v


def load_cfg() -> dict:
    if _common is None:
        return {}
    try:
        return _common.load_config()
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- 轉換狀態
class Ctx:
    def __init__(self, max_sec, media):
        self.max_sec = max_sec          # None＝不限（--md 模式、沒有 transcript.json）
        self.media = media              # None＝沒有播放器
        self.timecodes = 0
        self.out_of_range = 0
        self.escaped_html = 0
        self.headings = 0
        self.ids = set()
        self.tc_off = False             # 頁首：時間值不做成時間碼（規格 §4.3、§5.1）

    def slug(self, text: str) -> str:
        """規格 §3.4：h- ＋ slug(標題)；同一頁重複時依序加 -2、-3。"""
        t = TAIL_TC.sub("", text)
        t = unicodedata.normalize("NFKC", t)
        t = re.sub(r"[`*]", "", t).lower()
        t = SLUG_DROP.sub("-", t).strip("-")[:60] or "sec"
        base = "h-" + t
        sid, n = base, 1
        while sid in self.ids:
            n += 1
            sid = f"{base}-{n}"
        self.ids.add(sid)
        self.headings += 1
        return sid


# ---------------------------------------------------------------- 行內
def tc_html(ctx: Ctx, text: str) -> str:
    """已跳脫的文字裡把 HH:MM:SS 換成時間碼（規格 §5.1）。"""
    if ctx.tc_off:
        return text

    def sub(m):
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3))
        sec = h * 3600 + mi * 60 + se
        if ctx.max_sec is not None and sec > ctx.max_sec + 60:
            ctx.out_of_range += 1
            return m.group(0)
        ctx.timecodes += 1
        label = f"{h:02d}:{mi:02d}:{se:02d}"
        iso = f"PT{h}H{mi}M{se}S"
        if ctx.media:
            return (f'<button type="button" class="tc" data-t="{sec}" aria-label="從 {label} 播放">'
                    f'<time datetime="{iso}">{label}</time></button>')
        return f'<time class="tc-text" datetime="{iso}">{label}</time>'
    return TC_RE.sub(sub, text)


def esc_count(ctx: Ctx, s: str) -> str:
    ctx.escaped_html += len(TAG_RE.findall(s))
    return esc(s)


def text_html(ctx: Ctx, s: str) -> str:
    return tc_html(ctx, esc_count(ctx, s))


def inline(ctx: Ctx, s: str) -> str:
    """規格 §3.2 行內子集：`code`（內容是 [HH:MM:SS] 時當時間碼）、**粗體**、[文字](連結)；其餘跳脫後當文字。"""
    out, pos = [], 0
    for m in INLINE_RE.finditer(s):
        out.append(text_html(ctx, s[pos:m.start()]))
        tok = m.group(0)
        if m.group(1):
            inner = tok[1:-1]
            bare = inner.strip()
            if bare.startswith("[") and bare.endswith("]"):
                bare = bare[1:-1]
            if TC_RE.fullmatch(bare) and not ctx.tc_off:
                out.append(tc_html(ctx, esc(bare)))
            elif TC_RE.fullmatch(bare):
                out.append(f"<code>{esc(inner)}</code>")
            else:
                out.append(f"<code>{esc_count(ctx, inner)}</code>")
        elif m.group(2):
            out.append("<strong>" + text_html(ctx, tok[2:-2]) + "</strong>")
        elif m.group(3):
            out.append(esc_count(ctx, tok))
        else:
            text, href = LINK_RE.match(tok).groups()
            out.append(link(ctx, text, href))
        pos = m.end()
    out.append(text_html(ctx, s[pos:]))
    return "".join(out)


def link(ctx: Ctx, text: str, href: str) -> str:
    """規格 §3.2：#錨點與相對路徑做成連結；有 scheme（http:、mailto:、javascript: …）或 // 開頭的寫成純文字。"""
    h = href.strip()
    if h.startswith("#") or (not SCHEME_RE.match(h) and not h.startswith("//") and not h.startswith("\\")):
        return f'<a href="{esc(h)}">{esc_count(ctx, text)}</a>'
    return f'{esc_count(ctx, text)}（<span class="url">{esc_count(ctx, h)}</span>）'


def plain(s: str) -> str:
    """目錄與 <title> 用的純文字：去掉行內標記（`、**、連結只留文字）。"""
    s = LINK_RE.sub(lambda m: m.group(1), s)
    s = re.sub(r"\*\*([^*\n]+?)\*\*", r"\1", s)
    return s.replace("`", "")


# ---------------------------------------------------------------- 區塊
def split_row(line: str) -> list:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", line.strip()))


def block_start(ln: str) -> bool:
    s = ln.strip()
    return (bool(re.match(r"^(#{1,6}\s|>|```)", s)) or s.startswith("|") or bool(LIST_RE.match(ln))
            or bool(DETAILS_OPEN.match(s)) or s == "</details>" or bool(HR_RE.match(s)))


def parse(md: str) -> list:
    """Markdown → 區塊清單 [(kind, data)]。kind：h1 h2 h3 h4 p quote table ul hr code details_open details_close。
    不完整的寫法不丟例外：沒有分隔列的 | 行當段落、程式碼區塊沒有結尾時到文末為止。"""
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            lang, buf = s[3:].strip(), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            blocks.append(("code", (lang, "\n".join(buf))))
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            blocks.append((f"h{min(len(m.group(1)), 4)}", m.group(2).strip()))
            i += 1
            continue
        if DETAILS_OPEN.match(s):
            blocks.append(("details_open", DETAILS_OPEN.match(s).group(1)))
            i += 1
            continue
        if s == "</details>":
            blocks.append(("details_close", None))
            i += 1
            continue
        if HR_RE.match(s):
            blocks.append(("hr", None))
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and is_sep(lines[i + 1]):
            rows = [split_row(ln)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            blocks.append(("table", rows))
            continue
        if s.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append(("quote", buf))
            continue
        if LIST_RE.match(ln):
            items = []
            while i < len(lines) and LIST_RE.match(lines[i]):
                ind = len(lines[i]) - len(lines[i].lstrip())
                items.append((1 if ind >= 2 else 0, LIST_RE.sub("", lines[i], count=1).strip()))
                i += 1
            blocks.append(("ul", items))
            continue
        buf = [s]
        i += 1
        while i < len(lines) and lines[i].strip() and not block_start(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


def table_html(ctx: Ctx, rows: list) -> str:
    head, body = rows[0], rows[1:]
    tc_col = {i for i, h in enumerate(head) if h == "時間碼"}
    row_head = bool(head) and head[0] in ("#", "項目")
    th = "".join(f'<th scope="col"{" class=\"num\"" if i in tc_col else ""}>{inline(ctx, h)}</th>'
                 for i, h in enumerate(head))
    trs = []
    for r in body:
        r = (r + [""] * len(head))[:len(head)]
        cells = []
        for i, c in enumerate(r):
            cls = ' class="num"' if i in tc_col else ""
            if i == 0 and row_head:
                cells.append(f'<th scope="row"{cls}>{inline(ctx, c)}</th>')
            else:
                cells.append(f"<td{cls}>{inline(ctx, c)}</td>")
        trs.append("<tr>" + "".join(cells) + "</tr>")
    cls = "tbl wide" if len(head) >= 5 else "tbl"
    return f'<div class="{cls}"><table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table></div>'


def ul_html(ctx: Ctx, items: list) -> str:
    out, open_sub = ["<ul>"], False
    for lvl, text in items:
        if lvl == 1 and not open_sub:
            if out[-1].endswith("</li>"):
                out[-1] = out[-1][:-len("</li>")]
            else:
                out.append("<li>")
            out.append("<ul>")
            open_sub = True
        elif lvl == 0 and open_sub:
            out.append("</ul></li>")
            open_sub = False
        out.append(f"<li>{inline(ctx, text)}</li>")
    if open_sub:
        out.append("</ul></li>")
    out.append("</ul>")
    return "".join(out)


def code_html(lang: str, code: str) -> str:
    label = "Mermaid 圖的原始碼（網頁版離線顯示，不畫圖）" if lang.lower() == "mermaid" else "程式碼"
    return (f'<pre class="code" role="region" tabindex="0" aria-label="{esc(label)}"><code>'
            f"{esc(code)}</code></pre>")


def table_key(hdr: list) -> str | None:
    """規格 §4.4：依表頭判斷決議／待辦／待釐清表（不看節標題）。"""
    if len(hdr) > 1 and hdr[1] == "決議":
        return "decisions"
    if len(hdr) > 2 and hdr[1] == "事項" and hdr[2] == "負責人":
        return "actions"
    if len(hdr) > 1 and hdr[1].startswith("問題"):
        return "questions"
    return None


def h2_parts(text: str) -> tuple:
    t = TAIL_TC.sub("", text)
    m = NUM_H2.match(t)
    if m:
        return (m.group(1) or m.group(3)), (m.group(2) or m.group(4))
    return "", t


# ---------------------------------------------------------------- 頁面
def build_page(md: str, src_name: str, ctx: Ctx, kind: str, media_note: str | None) -> dict:
    blocks = parse(md)
    # 第一個 # 是標題；第二個以後的 # 當成 ##（規格 §3.2）
    title, seen_h1, norm = None, False, []
    for k, d in blocks:
        if k == "h1":
            if not seen_h1:
                seen_h1, title = True, d
                norm.append((k, d))
                continue
            k = "h2"
        norm.append((k, d))
    blocks = norm
    title = title or Path(src_name).stem
    first = next((n for n, b in enumerate(blocks) if b[0] in ("h2", "details_open")), len(blocks))
    head_blocks, body_blocks = blocks[:first], blocks[first:]

    # 頁首（規格 §3.3、§4.3）：時間值一律不做成時間碼
    ctx.tc_off = True
    status, warns, meta_rows, intro = None, [], [], []
    for k, d in head_blocks:
        if k == "h1":
            continue
        if k == "quote":
            for q in d:
                if q.startswith("自動整理後經對話確認："):
                    status = ("ok", "自動整理後經對話確認", q)
                elif q.startswith("自動整理："):
                    status = ("warn", "自動整理｜未經人工確認", q)
                elif q.strip():
                    warns.append(q)
        elif k == "table" and not meta_rows and d and d[0][:2] == ["項目", "內容"]:
            meta_rows = [r for r in d[1:] if len(r) >= 2]
        else:
            intro.append((k, d))
    mh = [f'<p class="eyebrow">meeting-minutes-pro · {"會議記錄" if kind == "meeting" else "筆記"}</p>',
          f"<h1>{inline(ctx, title)}</h1>"]
    if status:
        cls, label, line = status
        mh.append(f'<p class="status {cls}"><span class="badge">{esc(label)}</span>'
                  f'<span class="status-line">{inline(ctx, line)}</span></p>')
    if meta_rows:
        mh.append('<dl class="meta">' + "".join(f"<div><dt>{inline(ctx, r[0])}</dt><dd>{inline(ctx, r[1])}</dd></div>"
                                               for r in meta_rows) + "</dl>")
    for w in warns:
        mh.append(f'<p class="callout">{inline(ctx, w)}</p>')
    if media_note:
        mh.append(f'<p class="callout">{esc(media_note)}</p>')
    for k, d in intro:
        mh.append(block_html(ctx, k, d))
    ctx.tc_off = False

    # 正文
    toc, sections, cur = [], [], None
    counts = {}
    state = {"section": False, "details": False}

    def close_details():
        if state["details"]:
            sections.append("</div></details>")
            state["details"] = False

    def close_section():
        close_details()
        if state["section"]:
            sections.append("</section>")
            state["section"] = False

    for k, d in body_blocks:
        if k == "h2":
            close_section()
            sid = ctx.slug(d)
            no, label = h2_parts(d)
            toc.append({"id": sid, "no": no, "label": plain(label), "subs": []})
            cur = toc[-1]
            no_html = f'<span class="no">{esc(no)}</span>' if no else ""
            tail = TAIL_TC.search(d)
            sections.append(f'<section id="{sid}"><header><h2>{no_html}<span>{inline(ctx, label)}</span>'
                            + (f" {inline(ctx, tail.group(0).strip())}" if tail else "") + "</h2></header>")
            state["section"] = True
        elif k == "h3":
            sid = ctx.slug(d)
            if cur is not None:
                cur["subs"].append({"id": sid, "label": plain(TAIL_TC.sub("", d))})
            sections.append(f'<h3 id="{sid}">{inline(ctx, d)}</h3>')
        elif k == "details_open":
            close_section()
            sid = ctx.slug(d)
            toc.append({"id": sid, "no": "", "label": d, "subs": []})
            cur = toc[-1]
            sections.append(f'<details class="quality" id="{sid}"><summary>{esc(d)}</summary><div class="quality-body">')
            state["details"] = True
        elif k == "details_close":
            close_details()
        else:
            if k == "table" and cur is not None:
                key = table_key(d[0])
                if key and key not in counts:
                    counts[key] = {"n": sum(1 for r in d[1:] if r and r[0].strip() not in ("—", "-", "")), "id": cur["id"]}
            sections.append(block_html(ctx, k, d))
    close_section()

    if kind == "meeting" and counts:
        names = {"decisions": "決議", "actions": "待辦", "questions": "待釐清問題"}
        cards = [f'<a class="count" href="#{counts[k]["id"]}"><span class="count-n">{counts[k]["n"]}</span>'
                 f'<span class="count-l">{names[k]}</span></a>' for k in ("decisions", "actions", "questions") if k in counts]
        mh.append('<nav class="counts" aria-label="摘要">' + "".join(cards) + "</nav>")

    toc_html = []
    for t in toc:
        no = (f'<span class="no">{esc(t["no"])}</span>' if t["no"]
              else '<span class="no" aria-hidden="true">·</span>')
        sub = ""
        if t["subs"]:
            sub = '<ul class="toc-sub">' + "".join(f'<li><a href="#{s["id"]}">{esc(s["label"])}</a></li>'
                                                     for s in t["subs"]) + "</ul>"
        toc_html.append(f'<li><a href="#{t["id"]}">{no}<span class="toc-label">{esc(t["label"])}</span></a>{sub}</li>')
    return {"title": plain(title), "toc": "\n".join(toc_html), "masthead": "\n".join(mh), "body": "\n".join(sections),
            "counts": counts, "toc_items": toc}


def block_html(ctx: Ctx, k: str, d) -> str:
    if k == "h4":
        return f"<h4>{inline(ctx, d)}</h4>"
    if k in ("h2", "h3"):            # 頁首裡不會有（頁首在第一個 ## 之前）；保險起見當成 h4
        return f"<h4>{inline(ctx, d)}</h4>"
    if k == "p":
        return f'<p class="prose">{inline(ctx, d)}</p>'
    if k == "quote":
        return '<div class="callout">' + "".join(f"<p>{inline(ctx, q)}</p>" for q in d if q) + "</div>"
    if k == "ul":
        return f'<div class="prose">{ul_html(ctx, d)}</div>'
    if k == "table":
        return table_html(ctx, d)
    if k == "code":
        return code_html(*d)
    return ""                        # hr、孤立的 </details>：不輸出


def player_html(media: dict) -> str:
    video = media["kind"] == "video"
    what = "影片" if video else "錄音"
    tag = "video" if video else "audio"
    btns = ""
    if video:
        btns = ('<span class="dock-btns">'
                '<button type="button" class="dock-btn dock-play" hidden>播放</button>'
                '<button type="button" class="dock-btn dock-full" hidden>全螢幕</button>'
                '<button type="button" class="dock-btn dock-fold" aria-expanded="true" hidden>收合影片</button></span>')
    return (f'<aside class="dock dock-{media["kind"]}" id="dock" aria-label="原始{what}">'
            f'<div class="dock-head"><span class="dock-title">原始{what}：<span class="mono">{esc(media["name"])}</span></span>'
            f'<span class="dock-status" role="status" aria-live="polite"></span>{btns}</div>'
            f'<div class="dock-media"><{tag} id="media" controls preload="metadata" playsinline src="{esc(media["src"])}"></{tag}></div>'
            "</aside>")


# ---------------------------------------------------------------- 媒體定位（規格 §5.2）
def glob_ci(s: str) -> str:
    return "".join(f"[{c.lower()}{c.upper()}]" if c.isascii() and c.isalpha() else re.sub(r"([\[\]*?])", r"[\1]", c)
                   for c in s)


def find_media(out_dir: Path, meta: dict) -> dict:
    """① <輸出資料夾>/../<meta.source> ② <輸出資料夾>/<meta.source> ③ <名稱>_minutes → ../<名稱>.<副檔名>（依 §5.3 表的順序）。
    取第一個瀏覽器能播的；都不能播但有認得的媒體 → unsupported；什麼都沒有 → none。"""
    cands = []
    src = meta.get("source")
    if isinstance(src, str) and src and "/" not in src and "\\" not in src and src not in (".", ".."):
        cands += [out_dir.parent / src, out_dir / src]
    if out_dir.name.endswith("_minutes") and len(out_dir.name) > len("_minutes"):
        stem = out_dir.name[: -len("_minutes")]
        for ext in MEDIA_EXT + UNPLAYABLE_EXT:
            try:
                cands += sorted(out_dir.parent.glob(glob_ci(stem) + glob_ci(ext)))
            except Exception:  # noqa: BLE001
                pass
    files = []
    for p in cands:
        try:
            if p.is_file() and p.suffix.lower() in MEDIA_EXT + UNPLAYABLE_EXT and p not in files:
                files.append(p)
        except OSError:
            pass
    for p in files:
        if p.suffix.lower() in MEDIA_EXT:
            return {"status": "found", "path": p, "ext": p.suffix.lower()}
    for p in files:
        return {"status": "unsupported", "ext": p.suffix.lower()}
    return {"status": "none", "ext": None}


def rel_url(target: Path, base_dir: Path) -> str | None:
    """網頁版所在資料夾 → 媒體的相對路徑（/ 分隔、每段 percent-encoding）。不同磁碟（沒有相對路徑）回傳 None。"""
    try:
        rel = os.path.relpath(Path(target).resolve(), Path(base_dir).resolve())
    except ValueError:
        return None
    return "/".join(quote(seg) for seg in rel.replace("\\", "/").split("/"))


def unsupported_note(ext: str) -> str:
    return f"原始檔格式 {ext} 瀏覽器多半不能播放，時間碼以文字顯示。"


# ---------------------------------------------------------------- 寫檔
def b64sha(s: str) -> str:
    return base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()


def csp_for(tpl: str) -> str:
    """規格 §8.1：style／script 只放行樣板那一段（雜湊＝標籤之間的完整內容）。"""
    style = re.search(r"<style>(.*?)</style>", tpl, re.S).group(1)
    script = re.search(r"<script>(.*?)</script>", tpl, re.S).group(1)
    return ("default-src 'none'; "
            f"style-src 'sha256-{b64sha(style)}'; script-src 'sha256-{b64sha(script)}'; "
            "media-src 'self' file:; img-src 'none'; base-uri 'none'; form-action 'none'")


def write_atomic(path: Path, text: str):
    """暫存檔＋os.replace()：寫到一半失敗不會留下半個 .html。UTF-8（不加 BOM）、換行 \\n。"""
    fd, tmp = tempfile.mkstemp(prefix=".~" + path.stem + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def template_path() -> Path:
    return HERE / TEMPLATE_NAME


def _read_meta(out_dir: Path) -> dict:
    try:
        meta = json.loads((out_dir / "transcript.json").read_text(encoding="utf-8")).get("meta") or {}
        return meta if isinstance(meta, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def build(md_path: Path, out_html: Path, out_dir: Path | None, media_opt, theme: str) -> dict:
    """產生網頁版（會丟例外；render() 負責接住）。media_opt：'auto'｜'off'｜Path（--media）。"""
    md = md_path.read_text(encoding="utf-8-sig")
    meta = _read_meta(out_dir) if out_dir is not None else {}
    try:
        dur = float(meta.get("duration") or 0) or None
    except (TypeError, ValueError):
        dur = None
    media, media_status, media_ext, note = None, "none", None, None
    html_dir = out_html.parent
    if media_opt == "off":
        media_status = "off"
    elif isinstance(media_opt, Path):
        media_status, media_ext = "explicit", media_opt.suffix.lower()
        if media_ext not in MEDIA_EXT:
            media_status, note = "unsupported", unsupported_note(media_ext or "（沒有副檔名）")
        else:
            src = rel_url(media_opt, html_dir)
            if src is None:
                media_status, note = "none", "原始媒體與網頁版不在同一個磁碟，無法用相對路徑播放，時間碼以文字顯示。"
            else:
                media = {"kind": "video" if media_ext in VIDEO_EXT else "audio", "src": src, "name": media_opt.name}
    elif out_dir is not None:
        f = find_media(out_dir, meta)
        media_status, media_ext = f["status"], f["ext"]
        if f["status"] == "found":
            src = rel_url(f["path"], html_dir)
            if src is None:
                media_status, note = "none", "原始媒體與網頁版不在同一個磁碟，無法用相對路徑播放，時間碼以文字顯示。"
            else:
                media = {"kind": "video" if media_ext in VIDEO_EXT else "audio", "src": src, "name": f["path"].name}
        elif f["status"] == "unsupported":
            note = unsupported_note(media_ext)
    ctx = Ctx(dur if out_dir is not None else None, media)
    first_line = md.lstrip().split("\n", 1)[0].strip()
    kind = "meeting" if md_path.name == MEETING_MD or (first_line.startswith("# ") and first_line.endswith(" 會議記錄")) \
        else "notes"
    page = build_page(md, md_path.name, ctx, kind, note)
    tpl = template_path().read_text(encoding="utf-8")
    gen = datetime.now().astimezone().isoformat(timespec="seconds")
    name = esc(md_path.name)
    values = {
        "CSP": esc(csp_for(tpl)), "THEME": "light" if theme == "light" else "dark", "TITLE": esc(page["title"]),
        "TOC": page["toc"], "MASTHEAD": page["masthead"], "BODY": page["body"],
        "PLAYER": player_html(media) if media else "",
        "FOOTER": (f"由 meeting-minutes-pro {esc(VERSION)} 從 <code>{name}</code> 產生於 {esc(gen)}。"
                   f"內容以 {name} 為準；改過 .md 之後請重新產生網頁版。"),
    }
    text = PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), tpl)   # 一次替換（§4.1）
    write_atomic(out_html, text)
    return {"status": "ok", "reason": None, "source": md_path.name, "output": out_html.name,
            "bytes": len(text.encode("utf-8")), "headings": ctx.headings, "timecodes": ctx.timecodes,
            "timecodes_out_of_range": ctx.out_of_range, "media": media_status,
            "media_ext": media_ext if media_status in ("found", "explicit", "unsupported") else None,
            "escaped_html": ctx.escaped_html}


def _result(status, reason=None, **kw) -> dict:
    r = {"status": status, "reason": reason, "source": None, "output": None, "bytes": None, "headings": None,
         "timecodes": None, "timecodes_out_of_range": None, "media": None, "media_ext": None, "escaped_html": None}
    r.update(kw)
    return r


def default_md(out_dir: Path) -> str:
    return MEETING_MD if (out_dir / MEETING_MD).exists() else NOTES_MD


def render(out_dir=None, md_name: str | None = None, cfg: dict | None = None, run_log=None, media=None,
           theme: str | None = None, md_path=None, out_path=None, checkpoint: str = "minutes.html") -> dict:
    """產生網頁版。**不丟例外**：回傳 {"status": ok|failed|skipped, "reason", "source", "output", "bytes", "headings",
    "timecodes", "timecodes_out_of_range", "media", "media_ext", "escaped_html", "duration_ms"}。

    out_dir＋md_name：輸出資料夾內的 .md（md_name 預設 meeting-minutes.md，沒有就 notes.md）。
    md_path（＋out_path）：單獨一份 .md（不讀 transcript.json、不找媒體、時間碼不限範圍）。
    media：None＝依 html.media（auto／off）；'off'；或媒體檔路徑（--media）。theme：None＝依 html.theme。
    run_log：runlog.RunLog；有給時寫 checkpoint（auto_minutes 內是 minutes.html，單獨執行是 html）。不記內容、標題、媒體檔名與路徑。
    """
    t0 = time.perf_counter()
    started = datetime.now().astimezone()
    try:
        r = _render(out_dir, md_name, cfg, media, theme, md_path, out_path)
    except Exception as ex:  # noqa: BLE001  理論上 _render 已接住；保險
        r = _result("failed", "internal_error", error=type(ex).__name__)
    r["duration_ms"] = int((time.perf_counter() - t0) * 1000)
    if run_log is not None:
        try:
            fields = {k: r.get(k) for k in ("status", "reason", "source", "output", "bytes", "headings", "timecodes",
                                            "timecodes_out_of_range", "media", "media_ext", "escaped_html",
                                            "duration_ms", "error")}
            ended = datetime.now().astimezone()
            run_log.event("checkpoint", name=checkpoint, started_at=started.isoformat(timespec="milliseconds"),
                          ended_at=ended.isoformat(timespec="milliseconds"),
                          duration_sec=round(time.perf_counter() - t0, 3), **fields)
        except Exception:  # noqa: BLE001
            pass
    return r


def _render(out_dir, md_name, cfg, media, theme, md_path, out_path) -> dict:
    cfg = load_cfg() if cfg is None else cfg
    try:
        if md_path is not None:
            md_p = Path(md_path)
            od = None
        else:
            od = Path(out_dir)
            md_p = od / (md_name or default_md(od))
        if not md_p.is_file():
            return _result("skipped", "no_md", source=md_p.name)
        out_html = Path(out_path) if out_path is not None else md_p.with_suffix(".html")
        if not template_path().is_file():
            return _result("failed", "template_missing", source=md_p.name)
        if media is None:
            media_opt = html_setting(cfg, "media")
        elif media == "off":
            media_opt = "off"
        else:
            media_opt = Path(media)
        if od is None and media_opt == "auto":
            media_opt = None          # --md：不找媒體
        th = theme if theme in ("dark", "light") else html_setting(cfg, "theme")
        try:
            return build(md_p, out_html, od, media_opt, th)
        except OSError as ex:          # 寫檔失敗（含權限、唯讀資料夾）
            return _result("failed", "write_failed", source=md_p.name, output=out_html.name, error=type(ex).__name__)
    except Exception as ex:  # noqa: BLE001
        return _result("failed", "internal_error", error=type(ex).__name__)


# ---------------------------------------------------------------- 命令列
def main(argv=None) -> int:
    try:
        if _common is not None:
            _common.utf8_console()
        else:
            for s in (sys.stdout, sys.stderr):
                s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="會議記錄／筆記的網頁版（不呼叫模型）：.md → 單一檔案、離線的 .html")
    ap.add_argument("out_dir", nargs="?", help="輸出資料夾（<檔名>_minutes）")
    ap.add_argument("--file", default=None, help="輸出資料夾內的 .md 檔名（預設 meeting-minutes.md，沒有就 notes.md）")
    ap.add_argument("--md", default=None, help="單獨一份 .md（與 <輸出資料夾> 互斥）")
    ap.add_argument("--out", default=None, help="--md 模式的輸出 .html（預設同名 .html）")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--media", default=None, help="指定原始媒體（跳過自動尋找）")
    g.add_argument("--no-media", action="store_true", help="不放播放器（時間碼一律文字）")
    ap.add_argument("--theme", choices=["dark", "light"], default=None, help="本次的預設主題（預設 html.theme）")

    def skip(reason, msg):
        print(f"[!] {msg}", file=sys.stderr, flush=True)
        print(json.dumps({"html": _result("skipped", reason)}, ensure_ascii=False))
        return 2

    try:
        a = ap.parse_args(argv)
    except SystemExit as ex:
        if ex.code in (0, None):
            return 0
        print(json.dumps({"html": _result("skipped", "bad_option")}, ensure_ascii=False))
        return 2
    if bool(a.md) == bool(a.out_dir):
        return skip("bad_option", "請給輸出資料夾，或用 --md 指定一份 .md（兩者擇一）")
    if a.out and not a.md:
        return skip("bad_option", "--out 只能和 --md 一起用（輸出資料夾模式的網頁版固定放在 .md 旁邊）")
    if a.file and a.md:
        return skip("bad_option", "--file 只能和輸出資料夾一起用")
    if a.file and (("/" in a.file) or ("\\" in a.file) or a.file in (".", "..") or not a.file.lower().endswith(".md")):
        return skip("bad_option", "--file 只能是輸出資料夾內的 .md 檔名（不得含路徑）")
    if a.media and not Path(a.media).is_file():
        return skip("no_media", f"找不到 --media 指定的檔案：{Path(a.media).name}")
    media = "off" if a.no_media else (a.media or None)
    rl = None
    if a.md:
        r = render(md_path=a.md, out_path=a.out, media=media, theme=a.theme)
    else:
        od = Path(a.out_dir)
        if not od.is_dir():
            return skip("no_md", f"找不到輸出資料夾：{od.name}")
        try:
            import runlog
            rl = runlog.RunLog(od, step="html")     # 不寫 info 事件：它帶原始檔名（＝媒體檔名，規格 §6.4 不記）
        except Exception:  # noqa: BLE001  沙盒沒有 runlog：不寫 log
            rl = None
        r = render(od, a.file, run_log=rl, media=media, theme=a.theme, checkpoint="html")
        if rl is not None:
            try:
                rl.event("result", status=r["status"], reason=r["reason"], output=r["output"])
                if rl.owns:
                    rl.finish()
            except Exception:  # noqa: BLE001
                pass
    if r["status"] == "ok":
        print(f"已產生 {r['output']}（標題 {r['headings']}、時間碼 {r['timecodes']}、媒體 {r['media']}）",
              file=sys.stderr, flush=True)
    elif r["reason"] == "no_md":
        print("[!] 找不到 meeting-minutes.md 或 notes.md", file=sys.stderr, flush=True)
    else:
        print(f"[!] 網頁版未產生（{r['reason']}）", file=sys.stderr, flush=True)
    print(json.dumps({"html": r}, ensure_ascii=False))
    return 0 if r["status"] == "ok" else (2 if r["status"] == "skipped" else 1)


if __name__ == "__main__":
    sys.exit(main())
