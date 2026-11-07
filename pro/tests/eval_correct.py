"""自動語意校正的實測與計分（1.1.0 起；C1～C5、C1-O）。素材只用合成講稿（materials/）與它的辨識結果（_out/runs/）。

子指令：
  prepare <名稱> <輸出資料夾> [--hotwords "a, b"]
      取 _out/runs/<名稱>-turbo/transcript.json，用目前的 punctuate.py 重新分段標點，寫出 transcript.md／json
      （與 transcribe.py 的 write_outputs 相同格式）。meta.hotwords 換成素材自己的專有名詞（不用真實 glossary）。
  errors <名稱> <資料夾>
      以基準稿（_out/<名稱>.ref.json）對齊辨識結果，列出「已知錯誤」：內容不同的取代區段（數字寫法差異、只差語氣詞、
      ASR 整段漏掉或多出的字不算——校正無從判斷）。
  run <資料夾> --budget-file F --tool claude|codex --max N [--provider …] [--model …] [--effort …] [--timeout S]
      呼叫 auto_correct.run()；每次實際呼叫 CLI 前先在 budget-file 記一筆，超過 --max 就拒絕（不送出）。
  score <名稱> <資料夾>
      對 transcript.corrected.md 計分：修對／只標待確認／錯改／漏改、額外修改、未標記改動（驗證保證為 0）。
      〔1.1.0〕另列 fixed_plus_guess（修對＋待確認且推測正確，C1 新定義）與 c2（退回段數 ÷ 總段數、整塊全退塊數）；
      WORD_VARIANTS（集點／積點）視為相同寫法。
"""
import argparse
import difflib
import json
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path

import _testenv  # noqa: F401
import auto_correct as ac

HERE = Path(__file__).resolve().parent
RUNS = HERE / "_out" / "runs"
CN_NUM = set("零一二三四五六七八九十百千萬億兩點分之到")
VARIANTS = {("週", "周"), ("了", "瞭"), ("紀", "記")}   # 異體或兩種寫法都通：不算錯誤
WORD_VARIANTS = {"集點": "積點"}   # 台灣兩種寫法都通的詞（1.1.0 起的計分規則）：計分時視為相同；左右等長，座標不變


def words_norm(t: str) -> str:
    for a, b in WORD_VARIANTS.items():
        t = t.replace(a, b)
    return t
FILLERS = set("嗯欸誒啊呃喔哦噢吧呢啦嘛耶齁")
HOTWORDS = {   # 素材自己的專有名詞（只給一部分，其他要靠上下文；比照 1.1.0 研究的做法）
    "M1": "示範證券, 家豪, 怡君, 雅婷, 志明, Redis Sentinel, Kafka, Kubernetes",
    "M2": "建宏, 佩珊, 欣怡",
    "M3": "示範證券, 家豪, 怡君, 雅婷, 志明, Redis Sentinel, Kafka, Kubernetes, 建宏, 佩珊, 欣怡",
}


def is_punct(c):
    return unicodedata.category(c).startswith("P") or c in "～~"


def content(t: str) -> str:
    return "".join(c for c in t if not c.isspace() and not is_punct(c))


# ---------------------------------------------------------------- prepare
def prepare(name: str, out: Path, hotwords: str | None):
    from eval_materials import repunct
    import transcribe
    doc = json.loads((RUNS / f"{name}-turbo" / "transcript.json").read_text(encoding="utf-8"))
    doc = repunct(doc, "turbo")
    meta = dict(doc["meta"], hotwords=hotwords if hotwords is not None else HOTWORDS.get(name, ""))
    out.mkdir(parents=True, exist_ok=True)
    transcribe.write_outputs(out, meta, doc["segments"], doc.get("keyframes", []), doc["paragraphs"])
    print(json.dumps({"out": str(out), "paragraphs": len(doc["paragraphs"]),
                      "chars": sum(len(content(s["text"])) for s in doc["segments"])}, ensure_ascii=False))


# ---------------------------------------------------------------- 已知錯誤
def body_paras(md: str) -> list:
    _, items = ac.parse_md(md)
    return [it for it in items if it["kind"] == "para"]


