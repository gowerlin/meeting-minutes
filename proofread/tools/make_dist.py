#!/usr/bin/env python3
"""會議記錄校稿的發行檔打包。

用法（在 repo 任意位置執行皆可）：

    python -B <proofread 目錄>/tools/make_dist.py                                   # 版號最高的 meeting-minutes-proofread-v*
    python -B .../tools/make_dist.py meeting-minutes-proofread-v1.0.0               # 指定版本目錄
    python -B .../tools/make_dist.py --out-dir <資料夾>                              # 輸出到指定資料夾（預設 <proofread 目錄>/dist/）

產生到 dist/（不進版控）：

- `meeting-minutes-proofread-v<版號>-installer.zip`：唯一的發行檔。內容是版本目錄裡 `git ls-files` 列出的檔案（取自工作目錄），
  根目錄 `meeting-minutes-proofread-v<版號>/`；`.sh`／`.command` 權限 755，其餘 644；不含 `tests/`、`_out/`、`__pycache__`。
- `meeting-minutes-proofread-v<版號>-installer.zip.sha256`（`<hex>  <檔名>`）。

打包前檢查（任何一項不符就報錯停止、exit 2，不產生檔案）：

1. 版號一致：`payload/app/mmproof_model.py` 的 `TOOL_VERSION`、`install.ps1` 的 `$Version`、`install.sh` 的 `VERSION`、
   README 標題下的「版本 X」、版本目錄名稱。
2. 必要檔都有，而且沒有清單以外的檔（安裝包內容固定）。
3. 換行與編碼：`.cmd` 是 CRLF 而且只有 ASCII（cmd.exe 的限制）；`.ps1` 是 UTF-8 帶 BOM（Windows PowerShell 5.1 才不會把中文讀錯）；
   `.sh`／`.command`／`.py` 沒有 CR。
4. 不含 Portal 與外部網址：只允許本機 `http://127.0.0.1`／`http://localhost`。

只用 Python 標準函式庫；Windows／macOS 皆可執行，需要 `git` 指令。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # meeting-minutes-proofread/
DIR_PREFIX = "meeting-minutes-proofread-v"
EXCLUDED_PARTS = {"tests", "_out", "__pycache__"}
EXEC_SUFFIXES = (".sh", ".command")
# 安裝包的內容（規格 §2.1；另加安裝到 proofread/ 的 uninstall.ps1、uninstall.sh）
REQUIRED = (
    "install.cmd", "install.command", "install.ps1", "install.sh",
    "uninstall.cmd", "uninstall.command", "uninstall.ps1", "uninstall.sh",
    "README.md", "LICENSE",
    "payload/app/mmproof_launcher.py", "payload/app/mmproof_model.py", "payload/app/mmproof_pro.py",
    "payload/app/mmproof_server.py",
    "payload/app/static/app.html", "payload/app/static/app.js", "payload/app/static/app.css",
)
VERSIONS = (
    ("payload/app/mmproof_model.py", re.compile(r'^TOOL_VERSION\s*=\s*"([^"]+)"', re.M), "mmproof_model.py TOOL_VERSION"),
    ("install.ps1", re.compile(r'^\$Version\s*=\s*"([^"]+)"', re.M), "install.ps1 $Version"),
    ("install.sh", re.compile(r'^VERSION="([^"]+)"', re.M), "install.sh VERSION"),
    ("README.md", re.compile(r"^>\s*版本\s*([0-9][^\s｜|]*)", re.M), "README 標題下的版本"),
)
URL_RE = re.compile(r"https?://[^\s\"'`<>)）]+", re.I)
LOCAL_URL_RE = re.compile(r"^http://(127\.0\.0\.1|localhost)([:/]|$)", re.I)
TEXT_SUFFIXES = (".py", ".ps1", ".sh", ".command", ".cmd", ".md", ".html", ".js", ".css", "")


class DistError(Exception):
    """打包前檢查失敗。"""


def _version_key(name: str) -> tuple:
    ver = name[len(DIR_PREFIX):]
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\-]", ver))


def find_version_dir(arg: str | None, root: Path = ROOT) -> Path:
    if arg:
        path = Path(arg)
        if not path.is_absolute():
            path = (root / path) if (root / path).is_dir() else path.resolve()
        if not path.is_dir():
            raise DistError(f"找不到版本目錄：{arg}")
        return path.resolve()
    cands = [p for p in root.iterdir() if p.is_dir() and p.name.startswith(DIR_PREFIX) and p.name[len(DIR_PREFIX):][:1].isdigit()]
    if not cands:
        raise DistError(f"{root} 底下沒有 {DIR_PREFIX}* 版本目錄")
    return max(cands, key=lambda p: _version_key(p.name))


def read_version(version_dir: Path) -> str:
    found, errors = {}, []
    for rel, pat, label in VERSIONS:
        f = version_dir / rel
        if not f.is_file():
            errors.append(f"找不到 {rel}")
            continue
        m = pat.search(f.read_text(encoding="utf-8-sig"))
        if not m:
            errors.append(f"{label}：找不到版號")
        else:
            found[label] = m.group(1)
    if errors:
        raise DistError("版號檢查失敗：\n  - " + "\n  - ".join(errors))
    version = found[VERSIONS[0][2]]
    for label, v in found.items():
        if v != version:
            errors.append(f"{label} {v} ≠ mmproof_model.py TOOL_VERSION {version}")
    if version_dir.name != f"{DIR_PREFIX}{version}":
        errors.append(f"版本目錄名稱 {version_dir.name} ≠ {DIR_PREFIX}{version}")
    if errors:
        raise DistError("版號不一致：\n  - " + "\n  - ".join(errors))
    return version


def tracked_files(version_dir: Path) -> list[str]:
    """版本目錄內 git 追蹤的檔案（相對於版本目錄，POSIX 分隔）。"""
    try:
        out = subprocess.run(["git", "-C", str(version_dir), "ls-files", "-z", "--", "."],
                             check=True, capture_output=True).stdout
    except FileNotFoundError:
        raise DistError("找不到 git 指令") from None
    except subprocess.CalledProcessError as exc:
        raise DistError(f"git ls-files 失敗：{exc.stderr.decode(errors='replace').strip()}") from None
    files = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        if EXCLUDED_PARTS.intersection(rel.split("/")):
            continue
        if not (version_dir / rel).is_file():
            raise DistError(f"git 追蹤但工作目錄沒有這個檔：{rel}")
        files.append(rel)
    return sorted(files)


def check_file_list(files: list[str]) -> None:
    missing = [f for f in REQUIRED if f not in files]
    extra = [f for f in files if f not in REQUIRED]
    errors = []
    if missing:
        errors.append("缺少（或還沒 git add）：" + "、".join(missing))
    if extra:
        errors.append("清單以外的檔：" + "、".join(extra))
    if errors:
        raise DistError("安裝包檔案清單不符：\n  - " + "\n  - ".join(errors))


def check_encoding(version_dir: Path, files: list[str]) -> list[str]:
    """回傳檢查過的項目；不符就丟 DistError。"""
    errors = []
    for rel in files:
        b = (version_dir / rel).read_bytes()
        name = rel.lower()
        if name.endswith(".cmd"):
            if b.replace(b"\r\n", b"").count(b"\n") or b.replace(b"\r\n", b"").count(b"\r"):
                errors.append(f"{rel}：要全部是 CRLF 換行")
            if any(c > 0x7F for c in b):
                errors.append(f"{rel}：只能有 ASCII 字元")
        elif name.endswith(".ps1"):
            if not b.startswith(b"\xef\xbb\xbf"):
                errors.append(f"{rel}：要是 UTF-8 帶 BOM（Windows PowerShell 5.1 才讀得懂中文）")
        elif name.endswith((".sh", ".command", ".py")):
            if b"\r" in b:
                errors.append(f"{rel}：不能有 CR（要 LF 換行）")
        if name.endswith(TEXT_SUFFIXES) or "." not in name.rsplit("/", 1)[-1]:
            try:
                b.decode("utf-8-sig")
            except UnicodeDecodeError:
                errors.append(f"{rel}：不是 UTF-8")
    if errors:
        raise DistError("換行與編碼檢查失敗：\n  - " + "\n  - ".join(errors))
    return [".cmd CRLF＋ASCII", ".ps1 UTF-8 BOM", ".sh／.command／.py LF"]


def check_urls(version_dir: Path, files: list[str]) -> int:
    """不含 Portal 與外部網址（只允許本機）。回傳掃過的檔數。"""
    bad = []
    for rel in files:
        text = (version_dir / rel).read_bytes().decode("utf-8-sig", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for m in URL_RE.finditer(line):
                if not LOCAL_URL_RE.match(m.group(0)):
                    bad.append(f"{rel}:{n}")
    if bad:
        raise DistError("含有外部網址（產品只寫 Portal 頁面名稱，不寫網址）：\n  - " + "\n  - ".join(bad))
    return len(files)


def build_installer(version_dir: Path, files: list[str], dest: Path) -> None:
    root = version_dir.name + "/"
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in files:
            src = version_dir / rel
            mtime = time.localtime(max(src.stat().st_mtime, 315532800))  # zip 最早 1980-01-01
            info = zipfile.ZipInfo(root + rel, date_time=mtime[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if rel.endswith(EXEC_SUFFIXES) else 0o644
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, src.read_bytes())


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_atomic(dest: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=".tmp-", suffix=dest.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, dest)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def make(version_arg: str | None = None, out_dir: str | None = None, root: Path = ROOT) -> dict:
    version_dir = find_version_dir(version_arg, root)
    version = read_version(version_dir)
    files = tracked_files(version_dir)
    check_file_list(files)
    enc = check_encoding(version_dir, files)
    scanned = check_urls(version_dir, files)

    dist_dir = Path(out_dir).resolve() if out_dir else root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    name = f"{DIR_PREFIX}{version}-installer.zip"
    installer = dist_dir / name
    tmp = dist_dir / f".tmp-{name}"
    try:
        build_installer(version_dir, files, tmp)
        os.replace(tmp, installer)
    finally:
        if tmp.exists():
            tmp.unlink()
    digest = sha256_of(installer)
    write_atomic(installer.with_name(name + ".sha256"), f"{digest}  {name}\n".encode("ascii"))
    return {"version": version, "installer": installer, "files": files, "size": installer.stat().st_size,
            "sha256": digest, "encoding": enc, "url_scanned": scanned}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="產生會議記錄校稿的發行檔到 dist/")
    ap.add_argument("version_dir", nargs="?", help="版本目錄（預設：版號最高的 meeting-minutes-proofread-v*）")
    ap.add_argument("--out-dir", help="輸出資料夾（預設：<proofread 目錄>/dist）")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = make(args.version_dir, args.out_dir)
    except DistError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 2
    print(f"會議記錄校稿 版號 {r['version']}（mmproof_model.py、install.ps1、install.sh、README、目錄名稱一致）")
    print(f"檔案清單：{len(r['files'])} 檔，與安裝包內容一致；{'、'.join(r['encoding'])}；外部網址 0（掃 {r['url_scanned']} 檔）")
    print(f"{r['installer'].name}：{r['size']:,} bytes，sha256 {r['sha256']}")
    print(f".sha256 已寫入 {r['installer'].parent}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
