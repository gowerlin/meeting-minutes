"""合成測試素材：把 materials/*.txt 的講稿用 edge-tts 念出來，接成一個 16 kHz mono wav。

講稿就是基準稿（含標點與段落）。段落之間插入 0.3～2.5 秒隨機靜音（固定亂數種子，可重現），
「／」處插入 0.5～1 秒句中停頓；講者後面寫 <秒數> 時，與上一段的靜音固定為該值。

〔2.0.0〕講稿裡的 `@include <名稱> [gap=秒數] [舊詞=新詞 ...]` 把另一份講稿的段落原樣接進來（依序做字串替換；
gap＝與上一段的靜音，預設隨機），用來把短素材拼接成長素材（例 CL2＝CL1 三輪）。被 include 的講稿的 @voice 一併沿用。

輸出（不進版控）：tests/_out/<名稱>.wav、tests/_out/<名稱>.ref.json（每段的講者、文字、起訖秒數）
用法：python make_materials.py [M1 M2 CL1 ...]  # 預設全部（materials/ 底下所有 <名稱>-*.txt）；需要 edge-tts（網路）與 ffmpeg
"""
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

HERE = Path(__file__).resolve().parent
MAT = HERE / "materials"
OUT = HERE / "_out"
SR = 16000
SEED = 20261106


def parse(path: Path) -> dict:
    voices, paras = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("@include"):           # 〔2.0.0〕拼接另一份講稿（見檔頭說明）
            parts = line.split()
            opts = dict(p.split("=", 1) for p in parts[2:])
            gap = float(opts.pop("gap")) if "gap" in opts else None
            sub = parse(next(MAT.glob(f"{parts[1]}-*.txt")))
            for k, v in sub["voices"].items():
                voices.setdefault(k, v)
            for j, q in enumerate(sub["paragraphs"]):
                text = q["text"]
                for a, b in opts.items():
                    text = text.replace(a, b)
                paras.append({"speaker": q["speaker"], "text": text, "gap": gap if j == 0 and gap is not None else q["gap"]})
            continue
        if line.startswith("@voice"):
            parts = line.split()
            opts = dict(p.split("=", 1) for p in parts[3:])
            voices[parts[1]] = {"voice": parts[2], "rate": opts.get("rate", "+0%"), "pitch": opts.get("pitch", "+0Hz")}
            continue
        spk, text = line.split("｜", 1)
        gap = None
        m = re.match(r"<([0-9.]+)>", text)
        if m:
            gap, text = float(m.group(1)), text[m.end():]
        if re.search(r"<[0-9.]+>", text):        # 〔2.0.0〕<秒數> 只能寫在段首，段中會被 TTS 念出來
            sys.exit(f"{path.name}：<秒數> 只能寫在段首：{text[:30]}")
        paras.append({"speaker": spk.strip(), "text": text.strip(), "gap": gap})
    return {"voices": voices, "paragraphs": paras}


def tts(text: str, v: dict, cache: Path) -> np.ndarray:
    key = hashlib.sha256(json.dumps([text, v], ensure_ascii=False).encode()).hexdigest()[:20]
    wav = cache / f"{key}.wav"
    if not wav.exists():
        mp3 = cache / f"{key}.mp3"
        exe = shutil.which("edge-tts") or sys.exit("找不到 edge-tts")
        for attempt in range(4):   # edge-tts 偶爾連線失敗
            try:                    # 〔2.0.0〕連線偶爾掛住不回：逾時當成失敗重試
                p = subprocess.run([exe, "--voice", v["voice"], f"--rate={v['rate']}", f"--pitch={v['pitch']}",
                                    "--text", text, "--write-media", str(mp3)], capture_output=True, timeout=180)
            except subprocess.TimeoutExpired as ex:
                p = subprocess.CompletedProcess(ex.cmd, 1, b"", b"timeout")
            if p.returncode == 0 and mp3.exists() and mp3.stat().st_size > 0:
                break
            time.sleep(2 + 3 * attempt)
        else:
            sys.exit(f"edge-tts 失敗：{p.stderr.decode('utf-8', 'replace')[-300:]}")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR),
                        "-c:a", "pcm_s16le", str(wav)], check=True)
        mp3.unlink(missing_ok=True)
    audio, sr = sf.read(str(wav), dtype="float32")
    assert sr == SR
    return audio


def trim(a: np.ndarray, thr: float = 0.004) -> np.ndarray:
    """去掉 TTS 前後的靜音，讓插入的靜音長度就是實際停頓。"""
    idx = np.where(np.abs(a) > thr)[0]
    return a[max(0, idx[0] - 160): idx[-1] + 160] if len(idx) else a


def build(name: str):
    src = next(MAT.glob(f"{name}-*.txt"))
    doc = parse(src)
    cache = OUT / "tts-cache"
    cache.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(f"{SEED}-{name}")
    pieces, t, ref = [np.zeros(int(0.5 * SR), dtype=np.float32)], 0.5, []
    for i, p in enumerate(doc["paragraphs"]):
        if i:
            gap = p["gap"] if p["gap"] is not None else round(rnd.uniform(0.3, 2.5), 2)
            pieces.append(np.zeros(int(gap * SR), dtype=np.float32))
            t += gap
        start = t
        parts = [x for x in p["text"].split("／") if x.strip()]
        for j, part in enumerate(parts):
            if j:
                pause = round(rnd.uniform(0.5, 1.0), 2)
                pieces.append(np.zeros(int(pause * SR), dtype=np.float32))
                t += pause
            a = trim(tts(part.strip(), doc["voices"][p["speaker"]], cache))
            pieces.append(a)
            t += len(a) / SR
        ref.append({"speaker": p["speaker"], "text": p["text"].replace("／", ""), "start": round(start, 2),
                    "end": round(t, 2), "gap_before": None if i == 0 else round(start - ref[-1]["end"], 2)})
    pieces.append(np.zeros(int(0.8 * SR), dtype=np.float32))
    audio = np.concatenate(pieces)
    sf.write(str(OUT / f"{name}.wav"), audio, SR, subtype="PCM_16")
    (OUT / f"{name}.ref.json").write_text(json.dumps({"source": src.name, "duration": round(len(audio) / SR, 2),
                                                       "paragraphs": ref}, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    chars = sum(len(re.sub(r"[\s，。、；：？！「」]", "", r["text"])) for r in ref)
    print(f"{name}: {len(ref)} 段、{chars} 字、{len(audio) / SR / 60:.1f} 分鐘、"
          f"講者 {len({r['speaker'] for r in ref})} 位 → {OUT / (name + '.wav')}")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    names = sys.argv[1:] or sorted({p.name.split("-")[0] for p in MAT.glob("*-*.txt")})
    for n in names:
        build(n)


if __name__ == "__main__":
    main()
