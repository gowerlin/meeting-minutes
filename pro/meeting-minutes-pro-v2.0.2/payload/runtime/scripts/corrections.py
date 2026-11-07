"""固定錯誤對照表（corrections.tsv）：轉寫後自動把固定誤辨識換成正確寫法。

格式：一行一筆，Tab 分隔：錯誤寫法<TAB>正確寫法<TAB>備註（可省略）；# 開頭為註解。

CLI（給 Claude 或使用者維護用）：
  python corrections.py list
  python corrections.py add "酷伯內蒂斯" "Kubernetes" --note "2026-10-05 示範專案週會"
  python corrections.py remove "酷伯內蒂斯"
  python corrections.py test "我們的酷伯內蒂斯叢集"  # 試套用，不寫檔
  python corrections.py auto-list                    # 列出自動校正寫入的項目（備註 auto:<日期> <來源>）
  python corrections.py auto-undo [錯誤寫法 ...] [--date 2026-11-06] [--all]   # 撤銷自動寫入（先備份）

OpenCC 詞彙回復表（opencc_keep.py）處理「簡繁轉換造成的錯」，這裡處理「辨識造成的錯」：
錯誤寫法是回復表的保留寫法時，add 會提示並要求 --force。
"""
import argparse
import json
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import correction_history_path, corrections_path, data_home, utf8_console  # noqa: E402

HEADER = ("# meeting-minutes-pro 固定錯誤對照表\n"
          "# 格式：錯誤寫法<TAB>正確寫法<TAB>備註；轉寫後自動替換（長的詞優先）\n"
          "# 只放「每次都會錯成同一個樣子」的詞；一般同音錯字交給 Claude 依上下文校正\n")
MIN_LEN = 2   # 單一字元的全域替換風險太高，預設不允許
AUTO_PREFIX = "auto:"   # 自動校正寫入的行，備註以此開頭（1.1.0）


def load(path: Path | None = None) -> list:
    path = path or corrections_path()
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0] and parts[0] != parts[1]:
            rows.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return rows


class Corrector:
    """單次掃描替換（regex alternation，長詞優先），避免 A→B 之後 B 又被替換的連鎖效應。"""

    def __init__(self, rows: list):
        self.map = {w: r for w, r, _ in rows}
        keys = sorted(self.map, key=len, reverse=True)
        self.rx = re.compile("|".join(re.escape(k) for k in keys)) if keys else None

    def apply(self, text: str):
        if not self.rx:
            return text, []
        hits = {}

        def sub(m):
            hits[m.group(0)] = hits.get(m.group(0), 0) + 1
            return self.map[m.group(0)]
        new = self.rx.sub(sub, text)
        return new, [[w, self.map[w], n] for w, n in hits.items()]

    def right_terms(self) -> list:
        return sorted(set(self.map.values()))


def keep_words() -> set:
    """OpenCC 詞彙回復表合併後的保留寫法；讀不到就回傳空集合（不阻擋 add）。"""
    try:
        from opencc_keep import load_merged
        return {k for k, _, _, _ in load_merged()}
    except Exception:  # noqa: BLE001
        return set()


def save(rows: list, path: Path | None = None):
    path = path or corrections_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(f"{w}\t{r}\t{n}\n" for w, r, n in rows)
    path.write_text(HEADER + body, encoding="utf-8")


def backup(stamp: str | None = None, path: Path | None = None) -> str | None:
    """寫入或撤銷前備份到 $MMH/backups/corrections.<時間>.tsv；檔案不存在回傳 None。"""
    path = path or corrections_path()
    if not path.exists():
        return None
    stamp = stamp or datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    d = data_home() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"corrections.{stamp}.tsv"
    n = 1
    while dst.exists():
        dst = d / f"corrections.{stamp}-{n}.tsv"
        n += 1
    shutil.copy2(path, dst)
    return str(dst)


def append_rows(rows: list, path: Path | None = None):
    """在檔尾追加（保留使用者原本的註解與排版）；檔案不存在時先寫表頭。"""
    path = path or corrections_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else HEADER
    if old and not old.endswith("\n"):
        old += "\n"
    path.write_text(old + "".join(f"{w}\t{r}\t{n}\n" for w, r, n in rows), encoding="utf-8")


def auto_rows(path: Path | None = None) -> list:
    return [x for x in load(path) if x[2].startswith(AUTO_PREFIX)]


