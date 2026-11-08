"""〔2.2.0〕參考資料（refs.py；規格 2.2.0 §11.1、§11.3）的單元測試。不呼叫任何模型。

涵蓋：說明檔、一行描述、文件位置、抽取（DOCX／PPTX／PDF／TXT／MD 與讀不到的情況）、名詞與段落篩選、截圖挑選與縮圖、
講者對應、reference.json（寫入、摘要讀取、文件以重新收集為準）、上限、plan／show、collect() 不丟例外。
素材全部在測試裡產生（虛構）；有 spec/samples-v2.2.0 時另用它的合成素材驗證。PDF 的測試要有 pypdf，截圖的測試要有 ffmpeg，
沒有就略過。
"""
import builtins
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import _testenv

V22 = _testenv.VER >= (2, 2, 0)
if V22:
    import refs
try:
    import pypdf  # noqa: F401
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False
HAS_FFMPEG = shutil.which("ffmpeg") is not None
SAMPLES = _testenv.HERE.parent.parent / "spec" / "samples-v2.2.0" / "demo"
TZ = timezone(timedelta(hours=8))


# ---------------------------------------------------------------- 素材
def docx_bytes(body_xml: str) -> bytes:
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           + body_xml + "</w:body></w:document>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


DOCX_BODY = (
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>權限設計 RBAC</w:t></w:r></w:p>'
    '<w:p><w:r><w:t>登入改用 </w:t></w:r><w:r><w:rPr><w:b/></w:rPr><w:t>OAuth</w:t></w:r>'
    '<w:r><w:t> 搭配 JWT，稽核人員只能查詢下單紀錄。</w:t></w:r></w:p>'
    '<w:p><w:r><w:rPr><w:b w:val="0"/></w:rPr><w:t>不是粗體</w:t></w:r></w:p>'
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>營業員</w:t></w:r></w:p></w:tc>'
    '<w:tc><w:p><w:r><w:t>下單與查詢</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')

NS = ('xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"')


def _sp(text: str, ph: str | None = None) -> str:
    phx = f'<p:ph type="{ph}"/>' if ph else '<p:ph idx="1"/>'
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="1" name="s"/><p:cNvSpPr/><p:nvPr>{phx}</p:nvPr></p:nvSpPr>'
            f'<p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>')


def pptx_bytes(slides: list, notes: dict | None = None) -> bytes:
    """slides：[(標題, [內文…])]；notes：{頁碼: 備忘稿}。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        for i, (title, lines) in enumerate(slides, 1):
            sps = _sp(title, "title") + "".join(_sp(t) for t in lines)
            z.writestr(f"ppt/slides/slide{i}.xml", f"<p:sld {NS}><p:cSld><p:spTree>{sps}</p:spTree></p:cSld></p:sld>")
        for i, text in (notes or {}).items():
            sps = _sp(str(i), "sldNum") + _sp(text)
            z.writestr(f"ppt/notesSlides/notesSlide{i}.xml",
                       f"<p:notes {NS}><p:cSld><p:spTree>{sps}</p:spTree></p:cSld></p:notes>")
    return buf.getvalue()


def pdf_bytes(pages: list) -> bytes:
    """最小的文字 PDF（Helvetica、ASCII）；pages＝[[行…]…]，空的頁＝沒有文字層。"""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids, num = [], 4
    for lines in pages:
        content = "".join(f"BT /F1 12 Tf 72 {720 - 20 * i} Td ({t}) Tj ET\n" for i, t in enumerate(lines)).encode("latin-1")
        objs[num] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
                     b"/Contents %d 0 R >>" % (num + 1))
        objs[num + 1] = b"<< /Length %d >>\nstream\n" % len(content) + content + b"endstream"
        kids.append(num)
        num += 2
    objs[2] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    buf, offs = b"%PDF-1.4\n", {}
    for i in range(1, num):
        offs[i] = len(buf)
        buf += b"%d 0 obj\n" % i + objs[i] + b"\nendobj\n"
    xref = len(buf)
    buf += b"xref\n0 %d\n0000000000 65535 f \n" % num + b"".join(b"%010d 00000 n \n" % offs[i] for i in range(1, num))
    return buf + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (num, xref)


def encrypt_pdf(data: bytes, user: str, owner: str = "owner-pw") -> bytes:
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    w.encrypt(user_password=user, owner_password=owner, algorithm="RC4-128")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def ffimg(path: Path, w: int = 320, h: int = 180, box: int | None = None, cursor: bool = False, color: str = "gray"):
    """ffmpeg 產生合成截圖：灰底＋一條黑色直條（box＝x 座標）；cursor＝右下角多一個小白點（只差游標）。"""
    vf = []
    if box is not None:
        vf.append(f"drawbox=x={box}:y=0:w={w // 8}:h={h}:color=black:t=fill")
    if cursor:
        vf.append(f"drawbox=x={w - 30}:y={h - 30}:w=4:h=6:color=white:t=fill")
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}", "-frames:v", "1"]
    if vf:
        cmd += ["-vf", ",".join(vf)]
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd + [str(path)], check=True, capture_output=True, stdin=subprocess.DEVNULL)


class Tmp(unittest.TestCase):
    """暫存資料夾：<root>/會議/週會-1103.mp4 與輸出資料夾 <root>/會議/週會-1103_minutes。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="mmp-refs-test-"))
        self.folder = self.root / "會議"
        self.out = self.folder / "週會-1103_minutes"
        self.out.mkdir(parents=True)
        self.media = self.folder / "週會-1103.mp4"
        self.media.write_bytes(b"\x00")
        (self.out / "transcript.json").write_text(json.dumps({"meta": {"source": self.media.name}}), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, rel: str, data="x") -> Path:
        p = self.folder / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data, encoding="utf-8")
        return p


