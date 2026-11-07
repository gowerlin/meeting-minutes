"""素材評估：P1～P4（標點、分段、效能）、K7（回復表素材回歸）、R（1.0.0 回歸）。讀 run_matrix.py 的輸出。

指標沿用 1.1.0 研究的定義：
- 標點：基準稿與待測稿各自去掉標點與空白得到「內容字元」，記下每個內容字元後面有沒有斷點（句末 。？！＝E，
  句中 ，、；：＝M；段落結尾一律算 E）；以 difflib 對齊內容字元，把待測斷點映到基準座標，容許 ±1 字，算 P/R/F1。
  「任何斷點」不分種類；另算「句末斷點」。
- 段落：段落開頭位置映到基準座標，容許 ±8 字，算 P/R/F1；記錄段數、最長段。

用法：python eval_materials.py [--repunct] [M1 M2 ...]   → 印出表格，並寫 tests/_out/eval.json
  --repunct：不重跑辨識，把 turbo／Breeze 輸出的 segment 還原成加標點前的文字（text_plain），
             用目前的 punctuate.py 重新分段標點後再評估（1.1.0 標點演算法改版後重量 P1～P3 用）。
             需要測試 home 有標點模型。
"""
import difflib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import _testenv  # noqa: F401
from opencc import OpenCC

HERE = Path(__file__).resolve().parent
RUNS = HERE / "_out" / "runs"
E_MARKS = set("。？！?!")
M_MARKS = set("，、；：,;:")


def is_punct(c):
    return unicodedata.category(c).startswith("P") or c in "～~"


def breaks_of(paragraphs: list) -> tuple:
    """回傳 (內容字元字串, {位置: 'E'|'M'}, [段落起點])。"""
    chars, brk, starts = [], {}, []
    for text in paragraphs:
        starts.append(len(chars))
        for i, c in enumerate(text):
            if c.isspace():
                continue
            if is_punct(c):
                if chars and (c in E_MARKS or (c == "." and not (i + 1 < len(text) and text[i + 1].isdigit()))):
                    brk[len(chars) - 1] = "E"
                elif chars and c in M_MARKS:
                    brk.setdefault(len(chars) - 1, "M")
                continue
            chars.append(c)
        if chars:
            brk[len(chars) - 1] = "E"
    return "".join(chars), brk, starts


def mapper(ref: str, hyp: str):
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    blocks = sm.get_matching_blocks()

    def m(j):
        last = 0
        for a, b, size in blocks:
            if b <= j < b + size:
                return a + (j - b)
            if b + size <= j and size:
                last = a + size - 1
        return last
    return m, sm.ratio()


def prf(ref_pos: set, hyp_pos: list, tol: int) -> dict:
    used, hit = set(), 0
    for h in hyp_pos:
        cand = [r for r in range(h - tol, h + tol + 1) if r in ref_pos and r not in used]
        if cand:
            used.add(min(cand, key=lambda r: abs(r - h)))
            hit += 1
    p = hit / len(hyp_pos) if hyp_pos else 0.0
    r = hit / len(ref_pos) if ref_pos else 0.0
    return {"p": round(p, 3), "r": round(r, 3), "f1": round(2 * p * r / (p + r), 3) if p + r else 0.0}


def hyp_paragraphs(doc: dict) -> list:
    segs = doc["segments"]
    out = []
    for p in doc.get("paragraphs") or []:
        a, b = p["segments"]
        texts = [segs[i]["text"] for i in range(a, b + 1)]
        joined = ""
        for t in texts:
            joined += ("" if not joined or re.match(r"[一-鿿，。！？、]", t[:1]) else " ") + t
        out.append(joined)
    return out


def content_len(t):
    return sum(1 for c in t if not c.isspace() and not is_punct(c))


def eval_punct(ref_doc: dict, doc: dict) -> dict:
    ref_text, ref_brk, ref_starts = breaks_of([p["text"] for p in ref_doc["paragraphs"]])
    paras = hyp_paragraphs(doc)
    hyp_text, hyp_brk, hyp_starts = breaks_of(paras)
    m, ratio = mapper(ref_text, hyp_text)
    any_ = prf(set(ref_brk), [m(j) for j in hyp_brk], 1)
    end_ = prf({i for i, k in ref_brk.items() if k == "E"}, [m(j) for j, k in hyp_brk.items() if k == "E"], 1)
    par = prf(set(ref_starts), [m(j) for j in hyp_starts], 8)
    segs = doc["segments"]
    seg_len = [content_len(s["text"]) for s in segs]
    max_rule = 0
    for p in doc["paragraphs"]:
        a, b = p["segments"]
        max_rule = max(max_rule, sum(seg_len[a:b]))   # 加入最後一個 segment 之前的字數，規則保證 < max_chars
    pm = doc["meta"].get("punctuation", {})
    return {"content_similarity": round(ratio, 3), "punct_any": any_, "punct_end": end_, "paragraph": par,
            "paragraphs": len(paras), "ref_paragraphs": len(ref_starts),
            "max_paragraph": max(content_len(t) for t in paras), "max_segment": max(seg_len),
            "max_before_last_segment": max_rule, "by_source": pm.get("by_source"),
            "punct_elapsed_sec": pm.get("elapsed_sec"), "duration": doc["meta"]["duration"],
            "punct_sec_per_hour": round(pm.get("elapsed_sec", 0) / (doc["meta"]["duration"] / 3600), 2)}


