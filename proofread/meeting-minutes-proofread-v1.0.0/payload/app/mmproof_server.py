"""會議記錄校稿：本機服務（只用標準函式庫）。由 mmproof_launcher.py 在背景啟動，使用者不直接執行。

  <Pro 的 pythonw> -B mmproof_server.py [--home <$MMH>]

- 只綁 127.0.0.1，連接埠由作業系統挑空的（port 0）。啟動後把 {pid, port, secret, version, started_at} 寫進
  $MMH/proofread/state/instance.json；啟動器用 secret 把要開的輸出資料夾交給這個服務（同一位使用者只有一個服務）。
- 瀏覽器只能帶一次性登入權杖進來（/login?t=…，60 秒、用一次），換成 HttpOnly＋SameSite=Strict 的 cookie。
- 每個請求檢查 Host（只收 127.0.0.1:<port>、localhost:<port>）；寫入類請求另外要 cookie、同源 Origin 與 X-MMP: 1。
- API 只收 12 碼的稿 id，不收任何路徑；每份稿能讀寫的檔案是固定清單。
- 沒有分頁持有編輯權、沒有背景工作，而且最後一個請求之後超過 idle_seconds（$MMH/proofread/config.json，預設 180）就結束。
- server.log 只記「時間 方法 路徑 狀態碼」，不記查詢字串、cookie 與請求本文。

開發與測試用的參數與環境變數（使用者不需要）：--idle、--lease-ttl、--login-ttl 覆寫時間設定；
MMPROOF_NO_REVEAL=1「開啟資料夾」只回應不開檔案總管；MMPROOF_FAULTS=save,srt 模擬寫檔失敗。
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import mmproof_model as M  # noqa: E402
import mmproof_pro as P  # noqa: E402

STATIC = {"app.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8",
          "app.css": "text/css; charset=utf-8"}
MEDIA_TYPES = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
               ".flac": "audio/flac", ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
               ".weba": "audio/webm", ".mp4": "video/mp4", ".m4v": "video/mp4", ".webm": "video/webm",
               ".mov": "video/quicktime"}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; "
       "connect-src 'self'; font-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
ID_RE = re.compile(r"^[0-9a-f]{12}$")
DOC_RE = re.compile(r"^/api/doc/([0-9a-f]{12})/([a-z]+(?:/[a-z]+)?)$")
NEXT_RE = re.compile(r"^/(?:d/[0-9a-f]{12}(?:\?attach=1)?)?$")
DEFAULT_IDLE, IDLE_MIN, IDLE_MAX = 180, 30, 3600
LEASE_TTL = 150
LOGIN_TTL = 60
MAX_BODY = 20 * 1024 * 1024
MAX_OPEN_TABS = 10
RECENT_KEEP = 20
TMP_MAX_AGE = 3600
CLOSING_WAIT = 15
SHORTCUT = "會議記錄校稿.mmproof"
WRITE_OPS = ("session", "restart", "finalize", "experience/import", "experience/undo", "sync", "redo")
FAULTS = {x.strip() for x in os.environ.get("MMPROOF_FAULTS", "").split(",") if x.strip()}
REDO_EXIT = {0: "完成", 2: "跳過", 3: "登入失敗", 4: "模型不存在", 5: "失敗"}
LOG_LOCK = threading.Lock()


class ApiError(Exception):
    def __init__(self, code: int, error: str, message: str, **extra):
        super().__init__(message)
        self.code, self.payload = code, {"error": error, "message": message, **extra}


def fault(name: str):
    if name in FAULTS:
        raise PermissionError(13, "模擬的寫入錯誤（測試）")


# ---------------------------------------------------------------- 檔案
def write_text(path: Path, text: str):
    """暫存檔＋os.replace()：寫到一半失敗不會留下半個檔。UTF-8、換行 \\n。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".~{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def write_json(path: Path, obj):
    write_text(path, json.dumps(obj, ensure_ascii=False, indent=1))


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def bak_name(folder: Path, stem: str, suffix: str, st: str) -> str:
    """<主檔名>.<時間>.bak<副檔名>；同名已存在時加 -1、-2。"""
    name, n = f"{stem}.{st}.bak{suffix}", 1
    while (folder / name).exists():
        name, n = f"{stem}.{st}-{n}.bak{suffix}", n + 1
    return name


def err_text(ex: Exception) -> str:
    return f"{type(ex).__name__}：{getattr(ex, 'strerror', None) or ex}"


def tool_config(home: Path) -> dict:
    """$MMH/proofread/config.json：idle_seconds（30～3600，不合法用預設 180）。"""
    try:
        cfg = read_json(home / "proofread" / "config.json")
    except (OSError, ValueError):
        cfg = {}
    v = cfg.get("idle_seconds") if isinstance(cfg, dict) else None
    ok = isinstance(v, int) and not isinstance(v, bool) and IDLE_MIN <= v <= IDLE_MAX
    return {"idle_seconds": v if ok else DEFAULT_IDLE}


def resolve_folder(p: str):
    """傳進來的路徑 → 輸出資料夾：① 資料夾本身 ② 檔案所在資料夾 ③ 檔案旁的 <主檔名>_minutes/。
    第一個含有 transcript.corrected.md 或 transcript.md 的就是。"""
    try:
        path = Path(p)
        cands = []
        if path.is_dir():
            cands.append(path)
        elif path.is_file():
            cands += [path.parent, path.with_name(path.stem + "_minutes")]
        for c in cands:
            if (c / "transcript.corrected.md").is_file() or (c / "transcript.md").is_file():
                return c.resolve()
    except (OSError, ValueError):
        return None
    return None


def source_file(folder: Path) -> Path:
    c = folder / "transcript.corrected.md"
    return c if c.exists() else folder / "transcript.md"


def pdir(folder: Path) -> Path:
    return folder / ".proofread"


def session_path(folder: Path) -> Path:
    return pdir(folder) / "session.json"


def read_meta(folder: Path) -> dict:
    try:
        return read_json(folder / "transcript.json").get("meta") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def doc_kind(folder: Path) -> str:
    ct = read_meta(folder).get("content_type")
    if isinstance(ct, str) and ct:
        return "meeting" if ct == "meeting" else "notes"
    return "notes" if (folder / "notes.md").exists() and not (folder / "meeting-minutes.md").exists() else "meeting"


