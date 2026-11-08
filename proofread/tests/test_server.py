"""伺服器整合測試（不開瀏覽器）：單一服務與交接、多份同時 5 情境、安全、暫存與接續、版本衝突、校正版被重新產生、
定稿與字幕、經驗整理與匯入／復原、名詞同步、重做會議記錄（Pro 2.2.0 停用；假的 Pro 2.3.0）、寫入回饋（試跑、結果、部分失敗、
寫檔錯誤）、操作紀錄、媒體、生命週期（閒置結束、--shutdown、版號不同、殘留）、長稿效能。
〔1.1.0〕本機限定（Pro 2.4.0 的機敏會議）：假的 Pro 2.2.0／2.3.0／2.4.0 各跑一次，標記檔與全域設定 → 重做停用並寫原因、
首頁與頁面的 local_only、其他功能（定稿）照常；沒有本機限定時重做是否可用只看 Pro 版號。

  python -B test_server.py          （或經由 run_tests.py）

全部在暫存區的副本與假 $MMH 上跑；權杖與密鑰只在測試記憶體裡，不寫進結果。
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import helpers as H  # noqa: E402

R = H.Results("整合")
SECRETS = []                 # 權杖、cookie、交接密鑰：最後確認都沒有進 server.log


def collect(urls):
    for u in urls:
        m = re.search(r"[?&]t=([^&]+)", u)
        if m:
            SECRETS.append(m.group(1))
    return urls


def wait_job(tab, did, limit=60):
    t0 = time.time()
    while time.time() - t0 < limit:
        _, j = tab.js("GET", f"/api/doc/{did}/job")
        if j and j.get("status") not in ("running",):
            return j
        time.sleep(0.3)
    return None


def bound_check(port):
    others = set()
    try:
        for fam, _, _, _, addr in socket.getaddrinfo(socket.gethostname(), None):
            if addr[0] not in ("127.0.0.1", "::1"):
                others.add((fam, addr[0]))
    except OSError:
        pass
    others.add((socket.AF_INET6, "::1"))
    refused = []
    for fam, ip in sorted(others, key=str):
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            s.connect((ip, port))
            refused.append(False)
        except OSError:
            refused.append(True)
        finally:
            s.close()
    win = ""
    if sys.platform == "win32":
        win = subprocess.run(["powershell", "-NoProfile", "-Command",
                              f"(Get-NetTCPConnection -LocalPort {port} | Where-Object {{ $_.RemotePort -eq 0 -and "
                              f"$_.OwningProcess -ne 0 }}).LocalAddress -join ','"],
                             capture_output=True).stdout.decode("mbcs", "replace").strip()
    return H.port_open(port), len(refused), all(refused), win


def main():
    started = time.time()
    work = H.workdir("mmproof-int-")
    D = H.materials.make_all(work / "demo")
    pristine = {k: {n: (v / n).read_text(encoding="utf-8") for n in ("transcript.md", "transcript.corrected.md")}
                for k, v in D.items()}
    home = H.make_home(work)
    env = H.base_env(home)
    L = lambda paths, **kw: H.launch(home, paths, **kw)  # noqa: E731
    perf = {}

    # ================================================================ 單一服務
    args = [sys.executable, "-B", str(H.LAUNCHER), "--home", str(home), "--no-browser", "--idle", "15", "--lease-ttl", "6"]
    p1 = subprocess.Popen(args + [str(D["D1"])], stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    p2 = subprocess.Popen(args + [str(D["D2"])], stdout=subprocess.PIPE, text=True, encoding="utf-8", env=env)
    o1, o2 = p1.communicate(90)[0], p2.communicate(90)[0]
    inst = H.instance(home)
    port, pid = inst["port"], inst["pid"]
    SECRETS.append(inst["secret"])
    R.rec("兩個啟動器同時啟動 → 只有一個服務", p1.returncode == 0 and p2.returncode == 0 and '"open"' in o1 and '"open"' in o2,
          f"exit {p1.returncode}/{p2.returncode}；服務 1 個")
    lo, n_other, all_refused, win = bound_check(port)
    R.rec("只綁 127.0.0.1", lo and all_refused and (win == "127.0.0.1" if sys.platform == "win32" else True),
          f"127.0.0.1 連得上；其他 {n_other} 個位址都連不上；監聽位址 {win or '（非 Windows）'}")

    outs = [L([D[k]]) for k in ("D1", "D2", "D3")]
    for o in outs:
        collect(o[1])
    A = H.Tab(port, "tabA")
    A.login(outs[0][1][0])
    st, docs = A.js("GET", "/api/docs")
    R.rec("多份同時-1 連續傳送 3 個資料夾", H.instance(home)["pid"] == pid and all(o[0][0]["status"] == "open" and len(o[1]) == 1 for o in outs)
          and len(docs["open"]) == 3, f"pid 相同、3 個分頁網址、首頁列 {len(docs['open'])} 份")
    res, urls, code, _ = L([D["D2"], D["D3"]])
    collect(urls)
    R.rec("多份同時-2 一次選 2 個資料夾", [r["status"] for r in res] == ["open", "open"] and len(urls) == 2 and H.instance(home)["pid"] == pid,
          "一個啟動器、2 個網址")
    d1, d2, d3 = outs[0][0][0]["id"], outs[1][0][0]["id"], outs[2][0][0]["id"]
    R.rec("稿 id 是 12 碼、同一資料夾同一個 id", all(re.fullmatch(r"[0-9a-f]{12}", x) for x in (d1, d2, d3)) and res[0]["id"] == d2, "")

    # ================================================================ 安全
    T = H.Tab(port, "tabT")
    st = T.login(outs[1][1][0].replace("t=", "t=x"))
    R.rec("錯的權杖 401", st == 401, f"HTTP {st}")
    _, u2, _, _ = L([D["D2"]])
    collect(u2)
    st1, st2 = T.login(u2[0]), H.Tab(port, "tabZ").login(u2[0])
    R.rec("權杖只能用一次", st1 == 303 and st2 == 401, f"第一次 {st1}、第二次 {st2}")
    sc = [c for c in T.jar]
    SECRETS.extend(c.value for c in sc)
    st_e, _, hdr_e = A.req("GET", "/api/docs", headers={"Host": f"evil.example:{port}"}, origin=False)
    st_n, _, _ = A.req("GET", "/api/docs", headers={"Host": f"127.0.0.1.nip.io:{port}"}, origin=False)
    st_l, _, _ = A.req("GET", "/api/docs", headers={"Host": f"localhost:{port}"}, origin=False)
    R.rec("錯的 Host 403（含 DNS rebinding 形式）", st_e == 403 and st_n == 403 and st_l == 200,
          f"evil.example {st_e}、127.0.0.1.nip.io {st_n}、localhost {st_l}")
    st_o, _ = A.js("POST", "/api/ping", {}, origin=False)
    st_f, _ = A.js("POST", "/api/ping", {}, headers={"Origin": "http://evil.example"})
    st_x, _ = A.js("POST", "/api/ping", {}, headers={"X-MMP": "0"})
    r = A.req("POST", "/api/ping", raw=b"{}", headers={"X-MMP": ""})
    st_ok, _ = A.js("POST", "/api/ping", {})
    R.rec("寫入類請求：缺 Origin、外站 Origin、缺 X-MMP 都 403", (st_o, st_f, st_x, r[0], st_ok) == (403, 403, 403, 403, 200),
          f"缺 Origin {st_o}、外站 {st_f}、X-MMP=0 {st_x}、空 X-MMP {r[0]}、正確 {st_ok}")
    anon = H.Tab(port, "anon")
    st_p, body_p, _ = anon.req("GET", f"/d/{d1}", origin=False)
    st_a, _ = anon.js("GET", "/api/docs", origin=False)
    st_w, _ = anon.js("POST", "/api/ping", {})
    R.rec("沒有 cookie：頁面 401、API 401、寫入 403", (st_p, st_a, st_w) == (401, 401, 403) and "請從右鍵或捷徑開啟" in body_p.decode("utf-8"),
          f"頁面 {st_p}、API {st_a}、寫入 {st_w}")

    def handoff(secret, origin=None):
        req = H.urllib.request.Request(f"http://127.0.0.1:{port}/api/handoff", method="POST", data=b'{"folders":[]}',
                                       headers={"X-MMP-Handoff": secret, "Content-Type": "application/json",
                                                **({"Origin": origin} if origin else {})})
        try:
            with H.urllib.request.urlopen(req, timeout=5) as rr:
                return rr.status
        except H.urllib.error.HTTPError as e:
            return e.code
    hw, ho = handoff("wrong"), handoff(inst["secret"], f"http://127.0.0.1:{port}")
    R.rec("交接 API：錯的密鑰、帶 Origin 都 403", hw == 403 and ho == 403, f"錯密鑰 {hw}、帶 Origin {ho}")
    bad = [A.req("GET", p, origin=False)[0] for p in ("/api/doc/../../etc/passwd", "/static/../mmproof_server.py",
                                                       "/api/doc/%2e%2e/data", "/static/%2e%2e/mmproof_server.py",
                                                       "/static/mmproof_server.py")]
    R.rec("路徑穿越被拒（4 種＋非固定靜態檔）", all(s == 404 for s in bad), f"HTTP {bad}")
    ids = [A.req("GET", p, origin=False)[0] for p in ("/api/doc/0123456789ab/data", f"/api/doc/{d1[:11]}/data",
                                                       f"/api/doc/{d1}0/data", f"/api/doc/{d1.upper()}/data")]
    R.rec("只收 12 碼小寫 id；未開啟的 id 404", all(s == 404 for s in ids), f"未開啟、11 碼、13 碼、大寫 → {ids}")
    big = H.raw_http(port, (f"POST /api/ping HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nOrigin: http://127.0.0.1:{port}\r\n"
                            f"X-MMP: 1\r\nCookie: mmp_s={[c.value for c in A.jar][0]}\r\nContent-Type: application/json\r\n"
                            "Content-Length: 25000000\r\n\r\n").encode())
    R.rec("超過 20 MB 的本文 413（不讀本文）", big.startswith(b"HTTP/1.1 413"), big.split(b"\r\n", 1)[0].decode())
    st_j, ej = A.js("POST", "/api/ping", raw=b"{not json")
    R.rec("JSON 解析失敗 400", st_j == 400, f"HTTP {st_j}")
    need = {"Content-Security-Policy": "default-src 'none'", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Cross-Origin-Resource-Policy": "same-origin", "Cache-Control": "no-store"}
    samples = [A.req("GET", "/", origin=False), A.req("GET", "/api/docs", origin=False), A.req("GET", "/static/app.js", origin=False),
               A.req("GET", "/nope", origin=False), anon.req("GET", "/", origin=False)]
    okh = all(all(v in (s[2].get(k) or "") for k, v in need.items()) and "Access-Control-Allow-Origin" not in s[2] for s in samples)
    R.rec("每個回應都帶安全標頭、沒有 CORS 標頭", okh, samples[0][2].get("Content-Security-Policy", ""))
    _, u3, _, _ = L([D["D3"]])
    collect(u3)
    path = u3[0].split(f":{port}", 1)[1].replace(f"next=/d/{d3}", "next=//evil.example/")
    st_n, _, hn = H.Tab(port, "tabN").req("GET", path, origin=False)
    ck = hn.get("Set-Cookie", "")
    R.rec("登入後只轉到站內、cookie 是 HttpOnly＋SameSite=Strict", st_n == 303 and hn.get("Location") == "/" and "HttpOnly" in ck
          and "SameSite=Strict" in ck, f"Location {hn.get('Location')}")
    SECRETS.append(ck.split("=", 1)[1].split(";")[0] if "=" in ck else "")

    # 過期權杖：另一個服務，登入連結 1 秒過期
    home_x = H.make_home(work, "home-ttl")
    rx, ux, _, _ = H.launch(home_x, [D["D3"]], extra=["--login-ttl", "1"])
    collect(ux)
    ix = H.instance(home_x)
    time.sleep(1.6)
    R.rec("過期的權杖 401", H.Tab(ix["port"], "t").login(ux[0]) == 401, "登入連結 1 秒後過期（測試設定）")
    H.stop(home_x)

    # ================================================================ 多分頁
    A2 = H.Tab(port, "tabA")
    _, ua, _, _ = L([D["D1"]])
    A2.login(collect(ua)[0])
    st, l = A2.lease(d1)
    res, urls3, _, _ = L([D["D1"]])
    collect(urls3)
    st, l2 = A2.lease(d1)
    R.rec("多份同時-3 同一份傳送兩次", l["holder"] and res[0]["status"] == "attach" and "attach=1" in urls3[0] and l2.get("attention") is True,
          "第二次回 attach（提示頁），原分頁下次心跳收到 attention")

    # ================================================================ 暫存
    st, data = A2.data(d1)
    dec, manual = H.d1_decisions(data)
    st, sv = A2.save(d1, data["session"]["rev"], dec, manual, history=[{"t": "d", "items": []}])
    R.rec("暫存（標記決定＋3 處人工修改）", st == 200 and sv["rev"] == data["session"]["rev"] + 1 and sv["progress"]["done"] == 17
          and sv["progress"]["total"] == 17, f"rev {sv.get('rev')}、已處理 {sv['progress']['done']}／{sv['progress']['total']}")
    st, e = A2.save(d1, sv["rev"], dec, [{"id": "x", "para": 0, "start": 0, "end": 30, "orig": "x", "value": "y"}])
    st2, e2 = A2.save(d1, sv["rev"], dict(dec, **{"m0-0": {"choice": "free", "value": "星{河"}}), manual)
    R.rec("人工修改跨到標記、自由輸入含標記符號都被拒 400", st == 400 and st2 == 400, f"{(e or {}).get('message')}；{(e2 or {}).get('message')}")
    st, sv2 = A2.save(d1, sv["rev"], dec, manual)                      # 不帶 history：保留伺服器上的
    hist = json.loads((D["D1"] / ".proofread" / "session.json").read_text(encoding="utf-8"))["history"]
    R.rec("離開分頁的 keepalive 暫存不帶歷史時保留原歷史", st == 200 and hist == [{"t": "d", "items": []}], "")
    rev_now = sv2["rev"]

    # ---- 多份同時-4：兩分頁同改一份
    B = H.Tab(port, "tabB")
    B.login(urls3[0])
    st, lb = B.lease(d1)
    st_a, sa = A2.save(d1, rev_now, dec, manual)
    st, lb2 = B.lease(d1, takeover=True)
    st_a2, _ = A2.save(d1, sa["rev"], dec, manual)
    st_b, sb = B.save(d1, lb2["rev"], dec, manual[:2])
    A2.lease(d1, takeover=True)
    st_a3, ea3 = A2.save(d1, sa["rev"], dec, manual)
    cur = json.loads((D["D1"] / ".proofread" / "session.json").read_text(encoding="utf-8"))
    R.rec("多份同時-4 兩分頁同改一份", lb["holder"] is False and st_a == 200 and lb2["holder"] and st_a2 == 423 and st_b == 200 and st_a3 == 409
          and len(cur["manual"]) == 2,
          f"B 只能看；B 接手後 A 存 → {st_a2}；B 存 → {st_b}；A 拿回但版本號過期 → {st_a3}「{(ea3 or {}).get('message', '')}」；檔案保留 B 的版本")
    st, cur2 = A2.data(d1)
    st, _ = A2.save(d1, cur2["session"]["rev"], dec, manual)

    # ---- .~*.tmp 清理、暫存檔損壞、格式較新
    pd = D["D1"] / ".proofread"
    old_t, new_t = pd / ".~session.json.1.1.tmp", pd / ".~session.json.2.2.tmp"
    old_t.write_text("x", encoding="utf-8")
    new_t.write_text("x", encoding="utf-8")
    os.utime(old_t, (time.time() - 7200, time.time() - 7200))
    A2.data(d1)
    R.rec("載入時刪除超過 1 小時的 .~*.tmp", not old_t.exists() and new_t.exists(), "")
    new_t.unlink()
    f_new = work / "fmt" / "D3-demo_minutes"
    shutil.copytree(D["D3"], f_new)
    (f_new / ".proofread").mkdir()
    (f_new / ".proofread" / "session.json").write_text(json.dumps({"format": "mm-proofread-session/2", "rev": 5, "marks": {}}),
                                                         encoding="utf-8")
    rf, uf_, _, _ = L([f_new])
    Fx = H.Tab(port, "tabF")
    Fx.login(collect(uf_)[0])
    fid = rf[0]["id"]
    _, fd_ = Fx.data(fid)
    Fx.lease(fid)
    st_fs, efs = Fx.save(fid, 5, {}, [])
    st_ff, _ = Fx.post(fid, "finalize", {"dry_run": True})
    R.rec("暫存格式主版號較新 → 唯讀、寫入被擋", fd_["readonly"] == "format_newer" and st_fs == 409 and efs["error"] == "format_newer" and st_ff == 409,
          f"save {st_fs}、finalize {st_ff}")
    f_bad = work / "broken" / "D3-demo_minutes"
    shutil.copytree(D["D3"], f_bad)
    (f_bad / ".proofread").mkdir()
    (f_bad / ".proofread" / "session.json").write_text("{壞掉的", encoding="utf-8")
    rb, ub, _, _ = L([f_bad])
    Fx.login(collect(ub)[0])
    _, bd = Fx.data(rb[0]["id"])
    R.rec("暫存檔讀不到 → 改名備份、從頭開始並提示", bd["notice"] and list((f_bad / ".proofread").glob("session.*.broken.json")), bd["notice"])

    # ================================================================ 經驗整理與匯入
    st, ex = A2.js("GET", f"/api/doc/{d1}/experience")
    c = {(x["wrong"], x["right"]): x for x in ex["corrections"]}
    ok = (c[("星荷", "星河")]["checked"] and c[("瑞迪斯", "Redis")]["checked"] and c[("退幣", "退避")]["checked"]
          and not c[("全線", "權限")]["checked"] and not c[("密等", "冪等")]["checked"] and not c[("謝謝觀看", "")]["checked"])
    R.rec("經驗整理：預設勾選＝Pro 固定錯誤條件＋min_count", ok and ex["min_count"] == 2,
          "；".join(f"{k[0]}→{k[1] or '（刪除）'}：{'勾' if v['checked'] else '不勾（' + '、'.join(v['why']) + '）'}" for k, v in c.items()))
    gl = {g["term"]: g["checked"] for g in ex["glossary"]}
    R.rec("詞表建議", gl.get("NotebookLM") is True and gl.get("Redis") is True and gl.get("冪等") is False, json.dumps(gl, ensure_ascii=False))
    before = (home / "corrections.tsv").read_bytes()
    gbefore = (home / "glossary.txt").read_bytes()
    pick = {"corrections": [{"wrong": "星荷", "right": "星河"}, {"wrong": "退幣", "right": "退避"}, {"wrong": "全線", "right": "權限"},
                            {"wrong": "不在建議裡", "right": "x"}], "glossary": ["NotebookLM"]}
    st, plan = A2.post(d1, "experience/import", dict(pick, dry_run=True))
    R.rec("匯入確認畫面（試跑：檔、筆數、備份位置；不寫檔）", st == 200 and [x["file"] for x in plan["plan"]] == ["$MMH/corrections.tsv", "$MMH/glossary.txt"]
          and plan["plan"][0]["rows"] == 3 and plan["plan"][0]["backup"].startswith("$MMH/backups/corrections.")
          and (home / "corrections.tsv").read_bytes() == before and not (home / "backups").exists(),
          "；".join(f"{x['file']} {x['rows']} 筆、備份 {x['backup']}" for x in plan["plan"]))
    st, im = A2.post(d1, "experience/import", pick)
    after = (home / "corrections.tsv").read_text(encoding="utf-8")
    bk = list((home / "backups").glob("corrections.*.tsv"))
    gk = list((home / "backups").glob("glossary.*.txt"))
    R.rec("匯入：先備份、只寫可匯入的、proofread: 備註、保留原註解", st == 200 and im["corrections"] == 3 and "星荷\t星河\tproofread:" in after
          and "不在建議裡" not in after and after.startswith(before.decode("utf-8")) and bk and bk[0].read_bytes() == before
          and gk and gk[0].read_bytes() == gbefore, f"對照表 {im.get('corrections')} 筆、詞表 {im.get('glossary')} 個；備份與匯入前相同")
    R.rec("匯入結果畫面（實際檔名、筆數、備份檔名）", [w["file"] for w in im["written"]] == ["$MMH/corrections.tsv", "$MMH/glossary.txt"]
          and all(w["backup"].startswith("$MMH/backups/") for w in im["written"]), json.dumps(im["written"], ensure_ascii=False))
    st, ex2 = A2.js("GET", f"/api/doc/{d1}/experience")
    c2 = {(x["wrong"], x["right"]): x for x in ex2["corrections"]}
    R.rec("匯入後同一筆「已在對照表」、不能勾", c2[("星荷", "星河")]["why"] == ["已在對照表"] and not c2[("星荷", "星河")]["importable"]
          and "NotebookLM" not in {g["term"] for g in ex2["glossary"]}, "")
    st, up = A2.post(d1, "experience/undo", {"dry_run": True})
    st2, un = A2.post(d1, "experience/undo")
    R.rec("復原上次匯入：確認畫面＋還原後逐位元相同", st == 200 and up["plan"] and st2 == 200 and (home / "corrections.tsv").read_bytes() == before
          and (home / "glossary.txt").read_bytes() == gbefore, json.dumps(up["plan"], ensure_ascii=False))
    A2.post(d1, "experience/import", {"corrections": [{"wrong": "星荷", "right": "星河"}]})
    with open(home / "corrections.tsv", "a", encoding="utf-8") as f:
        f.write("使用者\t之後加的\t\n")
    st, um = A2.post(d1, "experience/undo")
    R.rec("匯入後檔案又被改過 → 不能自動復原", st == 409 and "又被改過" in um["message"], um["message"])
    (home / "corrections.tsv").write_bytes(before)
    A2.js("GET", f"/api/doc/{d1}/data")
    sess = json.loads((D["D1"] / ".proofread" / "session.json").read_text(encoding="utf-8"))
    sess["imports"] = []
    (D["D1"] / ".proofread" / "session.json").write_text(json.dumps(sess, ensure_ascii=False), encoding="utf-8")
    (home / "glossary.txt").unlink()
    st, imn = A2.post(d1, "experience/import", {"glossary": ["NotebookLM"]})
    st2, _ = A2.post(d1, "experience/undo")
    R.rec("原本沒有的檔：不用備份、復原時刪除", st == 200 and imn["written"][0]["backup"] == "（原本沒有這個檔，不用備份）" and st2 == 200
          and not (home / "glossary.txt").exists(), imn["written"][0]["backup"])
    (home / "glossary.txt").write_bytes(gbefore)

    # ================================================================ 定稿、字幕、名詞同步
    st, fplan = A2.post(d1, "finalize", {"dry_run": True})
    R.rec("定稿確認畫面（試跑：要寫的檔與備份；不寫檔）", st == 200 and [x["file"] for x in fplan["plan"]] == ["transcript.final.md", "transcript.final.srt"]
          and not (D["D1"] / "transcript.final.md").exists(), f"{[(x['file'], x['backup']) for x in fplan['plan']]}；不改 {fplan['unchanged']}")
    st, fz = A2.post(d1, "finalize")
    final = (D["D1"] / "transcript.final.md").read_text(encoding="utf-8")
    srt = (D["D1"] / "transcript.final.srt").read_text(encoding="utf-8")
    R.rec("定稿：無標記、人工修改進定稿與字幕、結果列檔名與對時方式", st == 200 and not re.search(r"[{}]|\[\?", final.split("\n---\n", 1)[1])
          and "冪等" in final and "七月十三號" in final and "退避" in srt and "-->" in srt and not fz["failed"]
          and [w["file"] for w in fz["written"]] == ["transcript.final.md", "transcript.final.srt"] and fz["written"][1]["map_failed"] == 0,
          f"{[(w['file'], w['detail']) for w in fz['written']]}")
    st, fz2 = A2.post(d1, "finalize")
    R.rec("再次定稿：舊檔先備份並列在結果", st == 200 and all(w["backup"] and (D["D1"] / w["backup"]).exists() for w in fz2["written"]),
          f"{[(w['file'], w['backup']) for w in fz2['written']]}")
    R.rec("transcript.md／transcript.corrected.md 沒被改", all((D["D1"] / n).read_text(encoding="utf-8") == pristine["D1"][n]
                                                          for n in ("transcript.md", "transcript.corrected.md")), "")
    A2.lease(d3)
    st_p, ep = A2.post(d3, "finalize")
    R.rec("還有未處理時預設擋下定稿", st_p == 409 and ep["error"] == "pending" and not (D["D3"] / "transcript.final.md").exists(),
          f"HTTP {st_p}：{ep.get('message')}")
    A2.post(d3, "bye")
    # 名詞同步：先用 Pro 產生一次網頁版，確認同步後會重產
    pro_rh = subprocess.run([sys.executable, "-B", "-c", "import sys;sys.path.insert(0,sys.argv[1]);import render_html;"
                             "print(render_html.render(sys.argv[2],'meeting-minutes.md',cfg={})['status'])", str(H.PRO_SCRIPTS),
                             str(D["D1"])], capture_output=True, text=True, env=env)
    html_before = (D["D1"] / "meeting-minutes.html").read_text(encoding="utf-8")
    pv = {(x["wrong"], x["right"]): x["count"] for x in fz["sync_preview"]}
    m0 = (D["D1"] / "meeting-minutes.md").read_text(encoding="utf-8")
    st, splan = A2.post(d1, "sync", {"wrong": [w for w, _ in pv], "dry_run": True})
    R.rec("名詞同步確認畫面（試跑）", st == 200 and splan["plan"][0]["file"] == "meeting-minutes.md" and splan["plan"][0]["html"] == "meeting-minutes.html"
          and (D["D1"] / "meeting-minutes.md").read_text(encoding="utf-8") == m0, json.dumps(splan["plan"], ensure_ascii=False))
    st, sy = A2.post(d1, "sync", {"wrong": [w for w, _ in pv]})
    mins = (D["D1"] / "meeting-minutes.md").read_text(encoding="utf-8")
    html_after = (D["D1"] / "meeting-minutes.html").read_text(encoding="utf-8")
    R.rec("名詞同步（先備份、> 行與程式區塊不改、Pro render_html 重產網頁版）", pro_rh.stdout.strip() == "ok" and st == 200
          and "星荷物流倉儲" not in mins and "這一行提到星荷不會被改" in mins and "程式區塊裡的星荷不會被改" in mins
          and list(D["D1"].glob("meeting-minutes.*.bak.md")) and html_after != html_before and "星河物流倉儲" in html_after,
          f"預覽 {len(pv)} 組；結果 {[(w['file'], w.get('edits'), w.get('backup')) for w in sy['written']]}")

    # ---- 部分失敗：transcript.json 壞掉 → 定稿逐字稿寫入、字幕失敗 207
    f2 = work / "partial" / "D2-demo_minutes"
    shutil.copytree(D["D2"], f2)
    (f2 / "transcript.json").write_text("{壞掉", encoding="utf-8")
    rp, up_, _, _ = L([f2])
    P2 = H.Tab(port, "tabP")
    P2.login(collect(up_)[0])
    pid2 = rp[0]["id"]
    P2.lease(pid2)
    st, fp = P2.post(pid2, "finalize", {"allow_pending": True})
    R.rec("部分失敗 207：列出已寫入與失敗原因", st == 207 and [w["file"] for w in fp["written"]] == ["transcript.final.md"]
          and fp["failed"][0]["file"] == "transcript.final.srt" and "transcript.json" in fp["failed"][0]["reason"], json.dumps(fp["failed"], ensure_ascii=False))
    f4 = work / "nojson" / "D3-demo_minutes"
    shutil.copytree(D["D3"], f4)
    (f4 / "transcript.json").unlink()
    r4, u4, _, _ = L([f4])
    P2.login(collect(u4)[0])
    P2.lease(r4[0]["id"])
    st, n4 = P2.post(r4[0]["id"], "finalize", {"dry_run": True})
    R.rec("沒有 transcript.json：不產生字幕並說明原因", st == 200 and [x["file"] for x in n4["plan"]] == ["transcript.final.md"]
          and "沒有 transcript.json" in n4["srt_note"], n4["srt_note"])

    # ================================================================ 重做（Pro 2.2.x：停用）
    # 〔1.1.0〕repo 內的 Pro 是 2.3.0 以上時（公開 repo 只有最新版），停用的情境改在下面「本機限定」一節用假的 Pro 2.2.0 測
    st, rd = A2.post(d1, "redo", {"dry_run": True})
    _, dd = A2.data(d1)
    if H.locate.vtuple(H.PRO_VERSION) < (2, 3, 0):
        R.rec("重做：Pro 2.2.x 停用並說明原因", st == 409 and rd["error"] == "pro_too_old" and dd["redo"]["available"] is False
              and "2.3.0" in dd["redo"]["reason"], dd["redo"]["reason"])
    else:
        R.rec(f"重做：Pro {H.PRO_VERSION}（≥ 2.3.0）可用", dd["redo"]["available"] is True and dd["redo"]["reason"] is None
              and dd["local_only"] is None, json.dumps(dd["redo"], ensure_ascii=False))

    # ================================================================ 開啟資料夾、操作紀錄、媒體
    rv = [A2.post(d1, "reveal", {"target": t})[0] for t in ("folder", "mmh", "backups", "../outside", "C")]
    R.rec("「開啟資料夾」只開服務決定的位置", rv == [200, 200, 200, 404, 404], f"folder/mmh/backups/任意/其他 → {rv}")
    st, cur3 = A2.data(d1)
    A2.save(d1, cur3["session"]["rev"], dec, manual, manual_save=True)
    A2.save(d1, cur3["session"]["rev"] + 1, dec, manual, reason="離開分頁")
    st, lg = A2.js("GET", f"/api/doc/{d1}/log")
    acts = [x["action"] for x in lg["log"]]
    need_a = ["開始校稿", "儲存（手動）", "儲存（離開分頁）", "匯入對照表與詞表", "復原上次匯入", "定稿", "名詞同步到會議記錄"]
    dump = json.dumps(lg["log"], ensure_ascii=False)
    leak = any(w in dump for w in ("冪等", "退避", "星河物流倉儲", "七月十三號", "NotebookLM"))
    R.rec("操作紀錄（時間、動作、檔名；不記內容）", all(n in acts for n in need_a) and not leak and all(set(x) <= {"at", "action", "files", "note"} for x in lg["log"]),
          "、".join(dict.fromkeys(acts)))
    st, media_full, mh = A2.req("GET", f"/api/doc/{d1}/media", origin=False)
    st_r, media_part, mhr = A2.req("GET", f"/api/doc/{d1}/media", origin=False, headers={"Range": "bytes=100-199"})
    st_h, hb, _ = A2.req("HEAD", f"/api/doc/{d1}/media", origin=False)
    _, d2data = A2.data(d2)
    wav = work / "demo" / "D1-demo.wav"
    R.rec("媒體：Range 206、整檔 200、HEAD 沒有本文；沒有媒體的稿 null", st == 200 and len(media_full) == wav.stat().st_size
          and st_r == 206 and media_part == wav.read_bytes()[100:200] and mhr.get("Content-Range") == f"bytes 100-199/{wav.stat().st_size}"
          and st_h == 200 and hb == b"" and d2data["media"] is None and mh.get("Content-Type") == "audio/wav", "")
    (work / "demo" / "D3-demo.wma").write_bytes(b"x")
    _, d3data = A2.data(d3)
    R.rec("瀏覽器不能播的格式：顯示說明", d3data["media"] == {"status": "unsupported", "ext": ".wma"}, json.dumps(d3data["media"]))

    # ================================================================ 校正版被重新產生
    cor = D["D1"] / "transcript.corrected.md"
    cor.write_text(cor.read_text(encoding="utf-8").replace("{瑞迪斯→Redis}的快取", "{瑞迪斯→Redis}的快取（重跑）"), encoding="utf-8")
    st, dd = A2.data(d1)
    blocked = {op: A2.post(d1, op, body)[0] for op, body in (("finalize", {"dry_run": True}), ("sync", {"wrong": ["星荷"]}),
                                                               ("experience/import", {"glossary": ["X"]}), ("experience/undo", {}),
                                                               ("redo", {"dry_run": True}))}
    st_s, es = A2.save(d1, dd["session"]["rev"], {}, [])
    st_r, rr = A2.post(d1, "restart", {"carry": True})
    R.rec("校正版被重新產生：偵測、所有寫入被擋、帶入對得上的決定", dd["changed"] is not None and st_s == 409 and es["error"] == "source_changed"
          and all(v == 409 for v in blocked.values()) and st_r == 200 and rr["carried"]["marks"] == rr["carried"]["marks_total"] == 14
          and rr["carried"]["manual"] == rr["carried"]["manual_total"] == 3, f"擋下 {blocked}；帶入 {rr.get('carried')}")
    acts2 = [x["action"] for x in A2.js("GET", f"/api/doc/{d1}/log")[1]["log"]]
    R.rec("用新版重新開始記進紀錄並保留舊紀錄", "用新版重新開始（帶入決定）" in acts2 and "定稿" in acts2
          and list((D["D1"] / ".proofread").glob("session.*.bak.json")), "")

    # ================================================================ 路徑換算、一次超過 10 份
    rm, um_, _, _ = L([work / "demo" / "D1-demo.wav", D["D2"] / "transcript.md", D["D3"] / "會議記錄校稿.mmproof", D["D2"]])
    collect(um_)
    R.rec("路徑換算：錄音檔 → <檔名>_minutes、資料夾裡的檔 → 資料夾、.mmproof → 資料夾、重複只開一次",
          [x["id"] for x in rm] == [d1, d2, d3] and (D["D3"] / "會議記錄校稿.mmproof").read_text(encoding="utf-8") == "meeting-minutes-proofread 1\n",
          f"{[x['status'] for x in rm]}")
    ri, ui, code_i, err_i = L([work / "not-a-folder", work])
    collect(ui)
    R.rec("不是輸出資料夾：列出來、開首頁", [x["status"] for x in ri] == ["invalid", "invalid", "home"] and len(ui) == 1 and "/login?" in ui[0]
          and "next=/" in ui[0] and "不是會議的輸出資料夾" in err_i, err_i.strip().splitlines()[0])
    many = []
    for i in range(11):
        f = work / "many" / f"M{i:02d}_minutes"
        shutil.copytree(D["D3"], f)
        many.append(f)
    rmn, umn, _, _ = L(many)
    collect(umn)
    st, docs = A2.js("GET", "/api/docs")
    R.rec("一次超過 10 份只開首頁、全部列在開著的稿", [x["status"] for x in rmn].count("listed") == 11 and rmn[-1]["status"] == "home"
          and len(umn) == 1 and sum(1 for o in docs["open"] if o["name"].startswith("M")) == 11, f"網址 {len(umn)} 個")

    # ================================================================ 長稿效能（伺服器端）
    long_dir = H.materials.make_long(work / "long")
    rl, ul, _, _ = L([long_dir])
    Lt = H.Tab(port, "tabL")
    Lt.login(collect(ul)[0])
    lid = rl[0]["id"]
    t0 = time.perf_counter()
    st, ld = Lt.data(lid)
    perf["long_data_ms"] = round((time.perf_counter() - t0) * 1000)
    lm = H.marks_of(ld)
    Lt.lease(lid)
    ldec = {k: {"choice": "suggest"} for k in lm}
    body = json.dumps({"tab": "tabL", "base_rev": ld["session"]["rev"], "marks": ldec, "manual": [], "history": []})
    t0 = time.perf_counter()
    st_ls, _ = Lt.js("PUT", f"/api/doc/{lid}/session", raw=body.encode())
    perf["long_save_ms"] = round((time.perf_counter() - t0) * 1000)
    perf["long_save_kb"] = round(len(body.encode()) / 1024)
    t0 = time.perf_counter()
    st_lf, lf = Lt.post(lid, "finalize")
    perf["long_finalize_ms"] = round((time.perf_counter() - t0) * 1000)
    paras = sum(1 for b in ld["doc"]["body"] if b["t"] == "para")
    R.rec("長稿（3 小時）：載入、暫存、定稿", st == 200 and st_ls == 200 and st_lf == 200 and paras == 900 and len(lm) >= 1000
          and lf["written"][1]["map_failed"] == 0,
          f"{paras} 段、{len(lm)} 處標記；data {perf['long_data_ms']} ms、暫存 {perf['long_save_ms']} ms（{perf['long_save_kb']} KB）、"
          f"定稿＋字幕 {perf['long_finalize_ms']} ms")

    # ================================================================ 多份同時-5：全部關閉 → 閒置結束 → 接續
    for tab, did in ((A2, d1), (B, d1), (Fx, fid), (P2, pid2), (Lt, lid)):
        tab.post(did, "bye")
    for did in list({d1, d2, d3}):
        A2.post(did, "bye")
    waited = H.wait_exit(home, port, 60)
    R.rec("多份同時-5 全部關閉後閒置結束、instance.json 刪除", waited is not None and not H.pid_alive(pid),
          f"最後一個請求後約 {waited:.1f} 秒結束（測試設定閒置 15 秒）" if waited else "沒有結束")
    res5, urls5, _, _ = L([D["D1"]])
    inst2 = H.instance(home)
    SECRETS.append(inst2["secret"])
    C = H.Tab(inst2["port"], "tabC")
    C.login(collect(urls5)[0])
    st, d5 = C.data(d1)
    R.rec("關閉再開 → 接續（決定、人工修改都在）", st == 200 and len(d5["session"]["marks"]) == 14 and len(d5["session"]["manual"]) == 3
          and inst2["pid"] != pid, f"新服務；決定 {len(d5['session']['marks'])}、人工修改 {len(d5['session']['manual'])}")
    st, docs = C.js("GET", "/api/docs")
    r1 = next(r for r in docs["recent"] if r["id"] == d1)
    R.rec("首頁：最近的稿（上次儲存、已處理、不回傳路徑、最多 20 份）", st == 200 and all("dir" not in r for r in docs["recent"])
          and r1["saved_at"] and r1["progress"]["total"] and len(docs["recent"]) <= 20 and docs["idle_seconds"] == 15,
          f"最近 {len(docs['recent'])} 份；D1 上次儲存 {r1['saved_at'][11:16]}、已處理 {r1['progress']['done']}／{r1['progress']['total']}")
    st_ro, ro = C.js("POST", f"/api/docs/{d2}/reopen", {})
    moved = work / "moved"
    shutil.move(str(D["D3"]), str(moved))
    st_rm, rmv = C.js("POST", f"/api/docs/{d3}/reopen", {})
    shutil.move(str(moved), str(D["D3"]))
    R.rec("首頁「接續」：只開最近清單的 id；資料夾不見了要說明", st_ro == 200 and st_rm == 404 and "找不到" in rmv["message"], rmv["message"])

    # ---- 殘留：服務被強制結束後 instance.json 還在
    H.kill(inst2["pid"])
    time.sleep(0.5)
    stale = H.instance(home) is not None
    res6, urls6, _, _ = L([D["D2"]])
    inst3 = H.instance(home)
    SECRETS.append(inst3["secret"])
    R.rec("服務異常結束後的殘留處理", stale and res6 and res6[0]["status"] == "open" and inst3["pid"] != inst2["pid"], "連不上 → 刪掉重啟")

    # ---- 版號不同的舊服務被換掉
    ip = home / "proofread" / "state" / "instance.json"
    j = json.loads(ip.read_text(encoding="utf-8"))
    j["version"] = "0.9.0"
    ip.write_text(json.dumps(j), encoding="utf-8")
    res7, urls7, code7, _ = L([D["D2"]])
    inst4 = H.instance(home)
    SECRETS.append(inst4["secret"])
    t_old = time.time()
    while H.pid_alive(inst3["pid"]) and time.time() - t_old < 5:
        time.sleep(0.2)
    R.rec("版號不同（升級後舊服務還在）→ 舊的結束、啟動新版", code7 == 0 and res7[0]["status"] == "open" and inst4["pid"] != inst3["pid"]
          and inst4["version"] == H.TOOL_VERSION and not H.pid_alive(inst3["pid"]), "")

    # ---- --shutdown：分頁收到 closing → 先存再放開 → 服務馬上結束
    E = H.Tab(inst4["port"], "tabE")
    E.login(collect(urls7)[0])
    E.lease(d2)
    sd = {}
    th = threading.Thread(target=lambda: sd.update(r=subprocess.run([sys.executable, "-B", str(H.LAUNCHER), "--home", str(home), "--shutdown"],
                                                                     capture_output=True, text=True, encoding="utf-8", env=env)))
    th.start()
    time.sleep(0.8)
    st, le = E.lease(d2)
    _, dd2 = E.data(d2)
    st_s, _ = E.save(d2, dd2["session"]["rev"], {}, [], reason="服務關閉")
    E.post(d2, "bye")
    t1 = time.time()
    w = H.wait_exit(home, inst4["port"], 20)
    th.join(60)
    acts3 = [x["action"] for x in json.loads((D["D2"] / ".proofread" / "session.json").read_text(encoding="utf-8"))["log"]]
    R.rec("--shutdown：分頁先存、放開後服務結束", le.get("closing") is True and st_s == 200 and "儲存（服務關閉）" in acts3 and w is not None and w < 5
          and '"closing": true' in sd["r"].stdout, f"存檔 {st_s}、放開後 {w:.1f} 秒結束" if w is not None else "沒有結束")
    _, _, code_h, _ = H.launch(home, [D["D2"]])
    R.rec("關閉中的交接不接新稿，舊服務結束後由新服務接手", code_h == 0 and H.instance(home) is not None, "")
    H.stop(home)

    # ================================================================ idle_seconds 設定值
    for val, want in ((45, 45), (5, 180), ("x", 180)):
        hc = H.make_home(work, f"home-idle-{val}")
        (hc / "proofread").mkdir(exist_ok=True)
        (hc / "proofread" / "config.json").write_text(json.dumps({"idle_seconds": val}), encoding="utf-8")
        rc, uc, _, _ = H.launch(hc, [D["D3"]], idle=None)
        ic = H.instance(hc)
        Tc = H.Tab(ic["port"], "c")
        Tc.login(collect(uc)[0])
        _, dc = Tc.js("GET", "/api/docs")
        R.rec(f"idle_seconds 設定 {val!r} → {want}", dc["idle_seconds"] == want, f"服務回報 {dc['idle_seconds']}")
        H.stop(hc)

    # ================================================================ 寫檔錯誤 500、字幕寫入失敗 207（模擬）
    hf = H.make_home(work, "home-fault")
    envf = dict(H.base_env(hf), MMPROOF_FAULTS="save,srt")
    f5 = work / "fault" / "D3-demo_minutes"
    shutil.copytree(D["D3"], f5)
    rf5, uf5, _, _ = H.launch(hf, [f5], env=envf)
    i5 = H.instance(hf)
    F5 = H.Tab(i5["port"], "f")
    F5.login(collect(uf5)[0])
    id5 = rf5[0]["id"]
    F5.lease(id5)
    _, d5f = F5.data(id5)
    st_e5, e5 = F5.save(id5, d5f["session"]["rev"], {}, [])
    st_f5, f5r = F5.post(id5, "finalize", {"allow_pending": True})
    R.rec("寫檔錯誤 500 並說明原因", st_e5 == 500 and "寫不進 .proofread/session.json" in e5["message"], e5["message"])
    R.rec("字幕寫入失敗（模擬）→ 207：已寫入的與失敗的分開列", st_f5 == 207 and [w["file"] for w in f5r["written"]] == ["transcript.final.md"]
          and f5r["failed"][0]["file"] == "transcript.final.srt", json.dumps(f5r["failed"], ensure_ascii=False))
    H.stop(hf)

    # ================================================================ 重做：假的 Pro 2.3.0
    fake = H.materials.make_fake_pro(H.PRO_SCRIPTS, work / "fake-pro-2.3.0")
    hr = H.make_home(work, "home-pro230")
    envr = H.base_env(hr, fake)
    f6 = work / "redo" / "D1-demo_minutes"
    shutil.copytree(D["D1"], f6)
    for n in ("transcript.md", "transcript.corrected.md"):
        (f6 / n).write_text(pristine["D1"][n], encoding="utf-8")
    shutil.rmtree(f6 / ".proofread", ignore_errors=True)
    rr6, ur6, _, _ = H.launch(hr, [f6], env=envr)
    i6 = H.instance(hr)
    G = H.Tab(i6["port"], "g")
    G.login(collect(ur6)[0])
    id6 = rr6[0]["id"]
    G.lease(id6)
    _, d6 = G.data(id6)
    dec6, man6 = H.d1_decisions(d6)
    G.save(id6, d6["session"]["rev"], dec6, man6)
    G.post(id6, "finalize")
    st_d, rdp = G.post(id6, "redo", {"dry_run": True})
    R.rec("重做確認畫面（Pro ≥ 2.3.0：供應商、費用估算、檔與備份）", d6["redo"]["available"] and st_d == 200 and rdp["estimate"]["provider"] == "Claude"
          and rdp["estimate"]["usd_high"] == 0.02 and rdp["plan"][0]["backup"] and rdp["plan"][1]["file"] == "meeting-minutes.html",
          f"{rdp.get('estimate')}；{[(x['file'], x['backup']) for x in rdp.get('plan', [])]}")
    mm_before = (f6 / "meeting-minutes.md").read_text(encoding="utf-8")
    st_go, _ = G.post(id6, "redo")
    st_dup, dup = G.post(id6, "redo")
    j6 = wait_job(G, id6)
    R.rec("重做（背景執行；同時只能一個；結果列檔名、備份、網頁版）", st_go == 202 and st_dup == 409 and j6 and j6["status"] == "ok"
          and j6["written"][0]["backup"] and (f6 / j6["written"][0]["backup"]).read_text(encoding="utf-8") == mm_before
          and "假的重做" in (f6 / "meeting-minutes.md").read_text(encoding="utf-8") and any(w["file"] == "meeting-minutes.html" for w in j6["written"]),
          f"{j6 and j6['written']}")
    (hr / "fake-exit.txt").write_text("3", encoding="utf-8")
    G.post(id6, "redo")
    j7 = wait_job(G, id6)
    R.rec("重做失敗：exit code 對應 Pro（3 登入失敗）並顯示 Pro 的訊息", j7 and j7["status"] == "failed" and "登入失敗（exit 3）" in j7["failed"][0]["reason"]
          and "模擬的失敗" in j7["failed"][0]["reason"], j7 and j7["failed"][0]["reason"])
    (hr / "fake-exit.txt").unlink()
    sp6 = f6 / ".proofread" / "session.json"
    s6 = json.loads(sp6.read_text(encoding="utf-8"))
    acts6 = [x["action"] for x in s6["log"]]
    s6["redo"] = {"started_at": "2026-01-01T00:00:00+08:00", "status": "running"}
    sp6.write_text(json.dumps(s6, ensure_ascii=False), encoding="utf-8")
    _, d6b = G.data(id6)
    R.rec("重做紀錄與「上次的重做沒有完成」偵測", "重做會議記錄" in acts6 and "重做會議記錄（失敗）" in acts6 and d6b["redo"]["interrupted"] is True, "")
    H.stop(hr)

    # ================================================================ 〔1.1.0〕本機限定：搭 Pro 2.2.0／2.3.0／2.4.0
    lo_detail = []
    lo_ok = {"marker": True, "config": True, "plain": True, "other": True}
    for v in ("2.2.0", "2.3.0", "2.4.0"):
        fv = H.materials.make_fake_pro(H.PRO_SCRIPTS, work / f"fake-pro-lo-{v}", version=v)
        for mode in ("plain", "config"):
            hv = H.make_home(work, f"home-lo-{v}-{mode}", {"runtime_version": v, **({"privacy": {"local_only": True}}
                                                                                    if mode == "config" else {})})
            base = work / "lo" / v / mode
            folders = []
            for name in (("D2-demo_minutes", "D3-demo_minutes") if mode == "plain" else ("D2-demo_minutes",)):
                fd = base / name
                shutil.copytree(D[name[:2]], fd)
                shutil.rmtree(fd / ".proofread", ignore_errors=True)
                folders.append(fd)
            if mode == "plain":
                (folders[1] / "local-only.json").write_text('{"local_only": true, "source": "sendto"}\n', encoding="utf-8")
            rv, uv, _, _ = H.launch(hv, folders, env=H.base_env(hv, fv))
            iv = H.instance(hv)
            T = H.Tab(iv["port"], f"lo-{v}-{mode}")
            T.login(collect(uv)[0])
            ids = [x["id"] for x in rv]
            _, docs = T.js("GET", "/api/docs")
            flags = {o["name"]: o["local_only"] for o in docs["open"]}
            for k, did in enumerate(ids):
                T.lease(did)
                _, dv = T.data(did)
                st_r, rr = T.post(did, "redo", {"dry_run": True})
                lo = dv.get("local_only")
                is_marker = mode == "plain" and k == 1
                if mode == "config" or is_marker:
                    want = ["config"] if mode == "config" else ["marker"]
                    ok = (lo and lo["sources"] == want and dv["redo"]["available"] is False and dv["redo"]["local_only"] is True
                          and "本機限定" in dv["redo"]["reason"] and "GPT 或 Claude" in dv["redo"]["reason"]
                          and ("local-only.json" in dv["redo"]["reason"] if is_marker else "privacy.local_only" in dv["redo"]["reason"])
                          and st_r == 409 and rr["error"] == "local_only" and flags[folders[k].name] is True
                          and docs["local_only_global"] is (mode == "config"))
                    lo_ok["marker" if is_marker else "config"] &= bool(ok)
                    if is_marker:          # 其他功能照常：定稿可以做
                        st_f, fr = T.post(did, "finalize", {"allow_pending": True})
                        lo_ok["other"] &= st_f == 200 and (folders[k] / "transcript.final.md").exists()
                    lo_detail.append(f"{v}/{'標記檔' if is_marker else '全域'}：redo {st_r} {rr.get('error')}")
                else:
                    want_av = H.locate.vtuple(v) >= (2, 3, 0)
                    ok = lo is None and dv["redo"]["available"] is want_av and dv["redo"]["local_only"] is False \
                        and flags[folders[k].name] is False and docs["local_only_global"] is False
                    lo_ok["plain"] &= bool(ok)
                    lo_detail.append(f"{v}/一般：重做{'可用' if want_av else '停用'}")
            H.stop(hv)
    R.rec("本機限定（標記檔）：Pro 2.2／2.3／2.4 都停用重做並寫原因（本機限定、GPT 或 Claude、刪除 local-only.json），重做 API 409 local_only，首頁標示",
          lo_ok["marker"], "；".join(x for x in lo_detail if "標記檔" in x))
    R.rec("本機限定（全域 privacy.local_only）：Pro 2.2／2.3／2.4 都停用重做、首頁 local_only_global", lo_ok["config"],
          "；".join(x for x in lo_detail if "全域" in x))
    R.rec("沒有本機限定：重做是否可用只看 Pro 版號（2.2 停用、2.3／2.4 可用），首頁不標示", lo_ok["plain"],
          "；".join(x for x in lo_detail if "一般" in x))
    R.rec("本機限定時其他功能照常（定稿寫出 transcript.final.md）", lo_ok["other"], "")

    # ================================================================ server.log
    logs = "".join(p.read_text(encoding="utf-8") for p in work.rglob("server.log*"))
    leaked = sum(logs.count(s) for s in SECRETS if s)
    fmt_ok = all(re.fullmatch(r"\S+ [A-Z]+ /\S* \S+", ln) for ln in logs.strip().splitlines())
    R.rec("server.log 只記時間、方法、路徑、狀態碼；權杖、cookie、密鑰 0 筆", leaked == 0 and fmt_ok and "?" not in logs,
          f"{len(logs.splitlines())} 行；比對 {len([s for s in SECRETS if s])} 個秘密值，命中 {leaked}")
    pyc = list(H.PRO_SCRIPTS.rglob("__pycache__"))
    R.rec("Pro 版本目錄沒有 __pycache__", not pyc, "")
    shutil.rmtree(work, ignore_errors=True)
    return R, perf, round(time.time() - started, 1)


if __name__ == "__main__":
    r, perf, sec = main()
    print(f"\nintegration {r.passed}/{len(r.cases)} PASS（{sec} 秒）；{perf}")
    sys.exit(0 if r.passed == len(r.cases) else 1)
