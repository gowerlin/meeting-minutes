#!/usr/bin/env python3
"""meeting-minutes 發行檔打包：Pro 版（預設）與基本版（`--product basic`）。

用法（在 repo 任意位置執行皆可）：

    python <pro 目錄>/tools/make_dist.py                              # Pro：版號最高的 meeting-minutes-pro-v*
    python .../tools/make_dist.py meeting-minutes-pro-v2.0.1          # 指定版本目錄
    python .../tools/make_dist.py --product basic                     # 基本版：版號最高的 meeting-minutes-v*
    python .../tools/make_dist.py --product basic --out-dir <資料夾>   # 輸出到指定資料夾（預設 <產品根目錄>/dist/）

產品根目錄：Pro 是本工具上一層（`meeting-minutes-pro-skill/`，公開 repo 是 `pro/`）；基本版是它旁邊的
`meeting-minutes-skill/`（公開 repo 是 `basic/`），先找到哪個用哪個。

產生到 `<產品根目錄>/dist/`（不進版控）：

- `<目錄前綴><版號>-installer.zip`：版本目錄裡 `git ls-files` 列出的檔案，根目錄 `<目錄前綴><版號>/`；
  `.sh`／`.command` 權限 755，其餘 644；不含 `tests/`、`_out/`、`__pycache__`。內容取自工作目錄。
- `<目錄前綴><版號>-claude-app-upload.zip`：payload 裡的上傳用 zip 原檔複製
  （只有 skill 的 `SKILL.md`＋`references/`；〔2.1.0〕起另有 `scripts/` 兩檔；不含任何 zip），給 Claude App 直接上傳。
- 兩個 zip 各一個 `.sha256`（`<hex>  <檔名>`），以及 `README.txt`（兩個檔的用途）。

目錄前綴：Pro `meeting-minutes-pro-v`、基本版 `meeting-minutes-v`。發行檔名例：
`meeting-minutes-pro-v2.0.2-installer.zip`、`meeting-minutes-v1.0.1-claude-app-upload.zip`。

版號取自 `payload/runtime/scripts/common.py` 的 `VERSION`，並檢查版本目錄名稱、SKILL.md 版本註解、
`install.ps1` 的 `$Version`、`install.sh` 的 `VERSION`、README 標題下的「版本 X」一致（1.2.0 起的四處版號）；
任何一項不一致就報錯停止，不產生檔案。舊版目錄沒有的項目（例 install.sh）略過不查。

另查模型權重（2.0.0 起，規格 §9.5）：版本目錄內（不論有沒有被 git 追蹤）只要有 `pytorch_model.bin` 或 `*.npz`
（pyannote 權重的檔名）就報錯停止、exit 2。權重由使用者自己同意 Hugging Face 條件後下載，不得放進安裝包（規格 §8.7）。

〔2.1.0〕網頁版（規格 2.1.0 §6.6、§7.4、H-13）：runtime 有 `payload/runtime/scripts/render_html.py` 的 Pro 版本目錄另查
① `render_html.py` 的 `FALLBACK_VERSION` 等於 `common.py` 的 `VERSION`；② skill 內的 `scripts/render_html.py`、
`scripts/html_template.html` 與 runtime 的同名檔逐位元相同（Claude App 沙盒用的就是 skill 內這兩檔）。不符合就 exit 2。
skill 內這兩檔由打包複製，不手改：

    python .../tools/make_dist.py meeting-minutes-pro-v2.1.0 --sync-skill   # 複製兩檔到 skill/scripts/、重產 payload zip

`--sync-skill` 只更新版本目錄（不產生 dist/）；之後 `git add` 新檔再執行一次（不加 `--sync-skill`）產生發行檔。

〔2.2.0〕參考資料（規格 2.2.0 §5.1、§10）：runtime 有 `payload/runtime/scripts/refs.py` 的 Pro 版本目錄另查
① skill 內沒有 `refs.py`（Claude App 模式由 Claude 自己讀圖與文件，refs.py 不進上傳檔）；② `requirements.txt`、
`requirements-mac.txt` 都有 `pypdf`。不符合就 exit 2，不產生檔案。

只用 Python 標準函式庫；Windows／macOS 皆可執行，需要 `git` 指令。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

TOOLS_PARENT = Path(__file__).resolve().parent.parent
EXCLUDED_PARTS = {"tests", "_out", "__pycache__"}
EXEC_SUFFIXES = (".sh", ".command")
# 模型權重的檔名：版本目錄內出現就不打包（規格 §9.5、§8.7）
WEIGHT_NAMES = ("pytorch_model.bin",)
WEIGHT_SUFFIXES = (".npz",)

VERSION_RE = re.compile(r'^VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
FALLBACK_VERSION_RE = re.compile(r'^FALLBACK_VERSION\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
# 〔2.1.0〕skill 內由打包從 runtime 複製的檔（規格 2.1.0 §7.4；Claude App 沙盒執行 render_html.py 用）
SKILL_SCRIPT_FILES = ("render_html.py", "html_template.html")
# 〔2.2.0〕參考資料（規格 2.2.0 §5.1、§10）：refs.py 只在 runtime；PDF 抽取的套件寫在兩份 requirements
REFS_SCRIPT = "refs.py"
REFS_REQUIREMENTS = ("requirements.txt", "requirements-mac.txt")
# (相對路徑, 版號樣式, 說明)：兩個產品共用
OTHER_VERSIONS = (
    ("install.ps1", re.compile(r'^\$Version\s*=\s*"([^"]+)"', re.MULTILINE), "install.ps1 $Version"),
    ("install.sh", re.compile(r'^VERSION="([^"]+)"', re.MULTILINE), "install.sh VERSION"),
    ("README.md", re.compile(r"^>\s*版本\s*([0-9][^\s]*)", re.MULTILINE), "README 標題下的版本"),
)


@dataclass(frozen=True)
class Product:
    key: str                  # --product 的值
    name: str                 # 顯示名稱（README.txt 標題、錯誤訊息）
    root_candidates: tuple    # 產品根目錄的候選（依序找第一個存在的）
    dir_prefix: str           # 版本目錄前綴，也是發行檔名的前綴
    skill_dir: str            # 版本目錄內的 skill 目錄
    upload_root: str          # upload zip 內的根目錄
    payload_zip: str          # 版本目錄內的 upload zip
    skill_version_re: re.Pattern
    skill_version_label: str  # SKILL.md 版本註解的寫法（錯誤訊息用）
    desktop_zip: str          # 安裝程式放到桌面的上傳用 zip（README.txt 用）

    def root(self) -> Path:
        for p in self.root_candidates:
            if p.is_dir():
                return p
        return self.root_candidates[0]


PRO = Product(
    key="pro", name="meeting-minutes-pro",
    root_candidates=(TOOLS_PARENT,),
    dir_prefix="meeting-minutes-pro-v",
    skill_dir="payload/skill/meeting-minutes-pro",
    upload_root="meeting-minutes-pro/",
    payload_zip="payload/meeting-minutes-pro-upload.zip",
    skill_version_re=re.compile(r"<!--\s*meeting-minutes-pro-version:\s*([^\s>]+)\s*-->"),
    skill_version_label="<!-- meeting-minutes-pro-version: … -->",
    desktop_zip="meeting-minutes-pro-skill-upload.zip",
)
BASIC = Product(
    key="basic", name="meeting-minutes（基本版）",
    root_candidates=(TOOLS_PARENT.parent / "meeting-minutes-skill", TOOLS_PARENT.parent / "basic"),
    dir_prefix="meeting-minutes-v",
    skill_dir="payload/skill/meeting-minutes",
    upload_root="meeting-minutes/",
    payload_zip="payload/meeting-minutes-upload.zip",
    skill_version_re=re.compile(r"<!--\s*meeting-minutes-version:\s*([^\s>]+)\s*-->"),
    skill_version_label="<!-- meeting-minutes-version: … -->",
    desktop_zip="meeting-minutes-skill-upload.zip",
)
PRODUCTS = {p.key: p for p in (PRO, BASIC)}

# Pro 的常數（沿用舊名稱，給既有的呼叫端與測試）
SKILL_ROOT = PRO.root()
DIST_DIR = SKILL_ROOT / "dist"
DIR_PREFIX = PRO.dir_prefix
UPLOAD_ROOT = PRO.upload_root
SKILL_VERSION_RE = PRO.skill_version_re


class DistError(Exception):
    """打包前檢查失敗。"""


def _version_key(name: str, prefix: str = DIR_PREFIX) -> tuple:
    ver = name[len(prefix):]
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.\-]", ver))


def _is_version_name(name: str, prefix: str) -> bool:
    return name.startswith(prefix) and name[len(prefix):][:1].isdigit()


def find_version_dir(arg: str | None, product: Product = PRO, root: Path | None = None) -> Path:
    root = root or product.root()
    if arg:
        path = Path(arg)
        if not path.is_absolute():
            path = (root / path) if (root / path).is_dir() else path.resolve()
        if not path.is_dir():
            raise DistError(f"找不到版本目錄：{arg}")
        return path.resolve()
    if not root.is_dir():
        raise DistError(f"找不到 {product.name} 的產品目錄：{root}")
    candidates = [p for p in root.iterdir() if p.is_dir() and _is_version_name(p.name, product.dir_prefix)]
    if not candidates:
        raise DistError(f"{root} 底下沒有 {product.dir_prefix}* 版本目錄")
    return max(candidates, key=lambda p: _version_key(p.name, product.dir_prefix))


def read_version(version_dir: Path, product: Product = PRO) -> str:
    common = version_dir / "payload" / "runtime" / "scripts" / "common.py"
    skill_md = version_dir / product.skill_dir / "SKILL.md"
    for f in (common, skill_md):
        if not f.is_file():
            raise DistError(f"找不到 {f}")

    m = VERSION_RE.search(common.read_text(encoding="utf-8"))
    if not m:
        raise DistError(f"{common} 沒有 VERSION = \"…\"")
    version = m.group(1)

    m = product.skill_version_re.search(skill_md.read_text(encoding="utf-8"))
    if not m:
        raise DistError(f"{skill_md} 沒有 {product.skill_version_label} 版本註解")
    skill_version = m.group(1)

    errors = []
    for rel, pat, label in OTHER_VERSIONS:
        f = version_dir / rel
        if not f.is_file():
            continue
        m = pat.search(f.read_text(encoding="utf-8-sig"))
        if not m:
            errors.append(f"{label}：找不到版號")
        elif m.group(1) != version:
            errors.append(f"{label} {m.group(1)} ≠ common.py VERSION {version}")
    if skill_version != version:
        errors.append(f"SKILL.md 版本註解 {skill_version} ≠ common.py VERSION {version}")
    if version_dir.name != f"{product.dir_prefix}{version}":
        errors.append(f"版本目錄名稱 {version_dir.name} ≠ {product.dir_prefix}{version}")
    if errors:
        raise DistError("版號不一致：\n  - " + "\n  - ".join(errors))
    return version


def tracked_files(version_dir: Path) -> list[str]:
    """版本目錄內 git 追蹤的檔案（相對於版本目錄，POSIX 分隔）。"""
    try:
        out = subprocess.run(
            ["git", "-C", str(version_dir), "ls-files", "-z", "--", "."],
            check=True, capture_output=True,
        ).stdout
    except FileNotFoundError:
        raise DistError("找不到 git 指令")
    except subprocess.CalledProcessError as exc:
        raise DistError(f"git ls-files 失敗：{exc.stderr.decode(errors='replace').strip()}")

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
    if not files:
        raise DistError(f"{version_dir} 沒有 git 追蹤的檔案")
    return sorted(files)


def find_weights(version_dir: Path) -> list[str]:
    """版本目錄內的模型權重檔（相對路徑，POSIX 分隔）；不看 git，工作目錄裡有就算。"""
    found = []
    for p in version_dir.rglob("*"):
        if not p.is_file():
            continue
        name = p.name.lower()
        if name in WEIGHT_NAMES or name.endswith(WEIGHT_SUFFIXES):
            found.append(p.relative_to(version_dir).as_posix())
    return sorted(found)


def check_no_weights(version_dir: Path) -> None:
    found = find_weights(version_dir)
    if found:
        raise DistError("版本目錄內有模型權重檔（不得放進安裝包，請移走）：\n  - " + "\n  - ".join(found))


def runtime_scripts(version_dir: Path) -> Path:
    return version_dir / "payload" / "runtime" / "scripts"


def has_html(version_dir: Path, product: Product = PRO) -> bool:
    """〔2.1.0〕這個版本目錄有網頁版（runtime 有 render_html.py）；基本版與 2.0.x 以前沒有。"""
    return product.key == PRO.key and (runtime_scripts(version_dir) / SKILL_SCRIPT_FILES[0]).is_file()


def check_skill_scripts(version_dir: Path, product: Product = PRO) -> list[str]:
    """〔2.1.0〕H-13：FALLBACK_VERSION＝common.VERSION；skill 內的 scripts/ 兩檔與 runtime 逐位元相同。
    沒有網頁版的版本目錄回傳 []（不查）；有就回傳檢查過的檔名。"""
    if not has_html(version_dir, product):
        return []
    rt = runtime_scripts(version_dir)
    errors = []
    m = VERSION_RE.search((rt / "common.py").read_text(encoding="utf-8")) if (rt / "common.py").is_file() else None
    fb = FALLBACK_VERSION_RE.search((rt / "render_html.py").read_text(encoding="utf-8"))
    if not fb:
        errors.append("render_html.py 沒有 FALLBACK_VERSION = \"…\"")
    elif not m or fb.group(1) != m.group(1):
        errors.append(f"render_html.py FALLBACK_VERSION {fb.group(1)} ≠ common.py VERSION {m.group(1) if m else '（讀不到）'}")
    skill_scripts = version_dir / product.skill_dir / "scripts"
    for name in SKILL_SCRIPT_FILES:
        src, dst = rt / name, skill_scripts / name
        if not src.is_file():
            errors.append(f"runtime 沒有 {name}")
        elif not dst.is_file():
            errors.append(f"skill 內沒有 scripts/{name}（執行 make_dist.py --sync-skill 從 runtime 複製）")
        elif src.read_bytes() != dst.read_bytes():
            errors.append(f"skill 內的 scripts/{name} 和 runtime 的不是逐位元相同（執行 make_dist.py --sync-skill 重新複製）")
    if errors:
        raise DistError("網頁版檔案檢查（H-13）失敗：\n  - " + "\n  - ".join(errors))
    return list(SKILL_SCRIPT_FILES)


def has_refs(version_dir: Path, product: Product = PRO) -> bool:
    """〔2.2.0〕這個版本目錄有參考資料功能（runtime 有 refs.py）；基本版與 2.1.x 以前沒有。"""
    return product.key == PRO.key and (runtime_scripts(version_dir) / REFS_SCRIPT).is_file()


def check_refs(version_dir: Path, product: Product = PRO) -> list[str]:
    """〔2.2.0〕參考資料（規格 2.2.0 §5.1、§10）：① refs.py 不進 skill（Claude App 上傳檔）；② requirements.txt、
    requirements-mac.txt 都有 pypdf。沒有參考資料功能的版本目錄回傳 []（不查）；有就回傳檢查過的項目。"""
    if not has_refs(version_dir, product):
        return []
    errors = []
    skill_dir = version_dir / product.skill_dir
    found = sorted(p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob(REFS_SCRIPT)) if skill_dir.is_dir() else []
    if found:
        errors.append(f"skill 內有 {', '.join(found)}：refs.py 只放 runtime，不進 Claude App 上傳檔（規格 2.2.0 §10）")
    for name in REFS_REQUIREMENTS:
        req = version_dir / "payload" / "runtime" / name
        if not req.is_file():
            errors.append(f"找不到 payload/runtime/{name}")
        elif not re.search(r"^\s*pypdf\b", req.read_text(encoding="utf-8"), re.MULTILINE | re.IGNORECASE):
            errors.append(f"payload/runtime/{name} 沒有 pypdf（PDF 會議文件的抽取要用）")
    if errors:
        raise DistError("參考資料檔案檢查失敗：\n  - " + "\n  - ".join(errors))
    return [f"skill 內沒有 {REFS_SCRIPT}"] + [f"{n} 有 pypdf" for n in REFS_REQUIREMENTS]


def build_upload_zip(skill_dir: Path, dest: Path, upload_root: str = UPLOAD_ROOT) -> list[str]:
    """payload 的上傳用 zip：skill 目錄的所有檔（不含 __pycache__、zip），依路徑排序，根目錄 upload_root。"""
    files = sorted(p for p in skill_dir.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts and not p.name.lower().endswith(".zip"))
    names = []
    fd, tmp = tempfile.mkstemp(dir=str(dest.parent), prefix=".tmp-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in files:
                rel = p.relative_to(skill_dir).as_posix()
                mtime = time.localtime(max(p.stat().st_mtime, 315532800))
                info = zipfile.ZipInfo(upload_root + rel, date_time=mtime[:6])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100000 | 0o644) << 16
                zf.writestr(info, p.read_bytes())
                names.append(upload_root + rel)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return names


def sync_skill(version_dir: Path, product: Product = PRO) -> list[str]:
    """〔2.1.0〕`--sync-skill`：runtime 的 render_html.py、html_template.html 複製到 skill/scripts/，重產 payload zip。"""
    if not has_html(version_dir, product):
        raise DistError(f"{version_dir.name} 沒有網頁版（runtime 沒有 render_html.py），不需要 --sync-skill")
    skill_dir = version_dir / product.skill_dir
    (skill_dir / "scripts").mkdir(exist_ok=True)
    for name in SKILL_SCRIPT_FILES:
        shutil.copyfile(runtime_scripts(version_dir) / name, skill_dir / "scripts" / name)
    names = build_upload_zip(skill_dir, version_dir / product.payload_zip, product.upload_root)
    check_skill_scripts(version_dir, product)
    check_upload_zip(version_dir / product.payload_zip, skill_dir, product.upload_root)
    return names


def check_upload_zip(upload_zip: Path, skill_dir: Path, upload_root: str = UPLOAD_ROOT) -> list[str]:
    if not upload_zip.is_file():
        raise DistError(f"找不到 {upload_zip}")
    with zipfile.ZipFile(upload_zip) as zf:
        names = zf.namelist()
        bad = [n for n in names if n.lower().endswith(".zip")]
        if bad:
            raise DistError(f"{upload_zip.name} 含巢狀 zip：{bad}")
        outside = [n for n in names if not n.startswith(upload_root)]
        if outside:
            raise DistError(f"{upload_zip.name} 有不在 {upload_root} 底下的項目：{outside}")
        # payload zip 必須和 payload/skill/ 目前的內容一致，避免發出過時的上傳檔
        for name in names:
            if name.endswith("/"):
                continue
            src = skill_dir / name[len(upload_root):]
            if not src.is_file() or src.read_bytes() != zf.read(name):
                raise DistError(f"{upload_zip.name} 的 {name} 和 {src} 不同，請先重新產生 payload zip")
        skill_files = sorted(
            p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts
        )
        zipped = sorted(n[len(upload_root):] for n in names if not n.endswith("/"))
        if skill_files != zipped:
            raise DistError(f"{upload_zip.name} 檔案清單 {zipped} 和 {skill_dir} 的 {skill_files} 不同")
    return names


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


def readme_text(version: str, installer: str, upload: str, product: Product = PRO) -> str:
    folder = f"{product.dir_prefix}{version}"
    title = f"{product.name} v{version} 發行檔說明"
    return f"""{title}
{"=" * 40}

