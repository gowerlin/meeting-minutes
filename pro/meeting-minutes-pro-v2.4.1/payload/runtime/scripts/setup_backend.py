"""安裝時執行一次：盤點硬體 → 下載候選後端模型 → 實測 → 把最佳組合寫入 config.json。

轉寫時不再偵測；換硬體、更新驅動後，重新執行 install.cmd（或本程式）即可。

Usage:
  python setup_backend.py [--whisper turbo] [--seconds 60] [--keep-all] [--breeze]
  python setup_backend.py --force openvino:CPU     # 不測速，直接指定（保留 config.json 既有的 bench、detected_at）
  python setup_backend.py --force ct2:cuda [--compute-type int8_float16]
                                                   # 〔1.2.1〕不指定精度時，後端與裝置和既有設定相同就沿用既有 compute_type
  python setup_backend.py --breeze-only            # 已安裝後再加裝 Breeze-ASR-25（沿用既有選定的後端）
  python setup_backend.py --punct-only             # 只補裝 CT-Transformer 標點模型（下載失敗後補裝用）

〔2.4.1〕config.json 存在但讀不了（common.read_config() 的 unreadable）：除了 --punct-only（不寫 config）以外，
一開始就印原因與路徑、exit 5，不下載、不實測、不寫入（規格 2.4.1 §3）。save_config() 本身也會丟 ConfigUnreadable。
"""
import argparse
import json
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (BACKENDS, CONFIG_UNREADABLE_EXIT, DEFAULT_WHISPER, config_write_refused_message,  # noqa: E402
                    load_config, print_banner, read_config, sample_wav, save_config, utf8_console)

OFFLOAD_PREFERENCE = 1.25   # NPU／Apple GPU 在最快者 1.25 倍時間內就優先選（省電、不佔 CPU）
OFFLOAD = [("openvino", "NPU"), ("mlx", "gpu")]
MIN_VRAM_MIB = 3000       # turbo 模型在 CUDA 上至少需要的顯示記憶體
CT2_COMPUTE_PREF = ["int8_float16", "float16", "int8_float32", "int8", "float32"]


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- inventory
def video_controllers() -> list:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"],
            capture_output=True, text=True, timeout=30).stdout
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:  # noqa: BLE001
        return []


