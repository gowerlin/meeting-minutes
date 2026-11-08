"""Shared paths, model registry and config for the meeting-minutes-pro runtime.

設計原則：硬體偵測與測速只在安裝時（setup_backend.py）做一次，結果寫進 config.json；
轉寫時（transcribe.py）只照 config 載入，不再即時偵測。
"""
import copy
import json
import os
import sys
from pathlib import Path

VERSION = "2.4.1"

# backend -> alias -> Hugging Face repo id
WHISPER_MODELS = {
    "openvino": {   # Intel NPU / Intel GPU / 任何 x86-64 CPU（含 AMD）
        "turbo": "OpenVINO/whisper-large-v3-turbo-int8-ov",
        "large-v3": "OpenVINO/whisper-large-v3-int8-ov",
        "base": "OpenVINO/whisper-base-int8-ov",
        "breeze": "local/breeze-asr-25-int8-ov",          # 沒有現成版本，安裝時由原始模型轉換
    },
    "ct2": {        # faster-whisper / CTranslate2：NVIDIA CUDA，或 macOS 上的 CPU（Apple Accelerate）
        "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "large-v3": "Systran/faster-whisper-large-v3",
        "base": "Systran/faster-whisper-base",
        "breeze": "shdennlin/breeze-asr-25-ct2",          # 依精度下載 int8 / float16 / int8_float16 子資料夾
    },
    "mlx": {        # mlx-whisper：Apple Silicon GPU（Metal）
        "turbo": "mlx-community/whisper-large-v3-turbo",
        "large-v3": "mlx-community/whisper-large-v3-mlx",
        "base": "mlx-community/whisper-base-mlx",
        "breeze": "BRlin/Breeze-ASR-25-mlx-fp16",
    },
}
# Breeze-ASR-25：MediaTek Research 以 Whisper large-v2 微調的台灣華語／中英夾雜模型（Apache-2.0）
BREEZE_SOURCE = "MediaTek-Research/Breeze-ASR-25"
BACKENDS = tuple(WHISPER_MODELS)
DEFAULT_WHISPER = "turbo"

SEG_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2")
EMB_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
           "speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
SAMPLE_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
              "speaker-segmentation-models/0-four-speakers-zh.wav")

# CT-Transformer 標點模型（FunASR Model License 1.1；sherpa-onnx 轉換的 int8 版）。安裝時下載，不打包進 zip。
PUNCT_NAME = "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
PUNCT_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             f"punctuation-models/{PUNCT_NAME}.tar.bz2")
PUNCT_SHA256 = "c0d5aa5f8eeb686032345e180bedf39319dc2e0556781c6264bcadba8328a6e1"
PUNCT_SIZE = 64717756
PUNCT_FILES = ("model.int8.onnx", "README.md", "config.yaml")   # 其餘檔只是轉換腳本，不解出
PUNCT_MIN_BYTES = 50 * 1024 * 1024

