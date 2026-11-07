"""本機分段標點：規則分段（講者切換／畫面／停頓／段長）＋標點（Whisper 自帶標點或 CT-Transformer）。

- build_paragraphs()：決定段落邊界（一定落在 segment 邊界）。
- punctuate_paragraphs()：每段決定標點來源，把結果寫回每個 segment 的 text（加標點前的文字存在 text_plain）。
  Breeze 一律整段交給 CT-Transformer；其他模型逐個 segment 判斷：標點夠密（每 whisper_density 個內容字元至少 1 個）
  就沿用 Whisper 標點，不夠密的 segment 單獨交給 CT-Transformer（1.1.0 實測：以 segment 判斷比以段落判斷的 F1 高）。
  CT-Transformer 用簡體語料訓練，所以逐字轉簡體後再標點，標點插回原本的繁體文字。
"""
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CJK_PUNCT = "，。、；：？！"
HALF_TO_FULL = {",": "，", "?": "？", "!": "！", ";": "；", ":": "："}
FULL_TO_HALF = {v: k for k, v in HALF_TO_FULL.items()}
SENT_END = "。？！"
# 1.0.0 write_outputs() 串接 segment 的規則：後者開頭是中日韓字元或這些標點時不加空白
JOIN_NO_SPACE = re.compile(r"[一-鿿，。！？、]")


def is_cjk(c: str) -> bool:
    if not c:
        return False
    o = ord(c)
    return (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF or 0xF900 <= o <= 0xFAFF
            or 0x20000 <= o <= 0x2FFFF)


def is_punct(c: str) -> bool:
    return bool(c) and unicodedata.category(c).startswith("P")


def content_len(text: str) -> int:
    """內容字元數：去掉空白與標點。"""
    return sum(1 for c in text if not c.isspace() and not is_punct(c))


def join_texts(texts: list) -> tuple:
    """依 1.0.0 的規則串接，回傳 (段落文字, [(起, 迄)])。"""
    buf, spans, pos = [], [], 0
    for t in texts:
        sep = "" if not buf or JOIN_NO_SPACE.match(t[:1]) else " "
        pos += len(sep)
        spans.append((pos, pos + len(t)))
        buf.append(sep + t)
        pos += len(t)
    return "".join(buf), spans


# ---------------------------------------------------------------- ② 分段
def build_paragraphs(segs: list, frames: list, gap: float, max_chars: int, enabled: bool = True) -> list:
    """回傳 [{"start", "end", "speaker", "segments": [起, 迄], "punct": None}]（segments 含頭含尾）。

    換段條件（在這個 segment 之前）：講者不同；中間有畫面事件；enabled 時另加
    seg.start - prev.end >= gap，或目前段落內容字元數 >= max_chars。
    畫面事件的位置與 1.0.0 相同：prev.start <= 畫面時間 < seg.start 時視為在兩者之間。
    """
    times = sorted(float(f["time"]) for f in frames)
    paras = []
    cur = None
    chars = 0
    for i, s in enumerate(segs):
        new = cur is None
        if not new:
            prev = segs[i - 1]
            if s["speaker"] != prev["speaker"]:
                new = True
            elif any(prev["start"] <= t < s["start"] for t in times):
                new = True
            elif enabled and (s["start"] - prev["end"] >= gap or chars >= max_chars):
                new = True
        if new:
            cur = {"start": s["start"], "end": s["end"], "speaker": s["speaker"], "segments": [i, i], "punct": None}
            paras.append(cur)
            chars = 0
        cur["segments"][1] = i
        cur["end"] = s["end"]
        chars += content_len(s["text"])
    return paras


# ---------------------------------------------------------------- ③ 標點
class Punctuator:
    """CT-Transformer（sherpa-onnx OfflinePunctuation，CPU）。輸入簡體文字，回傳加了標點的文字。"""

    def __init__(self, model_path, threads: int = 2):
        import sherpa_onnx
        t0 = time.time()
        cfg = sherpa_onnx.OfflinePunctuationConfig(
            model=sherpa_onnx.OfflinePunctuationModelConfig(
                ct_transformer=str(model_path), num_threads=threads, provider="cpu"))
        self.model = sherpa_onnx.OfflinePunctuation(cfg)
        self.load_sec = time.time() - t0

    def add(self, text: str) -> str:
        return self.model.add_punctuation(text)