def clean_tmp(folder: Path):
    """寫到一半斷電留下的 .~*.tmp：超過 1 小時的刪掉（正式檔因為 os.replace 不會是半個檔）。"""
    d = pdir(folder)
    if not d.is_dir():
        return
    now = time.time()
    for p in d.glob(".~*.tmp"):
        try:
            if now - p.stat().st_mtime > TMP_MAX_AGE:
                p.unlink()
        except OSError:
            pass


def reveal(path: Path):
    """用作業系統的檔案管理員開啟（只開服務決定的位置）。"""
    if os.environ.get("MMPROOF_NO_REVEAL"):
        return
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- 狀態
class Doc:
    def __init__(self, folder: Path):
        self.folder = folder
        self.lease = None            # {"tab", "ts"}
        self.attention = False
        self.lock = threading.RLock()
        self.job = None              # 重做會議記錄的背景工作


class State:
    def __init__(self, home: Path, pro: "P.Pro", idle: int, lease_ttl: int, login_ttl: int):
        self.home, self.pro = home, pro
        self.state_dir = home / "proofread" / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.idle, self.lease_ttl, self.login_ttl = idle, lease_ttl, login_ttl
        self.lock = threading.RLock()
        self.secret = secrets.token_urlsafe(32)
        self.logins = {}
        self.sessions = set()
        self.docs = {}
        self.last = time.time()
        self.port = None
        self.closing = None
        self.started = time.time()

    def doc_id(self, folder: Path) -> str:
        return hashlib.sha256(str(folder.resolve()).lower().encode("utf-8")).hexdigest()[:12]

    def recent(self) -> list:
        try:
            rs = read_json(self.state_dir / "recent.json")
            return [r for r in rs if isinstance(r, dict) and ID_RE.match(str(r.get("id", "")))]
        except (OSError, ValueError, TypeError):
            return []

    def touch_recent(self, did: str, folder: Path, prog=None, saved_at=None):
        with self.lock:
            rs = self.recent()
            old = next((r for r in rs if r["id"] == did), {})
            if prog is None:
                try:
                    ss = read_json(session_path(folder))
                    prog, saved_at = ss.get("progress"), ss.get("saved_at")
                except (OSError, ValueError, AttributeError):
                    pass
            rest = [r for r in rs if r["id"] != did]
            rest.insert(0, {"id": did, "dir": str(folder), "name": folder.name, "opened_at": M.now_iso(),
                            "saved_at": saved_at or old.get("saved_at"), "progress": prog or old.get("progress")})
            try:
                write_json(self.state_dir / "recent.json", rest[:RECENT_KEEP])
            except OSError:
                pass

    def register(self, folder: Path) -> str:
        folder = folder.resolve()
        did = self.doc_id(folder)
        with self.lock:
            if did not in self.docs:
                self.docs[did] = Doc(folder)
        self.touch_recent(did, folder)
        return did

    def lease_live(self, d: Doc) -> bool:
        return bool(d.lease) and time.time() - d.lease["ts"] < self.lease_ttl

    def busy(self) -> bool:
        with self.lock:
            return any(self.lease_live(d) for d in self.docs.values()) or any(
                d.job and d.job.get("status") == "running" for d in self.docs.values())

    def login_url(self, nxt: str) -> str:
        t = secrets.token_urlsafe(24)
        with self.lock:
            now = time.time()
            self.logins = {k: v for k, v in self.logins.items() if v > now}
            self.logins[t] = now + self.login_ttl
        return f"http://127.0.0.1:{self.port}/login?t={t}&next={nxt}"

    def log_line(self, method: str, path: str, code):
        line = f"{M.now_iso()} {method} {path} {code}\n"
        p = self.state_dir / "server.log"
        with LOG_LOCK:
            try:
                if p.exists() and p.stat().st_size > 1024 * 1024:
                    os.replace(p, p.with_name("server.log.1"))
                with open(p, "a", encoding="utf-8") as f:
                    f.write(line)
            except OSError:
                pass


# ---------------------------------------------------------------- 稿件
class Loaded:
    """一份稿目前的狀態：來源、暫存、畫面上的稿、是否被重新產生、是否唯讀。"""

    def __init__(self, S: State, folder: Path):
        self.folder = folder
        clean_tmp(folder)
        self.src = source_file(folder)
        self.text = self.src.read_text(encoding="utf-8")
        self.notice = None
        self.readonly = None
        snap = pdir(folder) / "source.md"
        sp = session_path(folder)
        sess = None
        if sp.exists():
            try:
                sess = read_json(sp)
                if not isinstance(sess, dict):
                    raise ValueError("not an object")
            except (OSError, ValueError) as ex:
                st = M.stamp()
                broken = f"session.{st}.broken.json"
                try:
                    os.replace(sp, pdir(folder) / broken)
                except OSError:
                    pass
                self.notice = f"上次的校稿暫存讀不到（{type(ex).__name__}），已改名為 .proofread/{broken}，從頭開始。"
                sess = None
        if sess is not None:
            major = M.session_major(sess)
            if major is None or major > M.SESSION_MAJOR:
                self.readonly = "format_newer"       # 較新版工具寫的：只在記憶體補欄位顯示，不寫回
            M.normalize_session(sess)
        if sess is None:
            sess = M.empty_session(self.src.name, self.text)
            M.log_op(sess, "開始校稿", [".proofread/session.json", ".proofread/source.md"])
            write_text(snap, self.text)
            write_json(sp, sess)
        self.sess = sess
        self.changed = None
        shown = self.text
        if not self.readonly and sess["source"].get("sha256") != M.sha256_text(self.text):
            self.changed = {"file": self.src.name, "since": sess.get("saved_at") or sess.get("created_at")}
            if snap.exists():
                shown = snap.read_text(encoding="utf-8")
        elif not self.readonly and not snap.exists():
            try:
                write_text(snap, self.text)
            except OSError:
                pass
        self.doc = M.parse_corrected(shown, S.pro.key_of)

    def full(self) -> dict:
        return M.with_manual(self.doc, self.sess)

    def save(self):
        fault("save")
        write_json(session_path(self.folder), self.sess)


def original_paras(folder: Path) -> list:
    p = folder / "transcript.md"
    return M.original_paragraphs(p.read_text(encoding="utf-8")) if p.exists() else []


def glossary_terms(pro) -> set:
    p = pro.glossary_path()
    return M.load_glossary(p.read_text(encoding="utf-8")) if p.exists() else set()


