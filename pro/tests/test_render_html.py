"""〔2.1.0〕網頁版（render_html.py；規格 meeting-minutes-pro-v2.1.0-spec.md §9.1 H-1～H-7、H-9、H-12）。

H-8（auto_minutes 整合）在 test_auto_minutes.py 的 Html、H-10（run_log）在 test_runlog.py 的 HtmlLog、H-11（upgrade_config）在
test_config.py 的 UpgradeTo210。外部請求 0 的檢查函式 assert_offline()（§9.3）由本檔每一份輸出共用（H-7）。
全部用合成資料與假的模型呼叫器，**不呼叫任何模型**。
"""
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import _testenv

V21 = _testenv.VER >= (2, 1, 0)
if V21:
    import render_html as rh

V202_SCRIPTS = _testenv.HERE.parent / "meeting-minutes-pro-v2.0.2" / "payload" / "runtime" / "scripts"
TC_MD = re.compile(r"(?<![\d:])(\d{1,2}):([0-5]\d):([0-5]\d)(?![\d:])")


# ---------------------------------------------------------------- §9.3 外部請求 0 的自動檢查（共用）
FORBIDDEN = ("<link", "<iframe", "<object", "<embed", "<img", "<base", "<form", "@import", "url(", "srcset=", "poster=")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def strip_code(page: str) -> str:
    """樣板的 <style>、<script> 內容不是標籤；只看其餘的部分。"""
    page = re.sub(r"<style>.*?</style>", "<style></style>", page, flags=re.S)
    return re.sub(r"<script>.*?</script>", "<script></script>", page, flags=re.S)


def tags(page: str) -> list:
    return re.findall(r"<([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?>", strip_code(page))


def attrs(attr_text: str) -> list:
    return re.findall(r'([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:="([^"]*)")?', attr_text or "")


def offline_problems(page: str) -> list:
    out = []
    low = page.lower()
    for f in FORBIDDEN:
        if f in low:
            out.append(f"含 {f}")
    if not re.search(r'<meta http-equiv="Content-Security-Policy" content="[^"]*default-src &#x27;none&#x27;', page):
        out.append("沒有含 default-src 'none' 的 CSP meta")
    for name, at in tags(page):
        for k, v in attrs(at):
            k = k.lower()
            if k in ("src", "href"):
                v2 = v.strip()
                if not (v2.startswith("#") or (not SCHEME.match(v2) and not v2.startswith("//"))):
                    out.append(f"{name} {k}={v}")
                if k == "src" and name.lower() not in ("audio", "video"):
                    out.append(f"src 不在 audio／video：{name}")
            if re.search(r"https?://", v or "", re.I):
                out.append(f"屬性含網址：{name} {k}")
    return out


def assert_offline(test: unittest.TestCase, page: str):
    test.assertEqual(offline_problems(page), [], "外部請求 0 檢查（§9.3）")


def toc_hrefs(page: str) -> list:
    m = re.search(r'<ul class="toc-list">(.*?)</ul>\s*</div>\s*</details>', page, re.S)
    return re.findall(r'href="#([^"]+)"', m.group(1)) if m else []


def ids(page: str) -> list:
    return re.findall(r'\sid="([^"]+)"', strip_code(page))


def body_of(page: str) -> str:
    """masthead 之後、頁尾之前（正文）。"""
    a = page.index('<div class="masthead">')
    b = page.index('<footer class="colophon">')
    return page[a:b]


def masthead(page: str) -> str:
    a = page.index('<div class="masthead">')
    m = re.search(r'</div>\n(<section|<details|<footer)', page[a:])
    return page[a:a + m.start()] if m else page[a:]


