"""產生 M3 長會議講稿（規格 §9.1：M1＋M2 改寫拼接再延長；自動校正 C3 用）：materials/M3-long-meeting.txt。

全部由 M1、M2 的虛構講稿改寫而成（換公司名、版本、月份、數字），不含任何真實會議內容。
目標：約 70 分鐘、4 位講者，讓自動校正切成 ≥ 6 塊（每塊 3,500 字）。輸出檔是普通講稿，之後照 make_materials.py M3 合成。

講者對應：M1 的 S1～S4 原樣；M2 的 S1（男）→ S4、S2（女）→ S1、S3（女）→ S3。
用法：python make_m3.py
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAT = HERE / "materials"
M2_SPK = {"S1": "S4", "S2": "S1", "S3": "S3"}

# 每一輪的改寫（依序套用；只換虛構的名稱與數字，不改句型，所以辨識難度與 M1／M2 相近）
ROUNDS = [
    ("M1", {}),
    ("M2", {}),
    ("M1", {"示範證券": "範例證券", "第三版": "第四版", "上週五": "上週三", "第二輪": "第三輪", "八百筆": "九百筆",
            "一百二十毫秒": "一百一十毫秒", "兩百毫秒": "三百毫秒", "十二秒": "九秒"}),
    ("M2", {"十月": "十一月", "九月": "十月", "四千三百六十萬": "四千七百二十萬", "百分之八點五": "百分之六點二",
            "九百八十萬": "一千零五十萬", "兩百一十萬": "一百九十萬", "年底促銷": "春節促銷"}),
    ("M1", {"示範證券": "範例期貨", "第三版": "第二版", "上週五": "前天", "八百筆": "六百筆", "一百二十毫秒": "九十毫秒",
            "十二秒": "十五秒"}),
    ("M2", {"十月": "十二月", "九月": "十一月", "四千三百六十萬": "五千一百萬", "百分之八點五": "百分之九",
            "年底促銷": "週年慶"}),
]


def paragraphs(path: Path) -> tuple:
    head, voices, paras = [], [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if line.startswith("@voice"):
            voices.append(line)
            continue
        spk, text = line.split("｜", 1)
        text = re.sub(r"^<[0-9.]+>", "", text)          # 固定靜音只在原講稿用，M3 一律隨機
        paras.append((spk.strip(), text.strip()))
    return voices, paras


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    m1_voices, m1 = paragraphs(next(MAT.glob("M1-*.txt")))
    _, m2 = paragraphs(next(MAT.glob("M2-*.txt")))
    lines = ["# M3 長會議（虛構；由 tests/make_m3.py 從 M1、M2 改寫拼接產生，請勿手改）",
             "# 用途：自動校正的切塊（≥ 6 塊）、用字表、跨塊一致、耗時與預估（C3）。基準稿＝本檔。",
             "# 講者：同 M1 的 S1～S4；M2 的段落改由 S1（女）、S3（女）、S4（男）念。"]
    lines += m1_voices
    n = 0
    for src, subs in ROUNDS:
        rows = m1 if src == "M1" else [(M2_SPK[s], t) for s, t in m2]
        for spk, text in rows:
            for a, b in subs.items():
                text = text.replace(a, b)
            lines.append(f"{spk}｜{text}")
            n += 1
    out = MAT / "M3-long-meeting.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    chars = sum(len(re.sub(r"[\s，。、；：？！「」／]", "", l.split("｜", 1)[1])) for l in lines if "｜" in l)
    print(f"{out.name}: {n} 段、約 {chars} 字")


if __name__ == "__main__":
    main()