def md_body(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").split("\n")
    i = 2
    while i < len(lines) and lines[i].startswith("- "):
        i += 1
    return "\n".join(lines[i:])


def eval_regression(name: str) -> dict:
    a, b = RUNS / f"{name}-turbo-v100", RUNS / f"{name}-turbo-r110"
    if not (a / "transcript.md").exists() or not (b / "transcript.md").exists():
        return {"status": "missing"}
    md_same = md_body(a / "transcript.md") == md_body(b / "transcript.md")
    srt_same = (a / "transcript.srt").read_bytes() == (b / "transcript.srt").read_bytes()
    out = {"md_body_identical": md_same, "srt_identical": srt_same}
    if not md_same:
        d = list(difflib.unified_diff(md_body(a / "transcript.md").splitlines(),
                                      md_body(b / "transcript.md").splitlines(), lineterm="", n=0))
        out["md_diff_head"] = d[:12]
    return out


def eval_keep(name: str, ref_doc: dict) -> dict:
    """K7：回復表開（turbo）與關（turbo-r110）的逐字比較；兩者辨識結果相同，差異只能來自回復表。"""
    on_p, off_p = RUNS / f"{name}-turbo" / "transcript.json", RUNS / f"{name}-turbo-r110" / "transcript.json"
    if not on_p.exists() or not off_p.exists():
        return {"status": "missing"}
    on = json.loads(on_p.read_text(encoding="utf-8"))["segments"]
    off = json.loads(off_p.read_text(encoding="utf-8"))["segments"]
    if [(s["start"], s["end"]) for s in on] != [(s["start"], s["end"]) for s in off]:
        return {"status": "segments_differ", "on": len(on), "off": len(off)}
    sys.path.insert(0, str(_testenv.SCRIPTS))
    from opencc_keep import load_table
    table = load_table()
    cc = OpenCC("s2twp")
    keep_pairs = {k: cc.convert(k) for k in table.keeps}
    # 「其他字元與關閉時相同」：兩邊都把「來源寫法經 s2twp 的結果」（許可權、賬號、釋出……）換回保留寫法，
    # 之後完全相同，就代表差異只在回復表的詞上（講者原本就說的「視窗」兩邊都會被換，不影響比較）
    bad_map = {}
    for s, k in table.src_map.items():
        b = cc.convert(s)
        if b != k:
            bad_map.setdefault(b, k)
    rx = re.compile("|".join(re.escape(b) for b in sorted(bad_map, key=len, reverse=True)))

    def norm(t):
        return rx.sub(lambda m: bad_map[m.group(0)], t)
    other, changed = [], 0
    for a, b in zip(off, on):
        x, y = a["text"], b.get("text_plain", b["text"])
        if x != y:
            changed += 1
        if norm(x) != norm(y):
            other.append((x, y))
    keep_diffs = json.loads((RUNS / f"{name}-turbo" / "transcript.json").read_text(encoding="utf-8"))[
        "meta"].get("opencc_keep_applied", {})
    # 以基準稿為準數「OpenCC 類錯誤」：基準稿寫保留寫法、轉寫結果在對應位置寫成 s2twp 改過的詞
    ref_text = "".join(p["text"] for p in ref_doc["paragraphs"])

    def opencc_errors(segs, key):
        hyp = "".join(s.get(key, s["text"]) if key else s["text"] for s in segs)
        sm = difflib.SequenceMatcher(None, ref_text, hyp, autojunk=False)
        errs = {}
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "replace":
                continue
            r, h = ref_text[max(0, i1 - 3):i2 + 3], hyp[max(0, j1 - 3):j2 + 3]
            for k, bad in keep_pairs.items():
                if k in r and bad in h and k not in h:
                    errs[k] = errs.get(k, 0) + 1
        return errs
    e_off = opencc_errors(off, None)
    e_on = opencc_errors(on, "text_plain")
    return {"segments": len(on), "segments_changed": changed, "keep_hits": keep_diffs,
            "keep_hits_total": sum(keep_diffs.values()), "other_differences": other[:5], "other_count": len(other),
            "opencc_errors_off": e_off, "opencc_errors_off_total": sum(e_off.values()),
            "opencc_errors_on": e_on, "opencc_errors_on_total": sum(e_on.values())}


def perf_one_hour(name: str) -> dict | None:
    """P4 補充：把 turbo 的 segments 重複接到一小時長，以 Breeze 模式（每段都走 CT-Transformer，最壞情況）計時。"""
    import common
    import punctuate as pu
    p = RUNS / f"{name}-turbo" / "transcript.json"
    if not p.exists() or not common.punct_ready():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    base = [dict(s, text=s.get("text_plain", s["text"])) for s in doc["segments"]]
    dur = doc["meta"]["duration"]
    segs, k = [], 0
    while (k + 1) * dur <= 3600 + dur:
        segs += [dict(s, start=s["start"] + k * dur, end=s["end"] + k * dur) for s in base]
        k += 1
    segs = [s for s in segs if s["start"] < 3600]
    t0 = time.time()
    punct = pu.Punctuator(common.punct_model(), 4)
    paras = pu.build_paragraphs(segs, [], 2.0, 200, True)
    st = pu.punctuate_paragraphs(paras, segs, "breeze", punct, 20)
    return {"segments": len(segs), "chars": sum(content_len(s["text"]) for s in segs), "paragraphs": len(paras),
            "elapsed_sec": round(time.time() - t0, 2), "by_source": st["by_source"]}


def repunct(doc: dict, alias: str) -> dict:
    """用目前的 punctuate.py 對同一份辨識結果重新分段標點（辨識、OpenCC、對照表的結果不變）。"""
    import common
    import punctuate as pu
    pm = doc["meta"].get("punctuation") or {}
    segs = []
    for s in doc["segments"]:
        s = dict(s, text=s.get("text_plain", s["text"]))
        s.pop("text_plain", None)
        s.pop("para", None)
        segs.append(s)
    gap, mx, dens = pm.get("paragraph_gap", 2.0), pm.get("paragraph_max_chars", 200), pm.get("whisper_density", 20)
    t0 = time.time()
    punct = pu.Punctuator(common.punct_model(), 4)
    paras = pu.build_paragraphs(segs, doc.get("keyframes", []), gap, mx, True)
    st = pu.punctuate_paragraphs(paras, segs, alias, punct, dens)
    meta = dict(doc["meta"], punctuation=dict(pm, by_source=st["by_source"], by_segment=st["by_segment"],
                                               elapsed_sec=round(time.time() - t0, 3), paragraphs=len(paras)))
    return {"meta": meta, "paragraphs": paras, "segments": segs, "keyframes": doc.get("keyframes", [])}


def main():
    args = sys.argv[1:]
    again = "--repunct" in args
    names = [a for a in args if not a.startswith("--")] or ["M1", "M2"]
    result = {}
    for n in names:
        ref = json.loads((HERE / "_out" / f"{n}.ref.json").read_text(encoding="utf-8"))
        r = {"duration_min": round(ref["duration"] / 60, 1)}
        for model in ("turbo", "breeze", "turbo-r110", "turbo-v100"):
            p = RUNS / f"{n}-{model}" / "transcript.json"
            if p.exists():
                doc = json.loads(p.read_text(encoding="utf-8"))
                if again and model in ("turbo", "breeze"):
                    doc = repunct(doc, model)
                if doc.get("paragraphs") is None:     # 1.0.0：沒有段落資訊，以講者連續合併重建
                    import punctuate as pu
                    doc["paragraphs"] = pu.build_paragraphs(doc["segments"], doc.get("keyframes", []), 0, 0, False)
                    doc["meta"].setdefault("punctuation", {})
                r[model] = eval_punct(ref, doc)
        r["K7"] = eval_keep(n, ref)
        r["R"] = eval_regression(n)
        r["P4_one_hour"] = perf_one_hour(n)
        result[n] = r
    (HERE / "_out" / "eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for n, r in result.items():
        print(f"\n## {n}（{r['duration_min']} 分鐘）")
        print("| 設定 | 標點 F1 任何／句末 | 段落 F1 | 段數（基準） | 最長段 | 最長 segment | 內容相似度 | 標點來源 | 分段標點耗時 |")
        print("|---|---|---|---|---|---|---|---|---|")
        for model in ("turbo", "breeze", "turbo-r110", "turbo-v100"):
            if model not in r:
                continue
            x = r[model]
            print(f"| {model} | {x['punct_any']['f1']}／{x['punct_end']['f1']} | {x['paragraph']['f1']} | "
                  f"{x['paragraphs']}（{x['ref_paragraphs']}） | {x['max_paragraph']} | {x['max_segment']} | "
                  f"{x['content_similarity']} | {x['by_source']} | {x['punct_elapsed_sec']}s"
                  f"（{x['punct_sec_per_hour']} s/h） |")
        print(f"K7：{json.dumps(r['K7'], ensure_ascii=False)}")
        print(f"R：{json.dumps(r['R'], ensure_ascii=False)}")
        print(f"P4（一小時、全部走 CT）：{json.dumps(r['P4_one_hour'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