_t2s = None
_t2s_cache = {}


def to_simplified_charwise(text: str) -> str:
    """逐字轉簡體；結果長度不是 1 就保留原字，所以字數與位置不變。"""
    global _t2s
    if _t2s is None:
        from opencc import OpenCC
        _t2s = OpenCC("t2s")
    out = []
    for c in text:
        r = _t2s_cache.get(c)
        if r is None:
            r = _t2s.convert(c)
            r = r if len(r) == 1 else c
            _t2s_cache[c] = r
        out.append(r)
    return "".join(out)


def _neighbors(text: str, i: int) -> tuple:
    j = i - 1
    while j >= 0 and text[j] == " ":
        j -= 1
    k = i + 1
    while k < len(text) and text[k] == " ":
        k += 1
    return (text[j] if j >= 0 else ""), (text[k] if k < len(text) else "")


def _convertible(text: str, i: int) -> bool:
    """這個半形標點是否屬於中文句子（§5.4.1 會轉成全形）。"""
    c = text[i]
    if c in HALF_TO_FULL:
        left, right = _neighbors(text, i)
        return is_cjk(left) or is_cjk(right)
    if c == ".":
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        return is_cjk(prev) and (nxt == "" or nxt.isspace() or is_cjk(nxt))
    return False


def _drop_space_around(chars: list, marks: set) -> list:
    """刪掉緊鄰全形標點的空白（「Sentinel， 切換」→「Sentinel，切換」）。marks 是全形標點的索引。"""
    out = []
    for i, c in enumerate(chars):
        if c == " " and ((i > 0 and (i - 1) in marks) or (i + 1 < len(chars) and (i + 1) in marks)):
            continue
        out.append(c)
    return out


def normalize_whisper(text: str) -> str:
    """§5.4.1 步驟 1：中文句子裡的半形標點換成全形，並刪掉緊鄰的空白。"""
    chars = list(text)
    marks = set()
    for i, c in enumerate(text):
        if _convertible(text, i):
            chars[i] = HALF_TO_FULL.get(c, "。")
            marks.add(i)
        elif c in CJK_PUNCT:
            marks.add(i)
    return "".join(_drop_space_around(chars, marks)).strip()


def ends_with_punct(text: str) -> bool:
    t = text.rstrip()
    return bool(t) and is_punct(t[-1])


def boundary_mark(text: str) -> str:
    t = text.rstrip()
    return "？" if t.endswith("嗎") else "。"


def count_marks(text: str) -> int:
    return sum(1 for i, c in enumerate(text) if c in CJK_PUNCT or _convertible(text, i))


def _whisper_path(texts: list) -> list:
    out = []
    for t in texts:
        t = normalize_whisper(t)
        if t and not ends_with_punct(t):
            t += boundary_mark(t)
        out.append(t)
    return out


def _close_paragraph(texts: list) -> list:
    """段尾沒有 。？！ 時補 。（段尾若是 ，、；： 就換成 。）。"""
    for k in range(len(texts) - 1, -1, -1):
        t = texts[k].rstrip()
        if not t:
            continue
        if t[-1] in SENT_END or t[-1] in "?!":
            pass
        elif t[-1] in "，、；：,;:":
            t = t[:-1] + "。"
        elif t[-1] not in "」』）)》〉…":
            t += "。"
        texts[k] = t
        break
    return texts