def nvidia_gpus() -> list:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run([exe, "--query-gpu=index,name,memory.total,compute_cap,driver_version",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return []
    gpus = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 5:
            gpus.append({"index": int(parts[0]), "name": parts[1], "vram_mib": int(float(parts[2])),
                         "compute_cap": parts[3], "driver": parts[4]})
    return gpus


def openvino_devices() -> dict:
    try:
        import openvino as ov
        core = ov.Core()
        return {d: core.get_property(d, "FULL_DEVICE_NAME") for d in core.available_devices}
    except Exception as ex:  # noqa: BLE001
        log(f"  [!] OpenVINO 無法列出裝置：{ex}")
        return {}


def mac_info() -> dict:
    def sysctl(key):
        try:
            return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:  # noqa: BLE001
            return ""
    mem = sysctl("hw.memsize")
    return {"cpu": sysctl("machdep.cpu.brand_string") or platform.processor(),
            "memory_gb": round(int(mem) / 2**30) if mem.isdigit() else None,
            "perf_cores": sysctl("hw.perflevel0.physicalcpu")}


def inventory() -> dict:
    if sys.platform == "darwin":
        mi = mac_info()
        return {"os": "macos", "machine": platform.machine(), "cpu": mi["cpu"], "mac": mi,
                "video": [], "nvidia": [], "openvino": {}}
    return {"os": sys.platform, "machine": platform.machine(), "cpu": platform.processor(),
            "video": video_controllers(), "nvidia": nvidia_gpus(), "openvino": openvino_devices()}


def mac_candidates(inv: dict) -> list:
    cands = []
    if inv["machine"] == "arm64":
        try:
            import mlx.core as mx
            cands.append(("mlx", "gpu", "default", f"{inv['cpu']} GPU（Metal，{mx.default_device()}）"))
        except Exception as ex:  # noqa: BLE001
            log(f"  [!] MLX 無法使用：{ex}")
    try:
        import ctranslate2
        types = ctranslate2.get_supported_compute_types("cpu")
        ct = "int8" if "int8" in types else "float32"
        cands.append(("ct2", "cpu", ct, f"{inv['cpu']} CPU"))
    except Exception as ex:  # noqa: BLE001
        log(f"  [!] CTranslate2 無法使用：{ex}")
    return cands


# ---------------------------------------------------------------- candidates
def candidates(inv: dict) -> list:
    """每個候選 = (backend, device, compute_type, 說明)"""
    if inv.get("os") == "macos":
        return mac_candidates(inv)
    cands = []
    for dev, name in inv["openvino"].items():
        if dev == "NPU" or dev.startswith("GPU") or dev == "CPU":
            cands.append(("openvino", dev, "default", name))
    if not any(c[1] == "CPU" for c in cands):
        cands.append(("openvino", "CPU", "default", inv["cpu"]))
    if inv["nvidia"]:
        try:
            from backends import _add_nvidia_dll_dirs
            _add_nvidia_dll_dirs()
            import ctranslate2
            n = ctranslate2.get_cuda_device_count()
            types = ctranslate2.get_supported_compute_types("cuda") if n else set()
        except Exception as ex:  # noqa: BLE001
            n, types = 0, set()
            log(f"  [!] CTranslate2 無法使用 CUDA：{ex}")
        for g in inv["nvidia"]:
            if g["index"] >= n:
                continue
            if g["vram_mib"] < MIN_VRAM_MIB:
                log(f"  [略過] {g['name']}：顯示記憶體 {g['vram_mib']} MiB 不足")
                continue
            ct = next((t for t in CT2_COMPUTE_PREF if t in types), None)
            if ct:
                dev = "cuda" if g["index"] == 0 else f"cuda:{g['index']}"
                cands.append(("ct2", dev, ct, f"{g['name']}（CC {g['compute_cap']}，{g['vram_mib']} MiB）"))
    return cands


# ---------------------------------------------------------------- bench
def bench_one(backend, device, compute_type, audio, sr, model) -> dict:
    import backends
    from transcribe import split_long
    t0 = time.time()
    b = backends.create(backend, model, device, "zh", None, compute_type)
    t1 = time.time()
    dur = len(audio) / sr
    text = "".join(b.transcribe(audio[int(a * sr):int(e * sr)]) for a, e in split_long(audio, 0.0, dur))
    t2 = time.time()
    del b
    return {"load_s": round(t1 - t0, 1), "asr_s": round(t2 - t1, 1), "rtf": (t2 - t1) / dur, "text": text}


def choose(results: list) -> dict:
    ok = [r for r in results if r.get("ok")]
    if not ok:
        return {}
    best = min(ok, key=lambda r: r["rtf"])
    for be, dev in OFFLOAD:
        r = next((r for r in ok if (r["backend"], r["device"]) == (be, dev)), None)
        if r and r["rtf"] <= best["rtf"] * OFFLOAD_PREFERENCE:
            return r
    return best


def load_sample(seconds: int):
    import soundfile as sf
    from transcribe import to_wav
    tmp = sample_wav().with_name("bench16k.wav")
    to_wav(sample_wav(), tmp)
    audio, sr = sf.read(str(tmp), dtype="float32")
    tmp.unlink(missing_ok=True)
    return audio[: seconds * sr], sr


# ---------------------------------------------------------------- Breeze-ASR-25
def breeze_tries(backend: str, device: str, compute_type: str) -> list:
    """Breeze 在主後端上要試的（裝置, 精度）順序；大模型在 NPU／舊 GPU 上可能失敗，安裝時就決定退路。"""
    if backend == "openvino":
        return list(dict.fromkeys([(device, "default"), ("CPU", "default")]))
    if backend == "ct2":
        tries = [(device, compute_type)]
        if device != "cpu":
            tries.append(("cpu", "int8"))
        return tries
    return [(device, compute_type)]


def setup_breeze(seconds: int = 30):
    import download_models as dl
    cfg = load_config()
    if not cfg.get("backend"):
        sys.exit("尚未完成主模型偵測，請先執行完整安裝")
    be, dev, ct = cfg["backend"], cfg["device"], cfg.get("compute_type", "default")
    log(f"\n[Breeze-ASR-25] 主後端：{be} / {dev} / {ct}")
    dl.ensure_whisper(be, "breeze", ct)
    audio, sr = load_sample(seconds)
    turbo_rtf = next((r["rtf"] for r in cfg.get("bench", []) if r.get("ok") and r["backend"] == be
                      and r["device"] == dev and r.get("rtf")), None)
    for d, c in breeze_tries(be, dev, ct):
        try:
            r = bench_one(be, d, c, audio, sr, "breeze")
            if len(r["text"]) < 10:
                raise RuntimeError("輸出幾乎沒有文字")
            prof = {"backend": be, "device": d, "compute_type": c, "rtf": round(r["rtf"], 4)}
            profiles = dict(cfg.get("profiles", {}), breeze=prof)
            save_config(profiles=profiles)
            slower = f"，約為 turbo 的 {r['rtf'] / turbo_rtf:.1f} 倍時間" if turbo_rtf else ""
            log(f"  [選定] Breeze：{be} / {d} / {c}（RTF {r['rtf']:.3f}{slower}）  {r['text'][:24]}")
            return prof
        except Exception as ex:  # noqa: BLE001
            log(f"  [!] Breeze 在 {be}/{d} 失敗：{str(ex)[:100]}")
    sys.exit("Breeze-ASR-25 在可用裝置上都無法執行")


def detection_fields(results: list, forced: bool, old_cfg: dict) -> dict:
    """要寫進 config.json 的 bench、detected_at。

    真的測速時用這次的結果與現在時間。--force（不測速）時保留 config.json 既有的 bench、detected_at，
    沒有既有值才寫空（bench=[]、detected_at=None）；SKILL 的 Breeze／turbo 預估要用 bench 的 rtf（1.1.0）。
    """
    if not forced:
        return {"detected_at": datetime.now().isoformat(timespec="seconds"),
                "bench": [{k: r.get(k) for k in ("backend", "device", "compute_type", "rtf", "ok", "error")}
                          for r in results]}
    return {"detected_at": old_cfg.get("detected_at"), "bench": old_cfg.get("bench") or []}


def forced_compute_type(backend: str, device: str, explicit: str | None, old_cfg: dict) -> tuple:
    """〔1.2.1〕--force（不測速）時要寫入的精度，回傳 (compute_type, 來源)。來源：
    explicit＝--compute-type 指定；kept＝既有 config.json 的後端與裝置相同，沿用既有的 compute_type
    （1.2.0 以前會被改成預設，例 int8_float16 → int8_float32）；default＝後端或裝置不同（或沒有既有值），照原本的預設。"""
    if explicit:
        return explicit, "explicit"
    old_ct = old_cfg.get("compute_type")
    if (old_ct and str(old_cfg.get("backend") or "") == backend
            and str(old_cfg.get("device") or "").lower() == str(device or "").lower()):
        return old_ct, "kept"
    return ("default" if backend != "ct2" else ("int8" if device == "cpu" else "int8_float32")), "default"


# ---------------------------------------------------------------- main
def main():
    utf8_console()
    print_banner()                     # 〔1.2.0〕第一行顯示版號
    ap = argparse.ArgumentParser()
    ap.add_argument("--whisper", default=DEFAULT_WHISPER)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--keep-all", action="store_true", help="保留所有後端的模型（預設只留選中的）")
    ap.add_argument("--force", help="不測速，直接指定 backend:device，例：openvino:NPU、openvino:CPU、ct2:cuda、mlx:gpu、ct2:cpu")
    ap.add_argument("--compute-type", default=None,
                    help="搭配 --force 使用，例：int8_float16、float16、int8_float32；不指定時，後端與裝置和既有設定相同就沿用既有精度（1.2.1）")
    ap.add_argument("--breeze", action="store_true", help="主模型選定後，再為同一後端準備 Breeze-ASR-25")
    ap.add_argument("--breeze-only", action="store_true", help="只加裝 Breeze-ASR-25，沿用 config 既有的後端")
    ap.add_argument("--punct-only", action="store_true", help="只補裝 CT-Transformer 標點模型")
    ap.add_argument("--punct-archive", help="離線安裝：本機的標點模型 tar.bz2（同樣驗 SHA-256）")
    args = ap.parse_args()
    rc = read_config()                   # 〔2.4.1〕config.json 存在但讀不了：什麼都不做、不寫（規格 2.4.1 §3）
    if rc["status"] == "unreadable" and not args.punct_only:
        log("\n[錯誤] " + config_write_refused_message(rc))
        sys.exit(CONFIG_UNREADABLE_EXIT)
    if args.punct_only:
        import download_models as dl
        ok = dl.ensure_punct(args.punct_archive)
        print(json.dumps({"punct": ok}, ensure_ascii=False))
        sys.exit(0 if ok else 1)
    if args.breeze_only:
        prof = setup_breeze()
        print(json.dumps({"breeze": prof}, ensure_ascii=False))
        return

    import download_models as dl
    dl.ensure_common()
    punct_ok = dl.ensure_punct(args.punct_archive)   # 失敗只警告，不中止安裝

    log("\n[硬體盤點]")
    inv = inventory()
    log(f"  CPU    ：{inv['cpu']}（{inv['machine']}）")
    if inv.get("mac"):
        log(f"  記憶體 ：{inv['mac']['memory_gb']} GB　效能核心：{inv['mac']['perf_cores']}")
    for v in inv["video"]:
        log(f"  顯示卡 ：{v}")
    for d, n in inv["openvino"].items():
        log(f"  OpenVINO {d}：{n}")
    for g in inv["nvidia"]:
        log(f"  NVIDIA ：{g['name']}  CC {g['compute_cap']}  {g['vram_mib']} MiB  驅動 {g['driver']}")
    others = [v for v in inv["video"] if not any(k in v for k in ("Intel", "NVIDIA", "Microsoft"))]
    if others:
        log(f"  [i] 下列顯示卡目前沒有對應後端，將不使用：{others}")

    if args.force:
        backend, _, device = args.force.partition(":")
        if backend not in BACKENDS:
            sys.exit(f"--force 的 backend 只能是 {'、'.join(BACKENDS)}")
        default_dev = {"openvino": "CPU", "ct2": "cpu" if sys.platform == "darwin" else "cuda", "mlx": "gpu"}[backend]
        device = device or default_dev
        compute, why = forced_compute_type(backend, device, args.compute_type, load_config())   # 〔1.2.1〕
        if why == "kept":
            log(f"  精度：沿用 config.json 既有的 {compute}（後端與裝置相同；要改請加 --compute-type）")
        dl.ensure_whisper(backend, args.whisper)
        best = {"backend": backend, "device": device, "compute_type": compute, "rtf": None}
        results = []
    else:
        cands = candidates(inv)
        log("\n[候選組合]")
        for c in cands:
            log(f"  {c[0]:<9}{c[1]:<8}{c[2]:<13}{c[3]}")
        for be in sorted({c[0] for c in cands}):
            dl.ensure_whisper(be, args.whisper)

        audio, sr = load_sample(args.seconds)

        log(f"\n[實測]（{len(audio) / sr:.0f}s 中文樣本）")
        log(f"  {'後端':<9}{'裝置':<8}{'精度':<13}{'載入s':>7}{'辨識s':>7}{'RTF':>7}  結果")
        results = []
        for be, dev, ct, desc in cands:
            r = {"backend": be, "device": dev, "compute_type": ct, "desc": desc}
            try:
                r.update(bench_one(be, dev, ct, audio, sr, args.whisper))
                r["ok"] = len(r["text"]) >= 10       # 輸出幾乎空白視為失敗（裝置異常）
                status = r["text"][:24] if r["ok"] else "輸出異常（幾乎沒有文字）"
                log(f"  {be:<9}{dev:<8}{ct:<13}{r['load_s']:>7}{r['asr_s']:>7}{r['rtf']:>7.3f}  {status}")
            except Exception as ex:  # noqa: BLE001
                r.update(ok=False, error=str(ex)[:200])
                log(f"  {be:<9}{dev:<8}{ct:<13}  失敗：{str(ex)[:80]}")
            results.append(r)
        best = choose(results)
        if not best:
            log("\n[錯誤] 沒有任何組合成功執行。")
            sys.exit(1)

    # 既有的模型 profile（例如 Breeze）若屬於別的後端，模型會被清掉，profile 也一併移除
    old_cfg = load_config()
    profiles = {k: v for k, v in old_cfg.get("profiles", {}).items() if v.get("backend") == best["backend"]}
    save_config(backend=best["backend"], device=best["device"], compute_type=best.get("compute_type", "default"),
                whisper=args.whisper, profiles=profiles, hardware=inv,
                **detection_fields(results, bool(args.force), old_cfg))
    rtf = f"RTF {best['rtf']:.3f}" if best.get("rtf") else "未測速"
    log(f"\n[選定] {best['backend']} / {best['device']} / {best.get('compute_type', 'default')}（{rtf}）→ 已寫入 config.json")

    used = {best["backend"]}
    if not args.keep_all:
        for be in BACKENDS:
            if be not in used:
                dl.remove_backend_models(be)
    breeze = setup_breeze() if args.breeze else None
    # 最後一行給 install.ps1 解析
    print(json.dumps({"backend": best["backend"], "device": best["device"], "breeze": breeze,
                      "compute_type": best.get("compute_type", "default"), "punct": punct_ok,
                      "prune_ct2_packages": (not args.keep_all) and best["backend"] != "ct2" and sys.platform == "win32"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
