"""自動語意校正（auto_correct.py；規格 §6）的單元測試。不呼叫任何模型：
CLI 以假的 subprocess 結果、API 以假的 SDK 模組、整體流程以假的呼叫函式驗證。

涵蓋：provider: auto 三種情境、C2 驗證、C5 拆段、C6 錯誤路徑、C7 結構化輸出的解析、
條件式自動寫入（mode off 與現行相同、五個條件、撤銷）。
〔2.2.0〕參考資料（規格 2.2.0 §11.2、§11.4）：四個呼叫器附圖、送圖失敗的退回（四通道各一）、重試與 STOP_ALL、
沒有參考資料時與 2.1.0 逐位元相同（獨立行程跑 2.1.0 與 2.2.0 比對）、帶截圖／說明檔／文件的整體流程與紀錄。
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path

import _testenv  # noqa: F401
import auto_correct as ac
import common
import corrections


def para(t, s, text):
    return f"**[{t}] {s}**：{text}"


MD_HEAD = ["# 逐字稿：demo.wav", "", "- 長度：00:10:00　講者數：2　ASR：turbo @ openvino/NPU", "- 處理耗時：60s（RTF 0.10）", ""]


def write_out(d: Path, paras: list, duration=600.0, frames=None, hotwords="Kafka, Redis"):
    body = []
    for p in paras:
        if isinstance(p, str):
            body += [p, ""]
        else:
            body += [para(*p), ""]
    (d / "transcript.md").write_text("\n".join(MD_HEAD + body), encoding="utf-8")
    meta = {"version": "1.1.0", "source": "demo.wav", "duration": duration, "model": "turbo", "device": "openvino/NPU",
            "hotwords": hotwords, "corrections_applied": {"酷伯內蒂斯→Kubernetes": 2}, "opencc_keep_applied": {"權限": 1}}
    (d / "transcript.json").write_text(json.dumps({"meta": meta, "segments": []}, ensure_ascii=False), encoding="utf-8")


def section(user: str, name: str) -> str:
    m = re.search(rf"## {name}[^\n]*\n(.*?)(?=\n## |\Z)", user, re.S)
    return m.group(1).strip() if m else ""


class FakeModel:
    """依「要校正的逐字稿」產生輸出：fix 是 {原文: 修正}，每次出現都標成 {原文→修正}。"""

    def __init__(self, fix=None, terms=None, script=None, model="claude-sonnet-5-5"):
        self.fix = fix or {}
        self.terms = terms or []
        self.script = list(script or [])    # 依序回傳的特殊結果（函式或 dict），用完就回正常輸出
        self.calls = []
        self.model = model

    def __call__(self, be, system, user, timeout, schema=None):
        self.calls.append({"schema": schema is not None, "user": user})
        if schema:
            return ac._ok(json.dumps({"terms": self.terms}), {"terms": self.terms}, {"input": 10}, self.model)
        if self.script:
            r = self.script.pop(0)
            if callable(r):
                return r(user)
            if r is not None:
                return r
        body = section(user, "要校正的逐字稿")
        for a, b in self.fix.items():
            body = body.replace(a, "{" + a + "→" + b + "}")
        return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {"input": 100, "output": 90}, self.model, 0.01)


class Base(unittest.TestCase):
    def setUp(self):
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = Path(tempfile.mkdtemp(prefix="mmp-ac-home-"))
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        # 〔2.2.0〕輸出資料夾放在自己的上層資料夾裡（refs.py 會看「媒體旁」＝輸出資料夾的上一層，不要看到系統暫存區）
        self.parent = Path(tempfile.mkdtemp(prefix="mmp-ac-out-"))
        self.out = self.parent / "demo_minutes"
        self.out.mkdir()
        self._callers = dict(ac.CALLERS)
        self._select = ac.select_backend
        self._wait = ac.RETRY_WAIT
        ac.RETRY_WAIT = 0

    def tearDown(self):
        ac.CALLERS.clear()
        ac.CALLERS.update(self._callers)
        ac.select_backend = self._select
        ac.RETRY_WAIT = self._wait
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.parent, ignore_errors=True)

    def use(self, fake, provider="claude", channel="cli", model="sonnet", effort="high"):
        ac.CALLERS[(provider, channel)] = fake
        ac.select_backend = lambda cfg, req: {"provider": provider, "channel": channel, "exe": "x",
                                              "cli_version": "fake 1.0", "auth": "subscription", "note": None,
                                              "model": model, "effort": effort, "model_api": model}

    def cfg(self, **corr):
        c = {"correction": dict(corr)}
        return c


# ---------------------------------------------------------------- 選項與偵測
class Options(unittest.TestCase):
    def test_infer_and_conflict(self):
        self.assertEqual(ac.resolve_request({}, model="gpt-6.1-sol")["provider"], "openai")
        self.assertEqual(ac.resolve_request({}, model="opus")["provider"], "claude")
        self.assertEqual(ac.resolve_request({}, model="claude-sonnet-5-5")["provider"], "claude")
        self.assertEqual(ac.resolve_request({})["provider"], "auto")
        with self.assertRaises(ac.OptionError):
            ac.resolve_request({}, provider="claude", model="gpt-6.1-sol")
        with self.assertRaises(ac.OptionError):
            ac.resolve_request({}, provider="claude", effort="xhigh")
        with self.assertRaises(ac.OptionError):
            ac.resolve_request({}, model="mystery-model")
        self.assertEqual(ac.resolve_request({}, provider="openai", effort="xhigh")["effort"], "xhigh")

    def test_cli_flags_and_shortcuts(self):
        ap = argparse.ArgumentParser()
        ac.add_cli_options(ap, with_switch=True)
        a = ap.parse_args(["--claude"])
        self.assertEqual((a.correct, a.correct_provider), (True, "claude"))
        a = ap.parse_args(["--openai", "--correct-model", "gpt-6.1-terra"])
        self.assertEqual((a.correct, a.correct_provider, a.correct_model), (True, "openai", "gpt-6.1-terra"))
        a = ap.parse_args(["--claude", "--no-correct"])            # 後出現的為準
        self.assertIs(a.correct, False)
        a = ap.parse_args([])
        self.assertIsNone(a.correct)
        for old in (["--claude-model", "opus"], ["--no-claude"]):  # 舊名不保留（1.1.0 起）
            with self.assertRaises(SystemExit):
                ap.parse_args(old)


class SelectBackend(unittest.TestCase):
    """provider: auto 的三種情境（兩家都有／只有 claude／只有 codex），加上兩家都沒有、Codex 未登入、明確指定。"""

    def setUp(self):
        self._find, self._auth = ac.find_cli, ac.codex_auth
        self.have = {}
        self.login = "chatgpt"
        ac.find_cli = lambda name, path=None: (Path(f"/bin/{name}"), f"{name} 9.9") if self.have.get(name) else (None, None)
        ac.codex_auth = lambda exe: self.login

    def tearDown(self):
        ac.find_cli, ac.codex_auth = self._find, self._auth

    def sel(self, **req):
        return ac.select_backend({}, ac.resolve_request({}, **req))

    def test_both_installed_defaults_to_openai(self):
        self.have = {"claude": True, "codex": True}
        be = self.sel()
        self.assertEqual((be["provider"], be["model"], be["effort"]), ("openai", "gpt-6.1-sol", "low"))   # 1.1.0 起的 OpenAI 預設
        self.assertIsNone(be.get("fallback"))

    def test_only_claude(self):
        self.have = {"claude": True}
        be = self.sel()
        self.assertEqual((be["provider"], be["model"], be["effort"]), ("claude", "opus", "medium"))   # 1.1.0 起的 Claude 預設
        self.assertEqual(be["fallback"], "codex_not_found")
        self.assertIn("找不到 codex", be["note"])

    def test_only_codex(self):
        self.have = {"codex": True}
        be = self.sel()
        self.assertEqual((be["provider"], be["model"], be["effort"]), ("openai", "gpt-6.1-sol", "low"))
        self.assertIsNone(be["note"])

    def test_codex_not_logged_in_falls_back_to_claude(self):
        self.have, self.login = {"claude": True, "codex": True}, "none"
        be = self.sel()
        self.assertEqual((be["provider"], be["model"]), ("claude", "opus"))
        self.assertEqual(be["fallback"], "codex_not_logged_in")
        self.assertIn("codex login", be["note"])

    def test_explicit_openai_not_logged_in_does_not_fall_back(self):
        self.have, self.login = {"claude": True, "codex": True}, "none"
        be = self.sel(provider="openai")
        self.assertEqual((be["skip"], be["provider"]), ("auth_failed", "openai"))

    def test_explicit_claude_with_both(self):
        self.have = {"claude": True, "codex": True}
        be = self.sel(provider="claude")
        self.assertEqual((be["provider"], be["model"]), ("claude", "opus"))
        self.assertIsNone(be.get("fallback"))

    def test_neither(self):
        self.assertEqual(self.sel()["skip"], "cli_not_found")

    def test_codex_not_logged_in(self):
        self.have, self.login = {"codex": True}, "none"
        be = self.sel()
        self.assertEqual(be["skip"], "auth_failed")
        self.assertIn("codex login", be["message"])

    def test_codex_api_key_login_warns(self):
        self.have, self.login = {"codex": True}, "api_key"
        self.assertIn("API 金鑰", self.sel()["note"])

    def test_explicit_claude_does_not_fall_back(self):
        self.have = {"codex": True}
        be = self.sel(provider="claude")
        self.assertEqual((be["skip"], be["provider"]), ("cli_not_found", "claude"))

    def test_explicit_openai_with_both(self):
        self.have = {"claude": True, "codex": True}
        self.assertEqual(self.sel(provider="openai")["provider"], "openai")
        self.assertEqual(self.sel(model="gpt-6.1-terra")["model"], "gpt-6.1-terra")

    def test_api_channel(self):
        keep = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
        try:
            self.assertEqual(self.sel(channel="api")["skip"], "api_key_missing")
            self.assertEqual(self.sel(channel="api", provider="openai")["skip"], "api_key_missing")
            os.environ["OPENAI_API_KEY"] = "test-placeholder-not-a-key"
            be = self.sel(channel="api")                       # 只有 OpenAI 金鑰
            self.assertEqual((be["provider"], be["model_api"], be["effort"]), ("openai", "gpt-6.1-sol", "low"))
            self.assertIsNone(be.get("fallback"))
            self.assertEqual(self.sel(channel="api", provider="claude")["skip"], "api_key_missing")   # 明確指定不換家
            os.environ["ANTHROPIC_API_KEY"] = "test-placeholder-not-a-key"
            be = self.sel(channel="api")                       # 〔1.1.0〕兩把都有 → OpenAI 優先
            self.assertEqual((be["provider"], be["model_api"], be["effort"]), ("openai", "gpt-6.1-sol", "low"))
            self.assertIsNone(be.get("fallback"))
            be = self.sel(channel="api", provider="claude")
            self.assertEqual((be["provider"], be["model_api"]), ("claude", "claude-opus-5-5"))     # §6.13.2 對照表（1.1.0 起預設 opus）
            self.assertIsNone(be.get("fallback"))
            self.assertEqual(self.sel(channel="api", model="sonnet")["model_api"], "claude-sonnet-5-5")
            self.assertEqual(self.sel(channel="api", model="claude-opus-5-5")["model_api"], "claude-opus-5-5")
        finally:
            for k, v in keep.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_find_cli_bad_path(self):
        ac.find_cli = self._find
        p, v = ac.find_cli("claude", str(Path(tempfile.gettempdir()) / "no-such-claude.exe"))
        self.assertIsNone(p)      # C6：cli_path 指向不存在的路徑 → 找不到（不再往下找）


class Estimate(unittest.TestCase):
    """〔1.1.0〕開始前的預估：每塊秒數依 1.1.0 實測校正；單塊不再印「2～2 分鐘」。"""

    MEASURED = {   # 規格附錄 D.7.2、D.8.1、D.9.1：(provider, model) → {塊數: [實際秒數, …]}
        ("claude", "opus"): {1: [44], 6: [415, 366]},
        ("claude", "sonnet"): {1: [40, 44], 6: [224]},
        ("openai", "gpt-6.1-sol"): {1: [64, 66], 6: [558]},
    }

    def be(self, provider, model):
        return {"provider": provider, "model": model}

    def test_fmt_span(self):
        self.assertEqual(ac.fmt_span(55, 65), "約 1 分鐘")                 # 單塊：上下限相同只寫一個數
        self.assertEqual(ac.fmt_span(35, 55), "不到 1 分鐘")
        self.assertEqual(ac.fmt_span(348, 411), "約 6～7 分鐘")
        self.assertEqual(ac.fmt_span(85, 95), "約 1～2 分鐘")
        self.assertEqual(ac.fmt_span(10, 70), "約 1 分鐘")                 # 下限不到 1 → 1
        self.assertEqual(ac.fmt_span(570, 570), "約 10 分鐘")              # 9.5 → 10（四捨五入，同入口）

    def test_estimates_cover_measured(self):
        for (p, m), runs in self.MEASURED.items():
            for n, actual in runs.items():
                lo, hi = ac.estimate_sec(self.be(p, m), n)
                for sec in actual:
                    self.assertLessEqual(abs(lo - sec) / sec, 0.5, (p, m, n, sec))   # C3：預估誤差 ≤ ±50%
                    self.assertLessEqual(abs(hi - sec) / sec, 0.5, (p, m, n, sec))
                if n > 1:   # 長會議：實際分鐘落在印出的範圍內
                    a, b = round(lo / 60), round(hi / 60)
                    for sec in actual:
                        self.assertTrue(a - 0.5 <= sec / 60 <= b + 0.5, (p, m, sec, ac.fmt_span(lo, hi)))

    def test_m3_text_and_entry_overlap(self):
        """M3（79.3 分鐘、6 塊）：印出的文字；範圍和入口選單的每小時數字（規格 D.9.2）× 長度重疊。"""
        entry = {("claude", "opus"): (4.6, 5.2), ("claude", "sonnet"): (2.8, 4.6), ("openai", "gpt-6.1-sol"): (6.7, 7.0)}
        text = {("claude", "opus"): "約 6～7 分鐘", ("claude", "sonnet"): "約 4～5 分鐘",
                ("openai", "gpt-6.1-sol"): "約 9～10 分鐘"}
        for key, (rlo, rhi) in entry.items():
            lo, hi = ac.estimate_sec(self.be(*key), 6)
            self.assertEqual(ac.fmt_span(lo, hi), text[key])
            self.assertTrue(lo / 60 <= rhi * 79.3 / 60 and rlo * 79.3 / 60 <= hi / 60, key)

    def test_model_ids_and_fallback(self):
        self.assertEqual(ac._sec_per_chunk(self.be("claude", "claude-opus-5-5")), ac.SEC_PER_CHUNK["opus"])
        self.assertEqual(ac._sec_per_chunk(self.be("claude", "haiku")), ac.SEC_PER_CHUNK_FALLBACK["claude"])
        self.assertEqual(ac._sec_per_chunk(self.be("openai", "gpt-6.1-terra")), ac.SEC_PER_CHUNK_FALLBACK["openai"])
        self.assertEqual(ac.estimate_sec(self.be("claude", "opus"), 1), (55, 65))   # 單塊不加用字表


# ---------------------------------------------------------------- 切塊與驗證
class Chunking(unittest.TestCase):
    def test_parse_and_chunks(self):
        md = "\n".join(MD_HEAD + [para("00:00:01", "S1", "甲" * 30), "", "> 🖼 [00:00:05] 畫面：`f.jpg`", "",
                                  para("00:00:09", "S2", "乙" * 30), "", para("00:00:20", "S1", "丙" * 30), ""])
        head, items = ac.parse_md(md)
        self.assertEqual(head[0], "# 逐字稿：demo.wav")
        self.assertEqual([i["kind"] for i in items], ["para", "line", "para", "para"])
        paras = [i for i in items if i["kind"] == "para"]
        chunks = ac.make_chunks(ac.make_units(paras, 50), 50)
        self.assertEqual([len(c) for c in chunks], [1, 1, 1])
        chunks = ac.make_chunks(ac.make_units(paras, 60), 60)
        self.assertEqual([len(c) for c in chunks], [2, 1])

    def test_huge_paragraph_split_at_sentence(self):
        text = "一二三四五。" * 20 + "六七八九十？" * 20
        units = ac.make_units([{"time": "00:00:01", "spk": "S1", "text": text}], 100)
        self.assertGreater(len(units), 1)
        self.assertEqual("".join(u["text"] for u in units), text)
        self.assertTrue(all(u["time"] == "00:00:01" for u in units))
        self.assertTrue(all(u["text"][-1] in "。？" for u in units[:-1]))


class Validate(unittest.TestCase):
    units = [{"time": "00:00:01", "spk": "S1", "text": "我們用卡夫卡做佇列，延持大約兩秒。"},
             {"time": "00:00:09", "spk": "S2", "text": "好的那退閉策略呢？我覺得要指數退避。"}]

    def out(self, *paras):
        return "<transcript>\n" + "\n\n".join(paras) + "\n</transcript>"

    def test_ok_with_marks_and_split(self):
        ok, outs, err = ac.validate(self.units, self.out(
            para("00:00:01", "S1", "我們用{卡夫卡→Kafka}做佇列，{延持→延遲}大約兩秒。"),
            para("00:00:09", "S2", "好的那{退閉→退避}策略呢？"), para("00:00:09", "S?", "我覺得要指數退避。")))
        self.assertTrue(ok, err)
        self.assertEqual(len(outs[1]), 2)                          # C5：拆段歸屬原段
        self.assertEqual(outs[1][1][1], "S?")

    def test_unmarked_change_rejected(self):
        ok, _, err = ac.validate(self.units, self.out(
            para("00:00:01", "S1", "我們用Kafka做佇列，延持大約兩秒。"), para("00:00:09", "S2", self.units[1]["text"])))
        self.assertFalse(ok)
        self.assertIn("content mismatch", err)

    def test_header_changes_rejected(self):
        for bad in (para("00:00:09", "S3", self.units[1]["text"]),           # 改講者
                    para("00:00:10", "S2", self.units[1]["text"])):           # 改時間
            ok, _, err = ac.validate(self.units, self.out(para("00:00:01", "S1", self.units[0]["text"]), bad))
            self.assertFalse(ok, err)
        ok, _, err = ac.validate(self.units, self.out(para("00:00:01", "S1", self.units[0]["text"])))
        self.assertFalse(ok)
        self.assertIn("missing", err)
        ok, _, _ = ac.validate(self.units, self.out(para("00:00:01", "S1", "我們用卡夫卡做佇列，"),
                                                    para("00:00:05", "S?", "延持大約兩秒。"),
                                                    para("00:00:09", "S2", self.units[1]["text"])))
        self.assertFalse(ok)                                          # S? 的時間必須等於原段首

    def test_last_block_wins_and_noop_marks(self):
        first = self.out(para("00:00:01", "S1", "亂寫"))
        second = self.out(para("00:00:01", "S1", "我們用{卡夫卡→卡夫卡}做佇列，延持大約兩秒。"),
                          para("00:00:09", "S2", self.units[1]["text"]))
        ok, outs, err = ac.validate(self.units, first + "\nWait — I need to correct my output\n" + second)
        self.assertTrue(ok, err)
        self.assertNotIn("→", outs[0][0][2])                         # {a→a} 換回 a

    def test_no_block_and_prefix_text(self):
        self.assertFalse(ac.validate(self.units, "沒有區塊")[0])
        self.assertFalse(ac.validate(self.units, "<transcript>前言\n" + para("00:00:01", "S1", "x") + "</transcript>")[0])

    def test_validate_units_rejects_only_bad_paragraph(self):
        """〔1.1.0〕結構通過、只有一段標記的原文與輸入不符 → 只有那段判失敗，另一段照常採用。"""
        ok, outs, bad, err = ac.validate_units(self.units, self.out(
            para("00:00:01", "S1", "我們用{卡夫卡→Kafka}做佇列，{延持→延遲}大約兩秒。"),
            para("00:00:09", "S2", "好的那{退避→退避策略}呢？我覺得要指數退避。")))     # 原文側「退避」不是輸入的「退閉」
        self.assertTrue(ok, err)
        self.assertEqual(list(bad), [1])
        self.assertIn("content mismatch", bad[1])
        self.assertIsNone(outs[1])
        self.assertIn("{卡夫卡→Kafka}", outs[0][0][2])
        self.assertFalse(ac.validate(self.units, self.out(                 # 整塊驗證仍判不過（舊介面不變）
            para("00:00:01", "S1", self.units[0]["text"]), para("00:00:09", "S2", "改了沒標記")))[0])

    def test_punctuation_only_marks_normalized(self):
        """1.1.0 實測：Sonnet 補標點時寫 {，}／{→。}；只差標點的標記直接換成修正側，不算內容不符。"""
        ok, outs, bad, err = ac.validate_units(self.units, self.out(
            para("00:00:01", "S1", "我們用{卡夫卡→Kafka}{，}做佇列{，→}延持大約兩秒{→。}"),
            para("00:00:09", "S2", "好的{那→那，}退閉策略呢？我覺得要指數退避。")))
        self.assertTrue(ok, err)
        self.assertEqual(bad, {})
        self.assertEqual(outs[0][0][2], "我們用{卡夫卡→Kafka}，做佇列延持大約兩秒。")
        self.assertEqual(outs[1][0][2], "好的那，退閉策略呢？我覺得要指數退避。")
        self.assertEqual(ac.edits_of(outs[0][0][2]), [("卡夫卡", "Kafka")])     # 不計入修改、不進建議檔
        self.assertEqual(ac.normalize_noop("{Kafka}")[0], "{Kafka}")             # 有文字的大括號不動 → 照常驗證

    def test_validate_units_structure_failure_is_whole_block(self):
        ok, outs, bad, err = ac.validate_units(self.units, self.out(para("00:00:01", "S1", self.units[0]["text"])))
        self.assertEqual((ok, outs, bad), (False, None, {}))
        self.assertIn("missing", err)

    def test_prompt_rules_v110(self):
        p = ac.SYSTEM_CORRECT
        self.assertIn("逐字照抄輸入", p)
        self.assertIn("含標點與空白", p)
        self.assertIn("正例：", p)
        self.assertIn("反例：", p)
        self.assertIn("能確定正確寫法 → 直接用 {原文→修正} 修正", p)
        self.assertIn("兩種寫法都說得通、無法判斷 → 用 [?原文｜推測]", p)
        self.assertNotIn("不確定一律用", p)
        for kept in ("沒有錯的文字一個字都不要動", "每一處修改都要用標記寫出來", "不要杜撰", "必須有把握",
                     "沒有把握的地方不要直接改", "不算有把握"):
            self.assertIn(kept, p)                                     # 錯改相關規則沒有放寬
        for ex_src in ("縮影", "盤典"):                                 # 例句的字不在測試素材裡（避免對素材調 prompt）
            for m in (Path(_testenv.HERE) / "materials").glob("*.txt"):
                self.assertNotIn(ex_src, m.read_text(encoding="utf-8"))

    def test_uncertain_and_delete_insert(self):
        ok, outs, err = ac.validate(self.units, self.out(
            para("00:00:01", "S1", "我們用[?卡夫卡｜Kafka]做佇列，{延持→延遲}大約{→約}兩秒。"),
            para("00:00:09", "S2", "好的{那→}退閉策略呢？我覺得要指數退避。")))
        self.assertTrue(ok, err)
        self.assertEqual(ac.uncertain_of(outs[0][0][2]), ["[?卡夫卡｜Kafka]"])
        self.assertEqual(ac.edits_of(outs[0][0][2]), [("延持", "延遲"), ("", "約")])


# ---------------------------------------------------------------- 四個呼叫函式（C6、C7）
class FakeProc:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out.encode("utf-8"), err.encode("utf-8")


class ClaudeCli(unittest.TestCase):
    be = {"provider": "claude", "channel": "cli", "exe": "claude", "model": "sonnet", "effort": "high"}

    def setUp(self):
        self._run = ac.subprocess.run
        self.seen = {}

    def tearDown(self):
        ac.subprocess.run = self._run

    def fake(self, rc=0, j=None, err="", exc=None):
        def run(cmd, **kw):
            self.seen.update(cmd=cmd, env=kw.get("env"), cwd=kw.get("cwd"))
            if exc:
                raise exc
            return FakeProc(rc, json.dumps(j) if j is not None else "", err)
        ac.subprocess.run = run

    def test_success_flags_env(self):
        os.environ["CLAUDE_EFFORT"] = "max"
        try:
            self.fake(0, {"type": "result", "subtype": "success", "is_error": False, "result": "<transcript>x</transcript>",
                          "stop_reason": "end_turn", "usage": {"input_tokens": 5, "output_tokens": 7,
                                                               "cache_read_input_tokens": 3},
                          "modelUsage": {"claude-sonnet-5-5": {}}, "total_cost_usd": 0.02})
            r = ac._call_claude_cli(self.be, "sys", "user", 10)
        finally:
            os.environ.pop("CLAUDE_EFFORT", None)
        self.assertTrue(r["ok"])
        self.assertEqual(r["model"], "claude-sonnet-5-5")
        cmd = self.seen["cmd"]
        for f in ("--safe-mode", "--no-session-persistence", "--system-prompt-file"):
            self.assertIn(f, cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")
        self.assertEqual(cmd[cmd.index("--effort") + 1], "high")
        self.assertNotIn("--dangerously-skip-permissions", cmd)
        self.assertEqual(cmd[2], ac.PROMPT)
        for k in ac.CLAUDE_DROP_ENV:
            self.assertNotIn(k, self.seen["env"])

    def test_structured_tool_use_accepted(self):
        self.fake(0, {"type": "result", "subtype": "success", "is_error": False, "result": "", "stop_reason": "tool_use",
                      "structured_output": {"terms": []}, "usage": {}})
        r = ac._call_claude_cli(self.be, "sys", "user", 10, ac.TERMS_SCHEMA)
        self.assertTrue(r["ok"])
        self.assertEqual(r["structured"], {"terms": []})
        self.assertIn("--json-schema", self.seen["cmd"])

    def test_error_paths(self):
        base = {"type": "result", "subtype": "success", "is_error": True, "terminal_reason": "api_error"}
        cases = [
            (dict(base, api_error_status=401, result="Invalid API key"), "", "auth_failed"),
            (dict(base, api_error_status=None, result="Not logged in · Please run /login"), "", "auth_failed"),
            (dict(base, api_error_status=404, result="There's an issue with the selected model"),
             '[claude-code:unrecognized_model] {"model":"x"}', "model_not_found"),
            (dict(base, api_error_status=429, result="rate limit"), "", "rate_limited"),
            (dict(base, api_error_status=None, result="You've hit your usage limit"), "", "rate_limited"),
            (dict(base, api_error_status=529, result="Overloaded"), "", "server_error"),
            (dict(base, api_error_status=None, result="something odd"), "", "cli_error"),
        ]
        for j, err, want in cases:
            self.fake(1, j, err)
            self.assertEqual(ac._call_claude_cli(self.be, "s", "u", 10)["reason"], want, j)
        self.fake(0, {"type": "result", "subtype": "success", "is_error": False, "result": "x", "stop_reason": "max_tokens"})
        self.assertEqual(ac._call_claude_cli(self.be, "s", "u", 10)["reason"], "truncated")
        self.fake(exc=subprocess.TimeoutExpired("claude", 5))
        self.assertEqual(ac._call_claude_cli(self.be, "s", "u", 5)["reason"], "timeout")
        self.fake(1, None, "garbage")
        self.assertEqual(ac._call_claude_cli(self.be, "s", "u", 5)["reason"], "cli_error")


class CodexCli(unittest.TestCase):
    def jl(self, *evs):
        return "\n".join(json.dumps(e) for e in evs)

    def test_success_and_usage(self):
        out = self.jl({"type": "thread.started"}, {"type": "item.completed", "item": {"type": "reasoning"}},
                      {"type": "item.completed", "item": {"type": "agent_message", "text": "x"}},
                      {"type": "turn.completed", "usage": {"input_tokens": 9, "cached_input_tokens": 4,
                                                           "output_tokens": 3, "reasoning_output_tokens": 2}})
        r = ac.parse_codex(0, out, "Reading additional input from stdin...", "<transcript>x</transcript>", "gpt-6.1-sol", False)
        self.assertTrue(r["ok"])
        self.assertEqual(r["usage"], {"input": 9, "cache_read": 4, "output": 3, "thinking": 2})

    def test_structured(self):
        out = self.jl({"type": "turn.completed", "usage": {}})
        r = ac.parse_codex(0, out, "", '{"terms": []}', "gpt-6.1-sol", True)
        self.assertEqual(r["structured"], {"terms": []})
        self.assertEqual(ac.parse_codex(0, out, "", "not json", "m", True)["reason"], "cli_error")

    def test_tool_items_rejected(self):
        for t in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
            out = self.jl({"type": "item.started", "item": {"type": t}}, {"type": "turn.completed", "usage": {}})
            self.assertEqual(ac.parse_codex(0, out, "", "x", "m", False)["reason"], "tool_use_detected", t)

    def test_error_paths(self):
        bad_model = self.jl({"type": "item.completed", "item": {"type": "error", "message": "Model metadata for x not found"}},
                            {"type": "turn.failed", "error": {"message": "The 'x' model is not supported when using "
                                                                       "Codex with a ChatGPT account."}})
        self.assertEqual(ac.parse_codex(1, bad_model, "", "", "x", False)["reason"], "model_not_found")
        unauth = self.jl({"type": "error", "message": "unexpected status 401 Unauthorized: Missing bearer"},
                         {"type": "turn.failed", "error": {"message": "unexpected status 401 Unauthorized"}})
        self.assertEqual(ac.parse_codex(1, unauth, "", "", "m", False)["reason"], "auth_failed")
        limit = self.jl({"type": "turn.failed", "error": {"message": "You've hit your usage limit. Try again later."}})
        self.assertEqual(ac.parse_codex(1, limit, "", "", "m", False)["reason"], "rate_limited")
        self.assertEqual(ac.parse_codex(1, "", "error: Unknown feature flag: goals", "", "m", False)["reason"],
                         "cli_incompatible")
        self.assertEqual(ac.parse_codex(0, self.jl({"type": "thread.started"}), "", "", "m", False)["reason"], "cli_error")

    def test_command_flags(self):
        seen = {}
        run0 = ac.subprocess.run

        def run(cmd, **kw):
            seen.update(cmd=cmd, env=kw["env"])
            Path(cmd[cmd.index("-o") + 1]).write_text("<transcript>x</transcript>", encoding="utf-8")
            return FakeProc(0, json.dumps({"type": "turn.completed", "usage": {}}), "")
        ac.subprocess.run = run
        os.environ["CODEX_API_KEY"] = "test-placeholder-not-a-key"
        try:
            r = ac._call_codex_cli({"exe": "codex", "model": "gpt-6.1-sol", "effort": "low"}, "sys", "user", 10)
        finally:
            ac.subprocess.run = run0
            os.environ.pop("CODEX_API_KEY", None)
        self.assertTrue(r["ok"])
        cmd = " ".join(seen["cmd"])
        for f in ("--ignore-user-config", "--ephemeral", "-s read-only", 'approval_policy="never"', "--json",
                  "model_instructions_file=", 'model_reasoning_effort="low"', "--disable shell_tool"):
            self.assertIn(f, cmd)
        for bad in ("dangerously", "workspace-write", "danger-full-access", "--add-dir"):
            self.assertNotIn(bad, cmd)
        self.assertNotIn("\\", cmd.split("model_instructions_file=")[1].split()[0])   # TOML 路徑用 /
        self.assertNotIn("CODEX_API_KEY", seen["env"])


def fake_sdk(name):
    """假的 anthropic／openai 模組：只有 _call_*_api 用到的例外類別與 client。"""
    m = types.ModuleType(name)

    class APIError(Exception):
        pass

    class APIStatusError(APIError):
        status_code = 400

        def __init__(self, msg="", status_code=None, code=None):
            super().__init__(msg)
            if status_code:
                self.status_code = status_code
            self.code = code
            self.body = {"code": code} if code else None

    class APIConnectionError(APIError):
        pass

    class APITimeoutError(APIConnectionError):
        pass
    m.APIStatusError, m.APIConnectionError, m.APITimeoutError = APIStatusError, APIConnectionError, APITimeoutError
    for cls, code in (("AuthenticationError", 401), ("PermissionDeniedError", 403), ("NotFoundError", 404),
                      ("RateLimitError", 429), ("InternalServerError", 500)):
        setattr(m, cls, type(cls, (APIStatusError,), {"status_code": code}))
    m.behavior = None
    m.seen = {}

    class Stream:
        def __init__(self, kw):
            m.seen.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            return m.behavior()

        get_final_response = get_final_message

    class Client:
        def __init__(self, **kw):
            m.seen["client"] = kw
            self.messages = types.SimpleNamespace(stream=lambda **kw: Stream(kw))
            self.responses = types.SimpleNamespace(stream=lambda **kw: Stream(kw))
    m.Anthropic = m.OpenAI = Client
    return m


class ApiChannels(unittest.TestCase):
    """API 通道（兩家）：沒有金鑰，只以假 SDK 驗證錯誤對應與參數（未實測）。"""

    def setUp(self):
        self.saved = {k: sys.modules.get(k) for k in ("anthropic", "openai")}
        self.env = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
        self.an, self.oa = fake_sdk("anthropic"), fake_sdk("openai")
        sys.modules["anthropic"], sys.modules["openai"] = self.an, self.oa
        self.be_c = {"model_api": "claude-sonnet-5-5", "effort": "high"}
        self.be_o = {"model_api": "gpt-6.1-sol", "effort": "low"}

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for k, v in self.env.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def raise_(self, exc):
        def f():
            raise exc
        return f

    def test_key_missing_and_sdk_missing(self):
        self.assertEqual(ac._call_claude_api(self.be_c, "s", "u", 5)["reason"], "api_key_missing")
        self.assertEqual(ac._call_openai_api(self.be_o, "s", "u", 5)["reason"], "api_key_missing")
        sys.modules["openai"] = None          # import 失敗
        self.assertEqual(ac._call_openai_api(self.be_o, "s", "u", 5)["reason"], "sdk_missing")

    def test_claude_api(self):
        os.environ["ANTHROPIC_API_KEY"] = "test-placeholder-not-a-key"
        msg = types.SimpleNamespace(stop_reason="end_turn", model="claude-sonnet-5-5",
                                    content=[types.SimpleNamespace(type="thinking", thinking=""),
                                             types.SimpleNamespace(type="text", text='{"terms": []}')],
                                    usage=types.SimpleNamespace(input_tokens=5, output_tokens=6, cache_read_input_tokens=1,
                                                                cache_creation_input_tokens=2))
        self.an.behavior = lambda: msg
        r = ac._call_claude_api(self.be_c, "s", "u", 5, ac.TERMS_SCHEMA)
        self.assertTrue(r["ok"])
        self.assertEqual(r["structured"], {"terms": []})
        self.assertEqual(self.an.seen["output_config"]["effort"], "high")
        self.assertEqual(self.an.seen["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(self.an.seen["client"]["max_retries"], 0)
        for exc, want in ((self.an.AuthenticationError("x"), "auth_failed"), (self.an.NotFoundError("x"), "model_not_found"),
                          (self.an.RateLimitError("x"), "rate_limited"), (self.an.InternalServerError("x"), "server_error"),
                          (self.an.APITimeoutError("x"), "timeout"), (self.an.APIConnectionError("x"), "timeout")):
            self.an.behavior = self.raise_(exc)
            self.assertEqual(ac._call_claude_api(self.be_c, "s", "u", 5)["reason"], want)
        for stop, want in (("refusal", "refusal"), ("max_tokens", "truncated")):
            self.an.behavior = lambda: types.SimpleNamespace(stop_reason=stop, content=[], usage=None)
            self.assertEqual(ac._call_claude_api(self.be_c, "s", "u", 5)["reason"], want)

    def test_openai_api(self):
        os.environ["OPENAI_API_KEY"] = "test-placeholder-not-a-key"
        resp = types.SimpleNamespace(status="completed", model="gpt-6.1-sol", output_text="<transcript>x</transcript>",
                                     output=[types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="output_text")])],
                                     usage=types.SimpleNamespace(input_tokens=5, output_tokens=6,
                                                                 input_tokens_details=types.SimpleNamespace(cached_tokens=2),
                                                                 output_tokens_details=types.SimpleNamespace(reasoning_tokens=1)))
        self.oa.behavior = lambda: resp
        r = ac._call_openai_api(self.be_o, "s", "u", 5)
        self.assertTrue(r["ok"])
        self.assertEqual(r["usage"], {"input": 5, "cache_read": 2, "output": 6, "thinking": 1})
        self.assertEqual(self.oa.seen["reasoning"], {"effort": "low"})          # 一定明確傳
        self.assertIs(self.oa.seen["store"], False)
        ac._call_openai_api(self.be_o, "s", "u", 5, ac.TERMS_SCHEMA)
        self.assertIs(self.oa.seen["text"]["format"]["strict"], True)
        for exc, want in ((self.oa.AuthenticationError("x"), "auth_failed"), (self.oa.NotFoundError("x"), "model_not_found"),
                          (self.oa.RateLimitError("x"), "rate_limited"),
                          (self.oa.RateLimitError("x", code="insufficient_quota"), "quota_exhausted"),
                          (self.oa.InternalServerError("x"), "server_error"), (self.oa.APITimeoutError("x"), "timeout")):
            self.oa.behavior = self.raise_(exc)
            self.assertEqual(ac._call_openai_api(self.be_o, "s", "u", 5)["reason"], want)
        self.oa.behavior = lambda: types.SimpleNamespace(
            status="incomplete", incomplete_details=types.SimpleNamespace(reason="max_output_tokens"))
        self.assertEqual(ac._call_openai_api(self.be_o, "s", "u", 5)["reason"], "truncated")
        self.oa.behavior = lambda: types.SimpleNamespace(status="completed", output_text="", output=[
            types.SimpleNamespace(type="message", content=[types.SimpleNamespace(type="refusal")])])
        self.assertEqual(ac._call_openai_api(self.be_o, "s", "u", 5)["reason"], "refusal")


# ---------------------------------------------------------------- run()：整體流程
DETAIL_RE = r"^content mismatch at \d+: got_len \d+, want_len \d+$"   # 1.1.0 起：detail 只記位置與長度
PARAS = [("00:00:01", "S1", "今天確認卡夫卡的延持，密等設計也要看。"),
         ("00:00:20", "S2", "卡夫卡的賴哥目前正常，密等鍵用訂單編號。"),
         ("00:00:40", "S1", "那退閉策略呢？我覺得用指數退避就好。"),
         ("00:01:00", "S3", "密等的部分我再確認一次卡夫卡設定。")]


class Run(Base):
    def md_hash(self):
        return hashlib.sha256((self.out / "transcript.md").read_bytes()).hexdigest()

    def test_ok_outputs_and_original_untouched(self):
        write_out(self.out, PARAS + ["> 🖼 [00:01:10] 畫面：`frame_0001.jpg`"])
        before = self.md_hash()
        fake = FakeModel(fix={"卡夫卡": "Kafka", "密等": "冪等", "延持": "延遲"},
                         terms=[{"wrong": ["卡夫卡"], "right": "Kafka", "confidence": "high", "reason": "r"},
                                {"wrong": ["賴哥"], "right": "lag", "confidence": "low", "reason": "r"}])
        self.use(fake)
        cfg = self.cfg(chunk_chars=40)
        res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg, in_pipeline=True)
        self.assertEqual(res["status"], "ok", res)
        self.assertEqual(self.md_hash(), before)                     # transcript.md 一個字都不動
        self.assertGreater(res["chunks"], 1)
        self.assertTrue(fake.calls[0]["schema"])                     # 多於 1 塊 → 先跑用字表
        self.assertIn("## 確定用字\n- 卡夫卡 → Kafka", fake.calls[1]["user"])
        self.assertNotIn("賴哥 → lag", fake.calls[1]["user"])         # low 項丟掉
        self.assertIn("## 前文", fake.calls[2]["user"])
        corrected = (self.out / "transcript.corrected.md").read_text(encoding="utf-8")
        self.assertIn("{卡夫卡→Kafka}", corrected)
        self.assertIn("校正：自動（Claude sonnet", corrected)
        self.assertIn("> 🖼 [00:01:10] 畫面", corrected)
        self.assertIn("| 1 | 卡夫卡 | Kafka | 3 | 用字表 | ✅ 待確認 |", corrected)
        sug = (self.out / "corrections.suggested.tsv").read_text(encoding="utf-8")
        self.assertIn("卡夫卡\tKafka\t×3", sug)
        self.assertIn("密等\t冪等\t×3", sug)
        self.assertFalse(corrections.corrections_path().exists())     # mode off：不寫 corrections.tsv
        self.assertFalse(common.correction_history_path().exists())    # 也不記歷史
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual((rec["status"], rec["terms"]["high"], rec["terms"]["dropped_low"]), ("ok", 1, 1))
        dump = json.dumps(rec, ensure_ascii=False)
        self.assertNotIn("退閉策略", dump)                            # 不含逐字稿文字
        self.assertNotIn("校對員", dump)                              # 不含 system prompt
        meta = json.loads((self.out / "transcript.json").read_text(encoding="utf-8"))["meta"]
        self.assertEqual(meta["correction"]["status"], "ok")
        self.assertEqual(meta["correction"]["provider"], "claude")

    def test_single_chunk_skips_terms(self):
        write_out(self.out, PARAS)
        fake = FakeModel(fix={"卡夫卡": "Kafka"})
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(fake.calls[0]["schema"])

    def test_single_chunk_estimate_text(self):
        """〔1.1.0〕1 塊時不印「預估 2～2 分鐘」：opus 1 塊 → 「預估約 1 分鐘」。"""
        import contextlib
        import io
        write_out(self.out, PARAS)
        self.use(FakeModel(), model="opus", effort="medium")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual(res["status"], "ok")
        line = next(l for l in err.getvalue().splitlines() if "預估" in l)
        # 〔1.2.2〕「1 塊」→「分 1 段」
        self.assertIn(("分 1 段" if _testenv.VER >= (1, 2, 2) else "1 塊") + "，預估約 1 分鐘；逐字稿文字會送到 " + _testenv.vendor("claude"), line)
        self.assertIsNone(re.search(r"(\d+)～\1 分鐘", line))

    def test_api_auto_only_anthropic_key_records_fallback(self):
        """〔1.1.0〕API 通道 auto 只有 ANTHROPIC_API_KEY → Claude，fallback 寫進 run() 回傳與 auto_correct.json。"""
        write_out(self.out, PARAS)
        keep = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
        try:
            os.environ["ANTHROPIC_API_KEY"] = "test-placeholder-not-a-key"
            fake = FakeModel(fix={"卡夫卡": "Kafka"}, model="claude-opus-5-5")
            ac.CALLERS[("claude", "api")] = fake
            cfg = self.cfg(channel="api")
            res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg)
            self.assertEqual((res["status"], res["provider"], res["channel"]), ("ok", "claude", "api"))
            self.assertEqual(res["fallback"], "openai_key_missing")
            rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
            self.assertEqual(rec["provider_fallback"], "openai_key_missing")
            self.assertNotIn("test-placeholder-not-a-key", json.dumps(rec))   # 金鑰值不寫進輸出
        finally:
            for k, v in keep.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v

    def test_validation_retry_then_partial(self):
        write_out(self.out, PARAS)
        bad = ac._ok("<transcript>\n" + para("00:00:01", "S1", "改了沒標記") + "\n</transcript>", None, {}, "m")
        fake = FakeModel(fix={"密等": "冪等"}, script=[bad, bad])     # 第 1 塊：驗證不過 → 重試 → 仍不過
        self.use(fake)
        cfg = self.cfg(chunk_chars=40)
        res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg)
        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["chunks_ok"], res["chunks"] - 1)
        corrected = (self.out / "transcript.corrected.md").read_text(encoding="utf-8")
        self.assertIn("> ⚠ 以下 2 段未自動校正（原因：validation_failed）", corrected)
        self.assertIn(para(*PARAS[0]), corrected)                       # 失敗塊放回原文
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["chunks"][0]["retries"], 1)
        self.assertEqual(ac.exit_code(res), 0)

    def test_paragraph_reject_keeps_rest_of_chunk(self):
        """〔1.1.0〕一塊中只有一段標記的原文不符 → 只退那段（放回原文並註記），同塊其他段照常採用、不重試。"""
        write_out(self.out, PARAS)

        def one_bad(user):
            body = section(user, "要校正的逐字稿")
            body = body.replace("卡夫卡", "{卡夫卡→Kafka}").replace("退閉策略", "{退避→退避}策略")   # 第 3 段原文側寫錯
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "m")
        fake = FakeModel(script=[one_bad])
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={})            # 1 塊（4 段）
        self.assertEqual((res["status"], res["chunks_ok"], res["units_rejected"]), ("ok", 1, 1), res)
        self.assertEqual(len(fake.calls), 1)                             # 逐段退回不重試
        corrected = (self.out / "transcript.corrected.md").read_text(encoding="utf-8")
        self.assertIn("> ⚠ 以下 1 段未自動校正（原因：validation_failed）\n\n" + para(*PARAS[2]), corrected)
        self.assertIn(para("00:00:01", "S1", "今天確認{卡夫卡→Kafka}的延持，密等設計也要看。"), corrected)
        self.assertIn(para("00:01:00", "S3", "密等的部分我再確認一次{卡夫卡→Kafka}設定。"), corrected)
        self.assertIn("`[00:00:40]` 這段的自動校正未通過驗證", corrected)
        self.assertEqual(corrected.count("⚠ 以下"), 1)
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        c = rec["chunks"][0]
        self.assertEqual((c["status"], c["retries"], c["fails"]), ("ok", 0, []))
        self.assertEqual([(x["unit"], x["para"], x["time"], x["spk"]) for x in c["rejects"]], [(2, 2, "00:00:40", "S1")])
        self.assertRegex(c["rejects"][0]["detail"], DETAIL_RE)          # 1.1.0 起：只記位置與長度
        self.assertEqual((rec["totals"]["units"], rec["totals"]["units_rejected"], rec["totals"]["chunks_rejected"]),
                         (4, 1, 0))
        self.assertEqual(rec["totals"]["edits"], 3)                      # 退回那段的標記不計入（卡夫卡 ×3）

    def test_all_paragraphs_bad_is_whole_chunk_failure(self):
        write_out(self.out, PARAS)

        def all_bad(user):
            body = re.sub(r"(\*\*：)(.)", r"\1{X\2→\2}", section(user, "要校正的逐字稿"))
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "m")
        fake = FakeModel(script=[all_bad, all_bad])
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual((res["status"], res["reason"]), ("failed", "validation_failed"))
        self.assertEqual(len(fake.calls), 2)                             # 整塊不過 → 照舊重試 1 次
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertRegex(rec["chunks"][0]["detail"], r"^all 4 paragraph\(s\): para 0: " + DETAIL_RE[1:])
        self.assertEqual(len(rec["chunks"][0]["fails"]), 2)
        for f in rec["chunks"][0]["fails"]:
            self.assertRegex(f["detail"], r"^all 4 paragraph\(s\): para 0: " + DETAIL_RE[1:])

    def test_details_have_no_transcript_text(self):
        """〔1.1.0〕fails[].detail、rejects[].detail 只記段號、字元位置、長度、原因代碼，不含逐字稿片段（規格 §6.14）。"""
        got, want = "今天確認Kafka的延遲", "今天確認卡夫卡的延持"
        self.assertEqual(ac._mismatch(got, want), "content mismatch at 4: got_len 12, want_len 10")
        self.assertEqual(ac._mismatch("abc", "abcd"), "content mismatch at 3: got_len 3, want_len 4")
        write_out(self.out, PARAS)

        def two_bad(user):       # 1 塊 4 段：第 1、4 段原文側寫錯 → 逐段退回 2 段
            body = section(user, "要校正的逐字稿")
            body = body.replace("密等設計", "{秘等→密等}設計").replace("密等的部分", "{秘等→密等}的部分")
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "m")

        def all_bad(user):
            body = re.sub(r"(\*\*：)(.)", r"\1{X\2→\2}", section(user, "要校正的逐字稿"))
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "m")
        for script in ([two_bad], [all_bad, all_bad]):
            with self.subTest(n=len(script)):
                for p in self.out.glob("transcript.corrected.md"):
                    p.unlink()
                fake = FakeModel(script=list(script))
                self.use(fake)
                ac.run(self.out, ac.resolve_request({}), cfg={})
                rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
                details = [x["detail"] for c in rec["chunks"] for x in (c.get("rejects") or []) + (c.get("fails") or [])]
                details += [c["detail"] for c in rec["chunks"] if c.get("detail")]
                self.assertTrue(details)
                for d in details:
                    self.assertRegex(d, r"^(all \d+ paragraph\(s\): para \d+: )?" + DETAIL_RE[1:])
                    self.assertTrue(d.isascii(), d)                                  # 只有 ASCII：沒有任何逐字稿文字
                dump = json.dumps(rec, ensure_ascii=False)
                for _, _, text in PARAS:
                    for k in range(0, len(text) - 3):
                        self.assertNotIn(text[k:k + 4], dump)                          # 素材任何 4 字片段都不在紀錄裡

    def test_auth_failed_stops(self):
        write_out(self.out, PARAS)
        fake = FakeModel(script=[ac._fail("auth_failed", 401)])
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual((res["status"], res["reason"]), ("failed", "auth_failed"))
        self.assertFalse((self.out / "transcript.corrected.md").exists())
        self.assertEqual(ac.exit_code(res), 3)

    def test_rate_limit_keeps_done_chunks(self):
        write_out(self.out, PARAS)
        fake = FakeModel(fix={"密等": "冪等"}, script=[None, ac._fail("rate_limited", 429)])   # 第 1 塊正常（用字表不消耗 script）
        self.use(fake)
        cfg = self.cfg(chunk_chars=20)                                # 4 塊
        res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg)
        self.assertEqual((res["status"], res["reason"]), ("partial", "rate_limited"))
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual([c["status"] for c in rec["chunks"]], ["ok", "failed", "not_run", "not_run"])
        self.assertIn(f"剩下 3 {_testenv.CHUNK_UNIT}未校正", res["message"])   # 〔1.2.2〕塊 → 段

    def test_server_error_retried_once(self):
        write_out(self.out, PARAS)
        fake = FakeModel(fix={"密等": "冪等"}, script=[ac._fail("server_error", 529)])
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(fake.calls), 2)

    def test_two_timeouts_stop(self):
        write_out(self.out, PARAS)
        to = ac._fail("timeout")
        fake = FakeModel(script=[None, to, to])
        self.use(fake)
        cfg = self.cfg(chunk_chars=20)                                # 4 塊
        res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg)
        self.assertEqual((res["status"], res["reason"]), ("partial", "timeout"))
        self.assertEqual(len(fake.calls), 4)                          # 用字表＋3 塊；連續 2 塊逾時就停（不重試）
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual([c["status"] for c in rec["chunks"]], ["ok", "failed", "failed", "not_run"])

    def test_truncated_splits_chunk(self):
        write_out(self.out, PARAS)
        fake = FakeModel(fix={"密等": "冪等"}, script=[ac._fail("truncated")])
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(fake.calls), 3)                          # 1 次截斷 → 對半各 1 次

    def test_cross_chunk_conflict(self):
        write_out(self.out, PARAS)

        def second(user):
            body = section(user, "要校正的逐字稿").replace("密等", "{密等→秘等}")
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "m")
        fake = FakeModel(fix={"密等": "冪等"}, script=[None, second])
        self.use(fake)
        cfg = self.cfg(chunk_chars=40)
        res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg)
        self.assertEqual(res["status"], "ok")
        corrected = (self.out / "transcript.corrected.md").read_text(encoding="utf-8")
        self.assertNotIn("{密等→", corrected)
        self.assertIn("「密等」在不同位置被改成「冪等」「秘等」，未自動修改", corrected)
        self.assertFalse((self.out / "corrections.suggested.tsv").exists())

    def test_split_paragraph_reported(self):
        write_out(self.out, PARAS)

        def split(user):
            body = section(user, "要校正的逐字稿").replace("呢？我覺得", "呢？\n\n**[00:00:40] S?**：我覺得")
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "m")
        self.use(FakeModel(script=[split]))
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual(res["status"], "ok")
        corrected = (self.out / "transcript.corrected.md").read_text(encoding="utf-8")
        self.assertIn("**[00:00:40] S?**：我覺得", corrected)
        self.assertIn("`[00:00:40]` 這段依內容拆出，講者待確認（S?）", corrected)
        self.assertIn("| S? | （待確認） |", corrected)

    def test_long_meeting_confirmation(self):
        write_out(self.out, PARAS, duration=130 * 60)                # 規格 §9.1：以單元測試把長度設成 130 分鐘
        fake = FakeModel()
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={}, interactive=False)
        self.assertEqual((res["status"], res["reason"]), ("skipped", "needs_confirmation"))
        self.assertEqual(fake.calls, [])
        import builtins
        old = builtins.input
        builtins.input = lambda prompt="": "n"
        try:
            res = ac.run(self.out, ac.resolve_request({}), cfg={}, interactive=True)
        finally:
            builtins.input = old
        self.assertEqual((res["status"], res["reason"]), ("skipped", "user_declined"))
        res = ac.run(self.out, ac.resolve_request({}), cfg={}, consent=True)      # --correct／--claude
        self.assertEqual(res["status"], "ok")

    def test_existing_corrected(self):
        write_out(self.out, PARAS)
        (self.out / "transcript.corrected.md").write_text("對話補過的版本", encoding="utf-8")
        self.use(FakeModel())
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual((res["status"], res["reason"]), ("skipped", "exists"))
        self.assertEqual(ac.exit_code(res), 2)
        res = ac.run(self.out, ac.resolve_request({}), cfg={}, force=True)
        self.assertEqual(res["status"], "ok")
        baks = list(self.out.glob("transcript.corrected.*.bak.md"))
        self.assertEqual(len(baks), 1)
        self.assertEqual(baks[0].read_text(encoding="utf-8"), "對話補過的版本")

    def test_skip_reasons_from_backend(self):
        write_out(self.out, PARAS)
        before = self.md_hash()
        for skip, code in (("cli_not_found", 2), ("api_key_missing", 2), ("auth_failed", 3)):
            ac.select_backend = lambda cfg, req, s=skip: {"skip": s, "provider": "openai", "message": "m"}
            res = ac.run(self.out, ac.resolve_request({}), cfg={})
            self.assertEqual((res["status"], res["reason"], ac.exit_code(res)), ("skipped", skip, code))
        self.assertEqual(self.md_hash(), before)

    def test_model_not_found_exit4(self):
        write_out(self.out, PARAS)
        self.use(FakeModel(script=[ac._fail("model_not_found", 404)]))
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual((res["reason"], ac.exit_code(res)), ("model_not_found", 4))
        self.assertIn("不存在", res["message"])

    def test_tool_use_detected_keeps_original(self):
        write_out(self.out, PARAS)
        self.use(FakeModel(script=[ac._fail("tool_use_detected")]), provider="openai", model="gpt-6.1-sol", effort="low")
        res = ac.run(self.out, ac.resolve_request({}), cfg={})
        self.assertEqual((res["status"], res["reason"]), ("failed", "tool_use_detected"))


# ---------------------------------------------------------------- 條件式自動寫入（1.1.0）
class AutoWrite(Base):
    def run_once(self, paras, fix, terms, mode="on", src="demo.wav", provider="claude", model_used="claude-sonnet-5-5",
                 **ca):
        d = Path(tempfile.mkdtemp(prefix="mmp-ac-meet-", dir=self.out))
        write_out(d, paras)
        meta = json.loads((d / "transcript.json").read_text(encoding="utf-8"))
        meta["meta"]["source"] = src
        (d / "transcript.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        self.use(FakeModel(fix=fix, terms=terms, model=model_used), provider=provider,
                 model="sonnet" if provider == "claude" else "gpt-6.1-sol")
        cfg = {"correction": {"chunk_chars": 40, "corrections_auto": dict({"mode": mode}, **ca)}}
        res = ac.run(d, ac.resolve_request(cfg), cfg=cfg)
        rec = json.loads((d / "auto_correct.json").read_text(encoding="utf-8"))
        return res, rec, d

    terms = [{"wrong": ["卡夫卡"], "right": "Kafka", "confidence": "high", "reason": "r"},
             {"wrong": ["密等"], "right": "冪等", "confidence": "high", "reason": "r"}]
    fix = {"卡夫卡": "Kafka", "密等": "冪等", "延持": "延遲"}

    def rows(self):
        return corrections.load()

    def test_mode_off_same_as_before(self):
        corrections.save([("酷伯內蒂斯", "Kubernetes", "")])
        before = corrections.corrections_path().read_bytes()
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, mode="off", min_meetings=1)
        self.assertEqual(rec["corrections_auto"], {"mode": "off", "written": []})
        self.assertEqual(corrections.corrections_path().read_bytes(), before)
        self.assertFalse(common.correction_history_path().exists())
        self.assertTrue((d / "corrections.suggested.tsv").exists())

    def test_conditions_and_history(self):
        # ② 第一場只記歷史，第二場（不同會議）才寫入
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, src="m1.wav")
        self.assertEqual(rec["corrections_auto"]["written"], [])
        self.assertGreaterEqual(rec["corrections_auto"]["skipped"]["② 場次不足"], 2)
        hist = json.loads(common.correction_history_path().read_text(encoding="utf-8"))
        self.assertEqual(sorted(hist["pairs"]), ["卡夫卡\tKafka", "密等\t冪等"])
        self.assertNotIn("退閉策略", json.dumps(hist, ensure_ascii=False))       # 只存詞對、次數、場次、日期
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, src="m1.wav")      # 同一場重跑不算第二場
        self.assertEqual(rec["corrections_auto"]["written"], [])
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, src="m2.wav")
        written = {(w["wrong"], w["right"]) for w in rec["corrections_auto"]["written"]}
        self.assertEqual(written, {("卡夫卡", "Kafka"), ("密等", "冪等")})
        self.assertNotIn(("延持", "延遲"), written)                               # ③ 不是用字表 high 項
        self.assertTrue(all(n.startswith("auto:") and "m2.wav" in n for _, _, n in self.rows()))
        self.assertTrue(Path(rec["corrections_auto"]["backup"] or "").exists() or rec["corrections_auto"]["backup"] is None)
        sug = (d / "corrections.suggested.tsv").read_text(encoding="utf-8")
        self.assertNotIn("卡夫卡\tKafka", sug)                                    # 寫入的不再列在建議檔
        self.assertIn("延持\t延遲", sug)
        self.assertIn("✅ 已自動加入", (d / "transcript.corrected.md").read_text(encoding="utf-8"))

    def test_min_count(self):
        paras = [("00:00:01", "S1", "卡夫卡要升級，密等鍵用訂單編號。"), ("00:00:20", "S2", "卡夫卡的部分我來處理。"),
                 ("00:00:40", "S1", "這週先處理監控告警的設定問題，然後再看儀表板。")]   # 3 段 → 2 塊，才會跑用字表
        res, rec, d = self.run_once(paras, self.fix, self.terms, min_meetings=1, min_count=2)
        written = {w["wrong"] for w in rec["corrections_auto"]["written"]}
        self.assertEqual(written, {"卡夫卡"})                                     # ① 密等只出現 1 次
        self.assertEqual(rec["corrections_auto"]["skipped"]["① 次數不足"], 1)

    def test_uncertain_blocks(self):
        def unsure(user):
            body = section(user, "要校正的逐字稿").replace("密等", "[?密等｜冪等]", 1).replace("卡夫卡", "{卡夫卡→Kafka}")
            return ac._ok(f"<transcript>\n{body}\n</transcript>", None, {}, "claude-sonnet-5-5")
        d = Path(tempfile.mkdtemp(prefix="mmp-ac-meet-", dir=self.out))
        write_out(d, PARAS)
        self.use(FakeModel(terms=self.terms, script=[unsure] * 3))
        cfg = {"correction": {"chunk_chars": 40, "corrections_auto": {"mode": "on", "min_meetings": 1}}}
        ac.run(d, ac.resolve_request(cfg), cfg=cfg)
        rec = json.loads((d / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual({w["wrong"] for w in rec["corrections_auto"]["written"]}, {"卡夫卡"})

    def test_models_list(self):
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, min_meetings=1, provider="openai",
                                    model_used="gpt-6.1-terra")
        self.assertEqual(rec["corrections_auto"]["written"], [])                  # ④ 預設清單沒有 terra
        self.assertGreater(rec["corrections_auto"]["skipped"]["④ 模型不在清單"], 0)
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, min_meetings=1, provider="openai",
                                    model_used="gpt-6.1-sol")                     # 1.1.0：預設清單加入 sol
        self.assertEqual(len(rec["corrections_auto"]["written"]), 2)
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, min_meetings=1, provider="openai",
                                    model_used="gpt-6.1-sol", models=["claude:sonnet"])   # 使用者自訂清單照舊優先
        self.assertEqual(rec["corrections_auto"]["written"], [])

    def test_model_allowed_rules(self):
        m = ["claude:sonnet", "opus", "openai:gpt-6.1-sol"]
        self.assertTrue(ac.model_allowed(m, "claude", "claude-sonnet-5-5", "sonnet"))
        self.assertTrue(ac.model_allowed(m, "claude", "claude-opus-5-5", "opus"))      # 沒有前綴＝claude:
        self.assertFalse(ac.model_allowed(m, "claude", "claude-haiku-5-5", "haiku"))
        self.assertTrue(ac.model_allowed(m, "openai", "gpt-6.1-sol-2026-10-01", "gpt-6.1-sol"))
        self.assertFalse(ac.model_allowed(m, "openai", "gpt-6.1-terra", "gpt-6.1-terra"))
        self.assertTrue(ac.model_allowed(["claude:claude-sonnet-5-5"], "claude", "claude-sonnet-5-5", "sonnet"))
        self.assertFalse(ac.model_allowed(["claude:claude-sonnet-5-5"], "claude", "claude-sonnet-6", "sonnet"))

    def test_max_per_run_and_undo(self):
        corrections.save([("酷伯內蒂斯", "Kubernetes", "使用者加的")])
        original = corrections.corrections_path().read_text(encoding="utf-8")
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, min_meetings=1, max_per_run=1)
        self.assertEqual(len(rec["corrections_auto"]["written"]), 1)              # ⑤
        self.assertEqual(rec["corrections_auto"]["skipped"]["⑤ 超過每場上限"], 1)
        self.assertTrue(Path(rec["corrections_auto"]["backup"]).exists())
        self.assertEqual(Path(rec["corrections_auto"]["backup"]).read_text(encoding="utf-8"), original)
        self.assertEqual(len(corrections.auto_rows()), 1)
        gone = corrections.remove_auto(lambda w, r, n: True)                       # 撤銷
        self.assertEqual(len(gone), 1)
        self.assertEqual(corrections.corrections_path().read_text(encoding="utf-8"), original)   # 還原成寫入前
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, min_meetings=1, max_per_run=5)
        written = {w["wrong"] for w in rec["corrections_auto"]["written"]}
        self.assertNotIn(gone[0][0], written)                                      # 撤銷過的不再自動寫入
        self.assertEqual(rec["corrections_auto"]["skipped"]["已撤銷過"], 1)

    def test_conflict_with_existing_rows(self):
        corrections.save([("Kafka", "卡夫卡", "")])     # §6.10 條件 3：a 是某筆的正確寫法 → 不列
        res, rec, d = self.run_once(PARAS, self.fix, self.terms, min_meetings=1)
        self.assertNotIn("卡夫卡", {w["wrong"] for w in rec["corrections_auto"]["written"]})


class UndoCli(Base):
    def test_auto_list_and_undo_cli(self):
        corrections.save([("酷伯內蒂斯", "Kubernetes", "")])
        corrections.append_rows([("卡夫卡", "Kafka", "auto:2026-11-06 m.wav"), ("密等", "冪等", "auto:2026-11-05 n.wav")])
        script = Path(_testenv.SCRIPTS) / "corrections.py"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        p = subprocess.run([sys.executable, "-B", str(script), "auto-list"], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        self.assertIn("自動寫入 2 筆", p.stdout)
        p = subprocess.run([sys.executable, "-B", str(script), "auto-undo", "--date", "2026-11-06"], capture_output=True,
                           text=True, encoding="utf-8", env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([w for w, _, _ in corrections.load()], ["酷伯內蒂斯", "密等"])
        self.assertTrue(list((self.home / "backups").glob("corrections.*.tsv")))
        p = subprocess.run([sys.executable, "-B", str(script), "auto-undo"], capture_output=True, text=True,
                           encoding="utf-8", env=env)
        self.assertNotEqual(p.returncode, 0)


# ---------------------------------------------------------------- 〔2.2.0〕參考資料（規格 2.2.0 §4、§6、§11.2、§11.4）
V22 = _testenv.VER >= (2, 2, 0)
HAS_FFMPEG = shutil.which("ffmpeg") is not None
V21_SCRIPTS = _testenv.HERE.parent / "meeting-minutes-pro-v2.1.0" / "payload" / "runtime" / "scripts"
CHANNELS = (("claude", "cli"), ("claude", "api"), ("openai", "cli"), ("openai", "api"))
REFS_RESULT = {"meeting": {"title": "示範證券 v3 上線準備會議", "date": "2026-11-03", "time": "14:00–14:30"},
               "participants": [{"name": "陳怡君", "role": "專案經理"}, {"name": "林家豪", "role": "SRE"},
                                {"name": "張雅婷", "role": "後端"}],
               "frames": [{"time": "00:00:01", "kind": "participants", "speaking": "陳怡君", "terms": []},
                          {"time": "00:00:25", "kind": "slide", "speaking": "林家豪", "terms": ["Kafka"]},
                          {"time": "00:01:01", "kind": "slide", "speaking": "", "terms": ["冪等"]}],
               "terms": [{"term": "Kafka", "source": "frame"}, {"term": "冪等", "source": "frame"}]}


def _img(path: Path, box: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180", "-frames:v", "1",
                    "-vf", f"drawbox=x={box}:y=0:w=40:h=180:color=black:t=fill", str(path)],
                   check=True, capture_output=True, stdin=subprocess.DEVNULL)


class RefsFake:
    """REFS_SCHEMA 的呼叫回 REFS_RESULT（script 依序回特殊結果，None＝正常）；其他呼叫交給 inner（FakeModel）。
    記下每次呼叫的 system、user、圖片路徑與當下圖片存不存在。"""

    def __init__(self, inner, script=None, result=None):
        self.inner, self.script, self.result, self.calls = inner, list(script or []), result or REFS_RESULT, []

    def __call__(self, be, system, user, timeout, schema=None, images=None):
        self.calls.append({"system": system, "user": user, "refs": schema is ac.REFS_SCHEMA, "schema": schema is not None,
                           "images": [str(i) for i in images] if images is not None else None,
                           "exists": [Path(i).is_file() for i in images or []]})
        if schema is ac.REFS_SCHEMA:
            r = self.script.pop(0) if self.script else None
            if r is not None:
                return r
            return ac._ok(json.dumps(self.result, ensure_ascii=False), json.loads(json.dumps(self.result)),
                          {"input": 9561, "output": 1839}, "claude-opus-5-5")
        return self.inner(be, system, user, timeout, schema)

    def refs_calls(self):
        return [c for c in self.calls if c["refs"]]

    def other_calls(self):
        return [c for c in self.calls if not c["refs"]]


class RefsBase(Base):
    def materials(self, frames=True, context=True, doc=True):
        write_out(self.out, PARAS, hotwords="")
        if frames:
            kf = []
            for i, (sec, box) in enumerate(((1, 0), (25, 120), (61, 240)), 1):
                _img(self.out / "frames" / f"frame_{i:04d}.jpg", box)
                kf.append({"time": float(sec), "file": f"frames/frame_{i:04d}.jpg"})
            doc_ = json.loads((self.out / "transcript.json").read_text(encoding="utf-8"))
            doc_["keyframes"] = kf
            (self.out / "transcript.json").write_text(json.dumps(doc_, ensure_ascii=False), encoding="utf-8")
        if context:
            (self.parent / "demo.context.md").write_text("示範證券上線週會。常用寫法：Grafana、Prometheus\n", encoding="utf-8")
        if doc:
            (self.parent / "demo.議程.md").write_text("# Redis Sentinel 切換\n\n今天確認卡夫卡的延遲與冪等設計\n", encoding="utf-8")

    def events(self):
        return [json.loads(l) for l in (self.out / "run_log.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def home_files(self):
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))


@unittest.skipUnless(V22, "2.2.0 才有")
class ImagesChannels(unittest.TestCase):
    """§4、§11.2：四個呼叫器附圖（假的 CLI／SDK）。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-ac-img-"))
        self.imgs = [self.tmp / "01 截圖.jpg", self.tmp / "02.jpg"]
        self.imgs[0].write_bytes(b"\xff\xd8first")
        self.imgs[1].write_bytes(b"\xff\xd8second")
        self._run = ac.subprocess.run

    def tearDown(self):
        ac.subprocess.run = self._run
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_claude_cli_stream_json(self):
        seen = {}
        result = {"type": "result", "subtype": "success", "is_error": False, "result": "", "stop_reason": "tool_use",
                  "structured_output": {"meeting": {}}, "usage": {"input_tokens": 2, "cache_creation_input_tokens": 9559,
                                                                  "output_tokens": 1839},
                  "modelUsage": {"claude-opus-5-5": {}}, "total_cost_usd": 0.113}

        def run(cmd, **kw):
            seen.update(cmd=cmd, input=kw["input"])
            out = "\n".join(json.dumps(e) for e in ({"type": "system", "subtype": "init"}, {"type": "assistant"}, result))
            return FakeProc(0, out, "")
        ac.subprocess.run = run
        be = {"provider": "claude", "channel": "cli", "exe": "claude", "model": "opus", "effort": "medium"}
        r = ac._call_claude_cli(be, "sys", "使用者訊息", 10, ac.REFS_SCHEMA, images=self.imgs)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["structured"], {"meeting": {}})
        self.assertEqual(r["usage"]["input"], 9561)
        cmd = seen["cmd"]
        self.assertNotIn(ac.PROMPT, cmd)                                                    # 不給位置參數 PROMPT
        self.assertEqual(cmd[cmd.index("--input-format") + 1], "stream-json")
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "stream-json")
        self.assertIn("--verbose", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "")                                 # --tools "" 不改
        for f in ("--safe-mode", "--no-session-persistence", "--json-schema", "--system-prompt-file"):
            self.assertIn(f, cmd)
        line = seen["input"].decode("utf-8")
        self.assertTrue(line.endswith("\n"))
        self.assertEqual(line.count("\n"), 1)                                              # stdin 一行
        msg = json.loads(line)
        content = msg["message"]["content"]
        self.assertEqual((msg["type"], msg["message"]["role"]), ("user", "user"))
        self.assertEqual([c["type"] for c in content], ["image", "image", "text"])
        self.assertEqual(content[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(base64.b64decode(content[1]["source"]["data"]), b"\xff\xd8second")
        self.assertEqual(content[2]["text"], "使用者訊息")
        ac.subprocess.run = lambda cmd, **kw: FakeProc(1, json.dumps({"type": "system"}), "error: unknown option '--input-format'")
        self.assertEqual(ac._call_claude_cli(be, "s", "u", 10, ac.REFS_SCHEMA, images=self.imgs)["reason"], "cli_incompatible")

    def test_claude_cli_without_images_unchanged(self):
        seen = {}

        def run(cmd, **kw):
            seen.update(cmd=cmd, input=kw["input"])
            return FakeProc(0, json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "x",
                                           "stop_reason": "end_turn", "usage": {}}), "")
        ac.subprocess.run = run
        ac._call_claude_cli({"exe": "claude", "model": "opus", "effort": "medium"}, "s", "u", 10)
        self.assertEqual(seen["cmd"][2], ac.PROMPT)
        self.assertEqual(seen["cmd"][seen["cmd"].index("--output-format") + 1], "json")
        self.assertNotIn("--input-format", seen["cmd"])
        self.assertEqual(seen["input"], b"u")

    def test_codex_images_right_after_exec(self):
        seen = {}

        def run(cmd, **kw):
            seen.update(cmd=cmd)
            Path(cmd[cmd.index("-o") + 1]).write_text('{"meeting": {}}', encoding="utf-8")
            return FakeProc(0, json.dumps({"type": "turn.completed", "usage": {}}), "Reading additional input from stdin...")
        ac.subprocess.run = run
        r = ac._call_codex_cli({"exe": "codex", "model": "gpt-6.1-sol", "effort": "low"}, "s", "u", 10, ac.REFS_SCHEMA,
                               images=self.imgs)
        self.assertTrue(r["ok"], r)
        cmd = seen["cmd"]
        self.assertEqual(cmd[1:6], ["exec", "-i", self.imgs[0].as_posix(), "-i", self.imgs[1].as_posix()])
        self.assertEqual(cmd[-1], ac.PROMPT)
        self.assertIn("--output-schema", cmd)
        disabled = [cmd[i + 1] for i, c in enumerate(cmd) if c == "--disable"]
        self.assertIn("view_image", disabled)                                               # view_image 保留關閉
        self.assertEqual(ac.CODEX_ALLOWED_ITEMS, {"agent_message", "reasoning", "error"})

    def test_api_content_blocks(self):
        saved = {k: sys.modules.get(k) for k in ("anthropic", "openai")}
        env = {k: os.environ.pop(k, None) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")}
        an, oa = fake_sdk("anthropic"), fake_sdk("openai")
        sys.modules["anthropic"], sys.modules["openai"] = an, oa
        os.environ["ANTHROPIC_API_KEY"] = os.environ["OPENAI_API_KEY"] = "test-placeholder-not-a-key"
        try:
            an.behavior = lambda: types.SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                                        content=[types.SimpleNamespace(type="text", text='{"a": 1}')],
                                                        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
            r = ac._call_claude_api({"model_api": "claude-opus-5-5", "effort": "medium"}, "s", "u", 5, ac.REFS_SCHEMA,
                                    images=self.imgs)
            self.assertTrue(r["ok"], r)
            content = an.seen["messages"][0]["content"]
            self.assertEqual([c["type"] for c in content], ["image", "image", "text"])
            self.assertEqual(content[0]["source"], {"type": "base64", "media_type": "image/jpeg",
                                                    "data": base64.b64encode(b"\xff\xd8first").decode("ascii")})
            self.assertEqual(content[2], {"type": "text", "text": "u"})
            oa.behavior = lambda: types.SimpleNamespace(status="completed", model="gpt-6.1-sol", output_text='{"a": 1}', output=[],
                                                        usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))
            r = ac._call_openai_api({"model_api": "gpt-6.1-sol", "effort": "low"}, "s", "u", 5, ac.REFS_SCHEMA, images=self.imgs)
            self.assertTrue(r["ok"], r)
            self.assertEqual(oa.seen["instructions"], "s")
            inp = oa.seen["input"]
            self.assertEqual((len(inp), inp[0]["role"]), (1, "user"))
            parts = inp[0]["content"]
            self.assertEqual([p["type"] for p in parts], ["input_image", "input_image", "input_text"])
            self.assertEqual(parts[1]["image_url"], "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8second").decode("ascii"))
            self.assertEqual(parts[0]["detail"], "high")
            self.assertEqual(parts[2], {"type": "input_text", "text": "u"})
            ac._call_openai_api({"model_api": "gpt-6.1-sol", "effort": "low"}, "s", "u", 5)
            self.assertEqual(oa.seen["input"], "u")                                         # 沒有圖：照 2.1.0
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
            for k, v in env.items():
                os.environ.pop(k, None)
                if v is not None:
                    os.environ[k] = v


