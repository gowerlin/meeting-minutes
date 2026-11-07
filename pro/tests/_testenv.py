"""測試共用設定：把版本目錄（預設 v2.1.0；MMP_TEST_VERSION=2.0.2、1.2.2 等可改測舊版）的 scripts 放上 sys.path，
並讓 MEETING_MINUTES_PRO_HOME 指向測試 home。

測試一律不碰已安裝的 runtime：沒有設定 MEETING_MINUTES_PRO_HOME 時，自動建一個暫存目錄當測試 home。
要用真的標點模型（Punctuator 的實測），把 MEETING_MINUTES_PRO_HOME 指向已下載模型的測試 home。
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = os.environ.get("MMP_TEST_VERSION", "2.1.0")
VER = tuple(int(x) for x in VERSION.split("."))
# 〔1.2.2〕console 與輸出檔的分段單位：1.2.2 起「段」（「17 塊」在台灣易誤讀成 17 元），1.2.1 以前「塊」
CHUNK_UNIT = "段" if VER >= (1, 2, 2) else "塊"
VERSION_DIR = HERE.parent / f"meeting-minutes-pro-v{VERSION}"
SCRIPTS = VERSION_DIR / "payload" / "runtime" / "scripts"
RUNTIME = SCRIPTS.parent

# 〔2.0.0〕防呆：測試不得寫入真實安裝。匯入時記下真實安裝 config.json 的修改時間與 SHA-256（只讀），
# 行程結束時再比一次；不同就印出原因並以 exit 3 結束（unittest、entry_harness 等匯入本模組的程式都適用）。
def real_home() -> Path:
    """真實安裝的位置（不看 MEETING_MINUTES_PRO_HOME：那是測試自己設的）。"""
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "meeting-minutes-pro"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "meeting-minutes-pro"
    return Path.home() / ".cache" / "meeting-minutes-pro"


def file_stamp(path: Path):
    """(修改時間 ns, SHA-256)；檔案不存在回傳 None。"""
    import hashlib
    try:
        return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


REAL_CONFIG = real_home() / "config.json"
_REAL_CONFIG_STAMP = file_stamp(REAL_CONFIG)


def real_install_changed() -> bool:
    return file_stamp(REAL_CONFIG) != _REAL_CONFIG_STAMP


def _guard_real_install():
    if real_install_changed():
        print("", file=sys.stderr)
        print(f"[測試防呆] 真實安裝的 {REAL_CONFIG} 在測試期間被寫入了：某個測試沒有把 MEETING_MINUTES_PRO_HOME 指到測試位置。"
              "請找出原因（不要手動改回真實設定），修好後再跑。", file=sys.stderr, flush=True)
        os._exit(3)


import atexit  # noqa: E402
atexit.register(_guard_real_install)

if not os.environ.get("MEETING_MINUTES_PRO_HOME"):
    os.environ["MEETING_MINUTES_PRO_HOME"] = tempfile.mkdtemp(prefix="mmp-test-home-")
sys.path.insert(0, str(SCRIPTS))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
