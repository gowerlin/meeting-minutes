"""測試用的合成素材與假的 meeting-minutes-pro。內容全部虛構：人名、公司、系統、對話都是編的，沒有真實會議內容。

  python -B materials.py <目錄>            產生 D1、D2、D3 三份輸出資料夾（D1 附合成提示音 D1-demo.wav）
  python -B materials.py --long <目錄>     另外產生 3 小時的長稿 LONG-demo_minutes（效能測試）

每個資料夾有 transcript.json（含 segments）、transcript.md、transcript.corrected.md（Pro 2.2.0 的標記）與
meeting-minutes.md 或 notes.md。transcript.md 依 Pro transcribe.write_outputs() 的接字規則由 segments 組成，
所以標記以外的文字與 transcript.md 逐字相同（Pro subtitles.map_corrected 對得回辨識段）。
"""
import json
import math
import random
import re
import shutil
import sys
import wave
from pathlib import Path

# 段落：(講者代號, [片段…])；片段是字串（原文＝校正版）或 ("fix"|"unify", 原文, 修正)、("del", 原文)、("ins", 補字)、
# ("q", 原文, 推測或 None)。
D1 = {
    "source": "D1-demo.wav", "title": "D1-demo.wav", "kind": "meeting", "gap": 11,
    "speakers": {"S1": "王小明", "S2": "李小華", "S3": "陳大同"},
    "paras": [
        ("S1", ["好，我們開始。今天主要確認", ("fix", "星荷", "星河"), "物流倉儲系統升級的進度，", "有三個項目：壓測結果、",
                ("unify", "kafka", "Kafka"), "的延遲，還有新的", ("fix", "全線", "權限"), "設計。"]),
        ("S2", ["上週五做了第二輪壓測，高峰大約每秒八百筆，", "延遲在一百二十毫秒以內。主要是把下單介面改成密等，", "重送的請求不會重複寫入。"]),
        ("S2", ["重試的策略改成指數退幣，最多三次，", "間隔從兩百毫秒開始加倍。", ("del", "謝謝觀看"), "這樣在對方回應變慢的時候，不會一直打過去。"]),
        ("S1", ["那", ("fix", "星荷", "星河"), "這邊的倉儲資料庫呢？", "上次提到要做分區。"]),
        ("S3", ["分區已經做好了，", "一個交易日一個分區，", "查歷史訂單只會掃到需要的分區。", ("fix", "瑞迪斯", "Redis"), "的快取也調整過。"]),
        ("S3", ["另外", ("unify", "notebook lm", "NotebookLM"), "整理的會議重點，我們會放到共用資料夾，", "大家可以直接查。"]),
        ("S1", ["好。上線日期是不是定在", ("q", "七月三號", "七月十三號"), "？", "我記得", ("fix", "星荷", "星河"), "那邊有提過。"]),
        ("S2", ["我這邊聽到的是十三號，", "不過還要跟", ("q", "滑頂", None), "確認一下", ("ins", "在"), "週三前回覆。"]),
        ("S3", [("unify", "KAFKA", "Kafka"), "的消費延遲高峰大約四秒就消化完，", "分割區從六個加到十二個，", "指數退幣的部分也一起套用。"]),
        ("S1", ["那", ("fix", "瑞迪斯", "Redis"), "的切換演練呢？", "上次花了十二秒，有點太久。"]),
        ("S2", ["我們想把偵測時間從五秒調到三秒，", "這週再排一次演練。", ("unify", "notebookLM", "NotebookLM"), "的紀錄也會更新。"]),
        ("S1", ["好，那今天就到這裡。", "下週同一時間再確認一次全線的進度。"]),
    ],
    "minutes": """# 會議記錄：D1-demo.wav

> 表頭：日期（合成示範）｜時長 00:02:12｜講者 3 位｜來源：transcript.corrected.md｜這一行提到星荷不會被改

## 摘要

- 星荷物流倉儲系統升級：第二輪壓測高峰每秒八百筆，延遲在一百二十毫秒以內。`[00:00:11]`
- 倉儲資料庫已做分區；瑞迪斯快取已調整。`[00:00:44]`
- notebook lm 整理的會議重點放在共用資料夾。`[00:00:55]`

## 決議

| # | 決議 | 時間碼 |
|---|---|---|
| 1 | 瑞迪斯切換演練的偵測時間從五秒調到三秒，本週再演練一次 | [00:01:50] |

## 待辦

| # | 事項 | 負責人 | 期限 | 備註 | 時間碼 |
|---|---|---|---|---|---|
| 1 | 跟星荷物流確認上線日期 | 李小華 | 週三 |  | [00:01:17] |

```
程式區塊裡的星荷不會被改
```

## 待釐清問題

- 上線日期是七月三號還是七月十三號？`[00:01:06]`
""",
}

