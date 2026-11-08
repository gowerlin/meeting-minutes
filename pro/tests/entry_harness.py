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

- 〔2.2.0〕參考資料（規格 2.2.0 §7.1、§7.2、§11.5）：假 runtime 多放真的 refs.py（入口用 `refs.py plan` 算截圖與文件數）；
  假 auto_correct.py／auto_minutes.py 收到 `--context` 時照真的程式寫 `context.md`（refs.write_context）；`FAKE_KEYFRAMES=N`
  讓假轉寫產生 N 張截圖與 keyframes；`FAKE_REFERENCE=1` 讓假校正寫 `reference.json`（含讀不到的文件）。
  1.x～2.1 的情境在 2.2.0 自動在媒體旁放 `meet.context.md`（入口印「背景說明：沿用」、不多問一題，答案與檢查不變）；
  v22_scenarios：有說明檔不問、沒有則問一行、只答應摘要時在摘要問、兩步都答否不問、`context.md` 重跑沿用、
  Enter 跳過、`ask_context: false`、特殊字元原樣傳、多個檔各問一次、詢問行的送出內容、結束畫面的 reference.json／context.md。
  另有「貼上兩行」的真主控台測試（`paste_*`，不經 stdin 管線）：PowerShell 7／5.1 在隱藏的新主控台用 WriteConsoleInput
  模擬貼上兩行，確認 Ask-Context 讀完第一行後清掉第二行；bash 在 WSL 的 pty 實測（沒有 WSL 或 MMP_TEST_NO_WSL 時略過）。

- 〔2.4.0〕本機限定（規格 2.4.0 §3）：v24_scenarios：本機限定入口（`-LocalOnly`／`--local-only`）、全域 `privacy.local_only`、
  輸出資料夾已有 `local-only.json`；檢查不問 AI、轉寫帶 `--local-only`、結束畫面文字與檔案列、假 claude／codex 被呼叫 0 次
  （假 CLI 把每次呼叫記到 `FAKE_CLI_LOG`）。供應商名稱統一（GPT／Claude）：舊情境檢查的畫面字串在測 2.4.0 時自動換成新說法
  （`OpenAI gpt-6.1-sol`→`GPT gpt-6.1-sol`、`會送到 OpenAI`→`會送到 GPT（OpenAI）`、`會送到 Anthropic`→`會送到 Claude（Anthropic）`）。

