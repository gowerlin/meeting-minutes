"""〔1.1.0〕測試用的位置：本工具與 meeting-minutes-pro（下稱 Pro）的版本目錄。開發 repo 與公開 repo 的配置都能用。

  開發 repo：<repo>/Meeting-Minutes-Skills/meeting-minutes-proofread/tests  ＋  …/meeting-minutes-pro-skill/meeting-minutes-pro-v<X.Y.Z>/
  公開 repo：<repo>/proofread/tests                                         ＋  <repo>/pro/meeting-minutes-pro-v<X.Y.Z>/

本工具的版本目錄：tests 的上一層裡版號最高的 meeting-minutes-proofread-v<X.Y.Z>。
Pro 的 scripts：環境變數 MMPROOF_TEST_PRO_SCRIPTS（scripts 目錄）→ MMPROOF_TEST_PRO_DIR（Pro 版本目錄）→ 開發 repo 的
meeting-minutes-pro-skill/ → 公開 repo 的 pro/（後兩者取版號最高的版本目錄）。Pro 的版號一律讀 scripts/common.py 的 VERSION，
測試依實際版號判斷（例：Pro ≥ 2.3.0 時「用定稿重做」可用）。
"""
import os
import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent                      # meeting-minutes-proofread/（開發 repo）或 proofread/（公開 repo）
SKILLS = ROOT.parent                     # Meeting-Minutes-Skills/（開發 repo）或 repo 根目錄（公開 repo）
PROOF_PREFIX = "meeting-minutes-proofread-v"
PRO_PREFIX = "meeting-minutes-pro-v"
DEV_PRO_PARENT = SKILLS / "meeting-minutes-pro-skill"
PUBLIC_PRO_PARENT = SKILLS / "pro"
IS_DEV_REPO = DEV_PRO_PARENT.is_dir()    # 公開 repo 沒有 meeting-minutes-pro-skill/
VERSION_RE = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.M)


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.split("."))


def version_dirs(parent: Path, prefix: str) -> list:
    """parent 底下的 <prefix><X.Y.Z> 目錄，依版號由小到大（數字比較）。"""
    out = []
    for p in parent.iterdir() if parent.is_dir() else []:
        rest = p.name[len(prefix):] if p.is_dir() and p.name.startswith(prefix) else ""
        if re.fullmatch(r"\d+\.\d+\.\d+", rest):
            out.append((vtuple(rest), p))
    return [p for _, p in sorted(out)]


def latest(parent: Path, prefix: str) -> Path | None:
    ds = version_dirs(parent, prefix)
    return ds[-1] if ds else None


def pro_parent() -> Path | None:
    for p in (DEV_PRO_PARENT, PUBLIC_PRO_PARENT):
        if version_dirs(p, PRO_PREFIX):
            return p
    return None


def pro_scripts() -> Path:
    env = os.environ.get("MMPROOF_TEST_PRO_SCRIPTS")
    if env:
        return Path(env)
    env = os.environ.get("MMPROOF_TEST_PRO_DIR")
    if env:
        return Path(env) / "payload" / "runtime" / "scripts"
    parent = pro_parent()
    if parent is None:
        raise RuntimeError(f"找不到 meeting-minutes-pro 的版本目錄（看過 {DEV_PRO_PARENT} 與 {PUBLIC_PRO_PARENT}）；"
                           "用環境變數 MMPROOF_TEST_PRO_SCRIPTS 指定 scripts 目錄")
    return latest(parent, PRO_PREFIX) / "payload" / "runtime" / "scripts"


def pro_dir(version: str) -> Path | None:
    """repo 內某一版 Pro 的版本目錄（公開 repo 只有最新版；沒有就 None）。"""
    parent = pro_parent()
    p = parent / f"{PRO_PREFIX}{version}" if parent else None
    return p if p and p.is_dir() else None


def read_pro_version(scripts: Path) -> str:
    m = VERSION_RE.search((scripts / "common.py").read_text(encoding="utf-8"))
    return m.group(1) if m else "0.0.0"


VDIR = latest(ROOT, PROOF_PREFIX)
if VDIR is None:
    raise RuntimeError(f"{ROOT} 底下沒有 {PROOF_PREFIX}<X.Y.Z> 版本目錄")
TOOL_VERSION = VDIR.name[len(PROOF_PREFIX):]
APP = VDIR / "payload" / "app"
PRO_SCRIPTS = pro_scripts()
PRO_VERSION = read_pro_version(PRO_SCRIPTS)
PRO_DIR = PRO_SCRIPTS.parent.parent.parent      # <版本目錄>/payload/runtime/scripts → <版本目錄>
