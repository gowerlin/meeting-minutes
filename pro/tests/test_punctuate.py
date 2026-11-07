"""本機分段標點（規格 §5.3～§5.5）的單元測試。CT-Transformer 的實測需要測試 home 已下載標點模型，沒有就略過。"""
import unittest

import _testenv  # noqa: F401
import common
import punctuate as pu


def seg(start, end, spk, text):
    return {"start": start, "end": end, "speaker": spk, "text": text}


class FakePunctuator:
    """回傳預先準備的輸出；用來驗證對齊與插回。"""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def add(self, text):
        self.calls.append(text)
        return self.outputs.pop(0) if self.outputs else text


class BuildParagraphs(unittest.TestCase):
    def test_rules(self):
        segs = [seg(0, 5, "S1", "第一句"), seg(5, 9, "S1", "接著說"),          # 同講者、間隔 0 → 同段
                seg(11.5, 14, "S1", "停頓之後"),                               # 間隔 2.5 ≥ 2.0 → 換段
                seg(14.2, 16, "S2", "換人了"),                                 # 講者不同 → 換段
                seg(16.1, 18, "S2", "畫面之後"), seg(18.1, 20, "S2", "同段")]  # 畫面 16.05 → 換段
        frames = [{"time": 16.05, "file": "f.jpg"}]
        paras = pu.build_paragraphs(segs, frames, 2.0, 200, True)
        self.assertEqual([p["segments"] for p in paras], [[0, 1], [2, 2], [3, 3], [4, 5]])
        self.assertEqual(paras[0]["start"], 0)
        self.assertEqual(paras[0]["end"], 9)

    def test_max_chars(self):
        segs = [seg(i, i + 1, "S1", "字" * 90) for i in range(5)]
        paras = pu.build_paragraphs(segs, [], 2.0, 200, True)
        # 累積到 ≥ 200 字之後的下一個 segment 換段：90+90+90=270 → 第 4 個起換段
        self.assertEqual([p["segments"] for p in paras], [[0, 2], [3, 4]])

    def test_disabled_is_v100(self):
        segs = [seg(0, 5, "S1", "甲"), seg(9, 10, "S1", "乙" * 300), seg(10, 11, "S1", "丙"),
                seg(12, 13, "S2", "丁")]
        paras = pu.build_paragraphs(segs, [], 2.0, 200, False)
        self.assertEqual([p["segments"] for p in paras], [[0, 2], [3, 3]])

    def test_frame_tie_matches_v100(self):
        # 1.0.0：依開始時間排序、時間相同時 segment 排在畫面前面，所以畫面在 prev.start <= t < seg.start 時才把兩段隔開
        segs = [seg(0, 2, "S1", "甲"), seg(3, 4, "S1", "乙")]
        paras = pu.build_paragraphs(segs, [{"time": 3, "file": "x"}], 9, 999, True)
        self.assertEqual([p["segments"] for p in paras], [[0, 1]])          # 畫面排在「乙」之後
        paras = pu.build_paragraphs(segs, [{"time": 0, "file": "x"}], 9, 999, True)
        self.assertEqual([p["segments"] for p in paras], [[0, 0], [1, 1]])  # 畫面排在「甲」之後、「乙」之前
        paras = pu.build_paragraphs(segs, [{"time": 5, "file": "x"}], 9, 999, True)
        self.assertEqual([p["segments"] for p in paras], [[0, 1]])


