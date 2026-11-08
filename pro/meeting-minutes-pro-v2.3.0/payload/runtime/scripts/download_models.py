"""Download diarization models, the benchmark sample, the punctuation model and Whisper models (idempotent).

Usage: python download_models.py [--backend openvino|ct2|mlx] [--whisper turbo|large-v3|base|<hf repo>]
       python download_models.py --punct-only [--punct-archive <本機 tar.bz2>]   # 只補標點模型（可離線）
"""
import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import (DEFAULT_WHISPER, EMB_URL, SAMPLE_URL, SEG_URL, emb_model, models_dir,  # noqa: E402
                    punct_model_dir, punct_ready, sample_wav, seg_model, utf8_console, whisper_dir,
                    whisper_ready, whisper_repo)

PUNCT_FAIL_MSG = ("標點模型下載失敗，逐字稿仍會分段，turbo 沿用 Whisper 標點；"
                  "之後可執行 setup_backend.py --punct-only 補裝")


def fetch(url: str, dst: Path):
    print(f"  下載 {url}", flush=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dst)


def ensure_common():
    root = models_dir()
    root.mkdir(parents=True, exist_ok=True)
    if not seg_model().exists():
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "seg.tar.bz2"
            fetch(SEG_URL, arc)
            with tarfile.open(arc, "r:bz2") as tf:
                tf.extractall(root, filter="data")
    print(f"[OK] segmentation：{seg_model()}")
    if not emb_model().exists():
        fetch(EMB_URL, emb_model())
    print(f"[OK] speaker embedding：{emb_model()}")
    if not sample_wav().exists():
        fetch(SAMPLE_URL, sample_wav())
    print(f"[OK] 測速樣本：{sample_wav()}")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def ensure_punct(archive: str | Path | None = None, url: str | None = None) -> bool:
    """CT-Transformer 標點模型：已就緒就跳過；否則下載（或用本機壓縮檔）→ 驗 SHA-256 → 只解出需要的檔。

    失敗不丟例外：印警告並回傳 False（安裝與轉寫都不中止）。
    """
    if punct_ready():
        print(f"[OK] 標點模型：{punct_model_dir()}")
        return True
    root = models_dir()
    root.mkdir(parents=True, exist_ok=True)
    arc = None
    try:
        if archive:
            arc = Path(archive)
            if not arc.exists():
                raise FileNotFoundError(f"找不到 {arc}")
            remove_after = False
        else:
            arc = root / (common.PUNCT_NAME + ".tar.bz2")
            print(f"  下載標點模型（約 65 MB）：{url or common.PUNCT_URL}", flush=True)
            part = arc.with_name(arc.name + ".part")
            try:
                urllib.request.urlretrieve(url or common.PUNCT_URL, part)
                part.replace(arc)
            finally:
                part.unlink(missing_ok=True)
            remove_after = True
        digest = sha256_of(arc)
        if digest != common.PUNCT_SHA256:
            if remove_after:
                arc.unlink(missing_ok=True)
            raise ValueError(f"SHA-256 不符（{digest[:16]}…，預期 {common.PUNCT_SHA256[:16]}…），已刪除下載檔")
        dst = punct_model_dir()
        with tarfile.open(arc, "r:bz2") as tf:
            members = [m for m in tf.getmembers()
                       if m.isfile() and m.name.split("/")[-1] in common.PUNCT_FILES
                       and m.name.split("/")[0] == common.PUNCT_NAME]
            if not any(m.name.endswith("/model.int8.onnx") for m in members):
                raise ValueError("壓縮檔裡沒有 model.int8.onnx")
            tf.extractall(root, members=members, filter="data")
        if remove_after:
            arc.unlink(missing_ok=True)
        if not punct_ready():
            raise ValueError(f"解開後找不到可用的 {dst / 'model.int8.onnx'}")
        print(f"[OK] 標點模型：{dst}（SHA-256 驗證通過）")
        return True
    except Exception as ex:  # noqa: BLE001
        print(f"  [!] {PUNCT_FAIL_MSG}（{str(ex)[:160]}）", flush=True)
        return False


# ct2 模型若沒附 tokenizer.json，從原始模型補上（避免轉寫時才連網下載）
CT2_TOKENIZER_SOURCE = {"turbo": "openai/whisper-large-v3-turbo", "large-v3": "openai/whisper-large-v3",
                        "base": "openai/whisper-base"}


def ensure_whisper(backend: str, alias: str, compute_type: str = "default"):
    if alias == "breeze":
        import breeze
        breeze.ensure(backend, compute_type)
        return
    d = whisper_dir(backend, alias)
    if not whisper_ready(backend, alias):
        from huggingface_hub import hf_hub_download, snapshot_download
        repo = whisper_repo(backend, alias)
        print(f"  下載 Whisper [{backend}] {repo}（約 1~1.6GB，請稍候）", flush=True)
        snapshot_download(repo, local_dir=str(d))
        if backend == "ct2" and not (d / "tokenizer.json").exists() and alias in CT2_TOKENIZER_SOURCE:
            hf_hub_download(CT2_TOKENIZER_SOURCE[alias], "tokenizer.json", local_dir=str(d))
    print(f"[OK] whisper [{backend}]：{d}")


def remove_backend_models(backend: str):
    d = models_dir() / backend
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        print(f"  已移除未採用的 {backend} 模型：{d}")


def main():
    utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="openvino", choices=["openvino", "ct2", "mlx"])
    ap.add_argument("--whisper", default=DEFAULT_WHISPER, help="turbo / large-v3 / base / breeze")
    ap.add_argument("--compute-type", default="default", help="ct2 + breeze 時決定下載哪個精度")
    ap.add_argument("--punct-archive", help="離線安裝：本機的標點模型 tar.bz2（同樣驗 SHA-256）")
    ap.add_argument("--punct-only", action="store_true", help="只補標點模型")
    args = ap.parse_args()
    print(f"模型目錄：{models_dir()}")
    if args.punct_only:
        sys.exit(0 if ensure_punct(args.punct_archive) else 1)
    ensure_common()
    ensure_punct(args.punct_archive)
    ensure_whisper(args.backend, args.whisper, args.compute_type)


if __name__ == "__main__":
    main()