# ---------------------------------------------------------------- §2.1、§2.2
@unittest.skipUnless(V22, "2.2.0 才有")
class Context(Tmp):
    def test_md_preferred_over_txt_and_frontmatter_stripped(self):
        self.put("週會-1103.context.md", "---\nk: v\n---\n示範證券上線週會\n")
        self.put("週會-1103.context.txt", "不該讀到")
        items = refs.find_context(self.media, self.out)
        self.assertEqual([(i["file"], i["text"]) for i in items], [("週會-1103.context.md", "示範證券上線週會")])

    def test_txt_when_no_md_and_cp950(self):
        self.put("週會-1103.context.txt", "記事本存的說明".encode("cp950"))
        items = refs.find_context(self.media, self.out)
        self.assertEqual(items[0]["text"], "記事本存的說明")
        self.assertIsNone(items[0]["reason"])

    def test_decode_replaced(self):
        self.put("週會-1103.context.md", b"\xff\xfe\xfdabc\n")
        items = refs.find_context(self.media, self.out)
        self.assertEqual(items[0]["reason"], "decode_replaced")
        self.assertIn("abc", items[0]["text"])

    def test_empty_is_none_and_truncated(self):
        self.put("週會-1103.context.md", "---\na: b\n---\n   \n")
        self.assertEqual(refs.find_context(self.media, self.out), [])
        self.put("週會-1103.context.md", "字" * 2500)
        items = refs.find_context(self.media, self.out)
        self.assertEqual((items[0]["chars"], items[0]["reason"]), (2000, "truncated"))

    def test_merge_order_and_total_limit(self):
        self.put("週會-1103.context.md", "說明檔在前")
        refs.write_context(self.out, "入口的一行在後")
        items = refs.find_context(self.media, self.out)
        self.assertEqual([i["file"] for i in items], ["週會-1103.context.md", "context.md"])
        self.assertEqual(refs.context_text(items), "說明檔在前\n\n入口的一行在後")
        self.put("週會-1103.context.md", "甲" * 1995)
        self.assertEqual(len(refs.context_text(refs.find_context(self.media, self.out))), 2000)

    def test_other_meeting_context_not_read(self):
        self.put("週會-1110.context.md", "別場")
        self.assertEqual(refs.find_context(self.media, self.out), [])


@unittest.skipUnless(V22, "2.2.0 才有")
class WriteContext(Tmp):
    def test_write_first_line_and_frontmatter(self):
        now = datetime(2026, 11, 8, 8, 21, 41, tzinfo=TZ)
        p = refs.write_context(self.out, "  示範證券 v3 上線準備週會，陳怡君主持  \n第二行不要\r\n", now)
        self.assertEqual(p.read_text(encoding="utf-8"),
                         "---\nsource: entry\ncreated_at: 2026-11-08T08:21:41+08:00\n---\n示範證券 v3 上線準備週會，陳怡君主持\n")

    def test_limit_empty_and_backup(self):
        self.assertIsNone(refs.write_context(self.out, "   "))
        self.assertIsNone(refs.write_context(self.out, ""))
        self.assertFalse((self.out / "context.md").exists())
        now = datetime(2026, 11, 8, 9, 0, 0, tzinfo=TZ)
        refs.write_context(self.out, "長" * 400, now)
        self.assertEqual(refs.find_context(None, self.out)[0]["chars"], 300)
        refs.write_context(self.out, "第二次", now)
        refs.write_context(self.out, "第三次", now)
        self.assertEqual(refs.find_context(None, self.out)[0]["text"], "第三次")
        baks = sorted(p.name for p in self.out.glob("context.*.bak.md"))
        self.assertEqual(baks, ["context.20261108-090000-2.bak.md", "context.20261108-090000.bak.md"])