def _ct_path(texts: list, punctuator) -> list | None:
    """§5.4.2。成功回傳加了標點的各 segment 文字；對不上回傳 None（ct_failed）。"""
    para, spans = join_texts(texts)
    # 步驟 2：去掉既有標點，記下每個保留字元屬於哪個 segment
    kept, owner = [], []
    seg_i = 0
    for i, c in enumerate(para):
        while seg_i + 1 < len(spans) and i >= spans[seg_i][1]:
            seg_i += 1
        if c in CJK_PUNCT or _convertible(para, i):
            continue
        kept.append(c)
        owner.append(seg_i)
    content_idx = [i for i, c in enumerate(kept) if not c.isspace()]
    if not content_idx:
        return None
    simp = to_simplified_charwise("".join(kept))
    simp_content = [simp[i] for i in content_idx]
    inserts = {}            # 內容字元序號 -> 插在它之後的標點
    pos = 0                 # 下一個要比對的內容字元序號
    for _ in range(8):      # 模型偶爾會吞掉句尾：剩下的部分再送一次
        start = pos
        out = punctuator.add("".join(simp_content[pos:]))
        for c in out:
            if c.isspace():
                continue
            if pos < len(simp_content) and c.lower() == simp_content[pos].lower():
                pos += 1
                continue
            if c in CJK_PUNCT or c in HALF_TO_FULL or c == ".":
                if pos > 0:
                    inserts[pos - 1] = c
                continue
            if pos >= len(simp_content):
                break
            return None
        if pos >= len(simp_content) or pos == start:
            break
    # 步驟 6：插回原本的繁體文字
    per_seg = [[] for _ in texts]
    marks = [set() for _ in texts]
    ci = -1
    for k, c in enumerate(kept):
        s = owner[k]
        if not c.isspace():
            ci += 1
        per_seg[s].append(c)
        if not c.isspace() and ci in inserts:
            m = inserts[ci]
            nxt_k = content_idx[ci + 1] if ci + 1 < len(content_idx) else None
            nxt = kept[nxt_k] if nxt_k is not None else ""
            if m in HALF_TO_FULL or m == ".":
                m = HALF_TO_FULL.get(m, "。") if (is_cjk(c) or is_cjk(nxt)) else m
            per_seg[s].append(m)
            if m in CJK_PUNCT:
                marks[s].add(len(per_seg[s]) - 1)
    out_texts = []
    for s, chars in enumerate(per_seg):
        t = "".join(_drop_space_around(chars, marks[s])).strip()
        out_texts.append(t)
    return out_texts


def _label(sources: list) -> str:
    """段落的標點來源：segment 來源全部相同就用它；有 ct_failed 就是 ct_failed；whisper 與 ct 混合是 mixed。"""
    kinds = set(sources)
    if "ct_failed" in kinds:
        return "ct_failed"
    if len(kinds) == 1:
        return sources[0]
    return "mixed"


def punctuate_paragraphs(paras: list, segs: list, whisper_alias: str, punctuator, density: int) -> dict:
    """每段決定標點來源並寫回 segs[i]["text"]（有變動時另存 text_plain）。回傳統計。

    p["punct"]：whisper | ct | mixed（同段有的 segment 沿用 Whisper、有的交給 CT）| ct_failed | none。
    by_source 以段落計，by_segment 以 segment 計（whisper／ct／ct_failed／none）。
    """
    t0 = time.time()
    by = {"whisper": 0, "ct": 0, "mixed": 0, "none": 0, "ct_failed": 0}
    by_seg = {"whisper": 0, "ct": 0, "none": 0, "ct_failed": 0}
    breeze = whisper_alias == "breeze"
    for p in paras:
        a, b = p["segments"]
        idx = list(range(a, b + 1))
        texts = [segs[i]["text"] for i in idx]
        if breeze:                                   # Breeze 幾乎不輸出標點：整段交給 CT（有上下文）
            if punctuator is None:
                new, srcs = [t.strip() for t in texts], ["none"] * len(texts)
            else:
                new = _ct_path(texts, punctuator)
                srcs = ["ct"] * len(texts)
                if new is None:
                    new, srcs = _whisper_path(texts), ["ct_failed"] * len(texts)
        else:                                        # 其他模型：逐個 segment 判斷密度
            new, srcs = _whisper_path(texts), ["whisper"] * len(texts)
            if punctuator is not None:
                for k, t in enumerate(texts):
                    if count_marks(t) * density >= content_len(t):
                        continue
                    ct = _ct_path([t], punctuator)
                    if ct is None:
                        srcs[k] = "ct_failed"
                    else:
                        new[k], srcs[k] = ct[0], "ct"
        new = _close_paragraph(new)
        src = _label(srcs)
        p["punct"] = src
        by[src] += 1
        for x in srcs:
            by_seg[x] += 1
        for i, t in zip(idx, new):
            if t != segs[i]["text"]:
                segs[i]["text_plain"] = segs[i]["text"]
                segs[i]["text"] = t
    return {"paragraphs": len(paras), "by_source": by, "by_segment": by_seg,
            "elapsed_sec": round(time.time() - t0, 3)}
