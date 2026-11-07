"""〔2.0.0〕假的 diarize_pyannote.py（規格 §10.3 第 7 點；D-5 退回測試用）。介面與真的相同，行為由環境變數決定：

- FAKE_PYANNOTE_MODE：
  ok（預設）       寫 FAKE_PYANNOTE_SEGS（JSON，預設兩位講者）的段落，exit 0
  fail:<reason>   寫 {"ok": false, "reason": <reason>}，exit 1（load_failed／cuda_error／oom／audio_error…）
  sleep           睡 60 秒（測逾時）
  badjson         寫壞的 JSON，exit 0
  nojson          什麼都不寫，exit 1
  wrongshape      ok 但 segments 格式不對
  empty           ok 但 segments 是空的
  overlap         ok，回傳互相重疊的段落（測主行程截掉重疊）
  noisy           ok，另在 stderr 印進度與一段假的錯誤訊息（含假權杖、假逐字稿；測主行程不轉印、不寫 log）
- FAKE_PYANNOTE_RECORD：有設定時把收到的參數與幾個環境變數寫成 JSON（測主行程怎麼呼叫）。
"""
import argparse
import json
import os
import sys
import time

DEFAULT_SEGS = [[0.5, 4.0, 0], [4.2, 8.0, 1], [8.1, 12.0, 0], [12.5, 15.0, 1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--min-seg", type=float, default=0.4)
    ap.add_argument("--annotation", default="exclusive")
    a = ap.parse_args()
    rec = os.environ.get("FAKE_PYANNOTE_RECORD")
    if rec:
        with open(rec, "w", encoding="utf-8") as f:
            json.dump({"argv": sys.argv[1:], "env": {k: os.environ.get(k) for k in (
                "HF_HUB_OFFLINE", "PYANNOTE_METRICS_ENABLED", "CUDA_VISIBLE_DEVICES", "PYTHONDONTWRITEBYTECODE")},
                "dont_write_bytecode": sys.dont_write_bytecode}, f)
    mode = os.environ.get("FAKE_PYANNOTE_MODE", "ok")
    segs = json.loads(os.environ.get("FAKE_PYANNOTE_SEGS") or json.dumps(DEFAULT_SEGS))

    def ok(seg_list):
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"ok": True, "segments": seg_list, "speakers": len({s[2] for s in seg_list}) if seg_list else 0,
                       "device": "cuda:0", "gpu_name": "Fake GPU", "torch": "0.0.0+fake", "pyannote": "0.0.0",
                       "init_sec": 0.1, "process_sec": 0.2, "peak_mib": 123,
                       "annotation": "exclusive_speaker_diarization"}, f)
        return 0
    if mode.startswith("fail:"):
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"ok": False, "reason": mode.split(":", 1)[1], "detail": "RuntimeError"}, f)
        return 1
    if mode == "sleep":
        time.sleep(60)
        return ok(segs)
    if mode == "badjson":
        with open(a.out, "w", encoding="utf-8") as f:
            f.write("{not json")
        return 0
    if mode == "nojson":
        return 1
    if mode == "wrongshape":
        return ok([[1.0, "x"]])
    if mode == "empty":
        return ok([])
    if mode == "overlap":
        return ok([[0.0, 5.0, 0], [4.0, 9.0, 1], [8.8, 9.1, 0], [9.5, 12.0, 0]])
    if mode == "noisy":
        for p in (0, 50, 100):
            print(f"progress {p}", file=sys.stderr, flush=True)
        print("Traceback: hf_FAKEtokenFAKEtokenFAKEtoken1234 在會議室討論預算分配的事情 C:\\secret\\path", file=sys.stderr)
        return ok(segs)
    return ok(segs)


if __name__ == "__main__":
    sys.exit(main())