# ---------------------------------------------------------------- §2.3
@unittest.skipUnless(V22, "2.2.0 才有")
class FindDocs(Tmp):
    def names(self, *a, **kw):
        paths, skipped = refs.find_docs(self.media, self.out, *a, **kw)
        return [p.name for p in paths], skipped

    def test_rule1_separators(self):
        for n in ("週會-1103.簡報.pptx", "週會-1103_議程.docx", "週會-1103-紀錄.md", "週會-1103 附件.txt", "週會-11030.pdf",
                  "議程.docx", "週會-1103.context.md", "購物清單.txt", "週會-1103.wav"):
            self.put(n)
        names, skipped = self.names()
        self.assertEqual(sorted(names), sorted(["週會-1103.簡報.pptx", "週會-1103_議程.docx", "週會-1103-紀錄.md",
                                                "週會-1103 附件.txt"]))
        self.assertEqual(skipped, [])

    def test_rule2_single_media_only(self):
        self.put("refs/a.pdf")
        self.assertEqual(self.names()[0], ["a.pdf"])
        self.put("另一場.mp3", b"\x00")
        names, skipped = self.names()
        self.assertEqual(names, [])
        self.assertEqual(skipped, [{"file": "refs/", "reason": "shared_folder"}])

    def test_rule3_flag_dedup_and_skips(self):
        (self.out / "refs").mkdir()
        (self.out / "refs" / "b.docx").write_text("x", encoding="utf-8")
        (self.out / "refs" / "~$b.docx").write_text("x", encoding="utf-8")
        (self.out / "refs" / ".hidden.md").write_text("x", encoding="utf-8")
        (self.out / "refs" / "old.doc").write_text("x", encoding="utf-8")
        (self.out / "refs" / "表.xlsx").write_text("x", encoding="utf-8")
        (self.out / "refs" / "sub").mkdir()
        (self.out / "refs" / "sub" / "deep.md").write_text("x", encoding="utf-8")
        extra = self.put("外部/c.md")
        names, skipped = self.names([self.out / "refs" / "b.docx", extra, self.folder / "外部"])
        self.assertEqual(names, ["b.docx", "c.md"])                       # 同一檔只讀一次、子資料夾不遞迴
        self.assertEqual(sorted((s["file"], s["reason"]) for s in skipped),
                         [("old.doc", "unsupported"), ("表.xlsx", "unsupported")])

    def test_too_many_files(self):
        for i in range(12):
            self.put(f"refs/{i:02d}.md")
        names, skipped = self.names(max_files=10)
        self.assertEqual(names, [f"{i:02d}.md" for i in range(10)])
        self.assertEqual([(s["file"], s["reason"]) for s in skipped], [("10.md", "too_many_files"), ("11.md", "too_many_files")])

    def test_no_media_only_rule3(self):
        self.put("週會-1103.簡報.pptx")
        (self.out / "refs").mkdir()
        (self.out / "refs" / "x.md").write_text("x", encoding="utf-8")
        paths, _ = refs.find_docs(None, self.out)
        self.assertEqual([p.name for p in paths], ["x.md"])

    def test_media_from_transcript_meta(self):
        self.assertEqual(refs.media_path(self.out, {"source": "週會-1103.mp4"}), self.media.resolve())
        self.assertEqual(refs.media_path(self.out, {"source": "D:/別處/週會-1103.mp4"}).name, "週會-1103.mp4")
        self.assertIsNone(refs.media_path(self.out, {}))

    @unittest.skipUnless(SAMPLES.is_dir(), "沒有 spec/samples-v2.2.0")
    def test_samples_unrelated_file_not_picked(self):
        demo = self.root / "demo"
        shutil.copytree(SAMPLES, demo)
        paths, skipped = refs.find_docs(demo / "M1-demo.mp4", demo / "M1-demo_minutes")
        names = [p.name for p in paths]
        self.assertNotIn("購物清單.txt", names)
        self.assertEqual(sorted(names), sorted(["M1-demo.簡報.pptx", "權限設計.docx", "壓測報告.pdf", "掃描檔.pdf", "加密.pdf"]))


