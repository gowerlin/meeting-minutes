"""〔2.0.0〕說話者分離（規格 §4）的單元測試：

- D-3 keep_top_n()、D-4 speaker_stats()／表頭行、trim_overlaps()
- D-5 引擎選擇（status、假的 nvidia-smi、VRAM、macOS）與退回（假的 diarize_pyannote.py：各種 reason、逾時、壞 JSON）
- D-6 主行程沒有 import torch；子行程的環境變數（HF_HUB_OFFLINE、PYANNOTE_METRICS_ENABLED、CUDA_VISIBLE_DEVICES）
- transcribe.py 整個流程（假的 ASR 與 sherpa，不需要模型）：表頭講者行、meta.diarization、run_log 欄位、退回時轉寫成功、
  log 不含逐字稿片段與子行程 stderr（L-1 分離部分）
- content_types 骨架、common.type_setting()、transcribe.resolve_settings()（類型、範本、人數、門檻的優先序）
不呼叫任何模型、不需要 GPU；真的 GPU 實測在 eval_diar.py。2.0.0 以前的版本整個略過。
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from argparse import Namespace
from pathlib import Path

import numpy as np

import _testenv

V2 = _testenv.VER >= (2, 0, 0)
HERE = Path(__file__).resolve().parent
FAKE = HERE / "fake_diarize_pyannote.py"
if V2:
    import common
    import content_types
    import diarize as diar
    import runlog
    import transcribe as tr

READY = {"diarization": {"pyannote": {"status": "ready"}}}


def fake_model_dir(root: Path) -> Path:
    d = root / "pyannote-model"
    for f in common.PYANNOTE_MODEL_FILES:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_bytes(b"x")
    return d


@unittest.skipUnless(V2, "2.0.0 才有")
class TopN(unittest.TestCase):
    def test_keeps_n_largest_and_merges_to_neighbour(self):
        segs = [(0, 10, 0), (10, 11, 1), (11, 20, 2), (20, 21, 3), (21, 30, 0), (30, 31, 1)]
        out, merged = diar.keep_top_n(segs, 2)            # 講者 0（19 s）、2（9 s）保留；1、3 併回前一段
        self.assertEqual({k for _, _, k in out}, {0, 1})
        self.assertEqual([k for _, _, k in out], [0, 0, 1, 1, 0, 0])
        self.assertEqual(merged, 3.0)

    def test_first_segment_merges_forward(self):
        out, _ = diar.keep_top_n([(0, 1, 0), (1, 10, 1), (10, 20, 2)], 2)
        self.assertEqual([k for _, _, k in out], [0, 0, 1])   # 第一段沒有前一段 → 併到後一段的講者，重編

    def test_not_more_than_n_untouched(self):
        segs = [(0, 1, 0), (1, 2, 1)]
        self.assertEqual(diar.keep_top_n(segs, 3), (segs, 0.0))
        self.assertEqual(diar.keep_top_n(segs, 2), (segs, 0.0))
        self.assertEqual(diar.keep_top_n(segs, None), (segs, 0.0))

    def test_tie_by_first_appearance(self):
        out, _ = diar.keep_top_n([(0, 5, 0), (5, 10, 1), (10, 15, 2)], 2)   # 三位一樣長 → 保留先出現的 0、1
        self.assertEqual([k for _, _, k in out], [0, 1, 1])

    def test_n_one_keeps_timeline(self):
        segs = [(0, 3, 0), (3, 4, 1), (4, 9, 0)]
        out, merged = diar.keep_top_n(segs, 1)               # 「人數 1」不是略過：時間軸照分離切
        self.assertEqual(out, [(0, 3, 0), (3, 4, 0), (4, 9, 0)])
        self.assertEqual(merged, 1.0)


@unittest.skipUnless(V2, "2.0.0 才有")
class Overlaps(unittest.TestCase):
    def test_trim(self):
        self.assertEqual(diar.trim_overlaps([(0, 5, 0), (4, 9, 1), (8.8, 9.1, 0), (9.5, 12, 0)]),
                         [(0, 5, 0), (5, 9, 1), (9.5, 12, 0)])

    def test_exclusive_untouched(self):
        segs = [(0, 1, 0), (1, 2, 1), (3, 4, 0)]
        self.assertEqual(diar.trim_overlaps(segs), segs)


@unittest.skipUnless(V2, "2.0.0 才有")
class Stats(unittest.TestCase):
    def test_stats_and_line(self):
        turns = [[0, 3493.2, "S1"], [3493.2, 3574.2, "S2"], [3574.2, 3580.3, "S3"]]
        st = diar.speaker_stats(turns, 10)
        self.assertEqual([s["speaker"] for s in st], ["S1", "S2", "S3"])
        self.assertEqual([s["minor"] for s in st], [False, False, True])
        self.assertEqual(st[0]["share"], 0.976)
        self.assertEqual(diar.stats_line(st), "- 講者發言時間：S1 58:13（98%）、S2 1:21（2%）、S3 0:06 ⚠ 發言很少，可能是分離誤判")

    def test_order_hours_and_single(self):
        st = diar.speaker_stats([[0, 5, "S1"], [5, 3700, "S2"], [3700, 3720, "S1"]], 10)
        self.assertEqual(st[0]["speaker"], "S2")
        self.assertEqual(diar.fmt_talk(3695), "1:01:35")
        self.assertEqual(diar.fmt_talk(6.1), "0:06")
        self.assertIsNone(diar.stats_line(diar.speaker_stats([[0, 10, "S1"]], 10)))
        self.assertIsNone(diar.stats_line([]))

    def test_cl1_student_marked_not_merged(self):
        """D-4：CL1 學員只問一題（6 秒）→ 標 ⚠、不被合併（沒給人數時 keep_top_n 不會被呼叫）。"""
        turns = [[0, 593, "S1"], [593, 614, "S2"], [614, 620, "S3"]]
        st = diar.speaker_stats(turns, 10)
        self.assertEqual(len(st), 3)
        self.assertTrue(st[2]["minor"])

    def test_header_line_in_transcript_md(self):
        out = Path(tempfile.mkdtemp(prefix="mmp-hdr-"))
        try:
            segs = [{"start": 0.0, "end": 5.0, "speaker": "S1", "text": "第一句"},
                    {"start": 5.0, "end": 9.0, "speaker": "S2", "text": "第二句"}]
            stats = diar.speaker_stats([[0, 5, "S1"], [5, 9, "S2"]], 10)
            meta = {"source": "a.wav", "duration": 9.0, "speakers": 2, "model": "turbo", "device": "x",
                    "elapsed_sec": 1.0, "rtf": 0.1, "diarization": {"setting": "auto"}, "speaker_stats": stats}
            tr.write_outputs(out, meta, segs, [])
            lines = (out / "transcript.md").read_text(encoding="utf-8").splitlines()
            self.assertTrue(lines[2].startswith("- 長度："))
            self.assertEqual(lines[3], "- 講者發言時間：S1 0:05 ⚠ 發言很少，可能是分離誤判、S2 0:04 ⚠ 發言很少，可能是分離誤判")
            self.assertTrue(lines[4].startswith("- 處理耗時："))
            meta["diarization"] = {"setting": "skip"}
            tr.write_outputs(out, meta, segs, [])
            self.assertNotIn("講者發言時間", (out / "transcript.md").read_text(encoding="utf-8"))
            del meta["diarization"], meta["speaker_stats"]                    # 1.2.2 形狀的 meta：照舊
            tr.write_outputs(out, meta, segs, [])
            self.assertNotIn("講者發言時間", (out / "transcript.md").read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(out, ignore_errors=True)


def _fake_nvsmi(root: Path, lines: list, rc: int = 0) -> Path:
    d = root / "nvsmi"
    d.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        body = "@echo off\r\n" + "".join(f"echo {x}\r\n" for x in lines) + f"exit /b {rc}\r\n"
        (d / "nvidia-smi.cmd").write_text(body, encoding="ascii")
    else:
        p = d / "nvidia-smi"
        p.write_text("#!/bin/sh\n" + "".join(f"echo '{x}'\n" for x in lines) + f"exit {rc}\n", encoding="ascii")
        p.chmod(0o755)
    return d


@unittest.skipUnless(V2, "2.0.0 才有")
class ChooseEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-ce-"))
        self._path = os.environ.get("PATH", "")

    def tearDown(self):
        os.environ["PATH"] = self._path
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ce(self, cfg, req=None, gpus=None, platform="win32"):
        return diar.choose_engine(cfg, req, platform=platform, gpus=gpus)

    def test_table(self):
        c = self.ce({}, "sherpa")
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "config", None))
        c = self.ce(READY, None, gpus=[(0, 8000)])
        self.assertEqual((c["engine"], c["reason"], c["fallback"], c["gpu_index"]), ("pyannote", "auto_gpu", None, 0))
        c = self.ce(READY, "pyannote", gpus=[(0, 3000), (1, 9000)])
        self.assertEqual((c["engine"], c["reason"], c["gpu_index"], c["free_mib"]), ("pyannote", "config", 1, 9000))
        c = self.ce({}, None, gpus=[(0, 8000)])                              # 沒裝（status 預設 none）
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "not_installed", None))
        c = self.ce(READY, None, gpus=[])
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "no_gpu", None))
        c = self.ce(READY, None, gpus=[(0, 3000)])
        self.assertEqual((c["engine"], c["reason"], c["fallback"], c["free_mib"]), ("sherpa", "low_vram", None, 3000))
        c = self.ce(READY, None, gpus=[(0, 8000)], platform="darwin")
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "macos", None))
        c = self.ce(READY, "pyannote", gpus=[(0, 3000)])                     # 要用 pyannote 卻沒用成 → fallback
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "low_vram", "low_vram"))
        c = self.ce({}, "pyannote", gpus=[(0, 8000)])
        self.assertEqual((c["engine"], c["fallback"]), ("sherpa", "not_installed"))
        c = self.ce({"diarization": {"engine": "sherpa", "pyannote": {"status": "ready"}}}, None, gpus=[(0, 8000)])
        self.assertEqual((c["engine"], c["reason"]), ("sherpa", "config"))
        c = self.ce({"diarization": {"min_vram_mib": 9000, "pyannote": {"status": "ready"}}}, None, gpus=[(0, 8000)])
        self.assertEqual(c["reason"], "low_vram")

    def test_type_engine_priority(self):
        """〔2.0.0〕命令列 > content_types.<代號>.diarize_engine > diarization.engine > DEFAULTS（範本不參與）。"""
        ce = lambda cfg, req=None, ctype=None: diar.choose_engine(cfg, req, platform="win32", gpus=[(0, 8000)], ctype=ctype)
        c = ce(READY, ctype="panel")                                         # 舊 config（沒有 content_types）→ DEFAULTS：座談 sherpa
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "type", None))
        for code in ("meeting", "course", "interview", "tutorial", "workshop", "requirements", None):
            c = ce(READY, ctype=code)
            self.assertEqual((c["engine"], c["reason"]), ("pyannote", "auto_gpu"), code)
        c = ce(READY, "pyannote", ctype="panel")                              # 命令列優先
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("pyannote", "config", None))
        c = ce(READY, "auto", ctype="panel")
        self.assertEqual((c["engine"], c["reason"]), ("pyannote", "auto_gpu"))
        cfg = {"diarization": {"engine": "sherpa", "pyannote": {"status": "ready"}}, "content_types": {"panel": {}}}
        c = ce(cfg, ctype="panel")                                            # 使用者拿掉類型鍵 → 共用鍵
        self.assertEqual((c["engine"], c["reason"]), ("sherpa", "config"))
        cfg = {"diarization": {"pyannote": {"status": "ready"}}, "content_types": {"course": {"diarize_engine": "pyannote"},
                                                                                     "panel": {"diarize_engine": "auto"}}}
        c = ce(cfg, ctype="course")                                           # 類型鍵指定 pyannote
        self.assertEqual((c["engine"], c["reason"]), ("pyannote", "type"))
        self.assertEqual(ce(cfg, ctype="panel")["reason"], "auto_gpu")        # 類型鍵 auto＝同共用
        c = diar.choose_engine({"content_types": {"course": {"diarize_engine": "pyannote"}}}, None, platform="win32",
                               gpus=[(0, 8000)], ctype="course")              # 類型要 pyannote 但沒裝 → 記退回
        self.assertEqual((c["engine"], c["reason"], c["fallback"]), ("sherpa", "not_installed", "not_installed"))
        c = ce({"diarization": {"engine": "pyannote", "pyannote": {"status": "ready"}}}, ctype="panel")
        self.assertEqual((c["engine"], c["reason"]), ("sherpa", "type"))      # 類型鍵優先於共用鍵
        self.assertEqual(diar.reason_text("type"), "內容類型的預設")

    def test_fake_nvidia_smi(self):
        os.environ["PATH"] = str(_fake_nvsmi(self.tmp, ["0, 3000", "1, 8000"]))
        self.assertEqual(diar.query_gpus(), [(0, 3000), (1, 8000)])
        c = diar.choose_engine(READY, None, platform="win32")
        self.assertEqual((c["engine"], c["gpu_index"]), ("pyannote", 1))

    def test_nvidia_smi_missing_or_failing(self):
        os.environ["PATH"] = str(self.tmp / "empty")
        self.assertIsNone(diar.query_gpus())
        self.assertEqual(diar.choose_engine(READY, None, platform="win32")["reason"], "no_gpu")
        os.environ["PATH"] = str(_fake_nvsmi(self.tmp, ["NVIDIA-SMI has failed"], rc=9))
        self.assertIsNone(diar.query_gpus())


@unittest.skipUnless(V2, "2.0.0 才有")
class PyannoteSubprocess(unittest.TestCase):
    """D-5／D-6：假的子行程。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-py-"))
        self.model = fake_model_dir(self.tmp)
        self.wav = self.tmp / "audio16k.wav"
        self.wav.write_bytes(b"RIFF")
        self.rec = self.tmp / "rec.json"
        self._env = {k: os.environ.get(k) for k in ("FAKE_PYANNOTE_MODE", "FAKE_PYANNOTE_RECORD", "FAKE_PYANNOTE_SEGS")}
        os.environ["FAKE_PYANNOTE_RECORD"] = str(self.rec)

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_py(self, mode="ok", n=None, cfg=None, has_sound=True, python=None):
        os.environ["FAKE_PYANNOTE_MODE"] = mode
        return diar.run_pyannote(self.wav, self.tmp, 600.0, n, 1, cfg or {}, has_sound=has_sound, log=self.logs.append,
                                 python=python or sys.executable, script=FAKE, model_dir=self.model)

    def setUpLogs(self):
        self.logs = []

    def test_ok_env_and_args(self):
        self.setUpLogs()
        segs, info = self.run_py("ok", n=3)
        self.assertEqual(segs, [(0.5, 4.0, 0), (4.2, 8.0, 1), (8.1, 12.0, 0), (12.5, 15.0, 1)])
        self.assertEqual(info["gpu_name"], "Fake GPU")
        rec = json.loads(self.rec.read_text(encoding="utf-8"))
        self.assertEqual(rec["env"], {"HF_HUB_OFFLINE": "1", "PYANNOTE_METRICS_ENABLED": "0", "CUDA_VISIBLE_DEVICES": "1",
                                      "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(rec["argv"][rec["argv"].index("--num-speakers") + 1], "3")
        self.assertTrue(rec["dont_write_bytecode"])
        self.assertFalse((self.tmp / diar.PYANNOTE_OUT).exists(), "子行程輸出讀完要刪掉")
        self.run_py("ok", n=None)
        self.assertNotIn("--num-speakers", json.loads(self.rec.read_text(encoding="utf-8"))["argv"])

    def test_failures(self):
        self.setUpLogs()
        for mode, reason in [("fail:load_failed", "load_failed"), ("fail:cuda_error", "cuda_error"), ("fail:oom", "oom"),
                             ("fail:audio_error", "audio_error"), ("fail:weird", "bad_output"), ("badjson", "bad_output"),
                             ("nojson", "bad_output"), ("wrongshape", "bad_output"), ("empty", "bad_output")]:
            with self.subTest(mode=mode):
                with self.assertRaises(diar.PyannoteFailed) as cm:
                    self.run_py(mode)
                self.assertEqual(cm.exception.reason, reason)

    def test_empty_ok_when_silent(self):
        self.setUpLogs()
        self.assertEqual(self.run_py("empty", has_sound=False)[0], [])

    def test_overlap_trimmed(self):
        self.setUpLogs()
        segs, _ = self.run_py("overlap")
        self.assertEqual(segs, [(0.0, 5.0, 0), (5.0, 9.0, 1), (9.5, 12.0, 0)])

    def test_timeout(self):
        self.setUpLogs()
        cfg = {"diarization": {"pyannote": {"timeout_min_sec": 1, "timeout_factor": 0}}}
        with self.assertRaises(diar.PyannoteFailed) as cm:
            self.run_py("sleep", cfg=cfg)
        self.assertEqual(cm.exception.reason, "timeout")
        self.assertLess(cm.exception.elapsed, 30)

    def test_not_installed(self):
        self.setUpLogs()
        with self.assertRaises(diar.PyannoteFailed) as cm:
            self.run_py("ok", python=self.tmp / "no-python.exe")
        self.assertEqual(cm.exception.reason, "not_installed")
        (self.model / "plda" / "plda.npz").unlink()
        with self.assertRaises(diar.PyannoteFailed) as cm:
            self.run_py("ok")
        self.assertEqual(cm.exception.reason, "not_installed")

    def test_progress_only_and_no_torch(self):
        self.setUpLogs()
        self.run_py("noisy")
        self.assertEqual(self.logs, ["  說話者分離 0%", "  說話者分離 50%", "  說話者分離 100%"])
        self.assertNotIn("torch", sys.modules)                       # D-6：主行程不 import torch


@unittest.skipUnless(V2, "2.0.0 才有")
class RunFallback(unittest.TestCase):
    """diarize.run()：pyannote 失敗退回 sherpa（sherpa 用假的），人數設定照用。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-run-"))
        self.model = fake_model_dir(self.tmp)
        self._sherpa = diar.run_sherpa
        self.sherpa_calls = []

        def fake_sherpa(audio, threshold, num_clusters=-1, log=None):
            self.sherpa_calls.append((threshold, num_clusters))
            return [(0, 10, 0), (10, 11, 1), (11, 20, 2), (20, 21, 3)]
        diar.run_sherpa = fake_sherpa
        self._mode = os.environ.get("FAKE_PYANNOTE_MODE")

    def tearDown(self):
        diar.run_sherpa = self._sherpa
        if self._mode is None:
            os.environ.pop("FAKE_PYANNOTE_MODE", None)
        else:
            os.environ["FAKE_PYANNOTE_MODE"] = self._mode
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_(self, choice, n=None, mode="ok"):
        os.environ["FAKE_PYANNOTE_MODE"] = mode
        self.msgs = []
        return diar.run(choice, np.ones(16000, dtype=np.float32), self.tmp / "a.wav", self.tmp, 30.0, n, 0.9, {},
                        log=self.msgs.append, python=sys.executable, script=FAKE, model_dir=self.model)

    def test_pyannote_ok_no_top_n(self):
        ch = diar.choose_engine(READY, None, platform="win32", gpus=[(0, 8000)])
        r = self.run_(ch, n=2)
        m = r["meta"]
        self.assertEqual((m["engine"], m["device"], m["engine_reason"], m["fallback"], m["cluster_threshold"]),
                         ("pyannote", "cuda:0", "auto_gpu", None, None))
        self.assertEqual((m["setting"], m["n"], m["speakers_raw"], m["top_n_merged_sec"]), (2, 2, 2, 0.0))
        self.assertEqual(m["pyannote"]["version"], "0.0.0")
        self.assertEqual(self.sherpa_calls, [])

    def test_pyannote_fails_falls_back_with_top_n(self):
        ch = diar.choose_engine(READY, None, platform="win32", gpus=[(0, 8000)])
        for mode, reason in [("fail:oom", "oom"), ("badjson", "bad_output")]:
            with self.subTest(mode=mode):
                r = self.run_(ch, n=2, mode=mode)
                m = r["meta"]
                self.assertEqual((m["engine"], m["device"], m["fallback"], m["engine_reason"]), ("sherpa", "cpu", reason, "auto_gpu"))
                self.assertEqual((m["speakers_raw"], m["cluster_threshold"], m["top_n_merged_sec"]), (4, 0.9, 2.0))
                self.assertEqual({k for _, _, k in r["segs"]}, {0, 1})
                self.assertIsNotNone(r["pyannote_sec"])
                self.assertTrue(any("GPU 說話者分離失敗" in x for x in self.msgs))
        self.assertTrue(all(c == (0.9, -1) for c in self.sherpa_calls), "退回時不再傳 num_clusters")

    def test_auto_sherpa_is_not_fallback(self):
        ch = diar.choose_engine({}, None, platform="win32", gpus=[(0, 8000)])
        m = self.run_(ch)["meta"]
        self.assertEqual((m["engine"], m["engine_reason"], m["fallback"], m["setting"]), ("sherpa", "not_installed", None, "auto"))
        self.assertEqual(self.msgs, [])

    def test_requested_pyannote_not_available(self):
        ch = diar.choose_engine(READY, "pyannote", platform="win32", gpus=[(0, 1000)])
        m = self.run_(ch)["meta"]
        self.assertEqual((m["engine"], m["fallback"]), ("sherpa", "low_vram"))
        self.assertTrue(any("可用 1000 MiB" in x for x in self.msgs))
        ch = diar.choose_engine({}, "pyannote", platform="win32", gpus=[(0, 8000)])
        m = self.run_(ch)["meta"]
        self.assertEqual((m["engine"], m["fallback"]), ("sherpa", "not_installed"))
        self.assertEqual(self.msgs, ["  [!] GPU 說話者分離套件未完成安裝，改用 CPU（執行 install.cmd -GpuDiar 補裝）"])


class FakeASR:
    TEXTS = ["預算分配要先跟財務部門確認清楚", "下週三之前把測試環境準備好", "客戶回饋的登入問題已經重現了",
             "伺服器搬遷排在月底的週末進行", "新進同仁的教育訓練由人資安排"]

    def __init__(self):
        self.i = 0

    def transcribe(self, audio):
        t = self.TEXTS[self.i % len(self.TEXTS)] + f"第{self.i}句"
        self.i += 1
        return t


@unittest.skipUnless(V2, "2.0.0 才有")
class TranscribeFlow(unittest.TestCase):
    """transcribe.main() 整個流程（假的 ffmpeg 轉檔、ASR、sherpa、GPU 子行程）。"""

    def setUp(self):
        import soundfile as sf
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-flow-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self.model = fake_model_dir(self.tmp)
        rng = np.random.default_rng(0)
        self.src = self.tmp / "meeting.wav"
        sf.write(str(self.src), (rng.standard_normal(16000 * 30) * 0.1).astype(np.float32), 16000)
        self.saved = {n: getattr(tr, n) for n in ("to_wav", "load_asr")}
        self.saved_d = {n: getattr(diar, n) for n in ("run_sherpa", "gpu_diar_python", "pyannote_model_dir",
                                                      "PYANNOTE_SCRIPT", "query_gpus", "choose_engine")}
        tr.to_wav = lambda src, dst: shutil.copyfile(src, dst)
        tr.load_asr = lambda *a, **k: FakeASR()
        self.sherpa_calls = []

        def fake_sherpa(audio, threshold, num_clusters=-1, log=None):
            self.sherpa_calls.append(threshold)
            return [(0.0, 8.0, 0), (8.0, 9.0, 2), (9.0, 20.0, 1), (20.0, 29.0, 0)]
        diar.run_sherpa = fake_sherpa
        diar.gpu_diar_python = lambda: Path(sys.executable)
        diar.pyannote_model_dir = lambda: self.model
        diar.PYANNOTE_SCRIPT = FAKE
        diar.query_gpus = lambda timeout=10: [(0, 8000)]
        orig = self.saved_d["choose_engine"]
        diar.choose_engine = lambda cfg, req=None, **kw: orig(cfg, req, platform="win32", **kw)
        self._mode = os.environ.pop("FAKE_PYANNOTE_MODE", None)
        self._run_id = os.environ.pop("MMP_RUN_ID", None)

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(tr, n, v)
        for n, v in self.saved_d.items():
            setattr(diar, n, v)
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        os.environ.pop("FAKE_PYANNOTE_MODE", None)
        if self._mode is not None:
            os.environ["FAKE_PYANNOTE_MODE"] = self._mode
        if self._run_id is not None:
            os.environ["MMP_RUN_ID"] = self._run_id
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, *extra, cfg=None, mode="ok"):
        (self.home / "config.json").write_text(json.dumps(cfg if cfg is not None else READY), encoding="utf-8")
        os.environ["FAKE_PYANNOTE_MODE"] = mode
        out = self.tmp / f"out{len(list(self.tmp.glob('out*')))}"
        argv = sys.argv
        sys.argv = ["transcribe.py", str(self.src), "--out-dir", str(out), "--no-correct", "--no-corrections",
                    "--backend", "ct2", "--device", "cpu", *extra]
        so, se = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(so), contextlib.redirect_stderr(se):
                tr.main()
        finally:
            sys.argv = argv
        self.err = se.getvalue()
        res = json.loads(so.getvalue().strip().splitlines()[-1])
        doc = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
        md = (out / "transcript.md").read_text(encoding="utf-8")
        ev = runlog.read_events(out / runlog.LOG_NAME)
        return res, doc["meta"], md, ev, out

    @staticmethod
    def info(ev):
        return [e for e in ev if e["event"] == "info"][0]

    @staticmethod
    def cp(ev, name):
        return [e for e in ev if e["event"] == "checkpoint" and e["name"] == name]

    def test_pyannote_path(self):
        res, meta, md, ev, out = self.main("--type", "course")
        self.assertEqual((res["content_type"], res["diarize_engine"], res["diarize_fallback"]), ("course", "pyannote", None))
        d = meta["diarization"]
        self.assertEqual((d["engine"], d["device"], d["engine_reason"], d["setting"], d["speakers"]),
                         ("pyannote", "cuda:0", "auto_gpu", "auto", 2))
        self.assertEqual((meta["content_type"], meta["template"]), ("course", None))
        self.assertEqual([s["speaker"] for s in meta["speaker_stats"]], ["S1", "S2"])
        self.assertIn("\n- 講者發言時間：S1 ", md)
        self.assertIn("[2/4] 說話者分離（pyannote／GPU）", self.err)
        dz = self.cp(ev, "diarize")[0]
        self.assertEqual((dz["engine"], dz["device"], dz["speakers_raw"], dz["speakers"]), ("pyannote", "cuda:0", 2, 2))
        inf = self.info(ev)
        self.assertEqual((inf["content_type"], inf["speakers_setting"], inf["diarize_engine"], inf["diarize_device"],
                          inf["diarize_engine_reason"]), ("course", "auto", "pyannote", "cuda:0", "auto_gpu"))
        self.assertNotIn("cluster_threshold", inf)                 # sherpa 才有
        self.assertFalse((out / "audio16k.wav").exists())
        self.assertFalse((out / diar.PYANNOTE_OUT).exists())
        self.assertNotIn("torch", sys.modules)

    def test_fallback_still_transcribes(self):
        """D-5：子行程失敗 → sherpa（類型門檻、保留前 N 位）→ 轉寫成功。"""
        cfg = {"diarization": {"pyannote": {"status": "ready"}}, "content_types": {"panel": {"cluster_threshold": 0.8}}}
        # 〔2.0.0〕座談預設 sherpa；這裡拿掉座談的引擎鍵（＝用共用的 auto）才會走 pyannote
        res, meta, md, ev, out = self.main("--type", "panel", "--speakers", "2", cfg=cfg, mode="fail:cuda_error")
        self.assertEqual((res["diarize_engine"], res["diarize_fallback"]), ("sherpa", "cuda_error"))
        self.assertEqual(self.sherpa_calls, [0.8])                  # 座談預設門檻 0.8
        d = meta["diarization"]
        self.assertEqual((d["engine"], d["fallback"], d["setting"], d["n"], d["speakers_raw"], d["speakers"],
                          d["cluster_threshold"]), ("sherpa", "cuda_error", 2, 2, 3, 2, 0.8))
        self.assertEqual(d["top_n_merged_sec"], 1.0)
        self.assertIn("GPU 說話者分離失敗（CUDA 錯誤），改用 CPU", self.err)
        dz = self.cp(ev, "diarize")[0]
        self.assertEqual((dz["engine"], dz["fallback"], dz["device"]), ("sherpa", "cuda_error", "cpu"))
        self.assertIn("pyannote_sec", dz)
        inf = self.info(ev)
        self.assertEqual((inf["diarize_fallback"], inf["cluster_threshold"], inf["speakers_setting"], inf["speakers_raw"]),
                         ("cuda_error", 0.8, 2, 3))
        self.assertGreater(res["segments"], 0)

    def test_sherpa_threshold_by_type_and_cli(self):
        cfg = {"diarization": {"engine": "sherpa"}}
        self.main(cfg=cfg)                                            # 預設類型 meeting → 共用 0.9
        self.main("--type", "course", cfg=cfg)                        # 課程 1.0
        self.main("--type", "course", "--cluster-threshold", "0.8", cfg=cfg)
        cfg2 = {"diarization": {"engine": "sherpa", "cluster_threshold": 0.85}, "content_types": {"panel": {}}}
        self.main("--type", "panel", cfg=cfg2)                        # 使用者把座談的鍵拿掉 → 共用鍵 0.85
        self.main("--type", "course", cfg=cfg2)                       # 區塊在、沒有 course → 共用鍵
        self.assertEqual(self.sherpa_calls, [0.9, 1.0, 0.8, 0.85, 0.85])
        res, meta, md, ev, out = self.main("--diarize-engine", "sherpa")
        self.assertEqual((meta["diarization"]["engine_reason"], meta["diarization"]["fallback"]), ("config", None))
        self.assertEqual(meta["content_type"], "meeting")

    def test_panel_defaults_to_sherpa(self):
        """〔2.0.0〕座談在 GPU 可用時也用 sherpa：engine_reason type、不算退回；命令列 --diarize-engine 優先；其他類型照舊 pyannote。"""
        res, meta, md, ev, out = self.main("--type", "panel")
        d = meta["diarization"]
        self.assertEqual((res["diarize_engine"], res["diarize_fallback"]), ("sherpa", None))
        self.assertEqual((d["engine"], d["engine_reason"], d["fallback"], d["cluster_threshold"]), ("sherpa", "type", None, 0.8))
        self.assertEqual(self.sherpa_calls, [0.8])
        self.assertIn("[2/4] 說話者分離（sherpa／CPU）", self.err)
        inf = self.info(ev)
        self.assertEqual((inf["diarize_engine"], inf["diarize_engine_reason"]), ("sherpa", "type"))
        self.assertNotIn("diarize_fallback", inf)                   # None 欄位不寫（RunLog.event）
        res, meta, md, ev, out = self.main("--type", "panel", "--diarize-engine", "pyannote")
        self.assertEqual((meta["diarization"]["engine"], meta["diarization"]["engine_reason"]), ("pyannote", "config"))
        res, meta, md, ev, out = self.main("--type", "workshop")
        self.assertEqual((meta["diarization"]["engine"], meta["diarization"]["engine_reason"]), ("pyannote", "auto_gpu"))

    def test_skip(self):
        res, meta, md, ev, out = self.main("--no-diarize", "--type", "course")
        d = meta["diarization"]
        self.assertEqual((d["engine"], d["setting"], d["speakers"]), ("none", "skip", 1))
        self.assertEqual(res["diarize_engine"], "none")
        self.assertNotIn("講者發言時間", md)
        self.assertEqual(self.cp(ev, "diarize"), [])                # 1.2.2 同：略過時沒有 diarize 檢查點
        self.assertEqual(self.info(ev)["speakers_setting"], "skip")
        self.assertEqual(self.sherpa_calls, [])

    def test_type_errors_exit_2(self):
        for extra in (["--type", "lecture"],):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as cm:
                with contextlib.redirect_stderr(io.StringIO()):
                    self.main(*extra)
            self.assertEqual(cm.exception.code, 2)

    def test_log_has_no_transcript_or_child_stderr(self):
        """L-1（分離部分）：run_log／runs.jsonl 不含逐字稿 6 字片段、子行程 stderr 的內容（假權杖、假逐字稿、路徑）。"""
        res, meta, md, ev, out = self.main(mode="noisy")
        blob = (out / runlog.LOG_NAME).read_text(encoding="utf-8")
        runs = self.home / "logs" / runlog.RUNS_NAME
        blob += runs.read_text(encoding="utf-8") if runs.exists() else ""
        self.assertNotRegex(blob, r"hf_[A-Za-z0-9]{20,}")
        self.assertNotIn("C:\\\\secret", blob)
        for t in FakeASR.TEXTS + ["在會議室討論預算分配的事情"]:
            for i in range(0, len(t) - 6):
                self.assertNotIn(t[i:i + 6], blob, "log 含逐字稿片段")
        self.assertNotIn("hf_FAKE", self.err)                       # 子行程 stderr 只轉印進度

    def test_runs_summary_fields(self):
        res, meta, md, ev, out = self.main("--type", "interview", mode="fail:oom")
        row = [json.loads(x) for x in (self.home / "logs" / runlog.RUNS_NAME).read_text(encoding="utf-8").splitlines()][-1]
        self.assertEqual((row["content_type"], row["template"], row["diarize_engine"], row["diarize_fallback"], row["speakers_raw"]),
                         ("interview", None, "sherpa", "oom", 3))
        self.assertEqual(runlog.summary_rows([row])[0]["分離"], "sherpa*")


@unittest.skipUnless(V2, "2.0.0 才有")
class Settings(unittest.TestCase):
    """transcribe.resolve_settings()：命令列 > 範本 > content_types.<代號> > 共用鍵 > DEFAULTS（規格 §6.3）。"""

    def setUp(self):
        self._tpl = sys.modules.get("templates")

    def tearDown(self):
        if self._tpl is None:
            sys.modules.pop("templates", None)
        else:
            sys.modules["templates"] = self._tpl

    @staticmethod
    def args(**kw):
        d = dict(template=None, content_type=None, no_diarize=False, speakers=-1, cluster_threshold=None, scene=None,
                 max_frames=None)
        d.update(kw)
        return Namespace(**d)

    def fake_templates(self, tpl: dict | None, invalid=None):
        m = types.ModuleType("templates")

        class TemplateInvalid(ValueError):
            def __init__(self, reason, message):
                super().__init__(message)
                self.reason, self.message = reason, message

        def load(code):
            if invalid:
                raise TemplateInvalid(*invalid)
            return dict(tpl, code=code)
        m.TemplateInvalid, m.load = TemplateInvalid, load
        sys.modules["templates"] = m

    def test_defaults(self):
        r = tr.resolve_settings(self.args(), {}, set())
        self.assertEqual((r["content_type"], r["speakers_setting"], r["cluster_threshold"], r["scene"], r["max_frames"]),
                         ("meeting", "auto", 0.9, 0.3, 60))
        r = tr.resolve_settings(self.args(content_type="tutorial"), {}, set())
        self.assertEqual((r["cluster_threshold"], r["scene"]), (0.9, 0.1))
        r = tr.resolve_settings(self.args(content_type="tutorial", scene=0.25, max_frames=5), {}, {"--scene", "--max-frames"})
        self.assertEqual((r["scene"], r["max_frames"]), (0.25, 5))
        r = tr.resolve_settings(self.args(), {"content_type": {"default": "panel"}}, set())
        self.assertEqual((r["content_type"], r["cluster_threshold"]), ("panel", 0.8))
        r = tr.resolve_settings(self.args(), {"content_type": {"default": "lecture"}}, set())
        self.assertEqual(r["content_type"], "meeting")
        self.assertIn("lecture", r["type_note"])

    def test_speakers(self):
        self.assertEqual(tr.resolve_settings(self.args(speakers=3), {}, {"--speakers"})["speakers_setting"], 3)
        self.assertEqual(tr.resolve_settings(self.args(speakers=-1), {}, {"--speakers"})["speakers_setting"], "auto")
        self.assertEqual(tr.resolve_settings(self.args(no_diarize=True), {}, set())["speakers_setting"], "skip")

    def test_template(self):
        self.fake_templates({"base": "course", "name": "讀書會", "speakers": 2, "cluster_threshold": 0.95,
                             "prompt_chars": 10, "prompt_truncated": False})
        r = tr.resolve_settings(self.args(template="book"), {}, set())
        self.assertEqual((r["content_type"], r["speakers_setting"], r["cluster_threshold"]), ("course", 2, 0.95))
        r = tr.resolve_settings(self.args(template="book", speakers=4, cluster_threshold=1.1), {},
                                {"--speakers", "--cluster-threshold"})                   # 命令列優先
        self.assertEqual((r["speakers_setting"], r["cluster_threshold"]), (4, 1.1))
        r = tr.resolve_settings(self.args(template="book", content_type="course"), {}, set())   # 相同 → 可以
        self.assertEqual(r["content_type"], "course")
        with self.assertRaises(tr.SettingsError):
            tr.resolve_settings(self.args(template="book", content_type="meeting"), {}, set())
        self.fake_templates({"base": "meeting", "speakers": "skip", "cluster_threshold": None})
        self.assertEqual(tr.resolve_settings(self.args(template="x"), {}, set())["speakers_setting"], "skip")
        self.fake_templates(None, invalid=("unknown_key", "不認得的設定 model"))
        with self.assertRaises(tr.SettingsError) as cm:
            tr.resolve_settings(self.args(template="bad"), {}, set())
        self.assertIn("不認得的設定 model", str(cm.exception))

    def test_template_module_missing(self):
        sys.modules["templates"] = None                            # import 失敗（I-1 還沒有 templates.py）
        with self.assertRaises(tr.SettingsError):
            tr.resolve_settings(self.args(template="x"), {}, set())


@unittest.skipUnless(V2, "2.0.0 才有")
class ContentTypes(unittest.TestCase):
    def test_codes_and_labels(self):
        self.assertEqual(content_types.CODES, ("meeting", "course", "interview", "tutorial", "panel", "workshop", "requirements"))
        self.assertEqual(content_types.label_of("course"), "課程（含演講／專題分享）")
        self.assertEqual(content_types.noun_of("meeting"), "會議摘要")
        self.assertTrue(all(t["diarization"] == "auto" for t in content_types.TYPES.values()))
        self.assertEqual([c for c, t in content_types.TYPES.items() if t["skip_in_prompt"]], ["course", "tutorial"])

    def test_table_matches_defaults(self):
        """TYPES 的 cluster_threshold／scene／diarize_engine 與 common.DEFAULTS 的 content_types 一致（數值以 config 為準）。"""
        for code, t in content_types.TYPES.items():
            for key in ("cluster_threshold", "scene", "diarize_engine"):
                want = common.type_setting({}, code, key)
                self.assertEqual(t[key] if t[key] is not None else common.setting({}, common.TYPE_SETTING_SHARED[key]),
                                 want, (code, key))

    def test_resolve(self):
        self.assertEqual(content_types.resolve_type(None, None, {}), ("meeting", None))
        self.assertEqual(content_types.resolve_type("panel", None, {}), ("panel", None))
        self.assertEqual(content_types.resolve_type(None, "course", {}), ("course", None))
        with self.assertRaises(content_types.TypeChoiceError):
            content_types.resolve_type("lecture", None, {})
        with self.assertRaises(content_types.TypeChoiceError):
            content_types.resolve_type("meeting", "course", {})


@unittest.skipUnless(V2, "2.0.0 才有")
class TypeSetting(unittest.TestCase):
    def test_priority(self):
        ts = common.type_setting
        self.assertEqual([ts({}, c, "cluster_threshold") for c in content_types.CODES], [0.9, 1.0, 0.9, 0.9, 0.8, 0.9, 0.9])
        self.assertEqual([ts({}, c, "scene") for c in content_types.CODES], [0.3, 0.3, 0.3, 0.1, 0.3, 0.3, 0.3])
        cfg = {"diarization": {"cluster_threshold": 0.7}, "keyframes": {"scene": 0.4}}     # 沒有 content_types 區塊
        self.assertEqual((ts(cfg, "meeting", "cluster_threshold"), ts(cfg, "course", "cluster_threshold")), (0.7, 1.0))
        cfg["content_types"] = {"course": {"cluster_threshold": 1.05, "model": "x"}, "workshop": {"scene": 0.2}}
        self.assertEqual(ts(cfg, "course", "cluster_threshold"), 1.05)
        self.assertEqual(ts(cfg, "panel", "cluster_threshold"), 0.7)                     # 區塊在、沒有 panel → 共用鍵
        self.assertEqual((ts(cfg, "workshop", "scene"), ts(cfg, "tutorial", "scene")), (0.2, 0.4))
        self.assertEqual(ts(cfg, None, "scene"), 0.4)
        with self.assertRaises(KeyError):
            ts(cfg, "course", "model")

    def test_diarize_engine_key(self):
        """〔2.0.0〕diarize_engine：content_types.<代號> → diarization.engine → DEFAULTS；type_entry() 只看類型鍵。"""
        ts, te = common.type_setting, common.type_entry
        self.assertEqual([ts({}, c, "diarize_engine") for c in content_types.CODES],
                         ["auto", "auto", "auto", "auto", "sherpa", "auto", "auto"])
        self.assertEqual((te({}, "panel", "diarize_engine"), te({}, "course", "diarize_engine")), ("sherpa", None))
        cfg = {"diarization": {"engine": "pyannote"}, "content_types": {"course": {"cluster_threshold": 1.0}}}
        self.assertEqual((ts(cfg, "panel", "diarize_engine"), te(cfg, "panel", "diarize_engine")), ("pyannote", None))
        self.assertEqual(common.DEFAULTS["content_types"]["panel"], {"cluster_threshold": 0.8, "diarize_engine": "sherpa"})


@unittest.skipUnless(V2, "2.0.0 才有")
class NoTorchImport(unittest.TestCase):
    def test_main_runtime_modules_do_not_import_torch(self):
        """D-6：主 runtime 的模組（transcribe、diarize）不 import torch／pyannote。"""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import transcribe, diarize; "
                "print(sorted(m for m in sys.modules if m.split('.')[0] in ('torch', 'pyannote')))")
        p = subprocess.run([sys.executable, "-B", "-c", code, str(_testenv.SCRIPTS)], capture_output=True, text=True,
                           encoding="utf-8", env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()
