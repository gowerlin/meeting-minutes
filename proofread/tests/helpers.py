"""測試共用：路徑、暫存區的假 $MMH、啟動器、模擬瀏覽器分頁、結果紀錄。

所有測試都在系統暫存區的副本裡跑：不碰真實安裝（%LOCALAPPDATA%\\meeting-minutes-pro、~/.claude/skills）、
不碰真實的 corrections.tsv／glossary.txt、不呼叫模型。Pro 的模組從 repo 內 Pro 版本目錄的 scripts 唯讀 import
（環境變數 MMPROOF_PRO_SCRIPTS），並設 PYTHONDONTWRITEBYTECODE=1，不在 Pro 的目錄留下 __pycache__。
"""
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
APP = ROOT / "meeting-minutes-proofread-v1.0.0" / "payload" / "app"
LAUNCHER = APP / "mmproof_launcher.py"
SKILLS = ROOT.parent
PRO_VERSION_DIR = "meeting-minutes-pro-v2.2.0"
PRO_SCRIPTS = Path(os.environ.get("MMPROOF_TEST_PRO_SCRIPTS")
                   or SKILLS / "meeting-minutes-pro-skill" / PRO_VERSION_DIR / "payload" / "runtime" / "scripts")
OUT = TESTS / "_out"
for p in (str(TESTS), str(APP)):
    if p not in sys.path:
        sys.path.insert(0, p)
import materials  # noqa: E402

FAKE_CORRECTIONS = "# 測試用假檔（使用者原本的註解）\n酷伯內蒂斯\tKubernetes\t示範\n"
FAKE_GLOSSARY = "# 測試用假詞表\n星河物流\n"


def base_env(home: Path, scripts: Path = PRO_SCRIPTS) -> dict:
    env = dict(os.environ)
    env.update(PYTHONDONTWRITEBYTECODE="1", MMPROOF_NO_REVEAL="1", MEETING_MINUTES_PRO_HOME=str(home),
               MMPROOF_PRO_SCRIPTS=str(scripts), MMPROOF_PRO_PYTHON=sys.executable, PYTHONUTF8="1")
    return env


def apply_env(home: Path, scripts: Path = PRO_SCRIPTS):
    os.environ.update(base_env(home, scripts))


def make_home(root: Path, name: str = "home", config: dict | None = None) -> Path:
    home = root / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.json").write_text(json.dumps(config or {"runtime_version": "2.2.0"}), encoding="utf-8")
    (home / "corrections.tsv").write_text(FAKE_CORRECTIONS, encoding="utf-8", newline="\n")
    (home / "glossary.txt").write_text(FAKE_GLOSSARY, encoding="utf-8", newline="\n")
    return home


def workdir(prefix: str = "mmproof-test-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


class Results:
    def __init__(self, group: str):
        self.group, self.cases = group, []

    def rec(self, name: str, ok: bool, detail: str = "") -> bool:
        self.cases.append({"group": self.group, "case": name, "result": "PASS" if ok else "FAIL", "detail": detail})
        print(("PASS " if ok else "FAIL ") + f"[{self.group}] {name}" + (f"：{detail}" if detail else ""), flush=True)
        return ok

    def check(self, name: str, fn):
        try:
            ok, detail = fn()
        except Exception as ex:  # noqa: BLE001
            ok, detail = False, f"例外 {type(ex).__name__}：{ex}"
        return self.rec(name, ok, detail)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c["result"] == "PASS")


def launch(home: Path, paths, extra=(), env=None, idle="15", lease="6") -> tuple:
    """回傳 (結果清單, 網址清單, exit code, stderr)。網址只存在測試記憶體裡，用完即丟。"""
    fd, ufn = tempfile.mkstemp(suffix=".txt")
    os.close(fd)
    uf = Path(ufn)
    args = [sys.executable, "-B", str(LAUNCHER), "--home", str(home), "--no-browser", "--url-file", str(uf)]
    if idle:
        args += ["--idle", str(idle)]
    if lease:
        args += ["--lease-ttl", str(lease)]
    r = subprocess.run(args + list(extra) + [str(p) for p in paths], capture_output=True, text=True, encoding="utf-8",
                       timeout=90, env=env or base_env(home))
    urls = [u for u in uf.read_text(encoding="utf-8").split("\n") if u] if uf.exists() else []
    uf.unlink(missing_ok=True)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else []
    except ValueError:
        res = []
    return res, urls, r.returncode, r.stderr