# ---------------------------------------------------------------- §5.1～§5.3
@unittest.skipUnless(V22, "2.2.0 才有")
class Extract(Tmp):
    def test_docx(self):
        r = refs.extract_doc(self.put("a.docx", docx_bytes(DOCX_BODY)))
        self.assertEqual(r["status"], "ok")
        kinds = [(b["kind"], b["text"]) for b in r["blocks"]]
        self.assertIn(("heading", "權限設計 RBAC"), kinds)
        self.assertIn(("strong", "OAuth"), kinds)
        self.assertNotIn(("strong", "不是粗體"), kinds)
        self.assertIn(("table", "營業員"), kinds)
        self.assertIn(("table", "下單與查詢"), kinds)
        self.assertNotIn(("body", "營業員"), kinds)                       # 表格裡的段落只算表格

    def test_pptx_title_body_note(self):
        data = pptx_bytes([("Redis Sentinel 切換", ["down-after-milliseconds 調成 5000"])], {1: "備忘：FreeSWITCH 錄音走 SIPREC"})
        r = refs.extract_doc(self.put("s.pptx", data))
        self.assertEqual([(b["kind"], b["text"]) for b in r["blocks"]],
                         [("heading", "Redis Sentinel 切換"), ("body", "down-after-milliseconds 調成 5000"),
                          ("note", "備忘：FreeSWITCH 錄音走 SIPREC")])         # 備忘稿的頁碼不算

    def test_txt_md(self):
        r = refs.extract_doc(self.put("n.md", "# 標題\n\n內文一行\n"))
        self.assertEqual([(b["kind"], b["text"]) for b in r["blocks"]], [("heading", "標題"), ("body", "內文一行")])
        r = refs.extract_doc(self.put("n.txt", "# 不是標題\n"))
        self.assertEqual(r["blocks"][0]["kind"], "body")

    def test_bad_zip_and_xml_too_large(self):
        self.assertEqual(refs.extract_doc(self.put("bad.docx", b"not a zip"))["reason"], "unreadable")
        self.assertEqual(refs.extract_doc(self.put("nodoc.docx", pptx_bytes([("t", [])])))["reason"], "unreadable")
        old = refs.ZIP_XML_MAX
        refs.ZIP_XML_MAX = 100
        try:
            self.assertEqual(refs.extract_doc(self.put("big.docx", docx_bytes(DOCX_BODY)))["reason"], "too_large")
        finally:
            refs.ZIP_XML_MAX = old

    def test_file_too_large_and_unsupported_and_missing(self):
        p = self.put("a.md", "x" * 2000)
        self.assertEqual(refs.extract_doc(p, max_bytes=1000)["reason"], "too_large")
        self.assertEqual(refs.extract_doc(self.put("a.xlsx"))["reason"], "unsupported")
        self.assertEqual(refs.extract_doc(self.folder / "nope.md")["reason"], "unreadable")

    def test_timeout(self):
        old = dict(refs.EXTRACTORS)
        refs.EXTRACTORS[".md"] = lambda p, n: time.sleep(2) or []
        try:
            t0 = time.time()
            self.assertEqual(refs.extract_doc(self.put("slow.md"), timeout=0.2)["reason"], "timeout")
            self.assertLess(time.time() - t0, 1.5)
        finally:
            refs.EXTRACTORS.clear()
            refs.EXTRACTORS.update(old)

    def test_char_limit(self):
        old = refs.DOC_MAX_CHARS
        refs.DOC_MAX_CHARS = 10
        try:
            r = refs.extract_doc(self.put("long.md", "一二三四五六\n七八九十甲乙丙\n"))
            self.assertEqual((r["chars"], r.get("truncated")), (10, True))
        finally:
            refs.DOC_MAX_CHARS = old

    def test_pdf_lib_missing(self):
        real = builtins.__import__

        def fake(name, *a, **kw):
            if name == "pypdf" or name.startswith("pypdf."):
                raise ImportError("no pypdf")
            return real(name, *a, **kw)
        saved = {k: v for k, v in sys.modules.items() if k == "pypdf" or k.startswith("pypdf.")}
        for k in saved:
            del sys.modules[k]
        builtins.__import__ = fake
        try:
            self.assertEqual(refs.extract_doc(self.put("a.pdf", b"%PDF-1.4"))["reason"], "pdf_lib_missing")
            self.assertEqual(refs.extract_doc(self.put("a.md", "其他格式照常"))["status"], "ok")
        finally:
            builtins.__import__ = real
            sys.modules.update(saved)

    @unittest.skipUnless(HAS_PYPDF, "沒有 pypdf")
    def test_pdf_text_scanned_encrypted(self):
        text = pdf_bytes([["Load Test Report", "Order API p99 120 ms"], ["FreeSWITCH SIPREC recording"]])
        r = refs.extract_doc(self.put("t.pdf", text))
        self.assertEqual(r["status"], "ok")
        self.assertEqual([b["text"] for b in r["blocks"]], ["Load Test Report", "Order API p99 120 ms",
                                                           "FreeSWITCH SIPREC recording"])
        self.assertEqual(refs.extract_doc(self.put("scan.pdf", pdf_bytes([[]])))["reason"], "no_text_layer")
        self.assertEqual(refs.extract_doc(self.put("enc.pdf", encrypt_pdf(text, "secret")))["reason"], "encrypted")
        r = refs.extract_doc(self.put("owner.pdf", encrypt_pdf(text, "")))          # 只有擁有者密碼：照常讀
        self.assertEqual(r["status"], "ok")
        self.assertIn("FreeSWITCH SIPREC recording", [b["text"] for b in r["blocks"]])
        self.assertEqual(refs.extract_doc(self.put("broken.pdf", b"%PDF-1.4\nbroken"))["status"], "skipped")

    @unittest.skipUnless(HAS_PYPDF, "沒有 pypdf")
    def test_pdf_page_limit(self):
        pages = [[f"Page{i:03d} text"] for i in range(1, 202)]
        r = refs.extract_doc(self.put("p.pdf", pdf_bytes(pages)), max_pages=200)
        texts = [b["text"] for b in r["blocks"]]
        self.assertIn("Page200 text", texts)
        self.assertNotIn("Page201 text", texts)                                     # §11.3：第 201 頁不讀


