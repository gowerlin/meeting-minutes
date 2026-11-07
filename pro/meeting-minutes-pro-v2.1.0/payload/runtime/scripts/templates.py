"""〔2.0.0〕自訂範本（規格 §3.8）：$MMH/templates/<代號>.md 的載入與驗證。

範本只能延伸內建類型（base 必填）：改名稱、講者設定、節標題，補一段「整理重點」。不能改執行行為（模型、旗標、送出的檔案）。
front matter 不用 YAML 套件（runtime 沒有 PyYAML），只解析 7 個鍵的有限語法：`key: value`、`labels:` 底下兩格縮排的
`key: value`、`#` 之後是註解、值可加單或雙引號；其他語法（清單、多行字串、錨點、更深的縮排）一律視為解析失敗。

介面（transcribe.py、auto_minutes.py、入口共用）：
  load(code) → dict：code、name、base、description、speakers（"auto"｜1～20｜"skip"｜None）、cluster_threshold（float｜None）、
                     labels（dict）、version、prompt、prompt_chars、prompt_truncated、path、notes（console 提醒）
  無效 → 丟 TemplateInvalid（reason、message、base：讀得到時的 base）
  list_all() → [{code, name, base, description, speakers, valid, reason, message}]（入口選單用，只驗證 front matter）

單獨執行：
  python templates.py list              # JSON 一行（入口用；〔2.0.0〕含 message：無效範本的原因）
  python templates.py check [檔案…]      # 使用者自己驗證；沒給檔案＝檢查 templates 目錄的全部範本；exit 0 全部有效、2 有無效的
不記、不印範本內容（規格 §3.8.3：log 只記代號、base、valid、reason、prompt_chars）。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import content_types  # noqa: E402
from common import templates_dir, utf8_console  # noqa: E402

MAX_BYTES = 16 * 1024
MAX_PROMPT = 2000
MAX_NAME = 20
MAX_DESC = 60
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
RESERVED = {c.lower() for c in content_types.CODES} | {"readme"}
KEYS = ("name", "base", "description", "speakers", "cluster_threshold", "labels", "version")
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{20,}|ANTHROPIC_API_KEY|OPENAI_API_KEY")
LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:[ \t]+(.*))?$")
SPEAKERS_MAX = 20
THRESHOLD_RANGE = (0.5, 1.2)


class TemplateInvalid(ValueError):
    """範本不能用。reason：parse_error｜missing_key｜bad_base｜unknown_key｜bad_value｜bad_file｜secret_like｜not_found。"""

    def __init__(self, reason: str, message: str, base: str | None = None, code: str | None = None):
        super().__init__(message)
        self.reason, self.message, self.base, self.code = reason, message, base, code


def _fail(code_or_file: str, reason: str, why: str, base=None, code=None):
    raise TemplateInvalid(reason, f"自訂範本 {code_or_file} 沒有載入：{why}", base, code)


def _strip_comment(v: str) -> str:
    """去掉 # 之後的註解（引號裡的 # 不算）。"""
    q = None
    for i, ch in enumerate(v):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "#" and (i == 0 or v[i - 1] in " \t"):
            return v[:i].rstrip()
    return v.rstrip()


def _scalar(v: str, lineno: int):
    v = _strip_comment(v).strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    if v[:1] in ("'", '"', "|", ">", "&", "*", "[", "{", "!") or v == "-" or (v[:1] == "-" and v[1:2].isspace()):
        raise ValueError(lineno)                     # 引號沒配對、多行字串、錨點、清單（-1、--x 是一般值，交給後面的檢查）
    return v


def parse(text: str) -> tuple:
    """回傳 (front matter dict, 正文)。解析失敗丟 ValueError(行號)。"""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(1)
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        last = max([i for i, x in enumerate(lines) if x.strip()] or [0])
        raise ValueError(last + 1) from None          # 沒有結尾的 ---：指到最後一行
    fm, cur_block = {}, None
    for i in range(1, end):
        raw, lineno = lines[i], i + 1
        if not _strip_comment(raw).strip():
            continue
        if raw.startswith("  ") and not raw.startswith("   ") and cur_block is not None:
            m = LINE_RE.match(raw[2:])
            if not m or not (m.group(2) or "").strip():
                raise ValueError(lineno)
            if m.group(1) in fm[cur_block]:
                raise ValueError(lineno)
            fm[cur_block][m.group(1)] = _scalar(m.group(2), lineno)
            continue
        if raw[:1] in (" ", "\t"):
            raise ValueError(lineno)
        m = LINE_RE.match(raw.rstrip())
        if not m:
            raise ValueError(lineno)
        key, val = m.group(1), _strip_comment(m.group(2) or "").strip()
        if key in fm:
            raise ValueError(lineno)
        if not val:                                   # 只有 labels 可以是區塊；其他鍵空值當空字串
            fm[key] = {} if key == "labels" else ""
            cur_block = key if key == "labels" else None
        else:
            fm[key] = _scalar(val, lineno)
            cur_block = None
    return fm, "\n".join(lines[end + 1:])