D2 = {
    "source": "D2-demo.m4a", "title": "D2-demo.m4a", "kind": "course", "gap": 20, "no_media": True,
    "speakers": {"S1": "講師"},
    "paras": [
        ("S1", ["今天我們講資料分析入門的第二堂，", "先複習相關係數。", ("fix", "皮爾森", "Pearson"), "相關係數介於負一到一之間。"]),
        ("S1", ["大家手上的", ("unify", "excel", "Excel"), "檔案打開，", "第二個工作表有一份銷售資料。"]),
        ("S1", ["接下來是", ("q", "迴歸", "回歸"), "分析，", "我們用最小平方法找一條線。"]),
        ("S1", ["用", ("unify", "EXCEL", "Excel"), "的話，", "可以直接加趨勢線，", "勾選顯示公式就可以看到斜率。"]),
        ("S1", [("fix", "皮爾森", "Pearson"), "相關係數高，不代表有因果關係，", "這點考試很常考。"]),
        ("S1", ["下課前請大家把作業上傳到課程平台，", "截止時間是下週一晚上。"]),
    ],
    "notes": """# 課程筆記：D2-demo.m4a

> 內容類型：課程（合成示範）｜時長 00:02:00

## 重點

- 皮爾森相關係數介於 -1 到 1。`[00:00:00]`
- excel 可直接加趨勢線並顯示公式。`[00:01:00]`
- 相關不代表因果。`[00:01:20]`
""",
}

D3 = {
    "source": "D3-demo.wav", "title": "D3-demo.wav", "kind": "meeting", "gap": 15, "no_media": True,
    "speakers": {"S1": "王小明", "S2": "陳大同"},
    "paras": [
        ("S1", ["這是第三份示範稿，", "用來測試一次開三份。", ("fix", "庫伯", "Kubernetes"), "的版本要升級。"]),
        ("S2", ["好，我下週二前把", ("q", "測試環境", "預備環境"), "準備好。"]),
        ("S1", ["那就這樣。"]),
    ],
    "minutes": "# 會議記錄：D3-demo.wav\n\n## 摘要\n\n- 庫伯版本要升級。`[00:00:00]`\n",
}