# ---------------------------------------------------------------- §5.4
@unittest.skipUnless(V22, "2.2.0 才有")
class Select(unittest.TestCase):
    def doc(self, *blocks, name="d"):
        return {"file": name, "blocks": [{"kind": k, "text": t} for k, t in blocks]}

    def test_terms_rules(self):
        d = self.doc(("heading", "Redis Sentinel 切換與 RBAC"), ("body", "the plan uses Kafka and down-after-milliseconds，"
                                                                  "另外「冪等設計」與 OK、ok 都不收；p99 收"),
                     ("table", "營業員"), ("strong", "稽核人員"), ("table", "很長很長的一格表格內容超過八個字"),
                     ("body", "lowercase words only"), ("strong", "JWT token"))
        terms = refs.select_terms([d], "常用寫法：Grafana、Prometheus")
        for t in ("Redis Sentinel", "RBAC", "Kafka", "down-after-milliseconds", "冪等設計", "營業員", "稽核人員", "p99",
                  "Grafana", "Prometheus"):
            self.assertIn(t, terms)
        for t in ("OK", "ok", "the", "plan", "lowercase", "很長很長的一格表格內容超過八個字"):
            self.assertNotIn(t, terms)
        self.assertLess(terms.index("Grafana"), terms.index("Kafka"))     # 說明檔 +3 排前面
        self.assertLess(terms.index("Redis Sentinel"), terms.index("Kafka"))   # 標題 +2
        self.assertEqual(refs.latin_terms("uses Kafka and Redis Sentinel, Order API v2"),
                         ["uses", "Kafka", "and", "Redis Sentinel", "Order API", "v2"])   # 小寫詞後面的大寫詞不併

    def test_terms_limit(self):
        d = self.doc(*[("heading", f"Term{i:04d}X") for i in range(400)])
        terms = refs.select_terms([d], "", 1500)
        self.assertLessEqual(len("、".join(terms)), 1500)
        self.assertGreater(len("、".join(terms)), 1490)
        self.assertEqual(refs.join_terms(["甲乙", "丙丁"], 4), "甲乙")

    def test_paragraphs(self):
        d = self.doc(("body", "Kafka 的消費延遲要在灰度發布前確認"), ("body", "與會議完全無關的古老章節內容"),
                     ("note", "Kafka 延遲確認"), ("body", "短"), ("heading", "Kafka 的消費延遲要在灰度發布前確認（標題不收）"))
        paras = refs.select_paragraphs([d], "今天確認 Kafka 的消費延遲，灰度發布前要確認")
        self.assertEqual([p["text"] for p in paras], ["Kafka 延遲確認", "Kafka 的消費延遲要在灰度發布前確認"])   # 分數高的在前
        self.assertGreaterEqual(min(p["score"] for p in paras), 0.15)

    def test_paragraph_limits(self):
        long = "Kafka 延遲確認" * 80
        d = self.doc(*[("body", f"{i:02d}" + long) for i in range(20)])
        paras = refs.select_paragraphs([d], "Kafka 延遲確認", 4000)
        self.assertTrue(all(len(p["text"]) <= 400 for p in paras))
        self.assertLessEqual(sum(len(p["text"]) for p in paras), 4000)
        self.assertEqual(len(paras), 10)


# ---------------------------------------------------------------- §3.2、§3.3
@unittest.skipUnless(V22 and HAS_FFMPEG, "2.2.0 才有；要有 ffmpeg")
class Frames(Tmp):
    def kf(self, specs):
        """specs：[(秒, 產生方式 kwargs 或 None＝不產生檔案)]。"""
        out = []
        for i, (sec, kw) in enumerate(specs, 1):
            rel = f"frames/frame_{i:04d}.jpg"
            if kw is not None:
                ffimg(self.out / rel, **kw)
            out.append({"time": float(sec), "file": rel})
        return out

    def test_blank_duplicate_missing(self):
        kf = self.kf([(1, {"box": 0}), (2, {"color": "black"}), (3, {"box": 120}), (4, {"box": 120, "cursor": True}),
                      (5, None), (6, {"box": 240})])
        kept, dropped = refs.select_frames(self.out, kf, 8)
        self.assertEqual([k["file"] for k in kept], ["frames/frame_0001.jpg", "frames/frame_0004.jpg", "frames/frame_0006.jpg"])
        self.assertEqual(dropped, {"blank": 1, "duplicate": 1, "missing": 1})   # 只差游標 → 留較晚的那張

    def test_over_limit_first_two_kept(self):
        kf = self.kf([(i, {"box": i * 26}) for i in range(10)])
        kept, dropped = refs.select_frames(self.out, kf, 8)
        times = [k["time"] for k in kept]
        self.assertEqual(len(kept), 8)
        self.assertEqual(times[:2], [0.0, 1.0])
        self.assertEqual(times, sorted(times))
        self.assertEqual(dropped, {"over_limit": 2})
        self.assertEqual(refs.select_frames(self.out, kf, 0), ([], {}))          # max_frames 0：不送

    def test_shrink_keeps_ratio(self):
        ffimg(self.out / "w.jpg", 1600, 900, box=100)
        ffimg(self.out / "t.jpg", 900, 1600, box=100)
        ffimg(self.out / "s.jpg", 320, 180, box=100)
        frames = [{"file": n, "time": float(i), "path": self.out / n} for i, n in enumerate(("w.jpg", "t.jpg", "s.jpg"))]
        frames.append({"file": "gone.jpg", "time": 9.0, "path": self.out / "gone.jpg"})
        with tempfile.TemporaryDirectory(prefix="mmp-refs-") as td:
            sent, dropped = refs.shrink_frames(frames, 1280, td)
            self.assertEqual([(s["w"], s["h"]) for s in sent], [(1280, 720), (720, 1280), (320, 180)])
            self.assertTrue(all(Path(s["path"]).parent == Path(td) for s in sent))
        self.assertEqual(dropped, {"shrink_failed": 1})
        self.assertFalse(Path(td).exists())
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), ["s.jpg", "t.jpg", "transcript.json", "w.jpg"])

    @unittest.skipUnless((SAMPLES / "M1-demo_minutes" / "frames").is_dir(), "沒有 spec/samples-v2.2.0")
    def test_samples_16x16_dhash_regression(self):
        """版面相同、文字不同的三張簡報全部留下（9×8 dHash 會判成重複）；只差游標的留較晚的；空白去掉。"""
        out = SAMPLES / "M1-demo_minutes"
        kf = json.loads((out / "transcript.json").read_text(encoding="utf-8"))["keyframes"]
        kept, dropped = refs.select_frames(out, kf, 8)
        self.assertEqual([Path(k["file"]).name for k in kept],
                         ["frame_0001_000001.jpg", "frame_0002_000003.jpg", "frame_0003_000022.jpg",
                          "frame_0005_000206.jpg", "frame_0006_000312.jpg"])
        self.assertEqual(dropped, {"duplicate": 1, "blank": 1})


