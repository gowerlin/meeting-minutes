"""會議摘要的實測與計分（1.2.0 起）。只用合成素材（tests/materials、tests/_out 的辨識結果）。

  prepare M1|M2|M3 <資料夾>              從 _out/runs/<M>-turbo 複製 transcript.md／.json（辨識結果，未校正）
  run <資料夾> --budget-file F --tool claude|codex --max N [--provider P] [--model M] [--effort E] [--source S]
      呼叫 auto_minutes.run(force=True)；每次實際呼叫 CLI 前先在 budget-file 記一筆，達到 --max 就拒絕（不送出）。
  score M1|M2|M3 <資料夾> [--json 檔案]    依 materials/minutes-ref.json 計分

計分（規格附錄 F）：
- 涵蓋率：基準的每個決議／待辦，在會議記錄的同一列（決議表或待辦表的一列）裡每組關鍵詞都命中才算涵蓋；
  在另一張表命中的另計「別表」（分類不同，但有寫到）。議題以每個議題的標題＋內容計；下次會議以第六節計。
- 杜撰候選：決議表、待辦表裡對不上任何基準項目的列，全部列出，由人逐列判斷（逐字稿有講、只是基準沒列 → 合理；
  逐字稿沒講或內容不對 → 杜撰）。程式不自動判定杜撰。
- 時間碼：決議、待辦、待釐清每一列有沒有 HH:MM:SS。
- 耗時、token、費用：讀 run_log.jsonl 的 call 事件。
- 〔1.2.2〕待釐清問題：基準的 questions（會中有人提出、到最後沒有答覆或決定的問題）有沒有出現在〈五、待釐清問題〉的一列
  （必列項目漏掉＝不合格；寫在議題、決議或待辦另計「別處」）；〈五〉的每一列全部列出，由人逐列判定
  （合理／已有答覆／現況說明／自行提出）。程式不自動判定。
- 〔2.0.0〕C-M2：M2-Q2（夏季庫存出清後剩下約 300 萬怎麼處理）維持**必列**：原話「要先收到應收帳款才行」
  「這個要一起考慮」只講了條件，沒有講好怎麼決定、由誰決定或什麼時候決定，屬規則 6 (a) 收窄後「仍然要列」的那一種。
  寫成議題結論（例「剩下的部分要和應收帳款一起考慮」）而沒有列進〈五〉→ 照現行計法算「別處」，**仍算漏列**。基準不改。
- 〔2.0.0〕C-M 的門檻（規格 §10.2）：M1 的 M1-Q1、M2 的 M2-Q1 與 M2-Q2、M3 的三題都要在〈五〉；sol low、opus medium
  各 2 次，任一次漏列即未達標；決議／待辦／議題不低於 1.2.2 附錄 H.2；杜撰 0（逐列人工判定）。
"""
import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

import _testenv  # noqa: F401
import auto_correct as ac
import auto_minutes as am
import runlog

HERE = Path(__file__).resolve().parent
REF = json.loads((HERE / "materials" / "minutes-ref.json").read_text(encoding="utf-8"))
TC = re.compile(r"\d{2}:\d{2}:\d{2}")


def refs(name: str) -> dict:
    if name == "M3":
        return {k: REF["M1"].get(k, []) + REF["M2"].get(k, []) for k in ("decisions", "actions", "topics", "next_meeting", "questions")}
    return REF[name]


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def hit(groups: list, text: str) -> bool:
    t = norm(text)
    return all(any(norm(a) in t for a in g) for g in groups)