class Base(unittest.TestCase):
    def setUp(self):
        self._home = os.environ["MEETING_MINUTES_PRO_HOME"]
        self.home = Path(tempfile.mkdtemp(prefix="mmp-rh-home-"))
        os.environ["MEETING_MINUTES_PRO_HOME"] = str(self.home)
        self.tmp = Path(tempfile.mkdtemp(prefix="mmp-rh-"))
        os.environ.pop("MMP_RUN_ID", None)

    def tearDown(self):
        os.environ["MEETING_MINUTES_PRO_HOME"] = self._home
        shutil.rmtree(self.home, ignore_errors=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conv(self, md: str, name: str = "notes.md", **kw) -> tuple:
        """單獨一份 .md（--md 模式）→ (html, 結果)。每份輸出都過 §9.3 檢查（H-7）。"""
        p = self.tmp / name
        p.write_text(md, encoding="utf-8")
        r = rh.render(md_path=p, cfg={}, **kw)
        self.assertEqual(r["status"], "ok", r)
        page = p.with_suffix(".html").read_text(encoding="utf-8")
        assert_offline(self, page)
        return page, r

    def out_dir(self, name="demo_minutes", md="# 測試 會議記錄\n\n## 一、摘要\n\n內容 00:01:00\n", md_name="meeting-minutes.md",
                source="demo.wav", duration=600.0) -> Path:
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        (d / md_name).write_text(md, encoding="utf-8")
        meta = {"duration": duration}
        if source is not None:
            meta["source"] = source
        (d / "transcript.json").write_text(json.dumps({"meta": meta, "segments": []}, ensure_ascii=False), encoding="utf-8")
        return d

    def page_of(self, d: Path, name="meeting-minutes.html") -> str:
        page = (d / name).read_text(encoding="utf-8")
        assert_offline(self, page)
        return page


# ---------------------------------------------------------------- H-1
@unittest.skipUnless(V21, "2.1.0 才有")
class H1Types(Base):
    """7 種類型＋1 份 base: meeting 自訂範本：auto_minutes（假呼叫器）產生 .md 與 .html，比對目錄、錨點、時間碼、摘要卡；
    .md 與 2.0.2 逐位元相同（§9.4，有 2.0.2 目錄時）。"""

    TPL = "---\nname: 週會（研發處）\nbase: meeting\nlabels:\n  actions: 本週待辦\n  decisions: 本週決議\n---\n\n## 整理重點\n- 每個專案寫一個議題\n"

    def setUp(self):
        super().setUp()
        import auto_correct as ac
        import auto_minutes as am
        import test_auto_minutes as tam
        self.ac, self.am, self.tam = ac, am, tam
        self._callers = dict(ac.CALLERS)
        self._select = am.select_backend
        self._wait = ac.RETRY_WAIT
        ac.RETRY_WAIT = 0
        (self.home / "templates").mkdir()
        (self.home / "templates" / "weekly.md").write_text(self.TPL, encoding="utf-8")

    def tearDown(self):
        self.ac.CALLERS.clear()
        self.ac.CALLERS.update(self._callers)
        self.am.select_backend = self._select
        self.ac.RETRY_WAIT = self._wait
        super().tearDown()

    def prepare(self, d: Path):
        from test_auto_correct import write_out
        d.mkdir(parents=True)
        write_out(d, [(f"00:0{i}:00", f"S{i % 2 + 1}", self.tam.TEXTS[i % len(self.tam.TEXTS)]) for i in range(4)],
                  duration=600.0)
        self.tam.set_meta(d, speaker_stats=self.tam.STATS, diarization=self.tam.DIAR)

    def fake_script(self, code):
        return [self.tam.result()] if code == "meeting" else [self.tam.notes_result(code)]

    def run_case(self, code, template=None):
        d = self.tmp / f"{code}{'-' + template if template else ''}_minutes"
        self.prepare(d)
        ref = self.tmp / ("ref-" + d.name)
        shutil.copytree(d, ref)
        fake = self.tam.Fake(self.fake_script(code))
        self.ac.CALLERS[("claude", "cli")] = fake
        self.am.select_backend = lambda cfg, req, section=None: {
            "provider": "claude", "channel": "cli", "exe": "x", "cli_version": "fake 1.0", "auth": "subscription",
            "note": None, "model": "opus", "effort": "medium", "model_api": "opus"}
        res = self.am.run(d, {"provider": "claude", "channel": "cli", "model": None, "effort": None, "section": "minutes"},
                          cfg={}, content_type=None if template else code, template=template)
        self.assertIn(res["status"], ("ok", "partial"), res)
        self.assertEqual(res["html"]["status"], "ok", res["html"])
        return d, ref, res

    def check_page(self, md: str, page: str, meeting: bool):
        lines, in_code, heads, tc = md.split("\n"), False, 0, 0
        body_started = False
        for ln in lines:
            if ln.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue
            if ln.startswith("## ") or ln.startswith("### ") or ln.startswith("<details><summary>"):
                heads += 1
                body_started = True
            if body_started:
                tc += len(TC_MD.findall(ln))
        hrefs = toc_hrefs(page)
        all_ids = ids(page)
        self.assertEqual(len(hrefs), heads, "h2／h3（＋品質備註）數＝目錄項數")
        self.assertEqual(len(all_ids), len(set(all_ids)), "id 不重複")
        for h in hrefs:
            self.assertIn(h, all_ids, f"目錄 href #{h} 指得到 id")
        n_tc = len(re.findall(r'<time (?:class="tc-text" )?datetime="PT', body_of(page))) - \
            len(re.findall(r'<time (?:class="tc-text" )?datetime="PT', masthead(page)))
        self.assertEqual(n_tc, tc, "時間碼數＝.md 裡 HH:MM:SS 數（扣頭首）")
        cards = re.findall(r'<a class="count" href="#([^"]+)"><span class="count-n">(\d+)</span>'
                           r'<span class="count-l">([^<]+)</span>', page)
        if meeting:
            self.assertEqual([c[2] for c in cards], ["決議", "待辦", "待釐清問題"])
            for sid, n, label in cards:
                self.assertIn(sid, all_ids)
                sec = re.search(rf'<section id="{re.escape(sid)}">(.*?)</section>', page, re.S).group(1)
                rows = re.findall(r"<tbody>(.*?)</tbody>", sec, re.S)[0].count("<tr>")
                self.assertEqual(int(n), rows, label)
        else:
            self.assertEqual(cards, [])

    def same_as_202(self, d: Path, ref: Path, code: str, template=None):
        """§9.4：同一份輸入、同一個假呼叫器，2.0.2 寫出的 .md 與 2.1.0 逐位元相同。"""
        if not V202_SCRIPTS.is_dir():
            self.skipTest("沒有 meeting-minutes-pro-v2.0.2 目錄")
        script = (
            "import json, os, sys\n"
            "os.environ['MMP_TEST_VERSION'] = '2.0.2'\n"
            f"sys.path.insert(0, {str(_testenv.HERE)!r})\n"
            "import _testenv, test_auto_minutes as t, auto_correct as ac, auto_minutes as am\n"
            "a = json.loads(sys.argv[1])\n"
            "ac.RETRY_WAIT = 0\n"
            "code = a['code']\n"
            "ac.CALLERS[('claude', 'cli')] = t.Fake([t.result()] if code == 'meeting' else [t.notes_result(code)])\n"
            "am.select_backend = lambda cfg, req, section=None: {'provider': 'claude', 'channel': 'cli', 'exe': 'x', "
            "'cli_version': 'fake 1.0', 'auth': 'subscription', 'note': None, 'model': 'opus', 'effort': 'medium', "
            "'model_api': 'opus'}\n"
            "r = am.run(a['out'], {'provider': 'claude', 'channel': 'cli', 'model': None, 'effort': None, 'section': 'minutes'},"
            " cfg={}, content_type=None if a['tpl'] else code, template=a['tpl'])\n"
            "print(json.dumps({'status': r['status'], 'output': r['output']}))\n")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", MMP_TEST_VERSION="2.0.2")
        p = subprocess.run([sys.executable, "-B", "-c", script, json.dumps({"code": code, "out": str(ref), "tpl": template})],
                           capture_output=True, env=env, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace")[-2000:])
        out = json.loads(p.stdout.decode("utf-8").strip().splitlines()[-1])
        name = out["output"]
        want = (ref / name).read_bytes()
        if _testenv.VER >= (2, 2, 0):
            # 〔2.2.0〕規格 2.2.0 §9.1 刻意改寫的〈轉寫品質備註〉兩句（沒有參考資料時）；其餘仍須與 2.0.2 逐位元相同
            want = want.replace("；只送逐字稿文字，沒有送截圖".encode(), "；只送逐字稿文字".encode()).replace(
                "（只依時間對，先講後操作可能掛錯一步；畫面內容沒有送給模型）".encode(),
                "（掛圖只依時間對，先講後操作可能掛錯一步；畫面內容沒有用來判斷步驟）".encode())
        self.assertEqual(want, (d / name).read_bytes(), f"{name} 與 2.0.2 不同")
        self.assertFalse((ref / name).with_suffix(".html").exists())            # 2.0.2 沒有網頁版

    def test_all_types(self):
        import content_types as ct
        for code in ct.CODES:
            with self.subTest(code=code):
                d, ref, res = self.run_case(code)
                name = "meeting-minutes.md" if code == "meeting" else "notes.md"
                self.assertEqual(res["html"]["output"], Path(name).with_suffix(".html").name)
                page = self.page_of(d, Path(name).with_suffix(".html").name)
                self.check_page((d / name).read_text(encoding="utf-8"), page, code == "meeting")
                self.assertIn("meeting-minutes-pro · " + ("會議記錄" if code == "meeting" else "筆記"), page)
                self.same_as_202(d, ref, code)

    def test_custom_template_labels(self):
        d, ref, res = self.run_case("meeting", template="weekly")
        md = (d / "meeting-minutes.md").read_text(encoding="utf-8")
        self.assertIn("## 四、本週待辦", md)
        page = self.page_of(d)
        self.check_page(md, page, True)
        toc = re.search(r'<ul class="toc-list">(.*?)</ul>\s*</div>', page, re.S).group(1)
        self.assertIn('<span class="toc-label">本週待辦</span>', toc)
        self.assertIn('<span class="toc-label">本週決議</span>', toc)
        self.assertIn('href="#h-四-本週待辦"', page)                           # 摘要卡跟著表頭找，不看節名
        self.same_as_202(d, ref, "meeting", template="weekly")


# ---------------------------------------------------------------- H-2
@unittest.skipUnless(V21, "2.1.0 才有")
class H2Subset(Base):
    MD = "\n".join([
        "# 子集測試 會議記錄", "",
        "> 自動整理：測試，2026-11-08｜**未經人工確認**", "> ⚠ 這段未能自動整理", "",
        "| 項目 | 內容 |", "|---|---|", "| 日期時間 | 2026-11-08（長度 00:09:38） |", "| 與會者 | 甲、乙 |", "",
        "頁首的段落 00:01:00。", "",
        "## 一、會議摘要", "", "第一行", "第二行接在後面。", "",
        "## 二、議題討論", "",
        "### 2.1 議題甲　`[00:01:00]`", "",
        "- 背景：A", "  - 子項 `檔名.txt`", "* 星號項目", "1. 編號項目", "",
        "#### 小標", "", "##### 更小", "",
        "> 正文的引用", "",
        "| # | 決議 | 提出 | 時間碼 |", "|---|---|---|---|", "| D1 | 甲 | S1 | 00:02:00 |", "| D2 | 乙 |", "| D3 | a | b | 00:03:00 | 多的 |", "",
        "| 不是表格 | 沒有分隔列 |", "",
        "```mermaid", "graph TD; A-->B", "```", "",
        "```", "print('x')", "```", "",
        "[錨點](#h-一-會議摘要) [相對](notes.md) [外部](https://example.com/x) [信箱](mailto:a@b.c)", "",
        "*斜體* ![圖](x.png) <b>粗</b> **粗體**", "",
        "---", "",
        "# 第二個一級標題", "", "內容",
        "<details><summary>轉寫品質備註</summary>", "", "- 備註 `[00:04:00]` 某 → 某", ""])   # 故意沒有 </details>

    def test_rows(self):
        page, r = self.conv(self.MD, name="meeting-minutes.md")
        self.assertEqual(r["timecodes_out_of_range"], 0)
        self.assertIn("<title>子集測試 會議記錄</title>", page)
        self.assertIn("<h1>子集測試 會議記錄</h1>", page)
        mh = masthead(page)
        self.assertIn('<p class="status warn"><span class="badge">自動整理｜未經人工確認</span>', mh)
        self.assertIn('<p class="callout">⚠ 這段未能自動整理</p>', mh)
        self.assertIn("<dt>日期時間</dt><dd>2026-11-08（長度 00:09:38）</dd>", mh)     # 頁首時間不做成時間碼
        self.assertIn('<p class="prose">頁首的段落 00:01:00。</p>', mh)
        self.assertNotIn("<time", mh)
        self.assertIn('<p class="prose">第一行 第二行接在後面。</p>', page)
        self.assertIn('<section id="h-二-議題討論">', page)
        self.assertIn('<h3 id="h-2-1-議題甲">2.1 議題甲　<time class="tc-text" datetime="PT0H1M0S">00:01:00</time></h3>', page)
        self.assertIn('<ul><li>背景：A<ul><li>子項 <code>檔名.txt</code></li></ul></li><li>星號項目</li><li>編號項目</li></ul>',
                      page)
        self.assertIn("<h4>小標</h4>", page)
        self.assertIn("<h4>更小</h4>", page)
        self.assertNotIn('id="h-小標"', page)                                  # h4 不給 id、不進目錄
        self.assertIn('<div class="callout"><p>正文的引用</p></div>', page)
        self.assertIn('<th scope="row">D1</th>', page)
        self.assertIn('<th scope="col" class="num">時間碼</th>', page)
        self.assertIn('<td class="num"><time class="tc-text" datetime="PT0H2M0S">00:02:00</time></td>', page)
        self.assertIn('<tr><th scope="row">D2</th><td>乙</td><td></td><td class="num"></td></tr>', page)   # 欄數不足補空白
        self.assertNotIn("多的", page)                                             # 多的截掉
        self.assertIn('<p class="prose">| 不是表格 | 沒有分隔列 |</p>', page)
        self.assertIn('aria-label="Mermaid 圖的原始碼（網頁版離線顯示，不畫圖）"><code>graph TD; A--&gt;B</code></pre>', page)
        self.assertIn('aria-label="程式碼"><code>print(&#x27;x&#x27;)</code></pre>', page)
        self.assertIn('<a href="#h-一-會議摘要">錨點</a>', page)
        self.assertIn('<a href="notes.md">相對</a>', page)
        self.assertIn('外部（<span class="url">https://example.com/x</span>）', page)
        self.assertIn('信箱（<span class="url">mailto:a@b.c</span>）', page)
        self.assertIn("*斜體* ![圖](x.png) &lt;b&gt;粗&lt;/b&gt; <strong>粗體</strong>", page)        # 圖片不做成連結
        self.assertNotIn('href="x.png"', page)
        self.assertNotIn("<hr", page)
        self.assertIn('<section id="h-第二個一級標題"><header><h2><span>第二個一級標題</span></h2></header>', page)
        self.assertIn('<details class="quality" id="h-轉寫品質備註"><summary>轉寫品質備註</summary>', page)
        self.assertEqual(strip_code(page).count("<details"), strip_code(page).count("</details>"))   # 沒有 </details> → 文末自動關閉
        self.assertIn('<div class="quality-body">\n<div class="prose"><ul><li>備註 <time class="tc-text" datetime="PT0H4M0S">'
                      '00:04:00</time> 某 → 某</li></ul></div>\n</div></details>', page)
        toc = toc_hrefs(page)
        self.assertEqual(toc[-1], "h-轉寫品質備註")
        self.assertEqual(r["escaped_html"], 2)                                     # <b> 與 </b>
        self.assertIn('<span class="no" aria-hidden="true">·</span><span class="toc-label">轉寫品質備註</span>', page)
        self.assertIn('<span class="no">一</span><span class="toc-label">會議摘要</span>', page)

    def test_incomplete_never_raises(self):
        for md in ("", "沒有標題", "# 只有標題", "## 沒有一級標題\n| a |\n|---|", "```\n沒有結尾的程式碼",
                   "<details><summary>x</summary>\n## 在 details 裡的 h2", "| a | b |\n|---|---|", "- a\n    - b\n        - c",
                   "</details>\n## x", "> \n>\n", "\r\n# CRLF\r\n\r\n## 節\r\n內容\r\n", "\ufeff# BOM 開頭"):
            with self.subTest(md=md[:20]):
                page, r = self.conv(md)
                body = strip_code(page)
                self.assertEqual(body.count("<section"), body.count("</section>"))
                self.assertEqual(body.count("<details"), body.count("</details>"))


# ---------------------------------------------------------------- H-3
@unittest.skipUnless(V21, "2.1.0 才有")
class H3Injection(Base):
    MD = "\n".join([
        "# <script>alert(1)</script> {{CSP}}", "",
        "> 自動整理：<img src=x onerror=alert(2)>", "",
        "## <img src=x onerror=alert(2)>", "",
        '<iframe src="https://evil.example/"></iframe>', "",
        "{{BODY}} {{TOC}} {{PLAYER}}", "",
        "[壞連結](javascript:alert(3)) [外部](https://example.com/a) [協定相對](//evil.example/x) [反斜線](\\\\host\\x)", "",
        '| # | 項目 |', '|---|---|', '| 1 | " onmouseover="alert(4) |', "",
        "```mermaid", "</pre><script>alert(5)</script>", "```", "",
        "文字 <details><summary>寫在行中</summary> 不放行", "",
        "<details><summary>" + "長" * 81 + "</summary>", "",
        "<details><summary>有<b>標籤</summary>", "",
        "<details><summary>轉寫品質備註</summary>", "",
        "<svg onload=alert(6)>", "",
        "</details>", "",
        "## `<script>` 在 code 裡 **<b>粗</b>**", ""])

    def test_no_real_tags(self):
        page, r = self.conv(self.MD)
        self.assertEqual(page.count("<script"), 1, "只有樣板那一個 <script>")
        stripped = strip_code(page)
        self.assertFalse(re.search(r"<(img|iframe|svg|object|embed|form|base)\b", stripped, re.I))
        for name, at in tags(page):
            for k, v in attrs(at):
                self.assertFalse(re.fullmatch(r"on\w+", k, re.I), f"{name} 有事件屬性 {k}")
                if k == "href":
                    self.assertTrue(v.startswith("#") or not SCHEME.match(v), v)
                    self.assertFalse(v.startswith("//") or v.startswith("\\"), v)
                self.assertNotEqual(k, "src", "沒有媒體時不得有 src")
        self.assertIn("{{BODY}} {{TOC}} {{PLAYER}}", page)                       # 一次替換：照字面
        self.assertIn("{{CSP}}", page)
        self.assertIn("&lt;details&gt;&lt;summary&gt;寫在行中", page)
        self.assertIn("&lt;details&gt;&lt;summary&gt;" + "長" * 81, page)        # 超長 summary 不放行
        self.assertIn("&lt;details&gt;&lt;summary&gt;有&lt;b&gt;標籤", page)
        self.assertEqual(page.count('<details class="quality"'), 1)
        self.assertIn("&lt;/pre&gt;&lt;script&gt;alert(5)&lt;/script&gt;", page)
        self.assertIn("壞連結（<span class=\"url\">javascript:alert(3</span>）)", page)   # 網址含括號時截在第一個 )，仍是純文字
        self.assertIn("協定相對（<span class=\"url\">//evil.example/x</span>）", page)
        self.assertIn("&quot; onmouseover=&quot;alert(4)", page)
        self.assertGreater(r["escaped_html"], 5)


# ---------------------------------------------------------------- H-4
@unittest.skipUnless(V21, "2.1.0 才有")
class H4Anchors(unittest.TestCase):
    def test_spec_examples(self):
        c = rh.Ctx(None, None)
        self.assertEqual(c.slug("一、會議摘要"), "h-一-會議摘要")
        self.assertEqual(c.slug("2.1 壓測結果與資料庫調整　`[00:00:20]`"), "h-2-1-壓測結果與資料庫調整")
        self.assertEqual(c.slug("四、待辦事項（Action Items）"), "h-四-待辦事項-action-items")
        self.assertEqual(c.slug("2. 關鍵概念"), "h-2-關鍵概念")

    def test_duplicates_punct_long(self):
        c = rh.Ctx(None, None)
        self.assertEqual([c.slug("摘要"), c.slug("摘要"), c.slug("摘要")], ["h-摘要", "h-摘要-2", "h-摘要-3"])
        self.assertEqual(c.slug("（）「」！？"), "h-sec")
        self.assertEqual(c.slug("***"), "h-sec-2")
        long = "長" * 70
        self.assertEqual(c.slug(long), "h-" + "長" * 60)
        self.assertEqual(c.slug("**粗體** `程式`"), "h-粗體-程式")
        self.assertEqual(c.slug("ＡＢＣ　全形"), "h-abc-全形")                     # NFKC
        self.assertEqual(c.slug("摘要-2"), "h-摘要-2-2")                           # 已被「摘要」重複時用掉的 id 不再給

    def test_ids_in_page(self):
        b = Base("run")
        b.setUp()
        try:
            page, _ = b.conv("# T\n\n## 摘要\n\n### 摘要\n\n## 摘要\n")
            self.assertEqual(toc_hrefs(page), ["h-摘要", "h-摘要-2", "h-摘要-3"])
        finally:
            b.tearDown()


# ---------------------------------------------------------------- H-5
@unittest.skipUnless(V21, "2.1.0 才有")
class H5Timecodes(Base):
    def test_rules(self):
        md = "\n".join(["# T", "", "| 項目 | 內容 |", "|---|---|", "| 日期時間 | （長度 00:10:00） |", "",
                        "## 一、節", "",
                        "範圍內 00:09:59、邊界 00:11:00、超過 00:11:01、MM:SS 12:34、12:34:567、1:02:03、`[00:02:14]`、"
                        "`00:03:00`、`其他 00:04:00`、99:00:00", ""])
        d = self.out_dir(md=md, duration=600.0)
        r = rh.render(d, cfg={"html": {"media": "off"}})
        self.assertEqual(r["status"], "ok")
        page = self.page_of(d)
        body = body_of(page).split('<section id="h-一-節">', 1)[1]
        got = re.findall(r'<time class="tc-text" datetime="([^"]+)">([^<]+)</time>', body)
        self.assertEqual([g[1] for g in got], ["00:09:59", "00:11:00", "00:02:14", "00:03:00"])
        self.assertIn("超過 00:11:01", body)
        self.assertIn("1:02:03", body)                                            # 超過錄音長度＋60 秒：照原文
        self.assertIn("MM:SS 12:34、12:34:567", body)
        self.assertIn("<code>其他 00:04:00</code>", body)                         # 只有整段是時間碼的 code 才轉
        self.assertIn("99:00:00", body)
        self.assertEqual((r["timecodes"], r["timecodes_out_of_range"]), (4, 3))
        self.assertNotIn("[00:02:14]", body)
        self.assertIn("（長度 00:10:00）", masthead(page))                         # 頁首不轉
        self.assertNotIn("<time", masthead(page))

    def test_buttons_with_media(self):
        d = self.out_dir(md="# T 會議記錄\n\n## 一、節\n\n`[00:02:14]` 與 0:00:05\n")
        (d.parent / "demo.wav").write_bytes(b"RIFF")
        r = rh.render(d, cfg={})
        self.assertEqual((r["media"], r["media_ext"]), ("found", ".wav"))
        page = self.page_of(d)
        self.assertIn('<button type="button" class="tc" data-t="134" aria-label="從 00:02:14 播放">'
                      '<time datetime="PT0H2M14S">00:02:14</time></button>', page)
        self.assertIn('data-t="5" aria-label="從 00:00:05 播放"', page)

    def test_no_limit_without_duration(self):
        page, r = self.conv("# T\n\n## 節\n\n05:00:00 與 1:02:03\n")
        self.assertEqual((r["timecodes"], r["timecodes_out_of_range"]), (2, 0))
        self.assertIn('<time class="tc-text" datetime="PT1H2M3S">01:02:03</time>', page)   # 補成 HH:MM:SS


# ---------------------------------------------------------------- H-6
@unittest.skipUnless(V21, "2.1.0 才有")
class H6Media(Base):
    def media_of(self, page: str):
        m = re.search(r'<(audio|video) id="media" controls preload="metadata" playsinline src="([^"]*)">', page)
        return (m.group(1), m.group(2)) if m else None

    def test_order_1_2_3(self):
        d = self.out_dir(source="M1.wav")
        (d.parent / "M1.wav").write_bytes(b"x")                                   # ①
        (d / "M1.wav").write_bytes(b"x")                                          # ②
        (d.parent / "demo.mp3").write_bytes(b"x")                                 # ③
        r = rh.render(d, cfg={})
        self.assertEqual(r["media"], "found")
        self.assertEqual(self.media_of(self.page_of(d)), ("audio", "../M1.wav"))
        (d.parent / "M1.wav").unlink()
        rh.render(d, cfg={})
        self.assertEqual(self.media_of(self.page_of(d)), ("audio", "M1.wav"))
        (d / "M1.wav").unlink()
        rh.render(d, cfg={})
        self.assertEqual(self.media_of(self.page_of(d)), ("audio", "../demo.mp3"))

    def test_case_and_rule3_order(self):
        d = self.out_dir(source=None)
        (d.parent / "demo.MP4").write_bytes(b"x")
        (d.parent / "demo.WAV").write_bytes(b"x")
        r = rh.render(d, cfg={})
        self.assertEqual((r["media"], r["media_ext"]), ("found", ".wav"))         # §5.3 表的順序：錄音在影片之前
        self.assertEqual(self.media_of(self.page_of(d)), ("audio", "../demo.WAV"))

    def test_video(self):
        d = self.out_dir(source="demo.mp4")
        (d.parent / "demo.mp4").write_bytes(b"x")
        r = rh.render(d, cfg={})
        page = self.page_of(d)
        self.assertEqual(self.media_of(page), ("video", "../demo.mp4"))
        self.assertIn('<aside class="dock dock-video" id="dock" aria-label="原始影片">', page)
        for b in ("dock-play", "dock-full", "dock-fold"):
            self.assertIn(f'class="dock-btn {b}"', page)
        self.assertEqual(r["media_ext"], ".mp4")

    def test_explicit_off_config(self):
        d = self.out_dir()
        (d.parent / "demo.wav").write_bytes(b"x")
        other = self.tmp / "別處" / "錄音 檔.m4a"
        other.parent.mkdir()
        other.write_bytes(b"x")
        r = rh.render(d, cfg={}, media=str(other))
        self.assertEqual((r["media"], r["media_ext"]), ("explicit", ".m4a"))
        self.assertEqual(self.media_of(self.page_of(d)),
                         ("audio", "../%E5%88%A5%E8%99%95/%E9%8C%84%E9%9F%B3%20%E6%AA%94.m4a"))
        r = rh.render(d, cfg={}, media="off")
        self.assertEqual(r["media"], "off")
        page = self.page_of(d)
        self.assertIsNone(self.media_of(page))
        self.assertNotIn("<button type=\"button\" class=\"tc\"", page)
        r = rh.render(d, cfg={"html": {"media": "off"}})
        self.assertEqual(r["media"], "off")
        r = rh.render(d, cfg={"html": {"media": "yes"}})                          # 不認得 → auto
        self.assertEqual(r["media"], "found")

    def test_unsupported_and_mixed(self):
        d = self.out_dir(source="demo.wma")
        (d.parent / "demo.wma").write_bytes(b"x")
        r = rh.render(d, cfg={})
        self.assertEqual((r["media"], r["media_ext"]), ("unsupported", ".wma"))
        page = self.page_of(d)
        self.assertIsNone(self.media_of(page))
        self.assertIn("原始檔格式 .wma 瀏覽器多半不能播放，時間碼以文字顯示。", masthead(page))
        d2 = self.out_dir(name="mix_minutes", source="mix.mkv")
        (d2.parent / "mix.mkv").write_bytes(b"x")
        (d2.parent / "mix.mp4").write_bytes(b"x")
        r = rh.render(d2, cfg={})
        self.assertEqual((r["media"], r["media_ext"]), ("found", ".mp4"))         # 同時有能播與不能播 → 能播的

    def test_none_and_cjk_space_and_outdir_elsewhere(self):
        d = self.out_dir(name="週會 第3次_minutes", source="週會 第3次.m4a")
        r = rh.render(d, cfg={})
        self.assertEqual((r["media"], r["media_ext"]), ("none", None))
        (d.parent / "週會 第3次.m4a").write_bytes(b"x")
        r = rh.render(d, cfg={})
        self.assertEqual(self.media_of(self.page_of(d)), ("audio", "../%E9%80%B1%E6%9C%83%20%E7%AC%AC3%E6%AC%A1.m4a"))
        far = self.tmp / "out" / "elsewhere"                                       # transcribe.py --out-dir 到別處
        far.mkdir(parents=True)
        shutil.copy(d / "meeting-minutes.md", far / "meeting-minutes.md")
        shutil.copy(d / "transcript.json", far / "transcript.json")
        r = rh.render(far, cfg={})
        self.assertEqual(r["media"], "none")
        r = rh.render(far, cfg={}, media=str(d.parent / "週會 第3次.m4a"))
        self.assertEqual(self.media_of(self.page_of(far)), ("audio", "../../%E9%80%B1%E6%9C%83%20%E7%AC%AC3%E6%AC%A1.m4a"))

    def test_no_absolute_paths(self):
        d = self.out_dir()
        (d.parent / "demo.wav").write_bytes(b"x")
        rh.render(d, cfg={})
        page = self.page_of(d)
        for bad in (str(self.tmp), str(self.tmp).replace("\\", "/"), "file://", os.environ.get("USERNAME") or "\x00"):
            self.assertNotIn(bad, strip_code(page).replace("media-src &#x27;self&#x27; file:", ""))


# ---------------------------------------------------------------- H-9
@unittest.skipUnless(V21, "2.1.0 才有")
class H9Cli(Base):
    def cli(self, *args):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "render_html.py"), *map(str, args)],
                           capture_output=True, env=env, timeout=60)
        out = p.stdout.decode("utf-8").strip().splitlines()
        return p.returncode, json.loads(out[-1])["html"] if out else None, p.stderr.decode("utf-8", "replace")

    def test_exit_codes(self):
        d = self.out_dir()
        code, r, _ = self.cli(d)
        self.assertEqual((code, r["status"], r["output"]), (0, "ok", "meeting-minutes.html"))
        (d / "notes.md").write_text("# n\n\n## 節\n", encoding="utf-8")
        code, r, _ = self.cli(d, "--file", "notes.md", "--theme", "light")
        self.assertEqual((code, r["output"]), (0, "notes.html"))
        self.assertIn('data-theme="light"', (d / "notes.html").read_text(encoding="utf-8"))
        empty = self.tmp / "empty_minutes"
        empty.mkdir()
        self.assertEqual(self.cli(empty)[:2][0], 2)
        self.assertEqual(self.cli(empty)[1]["reason"], "no_md")
        self.assertEqual(self.cli(self.tmp / "nope")[0], 2)
        self.assertEqual(self.cli(d, "--file", "../x.md")[0], 2)
        self.assertEqual(self.cli(d, "--file", "missing.md")[0], 2)
        self.assertEqual(self.cli(d, "--media", self.tmp / "missing.wav")[0], 2)
        self.assertEqual(self.cli(d, "--media", "a.wav", "--no-media")[0], 2)       # 互斥
        self.assertEqual(self.cli(d, "--md", d / "meeting-minutes.md")[0], 2)      # 與 <out_dir> 互斥
        self.assertEqual(self.cli()[0], 2)
        self.assertEqual(self.cli(d, "--theme", "blue")[0], 2)

    def test_failure_exit_1(self):
        d = self.out_dir()
        (d / "meeting-minutes.html").mkdir()                                       # 目標是資料夾 → 寫檔失敗
        code, r, err = self.cli(d)
        self.assertEqual((code, r["status"], r["reason"]), (1, "failed", "write_failed"))
        self.assertIn("網頁版未產生（write_failed）", err)
        self.assertEqual([p.name for p in d.iterdir() if p.name.startswith(".~")], [])   # 沒有留下暫存檔

    def test_md_mode_no_log(self):
        d = self.tmp / "solo"
        d.mkdir()
        (d / "x.md").write_text("# 單獨一份\n\n## 節\n\n00:01:00\n", encoding="utf-8")
        code, r, _ = self.cli("--md", d / "x.md", "--out", d / "y.html")
        self.assertEqual((code, r["output"], r["media"]), (0, "y.html", "none"))
        self.assertFalse((d / "run_log.jsonl").exists())
        self.assertFalse((self.home / "logs").exists())
        code, r, _ = self.cli("--md", d / "x.md")
        self.assertEqual((code, r["output"]), (0, "x.html"))

    def test_out_dir_mode_logs(self):
        d = self.out_dir()
        self.cli(d)
        ev = [json.loads(x) for x in (d / "run_log.jsonl").read_text(encoding="utf-8").splitlines()]
        cp = [e for e in ev if e["event"] == "checkpoint"]
        self.assertEqual((cp[0]["name"], cp[0]["step"], cp[0]["status"]), ("html", "html", "ok"))
        runs = (self.home / "logs" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertIn("html", json.loads(runs[-1])["stages"])

    def test_render_never_raises(self):
        d = self.out_dir()
        orig = rh.build_page
        rh.build_page = lambda *a, **k: (_ for _ in ()).throw(KeyError("內容不應該出現"))
        try:
            r = rh.render(d, cfg={})
        finally:
            rh.build_page = orig
        self.assertEqual((r["status"], r["reason"], r["error"]), ("failed", "internal_error", "KeyError"))
        tpl = rh.TEMPLATE_NAME
        rh.TEMPLATE_NAME = "no-such-template.html"
        try:
            r = rh.render(d, cfg={})
        finally:
            rh.TEMPLATE_NAME = tpl
        self.assertEqual((r["status"], r["reason"]), ("failed", "template_missing"))
        r = rh.render(self.tmp / "nothing_minutes", cfg={})
        self.assertEqual((r["status"], r["reason"]), ("skipped", "no_md"))

    def test_no_model_modules(self):
        """規格 2.1.0 §2.3：render_html 不 import 任何會呼叫模型的模組（獨立行程裡匯入後檢查 sys.modules）。"""
        code = ("import sys; sys.path.insert(0, sys.argv[1]); import render_html; "
                "bad = [m for m in ('auto_minutes', 'auto_correct', 'content_types', 'templates', 'transcribe', 'backends', "
                "'diarize', 'subprocess') if m in sys.modules]; print(','.join(bad))")
        p = subprocess.run([sys.executable, "-B", "-c", code, str(_testenv.SCRIPTS)], capture_output=True, timeout=60,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(p.stdout.decode("utf-8").strip(), "")
        src = (_testenv.SCRIPTS / "render_html.py").read_text(encoding="utf-8")
        imports = set(re.findall(r"^\s*(?:import|from)\s+([a-zA-Z_][\w.]*)", src, re.M))
        self.assertLessEqual(imports, {"argparse", "base64", "hashlib", "html", "json", "os", "re", "sys", "tempfile",
                                       "time", "unicodedata", "datetime", "pathlib", "urllib.parse", "common", "runlog"})

    def test_sandbox_without_common(self):
        """Claude App 沙盒：只有 render_html.py 與樣板時照樣能跑（FALLBACK_VERSION）。"""
        sb = self.tmp / "sandbox"
        sb.mkdir()
        for n in ("render_html.py", "html_template.html"):
            shutil.copy(_testenv.SCRIPTS / n, sb / n)
        (sb / "m.md").write_text("# 會議 會議記錄\n\n## 一、摘要\n\n00:01:00\n", encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, "-B", "-I", str(sb / "render_html.py"), "--md", str(sb / "m.md")],
                           capture_output=True, env=env, timeout=60, cwd=str(sb))
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        page = (sb / "m.html").read_text(encoding="utf-8")
        self.assertIn(f"由 meeting-minutes-pro {rh.FALLBACK_VERSION} 從", page)
        self.assertEqual(rh.FALLBACK_VERSION, rh.VERSION)
        assert_offline(self, page)


# ---------------------------------------------------------------- H-12 與頁面骨架
@unittest.skipUnless(V21, "2.1.0 才有")
class H12Csp(Base):
    def test_hash_matches(self):
        page, _ = self.conv("# T\n\n## 節\n")
        csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page).group(1).replace("&#x27;", "'")
        style = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
        script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
        h = lambda s: base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()  # noqa: E731
        self.assertIn(f"style-src 'sha256-{h(style)}'", csp)
        self.assertIn(f"script-src 'sha256-{h(script)}'", csp)
        for part in ("default-src 'none'", "media-src 'self' file:", "img-src 'none'", "base-uri 'none'", "form-action 'none'"):
            self.assertIn(part, csp)
        self.assertEqual(page.count("<style>"), 1)
        self.assertEqual(page.count("<script>"), 1)

    def test_template_placeholders_and_skeleton(self):
        tpl = (_testenv.SCRIPTS / "html_template.html").read_text(encoding="utf-8")
        self.assertEqual(sorted(set(re.findall(r"\{\{([A-Z]+)\}\}", tpl))),
                         sorted(["CSP", "THEME", "TITLE", "TOC", "MASTHEAD", "BODY", "PLAYER", "FOOTER"]))
        self.assertTrue(tpl.startswith('<!doctype html>\n<html lang="zh-Hant-TW" data-theme="{{THEME}}">'))
        self.assertIn('<meta name="referrer" content="no-referrer">', tpl)
        self.assertIn("viewport-fit=cover", tpl)
        self.assertEqual(offline_problems(tpl.replace("{{CSP}}", "default-src &#x27;none&#x27;")), [])
        self.assertNotIn("@font-face", tpl)
        for k in ("--warn", "--warn-bg", "--ok", "--ok-bg", "--dock-h"):
            self.assertIn(k + ":", tpl)

    def test_footer_theme_and_write(self):
        page, _ = self.conv("# T\n\n## 節\n", name="meeting-minutes.md", theme="light")
        self.assertIn('data-theme="light"', page)
        self.assertRegex(page, "由 meeting-minutes-pro " + re.escape(_testenv.VERSION) + r" 從 <code>meeting-minutes\.md</code> 產生於 "
                               r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d。內容以 meeting-minutes\.md 為準；改過 \.md 之後請重新產生網頁版。")
        raw = (self.tmp / "meeting-minutes.html").read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)
        page, _ = self.conv("# T\n", theme=None)
        self.assertIn('data-theme="dark"', page)
        self.assertIn("meeting-minutes-pro · 筆記", page)


if __name__ == "__main__":
    unittest.main()
