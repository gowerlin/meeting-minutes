"""〔2.2.0〕參考資料（規格 2.2.0 §2、§3、§5、§6）：背景說明、會議文件、影片截圖。

- 找說明檔與文件（§2）、本機抽文字（§5.1～§5.3）、挑名詞與段落（§5.4）、挑截圖與縮圖（§3.2、§3.3）、
  講者對應（§3.5）、讀寫 reference.json（§2.5）、組提示詞段落（§6）。
- **不呼叫模型**；送截圖的「參考資料整理」呼叫（correct.refs）在 auto_correct.py。
- 不丟例外：每個來源各自記失敗原因（reason 代碼），任何未預期的例外記 internal_error 後當作沒有該來源。
- 只讀使用者放的檔；寫入只有輸出資料夾的 context.md、reference.json（§9.3）。縮圖寫在呼叫端給的暫存資料夾。

工具指令（不呼叫模型）：
  python refs.py plan <檔名>_minutes [--media <原始檔>]   # 會用到的說明檔、文件、截圖張數（JSON 一行；入口與 SKILL 用）
  python refs.py show <檔名>_minutes                     # reference.json 的摘要（與會者、名詞數、讀不到的文件）
"""
import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import VERSION, load_config, reference_setting, utf8_console  # noqa: E402

REFERENCE_NAME = "reference.json"
CONTEXT_NAME = "context.md"
CONTEXT_MAX = 2000                 # 說明檔＋context.md 合計（§2.1、§2.2）
LINE_MAX = 300                     # 入口一行描述（§2.2）
PARTICIPANTS_MAX = 50              # §6.5
DOC_EXT = (".pdf", ".pptx", ".docx", ".txt", ".md")
MEDIA_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg", ".ts", ".3gp",
             ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr"}
DOC_TIMEOUT = 30                   # 每份文件的抽取逾時（秒，§5.2）
DOC_MAX_CHARS = 200_000            # 每份文件抽出的文字上限（§5.2）
ZIP_XML_MAX = 20 * 1024 * 1024     # DOCX／PPTX 裡單一 XML 的大小上限（§5.2）
ZIP_TOTAL_MAX = 100 * 1024 * 1024  # DOCX／PPTX 整份解壓合計上限
PARA_MIN, PARA_MAX, PARA_SCORE_MIN = 8, 400, 0.15     # §5.4
MIN_STD, DHASH_N, DHASH_DIST = 6.0, 16, 8             # §3.2
IMAGE_MAX_BYTES = 5 * 1024 * 1024  # 單張圖上限（§4.5）
FFMPEG_TIMEOUT = 30
STOPWORDS = {"the", "and", "for", "with", "from", "this", "that", "are", "was", "were", "will", "you", "your", "our",
             "has", "have", "had", "not", "but", "all", "any", "can", "may", "its", "into", "than", "then", "also",
             "page", "slide", "note", "notes", "item", "items", "total", "date", "time", "name", "type", "value"}
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_./+][A-Za-z0-9]+)*")
CJK_QUOTE = re.compile(r"[「『]([^」』\n]{2,20})[」』]")
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2})$")
NS_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


class DocError(Exception):
    """文件讀不到；args[0] 是 §5.3 的 reason 代碼。"""


# ---------------------------------------------------------------- 共用
def ts(sec: float) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_ts(t: str):
    """HH:MM:SS（時可以一位）→ 秒；格式不對回傳 None。"""
    m = TIME_RE.match((t or "").strip())
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).lower()


def _bump(d: dict, key: str, n: int = 1):
    d[key] = d.get(key, 0) + n


def options(cfg: dict | None = None, frames: bool = True, docs: bool = True, context: bool = True, warn=None) -> dict:
    """設定（reference.*）＋單次旗標（--no-frames／--no-refs／--no-context 傳 False）→ 這次要讀什麼（§8.2：命令列優先）。"""
    cfg = load_config() if cfg is None else cfg

    def rs(k):
        return reference_setting(cfg, k, warn)
    max_frames = rs("max_frames")
    return {"frames": bool(frames and rs("frames") and max_frames > 0), "max_frames": max_frames,
            "frame_px": max(1, rs("frame_max_px")), "docs": bool(docs and rs("docs")),
            "context": bool(context and rs("context")), "terms_max": rs("terms_max_chars"),
            "paras_max": rs("paragraphs_max_chars"), "doc_max_files": rs("doc_max_files"),
            "doc_max_bytes": rs("doc_max_mb") * 1024 * 1024, "pdf_max_pages": rs("pdf_max_pages")}


def media_path(out_dir, meta: dict | None = None, media=None):
    """原始媒體的路徑：明確指定的 --media；否則依 transcript.json 的 meta.source 推回 <輸出資料夾>/../<source>（§7.3）。"""
    if media:
        return Path(media)
    src = (meta or {}).get("source")
    if not src:
        return None
    return Path(out_dir).resolve().parent / Path(str(src)).name