def sections(md: str) -> dict:
    out, cur = {}, None
    for line in md.splitlines():
        m = re.match(r"^## ([一二三四五六])、", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return out


def table_rows(lines: list, prefix: str) -> list:
    return [line for line in lines if re.match(rf"^\| {prefix}\d+ \|", line)]


def topic_blocks(lines: list) -> list:
    blocks, cur = [], None
    for line in lines:
        if line.startswith("### "):
            cur = [line]
            blocks.append(cur)
        elif cur is not None:
            cur.append(line)
    return ["\n".join(b) for b in blocks]


def score(name: str, d: Path) -> dict:
    md = (d / "meeting-minutes.md").read_text(encoding="utf-8")
    sec = sections(md)
    dec_rows, act_rows = table_rows(sec.get("三", []), "D"), table_rows(sec.get("四", []), "A")
    q_rows = table_rows(sec.get("五", []), "Q")
    tblocks = topic_blocks(sec.get("二", []))
    r = refs(name)
    res = {"material": name, "dir": str(d), "items": {}}

    def cover(kind, rows, other, items=None):
        items = r.get(kind, []) if items is None else items
        got, alt, miss = [], [], []
        for it in items:
            if any(hit(it["any"], row) for row in rows):
                got.append(it["id"])
            elif any(hit(it["any"], row) for row in other):
                alt.append(it["id"])
            else:
                miss.append(it["id"])
        return {"total": len(items), "covered": len(got), "other_table": len(alt), "missed": miss, "alt": alt}

    res["items"]["decisions"] = cover("decisions", dec_rows, act_rows + q_rows)
    res["items"]["actions"] = cover("actions", act_rows, dec_rows + q_rows)
    res["items"]["topics"] = cover("topics", tblocks, [])
    res["items"]["next_meeting"] = cover("next_meeting", ["\n".join(sec.get("六", []))], [])
    qs = r.get("questions", [])                # 〔1.2.2〕必列／選列的待釐清問題
    res["items"]["questions"] = cover("questions", q_rows, tblocks + dec_rows + act_rows, [q for q in qs if not q.get("optional")])
    res["items"]["questions_optional"] = cover("questions", q_rows, tblocks + dec_rows + act_rows, [q for q in qs if q.get("optional")])
    res["question_rows"] = q_rows
    all_ref = r["decisions"] + r["actions"]
    res["unmatched_rows"] = [row for row in dec_rows + act_rows if not any(hit(it["any"], row) for it in all_ref)]
    rows = dec_rows + act_rows + q_rows
    res["rows"] = {"decisions": len(dec_rows), "actions": len(act_rows), "questions": len(q_rows), "topics": len(tblocks)}
    heads = set(re.findall(r"^\*\*\[(\d{2}:\d{2}:\d{2})\]", (d / "transcript.md").read_text(encoding="utf-8"), re.M))
    tcs = [m.group(0) for x in rows for m in [TC.search(x)] if m]
    res["timecodes"] = {"rows": len(rows), "with_tc": len(tcs), "on_paragraph_start": sum(1 for t in tcs if t in heads)}
    res["actions_owner"] = sum(1 for x in act_rows if x.split("|")[3].strip() not in ("—", "（未指定）", ""))
    ev = runlog.read_events(d / runlog.LOG_NAME)
    calls = [e for e in ev if e.get("event") == "call" and str(e.get("stage", "")).startswith("minutes")]
    if calls:                                  # 同一個資料夾跑過好幾次時只算最後一次
        last = calls[-1]["run_id"]
        calls = [c for c in calls if c["run_id"] == last]
    res["calls"] = len(calls)
    res["call_sec"] = round(sum(c["duration_sec"] for c in calls), 1)
    res["tokens"] = {k: sum((c.get("tokens") or {}).get(k) or 0 for c in calls) for k in runlog.TOKEN_KEYS}
    res["cost_usd"] = round(sum(c.get("cost_usd") or 0 for c in calls), 4)
    res["cli_reported_usd"] = round(sum(c.get("cli_reported_usd") or 0 for c in calls), 4) or None
    res["models"] = sorted({f"{c['provider']}:{c.get('model')}:{c.get('effort')}" for c in calls})
    try:
        rec = json.loads((d / "auto_minutes.json").read_text(encoding="utf-8"))
        res["status"], res["parts"], res["merge_mode"] = rec.get("status"), len(rec.get("parts") or []), rec.get("merge_mode")
        res["elapsed_sec"] = rec.get("elapsed_sec")
    except Exception:  # noqa: BLE001
        pass
    return res


def run_cmd(args):
    budget = Path(args.budget_file)
    used = json.loads(budget.read_text(encoding="utf-8")) if budget.exists() else []
    key = ("claude", "cli") if args.tool == "claude" else ("openai", "cli")
    orig = ac.CALLERS[key]

    def guarded(be, system, user, timeout, schema=None):
        n = sum(1 for u in used if u["tool"] == args.tool)
        if n >= args.max:
            print(f"  [budget] {args.tool} 已用 {n} 次，達上限 {args.max}：拒絕送出", file=sys.stderr)
            return ac._fail("budget_exceeded")
        used.append({"tool": args.tool, "dir": str(args.dir), "type": "meeting", "model": be["model"], "effort": be["effort"],
                     "at": runlog.iso(runlog.now())})
        budget.write_text(json.dumps(used, ensure_ascii=False, indent=1), encoding="utf-8")
        r = orig(be, system, user, timeout, schema)
        # 〔1.2.2〕每次呼叫輸出的待釐清問題記在 eval_questions.jsonl（只在評估資料夾；看是分段還是彙整刪掉了問題）
        stage = {am.SYSTEM_MINUTES: "single", am.SYSTEM_PART: "part", am.SYSTEM_MERGE: "merge",
                 getattr(am, "SYSTEM_RECHECK", None): "recheck"}.get(system, "other")    # 〔2.0.0〕彙整後的待釐清補判
        qs = (r.get("structured") or {}).get("questions") if r.get("ok") and isinstance(r.get("structured"), dict) else None
        with open(Path(args.dir) / "eval_questions.jsonl", "a", encoding="utf-8") as f:
            print(json.dumps({"stage": stage, "ok": bool(r.get("ok")), "questions": qs}, ensure_ascii=False), file=f)
        return r
    ac.CALLERS[key] = guarded
    prov = args.provider or ("claude" if args.tool == "claude" else "openai")
    req = ac.resolve_request({}, prov, args.model, args.effort, "cli", section="minutes")
    t0 = time.time()
    res = am.run(Path(args.dir), req, force=True, source=args.source, cfg={})
    print(json.dumps({k: res[k] for k in ("status", "reason", "model", "parts", "parts_ok", "source_file")}, ensure_ascii=False))
    print(f"  {time.time() - t0:.0f}s；{args.tool} 累計 {sum(1 for u in used if u['tool'] == args.tool)} 次")


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("material", choices=["M1", "M2", "M3"])
    p.add_argument("dir")
    r = sub.add_parser("run")
    r.add_argument("dir")
    r.add_argument("--budget-file", required=True)
    r.add_argument("--tool", choices=["claude", "codex"], required=True)
    r.add_argument("--max", type=int, required=True)
    r.add_argument("--provider")
    r.add_argument("--model")
    r.add_argument("--effort")
    r.add_argument("--source", default="auto")
    s = sub.add_parser("score")
    s.add_argument("material", choices=["M1", "M2", "M3"])
    s.add_argument("dir")
    s.add_argument("--json")
    args = ap.parse_args()
    if args.cmd == "prepare":
        d = Path(args.dir)
        d.mkdir(parents=True, exist_ok=True)
        for n in ("transcript.md", "transcript.json"):
            shutil.copy(HERE / "_out" / "runs" / f"{args.material}-turbo" / n, d / n)
        print(f"prepared {d}")
    elif args.cmd == "run":
        run_cmd(args)
    else:
        res = score(args.material, Path(args.dir))
        if args.json:
            Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        it = res["items"]
        print(f"[{args.material}] {res.get('models')} status={res.get('status')} parts={res.get('parts')} merge={res.get('merge_mode')}")
        for k in ("decisions", "actions", "topics", "next_meeting", "questions", "questions_optional"):
            v = it[k]
            if v["total"]:
                print(f"  {k:12s} {v['covered']}/{v['total']}（別表 {v['other_table']}）漏：{', '.join(v['missed']) or '—'}")
        print(f"  列數 {res['rows']}；時間碼 {res['timecodes']['with_tc']}/{res['timecodes']['rows']}；待辦有負責人 {res['actions_owner']}/{res['rows']['actions']}")
        print(f"  呼叫 {res['calls']} 次 {res['call_sec']}s；tokens {res['tokens']}；API 等價 US${res['cost_usd']}（CLI 回報 {res['cli_reported_usd']}）")
        print(f"  待釐清（逐列人工判定：合理／已有答覆／現況說明／自行提出）{len(res['question_rows'])}：")
        for row in res["question_rows"]:
            print("    " + row[:160])
        print(f"  杜撰候選（對不上基準的列，人工判斷）{len(res['unmatched_rows'])}：")
        for row in res["unmatched_rows"]:
            print("    " + row[:160])


if __name__ == "__main__":
    main()