這個資料夾有兩個 zip，用途不同（用 Claude App 的人通常兩個都需要）：

1. {installer}
   給誰：要在自己的電腦上安裝（本機轉寫、右鍵／拖放轉寫、Claude CLI）的人。
   怎麼用：先完整解壓縮，再執行裡面的安裝程式。
     - Windows：雙擊 {folder}\\install.cmd
     - macOS：在 {folder}/install.command 上按右鍵 →「打開」
   安裝時選了 Claude App，安裝程式會在桌面放一個 {product.desktop_zip}，
   內容和下面第 2 個檔相同，上傳哪一個都可以。
   注意：這個檔裡面含有 zip，不能直接上傳到 Claude App，會出現
   「Zip cannot contain nested zip files」。

2. {upload}
   給誰：只要在 Claude App（對話／Cowork）上傳 skill 的人。
   怎麼用：不要解開，直接上傳整個 zip：
     Claude App「自訂 (Customize) → Skills → + → Upload a skill」
     （網頁版：https://claude.ai/customize/skills；需先在「設定 → Capabilities」開啟程式碼執行）
   App 的 skill 在沙盒中執行，轉寫仍要在本機完成，所以通常也需要第 1 個檔。

驗證檔案（可略過）：同名的 .sha256 檔記錄 SHA-256。
  - Windows（PowerShell）：Get-FileHash <檔名> -Algorithm SHA256
  - macOS（終端機）：shasum -a 256 -c <檔名>.sha256