REGRESSION_SCRIPT = r'''
import json, os, re, sys, types
from pathlib import Path
args = json.loads(sys.argv[1])
os.environ["MMP_TEST_VERSION"] = args["version"]
sys.path.insert(0, args["tests"])
import _testenv
import auto_correct as ac
records = []


class P:
    def __init__(self, rc, out, err=""):
        self.returncode, self.stdout, self.stderr = rc, out.encode("utf-8"), err.encode("utf-8")


def body_of(user):
    m = re.search(r"## 要校正的逐字稿\n(.*)\Z", user, re.S)
    return m.group(1).strip() if m else ""


def answer(user, schema):
    return json.dumps({"terms": []}) if schema else "<transcript>\n" + body_of(user) + "\n</transcript>"


def run(cmd, input=None, capture_output=True, timeout=None, env=None, cwd=None, **kw):
    tmp = str(cwd)
    norm = lambda s: s.replace(tmp, "<TMP>").replace(Path(tmp).as_posix(), "<TMP>")
    user = input.decode("utf-8")
    schema = "--json-schema" in cmd or "--output-schema" in cmd
    records.append({"cmd": [norm(c) for c in cmd], "stdin": user,
                    "system": (Path(tmp) / "system.txt").read_text(encoding="utf-8")})
    if cmd[1] == "exec":
        Path(cmd[cmd.index("-o") + 1]).write_text(answer(user, schema), encoding="utf-8")
        return P(0, json.dumps({"type": "turn.completed", "usage": {}}))
    j = {"type": "result", "subtype": "success", "is_error": False, "result": "" if schema else answer(user, False),
         "stop_reason": "end_turn", "usage": {}, "modelUsage": {}}
    if schema:
        j["structured_output"] = {"terms": []}
    return P(0, json.dumps(j))


ac.subprocess.run = run


def sdk(name):
    m = types.ModuleType(name)
    base = type("E", (Exception,), {})
    for c in ("AuthenticationError", "PermissionDeniedError", "NotFoundError", "RateLimitError", "APITimeoutError",
              "APIConnectionError", "APIStatusError"):
        setattr(m, c, type(c, (base,), {}))

    class Stream:
        def __init__(self, kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            records.append({"api": name, "kw": self.kw})
            text = answer(self.kw["messages"][0]["content"], "format" in self.kw["output_config"])
            return types.SimpleNamespace(stop_reason="end_turn", model="m", content=[types.SimpleNamespace(type="text", text=text)],
                                         usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

        def get_final_response(self):
            records.append({"api": name, "kw": self.kw})
            return types.SimpleNamespace(status="completed", model="m", output=[], output_text=answer(self.kw["input"], "text" in self.kw),
                                         usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

    class Client:
        def __init__(self, **kw):
            self.messages = types.SimpleNamespace(stream=lambda **kw: Stream(kw))
            self.responses = types.SimpleNamespace(stream=lambda **kw: Stream(kw))
    m.Anthropic = m.OpenAI = Client
    return m


sys.modules["anthropic"], sys.modules["openai"] = sdk("anthropic"), sdk("openai")
os.environ["ANTHROPIC_API_KEY"] = os.environ["OPENAI_API_KEY"] = "test-placeholder-not-a-key"
be = {"provider": args["provider"], "channel": args["channel"], "exe": "fake-cli", "cli_version": "fake 1.0",
      "auth": "subscription", "note": None, "model": args["model"], "effort": args["effort"], "model_api": args["model"]}
ac.select_backend = lambda cfg, req: dict(be)
res = ac.run(args["out"], {"provider": args["provider"], "channel": args["channel"], "model": None, "effort": None,
                           "section": "correction"}, cfg={"correction": {"chunk_chars": 40}}, consent=True)
print(json.dumps({"records": records, "status": res["status"]}, ensure_ascii=False))
'''


