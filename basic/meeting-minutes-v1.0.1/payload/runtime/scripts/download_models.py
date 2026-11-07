"""Download diarization models, the benchmark sample, and Whisper models (idempotent).

Usage: python download_models.py [--backend openvino|ct2|mlx] [--whisper turbo|large-v3|base|<hf repo>]
"""
import argparse
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DEFAULT_WHISPER, EMB_URL, SAMPLE_URL, SEG_URL, emb_model, models_dir,  # noqa: E402
                    sample_wav, seg_model, utf8_console, whisper_dir, whisper_ready, whisper_repo)


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


def ensure_whisper(backend: str, alias: str):
    if not whisper_ready(backend, alias):
        from huggingface_hub import snapshot_download
        repo = whisper_repo(backend, alias)
        print(f"  下載 Whisper [{backend}] {repo}（約 1~1.6GB，請稍候）", flush=True)
        snapshot_download(repo, local_dir=str(whisper_dir(backend, alias)))
    print(f"[OK] whisper [{backend}]：{whisper_dir(backend, alias)}")


def remove_backend_models(backend: str):
    d = models_dir() / backend
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
        print(f"  已移除未採用的 {backend} 模型：{d}")


def main():
    utf8_console()
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="openvino", choices=["openvino", "ct2", "mlx"])
    ap.add_argument("--whisper", default=DEFAULT_WHISPER)
    args = ap.parse_args()
    print(f"模型目錄：{models_dir()}")
    ensure_common()
    ensure_whisper(args.backend, args.whisper)


if __name__ == "__main__":
    main()