def prompt_of(body: str) -> str:
    """正文只取第一個 `## ` 標題之後到檔尾的內容（不含標題行）；沒有 `## ` 標題 → 空字串。"""
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return "\n".join(lines[i + 1:]).strip()
    return ""


def validate(code: str, raw: bytes, file_label: str | None = None) -> dict:
    """驗證一份範本（規格 §3.8.3）。回傳 load() 的 dict；無效丟 TemplateInvalid。"""
    fl = file_label or f"{code}.md"
    if not CODE_RE.match(code or ""):
        _fail(fl, "bad_file", "檔名（代號）只能用英數字、-、_，最多 32 字元", code=code)
    if code.lower() in RESERVED:
        _fail(fl, "bad_file", "代號不能和內建類型或 README 相同，請換一個檔名（例 my-course.md，base: course）", code=code)
    if len(raw) > MAX_BYTES:
        _fail(fl, "bad_file", f"檔案超過 16 KB（{len(raw):,} 位元組）", code=code)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail(fl, "bad_file", "檔案不是 UTF-8 編碼", code=code)
    if SECRET_RE.search(text):
        _fail(fl, "secret_like", "內容看起來含有金鑰，範本不應包含金鑰", code=code)
    try:
        fm, body = parse(text)
    except ValueError as ex:
        _fail(fl, "parse_error", f"開頭的 --- 設定區讀不懂（第 {ex.args[0]} 行）", code=code)
    base = fm.get("base") if fm.get("base") in content_types.CODES else None
    unknown = [k for k in fm if k not in KEYS]
    if unknown:
        _fail(fl, "unknown_key", f"不認得的設定 {'、'.join(unknown)}。範本只能改名稱、講者設定與整理重點，"
                                 "模型、指令與送出的檔案由程式決定", base, code)
    for k in ("name", "base"):
        if not str(fm.get(k) or "").strip():
            _fail(fl, "missing_key", f"缺少 {k}（必填）", base, code)
    if fm["base"] not in content_types.CODES:
        _fail(fl, "bad_base", f"base 只能是 {'、'.join(content_types.CODES)}", None, code)
    name = str(fm["name"]).strip()
    if len(name) > MAX_NAME:
        _fail(fl, "bad_value", f"name 最多 {MAX_NAME} 字（目前 {len(name)} 字）", base, code)
    desc = str(fm.get("description") or "").strip()
    if len(desc) > MAX_DESC:
        _fail(fl, "bad_value", f"description 最多 {MAX_DESC} 字（目前 {len(desc)} 字）", base, code)
    sp = str(fm.get("speakers") or "").strip() or None
    if sp is not None and sp not in ("auto", "skip"):
        if not re.fullmatch(r"\d{1,2}", sp) or not 1 <= int(sp) <= SPEAKERS_MAX:
            _fail(fl, "bad_value", f"speakers 只能是 auto、skip 或 1～{SPEAKERS_MAX} 的整數", base, code)
        sp = int(sp)
    th = str(fm.get("cluster_threshold") or "").strip() or None
    if th is not None:
        try:
            th = float(th)
        except ValueError:
            th = None
            ok = False
        else:
            ok = THRESHOLD_RANGE[0] <= th <= THRESHOLD_RANGE[1]
        if not ok:
            _fail(fl, "bad_value", f"cluster_threshold 只能是 {THRESHOLD_RANGE[0]}～{THRESHOLD_RANGE[1]} 的數字", base, code)
    labels = fm.get("labels") or {}
    if not isinstance(labels, dict):
        _fail(fl, "bad_value", "labels 底下要寫「  欄位名: 新標題」（兩格縮排）", base, code)
    allowed = content_types.label_keys(base)
    bad = [k for k in labels if k not in allowed]
    if bad:
        _fail(fl, "bad_value", f"labels 的 {'、'.join(bad)} 不是 {base} 的欄位；可用的欄位：{'、'.join(allowed)}", base, code)
    for k, v in labels.items():
        if not str(v).strip() or len(str(v)) > MAX_NAME:
            _fail(fl, "bad_value", f"labels 的 {k} 要寫 1～{MAX_NAME} 字的標題", base, code)
    ver = str(fm.get("version") or "1").strip()
    if ver != "1":
        _fail(fl, "bad_value", "version 目前只能是 1", base, code)
    prompt = prompt_of(body)
    notes = []
    truncated = len(prompt) > MAX_PROMPT
    if truncated:
        prompt = prompt[:MAX_PROMPT]
        notes.append(f"自訂範本 {fl} 的整理重點超過 2,000 字，只用前 2,000 字")
    return {"code": code, "name": name, "base": base, "description": desc, "speakers": sp, "cluster_threshold": th,
            "labels": {k: str(v).strip() for k, v in labels.items()}, "version": 1, "prompt": prompt,
            "prompt_chars": len(prompt), "prompt_truncated": truncated, "notes": notes}