@unittest.skipUnless(V22, "2.2.0 才有")
class RegressionV21(unittest.TestCase):
    """規格 2.2.0 §11.2：沒有任何參考資料時，四個呼叫器收到的命令列／stdin／系統提示詞（API：SDK 參數）與 2.1.0 逐位元相同，
    校正版也相同。兩個版本各在獨立行程跑同一份輸入、同一個假 CLI／假 SDK。"""

    def setUp(self):
        if not V21_SCRIPTS.is_dir():
            self.skipTest("沒有 meeting-minutes-pro-v2.1.0 目錄")
        self.root = Path(tempfile.mkdtemp(prefix="mmp-ac-reg-"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_version(self, version, provider, channel):
        out = self.root / f"{version}-{provider}-{channel}" / "demo_minutes"
        out.mkdir(parents=True)
        write_out(out, PARAS + ["> 🖼 [00:01:10] 畫面：`frame_0001.jpg`"])
        model, effort = ("opus", "medium") if provider == "claude" else ("gpt-6.1-sol", "low")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", MMP_TEST_VERSION=version)
        arg = json.dumps({"version": version, "tests": str(_testenv.HERE), "out": str(out), "provider": provider,
                          "channel": channel, "model": model, "effort": effort})
        p = subprocess.run([sys.executable, "-B", "-c", REGRESSION_SCRIPT, arg], capture_output=True, timeout=120, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace")[-2000:])
        res = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])
        return res, (out / "transcript.corrected.md").read_bytes(), out

    def test_four_channels_bit_identical(self):
        for provider, channel in CHANNELS:
            with self.subTest(provider=provider, channel=channel):
                old, old_md, _ = self.run_version("2.1.0", provider, channel)
                new, new_md, out = self.run_version(_testenv.VERSION, provider, channel)
                self.assertEqual(old["status"], "ok")
                self.assertGreaterEqual(len(old["records"]), 3)                       # 用字表＋至少 2 段
                self.assertEqual(new["records"], old["records"])
                self.assertEqual(new_md, old_md)
                self.assertFalse((out / "reference.json").exists())


@unittest.skipUnless(V22 and HAS_FFMPEG, "2.2.0 才有；要有 ffmpeg")
class RefsRun(RefsBase):
    """§6、§8、§11.4：帶截圖、說明檔、文件的 run()（假的呼叫器）。"""

    def test_full_flow(self):
        self.materials()
        home_before = self.home_files()
        fake = RefsFake(FakeModel(fix={"密等": "冪等", "卡夫卡": "Kafka"},
                                  terms=[{"wrong": ["延持"], "right": "延遲", "confidence": "high", "reason": "r"}]))
        self.use(fake, model="opus", effort="medium")
        cfg = self.cfg(chunk_chars=40)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = ac.run(self.out, ac.resolve_request(cfg), cfg=cfg, consent=True)
        self.assertEqual((res["status"], ac.exit_code(res)), ("ok", 0), res)
        console = err.getvalue()
        self.assertIn("逐字稿文字、截圖 3 張、會議文件 1 份的名詞與段落、背景說明會送到 " + _testenv.vendor("claude"), console)
        self.assertIn("參考資料：截圖 3 張、與會者 3 位、講者對應 2 個", console)
        # correct.refs：一次、附 3 張圖、圖在呼叫時存在、呼叫後暫存資料夾已刪
        rc = fake.refs_calls()
        self.assertEqual(len(rc), 1)
        self.assertEqual(rc[0]["system"], ac.SYSTEM_REFS)
        self.assertEqual((len(rc[0]["images"]), rc[0]["exists"]), (3, [True, True, True]))
        self.assertTrue(all(not Path(i).exists() for i in rc[0]["images"]))
        self.assertFalse(Path(rc[0]["images"][0]).parent.exists())
        self.assertTrue(Path(rc[0]["images"][0]).parent.name.startswith("mmp-refs-"))
        u = rc[0]["user"]
        self.assertIn("## 背景說明（使用者提供）\n示範證券上線週會。常用寫法：Grafana、Prometheus", u)
        self.assertIn("## 會議文件的用字（本機抽出）\n", u)
        self.assertIn("Redis Sentinel", u)
        self.assertIn("## 會議文件的相關段落（本機抽出）\n- （demo.議程.md）今天確認卡夫卡的延遲與冪等設計", u)
        self.assertIn("## 截圖（依時間順序，圖片依序附在訊息裡）\n1. 時間碼 00:00:01（frame_0001.jpg）\n"
                      "2. 時間碼 00:00:25（frame_0002.jpg）\n3. 時間碼 00:01:01（frame_0003.jpg）", u)
        self.assertNotIn("frames", [p.name for p in self.out.iterdir() if p.name.startswith("mmp-")])
        # 名詞階段與各段：三節＋規則 11
        terms_call, chunk_calls = fake.other_calls()[0], fake.other_calls()[1:]
        self.assertTrue(terms_call["schema"])
        self.assertTrue(terms_call["system"].endswith(ac.TERMS_REFS_NOTE))
        self.assertTrue(terms_call["user"].startswith("## 背景說明（使用者提供）\n"))
        self.assertLess(terms_call["user"].index("## 參考資料用字"), terms_call["user"].index("## 逐字稿"))
        self.assertGreaterEqual(len(chunk_calls), 2)
        for c in chunk_calls:
            self.assertEqual(c["system"], ac.SYSTEM_CORRECT + ac.RULE_REFS)
            self.assertIn("## 與會者（參考資料：截圖）\n- 陳怡君（專案經理）＝S1\n- 林家豪（SRE）＝S2\n- 張雅婷（後端）\n", c["user"])
            self.assertIn("## 參考資料用字（截圖、會議文件）\nKafka、冪等、", c["user"])
            self.assertLess(c["user"].index("## 參考資料用字"), c["user"].index("## 確定用字"))
            self.assertNotIn("## 會議文件的相關段落", c["user"])                     # 段落不進各段校正（§5.4）
        # reference.json
        ref = json.loads((self.out / "reference.json").read_text(encoding="utf-8"))
        self.assertEqual(ref["by"], {"provider": "claude", "model": "opus", "effort": "medium", "channel": "cli",
                                     "stage": "correct.refs"})
        self.assertEqual(ref["speakers"], {"S1": {"name": "陳怡君", "evidence": "截圖 00:00:01 正在發言"},
                                           "S2": {"name": "林家豪", "evidence": "截圖 00:00:25 正在發言"}})
        self.assertEqual(ref["sources"]["frames"], {"available": 3, "sent": 3, "dropped": {}, "max_px": 1280})
        self.assertEqual(ref["meeting"]["date"], "2026-11-03")
        self.assertEqual([f["file"] for f in ref["frames"]], ["frame_0001.jpg", "frame_0002.jpg", "frame_0003.jpg"])
        # 校正版：表頭下一行、講者對應、依據
        md = (self.out / "transcript.corrected.md").read_text(encoding="utf-8").split("\n")
        self.assertTrue(md[2].startswith("> 原始逐字稿：`transcript.md`（未修改）｜"))
        self.assertEqual(md[3], "> 參考資料：截圖 3 張、會議文件 1 份、背景說明（人名與名詞寫法參考；內容以逐字稿為準）")
        self.assertIn("| S1 | 陳怡君（專案經理） | 截圖 00:00:01 正在發言 |", md)
        self.assertIn("| S2 | 林家豪（SRE） | 截圖 00:00:25 正在發言 |", md)
        self.assertIn("| S3 | （待確認） |  |", md)
        self.assertIn("| 2 | 密等 | 冪等 | 3 | 參考資料 | ✅ 待確認 |", md)
        # auto_correct.json、res、run_log
        rec = json.loads((self.out / "auto_correct.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["reference"], {"status": "ok", "reason": None, "frames_sent": 3, "docs_read": 1, "docs_skipped": {},
                                            "terms": rec["reference"]["terms"], "participants": 3, "speakers_mapped": 2,
                                            "file": "reference.json"})
        self.assertEqual(res["reference"], rec["reference"])
        evs = self.events()
        cp = [e for e in evs if e["event"] == "checkpoint" and e["name"] == "correct.refs"]
        self.assertEqual(len(cp), 1)
        for k in ("status", "frames_available", "frames_sent", "frames_dropped", "frame_px", "docs_read", "docs_skipped",
                  "doc_chars", "terms", "terms_chars", "paragraphs", "paragraphs_chars", "context_chars", "participants",
                  "speakers_mapped", "duration_ms"):
            self.assertIn(k, cp[0], k)
        names = [e.get("name") for e in evs if e["event"] == "checkpoint"]
        self.assertLess(names.index("correct.refs"), names.index("correct.terms"))
        calls = [e for e in evs if e["event"] == "call"]
        self.assertEqual([(c.get("stage"), c.get("images")) for c in calls][:2], [("correct.refs", 3), ("correct.terms", None)])
        self.assertTrue(all("images" not in c for c in calls[1:]))
        # §11.4：log 只有數量與原因代碼；$MMH 沒有新檔
        new_home = sorted(set(self.home_files()) - set(home_before))
        self.assertEqual([p.replace("\\", "/") for p in new_home], ["logs", "logs/runs.jsonl"])   # 只有 2.1.0 就有的執行摘要
        log_text = (self.out / "run_log.jsonl").read_text(encoding="utf-8") + (self.home / "logs" / "runs.jsonl").read_text(
            encoding="utf-8")
        contents = ["陳怡君", "林家豪", "張雅婷", "示範證券 v3 上線準備會議", "Redis Sentinel", "Grafana", "Prometheus",
                    "今天確認卡夫卡的延遲與冪等設計", "示範證券上線週會。常用寫法"]
        for s in contents:                                                           # 名詞、人名、內容：6 字片段
            for frag in ([s] if len(s) < 6 else [s[i:i + 6] for i in range(len(s) - 5)]):
                self.assertNotIn(frag, log_text, s)
        for name in ("demo.議程.md", "demo.context.md", "frame_0001.jpg", "議程"):        # 檔名：整個檔名
            self.assertNotIn(name, log_text)
        self.assertFalse(list(self.home.rglob("reference.json")) + list(self.home.rglob("context.md")))

    def test_no_refs_same_as_before(self):
        write_out(self.out, PARAS)
        fake = RefsFake(FakeModel())
        self.use(fake)
        ac.run(self.out, ac.resolve_request({}), cfg={}, consent=True)
        self.assertEqual(fake.refs_calls(), [])
        self.assertEqual(fake.calls[0]["system"], ac.SYSTEM_CORRECT)
        self.assertFalse((self.out / "reference.json").exists())
        self.assertNotIn("correct.refs", (self.out / "run_log.jsonl").read_text(encoding="utf-8"))
        self.assertNotIn("> 參考資料：", (self.out / "transcript.corrected.md").read_text(encoding="utf-8"))

    def test_all_three_flags_off(self):
        self.materials()
        fake = RefsFake(FakeModel())
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={}, consent=True,
                     refs_opts={"no_refs": True, "no_context": True, "no_frames": True})
        self.assertEqual(res["status"], "ok")
        self.assertNotIn("reference", res)
        self.assertEqual(fake.refs_calls(), [])
        self.assertEqual(fake.calls[0]["system"], ac.SYSTEM_CORRECT)
        self.assertTrue(fake.calls[0]["user"].startswith("## 要校正的逐字稿"))
        self.assertFalse((self.out / "reference.json").exists())

    def test_text_only_sources_no_refs_call(self):
        self.materials(frames=False)
        fake = RefsFake(FakeModel())
        self.use(fake)
        res = ac.run(self.out, ac.resolve_request({}), cfg={}, consent=True)
        self.assertEqual(fake.refs_calls(), [])                                      # 只有文字 → 不呼叫 correct.refs
        self.assertEqual(res["reference"]["status"], "skipped")
        ref = json.loads((self.out / "reference.json").read_text(encoding="utf-8"))
        self.assertIsNone(ref["by"])
        self.assertEqual((ref["participants"], ref["speakers"], ref["frames"]), ([], {}, []))
        self.assertEqual(fake.calls[0]["system"], ac.SYSTEM_CORRECT + ac.RULE_REFS)
        self.assertIn("## 背景說明（使用者提供）", fake.calls[0]["user"])
        md = (self.out / "transcript.corrected.md").read_text(encoding="utf-8")
        self.assertIn("> 參考資料：會議文件 1 份、背景說明（", md)

    def test_no_frames_flag_and_config(self):
        self.materials()
        for kw in ({"refs_opts": {"no_frames": True}}, {"cfg": {"reference": {"frames": False}}},
                   {"cfg": {"reference": {"max_frames": 0}}}):
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                fake = RefsFake(FakeModel())
                self.use(fake)
                ac.run(self.out, ac.resolve_request({}), cfg=kw.get("cfg", {}), consent=True, force=True,
                       refs_opts=kw.get("refs_opts"))
                self.assertEqual(fake.refs_calls(), [])
                ref = json.loads((self.out / "reference.json").read_text(encoding="utf-8"))
                self.assertEqual(ref["sources"]["frames"]["sent"], 0)

    def test_context_flag_written_even_when_skipped(self):
        write_out(self.out, PARAS)
        (self.out / "transcript.corrected.md").write_text("old", encoding="utf-8")
        self.use(RefsFake(FakeModel()))
        res = ac.run(self.out, ac.resolve_request({}), cfg={}, refs_opts={"context": "本場重點：上線日期"})
        self.assertEqual((res["status"], res["reason"]), ("skipped", "exists"))
        self.assertIn("本場重點：上線日期", (self.out / "context.md").read_text(encoding="utf-8"))
        fake = RefsFake(FakeModel())
        self.use(fake)
        ac.run(self.out, ac.resolve_request({}), cfg={}, force=True)                    # 重跑沿用 context.md
        self.assertIn("## 背景說明（使用者提供）\n本場重點：上線日期", fake.calls[0]["user"])

    def test_refs_option_and_cli_flags(self):
        ap = argparse.ArgumentParser()
        ac.add_ref_options(ap)
        args = ap.parse_args(["--context", "一行", "--refs", "a.pdf", "--refs", "dir", "--no-frames"])
        self.assertEqual(ac.ref_options_of(args), {"context": "一行", "refs": ["a.pdf", "dir"], "no_refs": False,
                                                   "no_context": False, "no_frames": True})
        ap2 = argparse.ArgumentParser()
        ac.add_ref_options(ap2, frames=False)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            ap2.parse_args(["--no-frames"])


