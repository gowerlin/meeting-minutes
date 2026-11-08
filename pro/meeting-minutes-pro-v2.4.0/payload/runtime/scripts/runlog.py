"""執行 log（1.2.0；規格 §11）：每個輸出資料夾的 run_log.jsonl（一行一個事件）與 $MMH/logs/runs.jsonl（每次執行一列摘要）。

- 檢查點（checkpoint）：開始、結束時間（ISO 8601 含時區）與耗時；等使用者回答的時間另記 wait，不算處理時間。
- 模型呼叫（call）：供應商、通道、模型 ID、effort、token（input／output／cache_read／cache_write／reasoning，能取得的）、
  API 等價費用（價格表 scripts/pricing.json，可用 $MMH/pricing.json 蓋過）；訂閱通道標「等價估算，不另計費」。
  〔2.2.0〕附圖的呼叫另記 images（張數）；tokens 已含圖片 token。correct.refs 檢查點只記數量與原因代碼。
- 不寫逐字稿文字、檔名以外的內容片段或任何金鑰：事件只放名稱、數字、狀態代碼與檔名。寫 log 失敗一律忽略，不影響轉寫。
- 〔2.4.0〕本機限定（規格 2.4.0 §2.5）：privacy 事件記 local_only: true 與來源（config／marker／config+marker）；
  run_summary 與 runs.jsonl 只在本機限定時多 local_only、local_only_source 兩欄（不是本機限定時與 2.3.0 相同）。

一次執行（run）＝同一個 run_id 的事件。入口（右鍵／拖放）先設環境變數 MMP_RUN_ID，再依序呼叫 transcribe.py、
auto_correct.py、auto_minutes.py，最後執行 `runlog.py finish`；沒有 MMP_RUN_ID 時，各腳本自己開一個 run，結束時自己寫摘要。

命令列：
  python runlog.py wait <輸出資料夾> --name ask_correction --start ISO --end ISO   # 入口記等使用者的時間
  python runlog.py finish <輸出資料夾> [--run-id ID]                              # 寫 run_summary 與 runs.jsonl
  python runlog.py summary [--last N] [--csv 檔案]                               # 把 runs.jsonl 彙整成表
"""
import argparse
import contextlib
import csv
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import VERSION, logs_dir, user_pricing_path, utf8_console  # noqa: E402

LOG_NAME = "run_log.jsonl"
RUNS_NAME = "runs.jsonl"
PRICING = Path(__file__).resolve().parent / "pricing.json"
# 〔2.0.0〕subtitles（字幕；2.0.0 新增的檢查點）排在 write_outputs 與 correct 之間
# 〔2.1.0〕html（網頁版；單獨執行 render_html.py 時的階段，排在 minutes 之後。auto_minutes 內是 minutes.html 檢查點，不另成階段）
STAGE_ORDER = ("convert_audio", "keyframes", "diarize", "asr", "punctuate", "write_outputs", "subtitles", "correct",
               "minutes", "html")
STAGE_NAME = {"convert_audio": "轉換音訊", "keyframes": "擷取畫面", "diarize": "說話者分離", "asr": "語音辨識",
              "punctuate": "分段標點", "write_outputs": "輸出檔案", "subtitles": "字幕", "correct": "AI 校正",
              "minutes": "會議摘要", "html": "網頁版",
              "correct.refs": "參考資料",        # 〔2.2.0〕correct 步驟內的檢查點（不另成階段；費用照 call 事件計入校正）
              # 〔2.2.0〕全文用字統一（本機處理）：correct／minutes 步驟內的檢查點；consistency＝單獨執行 consistency.py
              "correct.consistency": "用字統一", "minutes.consistency": "用字統一", "consistency": "用字統一"}
TOKEN_KEYS = ("input", "cache_read", "cache_write", "output", "reasoning")
# 〔2.0.0〕info 事件裡要彙整進 runs.jsonl 的欄位（規格 §6.4）
INFO_KEYS = ("source", "recording_sec", "segments", "paragraphs", "speakers", "asr_model", "device")
INFO_KEYS_V2 = ("content_type", "template", "diarize_engine", "diarize_fallback", "speakers_raw")
DIARIZE_LABEL = {"pyannote": "pyannote", "sherpa": "sherpa", "none": "略過"}
BASIS_NOTE = {"subscription_equivalent": "等價估算，不另計費", "api": "依 API 用量計費（估算）"}


