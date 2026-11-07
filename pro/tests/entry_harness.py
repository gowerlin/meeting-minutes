"""入口（mm-sendto.ps1／mm-dropped.sh）流程實測（1.2.0 起；〔2.0.0〕規格 §10.2 E-1）：假 runtime＋假 claude／codex，以 stdin 餵答案。

- 假 runtime：暫存目錄裡的 venv（由已安裝 runtime 的 venv 建，`--without-pip`，不寫入已安裝的 venv）、
  真的 runlog.py／common.py／pricing.json，假的 transcribe.py／auto_correct.py／auto_minutes.py（記下參數、寫假輸出）。
- 假 CLI：bin/claude(.cmd)、bin/codex(.cmd)；`codex login status` 的 exit code 由 FAKE_CODEX_LOGIN 決定。
- 隔離：USERPROFILE／APPDATA／LOCALAPPDATA／HOME 指向暫存目錄、PATH 只留系統目錄與（依情境）假 bin，找不到真的 claude／codex。
- 不呼叫任何模型。
- 〔2.0.0〕入口多一題「內容類型」（第一題）：1.x 的情境在 2.0 自動在答案最前面補一個 Enter（＝會議）；
  2.0 才有的情境（v2_scenarios）只在測 2.0 時跑：upgraded_122、type_course_skip、template_menu、remember_last、state_unwritable 等。
- 〔2.0.1〕第一次執行（沒有 state.json）、壞掉的 state.json、空的 state.json 三個情境；並且**每個情境**都檢查
  主控台（stdout）與 stderr 沒有錯誤訊息（ERROR_MARKERS：PowerShell 的錯誤記錄、bash 的錯誤、Python Traceback）。
  測 2.0.1 以後自動開啟；`MMP_TEST_NOERR=1` 可對舊版開啟（對照組：2.0.0 的 PowerShell 入口第一次執行會印 Get-Content 錯誤）。
- 〔2.1.0〕網頁版（規格 2.1.0 §7.1）：假 auto_minutes.py 在 runtime 有 `common.html_setting`（2.1.0 起）時，照真的 auto_minutes.py
  寫 `auto_minutes.json` 的 `html` 與 `.html` 檔（讀 config.json 的 `html.enabled`、`--no-html`）；`FAKE_HTML` 決定結果：
  `found`（預設）／`explicit`／`none`／`unsupported`／`off`（＝`media`）、`failed:<reason>`（`status: failed`）。
  v21_scenarios：可點播放／時間碼為文字的說明、非會議類型、設定關閉、失敗的黃字、沒整理時不列；2.0.2 config 升級（upgraded_202）。
  檢查 `rows`：結束畫面的檔案列（依序）；1.x／2.0.x 升級的情境在 2.1.0 只多 `.html` 一列（測 2.0.2 時同一份清單去掉 `.html`）。

用法：python entry_harness.py --work <暫存目錄> [--shell pwsh powershell bash] [--only 情境名 ...]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _testenv  # noqa: E402

RUNTIME = _testenv.RUNTIME
INSTALLED_PY = Path(os.environ.get("LOCALAPPDATA", "")) / "meeting-minutes-pro" / "venv" / "Scripts" / "python.exe"
M1 = HERE / "_out" / "runs" / "M1-turbo"
GIT_BASH = Path(os.environ.get("MMP_GIT_BASH", "C:/Program Files/Git/bin/bash.exe"))   # 不要用 System32 的 WSL bash
# 〔2.0.1〕主控台與 stderr 不得出現的錯誤訊息片段（PowerShell 5.1／7 的錯誤記錄、bash、Python）
NOERR = _testenv.VER >= (2, 0, 1) or os.environ.get("MMP_TEST_NOERR") == "1"
ERROR_MARKERS = ("CategoryInfo", "FullyQualifiedErrorId", "Get-Content", "Select-String", "ConvertFrom-Json", "Exception",
                 "Line |", "+ ~", "Traceback", "No such file or directory", "command not found", "Permission denied",
                 "unbound variable", "syntax error")
V21 = _testenv.VER >= (2, 1, 0)          # 〔2.1.0〕網頁版
# 結束畫面列的檔名（兩支入口的清單，依序）；rows 檢查只看這些
END_ROW_NAMES = ("meeting-minutes.md", "meeting-minutes.html", "notes.md", "notes.html", "notes.json", "transcript.corrected.md",
                 "corrections.suggested.tsv", "transcript.md", "transcript.srt", "transcript.cues.srt",
                 "transcript.corrected.srt", "frames")

FAKE_TRANSCRIBE = r'''
import json, os, shutil, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog
mmh = Path(os.environ["MEETING_MINUTES_PRO_HOME"])
with open(mmh / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"script": "transcribe", "argv": sys.argv[1:], "run_id": os.environ.get("MMP_RUN_ID")}, ensure_ascii=False) + "\n")
src = Path(sys.argv[1])
out = src.with_name(src.stem + "_minutes")
out.mkdir(exist_ok=True)
for n in ("transcript.md", "transcript.json", "transcript.srt"):
    shutil.copy(mmh / "fixture" / n, out / n)
# 〔2.0.0〕字幕檔與 meta（FAKE_META：JSON，合併進 transcript.json 的 meta，例如 diarization.fallback、speaker_stats）
(out / "transcript.cues.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nfake\n", encoding="utf-8")
if os.environ.get("FAKE_META"):
    doc = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    doc.setdefault("meta", {}).update(json.loads(os.environ["FAKE_META"]))
    (out / "transcript.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
a = sys.argv[1:]
ctype = a[a.index("--type") + 1] if "--type" in a else None
dur = float(os.environ.get("FAKE_DURATION", "576.5"))
rl = runlog.RunLog(out, step="transcribe")
with rl.checkpoint("asr") as cp:
    time.sleep(0.05); cp["segments"] = 39
rl.event("info", source=src.name, recording_sec=dur, segments=39, paragraphs=33, speakers=4, asr_model="turbo", device="fake")
print("  [fake] 轉寫完成", file=sys.stderr)
print(json.dumps({"out_dir": str(out), "duration": dur, "run_id": rl.run_id, "correction": None, "content_type": ctype,
                  "subtitles": {"cues": {"status": "ok", "cues": 39}}}, ensure_ascii=False))
if rl.owns:
    rl.finish()
'''

FAKE_STEP = r'''
import json, os, sys, time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog
KIND = "%s"
mmh = Path(os.environ["MEETING_MINUTES_PRO_HOME"])
with open(mmh / "calls.jsonl", "a", encoding="utf-8") as f:
    f.write(json.dumps({"script": KIND, "argv": sys.argv[1:], "run_id": os.environ.get("MMP_RUN_ID")}, ensure_ascii=False) + "\n")
out = Path(sys.argv[1])
a = sys.argv[1:]
prov = a[a.index("--correct-provider" if KIND == "correction" else "--minutes-provider") + 1]
model = a[a.index("--correct-model" if KIND == "correction" else "--minutes-model") + 1]
rl = runlog.RunLog(out, step=KIND)
t0 = runlog.now()
rl.call({"provider": prov, "channel": "cli", "model": model, "effort": "low", "auth": "chatgpt" if prov == "openai" else "subscription"},
        {"ok": True, "usage": {"input": 9000, "output": 3000, "cache_read": 1000, "cache_write": 0}, "model": model},
        t0, runlog.now(), 0.01, stage=KIND)
rl.event("checkpoint", name=("correct" if KIND == "correction" else "minutes"), started_at=runlog.iso(t0),
         ended_at=runlog.iso(runlog.now()), duration_sec=0.02)
fail = os.environ.get("FAKE_FAIL_" + KIND.upper())
if fail:
    print(json.dumps({KIND: {"status": "failed", "reason": fail, "provider": prov}}, ensure_ascii=False)); sys.exit(3)
name = "transcript.corrected.md" if KIND == "correction" else "meeting-minutes.md"
extra = {}
if KIND == "minutes":                                   # 〔2.0.0〕非會議類型輸出 notes.md／notes.json
    ctype = a[a.index("--type") + 1] if "--type" in a else "meeting"
    if "--template" in a:
        import templates
        ctype = templates.load(a[a.index("--template") + 1])["base"]
    if ctype != "meeting":
        name = "notes.md"
        (out / "notes.json").write_text("{}", encoding="utf-8")
    extra["content_type"] = ctype
else:
    (out / "transcript.corrected.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nfake\n", encoding="utf-8")
    extra["subtitles"] = {"status": "ok", "cues": 40, "map_failed_paragraphs": 0, "doc_level": False}
(out / name).write_text("# fake\n", encoding="utf-8")
import common
if KIND == "minutes" and hasattr(common, "html_setting"):   # 〔2.1.0〕網頁版：同真的 auto_minutes.py 的 auto_minutes.json／stdout
    mode = os.environ.get("FAKE_HTML", "found")
    hname = name[:-3] + ".html"
    if not common.html_setting(common.load_config(), "enabled") or "--no-html" in a:
        h = {"status": "skipped", "reason": "disabled", "output": None, "media": None, "timecodes": None}
    elif mode.startswith("failed:"):
        h = {"status": "failed", "reason": mode[7:], "output": None, "media": None, "timecodes": None}
    else:
        (out / hname).write_text("<!doctype html>\n", encoding="utf-8")
        h = {"status": "ok", "reason": None, "output": hname, "media": mode, "timecodes": 3}
    (out / "auto_minutes.json").write_text(json.dumps({"version": common.VERSION, "status": "ok", "html": h}), encoding="utf-8")
    extra["html"] = {k: h[k] for k in ("status", "reason", "output", "media")}
print(json.dumps({KIND: dict({"status": "ok", "reason": None, "provider": prov, "model": model, "chunks": 1, "chunks_ok": 1,
                              "parts": 1, "parts_ok": 1}, **extra)}, ensure_ascii=False))
'''

V110_CONFIG = {"backend": "openvino", "device": "NPU", "whisper": "turbo", "runtime_version": "1.1.0",
               "correction": {"enabled": False, "provider": "auto", "channel": "cli", "chunk_chars": 3500,
                              "timeout_sec": 600, "confirm_over_minutes": 120,
                              "claude": {"model": "opus", "effort": "medium", "cli_path": None},
                              "openai": {"model": "gpt-6.1-sol", "effort": "low", "cli_path": None}}}


def make_runtime(work: Path) -> Path:
    mmh = work / "mmh"
    if mmh.exists():
        shutil.rmtree(mmh)
    (mmh / "scripts").mkdir(parents=True)
    if not (work / "venv").exists():
        subprocess.run([str(INSTALLED_PY), "-B", "-m", "venv", "--without-pip", str(work / "venv")], check=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    shutil.copytree(work / "venv", mmh / "venv")
    # Git Bash 測 mm-dropped.sh：venv/bin/python 轉到 Scripts/python.exe
    (mmh / "venv" / "bin").mkdir(exist_ok=True)
    (mmh / "venv" / "bin" / "python").write_text('#!/bin/bash\nexec "$(dirname "$0")/../Scripts/python.exe" "$@"\n',
                                                 encoding="utf-8", newline="\n")
    for n in ("runlog.py", "common.py", "pricing.json", "templates.py", "content_types.py", "diarize.py"):
        if (RUNTIME / "scripts" / n).exists():          # 〔2.0.0〕範本選單與退回原因用到後三個（1.x 沒有）
            shutil.copy(RUNTIME / "scripts" / n, mmh / "scripts" / n)
    (mmh / "scripts" / "transcribe.py").write_text(FAKE_TRANSCRIBE, encoding="utf-8")
    (mmh / "scripts" / "auto_correct.py").write_text(FAKE_STEP % "correction", encoding="utf-8")
    (mmh / "scripts" / "auto_minutes.py").write_text(FAKE_STEP % "minutes", encoding="utf-8")
    for n in ("mm-sendto.ps1", "mm-dropped.sh"):
        shutil.copy(RUNTIME / n, mmh / n)
    (mmh / "fixture").mkdir()
    for n in ("transcript.md", "transcript.json", "transcript.srt"):
        shutil.copy(M1 / n, mmh / "fixture" / n)
    bin_ = work / "bin"
    if bin_.exists():
        shutil.rmtree(bin_)
    bin_.mkdir()
    for name in ("claude", "codex"):
        (bin_ / f"{name}.cmd").write_text(
            "@echo off\r\nif \"%1\"==\"login\" exit /b %FAKE_CODEX_LOGIN%\r\necho fake 1.0\r\n", encoding="ascii")
        sh = bin_ / name
        sh.write_text('#!/bin/bash\nif [ "$1" = "login" ]; then exit "${FAKE_CODEX_LOGIN:-0}"; fi\necho fake 1.0\n',
                      encoding="utf-8", newline="\n")
    return mmh


# 情境：名稱 → (CLI, codex 登入, config, 秒數, 答案, 檢查)
# 答案順序：人數、專有名詞、①、①選模型、②、②選模型、按 Enter 關閉（沒有出現的題目不要給）
def scenarios():
    def calls(*kinds):
        return ("calls", list(kinds))
    V = _testenv.VERSION                 # 〔1.2.1〕版號取測試的版本目錄（MMP_TEST_VERSION），不寫死
    extra = {}
    if tuple(int(x) for x in V.split(".")) >= (1, 2, 1):
        # 〔1.2.1〕② 會議摘要選單的 sonnet 註記改成「較快」；① 校正選單維持「準確率較低」
        extra["sonnet_notes"] = (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", ""],
                                 [calls("transcribe", "correction", "minutes"),
                                  ("text", "[3] Claude sonnet（準確率較低）："),
                                  ("text", "[3] Claude sonnet（較快，約 sol 1/3 時間；可能漏 1～2 項待辦）："),
                                  ("count", "（準確率較低）", 1), ("count", "（較快，約 sol 1/3 時間；可能漏 1～2 項待辦）", 1)])
    legacy = {**extra,
        "both_enter": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", ""],
                       [calls("transcribe", "correction", "minutes"),
                        ("arg", "correction", "openai", "gpt-6.1-sol"), ("arg", "minutes", "openai", "gpt-6.1-sol"),
                        ("prompt", "要做 AI 校正嗎？[Y/n]"), ("prompt", "要產生會議摘要嗎？[Y/n]"),
                        ("text", "meeting-minutes.md"), ("text", "runs.jsonl"), ("runs", 1),
                        ("text", f"==== 會議轉寫（Pro）　meeting-minutes-pro {V} ===="), ("notext", "不一致")]),
        "version_mismatch": (["claude", "codex"], 0, {"runtime_version": "1.1.0"}, None, ["", "", "n", "n", ""],
                             [calls("transcribe"),
                              ("text", f"meeting-minutes-pro {V}（config.json 的 runtime_version 是 1.1.0，版號不一致：請重新執行安裝程式）")]),
        "both_no": (["claude", "codex"], 0, {}, None, ["", "", "n", "n", ""],
                    [calls("transcribe"), ("text", "略過AI 校正"), ("text", "略過會議摘要"), ("runs", 1)]),
        "corr_no_min_yes": (["claude", "codex"], 0, {}, None, ["", "", "n", "y", "", ""],
                            [calls("transcribe", "minutes"), ("text", "依 transcript.md 整理")]),
        "pick_models": (["claude", "codex"], 0, {}, None, ["4", "名詞A", "y", "2", "", "3", ""],
                        [calls("transcribe", "correction", "minutes"), ("arg", "correction", "claude", "opus"),
                         ("arg", "minutes", "claude", "sonnet"), ("targ", "--speakers"), ("text", "依校正版逐字稿整理")]),
        "no_cli": ([], 0, {}, None, ["", "", ""],
                   [calls("transcribe"), ("notext", "AI 校正："), ("text", "找不到 claude 或 codex 指令：略過 AI 校正與會議摘要"),
                    ("text", "codex login"), ("text", "用 meeting-minutes-pro 整理這份會議記錄")]),
        "only_claude": (["claude"], 0, {}, None, ["", "", "", "", "", "", ""],
                        [calls("transcribe", "correction", "minutes"), ("arg", "correction", "claude", "opus"),
                         ("notext", "OpenAI gpt-6.1-sol："), ("text", "[2] Claude sonnet")]),
        "codex_not_logged_in": (["claude", "codex"], 1, {}, None, ["", "", "", "", "", "", ""],
                                [calls("transcribe", "correction", "minutes"), ("arg", "correction", "claude", "opus"),
                                 ("text", "Codex 尚未登入，這次用 Claude")]),
        "only_codex_not_logged_in": (["codex"], 1, {}, None, ["", "", ""],
                                     [calls("transcribe"), ("text", "Codex 尚未登入（在終端機執行 codex login）"),
                                      ("notext", "AI 校正：")]),
        "upgraded_110_config": (["claude", "codex"], 0, "v110", None, ["", "", "", "", "", "", ""],
                                [calls("transcribe", "correction", "minutes"), ("prompt", "要做 AI 校正嗎？[Y/n]"),
                                 ("prompt", "要產生會議摘要嗎？[Y/n]"), ("rows", MEETING_ROWS)]),
        "ask_default_false": (["claude", "codex"], 0, {"correction": {"ask_default": False}, "minutes": {"ask_default": False}},
                              None, ["", "", "", "", ""],
                              [calls("transcribe"), ("prompt", "要做 AI 校正嗎？[y/N]"), ("prompt", "要產生會議摘要嗎？[y/N]")]),
        "long_meeting": (["claude", "codex"], 0, {}, "13620", ["", "", "", "", "n", ""],
                         [calls("transcribe", "correction"), ("text", "⚠ 錄音長 3 小時 47 分：AI 校正：OpenAI gpt-6.1-sol（產出 transcript.corrected.md，原稿不改）：約 25～26 分鐘"), ("text", "⚠ 錄音長 3 小時 47 分：會議摘要：")]),
        "correction_fails": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", ""],
                             [calls("transcribe", "correction", "minutes"), ("text", "Codex 尚未登入，AI 校正未完成")]),
    }
    if _testenv.VER < (2, 0, 0):
        return legacy
    # 〔2.0.0〕1.x 的情境：第一題（內容類型）按 Enter＝會議，其餘答案與檢查不變
    out = {k: v[:4] + ([""] + v[4],) + v[5:] for k, v in legacy.items()}
    out.update(v2_scenarios())
    if NOERR:
        out.update(v201_scenarios())
    if V21:
        out.update(v21_scenarios())
    return out


# 〔2.1.0〕結束畫面的檔案列（依序）：會議、全部按 Enter（校正＋整理）；2.1.0 起多 meeting-minutes.html 一列
MEETING_ROWS = [n for n in ("meeting-minutes.md", "meeting-minutes.html", "transcript.corrected.md", "transcript.md",
                            "transcript.srt", "transcript.cues.srt", "transcript.corrected.srt") if V21 or not n.endswith(".html")]
NEXT_MEETING = "下一步：打開 meeting-minutes.html（用瀏覽器）確認決議與待辦" if V21 else "下一步：打開 meeting-minutes.md 確認決議與待辦"
NEXT_NOTES = "下一步：打開 notes.html（用瀏覽器）確認內容" if V21 else "下一步：打開 notes.md 確認內容"


def v21_scenarios():
    """〔2.1.0〕網頁版（規格 2.1.0 §7.1）：不加題目（答案與 2.0.2 相同）；結束畫面列 .html、括號依 auto_minutes.json 的
    html.media；html.enabled 關或沒有產生時不列；失敗時一行說明與 render_html.py 補做的指令。"""
    def calls(*kinds):
        return ("calls", list(kinds))
    all3 = ["", "", "", "", "", "", "", ""]
    play = "會議記錄網頁版（用瀏覽器開；時間碼可點播放）"
    text_ = "會議記錄網頁版（用瀏覽器開；時間碼為文字）"
    base = [calls("transcribe", "correction", "minutes"), ("rows", MEETING_ROWS), ("text", NEXT_MEETING),
            ("text", "附上 meeting-minutes.md 與 transcript.corrected.md。"), ("notext", "網頁版未產生")]
    out = {
        "html_found": (["claude", "codex"], 0, {}, None, all3, base + [("text", play), ("notext", "時間碼為文字")]),
        "html_explicit": (["claude", "codex"], 0, {}, None, all3, base + [("text", play)], {"env": {"FAKE_HTML": "explicit"}}),
    }
    for m in ("none", "unsupported", "off"):
        out[f"html_text_{m}"] = (["claude", "codex"], 0, {}, None, all3, base + [("text", text_), ("notext", "可點播放")],
                                 {"env": {"FAKE_HTML": m}})
    no_html = [("notext", "meeting-minutes.html"), ("notext", "網頁版"), ("text", "下一步：打開 meeting-minutes.md 確認決議與待辦"),
               ("rows", [n for n in MEETING_ROWS if not n.endswith(".html")])]
    out.update({
        "html_course": (["claude", "codex"], 0, {}, None, ["2", "", "", "", "", "", "", ""],
                        [calls("transcribe", "correction", "minutes"), ("text", "課程筆記網頁版（用瀏覽器開；時間碼可點播放）"),
                         ("text", NEXT_NOTES), ("text", "附上 notes.md 與 transcript.corrected.md。"),
                         ("rows", ["notes.md", "notes.html", "notes.json", "transcript.corrected.md", "transcript.md",
                                   "transcript.srt", "transcript.cues.srt", "transcript.corrected.srt"])]),
        "html_disabled": (["claude", "codex"], 0, {"html": {"enabled": False}}, None, all3,
                          [calls("transcribe", "correction", "minutes")] + no_html),
        "html_failed": (["claude", "codex"], 0, {}, None, all3,
                        [calls("transcribe", "correction", "minutes"), ("notext", "會議記錄網頁版"),
                         ("text", "網頁版未產生（找不到網頁版樣板 html_template.html）；可執行 render_html.py 補做："),
                         ("text", "render_html.py\" \""), ("text", "下一步：打開 meeting-minutes.md 確認決議與待辦"),
                         ("rows", [n for n in MEETING_ROWS if not n.endswith(".html")])],
                        {"env": {"FAKE_HTML": "failed:template_missing"}}),
        "html_failed_internal": (["claude", "codex"], 0, {}, None, all3,
                                 [calls("transcribe", "correction", "minutes"),
                                  ("text", "網頁版未產生（程式錯誤）；可執行 render_html.py 補做")],
                                 {"env": {"FAKE_HTML": "failed:internal_error"}}),
        # 沒有整理（② 回答 n）：沒有 auto_minutes.json，不列網頁版、不說明失敗
        "html_minutes_no": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "n", ""],
                            [calls("transcribe", "correction"), ("notext", "網頁版"), ("notext", ".html")]),
        # 2.0.2 的 config.json 升級（common.upgrade_config 補 html 區塊：enabled true）→ 全部按 Enter：只多 .html 一列
        "upgraded_202": (["claude", "codex"], 0, "v202", None, all3,
                         [calls("transcribe", "correction", "minutes"), ("targ2", "--type", "meeting"),
                          ("targ_not", "--speakers"), ("targ_not", "--no-diarize"), ("targ_not", "--hotwords"),
                          ("targ_not", "--whisper"), ("marg2", "--type", "meeting"), ("text", "內容類型（Enter＝會議）"),
                          ("rows", MEETING_ROWS), ("text", play), ("text", NEXT_MEETING), ("cfg_html", True)]),
    })
    return out


def v201_scenarios():
    """〔2.0.1〕第一次執行：沒有 state.json（2.0.1 修正前實測：2.0.0 的 mm-sendto.ps1 在這裡印紅字）；
    壞掉、空的 state.json 也安靜地當作沒有記錄（Enter＝會議），並照常寫入這次的選擇。"""
    def calls(*kinds):
        return ("calls", list(kinds))
    ans = ["", "", "", "n", "n", ""]
    chk = [calls("transcribe"), ("targ2", "--type", "meeting"), ("text", "內容類型（Enter＝會議）"), ("notext", "上次"),
           ("state", "meeting"), ("wait", "ask_type"), ("noerr",)]
    return {
        "first_run_no_state": (["claude", "codex"], 0, {}, None, ans, chk + [("nostate_before",)]),
        "state_broken_json": (["claude", "codex"], 0, {}, None, ans, chk, {"state_raw": '{"content_type_last": "cour'}),
        "state_empty": (["claude", "codex"], 0, {}, None, ans, chk, {"state_raw": ""}),
    }


# 〔2.0.0〕自訂範本：有效 2 份（weekly：會議、3 位；readclub：課程、略過）、無效 1 份（不認得的鍵 model）
TEMPLATES = {
    "weekly.md": "---\nname: 週會（研發處）\nbase: meeting\nspeakers: 3\n---\n\n## 整理重點\n- 每個專案寫一個議題\n",
    "readclub.md": "---\nname: 讀書會\nbase: course\nspeakers: skip\n---\n\n## 整理重點\n- 每章寫一段\n",
    "old.md": "---\nname: 舊範本\nbase: meeting\nmodel: opus\n---\n\n## 整理重點\n- x\n",
}


def v2_scenarios():
    """規格 §10.2 E-1。答案順序：類型、人數、專有名詞、①、①選模型、②、②選模型、按 Enter 關閉。
    第 7 個元素（選用）：templates（放進 $MMH/templates）、state（預先寫 state.json；"DIR"＝建成資料夾讓寫入失敗）、
    runs（之後再跑幾次的答案，同一個 runtime）、env（額外環境變數）。"""
    def calls(*kinds):
        return ("calls", list(kinds))
    all3 = ["", "", "", "", "", "", "", ""]
    return {
        # 1.2.2 升級後：4 次 Enter＝1.2.2 連按 3 次的結果（會議、自動、無專有名詞、不用 Breeze）＋會議
        "upgraded_122": (["claude", "codex"], 0, "v122", None, all3,
                         [calls("transcribe", "correction", "minutes"), ("targ2", "--type", "meeting"),
                          ("targ_not", "--speakers"), ("targ_not", "--no-diarize"), ("targ_not", "--hotwords"),
                          ("targ_not", "--whisper"), ("marg2", "--type", "meeting"), ("text", "內容類型（Enter＝會議）"),
                          ("text", "1 會議（含業務／客戶會議）"), ("text", "7 客戶／需求訪談"), ("wait", "ask_type"),
                          ("wait", "ask_speakers"), ("state", "meeting"), ("text", "會議摘要：OpenAI gpt-6.1-sol"),
                          ("text", "meeting-minutes.md"), ("text", NEXT_MEETING), ("rows", MEETING_ROWS)]),
        "type_course_skip": (["claude", "codex"], 0, {}, None, ["2", "s", "", "", "", "", "", ""],
                             [calls("transcribe", "correction", "minutes"), ("targ2", "--type", "course"),
                              ("targ", "--no-diarize"), ("targ_not", "--speakers"), ("marg2", "--type", "course"),
                              ("text", "內容類型：課程（含演講／專題分享）"), ("text", "課程筆記：OpenAI gpt-6.1-sol"),
                              ("text", "notes.md"), ("text", "課程筆記（AI 自動整理，未經人工確認）"), ("text", "notes.json"),
                              ("text", NEXT_NOTES), ("text", "檢查這份課程筆記"), ("notext", "meeting-minutes.md"),
                              ("state", "course"), ("wait", "ask_type")]),
        "template_menu": (["claude", "codex"], 0, {}, None, ["9", "", "", "n", "", "", ""],
                          [calls("transcribe", "minutes"), ("text", "8 讀書會［自訂：課程］"),
                           ("text", "9 週會（研發處）［自訂：會議］"),
                           ("text", "⚠ 自訂範本 old.md 沒有載入：不認得的設定 model"),
                           ("targ2", "--template", "weekly"), ("targ2", "--speakers", "3"), ("targ_not", "--type"),
                           ("marg2", "--template", "weekly"), ("text", "〈週會（研發處）〉會議摘要：OpenAI"),
                           ("state", "template:weekly"), ("text", "meeting-minutes.md")],
                          {"templates": TEMPLATES}),
        "template_skip_default": (["claude", "codex"], 0, {}, None, ["8", "", "", "n", "n", ""],
                                  [calls("transcribe"), ("targ2", "--template", "readclub"), ("targ", "--no-diarize"),
                                   ("state", "template:readclub")],
                                  {"templates": TEMPLATES}),
        # 記住上次：第一次選課程，第二次直接 Enter＝課程
        "remember_last": (["claude", "codex"], 0, {}, None, ["2", "", "", "n", "n", ""],
                          [calls("transcribe", "transcribe"), ("targ2_all", "--type", "course"),
                           ("text", "內容類型（Enter＝上次：課程）"), ("state", "course")],
                          {"runs": [["", "", "", "n", "n", ""]]}),
        "remember_off": (["claude", "codex"], 0, {"content_type": {"remember_last": False}}, None, ["", "", "", "n", "n", ""],
                         [calls("transcribe"), ("targ2", "--type", "meeting"), ("text", "內容類型（Enter＝會議）")],
                         {"state": {"content_type_last": "course"}}),
        "remember_template_gone": (["claude", "codex"], 0, {}, None, ["", "", "", "n", "n", ""],
                                   [calls("transcribe"), ("targ2", "--type", "meeting"),
                                    ("text", "上次選的自訂範本 gone 已不存在或無法載入，預設改回〈會議〉")],
                                   {"state": {"content_type_last": "template:gone"}}),
        "state_unwritable": (["claude", "codex"], 0, {}, None, ["4", "", "", "n", "n", ""],
                             [calls("transcribe"), ("targ2", "--type", "tutorial")], {"state": "DIR"}),
        "bad_inputs": (["claude", "codex"], 0, {}, None, ["x", "99", "abc", "25", "", "n", "n", ""],
                       [calls("transcribe"), ("targ2", "--type", "meeting"), ("targ_not", "--speakers"),
                        ("text", "沒有這個選項，使用〈會議〉"), ("text", "沒有這個選項，使用自動判斷")]),
        "speakers_number": (["claude", "codex"], 0, {}, None, ["5", "x", "4", "", "n", "n", ""],
                            [calls("transcribe"), ("targ2", "--type", "panel"), ("targ2", "--speakers", "4")]),
        # 結束畫面：字幕條數、說話者分離退回 CPU 的原因、零星講者
        "end_screen_v2": (["claude", "codex"], 0, {}, None, all3,
                          [calls("transcribe", "correction", "minutes"), ("text", "transcript.cues.srt"),
                           ("text", "（39 條）"), ("text", "校正版字幕（40 條，對應失敗 0 段）"),
                           ("text", "說話者分離改用 CPU（sherpa）：沒有偵測到可用的 NVIDIA 顯示卡"),
                           ("text", "講者 S3 發言很少，可能是分離誤判")],
                          {"env": {"FAKE_META": json.dumps({"diarization": {"fallback": "no_gpu"}, "speaker_stats": [
                              {"speaker": "S1", "sec": 500.0, "turns": 20, "share": 0.98, "minor": False},
                              {"speaker": "S3", "sec": 6.1, "turns": 2, "share": 0.01, "minor": True}]})}}),
    }


V122_CONFIG = dict(V110_CONFIG, runtime_version="1.2.2",
                   minutes={"ask_default": True, "provider": "auto", "channel": "cli", "chunk_chars": 12000,
                            "timeout_sec": 900, "claude": {"model": "opus", "effort": "medium"},
                            "openai": {"model": "gpt-6.1-sol", "effort": "low"}})


def v202_config() -> dict:
    """〔2.1.0〕2.0.2 安裝後的 config.json：2.0.2 的 common.DEFAULTS＋安裝程式寫的 backend／device／whisper。"""
    scripts = HERE.parent / "meeting-minutes-pro-v2.0.2" / "payload" / "runtime" / "scripts"
    out = subprocess.run([sys.executable, "-B", "-c",
                          "import json, sys; sys.path.insert(0, sys.argv[1]); import common; print(json.dumps(common.DEFAULTS))",
                          str(scripts)], check=True, capture_output=True, text=True, encoding="utf-8",
                         env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).stdout
    return dict({"backend": "openvino", "device": "NPU", "whisper": "turbo"}, **json.loads(out))


def write_config(mmh: Path, cfg):
    if cfg in ("v110", "v122", "v202"):
        old = {"v110": V110_CONFIG, "v122": V122_CONFIG}.get(cfg) or v202_config()
        assert cfg != "v202" or (old["runtime_version"] == "2.0.2" and "html" not in old)
        (mmh / "config.json").write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        # 安裝程式升級（common.upgrade_config）：用真的 common.py 跑在假 runtime 上
        subprocess.run([str(mmh / "venv" / "Scripts" / "python.exe"), "-B", "-c",
                        "import sys; sys.path.insert(0, sys.argv[1]); import common; common.upgrade_config()",
                        str(mmh / "scripts")], check=True,
                       env=dict(os.environ, MEETING_MINUTES_PRO_HOME=str(mmh), PYTHONDONTWRITEBYTECODE="1"))
    else:
        base = {"backend": "openvino", "device": "NPU", "whisper": "turbo"}
        base.update(cfg)
        (mmh / "config.json").write_text(json.dumps(base, ensure_ascii=False), encoding="utf-8")


def run_one(shell: str, name: str, spec, work: Path) -> tuple:
    clis, login, cfg, dur, answers, checks = spec[:6]
    opts = spec[6] if len(spec) > 6 else {}
    mmh = make_runtime(work)
    write_config(mmh, cfg)
    if opts.get("templates"):                            # 〔2.0.0〕自訂範本
        (mmh / "templates").mkdir()
        for n, t in opts["templates"].items():
            (mmh / "templates" / n).write_text(t, encoding="utf-8")
    st = opts.get("state")
    if st == "DIR":                                       # state.json 是資料夾 → 寫入失敗（入口要照常進行）
        (mmh / "state.json").mkdir()
    elif st:
        (mmh / "state.json").write_text(json.dumps(st), encoding="utf-8")
    if "state_raw" in opts:                               # 〔2.0.1〕壞掉／空的 state.json（原樣寫入）
        (mmh / "state.json").write_text(opts["state_raw"], encoding="utf-8")
    state_before = (mmh / "state.json").exists()
    home = work / "home"
    if home.exists():
        shutil.rmtree(home)
    for d in ("home/AppData/Roaming", "home/AppData/Local", "media"):
        (work / d).mkdir(parents=True, exist_ok=True)
    audio = work / "media" / "meet.wav"
    audio.write_bytes(b"RIFF")
    out_dir = work / "media" / "meet_minutes"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    bin_ = work / "bin"
    for n in ("claude", "codex"):
        for ext in ("", ".cmd"):
            p = bin_ / f"{n}{ext}"
            if p.exists() and n not in clis:
                p.unlink()
    if shell == "bash":
        git = GIT_BASH.parent.parent
        path = os.pathsep.join([str(bin_), str(git / "usr" / "bin"), str(git / "bin"), str(Path(sysroot) / "System32")])
    else:
        path = os.pathsep.join([str(bin_), str(Path(sysroot) / "System32"), str(Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0")])
    env = {k: v for k, v in os.environ.items() if k.upper() not in (
        "PATH", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "MMP_RUN_ID", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "MEETING_MINUTES_PRO_HOME", "MSYS_NO_PATHCONV", "MSYS2_ARG_CONV_EXCL")}
    env.update(PATH=path, USERPROFILE=str(home), APPDATA=str(home / "AppData" / "Roaming"),
               LOCALAPPDATA=str(home / "AppData" / "Local"), HOME=str(home), MMP_TEST_NO_OPEN="1",
               FAKE_CODEX_LOGIN=str(login), PYTHONDONTWRITEBYTECODE="1")
    if dur:
        env["FAKE_DURATION"] = dur
    if name == "correction_fails":
        env["FAKE_FAIL_CORRECTION"] = "auth_failed"
    env.update(opts.get("env") or {})
    if shell == "pwsh":
        cmd = [shutil.which("pwsh"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(mmh / "mm-sendto.ps1"), str(audio)]
    elif shell == "powershell":
        cmd = [str(Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"), "-NoProfile",
               "-ExecutionPolicy", "Bypass", "-File", str(mmh / "mm-sendto.ps1"), str(audio)]
    else:
        cmd = [str(GIT_BASH), (mmh / "mm-dropped.sh").as_posix(), audio.as_posix()]
    # bytes：text 模式在 Windows 會把 \n 寫成 \r\n，bash 的 read 會讀到 \r
    text, codes = "", []
    outs, errs = "", ""
    for ans in [answers] + list(opts.get("runs") or []):  # 〔2.0.0〕runs：同一個 runtime 再跑（記住上次）
        p = subprocess.run(cmd, input=("\n".join(ans) + "\n").encode("utf-8"), capture_output=True, env=env, timeout=180)
        o, e = p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")
        text += o + e
        outs += o
        errs += e
        codes.append(p.returncode)
    calls_ = []
    cf = mmh / "calls.jsonl"
    if cf.exists():
        calls_ = [json.loads(line) for line in cf.read_text(encoding="utf-8").splitlines() if line.strip()]
    fails = []
    if NOERR and ("noerr",) not in checks:              # 〔2.0.1〕每個情境都不得有錯誤訊息
        checks = list(checks) + [("noerr",)]
    for c in checks:
        if c[0] == "noerr":
            for label, s in (("主控台", outs), ("stderr", errs)):
                hit = [m for m in ERROR_MARKERS if m in s]
                if hit:
                    fails.append(f"{label}有錯誤訊息 {hit}：" + next(ln.strip() for ln in s.splitlines() if any(m in ln for m in hit))[:160])
        elif c[0] == "nostate_before":
            if state_before:
                fails.append("情境前提錯誤：執行前已有 state.json")
        elif c[0] == "calls":
            got = [x["script"] for x in calls_]
            if got != c[1]:
                fails.append(f"calls {got} != {c[1]}")
        elif c[0] == "arg":
            x = next((x for x in calls_ if x["script"] == c[1]), None)
            flag = "--correct" if c[1] == "correction" else "--minutes"
            want = [f"{flag}-provider", c[2], f"{flag}-model", c[3]]
            if not x or " ".join(want) not in " ".join(x["argv"]) or "--force" not in x["argv"]:
                fails.append(f"{c[1]} argv {x and x['argv']} 不含 {want} 與 --force")
        elif c[0] == "targ":
            x = next((x for x in calls_ if x["script"] == "transcribe"), None)
            if not x or c[1] not in x["argv"] or "--no-correct" not in x["argv"]:
                fails.append(f"transcribe argv {x and x['argv']}")
        elif c[0] in ("targ2", "targ2_all", "targ_not", "marg2"):
            # 〔2.0.0〕targ2／marg2：transcribe／minutes 的 argv 有連續的兩項；targ2_all：每一次 transcribe 都有；targ_not：沒有這一項
            script = "minutes" if c[0] == "marg2" else "transcribe"
            xs = [x for x in calls_ if x["script"] == script]
            if c[0] != "targ2_all":
                xs = xs[:1]
            for x in xs or [None]:
                argv = x["argv"] if x else []
                pairs = list(zip(argv, argv[1:]))
                bad = (c[1] in argv) if c[0] == "targ_not" else ((c[1], c[2]) not in pairs)
                if bad or x is None:
                    fails.append(f"{c[0]} {c[1:]}：{script} argv {argv}")
        elif c[0] == "wait":
            rl = out_dir / "run_log.jsonl"
            evs = [json.loads(line) for line in rl.read_text(encoding="utf-8").splitlines()] if rl.exists() else []
            if not any(e.get("event") == "wait" and e.get("name") == c[1] for e in evs):
                fails.append(f"run_log 沒有 wait {c[1]}")
        elif c[0] == "state":
            try:
                got = json.loads((mmh / "state.json").read_text(encoding="utf-8")).get("content_type_last")
            except (OSError, ValueError):
                got = None
            if got != c[1]:
                fails.append(f"state.json content_type_last {got!r} != {c[1]!r}")
        elif c[0] == "text":
            if c[1] not in text:
                fails.append(f"沒有出現「{c[1]}」")
        elif c[0] == "prompt":
            pass   # Read-Host／read -p 在 stdin 不是終端機時不印提示；由 calls 檢查實際行為（Enter＝是／否）
        elif c[0] == "count":
            if text.count(c[1]) != c[2]:
                fails.append(f"「{c[1]}」出現 {text.count(c[1])} 次 != {c[2]}")
        elif c[0] == "rows":                            # 〔2.1.0〕結束畫面的檔案列（依序）
            got = [ln[2:].split()[0] for ln in outs.splitlines()
                   if ln.startswith("  ") and ln[2:3] != " " and ln[2:].split()[0] in END_ROW_NAMES]
            if got != c[1]:
                fails.append(f"結束畫面檔案列 {got} != {c[1]}")
        elif c[0] == "cfg_html":
            try:
                got = json.loads((mmh / "config.json").read_text(encoding="utf-8")).get("html", {}).get("enabled")
            except (OSError, ValueError):
                got = None
            if got is not c[1]:
                fails.append(f"config.json html.enabled {got!r} != {c[1]!r}")
        elif c[0] == "notext":
            if c[1] in text:
                fails.append(f"不該出現「{c[1]}」")
        elif c[0] == "runs":
            rf = mmh / "logs" / "runs.jsonl"
            rows = [json.loads(line) for line in rf.read_text(encoding="utf-8").splitlines()] if rf.exists() else []
            if len(rows) != c[1]:
                fails.append(f"runs.jsonl {len(rows)} 列 != {c[1]}")
            elif not rows[0].get("wait_sec") and "ask_speakers" not in (out_dir / "run_log.jsonl").read_text(encoding="utf-8"):
                fails.append("run_log 沒有等待時間")
    run_ids = {x.get("run_id") for x in calls_}
    if calls_ and len(run_ids) != 1 + len(opts.get("runs") or []):
        fails.append(f"同一個檔案的 run_id 不一致：{run_ids}")
    if any(codes):
        fails.append(f"exit {codes}")
    return fails, text


def main():
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--shell", nargs="*", default=["pwsh", "powershell", "bash"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--show", action="store_true", help="印出每個情境的畫面輸出")
    args = ap.parse_args()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    total, bad = 0, 0
    for shell in args.shell:
        for name, spec in scenarios().items():
            if args.only and name not in args.only:
                continue
            total += 1
            fails, text = run_one(shell, name, spec, work)
            print(f"[{'PASS' if not fails else 'FAIL'}] {shell:10s} {name}" + ("" if not fails else "：" + "；".join(fails)))
            if fails:
                bad += 1
            if args.show or fails:
                (work / f"{shell}-{name}.log").write_text(text, encoding="utf-8")
    print(f"\n{total - bad}/{total} 通過")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