def instance(home: Path):
    try:
        return json.loads((home / "proofread" / "state" / "instance.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def port_open(port: int) -> bool:
    s = socket.socket()
    s.settimeout(0.5)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True).stdout.decode("mbcs", "replace")
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def wait_exit(home: Path, port: int, limit: float = 40):
    t0 = time.time()
    while time.time() - t0 < limit:
        if not port_open(port) and instance(home) is None:
            return time.time() - t0
        time.sleep(0.3)
    return None


def stop(home: Path):
    """測試結束：請服務結束並等它離開。"""
    inst = instance(home)
    if not inst:
        return
    subprocess.run([sys.executable, "-B", str(LAUNCHER), "--home", str(home), "--shutdown"], capture_output=True,
                   env=base_env(home), timeout=60)
    wait_exit(home, inst["port"], 20)


def kill(pid: int):
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


class Tab:
    """一個瀏覽器（cookie 罐）＋一個分頁 id。"""

    def __init__(self, port: int, name: str):
        self.port, self.tab = port, name
        self.jar = http.cookiejar.CookieJar()

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def req(self, method: str, path: str, body=None, headers=None, origin=True, raw: bytes | None = None):
        h = {"X-MMP": "1"}
        if origin:
            h["Origin"] = f"http://127.0.0.1:{self.port}"
        data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
        if data is not None:
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method, headers=h, data=data)
        try:
            with self.op.open(r, timeout=30) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def js(self, method: str, path: str, body=None, **kw):
        st, raw, _ = self.req(method, path, body, **kw)
        try:
            return st, json.loads(raw.decode("utf-8"))
        except ValueError:
            return st, None

    def login(self, url: str) -> int:
        path = url.split(f":{self.port}", 1)[1]
        st, _, _ = self.req("GET", path, origin=False)
        return st

    def heartbeat(self, did: str):
        """真的分頁每 10 秒送一次心跳；測試在每次寫入前送一次（不接手，別的分頁持有時仍是唯讀）。"""
        b = json.dumps({"tab": self.tab}).encode("utf-8")
        self.req("POST", f"/api/doc/{did}/lease", raw=b)

    def post(self, did: str, op: str, body: dict | None = None):
        b = {"tab": self.tab}
        b.update(body or {})
        if op not in ("lease", "bye"):
            self.heartbeat(did)
        return self.js("POST", f"/api/doc/{did}/{op}", b)

    def lease(self, did: str, takeover=False):
        return self.post(did, "lease", {"takeover": takeover})

    def data(self, did: str):
        return self.js("GET", f"/api/doc/{did}/data")

    def save(self, did: str, base_rev: int, marks: dict, manual: list, **extra):
        b = {"tab": self.tab, "base_rev": base_rev, "marks": marks, "manual": manual}
        b.update(extra)
        self.heartbeat(did)
        return self.js("PUT", f"/api/doc/{did}/session", b)


def raw_http(port: int, request: bytes, timeout: float = 5) -> bytes:
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        s.sendall(request)
        buf = b""
        while True:
            try:
                chunk = s.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            if b"\r\n\r\n" in buf:
                head, _, rest = buf.partition(b"\r\n\r\n")
                n = next((int(ln.split(b":", 1)[1]) for ln in head.split(b"\r\n") if ln.lower().startswith(b"content-length")), 0)
                if len(rest) >= n:
                    break
        return buf
    finally:
        s.close()


def marks_of(data: dict) -> dict:
    return {m["id"]: m for b in data["doc"]["body"] if b["t"] == "para" for m in b["tokens"] if m["t"] == "mark"}


def para_raws(data: dict) -> list:
    return ["".join(t["src"] if t["t"] == "mark" else t["text"] for t in b["tokens"])
            for b in data["doc"]["body"] if b["t"] == "para"]


def d1_decisions(data: dict) -> tuple:
    """D1 的一組標準決定：校正類都接受、待確認第一個選推測、其他確認原文；3 處人工修改（密等→冪等、退幣→退避 ×2）。"""
    marks = marks_of(data)
    raws = para_raws(data)
    dec = {i: {"choice": "suggest"} for i, m in marks.items() if m["kind"] in ("fix", "unify", "delete", "insert")}
    unc = [i for i, m in marks.items() if m["kind"] == "uncertain"]
    dec[unc[0]] = {"choice": "guess"}
    for i in unc[1:]:
        dec[i] = {"choice": "orig"}

    def man(uid, pi, text, value):
        s = raws[pi].index(text)
        return {"id": uid, "para": pi, "start": s, "end": s + len(text), "orig": text, "value": value}
    manual = [man("u1", 1, "密等", "冪等"), man("u2", 2, "退幣", "退避"), man("u3", 8, "退幣", "退避")]
    return dec, manual