完整說明見安裝包裡的 README.md。
"""


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="產生 meeting-minutes 發行檔到 dist/（預設 Pro 版）")
    ap.add_argument("version_dir", nargs="?",
                    help="版本目錄（預設：產品目錄底下版號最高的版本目錄）")
    ap.add_argument("--product", choices=sorted(PRODUCTS), default=PRO.key,
                    help="pro（預設）或 basic（基本版）")
    ap.add_argument("--out-dir", help="輸出資料夾（預設：<產品目錄>/dist）")
    ap.add_argument("--sync-skill", action="store_true",
                    help="〔2.1.0〕把 runtime 的 render_html.py、html_template.html 複製到 skill/scripts/ 並重產 payload zip"
                         "（只更新版本目錄，不產生 dist/）")
    args = ap.parse_args(argv)
    product = PRODUCTS[args.product]

    if args.sync_skill:
        try:
            version_dir = find_version_dir(args.version_dir, product)
            names = sync_skill(version_dir, product)
        except DistError as exc:
            print(f"錯誤：{exc}", file=sys.stderr)
            return 2
        print(f"已複製 {', '.join(SKILL_SCRIPT_FILES)} 到 {product.skill_dir}/scripts/（與 runtime 逐位元相同）")
        print(f"已重產 {product.payload_zip}：{len(names)} 項")
        print("新檔請先 git add，再執行一次 make_dist.py（不加 --sync-skill）產生發行檔")
        return 0

    try:
        version_dir = find_version_dir(args.version_dir, product)
        version = read_version(version_dir, product)
        check_no_weights(version_dir)
        html_checked = check_skill_scripts(version_dir, product)
        refs_checked = check_refs(version_dir, product)
        files = tracked_files(version_dir)
        upload_src = version_dir / product.payload_zip
        upload_names = check_upload_zip(upload_src, version_dir / product.skill_dir, product.upload_root)
    except DistError as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 2

    dist_dir = Path(args.out_dir).resolve() if args.out_dir else product.root() / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    installer_name = f"{product.dir_prefix}{version}-installer.zip"
    upload_name = f"{product.dir_prefix}{version}-claude-app-upload.zip"
    installer = dist_dir / installer_name
    upload = dist_dir / upload_name

    tmp_installer = dist_dir / f".tmp-{installer_name}"
    try:
        build_installer(version_dir, files, tmp_installer)
        os.replace(tmp_installer, installer)
    finally:
        if tmp_installer.exists():
            tmp_installer.unlink()
    shutil.copyfile(upload_src, upload)
    if upload.read_bytes() != upload_src.read_bytes():
        print(f"錯誤：{upload_name} 和 payload zip 位元組不同", file=sys.stderr)
        return 2

    for path in (installer, upload):
        line = f"{sha256_of(path)}  {path.name}\n"
        write_atomic(path.with_name(path.name + ".sha256"), line.encode("ascii"))
    write_atomic(dist_dir / "README.txt",
                 readme_text(version, installer_name, upload_name, product).encode("utf-8-sig"))

    print(f"{product.name} 版號 {version}（common.py、SKILL.md、install.ps1、install.sh、README、目錄名稱一致）；模型權重檔 0 個")
    if html_checked:
        print(f"網頁版（H-13）：render_html.py FALLBACK_VERSION＝common.py VERSION；skill 內 scripts/ 的 "
              f"{'、'.join(html_checked)} 與 runtime 逐位元相同")
    if refs_checked:
        print(f"參考資料（2.2.0）：{'；'.join(refs_checked)}")
    print(f"{installer_name}：{len(files)} 檔，{installer.stat().st_size:,} bytes，sha256 {sha256_of(installer)}")
    print(f"{upload_name}：{len(upload_names)} 項（無巢狀 zip），{upload.stat().st_size:,} bytes，sha256 {sha256_of(upload)}")
    print(f"README.txt 與 .sha256 已寫入 {dist_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