def ref_text(name: str) -> str:
    ref = json.loads((HERE / "_out" / f"{name}.ref.json").read_text(encoding="utf-8"))
    return content("".join(p["text"] for p in ref["paragraphs"]))


def is_trivial(r: str, h: str) -> str | None:
    """不算已知錯誤的差異：回傳原因。"""
    if not r or not h:
        return "漏字／多字"
    if any(c.isdigit() for c in r + h) and all(c in CN_NUM or c.isdigit() or c in "%.／/" for c in r + h):
        return "數字寫法"
    if set(r) <= FILLERS and set(h) <= FILLERS:
        return "語氣詞"
    if r.lower() == h.lower():
        return "大小寫"
    if (r, h) in VARIANTS:
        return "異體字"
    return None


def known_errors(name: str, hyp: str) -> tuple:
    """回傳 (錯誤清單, 排除清單, 對齊器)。錯誤：{"h": [h1, h2), "r": [r1, r2), "wrong", "right"}，座標是內容字元。"""
    ref, hyp = words_norm(ref_text(name)), words_norm(hyp)
    sm = difflib.SequenceMatcher(None, ref.lower(), hyp.lower(), autojunk=False)   # 英文不分大小寫對齊
    regions = [[i1, i2, j1, j2] for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"]
    merged = []
    for g in regions:        # 同一個英文字被字元層對齊切成好幾段（DanaFamilu → DownAfter…）：併成一處
        if merged:
            p = merged[-1]
            gap = hyp[p[3]:g[2]]
            if gap and gap.isascii() and gap.isalnum() and (hyp[p[2]:p[3]] + ref[p[0]:p[1]]).isascii():
                p[1], p[3] = g[1], g[3]
                continue
        merged.append(list(g))
    errs, skipped = [], []
    for i1, i2, j1, j2 in merged:
        r, h = ref[i1:i2], hyp[j1:j2]
        why = is_trivial(r, h)
        item = {"h": [j1, j2], "r": [i1, i2], "wrong": h, "right": r}
        (skipped if why else errs).append(dict(item, why=why) if why else item)
    return errs, skipped, ref, sm


def errors_cmd(name: str, d: Path):
    hyp = content("".join(p["text"] for p in body_paras((d / "transcript.md").read_text(encoding="utf-8"))))
    errs, skipped, _, _ = known_errors(name, hyp)
    for k, e in enumerate(errs, 1):
        print(f"{k:3d}. {e['wrong']} → {e['right']}")
    kinds = {}
    for s in skipped:
        kinds[s["why"]] = kinds.get(s["why"], 0) + 1
    print(json.dumps({"known_errors": len(errs), "excluded": kinds}, ensure_ascii=False))


# ---------------------------------------------------------------- run（有呼叫上限）
def run_cmd(args):
    d = Path(args.dir)
    budget = Path(args.budget_file)
    used = json.loads(budget.read_text(encoding="utf-8")) if budget.exists() else []
    orig = dict(ac.CALLERS)
    tool = {"claude": ("claude", "cli"), "codex": ("openai", "cli")}[args.tool]

    def guarded(be, system, user, timeout, schema=None):
        n = sum(1 for u in used if u["tool"] == args.tool)
        if n >= args.max:
            print(f"  [budget] {args.tool} 已用 {n} 次，達上限 {args.max}：拒絕送出", file=sys.stderr)
            return ac._fail("budget_exceeded")
        t0 = time.time()
        used.append({"tool": args.tool, "at": time.strftime("%H:%M:%S"), "dir": d.name, "model": be["model"],
                     "effort": be["effort"], "kind": "terms" if schema else "chunk"})
        budget.write_text(json.dumps(used, ensure_ascii=False, indent=1), encoding="utf-8")
        r = orig[tool](be, system, user, timeout, schema)
        used[-1].update(ok=r["ok"], reason=r["reason"], sec=round(time.time() - t0, 1))
        budget.write_text(json.dumps(used, ensure_ascii=False, indent=1), encoding="utf-8")
        return r
    ac.CALLERS[tool] = guarded
    cfg = ac.load_config()
    if args.timeout:
        cfg.setdefault("correction", {})["timeout_sec"] = args.timeout
    req = ac.resolve_request(cfg, args.provider, args.model, args.effort, None)
    t0 = time.time()
    res = ac.run(d, req, consent=True, force=True, cfg=cfg)
    res["wall_sec"] = round(time.time() - t0, 1)
    res["exit_code"] = ac.exit_code(res)
    print(json.dumps(res, ensure_ascii=False))


# ---------------------------------------------------------------- score
def num_free(t: str) -> str:
    """計分時數字寫法、異體字、語氣詞不計（八百／800、記／紀、把辨識成 N 的「嗯」刪掉）：去掉數字與語氣詞、
    異體字換成同一寫法，英文不分大小寫。"""
    alt = {h: r for r, h in VARIANTS}
    return "".join(alt.get(c, c) for c in words_norm(t).lower() if not c.isdigit() and c not in CN_NUM and c not in FILLERS)


def tokens(text: str) -> list:
    """把校正版段落拆成 (原文側字元, 目標側字元, 標記編號, 種類)；標點與空白丟掉。"""
    out, k, pos = [], 0, 0
    for m in ac.MARK_RE.finditer(text):
        for c in text[pos:m.start()]:
            if not c.isspace() and not is_punct(c):
                out.append(("plain", c, c, None))
        k += 1
        if m.group(3) is not None:                          # [?a｜b]：原文側＝a，目標側＝推測 b（只用來算「推測對」）
            out.append(("unc", content(m.group(3)), content(m.group(4) or m.group(3)), k))
        else:
            a, b = content(m.group(1) or ""), content(m.group(2) or "")
            out.append(("edit", a, b, k))                   # 一個標記一個 token（原文側可能多字或空）
        pos = m.end()
    for c in text[pos:]:
        if not c.isspace() and not is_punct(c):
            out.append(("plain", c, c, None))
    return out


def score(name: str, d: Path) -> dict:
    corrected = (d / "transcript.corrected.md").read_text(encoding="utf-8")
    body = corrected.split("\n---\n", 1)[1]
    toks = []
    for p in body_paras("# x\n\n" + body):
        toks += tokens(p["text"])
    # 原文側座標
    src_pos, hyp = [], []
    for t in toks:
        src_pos.append(len(hyp))
        hyp += list(t[1])
    hyp = "".join(hyp)
    errs, skipped, ref, sm = known_errors(name, hyp)
    edits = [(i, t) for i, t in enumerate(toks) if t[0] == "edit"]
    uncs = [(i, t) for i, t in enumerate(toks) if t[0] == "unc"]

    ops = sm.get_opcodes()

    def ref_at(j, side):    # 原文側邊界 → 基準稿邊界的候選（非相等區段取該區段的起或迄；同一點可能有好幾個）
        out = []
        for tag, i1, i2, j1, j2 in ops:
            if j1 <= j <= j2:
                if tag == "equal":
                    out.append(i1 + (j - j1))
                else:
                    out.append(i1 if side == "lo" else i2)
        return sorted(set(out)) or [len(ref)]
    def touching(marks, h1, h2):
        return [(i, t) for i, t in marks
                if (src_pos[i] < h2 and src_pos[i] + len(t[1]) > h1) or (not t[1] and h1 <= src_pos[i] <= h2)]

    def judge(touch, h1, h2):
        """把 touch 這些標記換成目標側後，和基準稿比。回傳 (對不對, 模型寫法, 基準寫法)。"""
        lo = min([h1] + [src_pos[i] for i, _ in touch])
        hi = max([h2] + [src_pos[i] + len(t[1]) for i, t in touch])
        ids = {i for i, _ in touch}
        got = "".join(t[2] if i in ids else t[1] for i, t in enumerate(toks)
                      if lo <= src_pos[i] < hi or (i in ids and not t[1] and lo <= src_pos[i] <= hi))
        # ASR 漏掉的字若被模型補回（字安→資安），基準取含漏字的範圍也算對
        wants = [ref[a:b] for a in ref_at(lo, "lo") for b in ref_at(hi, "hi") if a <= b]
        want = min(wants, key=len) if wants else ""
        return any(num_free(got) == num_free(w) for w in wants), got, want

    used_edits = set()
    res = {"fixed": 0, "uncertain": 0, "wrong_fix": 0, "missed": 0}
    unc_right = 0
    detail = []
    others = {"uncertain": [], "missed": []}
    for e in errs:
        h1, h2 = e["h"]
        touch = touching(edits, h1, h2)
        if not touch:
            ut = touching(uncs, h1, h2)
            kind = "uncertain" if ut else "missed"
            if ut and judge(ut, h1, h2)[0]:
                unc_right += 1
            others[kind].append(f"{e['wrong']}→{e['right']}")
        else:
            for i, _ in touch:
                used_edits.add(i)
            ok, got, want = judge(touch, h1, h2)
            kind = "fixed" if ok else "wrong_fix"
            if kind == "wrong_fix":
                detail.append(f"錯改：{e['wrong']}→（模型：{got}／基準：{want}）")
        res[kind] += 1
    extra = [(t[1], t[2]) for i, t in edits if i not in used_edits]
    n = len(errs)
    rec = json.loads((d / "auto_correct.json").read_text(encoding="utf-8"))
    tot = rec.get("totals") or {}
    # C1（1.1.0 起的定義）：修對＋「待確認且推測正確」合計，兩個數字分開列；C2：退回段數 ÷ 總段數
    c2 = {"units": tot.get("units"), "units_rejected": tot.get("units_rejected"),
          "unit_reject_rate": round(tot["units_rejected"] / tot["units"], 3) if tot.get("units") else None,
          "chunks_all_rejected": sum(1 for c in rec.get("chunks") or [] if c.get("reason") == "validation_failed"),
          "rejected_at": [x["time"] for c in rec.get("chunks") or [] for x in c.get("rejects") or []]}
    out = dict(res, uncertain_right_guess=unc_right, known=n, fixed_rate=round(res["fixed"] / n, 3) if n else None,
               fixed_plus_guess=res["fixed"] + unc_right,
               fixed_plus_guess_rate=round((res["fixed"] + unc_right) / n, 3) if n else None, c2=c2,
               wrong_rate=round(res["wrong_fix"] / n, 3) if n else None, extra_edits=len(extra),
               extra_list=[f"{a}→{b}" for a, b in extra], wrong_list=detail,
               uncertain_list=others["uncertain"], missed_list=others["missed"],
               unmarked=0 if rec.get("status") in ("ok", "partial") else None,
               chunks=f"{rec.get('chunks') and sum(1 for c in rec['chunks'] if c['status'] == 'ok')}/{len(rec.get('chunks') or [])}",
               retries=sum(c.get("retries", 0) for c in rec.get("chunks") or []),
               splits=(rec.get("totals") or {}).get("split_paragraphs"), elapsed_sec=rec.get("elapsed_sec"),
               model=rec.get("model_used"), effort=rec.get("effort"), terms=rec.get("terms"))
    return out


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("name")
    p.add_argument("dir")
    p.add_argument("--hotwords")
    e = sub.add_parser("errors")
    e.add_argument("name")
    e.add_argument("dir")
    r = sub.add_parser("run")
    r.add_argument("dir")
    r.add_argument("--budget-file", required=True)
    r.add_argument("--tool", choices=["claude", "codex"], required=True)
    r.add_argument("--max", type=int, required=True)
    r.add_argument("--provider")
    r.add_argument("--model")
    r.add_argument("--effort")
    r.add_argument("--timeout", type=int)
    s = sub.add_parser("score")
    s.add_argument("name")
    s.add_argument("dir")
    s.add_argument("--save", help="把結果另存成 JSON")
    a = ap.parse_args()
    if a.cmd == "prepare":
        prepare(a.name, Path(a.dir), a.hotwords)
    elif a.cmd == "errors":
        errors_cmd(a.name, Path(a.dir))
    elif a.cmd == "run":
        run_cmd(a)
    elif a.cmd == "score":
        r = score(a.name, Path(a.dir))
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if a.save:
            Path(a.save).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