def now() -> datetime:
    return datetime.now().astimezone()


def iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds")


def parse_iso(s: str) -> datetime:
    """接受 Python／PowerShell（.fff）／date +%z（+0800）的寫法。"""
    s = (s or "").strip()
    m = re.match(r"^(.*?)([+-]\d{2})(\d{2})$", s)
    if m and ":" not in s[-6:]:
        s = f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.astimezone()


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------- token 與費用
def normalize_usage(provider: str, usage: dict | None) -> dict:
    """呼叫器回傳的 usage → 五個欄位。input＝不含快取的輸入；reasoning 是 output 的一部分（只供參考，不另計價）。

    - Claude：呼叫器的 input 已含 cache_creation（cache_write），這裡拆開；reasoning 只有 CLI 回報 thinking 時才有。
    - OpenAI／Codex：input_tokens 含 cached（cache_read），這裡扣掉；reasoning＝reasoning_output_tokens。
    取不到的欄位是 None（不是 0）。"""
    u = usage or {}
    cr = int(u.get("cache_read") or 0)
    if provider == "claude":
        cw = int(u.get("cache_write") or 0)
        inp = max(0, int(u.get("input") or 0) - cw)
    else:
        cw = 0
        inp = max(0, int(u.get("input") or 0) - cr)
    th = u.get("thinking")
    return {"input": inp, "cache_read": cr, "cache_write": cw, "output": int(u.get("output") or 0),
            "reasoning": int(th) if th is not None else None}