def experience_of(S: State, L: Loaded) -> dict:
    return M.experience(L.full(), L.sess, original_paras(L.folder), S.pro.correction_rows(), glossary_terms(S.pro),
                        S.pro.keep_words(), S.pro.common_words, S.pro.min_count())


def mmh_rel(p) -> str | None:
    return f"$MMH/backups/{Path(p).name}" if p else None


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "mmproof/" + M.TOOL_VERSION
    sys_version = ""
    protocol_version = "HTTP/1.1"
    S: State = None

    def log_request(self, code="-", size="-"):
        self.S.log_line(self.command, urlsplit(self.path).path, getattr(code, "value", code))

    def log_message(self, fmt, *args):
        pass

    # ---- 回應
    def headers_common(self):
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "no-store")

    def send(self, code: int, body: bytes = b"", ctype: str = "application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.headers_common()
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def js(self, code: int, obj):
        self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def page(self, code: int, title: str, msg: str):
        body = (f"<!doctype html><html lang=\"zh-Hant-TW\"><meta charset=\"utf-8\">"
                f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>{title}｜會議記錄校稿</title>"
                f"<link rel=\"stylesheet\" href=\"/static/app.css\"><body class=\"plain\"><main class=\"plain-box\">"
                f"<h1>{title}</h1><p>{msg}</p></main></body></html>").encode("utf-8")
        self.send(code, body, "text/html; charset=utf-8")

    # ---- 檢查
    def host_ok(self) -> bool:
        return self.headers.get("Host", "") in (f"127.0.0.1:{self.S.port}", f"localhost:{self.S.port}")

    def origin_ok(self) -> bool:
        return self.headers.get("Origin") in (f"http://127.0.0.1:{self.S.port}", f"http://localhost:{self.S.port}")

    def cookie_ok(self) -> bool:
        try:
            c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        except cookies.CookieError:
            return False
        v = c["mmp_s"].value if "mmp_s" in c else ""
        return bool(v) and any(hmac.compare_digest(v, s) for s in list(self.S.sessions))

    def read_body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "body", "請求格式不正確") from None
        if n > MAX_BODY:
            self.close_connection = True
            raise ApiError(413, "too_large", "請求太大")
        raw = self.rfile.read(n) if n > 0 else b""
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ApiError(400, "body", "請求不是正確的 JSON") from None
        if not isinstance(data, dict):
            raise ApiError(400, "body", "請求不是正確的 JSON")
        return data

    # ---- 分派
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self.S.last = time.time()
        if not self.host_ok():
            return self.send(403, b'{"error":"host"}')
        u = urlsplit(self.path)
        if u.path == "/login":
            return self.login(parse_qs(u.query))
        if u.path == "/favicon.ico":
            return self.send(204, b"", "image/x-icon")
        if u.path == "/static/app.css":                 # 錯誤頁也要用到，不需要登入
            return self.static("app.css")
        if not self.cookie_ok():
            if u.path.startswith("/api/"):
                return self.js(401, {"error": "login", "message": "請從右鍵或捷徑重新開啟"})
            return self.page(401, "請從右鍵或捷徑開啟",
                             "這個頁面要從「傳送到 → 會議記錄校稿」或輸出資料夾裡的「會議記錄校稿」捷徑開啟。")
        if u.path == "/" or re.fullmatch(r"/d/[0-9a-f]{12}", u.path):
            return self.static("app.html")
        if u.path in ("/static/app.js",):
            return self.static(u.path[len("/static/"):])
        if u.path == "/api/docs":
            return self.api_docs()
        m = DOC_RE.match(u.path)
        if m:
            return self.guard(lambda: self.doc_get(m.group(1), m.group(2)))
        return self.send(404, b'{"error":"not_found"}')

    def do_POST(self):
        self.S.last = time.time()
        if not self.host_ok():
            return self.send(403, b'{"error":"host"}')
        u = urlsplit(self.path)
        if u.path == "/api/handoff":
            return self.guard(self.handoff)
        if not (self.cookie_ok() and self.origin_ok() and self.headers.get("X-MMP") == "1"):
            self.close_connection = True
            return self.send(403, b'{"error":"auth"}')

        def run():
            data = self.read_body()
            if u.path == "/api/ping":
                return self.js(200, {"ok": True, "closing": bool(self.S.closing)})
            m = re.fullmatch(r"/api/docs/([0-9a-f]{12})/reopen", u.path)
            if m:
                return self.reopen(m.group(1))
            m = DOC_RE.match(u.path)
            if m:
                return self.doc_post(m.group(1), m.group(2), data)
            return self.send(404, b'{"error":"not_found"}')
        return self.guard(run)

    do_PUT = do_POST

    def guard(self, fn):
        try:
            return fn()
        except ApiError as ex:
            return self.js(ex.code, ex.payload)
        except (ConnectionError, TimeoutError):
            self.close_connection = True
        except Exception as ex:  # noqa: BLE001
            return self.js(500, {"error": "internal", "message": f"會議記錄校稿內部錯誤（{type(ex).__name__}）"})

    def static(self, name: str):
        self.send(200, (HERE / "static" / name).read_bytes(), STATIC[name])

    # ---- 登入與交接
    def login(self, q: dict):
        t = (q.get("t") or [""])[0]
        nxt = (q.get("next") or ["/"])[0]
        if not NEXT_RE.match(nxt):
            nxt = "/"
        with self.S.lock:
            now = time.time()
            hit = next((k for k in list(self.S.logins) if hmac.compare_digest(t, k)), None)
            ok = hit is not None and self.S.logins.get(hit, 0) > now
            if hit is not None:
                del self.S.logins[hit]                  # 用一次就失效（過期的也一併移除）
        if not ok:
            return self.page(401, "連結已失效", "這個開啟連結已經用過或過期。請再從右鍵或捷徑開啟一次。")
        sid = secrets.token_urlsafe(32)
        with self.S.lock:
            self.S.sessions.add(sid)
        self.send(303, b"", "text/plain; charset=utf-8",
                  {"Location": nxt, "Set-Cookie": f"mmp_s={sid}; HttpOnly; SameSite=Strict; Path=/"})

    def handoff(self):
        if self.headers.get("Origin") is not None or not hmac.compare_digest(
                self.headers.get("X-MMP-Handoff", ""), self.S.secret):
            self.close_connection = True
            return self.send(403, b'{"error":"handoff"}')
        data = self.read_body()
        if data.get("shutdown"):
            self.S.closing = self.S.closing or time.time()
            return self.js(200, {"closing": True})
        if self.S.closing:
            return self.js(503, {"error": "closing", "message": "服務正在關閉"})
        folders = [f for f in data.get("folders") or [] if isinstance(f, str)]
        found, res = [], []
        seen = set()
        for f in folders:
            folder = resolve_folder(f)
            if folder is None:
                res.append({"input": Path(f).name, "status": "invalid"})
                continue
            did = self.S.doc_id(folder)
            if did in seen:
                continue
            seen.add(did)
            found.append((folder, did))
        many = len(found) > MAX_OPEN_TABS
        for folder, did in found:
            self.S.register(folder)
            d = self.S.docs[did]
            try:
                sc = folder / SHORTCUT
                if not sc.exists():
                    sc.write_text("meeting-minutes-proofread 1\n", encoding="utf-8", newline="\n")
            except OSError:
                pass
            if many:
                res.append({"input": folder.name, "id": did, "status": "listed"})
                continue
            if self.S.lease_live(d):
                d.attention = True
                status, nxt = "attach", f"/d/{did}?attach=1"
            else:
                status, nxt = "open", f"/d/{did}"
            res.append({"input": folder.name, "id": did, "status": status, "url": self.S.login_url(nxt)})
        if data.get("home") or many or not found:          # 沒有有效路徑、或一次超過 10 份：開首頁
            res.append({"status": "home", "url": self.S.login_url("/")})
        self.js(200, {"results": res, "version": M.TOOL_VERSION})

    # ---- 首頁
    def api_docs(self):
        with self.S.lock:
            opened = [{"id": k, "name": v.folder.name, "editing": self.S.lease_live(v)} for k, v in self.S.docs.items()]
        recent = [{"id": r["id"], "name": r.get("name"), "opened_at": r.get("opened_at"), "saved_at": r.get("saved_at"),
                   "progress": r.get("progress"), "open": r["id"] in self.S.docs} for r in self.S.recent()]
        self.js(200, {"open": opened, "recent": recent, "version": M.TOOL_VERSION, "pro_version": self.S.pro.version,
                      "idle_seconds": self.S.idle})

    def reopen(self, did: str):
        r = next((x for x in self.S.recent() if x["id"] == did), None)
        folder = resolve_folder(r["dir"]) if r and isinstance(r.get("dir"), str) else None
        if folder is None or self.S.doc_id(folder) != did:
            return self.js(404, {"error": "gone", "message": "這份稿的資料夾找不到了（可能已搬移或刪除）"})
        self.S.register(folder)
        d = self.S.docs[did]
        self.js(200, {"ok": True, "editing": self.S.lease_live(d)})

    # ---- 單份稿：讀
    def doc_of(self, did: str) -> Doc:
        d = self.S.docs.get(did)
        if not d:
            raise ApiError(404, "not_open", "這份稿沒有開啟，請從右鍵或首頁開啟")
        if not source_file(d.folder).exists():
            raise ApiError(404, "gone", "這份稿的資料夾找不到了（可能已搬移或刪除）")
        return d

    def doc_get(self, did: str, op: str):
        d = self.doc_of(did)
        folder = d.folder
        if op == "media":
            return self.media(folder)
        if op == "job":
            return self.js(200, d.job or {"status": "none"})
        with d.lock:
            L = Loaded(self.S, folder)
        if op == "data":
            return self.js(200, self.data_of(did, d, L))
        if op == "experience":
            res = experience_of(self.S, L)
            res["imports"] = [{"at": x.get("at"), "corrections": len(x.get("corrections") or []),
                               "glossary": len(x.get("glossary") or []), "backups": {k: mmh_rel(v) for k, v in
                                                                                 (x.get("backups") or {}).items()}}
                              for x in L.sess.get("imports", [])]
            res["min_count"] = self.S.pro.min_count()
            return self.js(200, res)
        if op == "log":
            return self.js(200, {"log": L.sess.get("log", []), "saved_at": L.sess.get("saved_at"), "rev": L.sess["rev"]})
        raise ApiError(404, "not_found", "找不到")

    def data_of(self, did: str, d: Doc, L: Loaded) -> dict:
        folder = L.folder
        mf = self.S.pro.find_media(folder)
        media = None
        if mf.get("status") == "found" and mf["ext"] in MEDIA_TYPES:
            media = {"status": "found", "name": Path(mf["path"]).name, "type": MEDIA_TYPES[mf["ext"]].split("/")[0]}
        elif mf.get("status") in ("found", "unsupported"):
            media = {"status": "unsupported", "ext": mf.get("ext")}
        s = L.sess
        redo = s.get("redo") or {}
        job = d.job
        interrupted = bool(redo.get("status") == "running" and not (job and job.get("status") == "running"))
        kind = doc_kind(folder)
        return {"id": did, "name": folder.name, "kind": kind, "source_file": L.src.name, "doc": L.doc,
                "session": {k: s.get(k) for k in ("rev", "saved_at", "created_at", "marks", "manual", "history",
                                                   "progress", "finalized")},
                "changed": L.changed, "readonly": L.readonly, "notice": L.notice, "media": media,
                "files": {n: (folder / n).exists() for n in ("transcript.final.md", "transcript.final.srt",
                                                             "meeting-minutes.md", "notes.md", "transcript.json")},
                "redo": {"available": self.S.pro.redo_available, "pro_version": self.S.pro.version,
                         "reason": None if self.S.pro.redo_available else
                         f"升級 meeting-minutes-pro 到 {P.REDO_MIN_PRO} 以上就能用（目前 {self.S.pro.version}）",
                         "job": job, "interrupted": interrupted},
                "tool_version": M.TOOL_VERSION}

    def media(self, folder: Path):
        mf = self.S.pro.find_media(folder)
        if mf.get("status") != "found" or mf.get("ext") not in MEDIA_TYPES:
            return self.send(404, b'{"error":"no_media"}')
        p = Path(mf["path"])
        size = p.stat().st_size
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range", "").strip())
        a, b, partial = 0, size - 1, False
        if rng and (rng.group(1) or rng.group(2)):
            partial = True
            if rng.group(1):
                a = int(rng.group(1))
                b = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                a = max(size - int(rng.group(2)), 0)
            if a > b or a >= size:
                return self.send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
        n = b - a + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", MEDIA_TYPES[mf["ext"]])
        self.send_header("Content-Length", str(n))
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.headers_common()
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(p, "rb") as f:
            f.seek(a)
            left = n
            while left > 0:
                chunk = f.read(min(1024 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    # ---- 單份稿：寫
    def doc_post(self, did: str, op: str, data: dict):
        d = self.doc_of(did)
        tab = str(data.get("tab", ""))[:64]
        if op == "lease":
            return self.lease(d, tab, data)
        if op == "bye":
            with self.S.lock:
                if d.lease and d.lease["tab"] == tab:
                    d.lease = None
            return self.js(200, {"ok": True})
        if op == "reveal":
            tgt = {"folder": d.folder, "mmh": self.S.home, "backups": self.S.home / "backups"}.get(data.get("target"))
            if tgt is None or not tgt.is_dir():
                return self.js(404, {"error": "no_target", "message": "找不到這個資料夾"})
            reveal(tgt)
            return self.js(200, {"ok": True})
        if op not in WRITE_OPS:
            raise ApiError(404, "not_found", "找不到")
        with self.S.lock:
            holder = bool(d.lease and d.lease["tab"] == tab and self.S.lease_live(d))
        if not holder:
            raise ApiError(423, "locked", "這份稿正在另一個分頁編輯，這個分頁只能看")
        with d.lock:
            L = Loaded(self.S, d.folder)
            if L.readonly:
                raise ApiError(409, "format_newer", "這份稿的校稿暫存是較新版的會議記錄校稿寫的，請先升級會議記錄校稿")
            if L.changed and op != "restart":
                raise ApiError(409, "source_changed", "校正版逐字稿已經被重新產生，請先選擇怎麼處理")
            return getattr(self, "op_" + op.replace("/", "_"))(did, d, L, data)

    def lease(self, d: Doc, tab: str, data: dict):
        with self.S.lock:
            holder = d.lease["tab"] if self.S.lease_live(d) else None
            if not tab:
                return self.js(400, {"error": "tab"})
            if holder in (None, tab) or data.get("takeover"):
                d.lease = {"tab": tab, "ts": time.time()}
                att, d.attention = d.attention, False
                got = True
            else:
                got = False
        if not got:
            return self.js(200, {"holder": False, "closing": bool(self.S.closing)})
        try:
            rev = read_json(session_path(d.folder)).get("rev", 0)
        except (OSError, ValueError, AttributeError):
            rev = 0
        return self.js(200, {"holder": True, "attention": att, "rev": rev, "closing": bool(self.S.closing),
                             "job": d.job})

    def op_session(self, did: str, d: Doc, L: Loaded, data: dict):
        sess = L.sess
        try:
            base = int(data.get("base_rev", -1))
        except (TypeError, ValueError):
            base = -1
        if base != sess["rev"]:
            raise ApiError(409, "rev", "這份稿在別處存過更新的版本，這個分頁的修改沒有存", rev=sess["rev"],
                           saved_at=sess.get("saved_at"))
        marks, err = M.clean_decisions(L.doc, data.get("marks") or {})
        manual = data.get("manual") or []
        err = err or M.check_manual(L.doc, manual)
        if err:
            raise ApiError(400, "invalid", err)
        sess["marks"], sess["manual"] = marks, M.clean_manual(manual)
        if isinstance(data.get("history"), list):
            sess["history"] = data["history"][-M.HISTORY_KEEP:]
        sess.update(rev=sess["rev"] + 1, saved_at=M.now_iso(), tool_version=M.TOOL_VERSION)
        sess["progress"] = M.progress(L.full(), sess)
        pg = sess["progress"]
        if data.get("manual_save"):
            M.log_op(sess, "儲存（手動）", [".proofread/session.json"], f"已處理 {pg['done']}／{pg['total']}")
        elif data.get("reason") in ("離開分頁", "服務關閉"):
            M.log_op(sess, f"儲存（{data['reason']}）", [".proofread/session.json"])
        try:
            L.save()
        except OSError as ex:
            raise ApiError(500, "write", f"寫不進 .proofread/session.json（{err_text(ex)}）") from None
        self.S.touch_recent(did, L.folder, pg, sess["saved_at"])
        self.js(200, {"rev": sess["rev"], "saved_at": sess["saved_at"], "progress": pg})

    def op_restart(self, did: str, d: Doc, L: Loaded, data: dict):
        """校正版被重新產生：舊暫存改名備份，用新版重新開始；carry=true 時把對得上的決定帶過去。"""
        if not L.changed:
            raise ApiError(400, "not_changed", "校正版沒有被重新產生")
        st = M.stamp()
        pd = pdir(L.folder)
        old_sess, old_doc = L.sess, L.doc
        sb, mb = f"session.{st}.bak.json", f"source.{st}.bak.md"
        try:
            os.replace(session_path(L.folder), pd / sb)
            if (pd / "source.md").exists():
                os.replace(pd / "source.md", pd / mb)
            new = M.empty_session(L.src.name, L.text)
            new["rev"] = old_sess["rev"] + 1
            info = None
            if data.get("carry"):
                new_doc = M.parse_corrected(L.text, self.S.pro.key_of)
                new["marks"], new["manual"], info = M.carry_over(old_doc, old_sess, new_doc)
                new["progress"] = M.progress(M.with_manual(new_doc, new), new)
            new["log"] = old_sess.get("log", [])
            new["imports"] = old_sess.get("imports", [])
            note = f"舊暫存備份 .proofread/{sb}"
            if info:
                note += f"；帶入標記決定 {info['marks']}／{info['marks_total']}、人工修改 {info['manual']}／{info['manual_total']}"
            M.log_op(new, "用新版重新開始" + ("（帶入決定）" if data.get("carry") else "（不帶入）"),
                     [".proofread/session.json", ".proofread/source.md", f".proofread/{sb}"], note)
            write_text(pd / "source.md", L.text)
            write_json(session_path(L.folder), new)
        except OSError as ex:
            raise ApiError(500, "write", f"沒有寫入任何檔案。原因：{err_text(ex)}") from None
        self.js(200, {"ok": True, "carried": info, "backup": f".proofread/{sb}"})

    def op_finalize(self, did: str, d: Doc, L: Loaded, data: dict):
        """dry_run：只計算要寫的檔與備份（確認畫面）。正式：逐檔寫，回實際寫入、備份與失敗原因（結果畫面）。"""
        folder, sess = L.folder, L.sess
        doc = L.full()
        pg = M.progress(doc, sess)
        st = M.stamp()
        n_para = len(M.paragraphs(doc))
        md, srt = folder / "transcript.final.md", folder / "transcript.final.srt"
        tj = folder / "transcript.json"
        srt_note = None
        if not tj.exists():
            srt_note = "沒有 transcript.json，不產生定稿字幕"
        plan = [{"file": md.name, "what": f"定稿逐字稿（{n_para} 段）",
                 "backup": bak_name(folder, "transcript.final", ".md", st) if md.exists() else None}]
        if srt_note is None:
            plan.append({"file": srt.name, "what": "定稿字幕（Pro 字幕對時）",
                         "backup": bak_name(folder, "transcript.final", ".srt", st) if srt.exists() else None})
        if data.get("dry_run"):
            return self.js(200, {"plan": plan, "pending": pg["pending"], "progress": pg, "srt_note": srt_note,
                                 "unchanged": ["transcript.md", L.src.name] if L.src.name != "transcript.md"
                                 else ["transcript.md"]})
        if pg["pending"] and not data.get("allow_pending"):
            raise ApiError(409, "pending", f"還有 {pg['pending']} 處未處理", pending=pg["pending"])
        when = time.strftime("%Y-%m-%d %H:%M")
        fallback = read_meta(folder).get("source") or folder.name
        written, failed = [], []
        try:
            text = M.final_markdown(doc, sess, L.src.name, when, fallback)
            bak = None
            if md.exists():
                bak = bak_name(folder, "transcript.final", ".md", st)
                os.replace(md, folder / bak)
            write_text(md, text)
            written.append({"file": md.name, "backup": bak, "detail": f"{n_para} 段"})
        except Exception as ex:  # noqa: BLE001
            failed.append({"file": md.name, "reason": err_text(ex)})
        if srt_note is None:
            try:
                try:
                    tdoc = read_json(tj)
                except (OSError, ValueError) as ex:
                    raise RuntimeError(f"transcript.json 讀不到（{type(ex).__name__}）") from None
                if not isinstance(tdoc, dict) or not tdoc.get("segments"):
                    raise RuntimeError("transcript.json 沒有辨識段（segments），不產生定稿字幕")
                body, n_cues, map_failed = self.S.pro.final_srt(tdoc, M.resolved_corrected_text(doc, sess))
                fault("srt")
                bak = None
                if srt.exists():
                    bak = bak_name(folder, "transcript.final", ".srt", st)
                    os.replace(srt, folder / bak)
                write_text(srt, body)
                note = f"{n_cues} 條；Pro subtitles.map_corrected 對時，對應失敗 {map_failed} 段"
                if map_failed:
                    note += "（該段用原文）"
                written.append({"file": srt.name, "backup": bak, "detail": note, "map_failed": map_failed})
            except Exception as ex:  # noqa: BLE001
                failed.append({"file": srt.name, "reason": str(ex) if isinstance(ex, RuntimeError) else err_text(ex)})
        if not written:
            raise ApiError(500, "write", "沒有寫入任何檔案。原因：" + "；".join(f"{f['file']}：{f['reason']}" for f in failed),
                           failed=failed)
        sess["finalized"] = {"at": M.now_iso(), "rev": sess["rev"], "pending": pg["pending"]}
        M.log_op(sess, "定稿" + ("（部分失敗）" if failed else ""),
                 [w["file"] for w in written] + [w["backup"] for w in written if w["backup"]],
                 f"{n_para} 段" + (f"；未處理 {pg['pending']} 處" if pg["pending"] else ""))
        try:
            L.save()
        except OSError as ex:
            failed.append({"file": ".proofread/session.json", "reason": err_text(ex)})
        pairs = M.sync_pairs(doc, sess)
        mins = [n for n in M.MINUTES_FILES if (folder / n).exists()]
        preview = []
        for n in mins:
            _, hits = M.apply_pairs((folder / n).read_text(encoding="utf-8"), pairs)
            preview += [{"file": n, "wrong": a, "right": dict(pairs)[a], "count": c} for a, c in hits.items()]
        self.js(207 if failed else 200, {"written": written, "failed": failed, "progress": pg,
                                         "sync_preview": preview, "minutes": mins})

    def op_sync(self, did: str, d: Doc, L: Loaded, data: dict):
        """名詞寫法同步到會議記錄／筆記：先備份，單次替換（長的先比），有網頁版就用 Pro 重新產生。"""
        folder = L.folder
        want = {w for w in data.get("wrong") or [] if isinstance(w, str)}
        pairs = [(a, v) for a, v in M.sync_pairs(L.full(), L.sess) if a in want]
        if not pairs:
            raise ApiError(400, "empty", "沒有勾選要同步的寫法")
        st = M.stamp()
        plan, written, failed = [], [], []
        for n in M.MINUTES_FILES:
            p = folder / n
            if not p.exists():
                continue
            new, hits = M.apply_pairs(p.read_text(encoding="utf-8"), pairs)
            if not hits:
                continue
            html = p.with_suffix(".html")
            bak = bak_name(folder, p.stem, p.suffix, st)
            plan.append({"file": n, "edits": sum(hits.values()), "backup": bak, "html": html.name if html.exists() else None})
            if data.get("dry_run"):
                continue
            try:
                os.replace(p, folder / bak)
                write_text(p, new)
                written.append({"file": n, "edits": sum(hits.values()), "backup": bak})
            except OSError as ex:
                failed.append({"file": n, "reason": err_text(ex)})
                continue
            if html.exists():
                hs = self.S.pro.render_html(folder, n)
                if hs == "ok":
                    written.append({"file": html.name, "backup": None, "detail": "已重新產生（Pro render_html）"})
                else:
                    failed.append({"file": html.name, "reason": f"網頁版沒有重新產生：{hs}"})
        if data.get("dry_run"):
            return self.js(200, {"plan": plan})
        if not written:
            raise ApiError(500, "write", "沒有寫入任何檔案。原因：" + ("；".join(f"{f['file']}：{f['reason']}" for f in failed)
                                                          or "會議記錄裡沒有要改的寫法"), failed=failed)
        edits = sum(w.get("edits", 0) for w in written)
        M.log_op(L.sess, "名詞同步到會議記錄" + ("（部分失敗）" if failed else ""),
                 [w["file"] for w in written] + [w["backup"] for w in written if w.get("backup")], f"{edits} 處")
        try:
            L.save()
        except OSError:
            pass
        self.js(207 if failed else 200, {"written": written, "failed": failed})

    def op_experience_import(self, did: str, d: Doc, L: Loaded, data: dict):
        pro = self.S.pro
        cp, gp = pro.corrections_path(), pro.glossary_path()
        ex = experience_of(self.S, L)
        pairs, terms, skipped = M.pick_imports(ex, data.get("corrections"), data.get("glossary"))
        if not pairs and not terms:
            raise ApiError(400, "empty", "沒有勾選可以匯入的項目")
        st = M.stamp()
        if data.get("dry_run"):
            plan = []
            if pairs:
                plan.append({"file": "$MMH/corrections.tsv", "rows": len(pairs), "what": f"固定錯誤對照表：檔尾加入 {len(pairs)} 筆",
                             "backup": f"$MMH/backups/corrections.{st}.tsv" if cp.exists() else None})
            if terms:
                plan.append({"file": "$MMH/glossary.txt", "rows": len(terms), "what": f"詞表：檔尾加入 {len(terms)} 個",
                             "backup": f"$MMH/backups/glossary.{st}.txt" if gp.exists() else None})
            return self.js(200, {"plan": plan, "corrections": [list(x) for x in pairs], "glossary": terms,
                                 "skipped": skipped})
        today = time.strftime("%Y-%m-%d")
        src_name = re.sub(r"_minutes$", "", L.folder.name)
        rec = {"at": M.now_iso(), "corrections": [list(p) for p in pairs], "glossary": terms, "backups": {}}
        written = []
        try:
            if pairs:
                rec["backups"]["corrections.tsv"] = pro.backup_corrections(st)
                pro.append_corrections([(a, b, f"proofread:{today} {src_name}") for a, b in pairs])
                rec["after_corrections"] = M.sha256_text(cp.read_text(encoding="utf-8"))
                written.append({"file": "$MMH/corrections.tsv", "rows": len(pairs),
                                "backup": mmh_rel(rec["backups"]["corrections.tsv"]) or "（原本沒有這個檔，不用備份）"})
            if terms:
                rec["backups"]["glossary.txt"] = backup_glossary(gp, self.S.home / "backups", st)
                old = gp.read_text(encoding="utf-8") if gp.exists() else ""
                if old and not old.endswith("\n"):
                    old += "\n"
                write_text(gp, old + "".join(t + "\n" for t in terms))
                rec["after_glossary"] = M.sha256_text(gp.read_text(encoding="utf-8"))
                written.append({"file": "$MMH/glossary.txt", "rows": len(terms),
                                "backup": mmh_rel(rec["backups"]["glossary.txt"]) or "（原本沒有這個檔，不用備份）"})
        except OSError as ex:
            if written:
                L.sess.setdefault("imports", []).append(rec)
                M.log_op(L.sess, "匯入對照表與詞表（部分失敗）", [w["file"] for w in written], "")
                try:
                    L.save()
                except OSError:
                    pass
                return self.js(207, {"written": written, "failed": [{"file": "$MMH/glossary.txt", "reason": err_text(ex)}]})
            raise ApiError(500, "write", f"沒有寫入任何檔案。原因：{err_text(ex)}") from None
        L.sess.setdefault("imports", []).append(rec)
        M.log_op(L.sess, "匯入對照表與詞表", [w["file"] for w in written] + [w["backup"] for w in written
                                                                     if w["backup"].startswith("$MMH")],
                 f"對照表 {len(pairs)} 筆、詞表 {len(terms)} 個")
        try:
            L.save()
        except OSError:
            pass
        self.js(200, {"written": written, "failed": [], "skipped": skipped, "corrections": len(pairs),
                      "glossary": len(terms)})

    def op_experience_undo(self, did: str, d: Doc, L: Loaded, data: dict):
        sess = L.sess
        if not sess.get("imports"):
            raise ApiError(400, "none", "沒有可以復原的匯入")
        rec = sess["imports"][-1]
        files = {"corrections.tsv": self.S.pro.corrections_path(), "glossary.txt": self.S.pro.glossary_path()}
        for name, key in (("corrections.tsv", "after_corrections"), ("glossary.txt", "after_glossary")):
            p = files[name]
            if key in rec and (not p.exists() or M.sha256_text(p.read_text(encoding="utf-8")) != rec[key]):
                raise ApiError(409, "modified", f"{name} 在匯入後又被改過，不能自動復原；備份在 backups/")
        if data.get("dry_run"):
            plan = [{"file": f"$MMH/{k}", "what": "還原成匯入前",
                     "backup": f"從 {mmh_rel(v)} 還原" if v else "（原本沒有這個檔：刪除）"} for k, v in rec["backups"].items()]
            return self.js(200, {"plan": plan})
        done = []
        try:
            for name, b in rec["backups"].items():
                p = files[name]
                if b:
                    shutil.copyfile(b, p)
                    done.append({"file": f"$MMH/{name}", "detail": f"已從 {mmh_rel(b)} 還原", "backup": None})
                else:
                    p.unlink(missing_ok=True)
                    done.append({"file": f"$MMH/{name}", "detail": "原本沒有這個檔：已刪除", "backup": None})
        except OSError as ex:
            raise ApiError(500, "write", f"復原沒有完成（{err_text(ex)}）；備份在 backups/", written=done) from None
        sess["imports"].pop()
        M.log_op(sess, "復原上次匯入", [x["file"] for x in done], "用匯入前的備份還原")
        try:
            L.save()
        except OSError:
            pass
        self.js(200, {"written": done, "failed": []})

    def op_redo(self, did: str, d: Doc, L: Loaded, data: dict):
        """用定稿重做會議記錄／筆記（要花費、按了才做）：Pro ≥ 2.3.0 的 auto_minutes.py --source final。"""
        pro = self.S.pro
        if not pro.redo_available:
            raise ApiError(409, "pro_too_old", f"升級 meeting-minutes-pro 到 {P.REDO_MIN_PRO} 以上就能用（目前 {pro.version}）")
        folder = L.folder
        if not (folder / "transcript.final.md").exists():
            raise ApiError(400, "no_final", "請先定稿")
        if d.job and d.job.get("status") == "running":
            raise ApiError(409, "running", "已經在重做了")
        name = "notes.md" if doc_kind(folder) == "notes" else "meeting-minutes.md"
        p = folder / name
        html = p.with_suffix(".html")
        st = M.stamp()
        plan = [{"file": name, "what": "用 transcript.final.md 重新整理（呼叫模型）",
                 "backup": bak_name(folder, p.stem, p.suffix, st) if p.exists() else None},
                {"file": html.name, "what": "網頁版（由 meeting-minutes-pro 重新產生）", "backup": "（由 .md 重新產生，不另備份）"}]
        if data.get("dry_run"):
            try:
                est = pro.estimate(folder)
            except Exception as ex:  # noqa: BLE001
                raise ApiError(500, "estimate", f"沒有寫入任何檔案。原因：取得費用估算失敗（{ex}）") from None
            return self.js(200, {"plan": plan, "estimate": est})
        before = {x.name for x in folder.glob(f"{p.stem}.*.bak{p.suffix}")}
        started = M.now_iso()
        d.job = {"status": "running", "started_at": started, "file": name}
        L.sess["redo"] = {"started_at": started, "status": "running"}
        try:
            L.save()
        except OSError:
            pass
        threading.Thread(target=self.redo_work, args=(d, folder, name, before, started), daemon=True).start()
        self.js(202, {"status": "running"})

    def redo_work(self, d: Doc, folder: Path, name: str, before: set, started: str):
        pro, p = self.S.pro, folder / name
        html = p.with_suffix(".html")
        try:
            proc = pro.popen(pro.auto_minutes_cmd(folder, "--force"))
            out, err = proc.communicate()
            code = proc.returncode
            res = (P.last_json(out) or {}).get("minutes") or {}
        except Exception as ex:  # noqa: BLE001
            code, res, err = 5, {}, str(ex).encode("utf-8")
        baks = sorted({x.name for x in folder.glob(f"{p.stem}.*.bak{p.suffix}")} - before)
        written, failed = [], []
        ok = code == 0 and res.get("status") in ("ok", "partial")
        if ok:
            written.append({"file": name, "backup": baks[-1] if baks else None,
                            "detail": "部分完成" if res.get("status") == "partial" else "已重新整理"})
            hs = (res.get("html") or {}).get("status")
            if hs == "ok":
                written.append({"file": html.name, "backup": None, "detail": "已重新產生"})
            elif hs:
                failed.append({"file": html.name, "reason": f"網頁版沒有重新產生（{(res.get('html') or {}).get('reason') or hs}）"})
        else:
            label = REDO_EXIT.get(code, "失敗")
            msg = res.get("message") or res.get("reason") or P.pro_message(err, code)
            failed.append({"file": name, "reason": f"{label}（exit {code}）：{msg}"})
        cost = res.get("cost_usd")
        job = {"status": "ok" if ok else "failed", "exit": code, "started_at": started, "finished_at": M.now_iso(),
               "file": name, "written": written, "failed": failed, "cost_usd": cost,
               "provider": res.get("provider"), "model": res.get("model")}
        with d.lock:
            d.job = job
            try:
                L = Loaded(self.S, folder)
                L.sess["redo"] = {"started_at": started, "status": job["status"], "finished_at": job["finished_at"]}
                note = f"費用 US${cost}" if cost is not None else "費用見 meeting-minutes-pro 的執行 log"
                M.log_op(L.sess, ("重做會議記錄" if name == "meeting-minutes.md" else "重做筆記") + ("" if ok else "（失敗）"),
                         [w["file"] for w in written] + [w["backup"] for w in written if w.get("backup")], note)
                L.save()
            except Exception:  # noqa: BLE001
                pass


def backup_glossary(path: Path, backups: Path, st: str):
    """glossary.txt → $MMH/backups/glossary.<時間>.txt（同名已存在時加 -1、-2）；檔案不存在回傳 None。"""
    if not path.exists():
        return None
    backups.mkdir(parents=True, exist_ok=True)
    dst, n = backups / f"glossary.{st}.txt", 1
    while dst.exists():
        dst, n = backups / f"glossary.{st}-{n}.txt", n + 1
    shutil.copy2(path, dst)
    return str(dst)


# ---------------------------------------------------------------- 主程式
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="會議記錄校稿的本機服務（由啟動器在背景執行）")
    ap.add_argument("--home", help="meeting-minutes-pro 的資料夾（預設 MEETING_MINUTES_PRO_HOME 或系統預設位置）")
    ap.add_argument("--idle", type=int, help="（測試用）覆寫閒置結束秒數")
    ap.add_argument("--lease-ttl", type=int, default=LEASE_TTL, help="（測試用）編輯權有效秒數")
    ap.add_argument("--login-ttl", type=int, default=LOGIN_TTL, help="（測試用）登入連結有效秒數")
    a = ap.parse_args(argv)
    home = Path(a.home) if a.home else P.data_home()
    res = P.check(home)
    if not res["ok"]:
        return 2
    idle = a.idle if a.idle else tool_config(home)["idle_seconds"]
    S = State(home, res["pro"], idle, a.lease_ttl, a.login_ttl)
    Handler.S = S
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    S.port = httpd.server_address[1]
    inst = S.state_dir / "instance.json"
    write_json(inst, {"pid": os.getpid(), "port": S.port, "secret": S.secret, "version": M.TOOL_VERSION,
                      "started_at": M.now_iso()})
    try:
        vj = read_json(home / "proofread" / "version.json")
        if vj.get("pro_version_at_install") not in (None, res["version"]):
            S.log_line("INFO", f"pro-version-changed {vj.get('pro_version_at_install')}->{res['version']}", "-")
    except (OSError, ValueError, AttributeError):
        pass

    def watch():
        while True:
            time.sleep(0.5)
            if S.closing:
                with S.lock:
                    live = any(S.lease_live(d) for d in S.docs.values())
                if not live or time.time() - S.closing > CLOSING_WAIT:
                    break
            elif not S.busy() and time.time() - S.last > S.idle:
                break
        httpd.shutdown()
    threading.Thread(target=watch, daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.25)
    finally:
        httpd.server_close()
        try:
            if read_json(inst).get("pid") == os.getpid():
                inst.unlink()
        except (OSError, ValueError, AttributeError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