# ---------------------------------------------------------------- §3.5
@unittest.skipUnless(V22, "2.2.0 才有")
class Speakers(unittest.TestCase):
    PARAS = [{"time": "00:00:00", "spk": "S1"}, {"time": "00:00:20", "spk": "S2"}, {"time": "00:03:04", "spk": "S3"},
             {"time": "00:05:00", "spk": "S?"}, {"time": "00:06:00", "spk": "S2"}]

    def fr(self, t, who):
        return {"time": t, "speaking": who, "file": "f.jpg"}

    def test_map_three_codes(self):
        sp, conf = refs.map_speakers([self.fr("00:00:03", "陳怡君"), self.fr("00:02:06", "林家豪"), self.fr("00:03:12", "王志明"),
                                      self.fr("00:06:30", "林家豪"), self.fr("00:00:05", "")], self.PARAS)
        self.assertEqual({k: v["name"] for k, v in sp.items()}, {"S1": "陳怡君", "S2": "林家豪", "S3": "王志明"})
        self.assertEqual(sp["S1"]["evidence"], "截圖 00:00:03 正在發言")
        self.assertEqual(sp["S2"]["evidence"], "截圖 00:02:06 正在發言")
        self.assertEqual(conf, [])

    def test_conflicts_not_adopted(self):
        sp, conf = refs.map_speakers([self.fr("00:00:03", "陳怡君"), self.fr("00:03:12", "陳怡君"),      # 一人兩代號
                                      self.fr("00:00:30", "林家豪"), self.fr("00:06:10", "張雅婷")], self.PARAS)  # 兩人一代號
        self.assertEqual(sp, {})
        self.assertIn({"name": "陳怡君", "speakers": ["S1", "S3"]}, conf)
        self.assertIn({"speaker": "S2", "names": ["張雅婷", "林家豪"]}, conf)

    def test_unknown_speaker_and_before_first(self):
        paras = [{"time": "00:00:10", "spk": "S1"}, {"time": "00:05:00", "spk": "S?"}]
        sp, conf = refs.map_speakers([self.fr("00:00:03", "甲"), self.fr("00:05:10", "乙"), self.fr("bad", "丙")], paras)
        self.assertEqual((sp, conf), ({}, []))

    def test_normalize_refs(self):
        sent = [{"file": "frames/frame_0002_000003.jpg", "time": 3.0}, {"file": "frames/frame_0006_000312.jpg", "time": 192.0}]
        st = {"meeting": {"title": " 週會 ", "date": "2026-11-03", "time": ""},
              "participants": [{"name": "陳怡君", "role": "專案經理"}, {"name": "陳怡君", "role": ""}, {"name": " ", "role": ""}],
              "frames": [{"time": "00:00:03", "kind": "participants", "speaking": "陳怡君", "terms": ["Grafana"]},
                         {"time": "00:00:22", "kind": "other", "speaking": "", "terms": []},          # 沒送的圖：丟掉
                         {"time": "0:03:12", "kind": "slide", "speaking": "王志明", "terms": []}],
              "terms": [{"term": "Grafana", "source": "frame"}, {"term": "grafana", "source": "doc"}]}
        r = refs.normalize_refs(st, sent)
        self.assertEqual(r["meeting"]["title"], "週會")
        self.assertEqual([p["name"] for p in r["participants"]], ["陳怡君"])
        self.assertEqual([(f["file"], f["time"]) for f in r["frames"]],
                         [("frame_0002_000003.jpg", "00:00:03"), ("frame_0006_000312.jpg", "00:03:12")])
        self.assertEqual(r["terms"], ["Grafana"])
        self.assertTrue(refs.valid_refs(st))
        self.assertFalse(refs.valid_refs({"meeting": {}, "participants": [], "frames": [], "terms": []}))
        self.assertFalse(refs.valid_refs({"meeting": {"title": "", "date": "", "time": ""}, "participants": [{"name": 1}],
                                          "frames": [], "terms": []}))