def path_of(code: str) -> Path:
    return templates_dir() / f"{code}.md"


def load(code: str) -> dict:
    """依代號讀 $MMH/templates/<代號>.md 並驗證（每次重新讀檔，不快取）。"""
    if not CODE_RE.match(code or ""):
        _fail(f"{code}.md", "bad_file", "代號只能用英數字、-、_，最多 32 字元", code=code)
    p = path_of(code)
    if not p.is_file():
        _fail(f"{code}.md", "not_found", f"找不到 {p}", code=code)
    t = validate(code, p.read_bytes())
    t["path"] = str(p)
    return t


def load_file(path) -> dict:
    p = Path(path)
    t = validate(p.stem, p.read_bytes(), p.name)
    t["path"] = str(p)
    return t


def list_all(directory: Path | None = None) -> list:
    """templates 目錄裡每個 *.md（README.md 除外）的驗證結果，依代號排序。"""
    d = Path(directory) if directory else templates_dir()
    out = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("*.md"), key=lambda x: x.name.lower()):
        if p.stem.lower() == "readme":
            continue
        try:
            t = load_file(p)
            out.append({"code": t["code"], "name": t["name"], "base": t["base"], "description": t["description"],
                        "speakers": t["speakers"], "valid": True, "reason": None, "message": None,
                        "notes": t["notes"]})
        except TemplateInvalid as ex:
            out.append({"code": p.stem, "name": None, "base": ex.base, "description": None, "speakers": None,
                        "valid": False, "reason": ex.reason, "message": ex.message, "notes": []})
        except OSError as ex:
            out.append({"code": p.stem, "name": None, "base": None, "description": None, "speakers": None,
                        "valid": False, "reason": "bad_file",
                        "message": f"自訂範本 {p.name} 沒有載入：讀不到檔案（{type(ex).__name__}）", "notes": []})
    return out


def log_fields(t: dict | None = None, ex: TemplateInvalid | None = None, code: str | None = None) -> dict:
    """run_log 的 template 事件欄位（規格 §6.4）：只記代號、base、valid、reason、prompt_chars、prompt_truncated；不記內容。"""
    if t is not None:
        return {"code": t["code"], "base": t["base"], "valid": True, "prompt_chars": t["prompt_chars"],
                "prompt_truncated": t["prompt_truncated"]}
    return {"code": code or (ex.code if ex else None), "base": ex.base if ex else None, "valid": False,
            "reason": ex.reason if ex else None}


def main():
    utf8_console()
    args = sys.argv[1:]
    if not args or args[0] not in ("list", "check"):
        print("用法：templates.py list | check [檔案…]", file=sys.stderr)
        sys.exit(2)
    if args[0] == "list":
        # 〔2.0.0〕加 message：入口在選單下方印無效範本的原因（規格 §7.1；§6.2 的欄位只新增）
        print(json.dumps([{k: x[k] for k in ("code", "name", "base", "description", "speakers", "valid", "reason", "message")}
                          for x in list_all()], ensure_ascii=False))
        return
    files = args[1:]
    results = []
    if files:
        for f in files:
            try:
                t = load_file(f)
                results.append((True, f"[OK] {Path(f).name}：{t['name']}（base: {t['base']}，整理重點 {t['prompt_chars']} 字）",
                                t["notes"]))
            except TemplateInvalid as ex:
                results.append((False, f"[X] {ex.message}", []))
            except OSError as ex:
                results.append((False, f"[X] 自訂範本 {Path(f).name} 沒有載入：讀不到檔案（{type(ex).__name__}）", []))
    else:
        for x in list_all():
            results.append((x["valid"], f"[OK] {x['code']}.md：{x['name']}（base: {x['base']}）" if x["valid"]
                            else f"[X] {x['message']}", x["notes"]))
        if not results:
            print(f"{templates_dir()} 沒有自訂範本")
    for ok, line, notes in results:
        print(line)
        for n in notes:
            print(f"    [!] {n}")
    sys.exit(0 if all(ok for ok, _, _ in results) else 2)


if __name__ == "__main__":
    main()