# config.json 新鍵的預設值（1.1.0 起；1.2.0 加 correction.ask_default、minutes）（讀取一律經 setting()；鍵不存在時用這裡的值，不在讀取時寫回）
DEFAULTS = {
    "runtime_version": VERSION,
    "punctuation": {
        "enabled": True,                 # 本機分段標點
        "model": "ct-transformer-int8",  # 1.1.0 只有這一個值
        "paragraph_gap": 2.0,            # 秒；與上一個 segment 的間隔 >= 此值就換段
        "paragraph_max_chars": 200,      # 段落累積到此字數（內容字元）就換段
        "whisper_density": 20,           # 每 N 個內容字元至少 1 個標點，才沿用 Whisper 標點（非 Breeze）
    },
    "opencc_keep": {"enabled": True},    # OpenCC 詞彙回復表
    "correction": {                      # 自動語意校正（行為由 auto_correct.py 實作；1.1.0）
        # 〔1.2.0〕enabled 只管「直接執行 transcribe.py、沒有 --correct／--no-correct」時要不要校正
        # （Claude CLI／對話）；右鍵／拖放入口一律在轉寫後詢問，不看 enabled
        "enabled": False,
        "ask_default": True,             # 〔1.2.0〕入口詢問「要做 AI 校正嗎？」時按 Enter 的答案（True＝是）
        "provider": "auto",              # auto | claude | openai；auto＝有已登入的 codex CLI 用 GPT，否則有 claude CLI 用 Claude
        "channel": "cli",                # cli（訂閱 claude -p／codex exec）| api（官方 SDK＋環境變數金鑰）
        "chunk_chars": 3500,
        "timeout_sec": 600,
        "confirm_over_minutes": 120,
        "claude": {
            "model": "opus",             # sonnet | opus | haiku | 以 claude- 開頭的完整 ID（1.1.0 實測：opus medium 在 M1、M3 都達 C1／C2）
            "effort": "medium",          # low | medium | high（1.1.0 實測：medium 不劣化，預設改 medium）
            "cli_path": None,
            "api_model_ids": {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"},
        },
        "openai": {
            "model": "gpt-6.1-sol",      # OpenAI 模型 ID 本身就是會跟著更新的別名；CLI 與 API 傳同一個值
            "effort": "low",             # low | medium | high | xhigh | max（API 一定明確傳）
            "cli_path": None,
        },
        "corrections_auto": {            # 對照表條件式自動寫入（1.1.0）；off＝只產生 corrections.suggested.tsv
            "mode": "off",               # off | on
            "min_count": 2,              # ① 單場同一修正出現次數下限
            "min_meetings": 2,           # ② 累計在幾場不同會議被建議同一修正（1＝當場寫入）
            "models": ["claude:sonnet", "claude:opus", "openai:gpt-6.1-sol"],   # ④ <provider>:<model>（1.1.0 起加 OpenAI）
            "max_per_run": 5,            # ⑤ 每場最多寫入幾筆
        },
    },
    "minutes": {                         # 〔1.2.0〕會議摘要（auto_minutes.py）；CLI 路徑沿用 correction.<家>.cli_path
        "ask_default": True,             # 入口詢問「要產生會議摘要嗎？」時按 Enter 的答案（True＝是）
        "provider": "auto",              # auto | claude | openai；auto 的選法與 correction 相同（已登入的 codex 優先＝GPT）
        "channel": "cli",                # cli | api
        "chunk_chars": 12000,            # 每段字數（內容字元）；超過就分段整理再彙整
        "timeout_sec": 900,
        "claude": {"model": "opus", "effort": "medium"},
        "openai": {"model": "gpt-6.1-sol", "effort": "low"},
    },
    # ---------------------------------------------------------------- 〔2.0.0〕規格 §6.1
    "content_type": {
        "default": "meeting",            # 入口第一次、與 transcribe.py／auto_minutes.py 沒指定時的類型
        "remember_last": True,           # 入口按 Enter＝上次選的類型（存在 $MMH/state.json）；False＝一律 default
    },
    "diarization": {
        "engine": "auto",                # auto | sherpa | pyannote（規格 §4.1）
        "cluster_threshold": 0.9,        # sherpa 自動分群門檻（2.0.0；越大講者越少）
        "minor_speaker_note_sec": 10,    # 總發言少於此秒數標「可能是分離誤判」（U2）
        "min_vram_mib": 4096,            # auto 選 pyannote 的可用 VRAM 下限
        "pyannote": {
            "status": "none",            # none（沒裝）| incomplete（裝到一半：見 reason）| ready；由安裝程式寫入
            "reason": None,              # incomplete 的原因代碼（規格 §8.5）
            "model": "pyannote/speaker-diarization-community-1",
            "timeout_factor": 0.5,       # 逾時＝max(timeout_min_sec, 錄音秒數 × timeout_factor)
            "timeout_min_sec": 600,
        },
    },
    "keyframes": {"scene": 0.3, "max_frames": 60},   # 影片關鍵畫面（1.2.2 的命令列預設值搬成設定）
    "content_types": {                   # 只放與共用值不同的項目；允許的鍵：cluster_threshold、scene、diarize_engine（其他鍵讀取時忽略）
        "course": {"cluster_threshold": 1.0},
        "panel": {"cluster_threshold": 0.8, "diarize_engine": "sherpa"},   # 〔2.0.0〕座談預設 sherpa（2.0.0 實測：pyannote 在 PN1 併掉觀眾）
        "tutorial": {"scene": 0.1},
    },
    "subtitles": {                       # 字幕（行為由 I-3 的 subtitles.py 實作；規格 §5）
        "cues_srt": True,
        "corrected_srt": True,
        "recue": True,
        "max_line_chars": 16, "max_lines": 2, "min_sec": 0.833, "max_sec": 7.0, "max_cps": 9,
        "speaker_label": "change",       # change | always | none
        "uncertain": "orig",             # orig | guess | mark（U6）
    },
    # ---------------------------------------------------------------- 〔2.1.0〕網頁版（規格 2.1.0 §6.1）
    "html": {
        "enabled": True,                 # auto_minutes.py 寫完 .md 後產生網頁版（規格 2.1.0 §6.1：預設產出）
        "media": "auto",                 # auto＝依規格 §5.2 找原始媒體並放播放器；off＝不放播放器（時間碼一律純文字）
        "theme": "dark",                 # dark | light：網頁版第一次開啟時的主題（之後依使用者在頁面上的選擇）
    },
    # ---------------------------------------------------------------- 〔2.2.0〕參考資料（規格 2.2.0 §8.1）
    "reference": {
        "frames": True,                  # AI 校正時送截圖（預設開）
        "max_frames": 8,                 # 送出的截圖上限（0＝不送）
        "frame_max_px": 1280,            # 截圖縮到長邊不超過這個值
        "docs": True,                    # 讀會議文件（媒體旁、refs/）
        "context": True,                 # 讀說明檔（<主檔名>.context.md）與輸出資料夾的 context.md
        "ask_context": True,             # 入口問一行背景說明（False＝不問，但檔案照讀）
        "terms_max_chars": 1500,         # 送出的文件名詞字數上限
        "paragraphs_max_chars": 4000,    # 送出的文件段落字數上限（每段最多 400 字）
        "doc_max_files": 10,             # 最多讀幾份文件
        "doc_max_mb": 50,                # 單一文件大小上限（MB）
        "pdf_max_pages": 200,            # PDF 最多讀前幾頁
    },
    # ---------------------------------------------------------------- 〔2.2.0〕全文用字統一（consistency.py；本機處理，不呼叫模型）
    "consistency": {
        "enabled": True,                 # 校正版、字幕、會議記錄／筆記裡同一個名詞統一寫法（大小寫、空格、「.」「-」）
    },
    # ---------------------------------------------------------------- 〔2.4.0〕本機限定（規格 2.4.0 §2）
    "privacy": {
        "local_only": False,             # True＝這部電腦的每一份都不送雲端：AI 校正與摘要拒絕送出，入口不問
    },
}
# 〔2.1.0〕html 區塊每個鍵認得的值（不認得 → 用預設並印提示，html_setting()）
HTML_CHOICES = {"enabled": (True, False), "media": ("auto", "off"), "theme": ("dark", "light")}
# 〔2.2.0〕reference 區塊的鍵：布林鍵與數字鍵（不認得 → 用預設並印提示；數字小於 0 當 0，reference_setting()）
REFERENCE_BOOL_KEYS = ("frames", "docs", "context", "ask_context")
REFERENCE_INT_KEYS = ("max_frames", "frame_max_px", "terms_max_chars", "paragraphs_max_chars", "doc_max_files",
                      "doc_max_mb", "pdf_max_pages")
# 〔2.0.0〕content_types.<代號> 允許的鍵 → 對應的共用鍵（規格 §6.1：type_setting() 的退回順序）
TYPE_SETTING_SHARED = {"cluster_threshold": "diarization.cluster_threshold", "scene": "keyframes.scene",
                       "diarize_engine": "diarization.engine"}       # 〔2.0.0〕diarize_engine：類型別的說話者分離引擎
# 〔2.0.0〕upgrade_config() 補的 2.0 區塊；巢狀區塊只有部分鍵時逐鍵補（content_types 由使用者增刪，只在整塊不存在時寫入）
V2_BLOCKS = ("content_type", "diarization", "keyframes", "content_types", "subtitles")
V2_DEEP_FILL = ("content_type", "diarization", "keyframes", "subtitles")
# 〔2.1.0〕upgrade_config() 補的 2.1 區塊（做法同 V2_BLOCKS：整塊不存在就寫入，部分鍵存在時逐鍵補）
V21_BLOCKS = ("html",)
# 〔2.2.0〕upgrade_config() 補的 2.2 區塊（做法同上：整塊不存在就寫入，部分鍵存在時逐鍵補）
V22_BLOCKS = ("reference", "consistency")
# 〔2.4.0〕upgrade_config() 補的 2.4 區塊（做法同上；既有的 local_only 值一律保留）
V24_BLOCKS = ("privacy",)
LEGACY_CLAUDE_TOP = ("enabled", "channel", "chunk_chars", "timeout_sec", "confirm_over_minutes")
_MISSING = object()


# 〔1.2.2〕安裝程式執行 setup_backend.py 時設成 "1"：版號不一致的提示改印「升級中」（入口與一般執行不設，照舊提示重裝）
INSTALLING_ENV = "MMP_INSTALLING"


def version_banner(cfg: dict | None = None) -> str:
    """〔1.2.0〕console 第一行：meeting-minutes-pro <版號>。config.json 的 runtime_version 不同時兩個都印並標示。"""
    if cfg is None:
        cfg = load_config()
    rv = (cfg or {}).get("runtime_version")
    s = f"meeting-minutes-pro {VERSION}"
    if rv and rv != VERSION:
        if os.environ.get(INSTALLING_ENV) == "1":
            # 〔1.2.2〕安裝程式在更新 runtime_version 之前執行 setup_backend.py：這是升級中的暫時狀態，不叫使用者重裝
            s += f"（升級中：{rv} → {VERSION}，安裝完成後更新 config.json 的 runtime_version）"
        else:
            s += f"（config.json 的 runtime_version 是 {rv}，版號不一致：請重新執行安裝程式）"
    return s


def print_banner(cfg: dict | None = None):
    """直接執行 transcribe.py／auto_correct.py／auto_minutes.py／setup_backend.py 時的第一行（寫到 stderr，stdout 留給 JSON）。"""
    print(version_banner(cfg), file=sys.stderr, flush=True)


def utf8_console():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # Windows console (cp950) safety
        except Exception:  # noqa: BLE001
            pass


def data_home() -> Path:
    """Runtime root. Override with MEETING_MINUTES_PRO_HOME."""
    env = os.environ.get("MEETING_MINUTES_PRO_HOME")
    if env:
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "meeting-minutes-pro"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "meeting-minutes-pro"
    return Path.home() / ".cache" / "meeting-minutes-pro"


def models_dir() -> Path:
    return data_home() / "models"


def whisper_repo(backend: str, alias_or_repo: str) -> str:
    return WHISPER_MODELS.get(backend, {}).get(alias_or_repo, alias_or_repo)


def whisper_dir(backend: str, alias_or_repo: str) -> Path:
    return models_dir() / backend / whisper_repo(backend, alias_or_repo).split("/")[-1]


def whisper_ready(backend: str, alias: str) -> bool:
    d = whisper_dir(backend, alias)
    if backend == "openvino":
        return (d / "openvino_encoder_model.xml").exists()
    if backend == "mlx":
        return (d / "config.json").exists() and any((d / w).exists() for w in ("weights.safetensors", "weights.npz"))
    # ct2：model.bin 之外還需要 tokenizer.json，否則 faster-whisper 會在轉寫時連網下載
    return (d / "model.bin").exists() and (d / "tokenizer.json").exists()


def seg_model() -> Path:
    return models_dir() / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"


def emb_model() -> Path:
    return models_dir() / EMB_URL.rsplit("/", 1)[-1]


def sample_wav() -> Path:
    return data_home() / "samples" / "four-speakers-zh.wav"


def default_glossary() -> Path:
    return data_home() / "glossary.txt"


def config_path() -> Path:
    return data_home() / "config.json"


# ---------------------------------------------------------------- 〔2.4.1〕config.json 讀不了（規格 2.4.1 §2、§3）
# 讀取分成三種結果：不存在（missing）、讀得到（ok）、讀不了（unreadable，附原因代碼）。讀不了時：
#   - 一般設定（後端、詞表…）照舊用預設值（load_config() 回 {}）；
#   - 全域本機限定當成「開」（local_only_state() 的來源 config-unreadable），寧可多擋、不外送；
#   - 寫入端（save_config()、upgrade_config()、setup_gpu_diar.py）一律不寫，丟 ConfigUnreadable（原檔逐位元不變）。
CONFIG_PROBLEM_TEXT = {
    "permission": "沒有讀取權限",
    "os_error": "讀取失敗",
    "is_dir": "是資料夾，不是檔案",
    "empty": "是空檔",
    "not_utf8": "不是 UTF-8 編碼",
    "bad_json": "不是合法的 JSON",
    "not_object": "最外層不是 JSON 物件",
    "bad_value": "值看不懂",
}
CONFIG_UNREADABLE_EXIT = 5     # common.py check-config：config.json 存在但讀不了


class ConfigUnreadable(Exception):
    """〔2.4.1〕config.json 存在但讀不了：寫入端不寫，原檔不動。str() 是給使用者看的完整訊息。"""

    def __init__(self, info: dict):
        self.info = info
        super().__init__(config_write_refused_message(info))


def read_config() -> dict:
    """〔2.4.1〕讀 config.json，回傳 {"status": "missing"／"ok"／"unreadable", "config": dict（讀不了或不存在時是 {}）,
    "path": str, "reason": 原因代碼或 None, "detail": 補充說明或 None}。不丟例外。
    原因代碼：permission、os_error（被鎖、其他 OSError）、is_dir、empty（空檔或只有空白）、not_utf8、
    bad_json（含開頭有 BOM）、not_object（最外層不是物件）。"""
    p = config_path()
    out = {"status": "ok", "config": {}, "path": str(p), "reason": None, "detail": None}

    def bad(reason, detail=None):
        out.update(status="unreadable", reason=reason, detail=detail)
        return out

    try:
        raw = p.read_bytes()
    except FileNotFoundError:
        out["status"] = "missing"
        return out
    except IsADirectoryError:
        return bad("is_dir")
    except PermissionError as ex:
        if p.is_dir():                    # Windows 對資料夾 open() 回 PermissionError
            return bad("is_dir")
        return bad("permission", ex.strerror or type(ex).__name__)
    except OSError as ex:
        return bad("os_error", ex.strerror or type(ex).__name__)
    if not raw.strip():
        return bad("empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as ex:
        return bad("not_utf8", f"第 {ex.start + 1} 個位元組")
    if text.startswith("\ufeff"):
        return bad("bad_json", "開頭有 BOM，請存成不含 BOM 的 UTF-8")
    try:
        data = json.loads(text)
    except ValueError as ex:
        line, col = getattr(ex, "lineno", None), getattr(ex, "colno", None)
        return bad("bad_json", f"第 {line} 行第 {col} 欄" if line else None)
    if not isinstance(data, dict):
        return bad("not_object", f"是{_json_kind(data)}")
    out["config"] = data
    return out


def _json_kind(v) -> str:
    if v is None:
        return " null"
    if isinstance(v, bool):
        return " true" if v else " false"
    return {list: "陣列", str: "字串", int: "數字", float: "數字"}.get(type(v), type(v).__name__)


def _shown(v) -> str:
    """設定值的顯示（給訊息用；最多 40 字）。"""
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 40 else s[:39] + "…"


def config_problem_text(info: dict) -> str:
    """〔2.4.1〕讀不了或值看不懂的原因（一句，不含路徑）。例「config.json 讀不了：不是合法的 JSON（第 3 行第 5 欄）」。"""
    r = info.get("reason")
    if r == "bad_value":
        return f"config.json 的值看不懂：{info.get('detail')}"
    s = f"config.json 讀不了：{CONFIG_PROBLEM_TEXT.get(r, r)}"
    if info.get("detail"):
        s += f"（{info['detail']}）"
    return s


def config_write_refused_message(info: dict) -> str:
    """〔2.4.1〕寫入端遇到讀不了的 config.json 時的訊息（安裝程式與 setup_*.py 印出）。"""
    return (f"{config_problem_text(info)}：{info.get('path')}\n"
            "為了不覆寫你的設定（包括本機限定 privacy.local_only），這次沒有寫入任何東西，檔案沒有被改動。\n"
            "請修好這個檔（UTF-8 的 JSON 物件，例如用記事本打開找出錯誤），或刪掉它，然後重新執行。"
            "刪掉的話，重新執行安裝程式會建立新的 config.json（本機限定是關，硬體重新偵測）。")


def load_config() -> dict:
    """讀 config.json。不存在或讀不了都回 {}（一般設定用預設值）；〔2.4.1〕要分辨兩者用 read_config()。
    讀不了時全域本機限定由 local_only_state() 另外判定為開。"""
    return read_config()["config"]


def load_config_for_write() -> dict:
    """〔2.4.1〕寫入端用：不存在 → {}；讀得到 → 內容；讀不了 → 丟 ConfigUnreadable（不寫，原檔不動）。"""
    rc = read_config()
    if rc["status"] == "unreadable":
        raise ConfigUnreadable(rc)
    return rc["config"]


def save_config(**kw):
    cfg = load_config_for_write()       # 〔2.4.1〕讀不了 → ConfigUnreadable，不覆寫
    cfg.update(kw)
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def corrections_path() -> Path:
    return data_home() / "corrections.tsv"


def setting(cfg: dict, dotted: str, defaults: dict | None = None):
    """讀設定值：cfg 有就用 cfg 的，否則用 defaults（預設 DEFAULTS）的值。不寫回 config.json。

    例：setting(cfg, "punctuation.paragraph_gap") -> 2.0
    """
    defaults = DEFAULTS if defaults is None else defaults
    keys = dotted.split(".")
    for src in (cfg or {}, defaults):
        cur = src
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                cur = _MISSING
                break
        if cur is not _MISSING:
            return copy.deepcopy(cur)
    raise KeyError(dotted)


def _merge(dst: dict, src: dict) -> dict:
    """把 src 合併進 dst：兩邊都是 dict 的鍵往下合併，其他鍵以 src 為準。"""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = copy.deepcopy(v)
    return dst


def migrate_claude_block(cfg: dict) -> bool:
    """1.1.0 開發期寫的 claude 區塊 → correction。correction 已存在時只刪掉舊鍵。回傳是否有改動。"""
    old = cfg.get("claude")
    if not isinstance(old, dict):
        return False
    del cfg["claude"]
    if "correction" in cfg:
        return True
    new = {k: old[k] for k in LEGACY_CLAUDE_TOP if k in old}
    sub = {k: old[k] for k in ("model", "effort", "cli_path", "api_model_ids") if k in old}
    if sub:
        new["claude"] = sub
    if old.get("enabled") and "provider" not in new:
        new["provider"] = "claude"          # 舊設定是明確開啟 Claude：沿用，不讓 auto 改送 OpenAI
    cfg["correction"] = _merge(copy.deepcopy(DEFAULTS["correction"]), new)
    return True


def type_setting(cfg: dict, ctype: str | None, key: str):
    """〔2.0.0〕類型別設定（規格 §6.1）：content_types.<type>.<key> → 共用鍵 → DEFAULTS。

    key 只能是 cluster_threshold、scene、diarize_engine（〔2.0.0〕diarize_engine 對 diarization.engine）。
    config.json 沒有 content_types 區塊（尚未升級）時，類型別的值取 DEFAULTS 的 content_types；有這個區塊時以使用者的為準
    （使用者刪掉某類型的鍵＝改用共用值）。要知道值是不是來自類型鍵，用 type_entry()。
    """
    v = type_entry(cfg, ctype, key)
    return v if v is not None else setting(cfg, TYPE_SETTING_SHARED[key])


def type_entry(cfg: dict, ctype: str | None, key: str):
    """〔2.0.0〕只看 content_types.<type>.<key>（沒有區塊時看 DEFAULTS 的）；沒有設定回傳 None（＝用共用鍵）。"""
    if key not in TYPE_SETTING_SHARED:
        raise KeyError(key)
    block = (cfg or {}).get("content_types")
    if not isinstance(block, dict):
        block = DEFAULTS["content_types"]
    entry = block.get(ctype) if ctype else None
    if isinstance(entry, dict) and entry.get(key) is not None:
        return copy.deepcopy(entry[key])
    return None


def _fill_missing(dst: dict, defaults: dict) -> dict:
    """defaults 有、dst 沒有的鍵補進 dst（往下遞迴）；dst 已有的值一律不動。"""
    for k, v in defaults.items():
        if k not in dst:
            dst[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(dst[k], dict):
            _fill_missing(dst[k], v)
    return dst


def upgrade_config(correction: dict | None = None) -> dict:
    """安裝時執行：補上 1.1.0／1.2.0／2.0.0 新增的設定鍵，已存在的鍵與使用者改過的值一律保留。

    - punctuation、opencc_keep、correction、minutes（1.2.0）：整塊不存在才寫入預設值（correction.enabled 先寫 False）。
    - 〔1.2.0〕從 1.1.0 升級時 correction 區塊原樣保留、不補 ask_default：讀取時 setting() 用預設 True。
      1.1.0 的 enabled: false 不影響入口詢問（入口不再看 enabled），兩題按 Enter 都是「是」（1.2.0）。
    - 1.1.0 開發期的 claude 區塊改名成 correction（migrate_claude_block）。
    - 〔2.0.0〕content_type、diarization、keyframes、content_types、subtitles：整塊不存在才寫入預設值
      （diarization.pyannote.status 寫 none；之後只由安裝程式改）；content_type、diarization、keyframes、subtitles
      只有部分鍵時逐鍵補上缺的鍵（既有的值不變）；content_types 由使用者增刪，只在整塊不存在時寫入。
    - 〔2.1.0〕html：整塊不存在才寫入預設值（enabled: true）；只有部分鍵時逐鍵補上缺的鍵。使用者寫的值（含不認得的值）
      照原樣保留，讀取時由 html_setting() 改用預設並印提示。
    - 〔2.2.0〕reference：做法同 html（整塊不存在才寫入預設值，全部開；部分鍵存在時逐鍵補）；讀取由 reference_setting()。
      consistency（全文用字統一）同樣做法（預設開）；讀取由 consistency.enabled()。
    - 〔2.4.0〕privacy：做法同上（整塊不存在才寫入 local_only: false；使用者設的 true 一律保留）；讀取由 local_only_state()。
    - 〔2.4.1〕config.json 存在但讀不了（read_config() 的 unreadable）→ 丟 ConfigUnreadable，什麼都不寫（原檔逐位元不變）。
    - correction 參數（安裝程式的明確選擇，例 -Correct、-CorrectProvider openai、{"openai": {"model": …}}）
      不論區塊是否已存在都會寫入；巢狀的 claude／openai／corrections_auto 逐鍵合併。
    - runtime_version 每次都更新成 VERSION。
    回傳寫入後的 config。
    """
    cfg = load_config_for_write()       # 〔2.4.1〕讀不了 → ConfigUnreadable，不覆寫
    migrate_claude_block(cfg)
    for key in ("punctuation", "opencc_keep", "correction", "minutes") + V2_BLOCKS + V21_BLOCKS + V22_BLOCKS + V24_BLOCKS:
        if key not in cfg:
            cfg[key] = copy.deepcopy(DEFAULTS[key])
        elif key in V2_DEEP_FILL + V21_BLOCKS + V22_BLOCKS + V24_BLOCKS and isinstance(cfg[key], dict):
            _fill_missing(cfg[key], DEFAULTS[key])
    if correction:
        if not isinstance(cfg.get("correction"), dict):
            cfg["correction"] = copy.deepcopy(DEFAULTS["correction"])
        _merge(cfg["correction"], correction)
    cfg["runtime_version"] = VERSION
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def html_setting(cfg: dict, key: str, warn=None):
    """〔2.1.0〕讀 html.<key>（enabled／media／theme；規格 §6.1）。不認得的值當成預設值，並印一行提示（warn 預設印到 stderr）。"""
    default = DEFAULTS["html"][key]
    v = setting(cfg, "html." + key)
    ok = isinstance(v, bool) if key == "enabled" else (isinstance(v, str) and v in HTML_CHOICES[key])
    if ok:
        return v
    shown = json.dumps(default) if isinstance(default, bool) else default
    msg = f"[!] html.{key} 的值 {v} 不認得，改用 {shown}"
    if warn is None:
        print(msg, file=sys.stderr, flush=True)
    else:
        warn(msg)
    return default


def reference_setting(cfg: dict, key: str, warn=None):
    """〔2.2.0〕讀 reference.<key>（規格 2.2.0 §8.1）。布林鍵要是 true／false，數字鍵要是整數（小於 0 當 0）；
    不認得的值當成預設值，並印一行提示（warn 預設印到 stderr，同 html_setting()）。"""
    default = DEFAULTS["reference"][key]
    try:
        v = setting(cfg, "reference." + key)
    except KeyError:
        v = default
    if key in REFERENCE_BOOL_KEYS:
        if isinstance(v, bool):
            return v
    elif isinstance(v, int) and not isinstance(v, bool):
        return max(0, v)
    shown = json.dumps(default) if isinstance(default, bool) else default
    msg = f"[!] reference.{key} 的值 {v} 不認得，改用 {shown}"
    if warn is None:
        print(msg, file=sys.stderr, flush=True)
    else:
        warn(msg)
    return default


def added_config_keys(before: dict, after: dict, prefix: str = "") -> list:
    """〔1.2.2〕安裝時的「更新設定」比對：after 有、before 沒有的鍵（點分隔路徑；整塊新增只列區塊名）。

    runtime_version 每次安裝都會更新，不算「補上的鍵」。安裝程式依結果印「已補上新版設定鍵：…」或「設定鍵無變更」。
    """
    out = []
    before = before if isinstance(before, dict) else {}
    for k, v in (after or {}).items():
        path = f"{prefix}{k}"
        if path == "runtime_version":
            continue
        if k not in before:
            out.append(path)
        elif isinstance(v, dict) and isinstance(before.get(k), dict):
            out.extend(added_config_keys(before[k], v, path + "."))
    return out


def logs_dir() -> Path:
    """〔1.2.0〕跨場次的執行摘要 runs.jsonl 放這裡。"""
    return data_home() / "logs"


def user_pricing_path() -> Path:
    """〔1.2.0〕使用者自己的價格表（選用，蓋過 scripts/pricing.json 的同名項目）。"""
    return data_home() / "pricing.json"


def correction_history_path() -> Path:
    """對照表建議歷史（只存詞對、次數、場次、日期）。"""
    return data_home() / "corrections_history.json"


def state_path() -> Path:
    """〔2.0.0〕入口記住的上次類型（規格 §7.2）；不寫進 config.json。"""
    return data_home() / "state.json"


def templates_dir() -> Path:
    """〔2.0.0〕使用者自訂範本目錄 $MMH/templates（規格 §3.8.1）。"""
    return data_home() / "templates"


# 〔2.0.0〕GPU 說話者分離（選用安裝，規格 §4.2、§8）：獨立 venv＋本機權重
PYANNOTE_MODEL_NAME = "pyannote-speaker-diarization-community-1"
PYANNOTE_MODEL_FILES = ("config.yaml", "segmentation/pytorch_model.bin", "embedding/pytorch_model.bin",
                        "plda/plda.npz", "plda/xvec_transform.npz")


def gpu_diar_dir() -> Path:
    return data_home() / "venv-gpu-diar"


def gpu_diar_python() -> Path:
    d = gpu_diar_dir()
    return d / "Scripts" / "python.exe" if sys.platform == "win32" else d / "bin" / "python"


def pyannote_model_dir() -> Path:
    return models_dir() / PYANNOTE_MODEL_NAME


def punct_model_dir() -> Path:
    return models_dir() / PUNCT_NAME


def punct_model() -> Path:
    return punct_model_dir() / "model.int8.onnx"


def punct_ready() -> bool:
    p = punct_model()
    return p.exists() and p.stat().st_size > PUNCT_MIN_BYTES


def opencc_keep_paths() -> tuple:
    """(內建表, 使用者表)。內建表隨腳本更新；使用者表在 runtime 根目錄，安裝時不存在才建立。"""
    return Path(__file__).resolve().parent / "opencc_keep_default.tsv", data_home() / "opencc_keep.tsv"


# ---------------------------------------------------------------- 〔2.4.0〕本機限定（規格 2.4.0 §2）
# 兩種開法，任一成立就是本機限定：全域 config.json 的 privacy.local_only: true；或輸出資料夾裡有標記檔 local-only.json
# （「會議轉寫（Pro，本機限定）」入口或 transcribe.py --local-only 寫入）。本機限定時 AI 校正與摘要拒絕送出（exit 6），
# 沒有任何命令列旗標可以略過；要解除只能改 config.json 或刪掉標記檔。
LOCAL_ONLY_MARKER = "local-only.json"
LOCAL_ONLY_EXIT = 6
LOCAL_ONLY_SOURCES = ("config", "config-unreadable", "marker")   # 〔2.4.1〕config-unreadable：config.json 讀不了或值看不懂


def local_only_marker(out_dir) -> Path:
    return Path(out_dir) / LOCAL_ONLY_MARKER


def write_local_only_marker(out_dir, source: str, created_at: str | None = None) -> Path:
    """在輸出資料夾寫入本機限定標記檔（已有就保留原檔，回傳路徑）。source：寫入的入口（例 sendto、dropped、transcribe）。
    內容只有標記、建立時間、來源與版號（不含任何逐字稿內容或檔名）。"""
    p = local_only_marker(out_dir)
    if p.exists():
        return p
    if created_at is None:
        from datetime import datetime
        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"local_only": True, "created_at": created_at, "source": source, "version": VERSION,
           "note": "本機限定：這份不送 GPT 或 Claude。要解除，刪除這個檔案。"}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
    return p


def config_local_only(cfg: dict | None = None) -> dict | None:
    """〔2.4.1〕全域本機限定（config.json）的判定，規格 2.4.1 §2 的判定表：
    - config.json 不存在；或讀得到且 privacy 不存在、privacy.local_only 不存在或是 false → None（關）
    - privacy.local_only 是 true → {"source": "config"}
    - 存在但讀不了（權限、被鎖、其他 OSError、不是 UTF-8、不是合法 JSON、空檔、最外層不是物件）
      → {"source": "config-unreadable", "reason": 原因代碼, "detail", "path"}
    - privacy 不是物件，或 local_only 是 true／false 以外的值 → 同上，reason "bad_value"
    cfg 有給時用 cfg 的值判斷 privacy（相容 2.4.0 的呼叫方式），但檔案讀不了時一律是 config-unreadable。"""
    rc = read_config()
    if rc["status"] == "unreadable":
        return {"source": "config-unreadable", "reason": rc["reason"], "detail": rc["detail"], "path": rc["path"]}
    if cfg is None:
        cfg = rc["config"]
    if not isinstance(cfg, dict) or "privacy" not in cfg:
        return None
    priv = cfg["privacy"]
    if not isinstance(priv, dict):
        return {"source": "config-unreadable", "reason": "bad_value", "path": rc["path"],
                "detail": f"privacy 應該是物件（{{ … }}），現在是 {_shown(priv)}"}
    if "local_only" not in priv or priv["local_only"] is False:
        return None
    if priv["local_only"] is True:
        return {"source": "config"}
    return {"source": "config-unreadable", "reason": "bad_value", "path": rc["path"],
            "detail": f"privacy.local_only 是 {_shown(priv['local_only'])}，只認得 true 或 false"}


def local_only_state(out_dir=None, cfg: dict | None = None) -> dict | None:
    """本機限定的判定。不是本機限定 → None；是 → {"local_only": True, "sources": [...], "source": "+" 連起來}。
    sources：「config」（privacy.local_only: true）或〔2.4.1〕「config-unreadable」（config.json 讀不了或值看不懂，
    另有 "config_problem": {reason, detail, path}），以及「marker」（輸出資料夾有標記檔）。
    cfg 為 None 時讀 config.json；out_dir 為 None 時只看全域設定。
    標記檔只看「存在」：內容讀不懂或是空檔也算（寧可多擋）。"""
    sources = []
    g = config_local_only(cfg)
    if g:
        sources.append(g["source"])
    if out_dir is not None and local_only_marker(out_dir).exists():
        sources.append("marker")
    if not sources:
        return None
    st = {"local_only": True, "sources": sources, "source": "+".join(sources)}
    if g and g["source"] == "config-unreadable":
        st["config_problem"] = {k: g.get(k) for k in ("reason", "detail", "path")}
    return st


def local_only_why(state: dict, out_dir=None) -> list:
    """〔2.4.1〕本機限定的原因（每個來源一句，給入口、transcribe.py 與拒絕訊息用）。"""
    why = []
    for src in state["sources"]:
        if src == "config":
            why.append("config.json 的 privacy.local_only 是 true")
        elif src == "config-unreadable":
            why.append(config_problem_text(state["config_problem"]) + "；為了不外送，已當成本機限定")
        elif src == "marker":
            why.append(f"輸出資料夾有標記檔 {LOCAL_ONLY_MARKER}")
    return why


def local_only_how(state: dict, out_dir=None) -> list:
    """〔2.4.1〕怎麼解除（每個來源一句）。"""
    how = []
    for src in state["sources"]:
        if src == "config":
            how.append(f"把 {config_path()} 的 privacy.local_only 改成 false")
        elif src == "config-unreadable":
            cp = state["config_problem"]
            need = "privacy.local_only 只能是 true 或 false" if cp.get("reason") == "bad_value" else "存成 UTF-8 的 JSON 物件"
            how.append(f"修好 {cp.get('path') or config_path()}（{need}）；或刪掉它再重新執行安裝程式（重建的 config.json 本機限定是關）")
        elif src == "marker":
            where = local_only_marker(out_dir) if out_dir is not None else LOCAL_ONLY_MARKER
            how.append(f"刪除 {where}")
    return how


def local_only_message(state: dict, what: str, out_dir=None) -> str:
    """拒絕送出時的固定訊息（stderr）：為什麼、怎麼解除。what：「AI 校正」「會議摘要」等。"""
    return (f"本機限定（{'、'.join(local_only_why(state, out_dir))}）：{what}會把內容送到 GPT 或 Claude，已拒絕，"
            f"沒有送出任何資料。要解除：{'；並'.join(local_only_how(state, out_dir))}。")


def _cli(argv: list) -> int:
    """〔2.4.1〕命令列（入口與安裝程式用；只用標準函式庫，系統 Python 也能跑）：
    common.py local-only [--out-dir 資料夾] [--lines]：印本機限定判定的 JSON（local_only、source、why、how、
        config_problem；--lines 改印 4 行：1／0、來源、原因、解除方法）；exit 0
    common.py check-config：印 read_config() 的狀態 JSON；讀不了時 stderr 印訊息、exit 5（CONFIG_UNREADABLE_EXIT）"""
    utf8_console()
    if argv[:1] == ["local-only"]:
        out_dir = argv[argv.index("--out-dir") + 1] if "--out-dir" in argv else None
        st = local_only_state(out_dir)
        doc = {"local_only": False, "source": None}
        if st:
            doc = {"local_only": True, "source": st["source"], "sources": st["sources"],
                   "why": "、".join(local_only_why(st, out_dir)), "how": "；".join(local_only_how(st, out_dir))}
            if "config_problem" in st:
                doc["config_problem"] = st["config_problem"]
        if "--lines" in argv:            # mm-dropped.sh 用：4 行（1／0、來源、原因、解除方法），不必解析 JSON
            print("\n".join(["1" if doc["local_only"] else "0", doc.get("source") or "", doc.get("why", ""),
                             doc.get("how", "")]))
        else:
            print(json.dumps(doc, ensure_ascii=False))
        return 0
    if argv[:1] == ["check-config"]:
        rc = read_config()
        print(json.dumps({k: rc[k] for k in ("status", "reason", "detail", "path")}, ensure_ascii=False))
        if rc["status"] == "unreadable":
            print(config_write_refused_message(rc), file=sys.stderr)
            return CONFIG_UNREADABLE_EXIT
        return 0
    print("用法：common.py local-only [--out-dir 資料夾] [--lines]｜common.py check-config", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