def ts(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def piece_text(p, side: str) -> str:
    if isinstance(p, str):
        return p
    k = p[0]
    if k in ("fix", "unify"):
        return p[1] if side == "orig" else "{" + p[1] + "→" + p[2] + "}"
    if k == "del":
        return p[1] if side == "orig" else "{" + p[1] + "→}"
    if k == "ins":
        return "" if side == "orig" else "{→" + p[1] + "}"
    if k == "q":
        return p[1] if side == "orig" else ("[?" + p[1] + ("｜" + p[2] if p[2] else "") + "]")
    raise ValueError(k)


def build(spec: dict, out: Path) -> tuple:
    out.mkdir(parents=True, exist_ok=True)
    segs, t, orig_paras, cor_paras, pending = [], 0.0, [], [], []
    for pi, (spk, pieces) in enumerate(spec["paras"]):
        pieces = [p for p in pieces if p != ""]
        o = "".join(piece_text(p, "orig") for p in pieces)
        c = "".join(piece_text(p, "cor") for p in pieces)
        cuts, buf = [], ""
        for p in pieces:                         # 在純文字片段的邊界切辨識段
            buf += piece_text(p, "orig")
            if isinstance(p, str) and p.endswith("，") and len(buf) >= 8:
                cuts.append(buf)
                buf = ""
        if buf:
            cuts.append(buf)
        dur = spec["gap"] - 1.0
        n = sum(len(x) for x in cuts) or 1
        st = t
        for x in cuts:
            d = dur * len(x) / n
            segs.append({"start": round(st, 2), "end": round(st + d, 2), "speaker": spk, "text": x, "para": pi})
            st += d
        orig_paras.append((ts(t), spk, o))
        name = spec["speakers"][spk]
        cor_paras.append((ts(t), f"{name}（{spk}）" if name != spk else spk, c))
        for p in pieces:
            if not isinstance(p, str) and p[0] == "q":
                pending.append(f"- `[{ts(t)}]` {piece_text(p, 'cor')}：請回聽確認")
        t += spec["gap"]
    duration = t
    meta = {"version": "2.2.0", "source": spec["source"], "duration": duration, "speakers": len(spec["speakers"]),
            "model": "turbo", "device": "cpu", "language": "zh", "content_type": spec["kind"]}
    (out / "transcript.json").write_text(json.dumps({"meta": meta, "segments": segs}, ensure_ascii=False, indent=1),
                                         encoding="utf-8", newline="\n")
    md = [f"# 逐字稿：{spec['title']}", "", f"- 長度：{ts(duration)}　講者數：{len(spec['speakers'])}　ASR：turbo @ cpu",
          "- 合成示範素材：人名、公司、系統與對話都是虛構的", ""]
    for tt, spk, o in orig_paras:
        md += [f"**[{tt}] {spk}**：{o}", ""]
    (out / "transcript.md").write_text("\n".join(md), encoding="utf-8", newline="\n")
    edits = {}
    for spk, pieces in spec["paras"]:
        for p in pieces:
            if not isinstance(p, str) and p and p[0] == "fix" and p[1] != p[2]:
                edits[(p[1], p[2])] = edits.get((p[1], p[2]), 0) + 1
    cor = [f"# 校正版逐字稿：{spec['title']}", "",
           "> 原始逐字稿：`transcript.md`（未修改）｜模型：turbo @ cpu｜校正：自動（合成示範，未呼叫模型）｜1/1 段完成", "",
           "## 校正摘要", "", "| # | 原文 | 修正 | 次數 | 依據 | 建議加入對照表 |", "|---|---|---|---|---|---|"]
    for i, ((a, b), n) in enumerate(edits.items(), 1):
        cor.append(f"| {i} | {a} | {b} | {n} | 上下文 | ❌ 依上下文 |")
    cor += ["", "## 講者對應", "", "| 代號 | 姓名 | 依據 |", "|---|---|---|"]
    for k, v in spec["speakers"].items():
        cor.append(f"| {k} | {v} | 合成示範 |")
    cor += ["", "## 待確認", ""] + (pending or ["- 無"]) + ["", "---", ""]
    for i, (tt, spk, c) in enumerate(cor_paras):
        cor += [f"**[{tt}] {spk}**：{c}", ""]
        if i == 0 and spec is D1:
            cor += ["> 🖼 `[00:00:05]` 畫面：合成示範的投影片（原樣保留）", ""]
    (out / "transcript.corrected.md").write_text("\n".join(cor), encoding="utf-8", newline="\n")
    if spec.get("minutes"):
        (out / "meeting-minutes.md").write_text(spec["minutes"], encoding="utf-8", newline="\n")
    if spec.get("notes"):
        (out / "notes.md").write_text(spec["notes"], encoding="utf-8", newline="\n")
    return duration, [s["start"] for s in segs]


def make_wav(path: Path, duration: float, para_starts: list, rate: int = 8000):
    """合成提示音：每段開頭一聲短嗶，其餘是很輕的底噪。不是語音。"""
    rnd = random.Random(7)
    n = int(duration * rate)
    frames = bytearray(128 + int(rnd.uniform(-2, 2)) for _ in range(n))
    for k, s in enumerate(int(x * rate) for x in para_starts):
        f = 440 + 110 * (k % 4)
        for j in range(int(0.25 * rate)):
            if s + j < n:
                frames[s + j] = 128 + int(60 * math.sin(2 * math.pi * f * j / rate) * (1 - j / (0.25 * rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def long_spec(hours: float = 3.0) -> dict:
    paras = []
    base = D1["paras"]
    for i in range(int(hours * 3600 / 12)):
        spk, pieces = base[i % len(base)]
        paras.append((spk, list(pieces) + ["補充說明第" + str(i) + "段。"]))
    return dict(D1, paras=paras, gap=12, title="LONG-demo.wav", source="LONG-demo.wav", minutes=None, no_media=True)


def make_all(root: Path) -> dict:
    """D1～D3 → {"D1": 資料夾, …}。"""
    root.mkdir(parents=True, exist_ok=True)
    out = {}
    for spec, name in ((D1, "D1"), (D2, "D2"), (D3, "D3")):
        folder = root / f"{name}-demo_minutes"
        dur, _ = build(spec, folder)
        if not spec.get("no_media"):
            make_wav(root / spec["source"], dur, [i * spec["gap"] for i in range(len(spec["paras"]))])
        out[name] = folder
    return out


def make_long(root: Path) -> Path:
    folder = root / "LONG-demo_minutes"
    build(long_spec(), folder)
    return folder


# ---------------------------------------------------------------- 假的 meeting-minutes-pro
FAKE_AUTO_MINUTES = r'''"""測試用的假 auto_minutes.py（不呼叫模型）。只支援 --source final 的 --estimate-only 與 --force。
$MMH/fake-exit.txt 寫了 exit code 時模擬失敗。"""
import json, os, sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_html

args = sys.argv[1:]
out = Path(args[0])
if "--source" not in args or args[args.index("--source") + 1] != "final":
    print(json.dumps({"minutes": {"status": "skipped", "reason": "source"}}))
    sys.exit(2)
final = out / "transcript.final.md"
if "--estimate-only" in args:
    n = len(final.read_text(encoding="utf-8")) if final.exists() else 0
    print(json.dumps({"estimate": {"provider": "Claude", "model": "sonnet", "channel": "cli", "usd_low": 0.01,
                                   "usd_high": 0.02, "chars": n}}))
    sys.exit(0)
flag = Path(os.environ.get("MEETING_MINUTES_PRO_HOME", ".")) / "fake-exit.txt"
code = int(flag.read_text().strip() or 0) if flag.exists() else 0
if code:
    print("[!] 模擬的失敗", file=sys.stderr)
    print(json.dumps({"minutes": {"status": "failed", "reason": "simulated", "message": "模擬的失敗"}}, ensure_ascii=False))
    sys.exit(code)
meta = json.loads((out / "transcript.json").read_text(encoding="utf-8")).get("meta") or {}
name = "meeting-minutes.md" if meta.get("content_type", "meeting") == "meeting" else "notes.md"
p = out / name
if p.exists():
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    p.replace(p.with_name(f"{p.stem}.{stamp}.bak{p.suffix}"))
body = final.read_text(encoding="utf-8").split("---", 1)[-1].strip().splitlines()[:3]
p.write_text("# 會議記錄（假的重做）\n\n> 由測試用的假 auto_minutes.py 產生，來源 transcript.final.md\n\n" + "\n".join(body) + "\n",
             encoding="utf-8", newline="\n")
r = render_html.render(out, name, cfg={})
print(json.dumps({"minutes": {"status": "ok", "reason": None, "provider": "claude", "model": "sonnet",
                              "source_file": "transcript.final.md", "minutes_md": str(p),
                              "html": {"status": r.get("status"), "reason": r.get("reason")}, "cost_usd": 0.0}},
                 ensure_ascii=False))
'''


def make_fake_pro(real_scripts: Path, dst: Path, version: str = "2.3.0", mark_pattern: str | None = None,
                  drop: tuple = ()) -> Path:
    """複製真的 Pro scripts（唯讀來源，不改原檔）到 dst，再改版號、標記樣式或拿掉介面名稱；auto_minutes.py 換成假的。"""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(real_scripts, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    common = dst / "common.py"
    common.write_text(re.sub(r'^VERSION = "[^"]+"', f'VERSION = "{version}"', common.read_text(encoding="utf-8"), count=1,
                             flags=re.M), encoding="utf-8", newline="\n")
    if mark_pattern is not None:
        c = dst / "consistency.py"
        s = c.read_text(encoding="utf-8")
        s = re.sub(r'^MARK_RE = re\.compile\(.*\)$', "MARK_RE = re.compile(" + repr(mark_pattern) + ")", s, count=1, flags=re.M)
        c.write_text(s, encoding="utf-8", newline="\n")
    for mod, name in drop:
        f = dst / f"{mod}.py"
        f.write_text(f.read_text(encoding="utf-8") + f"\n\ndel {name}\n", encoding="utf-8", newline="\n")
    (dst / "auto_minutes.py").write_text(FAKE_AUTO_MINUTES, encoding="utf-8", newline="\n")
    return dst


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--long"]:
        print(make_long(Path(a[1])))
    elif a[:1] == ["--fake-pro"]:                          # 〔1.1.0〕瀏覽器測試用：--fake-pro <真的 scripts> <目的> <版號>
        print(make_fake_pro(Path(a[1]), Path(a[2]), version=a[3]))
    else:
        print(make_all(Path(a[0])))