@unittest.skipUnless(V22 and HAS_FFMPEG, "2.2.0 才有；要有 ffmpeg")
class RefsFallback(RefsBase):
    """§4.5、§11.2：送圖失敗的退回（四通道各一）、重試、STOP_ALL。"""

    def reject(self, channel):
        if channel == "cli":
            return ac._fail("cli_incompatible", detail="unknown option '--input-format'")
        return ac._fail("cli_error", 400, "Invalid request: image content is not supported")

    def go(self, script, provider="claude", channel="cli"):
        self.materials(context=False)
        fake = RefsFake(FakeModel(fix={"密等": "冪等"}), script=script)
        self.use(fake, provider=provider, channel=channel)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            res = ac.run(self.out, ac.resolve_request({}), cfg={}, consent=True)
        cp = [e for e in self.events() if e["event"] == "checkpoint" and e["name"] == "correct.refs"][0]
        return res, fake, cp, err.getvalue()

    def test_image_rejected_text_only_retry(self):
        for provider, channel in CHANNELS:
            with self.subTest(provider=provider, channel=channel):
                self.setUp()
                res, fake, cp, _ = self.go([self.reject(channel), None], provider, channel)
                rc = fake.refs_calls()
                self.assertEqual([c["images"] is not None for c in rc], [True, False])     # 不附圖重試一次
                self.assertNotIn("## 截圖", rc[1]["user"])
                self.assertEqual((res["status"], cp["status"], cp["images_fallback"], cp["frames_sent"]),
                                 ("ok", "ok", "text_only", 0))
                ref = json.loads((self.out / "reference.json").read_text(encoding="utf-8"))
                self.assertEqual((ref["speakers"], ref["frames"]), ({}, []))
                self.tearDown()

    def test_image_rejected_then_fails_correction_continues(self):
        for provider, channel in CHANNELS:
            with self.subTest(provider=provider, channel=channel):
                self.setUp()
                res, fake, cp, console = self.go([self.reject(channel), ac._fail("cli_error", detail="x")], provider, channel)
                self.assertEqual((res["status"], ac.exit_code(res)), ("ok", 0))
                self.assertEqual((cp["status"], cp["reason"], cp["images_fallback"]), ("failed", "cli_error", "text_only"))
                self.assertIn("[!] 截圖整理失敗（cli_error），只用文件與背景說明", console)
                self.assertEqual(len(fake.other_calls()), 1)                                # 校正照常跑
                ref = json.loads((self.out / "reference.json").read_text(encoding="utf-8"))
                self.assertEqual(ref["participants"], [])
                self.assertIn("Redis Sentinel", ref["doc_terms"])                          # 本機的文件篩選結果照用
                self.tearDown()

    def test_stop_all_stops_correction(self):
        for provider, channel in CHANNELS:
            with self.subTest(provider=provider, channel=channel):
                self.setUp()
                res, fake, cp, _ = self.go([ac._fail("auth_failed", 401)], provider, channel)
                self.assertEqual((res["status"], res["reason"], ac.exit_code(res)), ("failed", "auth_failed", 3))
                self.assertEqual(fake.other_calls(), [])
                self.assertEqual(len(fake.refs_calls()), 1)
                self.tearDown()

    def test_retry_rules(self):
        cases = [([ac._fail("timeout"), None], 2, "ok"), ([ac._fail("server_error"), ac._fail("server_error")], 2, "failed"),
                 ([ac._fail("validation_failed"), None], 2, "ok"), ([ac._fail("tool_use_detected")], 1, "failed"),
                 ([ac._fail("cli_error")], 1, "failed"), ([ac._fail("refusal")], 1, "failed")]
        for script, n, status in cases:
            with self.subTest(reason=script[0]["reason"]):
                self.setUp()
                res, fake, cp, _ = self.go(list(script))
                self.assertEqual((len(fake.refs_calls()), cp["status"], res["status"]), (n, status, "ok"))
                self.tearDown()

    def test_schema_mismatch_is_validation_failed(self):
        bad = ac._ok("{}", {"participants": "x"}, {}, "m")
        res, fake, cp, _ = self.go([bad, bad])
        self.assertEqual((len(fake.refs_calls()), cp["status"], cp["reason"], res["status"]), (2, "failed", "validation_failed", "ok"))


if __name__ == "__main__":
    unittest.main()