# ---------------------------------------------------------------- §2.5
@unittest.skipUnless(V22, "2.2.0 才有")
class Reference(Tmp):
    def col(self):
        self.put("週會-1103.context.md", "常用寫法：Grafana、Prometheus")
        self.put("週會-1103.筆記.md", "# Redis Sentinel\n\nKafka 延遲要在灰度發布前確認\n")
        self.put("refs/表.xlsx")
        return refs.collect(self.out, None, {}, frames=False, transcript_text="Kafka 延遲確認，灰度發布")

    def test_build_write_read(self):
        col = self.col()
        result = {"meeting": {"title": "週會", "date": "2026-11-03", "time": "14:00–14:30"},
                  "participants": [{"name": "陳怡君", "role": "專案經理"}, {"name": "張雅婷", "role": ""}],
                  "frames": [{"file": "f.jpg", "time": "00:00:03", "kind": "participants", "speaking": "陳怡君", "terms": []}],
                  "terms": ["示範證券"]}
        sp = {"S1": {"name": "陳怡君", "evidence": "截圖 00:00:03 正在發言"}}
        ref = refs.build_reference(col, result, {"provider": "claude", "stage": "correct.refs"}, sp, [{"speaker": "S2"}], 5,
                                   {"shrink_failed": 1}, 1280)
        refs.write_reference(self.out, ref)
        back = refs.read_reference(self.out)
        self.assertEqual(back, json.loads(json.dumps(ref, ensure_ascii=False)))
        self.assertEqual(back["version"], _testenv.VERSION)          # 〔2.3.0〕寫入的版本（原本寫死 2.2.0）
        self.assertEqual(back["sources"]["context"], [{"file": "週會-1103.context.md", "chars": 23}])
        self.assertEqual([(d["file"], d["status"]) for d in back["sources"]["docs"]],
                         [("週會-1103.筆記.md", "ok"), ("表.xlsx", "skipped")])
        self.assertEqual(back["sources"]["docs"][1]["reason"], "unsupported")
        self.assertEqual(back["sources"]["frames"], {"available": 0, "sent": 5, "dropped": {"shrink_failed": 1}, "max_px": 1280})
        self.assertEqual(back["participants"][0], {"name": "陳怡君", "role": "專案經理", "speaker": "S1", "source": "frame"})
        self.assertIsNone(back["participants"][1]["speaker"])
        self.assertIn("Redis Sentinel", back["doc_terms"])
        self.assertEqual(back["doc_paragraphs"][0]["doc"], "週會-1103.筆記.md")
        self.assertEqual(back["conflicts"], [{"speaker": "S2"}])
        self.assertFalse(list(self.out.glob("*.tmp")))

    def test_no_screenshots_reference(self):
        ref = refs.build_reference(self.col())
        self.assertIsNone(ref["by"])
        self.assertEqual((ref["participants"], ref["speakers"], ref["frames"]), ([], {}, []))
        self.assertEqual(ref["meeting"], {"title": "", "date": "", "time": ""})

    def test_for_minutes_docs_recollected(self):
        col = self.col()
        ref = refs.build_reference(col, {"meeting": {"title": "週會", "date": "2026-11-03", "time": ""},
                                         "participants": [{"name": "陳怡君", "role": ""}], "frames": [], "terms": ["示範證券"]},
                                   {"provider": "claude"}, {"S1": {"name": "陳怡君", "evidence": "e"}})
        refs.write_reference(self.out, ref)
        self.put("週會-1103.後來加的.md", "後來加的文件提到 FreeSWITCH 錄音\n")
        m = refs.for_minutes(self.out, None, {}, transcript_text="FreeSWITCH 錄音")
        self.assertEqual(m["source"], "reference.json")
        self.assertEqual(m["participants"][0]["name"], "陳怡君")              # 截圖整理結果照用
        self.assertEqual(m["terms"], ["示範證券"])
        self.assertIn("FreeSWITCH", m["doc_terms"])                         # 文件以重新收集的為準
        self.assertEqual(m["docs_read"], 2)
        self.assertEqual(m["context_text"], "常用寫法：Grafana、Prometheus")

    def test_for_minutes_without_reference_and_nothing(self):
        self.assertIsNone(refs.for_minutes(self.out, None, {}))
        self.put("週會-1103.context.md", "說明")
        m = refs.for_minutes(self.out, None, {})
        self.assertEqual((m["source"], m["participants"]), ("collected", []))

    def test_sections_and_header(self):
        ref = {"participants": [{"name": "陳怡君", "role": "專案經理", "speaker": "S1"}, {"name": "張雅婷", "role": "後端"}],
               "terms": ["示範證券", "Redis Sentinel"], "doc_terms": ["Redis Sentinel", "Kafka"]}
        s = refs.correct_sections(ref, "背景一句")
        self.assertEqual(s, "## 背景說明（使用者提供）\n背景一句\n\n## 與會者（參考資料：截圖）\n- 陳怡君（專案經理）＝S1\n"
                            "- 張雅婷（後端）\n\n## 參考資料用字（截圖、會議文件）\n示範證券、Redis Sentinel、Kafka")
        self.assertEqual(refs.correct_sections(None, ""), "")
        self.assertEqual(refs.header_line(5, 2, True),
                         "> 參考資料：截圖 5 張、會議文件 2 份、背景說明（人名與名詞寫法參考；內容以逐字稿為準）")
        self.assertIsNone(refs.header_line(0, 0, False))
        self.assertEqual(refs.send_note(0, 0, False), "逐字稿文字")
        self.assertEqual(refs.send_note(5, 2, False), "逐字稿文字、截圖 5 張、會議文件 2 份的名詞與段落")


