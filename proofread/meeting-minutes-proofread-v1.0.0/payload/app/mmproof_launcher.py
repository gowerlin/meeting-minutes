"""會議記錄校稿：啟動器。右鍵「傳送到 → 會議記錄校稿」、雙擊「會議記錄校稿.mmproof」、拖到「會議記錄校稿.app」都執行它。

  <Pro 的 pythonw> -B mmproof_launcher.py <資料夾或檔案> …       # 開這些稿（每份一個分頁）
  <Pro 的 pythonw> -B mmproof_launcher.py --home-page              # 只開首頁
  <Pro 的 python>  -B mmproof_launcher.py --shutdown               # 安裝程式升級、移除前：請服務先讓分頁存檔再結束

1. 把傳進來的路徑換成輸出資料夾；不是輸出資料夾的，最後用一個對話框列出。
2. 已有服務（$MMH/proofread/state/instance.json 連得上）→ 交給它；版號不同（升級後舊服務還在跑）→ 請它結束再啟動新版；
   沒有服務 → 檢查 Pro、在背景啟動一個（Windows 用 pythonw＋CREATE_NO_WINDOW，不出命令列視窗）。
   兩個啟動器同時跑時以 start.lock 排隊，只會有一個服務。
3. 用服務回的一次性網址開預設瀏覽器（網址不寫檔、不印出）。錯誤用對話框告知（沒有命令列視窗可以印）。

開發與測試用的參數（使用者不需要）：--home 指定 $MMH；--no-browser 不開瀏覽器、把結果（不含網址）印成 JSON、
錯誤印到 stderr；--url-file 把網址寫到指定檔（測試讀取後刪除）；--idle、--lease-ttl、--login-ttl 傳給新啟動的服務。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import mmproof_model as M  # noqa: E402
import mmproof_pro as P  # noqa: E402

TITLE = "會議記錄校稿"
START_WAIT = 15
LOCK_STALE = 30
STOP_WAIT = 25
DETACHED = 0x00000008 | 0x00000200 | 0x08000000   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
QUIET = {"on": False}


def message(text: str):
    """沒有主控台時用對話框告知（Windows MessageBoxW；macOS osascript）。測試模式印到 stderr。"""
    if QUIET["on"]:
        print(text, file=sys.stderr, flush=True)
        return
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x40)
        elif sys.platform == "darwin":
            esc = text.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(["osascript", "-e", f'display dialog "{esc}" with title "{TITLE}" buttons {{"好"}} default button 1'],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print(text, file=sys.stderr)
    except Exception:  # noqa: BLE001
        print(text, file=sys.stderr)


def read_instance(state: Path):
    try:
        d = json.loads((state / "instance.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and isinstance(d.get("port"), int) and d.get("secret") else None
    except (OSError, ValueError):
        return None


def post_handoff(inst: dict, body: dict, timeout: float = 5):
    """回傳 (HTTP 狀態碼, JSON)；連不上回傳 (None, None)。交接 API 不帶 Origin（瀏覽器無法偽造）。"""
    req = urllib.request.Request(f"http://127.0.0.1:{inst['port']}/api/handoff", method="POST",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-MMP-Handoff": inst["secret"]})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def server_python() -> Path:
    py = Path(sys.executable)
    if sys.platform == "win32" and py.name.lower() == "python.exe" and (py.parent / "pythonw.exe").exists():
        py = py.parent / "pythonw.exe"
    return py


def start_server(home: Path, extra: list):
    cmd = [str(server_python()), "-B", str(HERE / "mmproof_server.py"), "--home", str(home)] + extra
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True,
          "cwd": str(home)}
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MEETING_MINUTES_PRO_HOME=str(home))
    kw["env"] = env
    if sys.platform == "win32":
        kw["creationflags"] = DETACHED
    else:
        kw["start_new_session"] = True
    subprocess.Popen(cmd, **kw)


def wait_gone(state: Path, inst: dict, limit: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < limit:
        cur = read_instance(state)
        if not cur or cur.get("pid") != inst.get("pid"):
            return True
        if post_handoff(cur, {"shutdown": True}, timeout=2)[0] is None:
            return True
        time.sleep(0.3)
    return False


def try_handoff(state: Path, body: dict):
    """回傳 ("ok", 結果)、("none", None)：沒有可用的服務、("stopping", inst)：舊版或正在關閉的服務。"""
    inst = read_instance(state)
    if not inst:
        return "none", None
    if inst.get("version") != M.TOOL_VERSION:
        post_handoff(inst, {"shutdown": True})
        return "stopping", inst
    code, res = post_handoff(inst, body)
    if code is None:
        try:
            (state / "instance.json").unlink()            # 殘留（服務異常結束）
        except OSError:
            pass
        return "none", None
    if code == 503:
        return "stopping", inst
    if code == 200 and isinstance(res, dict):
        return "ok", res
    return "none", None


def ensure_and_handoff(home: Path, body: dict, extra: list):
    """回傳 (結果, 錯誤訊息)。"""
    state = home / "proofread" / "state"
    state.mkdir(parents=True, exist_ok=True)
    kind, res = try_handoff(state, body)
    if kind == "ok":
        return res, None
    if kind == "stopping":
        wait_gone(state, res, STOP_WAIT)
    lock = state / "start.lock"
    deadline = time.time() + START_WAIT
    have_lock = False
    while not have_lock:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            have_lock = True
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE:
                    lock.unlink()                         # 殘留的鎖
                    continue
            except OSError:
                continue
            kind, res = try_handoff(state, body)            # 另一個啟動器正在啟動服務：等它好
            if kind == "ok":
                return res, None
            if time.time() > deadline:
                return None, "start"
            time.sleep(0.2)
    try:
        kind, res = try_handoff(state, body)
        if kind == "ok":
            return res, None
        chk = P.check(home)
        if not chk["ok"]:
            return None, chk["message"]
        start_server(home, extra)
        while time.time() < deadline:
            time.sleep(0.15)
            kind, res = try_handoff(state, body)
            if kind == "ok":
                return res, None
        return None, "start"
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def shutdown(home: Path) -> dict:
    state = home / "proofread" / "state"
    inst = read_instance(state)
    if not inst:
        return {"closing": False, "running": False}
    code, res = post_handoff(inst, {"shutdown": True})
    if code is None:
        return {"closing": False, "running": False}
    gone = wait_gone(state, inst, STOP_WAIT)
    return {"closing": bool(res and res.get("closing")), "running": True, "stopped": gone}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="會議記錄校稿：開啟會議的輸出資料夾（<檔名>_minutes）")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--home-page", action="store_true", help="開首頁（開著的稿與最近的稿）")
    ap.add_argument("--shutdown", action="store_true", help="請執行中的服務先讓分頁存檔再結束（安裝程式用）")
    ap.add_argument("--home", help=argparse.SUPPRESS)
    ap.add_argument("--no-browser", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--url-file", help=argparse.SUPPRESS)
    ap.add_argument("--idle", help=argparse.SUPPRESS)
    ap.add_argument("--lease-ttl", help=argparse.SUPPRESS)
    ap.add_argument("--login-ttl", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    QUIET["on"] = a.no_browser or a.shutdown
    home = Path(a.home) if a.home else P.data_home()
    if a.shutdown:
        print(json.dumps(shutdown(home), ensure_ascii=False))
        return 0
    extra = []
    for k in ("idle", "lease_ttl", "login_ttl"):
        v = getattr(a, k)
        if v:
            extra += ["--" + k.replace("_", "-"), str(v)]
    if not a.paths and not a.home_page:
        a.home_page = True
    body = {"folders": [str(Path(p)) for p in a.paths], "home": a.home_page}
    res, err = ensure_and_handoff(home, body, extra)
    if res is None:
        message(err if err and err != "start" else
                "會議記錄校稿沒有啟動成功。請再試一次；還是不行請重新執行安裝程式。")
        if a.no_browser:
            print(json.dumps({"error": "start" if err == "start" else "pro"}, ensure_ascii=False))
        return 2 if err and err != "start" else 1
    results = res.get("results") or []
    bad = [r["input"] for r in results if r.get("status") == "invalid"]
    urls = [r["url"] for r in results if r.get("url")]
    if a.no_browser:
        print(json.dumps([{k: v for k, v in r.items() if k != "url"} for r in results], ensure_ascii=False))
        if a.url_file:
            Path(a.url_file).write_text("\n".join(urls), encoding="utf-8")
    else:
        for u in urls:
            webbrowser.open(u, new=2)
    if bad:
        message("這些不是會議的輸出資料夾（裡面沒有 transcript.md）：\n" + "\n".join(bad))
    return 0 if urls or not bad else 2


if __name__ == "__main__":
    sys.exit(main())
