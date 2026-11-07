"""R 回歸（單元層級）：分段標點關閉時，1.1.0 的 transcript.md 本文與 .srt 和 1.0.0 的 write_outputs() 相同。

1.0.0 的 write_outputs() 取自固定夾具 fixtures/v100_outputs.py（由 1.0.0 原樣複製），公開 repo 只有最新版目錄時也能跑；
repo 裡有 meeting-minutes-pro-v1.0.0 目錄時，另外檢查夾具和原檔的函式相同。實際音檔的端對端比對在 eval_materials.py。
"""
import ast
import importlib.util
import random
import tempfile
import unittest
from pathlib import Path

import _testenv
import punctuate as pu
import transcribe as t110

V100 = _testenv.HERE.parent / "meeting-minutes-pro-v1.0.0" / "payload" / "runtime" / "scripts" / "transcribe.py"
FIXTURE = _testenv.HERE / "fixtures" / "v100_outputs.py"
FIXTURE_FUNCS = ("ts", "write_outputs")


def load_v100():
    spec = importlib.util.spec_from_file_location("transcribe_v100", FIXTURE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def body(md: str) -> str:
    """表頭（第一個空行之前的 # 標題與 - 清單）以外的內容。"""
    lines = md.split("\n")
    i = 2                       # 「# 逐字稿：…」與空行之後是 - 開頭的表頭行
    while i < len(lines) and lines[i].startswith("- "):
        i += 1
    return "\n".join(lines[i:])


class WriteOutputsRegression(unittest.TestCase):
    def test_random_inputs(self):
        v100 = load_v100()
        rnd = random.Random(7)
        words = ["今天", "Redis", "確認", "，", "Kafka lag", "我們", "。", "好", "3.5", "可以嗎"]
        for case in range(60):
            segs, t = [], 0.0
            for _ in range(rnd.randint(1, 25)):
                t += rnd.choice([0, 0, 0.3, 1.0, 2.5, 4.0])
                d = rnd.uniform(0.5, 9)
                segs.append({"start": round(t, 2), "end": round(t + d, 2), "speaker": rnd.choice(["S1", "S2", "S3"]),
                             "text": "".join(rnd.choice(words) for _ in range(rnd.randint(1, 8)))})
                t += d
            frames = [{"time": round(rnd.uniform(0, t), 2), "file": f"frame_{k:04d}.jpg"}
                      for k in range(rnd.randint(0, 4))]
            meta = {"source": "x.wav", "duration": t, "speakers": 3, "model": "turbo", "device": "openvino/NPU",
                    "elapsed_sec": 1.0, "rtf": 0.1, "corrections_applied": {}}
            with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                v100.write_outputs(Path(a), dict(meta), [dict(s) for s in segs], frames)
                s110 = [dict(s) for s in segs]
                paras = pu.build_paragraphs(s110, frames, 2.0, 200, False)
                for k, p in enumerate(paras):
                    for i in range(p["segments"][0], p["segments"][1] + 1):
                        s110[i]["para"] = k
                t110.write_outputs(Path(b), dict(meta, punctuation={"enabled": False}, opencc_keep_applied={}),
                                   s110, frames, paras)
                md_a = (Path(a) / "transcript.md").read_text(encoding="utf-8")
                md_b = (Path(b) / "transcript.md").read_text(encoding="utf-8")
                self.assertIn("- 分段標點：關閉", md_b)
                self.assertEqual(body(md_a), body(md_b), f"case {case}")
                self.assertEqual((Path(a) / "transcript.srt").read_text(encoding="utf-8"),
                                 (Path(b) / "transcript.srt").read_text(encoding="utf-8"), f"case {case}")


def _functions(path: Path) -> dict:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in FIXTURE_FUNCS}


@unittest.skipUnless(V100.is_file(), "需要 meeting-minutes-pro-v1.0.0 目錄（公開 repo 只有最新版）")
class FixtureSameAsV100(unittest.TestCase):
    def test_fixture_matches_original(self):
        fixture = _functions(FIXTURE)
        self.assertEqual(sorted(fixture), sorted(FIXTURE_FUNCS))
        self.assertEqual(fixture, _functions(V100))


if __name__ == "__main__":
    unittest.main()