def read_meta(out_dir) -> dict:
    try:
        return json.loads((Path(out_dir) / "transcript.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- §2.1、§2.2 說明檔與一行描述
def read_text_file(path: Path) -> tuple:
    """UTF-8（可有 BOM）→ cp950 → errors="replace"。回傳 (文字, reason)；reason 為 None 或 decode_replaced。讀檔失敗丟 OSError。"""
    data = Path(path).read_bytes()
    try:
        return data.decode("utf-8-sig"), None
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp950"), None
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace"), "decode_replaced"


def strip_frontmatter(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\A---[ \t]*\n.*?\n---[ \t]*(?:\n|\Z)", "", text, count=1, flags=re.S)


def context_files(media, out_dir) -> list:
    """會讀的說明檔路徑（依序）：<主檔名>.context.md（沒有才看 .context.txt）、<輸出資料夾>/context.md。"""
    out = []
    if media is not None:
        media = Path(media)
        md, txt = media.with_name(media.stem + ".context.md"), media.with_name(media.stem + ".context.txt")
        if md.is_file():
            out.append(md)
        elif txt.is_file():
            out.append(txt)
    p = Path(out_dir) / CONTEXT_NAME
    if p.is_file():
        out.append(p)
    return out


def find_context(media, out_dir) -> list:
    """回傳 [{"file", "text", "chars", "status": ok|skipped, "reason"}]；空檔當作沒有（不列）。"""
    items = []
    for p in context_files(media, out_dir):
        try:
            text, reason = read_text_file(p)
        except OSError:
            items.append({"file": p.name, "status": "skipped", "reason": "unreadable", "chars": 0, "text": ""})
            continue
        text = strip_frontmatter(text).strip()
        if not text:
            continue
        if len(text) > CONTEXT_MAX:
            text, reason = text[:CONTEXT_MAX], reason or "truncated"
        items.append({"file": p.name, "status": "ok", "reason": reason, "chars": len(text), "text": text})
    return items


def context_text(items: list) -> str:
    """說明檔在前、context.md 在後，合計上限 2,000 字（§2.2）。"""
    return "\n\n".join(i["text"] for i in items if i.get("status") == "ok" and i.get("text"))[:CONTEXT_MAX].strip()


def write_context(out_dir, line: str, now: datetime | None = None):
    """--context "<一行>"：寫 <輸出資料夾>/context.md（§2.2）。只取第一行、去頭尾空白、最多 300 字；空字串不寫（回傳 None）。
    已有 context.md 時舊檔改名 context.<時間戳>.bak.md。回傳寫入的路徑。"""
    first = (line or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")[0].strip()[:LINE_MAX]
    if not first:
        return None
    out_dir = Path(out_dir)
    now = now or datetime.now().astimezone()
    p = out_dir / CONTEXT_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    if p.exists():
        stamp = now.strftime("%Y%m%d-%H%M%S")
        bak, i = out_dir / f"context.{stamp}.bak.md", 1
        while bak.exists():
            i += 1
            bak = out_dir / f"context.{stamp}-{i}.bak.md"
        p.replace(bak)
    p.write_text(f"---\nsource: entry\ncreated_at: {now.isoformat(timespec='seconds')}\n---\n{first}\n",
                 encoding="utf-8", newline="\n")
    return p


# ---------------------------------------------------------------- §2.3 會議文件的位置
def _skip_name(p: Path) -> bool:
    return p.name.startswith("~$") or p.name.startswith(".")


def _media_count(folder: Path) -> int:
    try:
        return sum(1 for p in folder.iterdir() if p.is_file() and p.suffix.lower() in MEDIA_EXT)
    except OSError:
        return 0


def _first_level(folder: Path) -> list:
    try:
        return sorted((p for p in folder.iterdir() if p.is_file() and not _skip_name(p)), key=lambda p: p.name)
    except OSError:
        return []


def find_docs(media, out_dir, extra=(), max_files: int = 10) -> tuple:
    """§2.3 三條規則（①媒體旁、檔名以「主檔名＋分隔字元」開頭；②媒體旁 refs/，資料夾裡只有這一個媒體檔時；
    ③輸出資料夾的 refs/）＋ --refs。回傳 (要讀的路徑, 略過的 [{"file", "reason"}])。"""
    out_dir = Path(out_dir)
    cands, skipped, seen = [], [], set()

    def add(p: Path, rule: str):
        try:
            key = str(p.resolve()).lower() if sys.platform == "win32" else str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        seen.add(key)
        if p.suffix.lower() not in DOC_EXT:
            skipped.append({"file": p.name, "reason": "unsupported"})
            return
        cands.append(p)

    if media is not None:
        media = Path(media)
        folder, stem = media.parent, media.stem
        for p in _first_level(folder):
            if not p.name.startswith(stem) or p.name == media.name:
                continue
            rest = p.name[len(stem):]
            if not rest or rest[0] not in "._- " or rest.lower().startswith(".context."):
                continue
            if p.suffix.lower() in MEDIA_EXT:      # 同名的其他媒體檔（例 .wav）不是文件，也不記 unsupported
                continue
            add(p, "beside")
        refs_dir = folder / "refs"
        if refs_dir.is_dir() and refs_dir.resolve() != (out_dir / "refs").resolve():
            if _media_count(folder) > 1:
                skipped.append({"file": "refs/", "reason": "shared_folder"})
            else:
                for p in _first_level(refs_dir):
                    add(p, "media_refs")
    for p in _first_level(out_dir / "refs"):
        add(p, "out_refs")
    for e in extra or ():
        e = Path(e)
        if e.is_dir():
            for p in _first_level(e):
                add(p, "flag")
        elif e.is_file():
            add(e, "flag")
        else:
            skipped.append({"file": e.name, "reason": "missing"})
    if len(cands) > max_files:
        skipped += [{"file": p.name, "reason": "too_many_files"} for p in cands[max_files:]]
        cands = cands[:max_files]
    return cands, skipped


# ---------------------------------------------------------------- §5 文件抽取（區塊：{"text", "kind": heading|body|table|strong|note}）
def _zip_xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    info = z.getinfo(name)
    if info.file_size > ZIP_XML_MAX:
        raise DocError("too_large")
    return ET.fromstring(z.read(name))


def _zip_guard(z: zipfile.ZipFile):
    if sum(i.file_size for i in z.infolist()) > ZIP_TOTAL_MAX:
        raise DocError("too_large")


def _bold(r) -> bool:
    b = r.find(f"{NS_W}rPr/{NS_W}b")
    return b is not None and b.get(NS_W + "val", "true").lower() not in ("0", "false", "off")


def extract_docx(path: Path, max_pages: int = 0) -> list:
    with zipfile.ZipFile(path) as z:
        _zip_guard(z)
        root = _zip_xml(z, "word/document.xml")
    in_table = {id(p) for tc in root.iter(NS_W + "tc") for p in tc.iter(NS_W + "p")}
    blocks = []
    for p in root.iter(NS_W + "p"):
        if id(p) in in_table:
            continue
        text = "".join(t.text or "" for t in p.iter(NS_W + "t")).strip()
        if not text:
            continue
        st = p.find(f"{NS_W}pPr/{NS_W}pStyle")
        sv = (st.get(NS_W + "val", "") if st is not None else "").lower()
        heading = sv.startswith(("heading", "title")) or sv.startswith("標題") or p.find(f"{NS_W}pPr/{NS_W}outlineLvl") is not None
        blocks.append({"text": text, "kind": "heading" if heading else "body"})
        for r in p.iter(NS_W + "r"):
            if _bold(r):
                s = "".join(t.text or "" for t in r.iter(NS_W + "t")).strip()
                if s:
                    blocks.append({"text": s, "kind": "strong"})
    for tc in root.iter(NS_W + "tc"):
        s = " ".join("".join(t.text or "" for t in p.iter(NS_W + "t")).strip() for p in tc.iter(NS_W + "p")).strip()
        if s:
            blocks.append({"text": s, "kind": "table"})
    return blocks


def extract_pptx(path: Path, max_pages: int = 0) -> list:
    blocks = []
    with zipfile.ZipFile(path) as z:
        _zip_guard(z)
        names = [n for n in z.namelist() if re.fullmatch(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml", n)]
        names.sort(key=lambda n: (int(re.search(r"(\d+)\.xml$", n).group(1)), n.startswith("ppt/notes")))
        for n in names:
            note = n.startswith("ppt/notes")
            root = _zip_xml(z, n)
            for sp in root.iter(NS_P + "sp"):
                ph = sp.find(f".//{NS_P}ph")
                ptype = ph.get("type") if ph is not None else None
                if ptype in ("sldNum", "hdr", "ftr", "dt", "sldImg"):
                    continue
                for p in sp.iter(NS_A + "p"):
                    text = "".join(t.text or "" for t in p.iter(NS_A + "t")).strip()
                    if not text or (note and text.isdigit()):
                        continue
                    kind = "note" if note else ("heading" if ptype in ("title", "ctrTitle") else "body")
                    blocks.append({"text": text, "kind": kind})
    return blocks


def extract_pdf(path: Path, max_pages: int = 200) -> list:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise DocError("pdf_lib_missing")
    try:
        from pypdf.errors import DependencyError, FileNotDecryptedError
    except ImportError:  # pragma: no cover  舊版 pypdf
        DependencyError = FileNotDecryptedError = PdfReadError
    try:
        r = PdfReader(str(path))
        if r.is_encrypted:
            try:
                ok = r.decrypt("")
            except (DependencyError, FileNotDecryptedError, NotImplementedError, PdfReadError):
                raise DocError("encrypted")
            if not ok:
                raise DocError("encrypted")
        blocks = []
        for i, page in enumerate(r.pages):
            if i >= max_pages:
                break
            for line in (page.extract_text() or "").splitlines():
                if line.strip():
                    blocks.append({"text": line.strip(), "kind": "body"})
    except DocError:
        raise
    except (DependencyError, FileNotDecryptedError):
        raise DocError("encrypted")
    except Exception as ex:  # noqa: BLE001  pypdf 對壞檔丟的例外種類很多
        raise DocError("encrypted" if "decrypt" in str(ex).lower() else "unreadable")
    if not blocks:
        raise DocError("no_text_layer")
    return blocks


def extract_text_doc(path: Path, max_pages: int = 0) -> list:
    text, _reason = read_text_file(path)
    md = path.suffix.lower() == ".md"
    blocks = []
    for line in strip_frontmatter(text).split("\n"):
        s = line.strip()
        if not s:
            continue
        if md and s.startswith("#"):
            blocks.append({"text": s.lstrip("#").strip(), "kind": "heading"})
        else:
            blocks.append({"text": s, "kind": "body"})
    return [b for b in blocks if b["text"]]


EXTRACTORS = {".docx": extract_docx, ".pptx": extract_pptx, ".pdf": extract_pdf, ".txt": extract_text_doc,
              ".md": extract_text_doc}


def _limit_chars(blocks: list) -> tuple:
    out, n = [], 0
    for b in blocks:
        if n + len(b["text"]) > DOC_MAX_CHARS:
            rest = DOC_MAX_CHARS - n
            if rest > 0:
                out.append(dict(b, text=b["text"][:rest]))
            return out, True
        out.append(b)
        n += len(b["text"])
    return out, False


def extract_doc(path: Path, max_bytes: int = 50 * 1024 * 1024, max_pages: int = 200, timeout: float | None = None) -> dict:
    """一份文件 → {"file", "status": ok|skipped, "reason", "chars", "blocks", "truncated"}。不丟例外。"""
    path = Path(path)
    rec = {"file": path.name, "status": "skipped", "reason": None, "chars": 0, "blocks": []}
    try:
        if path.stat().st_size > max_bytes:
            rec["reason"] = "too_large"
            return rec
    except OSError:
        rec["reason"] = "unreadable"
        return rec
    fn = EXTRACTORS.get(path.suffix.lower())
    if fn is None:
        rec["reason"] = "unsupported"
        return rec
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        fut = ex.submit(fn, path, max_pages)
        blocks = fut.result(timeout=DOC_TIMEOUT if timeout is None else timeout)
    except concurrent.futures.TimeoutError:
        rec["reason"] = "timeout"
        return rec
    except DocError as e:
        rec["reason"] = e.args[0] if e.args else "unreadable"
        return rec
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError, ValueError, UnicodeError):
        rec["reason"] = "unreadable"
        return rec
    except Exception as e:  # noqa: BLE001
        rec["reason"] = f"internal_error:{type(e).__name__}"
        return rec
    finally:
        ex.shutdown(wait=False)
    blocks, truncated = _limit_chars(blocks)
    if not blocks:
        rec["reason"] = "no_text_layer" if path.suffix.lower() == ".pdf" else "empty"
        return rec
    rec.update(status="ok", chars=sum(len(b["text"]) for b in blocks), blocks=blocks)
    if truncated:
        rec["truncated"] = True
    return rec


# ---------------------------------------------------------------- §5.4 名詞與段落篩選
def latin_terms(text: str) -> list:
    """拉丁字母詞；大寫開頭的詞後面隔一個空白又接大寫開頭的詞時併成一個（Redis Sentinel）。小寫詞不併（uses Kafka → Kafka）。"""
    out, run, end = [], [], -1
    for m in LATIN_WORD.finditer(text or ""):
        w = m.group(0)
        if run and w[0].isupper() and run[-1][0].isupper() and text[end:m.start()] == " ":
            run.append(w)
        else:
            if run:
                out.append(" ".join(run))
            run = [w]
        end = m.end()
    if run:
        out.append(" ".join(run))
    return out


def _term_ok(t: str, kind: str) -> bool:
    if len(t) <= 2 or len(t) > 40:
        return False
    if " " not in t and _norm(t) in STOPWORDS:
        return False
    return bool(re.search(r"[A-Z].*[A-Z]", t) or re.search(r"[\d_\-]", t) or t[0].isupper()
                or kind in ("heading", "table", "strong"))


def select_terms(docs: list, context: str = "", max_chars: int = 1500) -> list:
    """文件區塊＋背景說明 → 名詞清單（依分數排序，合計 ≤ max_chars 字，以「、」連接計）。"""
    score, first, shown = {}, {}, {}

    def add(t: str, w: int):
        t = t.strip(" .,:;/()[]")
        if not t:
            return
        k = _norm(t)
        if k not in score:
            first[k], shown[k], score[k] = len(first), t, 0
        score[k] += w
    for d in docs:
        for b in d.get("blocks") or []:
            kind = b["kind"]
            bonus = {"heading": 2, "table": 1, "strong": 1}.get(kind, 0)
            for t in latin_terms(b["text"]):
                if _term_ok(t, kind):
                    add(t, 1 + bonus)
            for m in CJK_QUOTE.finditer(b["text"]):
                add(m.group(1).strip(), 1 + bonus)
            cell = b["text"].strip()
            if kind in ("table", "strong") and 2 <= len(cell) <= 8 and not re.search(r"[A-Za-z]", cell) \
                    and re.search(r"[㐀-鿿]", cell):
                add(cell, 1 + bonus)
    for t in latin_terms(context or ""):
        if len(t) > 2 and not (" " not in t and _norm(t) in STOPWORDS):
            add(t, 3)
    out, n = [], 0
    for k in sorted(score, key=lambda k: (-score[k], first[k])):
        t = shown[k]
        need = len(t) + (1 if out else 0)
        if n + need > max_chars:
            break
        out.append(t)
        n += need
    return out


def _grams(s: str) -> set:
    s = _norm(s)
    cjk = re.sub(r"[^㐀-鿿]", "", s)
    return {cjk[i:i + 2] for i in range(len(cjk) - 1)} | set(re.findall(r"[a-z0-9]{3,}", s))


def select_paragraphs(docs: list, transcript_text: str, max_chars: int = 4000) -> list:
    """body／note 區塊（≥ 8 字）與逐字稿的字面重疊比例 ≥ 0.15 → 依分數取到 max_chars 字（每段最多 400 字）。"""
    tg = _grams(transcript_text or "")
    cands, seen = [], set()
    for d in docs:
        for b in d.get("blocks") or []:
            if b["kind"] not in ("body", "note") or len(b["text"]) < PARA_MIN:
                continue
            text = b["text"][:PARA_MAX]
            if text in seen:
                continue
            seen.add(text)
            g = _grams(b["text"])
            if g:
                cands.append((len(g & tg) / len(g), len(cands), d["file"], text))
    cands.sort(key=lambda x: (-x[0], x[1]))
    out, n = [], 0
    for sc, _i, doc, text in cands:
        if sc < PARA_SCORE_MIN:
            break
        if n + len(text) > max_chars:
            continue
        out.append({"doc": doc, "score": round(sc, 2), "text": text})
        n += len(text)
    return out


def join_terms(terms: list, max_chars: int = 1500) -> str:
    """名詞以「、」連接，在名詞邊界截到 max_chars 字。"""
    out, n = [], 0
    for t in terms:
        need = len(t) + (1 if out else 0)
        if n + need > max_chars:
            break
        out.append(t)
        n += need
    return "、".join(out)


# ---------------------------------------------------------------- §3 截圖挑選與縮圖（ffmpeg）
def _ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def _gray(path: Path, w: int, h: int) -> bytes:
    p = subprocess.run([_ffmpeg() or "ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h},format=gray",
                        "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True, timeout=FFMPEG_TIMEOUT,
                       stdin=subprocess.DEVNULL)
    if p.returncode != 0 or len(p.stdout) < w * h:
        raise OSError("ffmpeg")
    return p.stdout[:w * h]


def stddev(path: Path) -> float:
    px = _gray(path, 64, 36)
    m = sum(px) / len(px)
    return (sum((v - m) ** 2 for v in px) / len(px)) ** 0.5


def dhash(path: Path, n: int = DHASH_N) -> int:
    """n×n dHash：縮成 (n+1)×n 灰階，每列左右相鄰比較。"""
    px = _gray(path, n + 1, n)
    bits = 0
    for y in range(n):
        row = y * (n + 1)
        for x in range(n):
            bits = bits << 1 | (px[row + x] > px[row + x + 1])
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def select_frames(out_dir, keyframes: list, max_frames: int = 8) -> tuple:
    """§3.2：去掉不存在／讀不了、空白畫面、連續重複（留較晚的），超過上限時前 2 張必留、其餘依時間平均取。
    回傳 (留下的 [{"file", "time", "path"}], 去掉的張數 {reason: n})。"""
    out_dir = Path(out_dir)
    dropped = {}
    if max_frames <= 0:
        return [], dropped
    have_ffmpeg = _ffmpeg() is not None
    kept = []
    for k in sorted((k for k in keyframes or [] if isinstance(k, dict)), key=lambda k: float(k.get("time") or 0)):
        rel = str(k.get("file") or "")
        p = out_dir / rel
        if not rel or not p.is_file():
            _bump(dropped, "missing")
            continue
        if not have_ffmpeg:
            _bump(dropped, "unreadable")
            continue
        try:
            sd = stddev(p)
            h = None if sd < MIN_STD else dhash(p)
        except Exception:  # noqa: BLE001
            _bump(dropped, "unreadable")
            continue
        if h is None:
            _bump(dropped, "blank")
            continue
        item = {"file": rel, "time": float(k.get("time") or 0), "path": p, "dhash": h}
        if kept and hamming(h, kept[-1]["dhash"]) <= DHASH_DIST:
            kept[-1] = item                      # 同一個畫面：留較晚的那張（翻頁結束、游標停下後）
            _bump(dropped, "duplicate")
            continue
        kept.append(item)
    if len(kept) > max_frames:
        if max_frames <= 2:
            pick = kept[:max_frames]
        else:
            head, rest = kept[:2], kept[2:]
            step = len(rest) / (max_frames - 2)
            pick = head + [rest[int(i * step)] for i in range(max_frames - 2)]
        _bump(dropped, "over_limit", len(kept) - len(pick))
        kept = pick
    return [{"file": k["file"], "time": k["time"], "path": k["path"]} for k in kept], dropped


def jpeg_size(path: Path) -> tuple:
    """讀 JPEG 的 SOF 取得 (寬, 高)；讀不到回傳 (0, 0)。"""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return 0, 0
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + seg
    return 0, 0


def shrink_frames(frames: list, px: int, tmpdir) -> tuple:
    """§3.3：縮到長邊 ≤ px、JPEG -q:v 4（原圖較小也重新編碼，去掉 EXIF），寫到 tmpdir（呼叫端的 TemporaryDirectory）。
    回傳 (送出的 [{"file", "time", "path", "w", "h", "bytes"}], 去掉的張數 {shrink_failed|too_large: n})。"""
    tmpdir = Path(tmpdir)
    sent, dropped = [], {}
    vf = f"scale='if(gt(iw,ih),min({px},iw),-2)':'if(gt(iw,ih),-2,min({px},ih))'"
    for i, f in enumerate(frames, 1):
        dst = tmpdir / f"{i:02d}_{Path(f['file']).stem}.jpg"
        try:
            p = subprocess.run([_ffmpeg() or "ffmpeg", "-v", "error", "-y", "-i", str(f["path"]), "-vf", vf,
                                "-frames:v", "1", "-map_metadata", "-1", "-q:v", "4", str(dst)],
                               capture_output=True, timeout=FFMPEG_TIMEOUT, stdin=subprocess.DEVNULL)
            ok = p.returncode == 0 and dst.is_file() and dst.stat().st_size > 0
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            _bump(dropped, "shrink_failed")
            continue
        size = dst.stat().st_size
        if size > IMAGE_MAX_BYTES:
            _bump(dropped, "too_large")
            continue
        w, h = jpeg_size(dst)
        sent.append({"file": f["file"], "time": f["time"], "path": dst, "w": w, "h": h, "bytes": size})
    return sent, dropped


# ---------------------------------------------------------------- 收集（§2、§3、§5；不呼叫模型）
def _keyframes(out_dir) -> list:
    kf = read_meta(out_dir).get("keyframes")
    return kf if isinstance(kf, list) else []


def collect(out_dir, media=None, cfg: dict | None = None, *, frames: bool = True, docs: bool = True,
            context: bool = True, extra_refs=(), transcript_text: str = "", warn=None) -> dict:
    """一場會議的參考資料（本機）。frames／docs／context＝單次旗標（False＝這次不讀）；設定由 options() 合併。不丟例外。

    回傳：context（說明檔清單）、context_text、docs（每份的狀態，不含區塊）、doc_terms、doc_paragraphs、
    frames（挑好的截圖，尚未縮圖）、frames_available、frames_dropped、frames_reason、errors。"""
    out_dir = Path(out_dir)
    col = {"out_dir": str(out_dir), "media": None, "context": [], "context_text": "", "docs": [], "doc_terms": [],
           "doc_paragraphs": [], "frames": [], "frames_available": 0, "frames_dropped": {}, "frames_reason": None,
           "frames_enabled": False, "errors": [], "opts": {}}
    try:
        opts = options(cfg, frames=frames, docs=docs, context=context, warn=warn)
        col["opts"] = {k: v for k, v in opts.items()}
        meta = read_meta(out_dir).get("meta") or {}
        m = media_path(out_dir, meta, media)
        col["media"] = str(m) if m else None
    except Exception as ex:  # noqa: BLE001
        col["errors"].append(f"internal_error:{type(ex).__name__}")
        return col
    if opts["context"]:
        try:
            col["context"] = find_context(m, out_dir)
            col["context_text"] = context_text(col["context"])
        except Exception as ex:  # noqa: BLE001
            col["errors"].append(f"internal_error:{type(ex).__name__}")
    if opts["docs"]:
        try:
            paths, skipped = find_docs(m, out_dir, extra_refs, opts["doc_max_files"])
            recs = [extract_doc(p, opts["doc_max_bytes"], opts["pdf_max_pages"]) for p in paths]
            col["doc_terms"] = select_terms(recs, col["context_text"], opts["terms_max"])
            col["doc_paragraphs"] = select_paragraphs(recs, transcript_text, opts["paras_max"])
            col["docs"] = [{k: v for k, v in r.items() if k != "blocks"} for r in recs] + \
                          [{"file": s["file"], "status": "skipped", "reason": s["reason"], "chars": 0} for s in skipped]
        except Exception as ex:  # noqa: BLE001
            col["errors"].append(f"internal_error:{type(ex).__name__}")
    if opts["frames"]:
        col["frames_enabled"] = True
        try:
            kf = _keyframes(out_dir)
            col["frames_available"] = len(kf)
            if not kf:
                col["frames_reason"] = "no_keyframes"
            else:
                col["frames"], col["frames_dropped"] = select_frames(out_dir, kf, opts["max_frames"])
                if not col["frames"]:
                    col["frames_reason"] = "no_usable_frames"
        except Exception as ex:  # noqa: BLE001
            col["errors"].append(f"internal_error:{type(ex).__name__}")
            col["frames"], col["frames_reason"] = [], "internal_error"
    else:
        col["frames_reason"] = "frames_off"
    return col


def docs_read(col: dict) -> int:
    return sum(1 for d in col.get("docs") or [] if d.get("status") == "ok")


def docs_skipped(col: dict) -> dict:
    out = {}
    for d in col.get("docs") or []:
        if d.get("status") != "ok" and d.get("reason"):
            _bump(out, d["reason"].split(":")[0])
    return out


def found(col: dict) -> bool:
    """有沒有任何參考資料來源（說明檔、文件（含讀不到的）、可送的截圖來源）。沒有 → 與 2.1.0 完全相同（§2.4）。"""
    return bool(col.get("context") or col.get("docs") or (col.get("frames_enabled") and col.get("frames_available")))


def unreadable_summary(col: dict) -> str:
    """「會議文件 2 份沒有讀到（加密 1、沒有文字層 1）」；全部讀到時回傳空字串。"""
    names = {"encrypted": "加密", "no_text_layer": "沒有文字層", "unreadable": "讀不了", "too_large": "太大",
             "pdf_lib_missing": "缺 pypdf", "timeout": "逾時", "empty": "沒有文字"}
    sk = {k: v for k, v in docs_skipped(col).items() if k in names or k == "internal_error"}
    if not sk:
        return ""
    n = sum(sk.values())
    parts = "、".join(f"{names.get(k, '其他')} {v}" for k, v in sk.items())
    return f"會議文件 {n} 份沒有讀到（{parts}）"


# ---------------------------------------------------------------- §6.1 correct.refs 的使用者訊息與結果整理
def refs_user_text(col: dict, sent: list | None) -> str:
    """sent＝實際附上的截圖（None 或空＝不附圖重試，不列截圖節）。"""
    out = []
    if col.get("context_text"):
        out.append("## 背景說明（使用者提供）\n" + col["context_text"])
    if col.get("doc_terms"):
        out.append("## 會議文件的用字（本機抽出）\n" + "、".join(col["doc_terms"]))
    if col.get("doc_paragraphs"):
        out.append("## 會議文件的相關段落（本機抽出）\n" + "\n".join(f"- （{p['doc']}）{p['text']}"
                                                         for p in col["doc_paragraphs"]))
    if sent:
        out.append("## 截圖（依時間順序，圖片依序附在訊息裡）\n" + "\n".join(
            f"{i}. 時間碼 {ts(f['time'])}（{Path(f['file']).name}）" for i, f in enumerate(sent, 1)))
    return "\n\n".join(out) + "\n"


def valid_refs(structured) -> bool:
    """REFS_SCHEMA 的形狀（四個鍵與型別）；不合 → 呼叫端當 validation_failed。"""
    if not isinstance(structured, dict):
        return False
    m = structured.get("meeting")
    if not isinstance(m, dict) or not all(isinstance(m.get(k), str) for k in ("title", "date", "time")):
        return False
    for key, fields in (("participants", ("name", "role")), ("frames", ("time", "kind", "speaking")),
                        ("terms", ("term", "source"))):
        v = structured.get(key)
        if not isinstance(v, list) or not all(isinstance(x, dict) and all(isinstance(x.get(f), str) for f in fields)
                                              for x in v):
            return False
    return all(isinstance(f.get("terms"), list) for f in structured["frames"])


def normalize_refs(structured: dict, sent: list) -> dict:
    """§6.1 結果整理：frames 依 time 對回實際送出的截圖（對不上的丟掉）；participants 依 name 去重；terms 去重。"""
    st = structured if isinstance(structured, dict) else {}
    by_time = {}
    for f in sent or []:
        by_time.setdefault(int(f["time"]), f)
    frames, used = [], set()
    for fr in st.get("frames") or []:
        sec = parse_ts(fr.get("time") or "")
        f = by_time.get(sec) if sec is not None else None
        if f is None or sec in used:
            continue
        used.add(sec)
        frames.append({"file": Path(f["file"]).name, "time": ts(f["time"]), "kind": fr.get("kind") or "other",
                       "speaking": (fr.get("speaking") or "").strip(),
                       "terms": [t.strip() for t in fr.get("terms") or [] if isinstance(t, str) and t.strip()]})
    parts, seen = [], set()
    for p in st.get("participants") or []:
        name = (p.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        parts.append({"name": name, "role": (p.get("role") or "").strip()})
        if len(parts) >= PARTICIPANTS_MAX:
            break
    terms, seen = [], set()
    for t in st.get("terms") or []:
        term = (t.get("term") or "").strip()
        if term and _norm(term) not in seen:
            seen.add(_norm(term))
            terms.append(term)
    mt = st.get("meeting") or {}
    return {"meeting": {k: (mt.get(k) or "").strip() for k in ("title", "date", "time")}, "participants": parts,
            "frames": frames, "terms": terms}


# ---------------------------------------------------------------- §3.5 講者對應（本機）
def map_speakers(frames: list, paras: list) -> tuple:
    """frames：normalize_refs() 的 frames（time＝HH:MM:SS、speaking）；paras：[{"time", "spk"}]（逐字稿段落）。
    回傳 (speakers {代號: {"name", "evidence"}}, conflicts [...])。一人對一代號、一代號對一人才採用；S? 不參與。"""
    starts = sorted(((parse_ts(p.get("time") or ""), p.get("spk")) for p in paras or []
                     if parse_ts(p.get("time") or "") is not None), key=lambda x: x[0])
    votes, evidence = {}, {}
    for f in frames or []:
        name = (f.get("speaking") or "").strip()
        sec = parse_ts(f.get("time") or "")
        if not name or sec is None:
            continue
        cur = None
        for t, spk in starts:
            if t <= sec:
                cur = spk
            else:
                break
        if not cur or cur == "S?":
            continue
        votes.setdefault(name, set()).add(cur)
        evidence.setdefault((name, cur), f["time"])
    by_code, conflicts = {}, []
    for name, codes in votes.items():
        if len(codes) > 1:
            conflicts.append({"name": name, "speakers": sorted(codes, key=_spk_key)})
            continue
        by_code.setdefault(next(iter(codes)), []).append(name)
    speakers = {}
    for code in sorted(by_code, key=_spk_key):
        names = by_code[code]
        if len(names) == 1:
            speakers[code] = {"name": names[0], "evidence": f"截圖 {evidence[(names[0], code)]} 正在發言"}
        else:
            conflicts.append({"speaker": code, "names": sorted(names)})
    return speakers, conflicts


def _spk_key(code: str):
    return int(code[1:]) if code[1:].isdigit() else 9999


# ---------------------------------------------------------------- §2.5 reference.json
def build_reference(col: dict, refs: dict | None = None, by: dict | None = None, speakers: dict | None = None,
                    conflicts: list | None = None, sent: int = 0, dropped: dict | None = None, frame_px: int | None = None,
                    now: datetime | None = None) -> dict:
    refs = refs or {}
    speakers = speakers or {}
    code_of = {v["name"]: k for k, v in speakers.items()}
    fd = dict(col.get("frames_dropped") or {})
    for k, v in (dropped or {}).items():
        _bump(fd, k, v)
    docs = []
    for d in col.get("docs") or []:
        if d.get("status") == "ok":
            docs.append({"file": d["file"], "chars": d.get("chars", 0), "status": "ok"} |
                        ({"truncated": True} if d.get("truncated") else {}))
        else:
            docs.append({"file": d["file"], "status": "skipped", "reason": d.get("reason")})
    ref = {
        "version": VERSION, "created_at": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
        "by": by,
        "sources": {
            "context": [{"file": c["file"], "chars": c.get("chars", 0)} | ({"reason": c["reason"]} if c.get("reason") else {})
                        for c in col.get("context") or []],
            "docs": docs,
            "frames": {"available": col.get("frames_available", 0) if col.get("frames_enabled") else 0, "sent": sent,
                       "dropped": fd, "max_px": frame_px or (col.get("opts") or {}).get("frame_px")},
        },
        "meeting": refs.get("meeting") or {"title": "", "date": "", "time": ""},
        "participants": [dict(p, speaker=code_of.get(p["name"]), source="frame") for p in refs.get("participants") or []],
        "speakers": speakers,
        "terms": list(refs.get("terms") or []),
        "doc_terms": list(col.get("doc_terms") or []),
        "doc_paragraphs": [{"doc": p["doc"], "text": p["text"]} for p in col.get("doc_paragraphs") or []],
        "frames": list(refs.get("frames") or []),
    }
    if conflicts:
        ref["conflicts"] = conflicts
    return ref


def write_reference(out_dir, ref: dict) -> Path:
    p = Path(out_dir) / REFERENCE_NAME
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    tmp.replace(p)
    return p


def read_reference(out_dir) -> dict | None:
    try:
        ref = json.loads((Path(out_dir) / REFERENCE_NAME).read_text(encoding="utf-8"))
        return ref if isinstance(ref, dict) else None
    except Exception:  # noqa: BLE001
        return None


def merged_terms(ref: dict | None, doc_terms: list | None = None, max_chars: int = 1500) -> list:
    """correct.refs 回的名詞在前、文件名詞在後，去重；合計 ≤ max_chars 字（§5.4 表格第二列）。"""
    out, seen = [], set()
    for t in list((ref or {}).get("terms") or []) + list(doc_terms if doc_terms is not None else (ref or {}).get("doc_terms") or []):
        k = _norm(t)
        if t and k not in seen:
            seen.add(k)
            out.append(t)
    joined = join_terms(out, max_chars)
    return joined.split("、") if joined else []


def participant_lines(ref: dict | None) -> list:
    out = []
    for p in (ref or {}).get("participants") or []:
        s = "- " + p["name"] + (f"（{p['role']}）" if p.get("role") else "") + (f"＝{p['speaker']}" if p.get("speaker") else "")
        out.append(s)
    return out[:PARTICIPANTS_MAX]


def correct_sections(ref: dict | None, ctx_text: str = "", max_terms: int = 1500) -> str:
    """§6.2：名詞階段與各段校正共用的三節（〈背景說明〉〈與會者〉〈參考資料用字〉）；都沒有回傳空字串。"""
    out = []
    if ctx_text:
        out.append("## 背景說明（使用者提供）\n" + ctx_text)
    lines = participant_lines(ref)
    if lines:
        out.append("## 與會者（參考資料：截圖）\n" + "\n".join(lines))
    terms = merged_terms(ref, None, max_terms)
    if terms:
        out.append("## 參考資料用字（截圖、會議文件）\n" + "、".join(terms))
    return "\n\n".join(out)


def ref_words(ref: dict | None) -> set:
    """校正摘要表「依據」判斷用（§6.3）：參考資料用字與與會者姓名。"""
    ref = ref or {}
    words = set(ref.get("terms") or []) | set(ref.get("doc_terms") or [])
    words |= {p["name"] for p in ref.get("participants") or [] if p.get("name")}
    return {w for w in words if w}


def header_line(frames_used: int, docs_used: int, has_context: bool) -> str | None:
    """校正版表頭下的一行（§8.5）；沒有參考資料時 None。"""
    parts = []
    if frames_used:
        parts.append(f"截圖 {frames_used} 張")
    if docs_used:
        parts.append(f"會議文件 {docs_used} 份")
    if has_context:
        parts.append("背景說明")
    if not parts:
        return None
    return f"> 參考資料：{'、'.join(parts)}（人名與名詞寫法參考；內容以逐字稿為準）"


def send_note(frames: int, docs: int, has_context: bool) -> str:
    """console「…會送到 X」前的內容清單（§7.2）：沒有參考資料時就是「逐字稿文字」（與 2.1.0 相同）。"""
    parts = ["逐字稿文字"]
    if frames:
        parts.append(f"截圖 {frames} 張")
    if docs:
        parts.append(f"會議文件 {docs} 份的名詞與段落")
    if has_context:
        parts.append("背景說明")
    return "、".join(parts)


# ---------------------------------------------------------------- 摘要讀取（§2.5：reference.json ＋ 目前重新收集的文件）
def for_minutes(out_dir, media=None, cfg: dict | None = None, *, docs: bool = True, context: bool = True,
                extra_refs=(), transcript_text: str = "", warn=None) -> dict | None:
    """摘要用的參考資料（永遠不送圖，規格 2.2.0 §3.1）。reference.json 的截圖整理結果（meeting、participants、speakers、terms）
    照用；文件與說明檔以目前重新收集的為準（使用者後來加了文件也讀得到）。什麼都沒有回傳 None。"""
    ref = read_reference(out_dir)
    col = collect(out_dir, media, cfg, frames=False, docs=docs, context=context, extra_refs=extra_refs,
                  transcript_text=transcript_text, warn=warn)
    if ref is None and not found(col):
        return None
    base = ref or {}
    return {
        "source": "reference.json" if ref is not None else "collected",
        "context_text": col["context_text"],
        "meeting": base.get("meeting") or {"title": "", "date": "", "time": ""},
        "participants": base.get("participants") or [],
        "speakers": base.get("speakers") or {},
        "terms": base.get("terms") or [],
        "doc_terms": col["doc_terms"],
        "doc_paragraphs": [{"doc": p["doc"], "text": p["text"]} for p in col["doc_paragraphs"]],
        "docs_read": docs_read(col), "docs_skipped": docs_skipped(col),
        "context_chars": len(col["context_text"]),
    }


# ---------------------------------------------------------------- 命令列
def plan(out_dir, media=None, cfg: dict | None = None) -> dict:
    """只算數量（不抽文字、不跑 ffmpeg、不呼叫模型）：入口詢問行用（§7.2）。"""
    out_dir = Path(out_dir)
    opts = options(cfg)
    meta = read_meta(out_dir).get("meta") or {}
    m = media_path(out_dir, meta, media)
    ctx = [p.name for p in context_files(m, out_dir)] if opts["context"] else []
    docs, skipped = find_docs(m, out_dir, (), opts["doc_max_files"]) if opts["docs"] else ([], [])
    kf = [k for k in _keyframes(out_dir) if isinstance(k, dict) and (out_dir / str(k.get("file") or "")).is_file()] \
        if opts["frames"] else []
    return {"frames": min(len(kf), opts["max_frames"]) if opts["frames"] else 0, "frames_available": len(kf),
            "docs": len(docs), "doc_files": [p.name for p in docs],
            "docs_skipped": {r: sum(1 for s in skipped if s["reason"] == r) for r in sorted({s["reason"] for s in skipped})},
            "context": ctx, "context_md": (out_dir / CONTEXT_NAME).is_file(),
            "reference": (out_dir / REFERENCE_NAME).is_file()}


def show(out_dir) -> str:
    ref = read_reference(out_dir)
    if ref is None:
        return f"沒有 {REFERENCE_NAME}（這個資料夾還沒有用參考資料做過 AI 校正）"
    lines = []
    src = ref.get("sources") or {}
    fr = src.get("frames") or {}
    lines.append(f"參考資料（{ref.get('created_at', '')}）：截圖 {fr.get('sent', 0)}／{fr.get('available', 0)} 張、"
                 f"背景說明 {len(src.get('context') or [])} 份、會議文件 {sum(1 for d in src.get('docs') or [] if d.get('status') == 'ok')} 份")
    mt = ref.get("meeting") or {}
    if any(mt.get(k) for k in ("title", "date", "time")):
        lines.append(f"會議：{mt.get('title', '')} {mt.get('date', '')} {mt.get('time', '')}".rstrip())
    sp = ref.get("speakers") or {}
    parts = ref.get("participants") or []
    if parts:
        lines.append("與會者：" + "、".join(p["name"] + (f"＝{p['speaker']}" if p.get("speaker") else "") for p in parts))
    lines.append(f"講者對應 {len(sp)} 個；名詞 {len(ref.get('terms') or [])} 個（文件 {len(ref.get('doc_terms') or [])} 個）；"
                 f"文件段落 {len(ref.get('doc_paragraphs') or [])} 段")
    bad = [d for d in src.get("docs") or [] if d.get("status") != "ok"]
    if bad:
        lines.append("沒有讀到的文件：" + "、".join(f"{d['file']}（{d.get('reason')}）" for d in bad))
    return "\n".join(lines)


def main():
    utf8_console()
    ap = argparse.ArgumentParser(description="參考資料（背景說明、會議文件、截圖）的檢查工具；不呼叫模型")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="列出會用到的說明檔、文件、截圖張數（JSON 一行）")
    p.add_argument("out_dir")
    p.add_argument("--media", default=None, help="原始媒體檔（沒給時依 transcript.json 的 meta.source 推回）")
    s = sub.add_parser("show", help="印出 reference.json 的摘要")
    s.add_argument("out_dir")
    args = ap.parse_args()
    if not Path(args.out_dir).is_dir():
        print(f"找不到資料夾：{args.out_dir}", file=sys.stderr)
        sys.exit(2)
    if args.cmd == "plan":
        print(json.dumps(plan(args.out_dir, args.media), ensure_ascii=False))
    else:
        print(show(args.out_dir))


if __name__ == "__main__":
    main()