# ---------------------------------------------------------------- collect、上限、設定、命令列
@unittest.skipUnless(V22, "2.2.0 才有")
class Collect(Tmp):
    def test_options_and_flags(self):
        o = refs.options({})
        self.assertEqual((o["frames"], o["docs"], o["context"], o["max_frames"], o["frame_px"]), (True, True, True, 8, 1280))
        self.assertFalse(refs.options({"reference": {"max_frames": 0}})["frames"])
        self.assertFalse(refs.options({"reference": {"frames": False}})["frames"])
        msgs = []
        self.assertTrue(refs.options({"reference": {"docs": "yes"}}, warn=msgs.append)["docs"])
        self.assertEqual(msgs, ["[!] reference.docs 的值 yes 不認得，改用 true"])
        self.assertFalse(refs.options({}, frames=False, docs=False, context=False)["docs"])

    def test_nothing_found(self):
        col = refs.collect(self.out, None, {})
        self.assertFalse(refs.found(col))
        self.assertEqual(col["frames_reason"], "no_keyframes")

    def test_internal_error_never_raises(self):
        self.put("週會-1103.context.md", "說明")
        old = refs.find_docs
        refs.find_docs = lambda *a, **k: 1 / 0
        try:
            col = refs.collect(self.out, None, {})
        finally:
            refs.find_docs = old
        self.assertEqual(col["errors"], ["internal_error:ZeroDivisionError"])
        self.assertEqual(col["context_text"], "說明")

    def test_flags_disable_sources(self):
        self.put("週會-1103.context.md", "說明")
        self.put("週會-1103.筆記.md", "Kafka")
        col = refs.collect(self.out, None, {}, docs=False, context=False)
        self.assertEqual((col["context"], col["docs"]), ([], []))
        col = refs.collect(self.out, None, {"reference": {"docs": False}})
        self.assertEqual(col["docs"], [])
        self.assertEqual(len(col["context"]), 1)

    def test_unreadable_summary(self):
        col = {"docs": [{"status": "skipped", "reason": "encrypted"}, {"status": "skipped", "reason": "no_text_layer"},
                        {"status": "skipped", "reason": "unsupported"}, {"status": "ok"}]}
        self.assertEqual(refs.unreadable_summary(col), "會議文件 2 份沒有讀到（加密 1、沒有文字層 1）")
        self.assertEqual(refs.unreadable_summary({"docs": [{"status": "ok"}]}), "")

    def test_plan_and_show_cli(self):
        self.put("週會-1103.context.md", "說明")
        self.put("週會-1103.筆記.md", "Kafka")
        self.put("refs/a.doc")
        (self.out / "frames").mkdir()
        for i in range(10):
            (self.out / "frames" / f"f{i}.jpg").write_bytes(b"x")
        (self.out / "transcript.json").write_text(json.dumps({"meta": {"source": self.media.name}, "keyframes": [
            {"time": float(i), "file": f"frames/f{i}.jpg"} for i in range(11)]}), encoding="utf-8")
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "refs.py"), "plan", str(self.out)],
                           capture_output=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 0, p.stderr.decode("utf-8", "replace"))
        plan = json.loads(p.stdout.decode("utf-8"))
        self.assertEqual((plan["frames"], plan["frames_available"], plan["docs"], plan["context"]),
                         (8, 10, 1, ["週會-1103.context.md"]))
        self.assertEqual(plan["docs_skipped"], {"unsupported": 1})
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "refs.py"), "show", str(self.out)],
                           capture_output=True, timeout=60, env=env)
        self.assertIn("沒有 reference.json", p.stdout.decode("utf-8"))
        refs.write_reference(self.out, refs.build_reference(refs.collect(self.out, None, {}, frames=False),
                                                            {"meeting": {"title": "", "date": "", "time": ""},
                                                             "participants": [{"name": "陳怡君", "role": ""}], "frames": [],
                                                             "terms": ["甲"]}, {"provider": "x"},
                                                            {"S1": {"name": "陳怡君", "evidence": "e"}}))
        self.assertIn("陳怡君＝S1", refs.show(self.out))
        self.assertIn("a.doc（unsupported）", refs.show(self.out))
        p = subprocess.run([sys.executable, "-B", str(_testenv.SCRIPTS / "refs.py"), "plan", str(self.root / "nope")],
                           capture_output=True, timeout=60, env=env)
        self.assertEqual(p.returncode, 2)

    @unittest.skipUnless(SAMPLES.is_dir() and HAS_PYPDF and HAS_FFMPEG, "要有 spec/samples-v2.2.0、pypdf、ffmpeg")
    def test_samples_collect(self):
        """規格附錄 A.2 的合成素材：說明檔 1、文件 3 份讀到（掃描檔、加密檔略過）、名詞含 Redis Sentinel／FreeSWITCH／SIPREC、截圖 7 → 5。"""
        demo = self.root / "demo"
        shutil.copytree(SAMPLES, demo)
        (demo / "M1-demo_minutes" / "reference.json").unlink(missing_ok=True)
        out = demo / "M1-demo_minutes"
        text = (out / "transcript.md").read_text(encoding="utf-8")
        col = refs.collect(out, None, {}, transcript_text=text)
        self.assertEqual([c["file"] for c in col["context"]], ["M1-demo.context.md"])
        self.assertEqual(refs.docs_read(col), 3)
        self.assertEqual(refs.docs_skipped(col), {"encrypted": 1, "no_text_layer": 1})
        for t in ("Redis Sentinel", "FreeSWITCH", "SIPREC"):
            self.assertIn(t, col["doc_terms"])
        self.assertGreater(len(col["doc_paragraphs"]), 5)
        self.assertEqual((len(col["frames"]), col["frames_available"]), (5, 7))
        self.assertEqual(refs.unreadable_summary(col), "會議文件 2 份沒有讀到（加密 1、沒有文字層 1）")


if __name__ == "__main__":
    unittest.main()