class WhisperNormalize(unittest.TestCase):
    def test_half_to_full(self):
        self.assertEqual(pu.normalize_whisper("好的, 我們開始?"), "好的，我們開始？")
        self.assertEqual(pu.normalize_whisper("版本 3.5 和 Node.js 都可以"), "版本 3.5 和 Node.js 都可以")
        self.assertEqual(pu.normalize_whisper("就這樣. 下一題"), "就這樣。下一題")
        self.assertEqual(pu.normalize_whisper("Hello, world"), "Hello, world")
        self.assertEqual(pu.normalize_whisper("Sentinel， 切換"), "Sentinel，切換")

    def test_boundary_marks(self):
        segs = [seg(0, 1, "S1", "這樣可以嗎"), seg(1, 2, "S1", "我覺得可以")]
        paras = [{"segments": [0, 1]}]
        st = pu.punctuate_paragraphs(paras, segs, "turbo", None, 20)
        self.assertEqual([s["text"] for s in segs], ["這樣可以嗎？", "我覺得可以。"])
        self.assertEqual(segs[0]["text_plain"], "這樣可以嗎")
        self.assertEqual(st["by_source"]["whisper"], 1)
        self.assertEqual(paras[0]["punct"], "whisper")


class Density(unittest.TestCase):
    def test_dense_keeps_whisper(self):
        text = "今天先確認進度，然後看壓測結果。"   # 2 個標點、14 字：2×20 ≥ 14
        segs = [seg(0, 1, "S1", text)]
        fake = FakePunctuator("不应该被呼叫")
        pu.punctuate_paragraphs([{"segments": [0, 0]}], segs, "turbo", fake, 20)
        self.assertEqual(fake.calls, [])
        self.assertEqual(segs[0]["text"], text)

    def test_sparse_goes_ct(self):
        text = "今天先確認進度然後看壓測結果最後討論權限設計大家有沒有問題" + "還有時程" * 3
        segs = [seg(0, 1, "S1", text)]
        simp = pu.to_simplified_charwise(text)
        out = simp.replace("进度", "进度，").replace("权限设计", "权限设计。").replace("问题", "问题？")
        paras = [{"segments": [0, 0]}]
        pu.punctuate_paragraphs(paras, segs, "turbo", FakePunctuator(out), 20)
        self.assertEqual(paras[0]["punct"], "ct")
        self.assertTrue(segs[0]["text"].startswith("今天先確認進度，然後看壓測結果最後討論權限設計。大家有沒有問題？"))
        self.assertTrue(segs[0]["text"].endswith("。"))

    def test_density_is_per_segment(self):
        # 1.1.0：同段裡標點夠密的 segment 沿用 Whisper，不夠密的 segment 單獨交給 CT（段落標 mixed）
        dense = "今天先確認進度，然後看壓測結果。"
        sparse = "接著討論權限設計大家有沒有問題還有時程要再確認一次"
        segs = [seg(0, 1, "S1", dense), seg(1, 2, "S1", sparse)]
        out = pu.to_simplified_charwise(sparse).replace("权限设计", "权限设计，").replace("问题", "问题？")
        fake = FakePunctuator(out)
        paras = [{"segments": [0, 1]}]
        st = pu.punctuate_paragraphs(paras, segs, "turbo", fake, 20)
        self.assertEqual(fake.calls, [pu.to_simplified_charwise(sparse)])     # 只送不夠密的那個 segment
        self.assertEqual(paras[0]["punct"], "mixed")
        self.assertEqual(st["by_source"]["mixed"], 1)
        self.assertEqual(st["by_segment"], {"whisper": 1, "ct": 1, "none": 0, "ct_failed": 0})
        self.assertEqual(segs[0]["text"], dense)
        self.assertEqual(segs[1]["text"], "接著討論權限設計，大家有沒有問題？還有時程要再確認一次。")

    def test_segment_ct_failure_falls_back(self):
        segs = [seg(0, 1, "S1", "好的，我們開始。"), seg(1, 2, "S1", "這一段很長而且完全沒有任何標點符號要交給模型")]
        paras = [{"segments": [0, 1]}]
        pu.punctuate_paragraphs(paras, segs, "turbo", FakePunctuator("完全對不上。"), 20)
        self.assertEqual(paras[0]["punct"], "ct_failed")
        self.assertEqual(segs[1]["text"], "這一段很長而且完全沒有任何標點符號要交給模型。")

    def test_breeze_always_ct_or_none(self):
        segs = [seg(0, 1, "S1", "好的，我們開始。")]
        paras = [{"segments": [0, 0]}]
        pu.punctuate_paragraphs(paras, segs, "breeze", None, 20)
        self.assertEqual(paras[0]["punct"], "none")
        segs = [seg(0, 1, "S1", "好 那我們開始")]
        paras = [{"segments": [0, 0]}]
        pu.punctuate_paragraphs(paras, segs, "breeze", None, 20)
        self.assertEqual(segs[0]["text"], "好 那我們開始。")    # 只補段尾句號


