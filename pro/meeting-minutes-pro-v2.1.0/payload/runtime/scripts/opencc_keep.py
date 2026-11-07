"""OpenCC 詞彙回復表：s2twp 轉換前先保護台灣也在用的詞，轉完再放回。

OpenCC s2twp 的 TWPhrases（大陸用語→台灣用語）鍵是繁體，所以繁體輸入也會被改：
「權限」→「許可權」、「分區」→「分割槽」、「發布」→「釋出」……。本模組在 cc.convert() 之前把這些詞換成
私用區佔位字元（U+E000 起），轉換後再換回「保留寫法」。只動 Whisper 原文裡真的寫著這些詞的位置，
講者本來就說的「視窗」「釋出」不受影響。

長詞例外：TWPhrases 裡包含回復表詞的較長詞（「數據庫」「程序員」「用戶名」……）照 OpenCC 原本的結果轉換。

表格（UTF-8，Tab 分隔，# 開頭為註解）：保留寫法<TAB>其他來源寫法（逗號分隔，可留空）<TAB>備註
  內建表：scripts/opencc_keep_default.tsv（隨版本更新）
  使用者表：$MMH/opencc_keep.tsv（同名項目覆蓋內建表；以 - 開頭的行，例「-數據」，停用內建表的同名項目）

CLI：
  python opencc_keep.py test "審核通過後再發布"   # 純 s2twp、套用回復表的結果、命中的詞
  python opencc_keep.py list                       # 合併後的有效詞條與來源（內建／使用者）
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import opencc_keep_paths, utf8_console  # noqa: E402

PUA_BASE = 0xE000
PUA_MAX = 6400          # U+E000～U+F8FF
USER_TEMPLATE = (
    "# meeting-minutes-pro OpenCC 詞彙回復表（使用者表）\n"
    "# 格式：保留寫法<TAB>其他來源寫法（逗號分隔，可留空）<TAB>備註\n"
    "# 保留寫法＝最後要出現在逐字稿上的寫法（台灣正體）。它本身與它的簡體寫法一定會被保護，第二欄只列額外的寫法。\n"
    "# 這裡的同名項目會覆蓋內建表；以 - 開頭的行（例：-數據）會停用內建表的同名項目。\n"
    "# 試詞：python opencc_keep.py test \"要測試的句子\"\n"
)

_warned = set()


def _warn(msg: str):
    if msg not in _warned:
        _warned.add(msg)
        print(f"  [!] {msg}", file=sys.stderr, flush=True)


def parse_table(path: Path) -> tuple:
    """回傳 (rows, disabled)；rows = [(保留寫法, [其他來源寫法], 備註)]，disabled = {停用的保留寫法}。"""
    rows, disabled = [], set()
    if not path or not Path(path).exists():
        return rows, disabled
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        keep = parts[0].strip()
        if keep.startswith("-"):
            if keep[1:].strip():
                disabled.add(keep[1:].strip())
            continue
        if not keep:
            continue
        others = [w.strip() for w in (parts[1] if len(parts) > 1 else "").replace("，", ",").split(",") if w.strip()]
        rows.append((keep, others, parts[2].strip() if len(parts) > 2 else ""))
    return rows, disabled


def merge(builtin: list, user: list, disabled: set) -> list:
    """回傳 [(保留寫法, [其他來源寫法], 備註, 來源)]，使用者表在前（衝突時優先）。"""
    user_map = {k: (k, o, n, "使用者") for k, o, n in user}
    out = list(user_map.values())
    for k, o, n in builtin:
        if k in user_map or k in disabled:
            continue
        out.append((k, o, n, "內建"))
    return out


def opencc_dictionary_dir() -> Path | None:
    try:
        import opencc
    except Exception:  # noqa: BLE001
        return None
    d = Path(opencc.__file__).resolve().parent / "dictionary"
    return d if d.is_dir() else None


def tw_phrase_keys() -> list | None:
    d = opencc_dictionary_dir()
    f = d / "TWPhrases.txt" if d else None
    if not f or not f.exists():
        return None
    keys = []
    for line in f.read_text(encoding="utf-8").splitlines():
        k = line.split("\t", 1)[0].strip()
        if k:
            keys.append(k)
    return keys


class KeepTable:
    """回復表。rows 依優先序排列（同一個來源寫法對到兩個保留寫法時，先出現的優先）。"""

    def __init__(self, rows: list, tw_phrase_keys_: list | None, t2s=None):
        if t2s is None:
            from opencc import OpenCC
            t2s = OpenCC("t2s")
        self.rows = [(r[0], list(r[1]), r[2] if len(r) > 2 else "") for r in rows]
        self.keeps = [k for k, _, _ in self.rows]
        src_map = {}
        for keep, others, _ in self.rows:
            for s in dict.fromkeys([keep, t2s.convert(keep), *others]):
                if not s:
                    continue
                if s in src_map and src_map[s] != keep:
                    _warn(f"OpenCC 詞彙回復表：「{s}」同時對到「{src_map[s]}」與「{keep}」，採用「{src_map[s]}」")
                    continue
                src_map[s] = keep
        self.src_map = src_map
        if tw_phrase_keys_ is None:
            _warn("找不到 OpenCC 詞典，長詞例外停用")
            exc_all = set()
        else:
            exc_all = set(tw_phrase_keys_) | {t2s.convert(p) for p in tw_phrase_keys_}
        # 來源寫法 s 的例外 = 包含 s 且比 s 長的 TWPhrases 詞（繁體與簡體寫法），以及 s 在其中的所有位置
        self.exceptions = {}
        for s in src_map:
            ex = []
            for p in exc_all:
                if len(p) > len(s) and s in p:
                    off = p.find(s)
                    while off >= 0:
                        ex.append((p, off))
                        off = p.find(s, off + 1)
            self.exceptions[s] = ex
        self.by_first = {}
        for s in sorted(src_map, key=len, reverse=True):
            self.by_first.setdefault(s[0], []).append(s)

    def protect(self, text: str) -> tuple:
        """回傳 (含佔位字元的文字, [佔位字元對應的保留寫法])；沒有命中時 placeholders 為空。"""
        if not self.src_map or not text:
            return text, []
        if any(PUA_BASE <= ord(c) < PUA_BASE + PUA_MAX for c in text):
            _warn("文字裡已有私用區字元，這段不套用 OpenCC 詞彙回復表")
            return text, []
        out, slots, idx = [], [], {}
        i, n = 0, len(text)
        while i < n:
            hit = None
            for s in self.by_first.get(text[i], ()):
                if not text.startswith(s, i):
                    continue
                if any(i - off >= 0 and text.startswith(p, i - off) for p, off in self.exceptions[s]):
                    continue
                hit = s
                break
            if hit is None:
                out.append(text[i])
                i += 1
                continue
            keep = self.src_map[hit]
            if keep not in idx:
                idx[keep] = len(slots)
                slots.append(keep)
            out.append(chr(PUA_BASE + idx[keep]))
            i += len(hit)
        if len(slots) > PUA_MAX:
            _warn("佔位字元超過私用區上限，這段不套用 OpenCC 詞彙回復表")
            return text, []
        return "".join(out), slots

    def convert(self, text: str, cc) -> tuple:
        """保護 → cc.convert() → 放回。回傳 (轉換後文字, {保留寫法: 次數})。"""
        guarded, slots = self.protect(text)
        converted = cc.convert(guarded)
        if not slots:
            return converted, {}
        hits = {}
        out = []
        for c in converted:
            o = ord(c)
            if PUA_BASE <= o < PUA_BASE + len(slots):
                k = slots[o - PUA_BASE]
                hits[k] = hits.get(k, 0) + 1
                out.append(k)
            else:
                out.append(c)
        return "".join(out), hits


def load_merged(builtin: Path | None = None, user: Path | None = None) -> list:
    b_path, u_path = opencc_keep_paths()
    b_rows, _ = parse_table(builtin or b_path)
    u_rows, disabled = parse_table(user or u_path)
    return merge(b_rows, u_rows, disabled)


def load_table(builtin: Path | None = None, user: Path | None = None, t2s=None) -> KeepTable:
    merged = load_merged(builtin, user)
    return KeepTable([(k, o, n) for k, o, n, _ in merged], tw_phrase_keys(), t2s)


def main():
    utf8_console()
    ap = argparse.ArgumentParser(description="OpenCC 詞彙回復表")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("test", help="試詞：比較純 s2twp 與套用回復表的結果")
    t.add_argument("text")
    sub.add_parser("list", help="列出合併後的有效詞條")
    args = ap.parse_args()
    if args.cmd == "list":
        b_path, u_path = opencc_keep_paths()
        merged = load_merged()
        print(f"# 內建表：{b_path}")
        print(f"# 使用者表：{u_path}{'' if u_path.exists() else '（不存在）'}")
        print(f"# 有效詞條 {len(merged)} 筆")
        for k, o, n, src in merged:
            print(f"{k}\t{','.join(o)}\t{src}\t{n}")
        return
    from opencc import OpenCC
    cc = OpenCC("s2twp")
    table = load_table()
    kept, hits = table.convert(args.text, cc)
    print(f"純 s2twp  ：{cc.convert(args.text)}")
    print(f"套用回復表：{kept}")
    print("命中：" + ("、".join(f"{k} ×{v}" for k, v in hits.items()) if hits else "（無）"))


if __name__ == "__main__":
    main()