def load_prices() -> dict:
    """內建 pricing.json，再以 $MMH/pricing.json 的同名項目蓋過（逐鍵合併）。讀不到就回傳空表。"""
    try:
        base = json.loads(PRICING.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        base = {"models": {}}
    try:
        user = json.loads(user_pricing_path().read_text(encoding="utf-8"))
        for k, v in (user.get("models") or {}).items():
            base.setdefault("models", {}).setdefault(k, {}).update(v)
        if user.get("updated"):
            base["user_updated"] = user["updated"]
    except Exception:  # noqa: BLE001
        pass
    return base


def price_for(prices: dict, provider: str, model: str | None) -> tuple:
    """回傳 (價格表鍵, 價格) 或 (None, None)。完整 ID、別名、帶日期的 ID（gpt-…-2026-01-01）都對得上。"""
    m = (model or "").lower()
    if not m:
        return None, None
    for key, p in (prices.get("models") or {}).items():
        if not key.startswith(provider + ":"):
            continue
        for i in p.get("ids") or [key.split(":", 1)[1]]:
            i = i.lower()
            if m == i or m.startswith(i + "-") or (provider == "claude" and re.search(rf"\b{re.escape(i)}\b", m)):
                return key, p
    return None, None


def cost_of(prices: dict, provider: str, channel: str, auth: str | None, model: str | None, nu: dict) -> dict:
    """API 等價費用。Claude CLI 的 prompt cache 是 1 小時 TTL（1.1.0 開發前實測），API 通道沒有設快取，用 5 分鐘價。"""
    key, p = price_for(prices, provider, model)
    basis = "api" if channel == "api" or auth == "api_key" else "subscription_equivalent"
    if not p:
        return {"cost_usd": None, "price_key": None, "cost_basis": basis}
    cw_rate = p.get("cache_write_1h" if (provider == "claude" and channel == "cli") else "cache_write_5m", 0) or 0
    usd = (nu["input"] * p.get("input", 0) + nu["cache_read"] * p.get("cache_read", 0)
           + nu["cache_write"] * cw_rate + nu["output"] * p.get("output", 0)) / 1e6
    return {"cost_usd": round(usd, 6), "price_key": key, "cost_basis": basis}


# ---------------------------------------------------------------- 事件
class RunLog:
    """一個輸出資料夾的 log。owns＝這個行程負責寫 run_summary（沒有外層的 MMP_RUN_ID）。"""

    def __init__(self, out_dir, run_id: str | None = None, owns: bool | None = None, step: str | None = None):
        self.out_dir = Path(out_dir)
        self.path = self.out_dir / LOG_NAME
        env = os.environ.get("MMP_RUN_ID")
        self.run_id = run_id or env or new_run_id()
        self.owns = owns if owns is not None else not (run_id or env)
        self.step = step
        self._prices = None

    def event(self, kind: str, **fields):
        rec = {"ts": iso(now()), "run_id": self.run_id, "event": kind, "version": VERSION}   # 〔1.2.0〕每個事件都帶 runtime 版號
        if self.step and "step" not in fields:
            rec["step"] = self.step
        rec.update({k: v for k, v in fields.items() if v is not None})
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001  寫 log 失敗不影響主流程
            pass
        return rec

    @contextlib.contextmanager
    def checkpoint(self, name: str, **fields):
        """with log.checkpoint("asr") as cp: …; cp["segments"] = n   （cp 裡的鍵會寫進結束事件）"""
        t0, w0 = now(), time.perf_counter()
        info = dict(fields)
        status = "ok"
        try:
            yield info
        except BaseException:
            status = "error"
            raise
        finally:
            self.event("checkpoint", name=name, started_at=iso(t0), ended_at=iso(now()),
                       duration_sec=round(time.perf_counter() - w0, 3), status=info.pop("status", status), **info)

    def begin(self, name: str, **fields) -> dict:
        """不方便用 with 時：h = log.begin("asr") … log.end(h, segments=n)。"""
        return {"name": name, "t0": now(), "w0": time.perf_counter(), "fields": fields}

    def end(self, h: dict, **fields):
        f = dict(h["fields"], **fields)
        return self.event("checkpoint", name=h["name"], started_at=iso(h["t0"]), ended_at=iso(now()),
                          duration_sec=round(time.perf_counter() - h["w0"], 3), status=f.pop("status", "ok"), **f)

    def wait(self, name: str, started_at: str, ended_at: str):
        a, b = parse_iso(started_at), parse_iso(ended_at)
        return self.event("wait", name=name, started_at=iso(a), ended_at=iso(b),
                          duration_sec=round(max(0.0, (b - a).total_seconds()), 3))

    def call(self, be: dict, r: dict, started: datetime, ended: datetime, duration: float, **ctx):
        """一次模型呼叫。be＝auto_correct.select_backend() 的結果，r＝呼叫器的回傳（_ok／_fail）。"""
        if self._prices is None:
            self._prices = load_prices()
        prov = be.get("provider")
        nu = normalize_usage(prov, r.get("usage"))
        model = r.get("model") or be.get("model_api") or be.get("model")
        c = cost_of(self._prices, prov, be.get("channel"), be.get("auth"), model, nu)
        return self.event("call", started_at=iso(started), ended_at=iso(ended), duration_sec=round(duration, 3),
                          provider=prov, channel=be.get("channel"), model_requested=be.get("model"), model=model,
                          effort=be.get("effort"), status="ok" if r.get("ok") else "failed", reason=r.get("reason"),
                          tokens=nu, cost_usd=c["cost_usd"], cost_basis=c["cost_basis"],
                          cost_note=BASIS_NOTE[c["cost_basis"]], price_key=c["price_key"],
                          cli_reported_usd=r.get("cost"), cli_version=be.get("cli_version"), **ctx)

    def privacy(self, state: dict | None):
        """〔2.4.0〕本機限定：common.local_only_state() 的結果。None（不是本機限定）時不寫任何事件。"""
        if not state:
            return None
        return self.event("privacy", local_only=True, local_only_source=state.get("source"))

    def info_from_transcript(self):
        """單獨執行 auto_correct／auto_minutes 時，從 transcript.json 補錄音長度、段數、講者數（只取數字與檔名）。"""
        try:
            doc = json.loads((self.out_dir / "transcript.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        meta = doc.get("meta") or {}
        dz = meta.get("diarization") or {}                  # 〔2.0.0〕2.0 轉寫的才有；1.x 的 transcript.json 沒有這些欄位
        return self.event("info", source=meta.get("source"), recording_sec=meta.get("duration"),
                          segments=len(doc.get("segments") or []), paragraphs=len(doc.get("paragraphs") or []),
                          speakers=meta.get("speakers"), asr_model=meta.get("model"), device=meta.get("device"),
                          content_type=meta.get("content_type"), template=meta.get("template"),
                          diarize_engine=dz.get("engine"), diarize_fallback=dz.get("fallback"),
                          speakers_raw=dz.get("speakers_raw"))

    def finish(self):
        """寫 run_summary 事件，並在 $MMH/logs/runs.jsonl 追加一列。回傳摘要（失敗時 None）。"""
        try:
            s = summarize(read_events(self.path, self.run_id), self.out_dir)
        except Exception:  # noqa: BLE001
            return None
        self.event("run_summary", **{k: v for k, v in s.items() if k not in ("run_id",)})
        try:
            d = logs_dir()
            d.mkdir(parents=True, exist_ok=True)
            with open(d / RUNS_NAME, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass
        return s


def read_events(path: Path, run_id: str | None = None) -> list:
    out = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if run_id is None or ev.get("run_id") == run_id:
                out.append(ev)
    except FileNotFoundError:
        pass
    return out


def summarize(events: list, out_dir: Path) -> dict:
    """同一個 run 的事件 → 摘要列（runs.jsonl 的格式，規格 §11.3）。"""
    if not events:
        raise ValueError("no events")
    run_id = events[0]["run_id"]
    stages, calls, waits, steps, statuses, cli_versions = {}, [], 0.0, [], {}, []
    info = {}
    privacy = []                                          # 〔2.4.0〕本機限定的來源（依出現順序、不重複）
    for ev in events:
        k = ev.get("event")
        if k == "privacy" and ev.get("local_only"):
            for src in str(ev.get("local_only_source") or "").split("+"):
                if src and src not in privacy:
                    privacy.append(src)
        if k == "checkpoint" and "." not in ev.get("name", ""):
            stages[ev["name"]] = round(stages.get(ev["name"], 0.0) + float(ev.get("duration_sec") or 0), 3)
        elif k == "call":
            calls.append(ev)
            cv = ev.get("cli_version")
            if cv and cv not in cli_versions:
                cli_versions.append(cv)
        elif k == "wait":
            waits += float(ev.get("duration_sec") or 0)
        elif k == "info":
            info.update({x: ev[x] for x in INFO_KEYS + INFO_KEYS_V2 if ev.get(x) is not None})
        elif k == "result":
            st = ev.get("step")
            statuses[st] = {"status": ev.get("status"), "reason": ev.get("reason")}
        if ev.get("step") and ev["step"] not in steps and ev["step"] != "entry":
            steps.append(ev["step"])
    tokens = {t: 0 for t in TOKEN_KEYS}
    reasoning_known = False
    cost, cost_known, bases, models = 0.0, True, set(), []
    for c in calls:
        for t in TOKEN_KEYS:
            v = (c.get("tokens") or {}).get(t)
            if v is not None:
                tokens[t] += v
                reasoning_known |= t == "reasoning"
        if c.get("cost_usd") is None:
            cost_known = False
        else:
            cost += c["cost_usd"]
        bases.add(c.get("cost_basis"))
        label = f"{c.get('step', '?')}:{c.get('provider')}:{c.get('model_requested') or c.get('model')}:{c.get('effort')}:{c.get('channel')}"
        if label not in models:
            models.append(label)
    if not reasoning_known:
        tokens["reasoning"] = None
    ts = [parse_iso(ev["ts"]) for ev in events if ev.get("ts")]
    proc = round(sum(stages.values()), 3)
    rec_sec = info.get("recording_sec")
    basis = None if not bases else (bases.pop() if len(bases) == 1 else "mixed")
    total_cost = round(cost, 6)
    extra = {"local_only": True, "local_only_source": "+".join(privacy)} if privacy else {}   # 〔2.4.0〕
    return {**{
        "run_id": run_id, "version": VERSION, "finished_at": iso(now()), "out_dir": str(out_dir),
        "source": info.get("source"), "recording_sec": rec_sec, "segments": info.get("segments"),
        "paragraphs": info.get("paragraphs"), "speakers": info.get("speakers"),
        "asr_model": info.get("asr_model"), "device": info.get("device"),
        # 〔2.0.0〕新欄位（規格 §6.4）；沒有轉寫步驟的 run（單獨執行 auto_minutes 等）取自 transcript.json
        "content_type": info.get("content_type"), "template": info.get("template"),
        "diarize_engine": info.get("diarize_engine"), "diarize_fallback": info.get("diarize_fallback"),
        "speakers_raw": info.get("speakers_raw"),
        "steps": steps, "results": statuses,
        "started_at": iso(min(ts)) if ts else None,
        "processing_sec": proc, "wait_sec": round(waits, 3),
        "wall_sec": round((max(ts) - min(ts)).total_seconds(), 3) if ts else None,
        "stages": {k: stages[k] for k in sorted(stages, key=lambda x: (STAGE_ORDER.index(x) if x in STAGE_ORDER else 99, x))},
        "calls": len(calls), "calls_failed": sum(1 for c in calls if c.get("status") != "ok"),
        "tokens": tokens, "cost_usd": total_cost, "cost_complete": cost_known, "cost_basis": basis,
        "cost_note": BASIS_NOTE.get(basis) if basis in BASIS_NOTE else ("部分訂閱、部分 API" if basis == "mixed" else None),
        "cost_per_recording_hour_usd": round(total_cost / (rec_sec / 3600), 4) if rec_sec and calls else None,
        "models": models, "cli_versions": cli_versions,
        "versions_seen": sorted({ev["version"] for ev in events if ev.get("version")}),
    }, **extra}


# ---------------------------------------------------------------- 彙整工具
def _fmt_sec(s) -> str:
    if s is None:
        return "—"
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def diarize_label(r: dict) -> str:
    """〔2.0.0〕summary 的「分離」欄：pyannote／sherpa／略過，退回 sherpa 時 sherpa*（規格 §6.4、§9.3）。

    1.x 的紀錄沒有 diarize_engine：有 diarize 階段＝sherpa（1.x 只有 sherpa）；有轉寫但沒有 diarize 階段＝略過；
    沒有轉寫階段（只做校正或摘要）＝—。"""
    eng = r.get("diarize_engine")
    if eng:
        lab = DIARIZE_LABEL.get(eng, eng)
        return lab + "*" if eng == "sherpa" and r.get("diarize_fallback") else lab
    st = r.get("stages") or {}
    if "diarize" in st:
        return "sherpa"
    return "略過" if "asr" in st else "—"


def summary_rows(runs: list) -> list:
    rows = []
    for r in runs:
        st = r.get("stages") or {}
        transcribe = sum(v for k, v in st.items() if k not in ("correct", "minutes", "html"))   # 〔2.1.0〕網頁版不算轉寫
        tok = r.get("tokens") or {}
        rows.append({
            "日期": (r.get("started_at") or r.get("finished_at") or "")[:16].replace("T", " "),
            "來源": r.get("source") or Path(r.get("out_dir") or "").name,
            "類型": r.get("content_type") or "meeting",            # 〔2.0.0〕舊紀錄沒有 content_type＝meeting（規格 §9.3）
            "分離": diarize_label(r),
            "錄音": _fmt_sec(r.get("recording_sec")),
            "處理": _fmt_sec(r.get("processing_sec")),
            "轉寫": _fmt_sec(transcribe) if transcribe else "—",
            "校正": _fmt_sec(st.get("correct")) if "correct" in st else "—",
            "摘要": _fmt_sec(st.get("minutes")) if "minutes" in st else "—",
            "等待": _fmt_sec(r.get("wait_sec")) if r.get("wait_sec") else "—",
            "呼叫": r.get("calls", 0),
            "token(入/出)": f"{(tok.get('input') or 0) + (tok.get('cache_read') or 0) + (tok.get('cache_write') or 0):,}/{tok.get('output') or 0:,}",
            "費用US$": f"{r['cost_usd']:.3f}" if r.get("calls") else "—",
            "每小時錄音US$": f"{r['cost_per_recording_hour_usd']:.3f}" if r.get("cost_per_recording_hour_usd") is not None else "—",
            "處理/錄音": f"{r['processing_sec'] / r['recording_sec']:.2f}" if r.get("recording_sec") else "—",
        })
    return rows


def print_table(rows: list):
    if not rows:
        print("（runs.jsonl 沒有紀錄）")
        return
    cols = list(rows[0])

    def w(s):
        return sum(2 if ord(ch) > 0x2E7F else 1 for ch in str(s))
    widths = {c: max(w(c), *(w(r[c]) for r in rows)) for c in cols}
    print("  ".join(c + " " * (widths[c] - w(c)) for c in cols))
    for r in rows:
        print("  ".join(str(r[c]) + " " * (widths[c] - w(r[c])) for c in cols))


def load_runs(path: Path | None = None) -> list:
    p = path or (logs_dir() / RUNS_NAME)
    return read_events(p) if p.exists() else []


def main():
    utf8_console()
    ap = argparse.ArgumentParser(description="meeting-minutes-pro 執行 log")
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("wait", help="記一段等使用者回答的時間（不算處理時間）")
    w.add_argument("out_dir")
    w.add_argument("--name", required=True)
    w.add_argument("--start", required=True)
    w.add_argument("--end", required=True)
    w.add_argument("--run-id")
    f = sub.add_parser("finish", help="寫 run_summary 與 $MMH/logs/runs.jsonl")
    f.add_argument("out_dir")
    f.add_argument("--run-id")
    s = sub.add_parser("summary", help="把 $MMH/logs/runs.jsonl 彙整成表")
    s.add_argument("--last", type=int, default=0, help="只列最後 N 筆")
    s.add_argument("--csv", help="另存成 CSV（UTF-8 BOM，Excel 可直接開）")
    s.add_argument("--file", help="指定 runs.jsonl（預設 $MMH/logs/runs.jsonl）")
    args = ap.parse_args()
    if args.cmd == "wait":
        RunLog(args.out_dir, args.run_id, owns=False, step="entry").wait(args.name, args.start, args.end)
    elif args.cmd == "finish":
        rid = args.run_id or os.environ.get("MMP_RUN_ID")
        if not rid:
            sys.exit("需要 --run-id 或環境變數 MMP_RUN_ID")
        lg = RunLog(args.out_dir, rid, owns=True)
        if not read_events(lg.path, rid):
            sys.exit(0)
        s = lg.finish()
        if s:
            print(json.dumps({"run_id": rid, "processing_sec": s["processing_sec"], "cost_usd": s["cost_usd"]},
                             ensure_ascii=False))
    else:
        runs = load_runs(Path(args.file) if args.file else None)
        if args.last:
            runs = runs[-args.last:]
        rows = summary_rows(runs)
        print_table(rows)
        hrs = sum((r.get("recording_sec") or 0) for r in runs) / 3600
        cost = sum((r.get("cost_usd") or 0) for r in runs)
        proc = sum((r.get("processing_sec") or 0) for r in runs)
        if runs:
            print(f"\n共 {len(runs)} 次、錄音 {hrs:.2f} 小時、處理 {_fmt_sec(proc)}、API 等價 US${cost:.3f}"
                  + (f"（每小時錄音 US${cost / hrs:.3f}）" if hrs else "")
                  + "；訂閱通道是等價估算，不另計費")
        if args.csv and rows:
            with open(args.csv, "w", encoding="utf-8-sig", newline="") as fh:
                wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
                wr.writeheader()
                wr.writerows(rows)
            print(f"已寫入 {args.csv}")


if __name__ == "__main__":
    main()