class CtAlignment(unittest.TestCase):
    def test_traditional_text_untouched_and_split_back(self):
        segs = [seg(0, 1, "S1", "我們先確認 Redis 的切換時間"), seg(1, 2, "S1", "然後看延遲你覺得可以嗎")]
        # 模型輸出（簡體、去掉空白、半形標點）：插回的位置依內容字元對齊
        out = "我们先确认redis的切换时间，然后看延迟，你觉得可以吗?"
        texts = pu._ct_path([s["text"] for s in segs], FakePunctuator(out))
        self.assertEqual(texts, ["我們先確認 Redis 的切換時間，", "然後看延遲，你覺得可以嗎？"])

    def test_dot_inside_number_is_content(self):
        texts = pu._ct_path(["大約是3.5秒然後看結果"], FakePunctuator("大约是3 . 5秒，然后看结果。"))
        self.assertEqual(texts, ["大約是3.5秒，然後看結果。"])

    def test_tail_dropped_is_resent(self):
        fake = FakePunctuator("好，那我们就这样决定吧。", "下周三之前把文件交出来。")
        texts = pu._ct_path(["好那我們就這樣決定吧下週三之前把文件交出來"], fake)
        self.assertEqual(texts, ["好，那我們就這樣決定吧。下週三之前把文件交出來。"])
        self.assertEqual(len(fake.calls), 2)

    def test_mismatch_is_ct_failed(self):
        segs = [seg(0, 1, "S1", "這是一段很長而且沒有標點的文字要交給模型處理看看結果如何")]
        paras = [{"segments": [0, 0]}]
        st = pu.punctuate_paragraphs(paras, segs, "turbo", FakePunctuator("完全不同的输出。"), 20)
        self.assertEqual(paras[0]["punct"], "ct_failed")
        self.assertEqual(st["by_source"]["ct_failed"], 1)
        self.assertEqual(segs[0]["text"], "這是一段很長而且沒有標點的文字要交給模型處理看看結果如何。")

    def test_existing_punct_removed_first(self):
        texts = pu._ct_path(["好的,我們開始"], FakePunctuator("好的，我们开始。"))
        self.assertEqual(texts, ["好的，我們開始。"])

    def test_paragraph_end_comma_becomes_period(self):
        texts = pu._close_paragraph(["好的，", "我們開始，"])
        self.assertEqual(texts, ["好的，", "我們開始。"])


@unittest.skipUnless(common.punct_ready(), "測試 home 沒有標點模型（MEETING_MINUTES_PRO_HOME 指向已下載模型的 home 才會跑）")
class RealModel(unittest.TestCase):
    def test_real_ct(self):
        p = pu.Punctuator(common.punct_model(), 2)
        segs = [seg(0, 5, "S1", "我們今天先確認 Redis Sentinel 的切換時間 大約是三點五秒"),
                seg(5, 9, "S1", "然後看 Kafka consumer lag 你覺得這樣可以嗎")]
        paras = [{"segments": [0, 1]}]
        pu.punctuate_paragraphs(paras, segs, "breeze", p, 20)
        self.assertEqual(paras[0]["punct"], "ct")
        joined = "".join(s["text"] for s in segs)
        self.assertIn("Redis Sentinel", joined)
        self.assertTrue(joined.endswith(("？", "。")))
        self.assertEqual(pu.content_len(joined), pu.content_len("".join(s["text_plain"] for s in segs)))


if __name__ == "__main__":
    unittest.main()
