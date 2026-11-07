"""OpenCC 詞彙回復表：規格 §4.6 K1～K6（K7 素材回歸在 eval_materials.py）。

執行：python -B -m unittest test_opencc_keep -v（在 tests/ 目錄，用 runtime 的 venv）
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _testenv  # noqa: F401  (sys.path、測試 home)
from opencc import OpenCC

import opencc_keep
from opencc_keep import KeepTable, load_table, parse_table, tw_phrase_keys

CC = OpenCC("s2twp")
T2S = OpenCC("t2s")


class K1FullDictionaryScan(unittest.TestCase):
    """TWPhrases 的每個鍵（繁體與 t2s 兩種寫法）：套用回復表後與純 s2twp 不同的，只能是回復表的保留寫法本身。"""

    def test_k1(self):
        keys = tw_phrase_keys()
        self.assertIsNotNone(keys, "找不到 OpenCC 的 TWPhrases.txt")
        table = load_table()
        allowed = set(table.src_map)   # 保留寫法、它的簡體寫法、表上第二欄列的其他來源寫法
        forms = []
        for p in keys:
            forms += [p, T2S.convert(p)]
        diff = []
        for f in forms:
            plain = CC.convert(f)
            kept, _ = table.convert(f, CC)
            if kept != plain:
                diff.append((f, plain, kept))
        bad = [d for d in diff if d[0] not in allowed]
        for f, plain, kept in diff:
            if f in allowed:   # 不同處的結果就是該來源寫法對應的保留寫法
                self.assertEqual(kept, table.src_map[f], f"{f}: {kept}")
        print(f"\n  K1：{len(keys)} 鍵、{len(forms)} 種寫法，與純 s2twp 不同 {len(diff)} 種；"
              f"其中回復表來源寫法以外 {len(bad)} 種")
        self.assertEqual(bad, [], "回復表誤傷了保留寫法以外的詞")
        self.assertGreater(len(diff), 0)


class K2toK4Sentences(unittest.TestCase):
    def setUp(self):
        self.table = load_table()

    def conv(self, s):
        return self.table.convert(s, CC)[0]

    def test_k2_protected(self):
        src = ("權限设定 權限管理 分區表 服務窗口 版本發布 发布会 账号 審核通過 參數設定 規格文件 待辦項目 "
               "我支持 建立實例 社區大學 作業程序 游標 錯誤代碼 服務對象 循環經濟")
        want = ("權限設定 權限管理 分區表 服務窗口 版本發布 發布會 帳號 審核通過 參數設定 規格文件 待辦項目 "
                "我支持 建立實例 社區大學 作業程序 游標 錯誤代碼 服務對象 循環經濟")
        self.assertEqual(self.conv(src), want)
        self.assertNotEqual(CC.convert(src), want)   # 純 s2twp 確實會改壞

    def test_k2_other_forms(self):
        self.assertEqual(self.conv("發佈 帐号 賬戶 账户 数据 用户 函数"), "發布 帳號 帳戶 帳戶 數據 用戶 函數")

    def test_k2_v110_entries(self):
        """〔1.1.0〕補「綁定」「腳本」；「登錄」移出內建表（Whisper 把「登入」寫成「登录」時不再被保護成「登錄」）。"""
        self.assertEqual(self.conv("每個帐号要绑定角色 帳號綁定 写一支脚本 那個腳本 脚本语言"),
                         "每個帳號要綁定角色 帳號綁定 寫一支腳本 那個腳本 腳本語言")
        self.assertEqual(CC.convert("绑定 脚本"), "繫結 指令碼")          # 純 s2twp 會改
        self.assertNotIn("登錄", self.table.keeps)
        self.assertEqual(self.conv("连续登录失败五次"), CC.convert("连续登录失败五次"))
        self.assertEqual(self.conv("连续登录失败五次"), "連續登入失敗五次")

    def test_k3_still_converted(self):
        src = "软件 内存 视频 服务器 默认 网络 数据库 程序员 源代码 用户名 文件夹"
        want = "軟體 記憶體 影片 伺服器 預設 網路 資料庫 程式設計師 原始碼 使用者名稱 資料夾"
        self.assertEqual(CC.convert(src), want)
        self.assertEqual(self.conv(src), want)

    def test_k4_taiwan_words_untouched(self):
        src = "視窗 视窗大小 釋出善意 透過這個方式 檔案 專案 支援 引數"
        self.assertEqual(self.conv(src), CC.convert(src))
        self.assertEqual(self.conv(src), "視窗 視窗大小 釋出善意 透過這個方式 檔案 專案 支援 引數")

    def test_hits_counted(self):
        out, hits = self.table.convert("權限和權限，发布", CC)
        self.assertEqual(out, "權限和權限，發布")
        self.assertEqual(hits, {"權限": 2, "發布": 1})

    def test_no_hit_identical_to_plain(self):
        s = "今天天气很好，我们去公园散步"
        self.assertEqual(self.table.convert(s, CC), (CC.convert(s), {}))


class K5UserTable(unittest.TestCase):
    def test_k5_disable_and_override(self):
        with tempfile.TemporaryDirectory() as td:
            user = Path(td) / "opencc_keep.tsv"
            user.write_text(opencc_keep.USER_TEMPLATE + "-數據\n支援	支持	使用者改：一律寫支援\n", encoding="utf-8")
            builtin = opencc_keep.opencc_keep_paths()[0]
            t = load_table(builtin, user)
            self.assertEqual(t.convert("數據", CC)[0], "資料")
            self.assertEqual(t.convert("我支持", CC)[0], "我支援")   # 使用者表覆蓋第二欄
            rows, disabled = parse_table(user)
            self.assertEqual(disabled, {"數據"})

    def test_conflict_user_wins(self):
        t = KeepTable([("甲乙", ["丙丁"], ""), ("戊己", ["丙丁"], "")], tw_phrase_keys())
        self.assertEqual(t.src_map["丙丁"], "甲乙")

    def test_missing_dictionary_still_protects(self):
        t = KeepTable([("權限", [], "")], None)
        self.assertEqual(t.convert("權限設定", CC)[0], "權限設定")


class K6Coexistence(unittest.TestCase):
    """回復表與 corrections.tsv、glossary protect 共存。"""

    def test_k6(self):
        import transcribe
        from corrections import Corrector
        table = load_table()
        glossary = ["平台組", "星河物流", "Kubernetes"]
        protect = {CC.convert(w): w for w in glossary if CC.convert(w) != w}
        protect.update(transcribe.TW_PREFER)
        self.assertIn("平臺組", protect)
        text, hits = transcribe.clean("平台组的酷伯内蒂斯系统权限设定，星河物流的数据库", CC, protect, table)
        self.assertEqual(text, "平台組的酷伯內蒂斯系統權限設定，星河物流的資料庫")
        self.assertEqual(hits, {"權限": 1})
        new, fixes = Corrector([("酷伯內蒂斯", "Kubernetes", "範例")]).apply(text)
        self.assertEqual(new, "平台組的Kubernetes系統權限設定，星河物流的資料庫")
        self.assertEqual(fixes, [["酷伯內蒂斯", "Kubernetes", 1]])

    def test_clean_without_keep_is_v100(self):
        import transcribe
        self.assertEqual(transcribe.clean("权限设定", CC, {}, None), ("許可權設定", {}))

    def test_corrections_add_requires_force(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        with tempfile.TemporaryDirectory() as home:
            env["MEETING_MINUTES_PRO_HOME"] = home
            script = str(_testenv.SCRIPTS / "corrections.py")
            p = subprocess.run([sys.executable, "-B", script, "add", "權限", "全線"], env=env,
                               capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(p.returncode, 0)
            self.assertIn("OpenCC 詞彙回復表", p.stderr)
            p = subprocess.run([sys.executable, "-B", script, "add", "權限", "全線", "--force"], env=env,
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 0, p.stderr)
            p = subprocess.run([sys.executable, "-B", script, "add", "密等", "冪等"], env=env,
                               capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(p.returncode, 0, p.stderr)


class CliSmoke(unittest.TestCase):
    def test_cli_test_and_list(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        script = str(_testenv.SCRIPTS / "opencc_keep.py")
        p = subprocess.run([sys.executable, "-B", script, "test", "審核通過後再發布"], env=env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("套用回復表：審核通過後再發布", p.stdout)
        self.assertIn("純 s2twp  ：審核透過後再發布", p.stdout)
        p = subprocess.run([sys.executable, "-B", script, "list"], env=env,
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("有效詞條 27 筆", p.stdout)        # 1.1.0：+綁定 +腳本 −登錄


if __name__ == "__main__":
    unittest.main()
