"""會議記錄校稿與 meeting-minutes-pro（下稱 Pro）的接點：偵測 Pro、相容檢查、import Pro 的模組、呼叫 Pro。

  <Pro 的 python> -B mmproof_pro.py --check [--home <$MMH>]     # 安裝程式用：印一行 JSON，exit 0 通過、2 不通過

偵測（安裝程式與每次服務啟動都做）：
1. $MMH＝環境變數 MEETING_MINUTES_PRO_HOME，沒有就用 Pro common.data_home() 的預設位置。
2. 必須都存在：$MMH/config.json、$MMH/scripts/common.py、Pro 的 Python（venv）。
3. 版號（$MMH/scripts/common.py 的 VERSION，讀不到用 config.json 的 runtime_version）≥ MIN_PRO。
4. 介面檢查：import Pro 的模組，確認 INTERFACE 列的名稱都在，而且 consistency.MARK_RE 與本工具的標記樣式逐字相同。
   import 前設 sys.dont_write_bytecode，不在 Pro 的 scripts/ 留下 __pycache__。

開發與測試用的環境變數（使用者不需要）：MMPROOF_PRO_SCRIPTS 指到 Pro 的 scripts 目錄、MMPROOF_PRO_PYTHON 指到 Python。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import mmproof_model as M  # noqa: E402

MIN_PRO = "2.2.0"
REDO_MIN_PRO = "2.3.0"
# Portal 的網址不寫進程式（發行物的去識別規則）；訊息指向 Portal 的頁面名稱
PORTAL_INSTALL = "meeting-minutes Portal 的「安裝」頁"
PORTAL_COMPAT = "meeting-minutes Portal 的「安裝會議記錄校稿」頁（版本相容表）"
INTERFACE = {
    "common": ("VERSION", "data_home", "load_config", "setting", "default_glossary", "corrections_path"),
    "consistency": ("MARK_RE", "key_of", "COMMON_WORDS"),
    "corrections": ("load", "backup", "append_rows", "HEADER", "MIN_LEN"),
    "subtitles": ("map_corrected", "recue", "render_srt", "options"),
    "render_html": ("render",),
}
OPTIONAL = ("opencc_keep",)            # 讀不到時當成空的回復表（Pro 2.2.0 有）
VERSION_RE = re.compile(r'^VERSION\s*=\s*["\']([0-9][0-9A-Za-z.\-+]*)["\']', re.M)
NO_WINDOW = 0x08000000                 # CREATE_NO_WINDOW


def parse_version(v) -> tuple:
    nums = []
    for part in re.split(r"[.\-+]", str(v or "")):
        if not part.isdigit():
            break
        nums.append(int(part))
    return tuple((nums + [0, 0, 0])[:3])


def version_ge(v, minimum: str) -> bool:
    return bool(v) and parse_version(v) >= parse_version(minimum)


def data_home() -> Path:
    """同 Pro 2.2.0 common.data_home()。"""
    env = os.environ.get("MEETING_MINUTES_PRO_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "meeting-minutes-pro"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "meeting-minutes-pro"
    return Path.home() / ".cache" / "meeting-minutes-pro"


def scripts_dir(home: Path) -> Path:
    env = os.environ.get("MMPROOF_PRO_SCRIPTS")
    return Path(env) if env else home / "scripts"


def pro_pythons(home: Path) -> list:
    """Pro 的 Python（先列不開視窗的）。"""
    env = os.environ.get("MMPROOF_PRO_PYTHON")
    if env:
        return [Path(env)]
    if sys.platform == "win32":
        return [home / "venv" / "Scripts" / "pythonw.exe", home / "venv" / "Scripts" / "python.exe"]
    return [home / "venv" / "bin" / "python"]


def console_python(home: Path) -> Path:
    """跑 Pro 命令列腳本用的 Python（要讀 stdout）：Windows 用 python.exe（以 CREATE_NO_WINDOW 執行，不出視窗）。"""
    env = os.environ.get("MMPROOF_PRO_PYTHON")
    if env:
        p = Path(env)
    else:
        p = home / "venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if sys.platform == "win32" and p.name.lower() == "pythonw.exe" and (p.parent / "python.exe").exists():
        p = p.parent / "python.exe"
    return p


def read_version(home: Path, scripts: Path):
    try:
        m = VERSION_RE.search((scripts / "common.py").read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except OSError:
        pass
    try:
        return json.loads((home / "config.json").read_text(encoding="utf-8")).get("runtime_version")
    except (OSError, ValueError, AttributeError):
        return None


class Pro:
    """已通過介面檢查的 Pro 模組。所有對 Pro 的呼叫都經過這裡。"""

    def __init__(self, home: Path, scripts: Path, mods: dict, version: str):
        self.home, self.scripts, self.m, self.version = home, scripts, mods, version

    # ---- 標記與詞
    def key_of(self, s: str) -> str:
        return self.m["consistency"].key_of(s)

    @property
    def common_words(self) -> frozenset:
        return frozenset(self.m["consistency"].COMMON_WORDS)

    def config(self) -> dict:
        return self.m["common"].load_config() or {}

    def min_count(self) -> int:
        try:
            v = int(self.m["common"].setting(self.config(), "correction.corrections_auto.min_count"))
            return v if v >= 1 else M.MIN_COUNT
        except Exception:  # noqa: BLE001
            return M.MIN_COUNT

    def corrections_path(self) -> Path:
        return Path(self.m["common"].corrections_path())

    def glossary_path(self) -> Path:
        return Path(self.m["common"].default_glossary())

    def correction_rows(self) -> list:
        return [tuple(r) for r in self.m["corrections"].load(self.corrections_path())]

    def keep_words(self) -> set:
        ok = self.m.get("opencc_keep")
        if ok is None:
            return set()
        try:
            return {row[0] for row in ok.load_merged()}
        except Exception:  # noqa: BLE001
            return set()

    def backup_corrections(self, stamp: str):
        return self.m["corrections"].backup(stamp, self.corrections_path())

    def append_corrections(self, rows: list):
        self.m["corrections"].append_rows(rows, self.corrections_path())

    # ---- 字幕、網頁版、媒體
    def final_srt(self, transcript_doc: dict, resolved_text: str) -> tuple:
        """用 Pro 的字幕對時：map_corrected → recue → render_srt；選項與 transcript.corrected.srt 相同。
        回傳 (srt 文字, 條數, 對應失敗段數)。"""
        sub = self.m["subtitles"]
        o = sub.options(self.config())
        cues, st = sub.map_corrected(transcript_doc, resolved_text, "orig")
        cues = sub.recue(cues, o)
        return sub.render_srt(cues, o["speaker_label"]), len(cues), int(st.get("map_failed_paragraphs") or 0)

    def render_html(self, folder: Path, md_name: str) -> str:
        """重新產生網頁版；回傳 ok 或失敗原因（Pro render_html.render 不丟例外）。"""
        try:
            r = self.m["render_html"].render(folder, md_name, cfg=self.config())
        except Exception as ex:  # noqa: BLE001
            return f"失敗（{type(ex).__name__}）"
        st = r.get("status")
        if st == "ok":
            return "ok"
        return f"{st}（{r.get('reason') or r.get('error') or '原因不明'}）"

    def find_media(self, folder: Path) -> dict:
        rh = self.m["render_html"]
        try:
            meta = json.loads((folder / "transcript.json").read_text(encoding="utf-8")).get("meta") or {}
        except (OSError, ValueError, AttributeError):
            meta = {}
        try:
            return rh.find_media(folder, meta)
        except Exception:  # noqa: BLE001
            return {"status": "none", "ext": None}

    # ---- 用定稿重做會議記錄（Pro ≥ 2.3.0）
    @property
    def redo_available(self) -> bool:
        return version_ge(self.version, REDO_MIN_PRO)

    def auto_minutes_cmd(self, folder: Path, *extra) -> list:
        return [str(console_python(self.home)), "-B", str(self.scripts / "auto_minutes.py"), str(folder),
                "--source", "final", *extra]

    def run_env(self) -> dict:
        env = dict(os.environ)
        env.update(MEETING_MINUTES_PRO_HOME=str(self.home), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
                   PYTHONIOENCODING="utf-8")
        return env

    def popen(self, cmd: list) -> subprocess.Popen:
        """以參數陣列執行（不經 shell），不出命令列視窗。"""
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "env": self.run_env(),
              "cwd": str(self.home) if self.home.is_dir() else None}
        if sys.platform == "win32":
            kw["creationflags"] = NO_WINDOW
        return subprocess.Popen(cmd, **kw)

    def estimate(self, folder: Path, timeout: float = 60) -> dict:
        """auto_minutes.py --source final --estimate-only → {"provider","model","usd_low","usd_high","chars",…}。"""
        p = self.popen(self.auto_minutes_cmd(folder, "--estimate-only"))
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            p.kill()
            raise RuntimeError("預估逾時") from None
        data = last_json(out)
        if p.returncode != 0 or not isinstance(data, dict) or not isinstance(data.get("estimate"), dict):
            raise RuntimeError(pro_message(err, p.returncode))
        return data["estimate"]


def last_json(raw: bytes):
    for line in reversed((raw or b"").decode("utf-8", "replace").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def pro_message(err: bytes, code) -> str:
    lines = [ln.strip() for ln in (err or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
    tail = lines[-1] if lines else ""
    return f"meeting-minutes-pro 回報錯誤（exit {code}）" + (f"：{tail[:300]}" if tail else "")


def load_modules(scripts: Path) -> dict:
    sys.dont_write_bytecode = True
    s = str(scripts)
    if s not in sys.path:
        sys.path.insert(0, s)
    import importlib
    mods = {name: importlib.import_module(name) for name in INTERFACE}
    for name in OPTIONAL:
        try:
            mods[name] = importlib.import_module(name)
        except Exception:  # noqa: BLE001
            mods[name] = None
    return mods


def interface_missing(mods: dict) -> list:
    missing = [f"{mod}.{n}" for mod, names in INTERFACE.items() for n in names if not hasattr(mods[mod], n)]
    mr = getattr(mods["consistency"], "MARK_RE", None)
    if mr is not None and getattr(mr, "pattern", None) != M.MARK_PATTERN:
        missing.append("consistency.MARK_RE（標記格式不同）")
    return missing


_CACHE = {}


def check(home: Path | None = None, need_python: bool = True) -> dict:
    """回傳 {"ok", "code": ok|no_pro|too_old|incompatible, "version", "message", "missing"}；通過時另有 "pro"（Pro 物件）。"""
    home = Path(home) if home else data_home()
    scripts = scripts_dir(home)
    need = [home / "config.json", scripts / "common.py"]
    lacking = [p for p in need if not p.exists()]
    if need_python and not any(p.exists() for p in pro_pythons(home)):
        lacking.append(pro_pythons(home)[0])
    if lacking:
        return {"ok": False, "code": "no_pro", "version": None, "missing": [p.name for p in lacking],
                "message": f"請先安裝 meeting-minutes-pro {MIN_PRO} 以上。安裝方法見 {PORTAL_INSTALL}。"}
    ver = read_version(home, scripts)
    if not version_ge(ver, MIN_PRO):
        return {"ok": False, "code": "too_old", "version": ver, "missing": [],
                "message": f"meeting-minutes-pro 版本 {ver or '不明'} 太舊，請先升級到 {MIN_PRO} 以上。"}
    key = (str(home), str(scripts))
    if key in _CACHE:
        return _CACHE[key]
    os.environ["MEETING_MINUTES_PRO_HOME"] = str(home)
    try:
        mods = load_modules(scripts)
        missing = interface_missing(mods)
    except Exception as ex:  # noqa: BLE001
        mods, missing = None, [f"import 失敗（{type(ex).__name__}）"]
    if missing:
        res = {"ok": False, "code": "incompatible", "version": ver, "missing": missing,
               "message": (f"這版會議記錄校稿與目前的 meeting-minutes-pro {ver} 不相容，請到 {PORTAL_COMPAT}"
                           "下載相容的版本。")}
    else:
        res = {"ok": True, "code": "ok", "version": ver, "missing": [], "message": "",
               "pro": Pro(home, scripts, mods, ver)}
    _CACHE[key] = res
    return res


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if k != "pro"}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="檢查 meeting-minutes-pro 是否可以搭配這版會議記錄校稿")
    ap.add_argument("--check", action="store_true", required=True)
    ap.add_argument("--home", help="meeting-minutes-pro 的資料夾（預設 MEETING_MINUTES_PRO_HOME 或系統預設位置）")
    a = ap.parse_args(argv)
    res = check(Path(a.home) if a.home else None)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(public(res), ensure_ascii=False))
    return 0 if res["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