def remove_auto(match, path: Path | None = None) -> list:
    """刪掉 match(錯誤寫法, 正確寫法, 備註) 為真的自動寫入行，其他行（含註解）原樣保留。回傳刪掉的項目。"""
    path = path or corrections_path()
    if not path.exists():
        return []
    keep, gone = [], []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        parts = line.rstrip("\r\n").split("\t")
        if (len(parts) >= 3 and not line.lstrip().startswith("#") and parts[2].startswith(AUTO_PREFIX)
                and match(parts[0], parts[1], parts[2])):
            gone.append((parts[0], parts[1], parts[2]))
            continue
        keep.append(line)
    if gone:
        path.write_text("".join(keep), encoding="utf-8")
        _mark_undone(gone)
    return gone


def _mark_undone(rows: list):
    """撤銷過的詞對記在建議歷史，之後不再自動寫入（使用者明確不要）。"""
    p = correction_history_path()
    try:
        h = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    today = date.today().isoformat()
    for w, r, _ in rows:
        e = h.get("pairs", {}).get(f"{w}\t{r}")
        if e is not None:
            e["undone"] = today
    p.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    utf8_console()
    ap = argparse.ArgumentParser(description="維護 corrections.tsv")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    a = sub.add_parser("add")
    a.add_argument("wrong")
    a.add_argument("right")
    a.add_argument("--note", default="")
    a.add_argument("--force", action="store_true", help="允許單字元、覆蓋既有對應，或加入 OpenCC 詞彙回復表的詞")
    r = sub.add_parser("remove")
    r.add_argument("wrong")
    t = sub.add_parser("test")
    t.add_argument("text")
    sub.add_parser("auto-list", help="列出自動校正寫入的項目")
    u = sub.add_parser("auto-undo", help="撤銷自動寫入的項目（先備份；撤銷過的詞對之後不再自動寫入）")
    u.add_argument("wrong", nargs="*", help="只撤銷這些錯誤寫法")
    u.add_argument("--date", help="只撤銷這一天寫入的（YYYY-MM-DD）")
    u.add_argument("--all", action="store_true", help="撤銷全部自動寫入的項目")
    args = ap.parse_args()
    rows = load()
    path = corrections_path()

    if args.cmd == "list":
        print(f"# {path}（{len(rows)} 筆）")
        for w, rr, n in rows:
            print(f"{w}\t→\t{rr}\t{n}")
    elif args.cmd == "add":
        w, rr = args.wrong.strip(), args.right.strip()
        if not w or w == rr:
            sys.exit("錯誤寫法不可為空，且不能與正確寫法相同")
        if len(w) < MIN_LEN and not args.force:
            sys.exit(f"「{w}」太短，全域替換風險高；確定要加請帶 --force")
        if w in keep_words() and not args.force:
            sys.exit(f"「{w}」在 OpenCC 詞彙回復表中，通常不需要加入對照表；確定要加請帶 --force")
        exist = {x[0]: x for x in rows}
        if w in exist and exist[w][1] != rr and not args.force:
            sys.exit(f"已有「{w} → {exist[w][1]}」，要改成「{rr}」請帶 --force")
        if any(rr0 == w for _, rr0, _ in rows):
            sys.exit(f"「{w}」是其他項目的正確寫法，加入會互相衝突")
        note = args.note or f"{date.today().isoformat()} 加入"
        rows = [x for x in rows if x[0] != w] + [(w, rr, note)]
        save(rows)
        print(f"[OK] 已加入：{w} → {rr}（{path}）")
    elif args.cmd == "remove":
        n0 = len(rows)
        rows = [x for x in rows if x[0] != args.wrong]
        if len(rows) == n0:
            sys.exit(f"找不到「{args.wrong}」")
        save(rows)
        print(f"[OK] 已移除：{args.wrong}")
    elif args.cmd == "auto-list":
        auto = auto_rows()
        print(f"# {path}：自動寫入 {len(auto)} 筆")
        for w, rr, n in auto:
            print(f"{w}\t→\t{rr}\t{n}")
    elif args.cmd == "auto-undo":
        if not (args.wrong or args.date or args.all):
            sys.exit("請指定錯誤寫法、--date 或 --all")
        words = set(args.wrong)

        def match(w, rr, n):
            if words and w not in words:
                return False
            return not args.date or n.startswith(f"{AUTO_PREFIX}{args.date}")
        if not any(match(*x) for x in auto_rows()):
            sys.exit("沒有符合的自動寫入項目")
        bak = backup()
        gone = remove_auto(match)
        for w, rr, n in gone:
            print(f"[OK] 已撤銷：{w} → {rr}（{n}）")
        print(f"  備份：{bak}")
    elif args.cmd == "test":
        new, fixes = Corrector(rows).apply(args.text)
        print(new)
        for w, rr, n in fixes:
            print(f"  {w} → {rr} ×{n}")


if __name__ == "__main__":
    main()