用法：python entry_harness.py --work <暫存目錄> [--shell pwsh powershell bash] [--only 情境名 ...]
"""
import argparse
import ctypes
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
                 "corrections.suggested.tsv", "reference.json", "context.md", "transcript.md", "transcript.srt",
                 "transcript.cues.srt", "transcript.corrected.srt", "frames", "local-only.json")
V22 = _testenv.VER >= (2, 2, 0)          # 〔2.2.0〕參考資料
# 〔2.3.0〕--hotwords 特殊字元（PowerShell 5.1 用 Native-Arg）。MMP_TEST_HOTWORDS_CONTROL=1：舊版也跑這個情境（對照組，預期 5.1 失敗）
V23 = _testenv.VER >= (2, 3, 0) or os.environ.get("MMP_TEST_HOTWORDS_CONTROL") == "1"
V24 = _testenv.VER >= (2, 4, 0)          # 〔2.4.0〕本機限定、供應商名稱 GPT／Claude
NAMES_24 = (("OpenAI gpt-6.1-sol", "GPT gpt-6.1-sol"), ("會送到 OpenAI", "會送到 GPT（OpenAI）"),
            ("會送到 Anthropic", "會送到 Claude（Anthropic）"), ("：OpenAI", "：GPT"))


def nm(s: str) -> str:
    """〔2.4.0〕舊情境寫的畫面字串 → 測 2.4.0 時的新說法（測舊版時原樣）。"""
    if V24 and isinstance(s, str):
        for a, b in NAMES_24:
            s = s.replace(a, b)
    return s

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
lo_field = {}
if "--local-only" in sys.argv:                          # 〔2.4.0〕同真的程式：寫標記檔（common.write_local_only_marker）
    import common
    common.write_local_only_marker(out, os.environ.get("MMP_LOCAL_ONLY_SOURCE") or "transcribe")
    lo_field = {"local_only": "marker"}
# 〔2.0.0〕字幕檔與 meta（FAKE_META：JSON，合併進 transcript.json 的 meta，例如 diarization.fallback、speaker_stats）
(out / "transcript.cues.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nfake\n", encoding="utf-8")
if os.environ.get("FAKE_META"):
    doc = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    doc.setdefault("meta", {}).update(json.loads(os.environ["FAKE_META"]))
    (out / "transcript.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
if os.environ.get("FAKE_KEYFRAMES"):                   # 〔2.2.0〕截圖（入口的 refs.py plan 會數）
    doc = json.loads((out / "transcript.json").read_text(encoding="utf-8"))
    (out / "frames").mkdir(exist_ok=True)
    doc["keyframes"] = []
    for i in range(int(os.environ["FAKE_KEYFRAMES"])):
        (out / "frames" / f"frame_{i + 1:04d}.jpg").write_bytes(b"\xff\xd8fake")
        doc["keyframes"].append({"time": float(i * 30), "file": f"frames/frame_{i + 1:04d}.jpg"})
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
                  "subtitles": {"cues": {"status": "ok", "cues": 39}}, **lo_field}, ensure_ascii=False))
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
if "--context" in a:                                    # 〔2.2.0〕同真的程式：寫 context.md（refs.write_context）
    import refs
    refs.write_context(out, a[a.index("--context") + 1])
if KIND == "correction" and os.environ.get("FAKE_REFERENCE"):
    (out / "reference.json").write_text(json.dumps({"version": "2.2.0", "sources": {"docs": [
        {"file": "a.pdf", "status": "ok", "chars": 10}, {"file": "b.pdf", "status": "skipped", "reason": "encrypted"},
        {"file": "c.pdf", "status": "skipped", "reason": "no_text_layer"},
        {"file": "d.xlsx", "status": "skipped", "reason": "unsupported"}]}}, ensure_ascii=False), encoding="utf-8")
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
    for n in ("runlog.py", "common.py", "pricing.json", "templates.py", "content_types.py", "diarize.py", "refs.py"):
        if (RUNTIME / "scripts" / n).exists():          # 〔2.0.0〕範本選單與退回原因用到後三個（1.x 沒有）；〔2.2.0〕refs.py
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
        # 〔2.4.0〕每次被呼叫都記到 FAKE_CLI_LOG（本機限定時要是 0 次）
        (bin_ / f"{name}.cmd").write_text(
            "@echo off\r\nif defined FAKE_CLI_LOG echo %~n0 %*>>\"%FAKE_CLI_LOG%\"\r\n"
            "if \"%1\"==\"login\" exit /b %FAKE_CODEX_LOGIN%\r\necho fake 1.0\r\n", encoding="ascii")
        sh = bin_ / name
        sh.write_text('#!/bin/bash\n[ -n "$FAKE_CLI_LOG" ] && echo "$(basename "$0") $*" >> "$FAKE_CLI_LOG"\n'
                      'if [ "$1" = "login" ]; then exit "${FAKE_CODEX_LOGIN:-0}"; fi\necho fake 1.0\n',
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
    if V22:
        out.update(v22_scenarios())
    if V23:
        out.update(v23_scenarios())
    if V24:
        out.update(v24_scenarios())
    return out


def v24_scenarios():
    """〔2.4.0〕本機限定（規格 2.4.0 §3）。答案順序：類型、人數、專有名詞、按 Enter 關閉（沒有 AI 的題目）。
    opts：local_entry＝本機限定入口（-LocalOnly／--local-only）；pre_marker＝輸出資料夾事先有 local-only.json。"""
    no_ai = [("calls", ["transcribe"]), ("nocli",), ("notext", "要做 AI 校正嗎"), ("notext", "背景說明"),
             ("notext", "在 Claude 中說"), ("notext", "會送到"), ("text", "本機限定：沒有送出任何資料（沒有 AI 校正，也沒有 AI 整理）。"),
             ("text", "下一步：要人工校稿"), ("text", "會議記錄校稿"), ("text", "（Pro 的附屬工具，另外安裝）"),
             ("text", "本機限定：不做 AI 校正與會議摘要，不會送出任何資料")]
    ans = ["", "", "", ""]
    return {
        "local_only_entry": (["claude", "codex"], 0, {}, None, ans, no_ai + [
            ("targ_has", "--local-only"), ("marker", True), ("text", "會議轉寫（Pro，本機限定）　meeting-minutes-pro"),
            ("text", "：這次不會把任何資料送到 GPT 或 Claude"),
            ("rows", ["transcript.md", "transcript.srt", "transcript.cues.srt", "local-only.json"]),
            ("text", "要解除本機限定（之後才能用 AI 校正與整理）：這一份：刪除輸出資料夾裡的 local-only.json"),
            ("notext", "全部：把")], {"local_entry": True}),
        "local_only_global": (["claude", "codex"], 0, {"privacy": {"local_only": True}}, None, ans, no_ai + [
            ("targ_not", "--local-only"), ("marker", False), ("text", "==== 會議轉寫（Pro）　meeting-minutes-pro"),
            ("text", "config.json 的 privacy.local_only）：這次不會把任何資料送到 GPT 或 Claude"),
            ("rows", ["transcript.md", "transcript.srt", "transcript.cues.srt"]),
            ("text", "要解除本機限定（之後才能用 AI 校正與整理）：全部：把"), ("text", "privacy.local_only 改成 false")]),
        # 一般入口，但這份的輸出資料夾已有標記檔（之前用本機限定轉寫過）：轉寫照常、之後不問 AI（偵測 CLI 照舊，不送任何內容）
        "local_only_marker_existing": (["claude", "codex"], 0, {}, None, ans, [
            ("calls", ["transcribe"]), ("notext", "要做 AI 校正嗎"), ("notext", "會送到"), ("targ_not", "--local-only"),
            ("text", "本機限定：不做 AI 校正與會議摘要，不會送出任何資料"), ("text", "本機限定：沒有送出任何資料"),
            ("rows_has", "local-only.json"), ("text", "這一份：刪除輸出資料夾裡的 local-only.json"),
            ("cli_only", ("--version", "login"))], {"pre_marker": True}),
    }


def v23_scenarios():
    """〔2.3.0〕本次專有名詞（--hotwords）含雙引號、$HOME、反引號、%、&、管線符號、>、;、結尾反斜線，原樣傳到 transcribe.py
    （PowerShell 5.1 的 Legacy 傳參數會弄壞 " 與結尾 \\；2.3.0 改用 Native-Arg，同 2.2.0 的 --context）。
    答案順序：類型、人數、專有名詞、①、②、按 Enter 關閉。"""
    hot = 'Kafka, 含 "引號" $HOME 與 `反引號` 100% & | > ; 結尾\\'
    plain = "Kafka, Redis Sentinel, 星河物流"
    return {
        "hotwords_special_chars": (["claude", "codex"], 0, {}, None, ["", "", hot, "n", "n", ""],
                                   [("calls", ["transcribe"]), ("targ2", "--hotwords", hot)]),
        "hotwords_plain": (["claude", "codex"], 0, {}, None, ["", "", plain, "n", "n", ""],
                           [("calls", ["transcribe"]), ("targ2", "--hotwords", plain)]),
    }


def v22_scenarios():
    """〔2.2.0〕背景說明一行與送出內容（規格 2.2.0 §7.1、§7.2、§11.5）。這些情境媒體旁沒有說明檔（no_ctx_file），
    答案順序：類型、人數、專有名詞、①、（背景說明）、①選模型、②、（背景說明）、②選模型、按 Enter 關閉。"""
    def calls(*kinds):
        return ("calls", list(kinds))
    ask = "示範週會，主持人陳怡君"
    o = {"no_ctx_file": True}
    special = '含 "引號" $HOME 與 `反引號` 100% & | > ; 結尾\\'
    return {
        "ctx_ask": (["claude", "codex"], 0, {}, None, ["", "", "", "", ask, "", "", "", ""],
                    [calls("transcribe", "correction", "minutes"), ("carg", "correction", "--context", ask, 0),
                     ("carg_not", "minutes", "--context"), ("wait", "ask_context"), ("ctxmd", ask),
                     ("notext", "背景說明：沿用"), ("arg", "correction", "openai", "gpt-6.1-sol"),
                     ("arg", "minutes", "openai", "gpt-6.1-sol"), ("rows_has", "context.md")], o),
        "ctx_special_chars": (["claude", "codex"], 0, {}, None, ["", "", "", "", special, "", "n", ""],
                              [calls("transcribe", "correction"), ("carg", "correction", "--context", special, 0)], o),
        "ctx_file": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", "", ""],
                     [calls("transcribe", "correction", "minutes"), ("text", "背景說明：沿用 meet.context.md"),
                      ("count", "背景說明：沿用", 1), ("carg_not", "correction", "--context"), ("carg_not", "minutes", "--context"),
                      ("nowait", "ask_context"), ("arg", "minutes", "openai", "gpt-6.1-sol")]),
        "ctx_minutes_only": (["claude", "codex"], 0, {}, None, ["", "", "", "n", "", "只整理摘要", "", ""],
                             [calls("transcribe", "minutes"), ("carg", "minutes", "--context", "只整理摘要", 0),
                              ("wait", "ask_context"), ("arg", "minutes", "openai", "gpt-6.1-sol")], o),
        "ctx_both_no": (["claude", "codex"], 0, {}, None, ["", "", "", "n", "n", ""],
                        [calls("transcribe"), ("nowait", "ask_context"), ("notext", "背景說明")], o),
        "ctx_skip_enter": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", "", "", ""],
                           [calls("transcribe", "correction", "minutes"), ("carg_not", "correction", "--context"),
                            ("carg_not", "minutes", "--context"), ("wait", "ask_context"), ("noctxmd",),
                            ("arg", "minutes", "openai", "gpt-6.1-sol")], o),
        # 重跑：第一次寫了 context.md，第二次「沿用 context.md」、不問、不傳 --context
        "ctx_rerun": (["claude", "codex"], 0, {}, None, ["", "", "", "", ask, "", "", "", ""],
                      [calls("transcribe", "correction", "minutes", "transcribe", "correction", "minutes"),
                       ("carg", "correction", "--context", ask, 0), ("carg_not_at", "correction", "--context", 1),
                       ("carg_not_at", "minutes", "--context", 1), ("text", "背景說明：沿用 context.md"), ("ctxmd", ask)],
                      dict(o, runs=[["", "", "", "", "", "", "", ""]])),
        "ctx_ask_off": (["claude", "codex"], 0, {"reference": {"ask_context": False}}, None, ["", "", "", "", "", "", "", ""],
                        [calls("transcribe", "correction", "minutes"), ("carg_not", "correction", "--context"),
                         ("nowait", "ask_context"), ("notext", "背景說明"), ("arg", "minutes", "openai", "gpt-6.1-sol")], o),
        # 一次兩個檔：每個檔各問一次
        "ctx_two_files": (["claude", "codex"], 0, {}, None,
                          ["", "", "", "", "第一場", "", "n", "", "第二場", "", "n", ""],
                          [calls("transcribe", "correction", "transcribe", "correction"),
                           ("carg", "correction", "--context", "第一場", 0), ("carg", "correction", "--context", "第二場", 1)],
                          dict(o, files=2)),
        # 詢問行：截圖 3 張、會議文件 2 份（校正）；摘要不列截圖
        "refs_send_line": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", "", "", ""],
                           [calls("transcribe", "correction", "minutes"),
                            ("text", "AI 校正：OpenAI gpt-6.1-sol（產出 transcript.corrected.md，原稿不改）："),
                            ("text", "（截圖整理另約 15～30 秒）；逐字稿文字、截圖 3 張、會議文件 2 份的名詞與段落會送到 OpenAI"),
                            ("text", "AI 校正：OpenAI gpt-6.1-sol；逐字稿文字、截圖 3 張、會議文件 2 份的名詞與段落會送到 OpenAI"),
                            ("text", "會議摘要：OpenAI gpt-6.1-sol；逐字稿文字、會議文件 2 份的名詞與段落會送到 OpenAI"),
                            ("count", "截圖 3 張", 2), ("notext", "；逐字稿文字會送到")],
                           dict(o, env={"FAKE_KEYFRAMES": "3"},
                                media={"meet.議程.md": "# 議程\n", "meet_簡報.pdf": "%PDF-1.4\n", "購物清單.txt": "x"})),
        # 沒有參考資料：詢問行與 2.1.0 相同
        "refs_none_line": (["claude", "codex"], 0, {}, None, ["", "", "", "", "", "", "", "", ""],
                           [calls("transcribe", "correction", "minutes"), ("text", "；逐字稿文字會送到 OpenAI"),
                            ("notext", "截圖整理"), ("notext", "會議文件")], o),
        # 結束畫面：reference.json、context.md 兩列（依序）、讀不到的文件、下一步說截圖已參考
        "refs_end_screen": (["claude", "codex"], 0, {}, None, ["", "", "", "", ask, "", "n", ""],
                            [calls("transcribe", "correction"),
                             ("rows", ["transcript.corrected.md", "reference.json", "context.md", "transcript.md", "transcript.srt",
                                       "transcript.cues.srt", "transcript.corrected.srt"]),
                             ("text", "會議文件 2 份沒有讀到（加密 1、沒有文字層 1），詳見 reference.json"),
                             ("text", "影片截圖已在 AI 校正時參考，認出的與會者在 reference.json"),
                             ("notext", "影片可一併附上 frames 內的截圖")],
                            dict(o, env={"FAKE_REFERENCE": "1"})),
    }


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
    if (work / "media").exists():                         # 〔2.2.0〕媒體旁的說明檔、文件不得留到下一個情境
        shutil.rmtree(work / "media")
    for d in ("home/AppData/Roaming", "home/AppData/Local", "media"):
        (work / d).mkdir(parents=True, exist_ok=True)
    audio = work / "media" / "meet.wav"
    audio.write_bytes(b"RIFF")
    audios = [audio]
    for i in range(2, int(opts.get("files") or 1) + 1):
        audios.append(work / "media" / f"meet{i}.wav")
        audios[-1].write_bytes(b"RIFF")
    if V22 and not opts.get("no_ctx_file"):              # 〔2.2.0〕舊情境：媒體旁有說明檔 → 入口不多問背景說明
        (work / "media" / "meet.context.md").write_text("合成素材的背景說明\n", encoding="utf-8")
    for n, t in (opts.get("media") or {}).items():
        (work / "media" / n).write_text(t, encoding="utf-8")
    out_dir = work / "media" / "meet_minutes"
    if opts.get("pre_marker"):                            # 〔2.4.0〕之前用本機限定轉寫過的輸出資料夾
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "local-only.json").write_text('{"local_only": true, "source": "sendto"}\n', encoding="utf-8")
    cli_log = work / "cli_calls.txt"
    cli_log.unlink(missing_ok=True)
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
               FAKE_CODEX_LOGIN=str(login), PYTHONDONTWRITEBYTECODE="1",
               FAKE_CLI_LOG=str(cli_log) if shell != "bash" else cli_log.as_posix())
    if dur:
        env["FAKE_DURATION"] = dur
    if name == "correction_fails":
        env["FAKE_FAIL_CORRECTION"] = "auth_failed"
    env.update(opts.get("env") or {})
    lo_ps = ["-LocalOnly"] if opts.get("local_entry") else []          # 〔2.4.0〕本機限定入口
    lo_sh = ["--local-only"] if opts.get("local_entry") else []
    if shell == "pwsh":
        cmd = [shutil.which("pwsh"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(mmh / "mm-sendto.ps1")] + \
            lo_ps + [str(x) for x in audios]
    elif shell == "powershell":
        cmd = [str(Path(sysroot) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"), "-NoProfile",
               "-ExecutionPolicy", "Bypass", "-File", str(mmh / "mm-sendto.ps1")] + lo_ps + [str(x) for x in audios]
    else:
        cmd = [str(GIT_BASH), (mmh / "mm-dropped.sh").as_posix()] + lo_sh + [x.as_posix() for x in audios]
    # bytes：text 模式在 Windows 會把 \n 寫成 \r\n，bash 的 read 會讀到 \r
    text, codes = "", []
    outs, errs = "", ""
    for ans in [answers] + list(opts.get("runs") or []):  # 〔2.0.0〕runs：同一個 runtime 再跑（記住上次）
        # 〔2.2.0〕PowerShell 讀導向的 stdin 用主控台字碼頁（繁中 Windows 是 cp950）解碼，答案要用同一個字碼頁送；
        # 真的主控台輸入走 Unicode，不受影響。bash 照舊送 UTF-8
        enc = "utf-8" if shell == "bash" or os.name != "nt" else \
            f"cp{ctypes.windll.kernel32.GetConsoleCP() or ctypes.windll.kernel32.GetOEMCP()}"
        p = subprocess.run(cmd, input=("\n".join(ans) + "\n").encode(enc), capture_output=True, env=env, timeout=180)
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
    cli_calls = cli_log.read_text(encoding="utf-8", errors="replace").splitlines() if cli_log.exists() else []
    checks = [tuple(nm(x) for x in c) for c in checks]   # 〔2.4.0〕舊情境的畫面字串換成新說法
    for c in checks:
        if c[0] == "nocli":                              # 〔2.4.0〕假 claude／codex 一次都沒有被呼叫
            if cli_calls:
                fails.append(f"本機限定時不該執行 claude／codex：{cli_calls}")
        elif c[0] == "cli_only":                         # 〔2.4.0〕只准偵測（--version、login status）
            bad = [x for x in cli_calls if not any(w in x for w in c[1])]
            if bad:
                fails.append(f"不該送出內容：{bad}")
        elif c[0] == "targ_has":
            x = next((x for x in calls_ if x["script"] == "transcribe"), None)
            if not x or c[1] not in x["argv"]:
                fails.append(f"transcribe argv 沒有 {c[1]}：{x and x['argv']}")
        elif c[0] == "marker":
            if (out_dir / "local-only.json").exists() != c[1]:
                fails.append(f"local-only.json 存在 {not c[1]}，應為 {c[1]}")
        elif c[0] == "noerr":
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
        elif c[0] in ("carg", "carg_not", "carg_not_at"):    # 〔2.2.0〕correction／minutes 的 argv：第 i 次呼叫有／沒有某旗標
            xs = [x["argv"] for x in calls_ if x["script"] == c[1]]
            if c[0] == "carg":
                argv = xs[c[4]] if len(xs) > c[4] else []
                if (c[2], c[3]) not in list(zip(argv, argv[1:])):
                    fails.append(f"{c[1]} 第 {c[4] + 1} 次 argv 沒有 {c[2]} {c[3]!r}：{argv}")
            elif c[0] == "carg_not_at":
                argv = xs[c[3]] if len(xs) > c[3] else None
                if argv is None or c[2] in argv:
                    fails.append(f"{c[1]} 第 {c[3] + 1} 次 argv 不該有 {c[2]}：{argv}")
            elif any(c[2] in argv for argv in xs):
                fails.append(f"{c[1]} argv 不該有 {c[2]}：{xs}")
        elif c[0] == "nowait":
            rl = out_dir / "run_log.jsonl"
            evs = [json.loads(line) for line in rl.read_text(encoding="utf-8").splitlines()] if rl.exists() else []
            if any(e.get("event") == "wait" and e.get("name") == c[1] for e in evs):
                fails.append(f"run_log 不該有 wait {c[1]}")
        elif c[0] in ("ctxmd", "noctxmd"):
            cm = out_dir / "context.md"
            if c[0] == "noctxmd":
                if cm.exists():
                    fails.append("不該寫 context.md")
            elif not cm.exists() or not cm.read_text(encoding="utf-8").endswith("\n" + c[1] + "\n") or \
                    "source: entry" not in cm.read_text(encoding="utf-8"):
                fails.append(f"context.md 不對：{cm.read_text(encoding='utf-8') if cm.exists() else '（沒有）'}")
        elif c[0] == "rows_has":
            got = [ln[2:].split()[0] for ln in outs.splitlines() if ln.startswith("  ") and ln[2:3] != " " and ln[2:].split()]
            if c[1] not in got:
                fails.append(f"結束畫面沒有 {c[1]} 這一列")
        elif c[0] == "runs":
            rf = mmh / "logs" / "runs.jsonl"
            rows = [json.loads(line) for line in rf.read_text(encoding="utf-8").splitlines()] if rf.exists() else []
            if len(rows) != c[1]:
                fails.append(f"runs.jsonl {len(rows)} 列 != {c[1]}")
            elif not rows[0].get("wait_sec") and "ask_speakers" not in (out_dir / "run_log.jsonl").read_text(encoding="utf-8"):
                fails.append("run_log 沒有等待時間")
    run_ids = {x.get("run_id") for x in calls_}
    if calls_ and len(run_ids) != len(audios) * (1 + len(opts.get("runs") or [])):
        fails.append(f"同一個檔案的 run_id 不一致：{run_ids}")
    if any(codes):
        fails.append(f"exit {codes}")
    return fails, text


# ---------------------------------------------------------------- 〔2.2.0〕貼上兩行（真主控台／pty；規格 2.2.0 §7.1 鍵盤緩衝）
PS_PASTE = r"""
param([string]$Src, [string]$Out, [string]$Mode)
$r = [ordered]@{ mode = $Mode }
try {
    $code = Get-Content -LiteralPath $Src -Raw -Encoding UTF8
    foreach ($name in @("Clear-KeyBuffer", "Get-Opt", "Now-Iso", "Ask", "Ask-Context")) {
        $m = [regex]::Match($code, "(?ms)^function $([regex]::Escape($name))[ (\{].*?^\}")
        if (-not $m.Success) { throw "找不到函式 $name" }
        $body = $m.Value
        if ($name -eq "Clear-KeyBuffer") { $body = $body -replace "^function Clear-KeyBuffer", "function Real-ClearKeyBuffer" }
        if ($name -eq "Ask-Context" -and $Mode -eq "noflush") {      # 對照組：Ask-Context 讀完後不清緩衝
            $body = $body -replace "(?m)^[ \t]*Clear-KeyBuffer[ \t].*$", ""
        }
        Invoke-Expression $body
    }
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class MmpPaste {
    [StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
    public struct KEY_EVENT_RECORD {
        [FieldOffset(0)] public int bKeyDown; [FieldOffset(4)] public ushort wRepeatCount;
        [FieldOffset(6)] public ushort wVirtualKeyCode; [FieldOffset(8)] public ushort wVirtualScanCode;
        [FieldOffset(10)] public char UnicodeChar; [FieldOffset(12)] public uint dwControlKeyState;
    }
    [StructLayout(LayoutKind.Explicit)]
    public struct INPUT_RECORD { [FieldOffset(0)] public ushort EventType; [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent; }
    [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr GetStdHandle(int n);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool WriteConsoleInputW(IntPtr h, INPUT_RECORD[] r, uint n, out uint w);
    public static uint Type(string s) {
        var r = new INPUT_RECORD[s.Length * 2];
        for (int i = 0; i < s.Length; i++) {
            ushort vk = (ushort)(s[i] == '\r' ? 13 : 0);
            for (int k = 0; k < 2; k++) {
                r[i * 2 + k].EventType = 1; r[i * 2 + k].KeyEvent.bKeyDown = (k == 0) ? 1 : 0;
                r[i * 2 + k].KeyEvent.wRepeatCount = 1; r[i * 2 + k].KeyEvent.wVirtualKeyCode = vk;
                r[i * 2 + k].KeyEvent.UnicodeChar = s[i];
            }
        }
        uint w; WriteConsoleInputW(GetStdHandle(-10), r, (uint)r.Length, out w); return w;
    }
}
"@
    # 題目出現時（Ask 開頭清緩衝之後）使用者貼上兩行
    $script:clears = 0
    function Clear-KeyBuffer { Real-ClearKeyBuffer; $script:clears++; if ($script:clears -eq 1) { [void][MmpPaste]::Type("line one`rline two`r") } }
    function Log-Wait { }
    $cfg = $null; $Vendor = @{ claude = "Anthropic"; openai = "OpenAI" }
    $script:RefsPlan = $null; $script:CtxAsked = $false; $script:CtxLine = $null
    $r.redirected = [Console]::IsInputRedirected
    Ask-Context "x" "claude"
    $r.context = $script:CtxLine
    $r.left = [Console]::KeyAvailable                 # 第二行還在緩衝區嗎
    [void][MmpPaste]::Type("3`r")                     # 下一題（選模型）才輸入的答案
    $r.next = Read-Host "next"
} catch { $r.error = "$_" }
$r | ConvertTo-Json | Set-Content -LiteralPath $Out -Encoding UTF8
"""

PTY_PASTE = r"""
import json, os, pty, select, sys, time, re
SRC = %r
MODE = %r
def func(name):
    m = re.search(r"(?ms)^" + re.escape(name) + r"\(\) \{.*?^\}", SRC)
    return m.group(0)
body = "now_iso() { date; }\n" + "\n".join(func(n) for n in ("flush_input", "ask", "ask_context"))
if MODE == "noflush":
    body = body.replace("    flush_input   # 讀完再清一次", "    :   # 對照組")
script = ('ASK_ANS=""; ASK_T0=""; ASK_T1=""; CTX_ASKED=""; CTX_LINE=""; REFS_CTX=""\n'
          'cfg_get() { echo ""; }\nvendor() { echo Anthropic; }\nlog_wait() { return 0; }\n' + body +
          '\nask_context x claude\nprintf "\\nCTX[%%s]\\n" "$CTX_LINE"\nIFS= read -r -p "next> " nxt\nprintf "\\nNEXT[%%s]\\n" "$nxt"\n')
pid, fd = pty.fork()
if pid == 0:
    os.execvp("bash", ["bash", "--norc", "--noprofile", "-c", script])
out = b""
def pump(until, t=10):
    global out
    end = time.time() + t
    while until not in out and time.time() < end:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                out += os.read(fd, 4096)
            except OSError:
                return
pump("背景說明".encode("utf-8"))
time.sleep(0.3)
os.write(fd, b"line one\rline two\r")      # 貼上兩行
pump(b"next> ")
time.sleep(0.5)
os.write(fd, b"3\r")
pump(b"NEXT[")
pump(b"]\r\n", 3)
os.waitpid(pid, 0)
print(json.dumps(out.decode("utf-8", "replace")))
"""


def paste_check(shell: str, work: Path) -> tuple:
    """回傳 (fails, text)；fails 是 None＝略過。PowerShell：隱藏的新主控台（不導向 stdin）；bash：WSL 的 pty。"""
    sendto, dropped = RUNTIME / "mm-sendto.ps1", RUNTIME / "mm-dropped.sh"
    results, fails = {}, []
    if shell in ("pwsh", "powershell"):
        exe = shutil.which("pwsh") if shell == "pwsh" else str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" /
                                                              "WindowsPowerShell" / "v1.0" / "powershell.exe")
        if not exe or os.name != "nt":
            return None, "沒有這個 PowerShell"
        (work / "paste.ps1").write_text(PS_PASTE, encoding="utf-8-sig")
        for mode in ("flush", "noflush"):
            res = work / f"paste-{shell}-{mode}.json"
            res.unlink(missing_ok=True)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            p = subprocess.Popen([exe, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(work / "paste.ps1"), str(sendto),
                                  str(res), mode], creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)
            p.wait(timeout=120)
            results[mode] = json.loads(res.read_text(encoding="utf-8-sig"))
        f, c = results["flush"], results["noflush"]
        if f.get("error") or c.get("error"):
            fails.append(f"錯誤：{f.get('error') or c.get('error')}")
        else:
            if f["redirected"]:
                fails.append("stdin 被導向（不是真主控台）")
            if (f["context"], f["left"], f["next"]) != ("line one", False, "3"):
                fails.append(f"清緩衝：背景說明 {f['context']!r}、第二行留在緩衝 {f['left']}、下一題讀到 {f['next']!r}")
            if (c["context"], c["left"], c["next"]) != ("line one", True, "line two"):
                fails.append(f"對照組（不清）應該讀到第二行：{c}")
        return fails, json.dumps(results, ensure_ascii=False)
    if os.environ.get("MMP_TEST_NO_WSL") or os.name != "nt" or not shutil.which("wsl.exe"):
        return None, "沒有 WSL（或 MMP_TEST_NO_WSL）：pty 實測略過"
    src = dropped.read_text(encoding="utf-8")
    for mode in ("flush", "noflush"):
        p = subprocess.run(["wsl.exe", "-e", "python3", "-"], input=(PTY_PASTE % (src, mode)).encode("utf-8"),
                           capture_output=True, timeout=120)
        if p.returncode != 0:
            return [f"pty 執行失敗：{p.stderr.decode('utf-8', 'replace')[:200]}"], ""
        results[mode] = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])
    if "CTX[line one]" not in results["flush"] or "NEXT[3]" not in results["flush"]:
        fails.append("清緩衝：" + results["flush"][-200:])
    if "NEXT[line two]" not in results["noflush"]:
        fails.append("對照組（不清）應該讀到第二行：" + results["noflush"][-200:])
    return fails, json.dumps(results, ensure_ascii=False)


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
        if V22 and (not args.only or "paste_two_lines" in args.only):     # 〔2.2.0〕貼上兩行（真主控台／pty）
            fails, text = paste_check(shell, work)
            if fails is None:
                print(f"[SKIP] {shell:10s} paste_two_lines：{text}")
                continue
            total += 1
            print(f"[{'PASS' if not fails else 'FAIL'}] {shell:10s} paste_two_lines" + ("" if not fails else "：" + "；".join(fails)))
            if fails:
                bad += 1
                (work / f"{shell}-paste_two_lines.log").write_text(text, encoding="utf-8")
    print(f"\n{total - bad}/{total} 通過")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
