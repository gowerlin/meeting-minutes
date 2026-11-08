"""〔2.2.0〕隱私說明文字檢查（規格 2.2.0 §11.4 第一點、§9.1）：2.2.0 起 AI 校正會送出影片截圖與參考資料，
說明文字不得再寫「只送文字、不送截圖」。

- 掃版本目錄裡全部文字檔（.md、.py、.ps1、.sh、.cmd、.command、.txt）：舊說法出現 0 次；
  允許清單（正確的句子）：「摘要不送截圖」「截圖沒有送給摘要」。
- 改寫後的關鍵句子在該在的位置（SKILL、README、安裝程式、入口、會議摘要的〈轉寫品質備註〉、範本說明）。
不呼叫任何模型；2.2.0 以前的版本整個略過。
"""
import unittest

import _testenv

V22 = _testenv.VER >= (2, 2, 0)
VD = _testenv.VERSION_DIR
EXTS = {".md", ".py", ".ps1", ".sh", ".cmd", ".command", ".txt"}
BANNED = ("只送逐字稿文字，沒有送截圖", "音檔與截圖不會", "不含音檔與截圖", "不送截圖", "沒有送截圖", "截圖不會")
ALLOWED = ("摘要不送截圖", "截圖沒有送給摘要")


def old_wording(line: str) -> list:
    """一行文字裡的舊說法（先拿掉允許清單的句子）。"""
    for a in ALLOWED:
        line = line.replace(a, "")
    return [b for b in BANNED if b in line]


def text_files():
    for p in sorted(VD.rglob("*")):
        if p.is_file() and p.suffix.lower() in EXTS and "__pycache__" not in p.parts:
            yield p


@unittest.skipUnless(V22, "2.2.0 才有")
class PrivacyText(unittest.TestCase):
    def test_checker(self):
        self.assertEqual(old_wording("開啟後，逐字稿文字會送到 Anthropic（音檔與截圖不會）"), ["音檔與截圖不會", "截圖不會"])
        self.assertEqual(old_wording("只送逐字稿文字，沒有送截圖"), ["只送逐字稿文字，沒有送截圖", "沒有送截圖"])
        self.assertEqual(old_wording("（不含音檔與截圖）"), ["不含音檔與截圖"])
        self.assertEqual(old_wording("摘要不送截圖；截圖沒有送給摘要（校正時認出的與會者 4 位已參考）"), [])
        self.assertEqual(old_wording("只送逐字稿文字"), [])            # 沒有參考資料時的正確說法（§9.1）

    def test_no_old_wording(self):
        files = list(text_files())
        self.assertGreater(len(files), 40)
        hits = []
        for p in files:
            for i, line in enumerate(p.read_text(encoding="utf-8-sig", errors="replace").splitlines(), 1):
                for b in old_wording(line):
                    hits.append(f"{p.relative_to(VD).as_posix()}:{i}：{b}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_new_wording(self):
        def read(rel):
            return (VD / rel).read_text(encoding="utf-8-sig")
        skill = read("payload/skill/meeting-minutes-pro/SKILL.md")
        # 〔2.4.0〕「使用者選的供應商」改成「使用者選的 AI（GPT（OpenAI）或 Claude（Anthropic））」
        self.assertIn("做自動校正時，逐字稿文字、影片截圖（最多 8 張，縮小後）、背景說明與會議文件的名詞和相關段落會送到使用者選的"
                      + (" AI（GPT（OpenAI）或 Claude（Anthropic））" if _testenv.V24 else "供應商"), skill)
        self.assertIn("做會議摘要時送逐字稿文字、背景說明與文件的名詞和段落（摘要不送截圖）。音檔與文件原檔都不上傳", skill)
        self.assertIn("代表使用者已同意送出逐字稿與參考資料", skill)
        self.assertIn("**逐字稿模式（Claude App 沙盒）的參考資料（2.2）**", skill)               # §10
        readme = read("README.md")
        self.assertIn("**2.2.0 新功能：參考資料**", readme)
        self.assertIn("校正：逐字稿＋截圖＋參考資料<br/>摘要：逐字稿＋參考資料", readme)
        for rel in ("install.ps1", "install.sh"):
            s = read(rel)
            self.assertEqual(s.count("開啟後，逐字稿文字與影片截圖會送到"), 2, rel)
            self.assertEqual(s.count("要關掉截圖：config 的 reference.frames 改成 false"), 2, rel)
        for rel in ("payload/runtime/mm-sendto.ps1", "payload/runtime/mm-dropped.sh"):
            s = read(rel)
            self.assertNotIn("；逐字稿文字會送到", s, rel)                             # 依實際內容（§7.2）
            self.assertIn("截圖", s)
            self.assertIn("影片截圖已在 AI 校正時參考，認出的與會者在 reference.json", s)
        am = read("payload/runtime/scripts/auto_minutes.py")
        self.assertIn("截圖沒有送給摘要", am)
        self.assertIn("畫面內容沒有用來判斷步驟", am)
        self.assertIn("送出的內容由程式決定：逐字稿文字，以及（校正時）截圖與參考資料；範本不能指定送出的檔案",
                      read("payload/runtime/templates/README.md"))
        self.assertIn("送出的內容由程式決定：逐字稿文字，以及（校正時）截圖與參考資料；範本不能指定送出的檔案",
                      read("payload/skill/meeting-minutes-pro/references/custom-template-format.md"))
        self.assertIn("pypdf", read("THIRD-PARTY-NOTICES.md"))
        self.assertIn("Redistribution and use in source and binary forms", read("THIRD-PARTY-NOTICES.md"))


if __name__ == "__main__":
    unittest.main()
