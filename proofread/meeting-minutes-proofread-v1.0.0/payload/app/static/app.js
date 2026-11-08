// 會議記錄校稿 1.0.0 前端。只連本機服務（CSP connect-src 'self'），不載入任何外部資源。
// 所有文字都用 textContent 放進頁面（不拼 innerHTML），逐字稿裡的 <…> 不會被當成 HTML。
'use strict';
(function () {
  var THEME_KEY = 'mmproof-theme';
  var ICON = { pending: '●', accepted: '✓', edited: '✎', rejected: '↺' };
  var STATE_LABEL = { pending: '未處理', accepted: '已確認', edited: '已改', rejected: '已退回' };
  var STATE_CHIP = { pending: 'p', accepted: 'a', edited: 'e', rejected: 'r' };
  var KIND_LABEL = { fix: '校正', unify: '用字統一', uncertain: '待確認', insert: '補字', 'delete': '刪除', manual: '人工修改' };
  var BAD_VALUE = /[{}\n\r]|\[\?/;
  var KEEPALIVE_MAX = 60000;      // 瀏覽器 keepalive 請求的上限約 64 KB
  var app = document.getElementById('app');
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------- 工具
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'style') el.style.cssText = v;            // CSSOM（CSP 不允許 HTML 的 style 屬性）
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, kid) {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach(function (k) { add(el, k); }); return; }
    el.appendChild(typeof kid === 'string' ? document.createTextNode(kid) : kid);
  }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function api(method, url, body, keepalive) {
    var opt = { method: method, credentials: 'same-origin', headers: { 'X-MMP': '1' }, keepalive: !!keepalive };
    if (body !== undefined) { opt.headers['Content-Type'] = 'application/json'; opt.body = typeof body === 'string' ? body : JSON.stringify(body); }
    return fetch(url, opt).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (j) { return { status: r.status, ok: r.ok, data: j }; });
    }).catch(function () { return { status: 0, ok: false, data: null }; });
  }
  function secOf(t) { var p = t.split(':').map(Number); return p[0] * 3600 + p[1] * 60 + p[2]; }
  function hhmmss(iso) { return iso ? iso.slice(11, 19) : ''; }
  function ymdhm(iso) { return iso ? iso.slice(0, 16).replace('T', ' ') : ''; }
  function why(r, fallback) {
    if (r.status === 0) return '連不上會議記錄校稿（服務可能已結束，請從右鍵重新開啟這份稿）';
    return (r.data && (r.data.message || r.data.error)) || fallback || ('HTTP ' + r.status);
  }
  function initTheme() {
    try { var t = localStorage.getItem(THEME_KEY); if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t); } catch (e) { /* 沒有儲存空間時用預設深色 */ }
  }
  function themeBtn() {
    return h('button', { class: 'btn', type: 'button', title: '切換深色／淺色', onclick: function () {
      var next = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* 只是記住偏好 */ }
    } }, '◐ 主題');
  }
  initTheme();

  // ---------------------------------------------------------------- 對話框
  function modal(title, body, buttons) {
    var prev = document.activeElement;
    var bg = h('div', { class: 'modal-bg', role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
    var close = function () { bg.remove(); document.removeEventListener('keydown', onk, true); if (prev && prev.focus) try { prev.focus({ preventScroll: true }); } catch (e) { /* 原元素可能已重畫 */ } };
    var onk = function (e) { if (e.key === 'Escape') { e.stopPropagation(); e.preventDefault(); close(); } };
    document.addEventListener('keydown', onk, true);
    var acts = h('div', { class: 'acts' });
    (buttons || []).forEach(function (b) {
      acts.appendChild(h('button', { class: 'btn' + (b.primary ? ' primary' : '') + (b.warn ? ' warn' : ''), type: 'button', onclick: function () { if (!b.keep) close(); if (b.fn) b.fn(); } }, b.label));
    });
    bg.appendChild(h('div', { class: 'modal' }, h('h2', { text: title }), body, acts));
    document.body.appendChild(bg);
    var f = acts.querySelector('.primary') || acts.querySelector('button');
    if (f) f.focus();
    return close;
  }
  function info(title, msg) { modal(title, [h('p', { text: msg })], [{ label: '好', primary: true }]); }

  // ---------------------------------------------------------------- 首頁（多份稿）
  function home() {
    document.title = '會議記錄校稿';
    var box = h('main', { class: 'home' });
    app.appendChild(box);
    function load() {
      api('GET', '/api/docs').then(function (r) {
        if (!r.ok) { clear(box); box.appendChild(h('h1', { text: '會議記錄校稿' })); box.appendChild(h('p', { text: why(r, '讀不到清單') })); return; }
        clear(box);
        var d = r.data;
        var mins = Math.max(1, Math.round((d.idle_seconds || 180) / 60));
        box.appendChild(h('div', { class: 'home-head' }, h('h1', { text: '會議記錄校稿' }),
          h('span', { class: 'muted', text: '版本 ' + d.version + '｜meeting-minutes-pro ' + d.pro_version }), themeBtn()));
        box.appendChild(h('p', { class: 'muted', text: '每份稿各開一個分頁。從檔案總管對輸出資料夾按右鍵「傳送到 → 會議記錄校稿」，或雙擊資料夾裡的「會議記錄校稿」捷徑，就會加到這裡。' }));
        box.appendChild(h('h2', { text: '開著的稿（' + d.open.length + '）' }));
        var c1 = h('div', { class: 'cards' });
        if (!d.open.length) c1.appendChild(h('p', { class: 'empty', text: '目前沒有開著的稿。' }));
        d.open.forEach(function (o) {
          c1.appendChild(h('div', { class: 'card' }, h('div', { class: 'name', text: o.name }),
            h('div', { class: 'row' }, h('span', { class: 'tag' + (o.editing ? ' live' : ''), text: o.editing ? '● 編輯中（在另一個分頁）' : '沒有分頁' }),
              h('a', { class: 'btn', href: '/d/' + o.id + (o.editing ? '?attach=1' : ''), target: '_blank', rel: 'noopener', text: o.editing ? '前往' : '開啟' }))));
        });
        box.appendChild(c1);
        box.appendChild(h('h2', { text: '最近的稿（可接續）' }));
        var c2 = h('div', { class: 'cards' });
        if (!d.recent.length) c2.appendChild(h('p', { class: 'empty', text: '還沒有校過的稿。' }));
        d.recent.forEach(function (o) {
          var p = o.progress, pct = p && p.total ? Math.round(p.done * 100 / p.total) : 0;
          c2.appendChild(h('div', { class: 'card' }, h('div', { class: 'name', text: o.name }),
            h('div', { class: 'row' }, h('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(p ? p.total : 0), 'aria-valuenow': String(p ? p.done : 0) }, h('i', { style: 'width:' + pct + '%' })),
              h('span', { class: 'muted', text: p ? ('已處理 ' + p.done + '／' + p.total + '（' + pct + '%）') : '尚未開始' })),
            h('div', { class: 'row' }, h('span', { class: 'muted', text: o.saved_at ? ('上次儲存 ' + ymdhm(o.saved_at)) : ('上次開啟 ' + ymdhm(o.opened_at) + '（還沒有儲存）') }),
              h('button', { class: 'btn primary', type: 'button', onclick: function () {
                api('POST', '/api/docs/' + o.id + '/reopen', {}).then(function (rr) {
                  if (rr.ok) { window.open('/d/' + o.id + (rr.data.editing ? '?attach=1' : ''), '_blank', 'noopener'); load(); }
                  else info('開不起來', why(rr));
                });
              } }, '接續'))));
        });
        box.appendChild(c2);
        box.appendChild(h('p', { class: 'note', text: '所有分頁關掉約 ' + mins + ' 分鐘後，會議記錄校稿會自動結束；不用另外關閉。校稿進度存在各輸出資料夾的 .proofread 資料夾裡。' }));
      });
    }
    load();
    setInterval(function () { api('POST', '/api/ping', {}); load(); }, 15000);
  }

  // ---------------------------------------------------------------- 校稿畫面
  function docView(id, attach) {
    var S = { id: id, tab: Math.random().toString(36).slice(2) + Date.now().toString(36), marks: {}, manual: [], history: [],
      redo: [], rev: 0, holder: false, readonly: true, dirty: false, saving: false, ver: 0, filterPending: false,
      cur: null, side: 'list', listState: 'all', listKind: 'all', narrow: window.matchMedia('(max-width: 760px)').matches };
    var el = {};
    api('GET', '/api/doc/' + id + '/data').then(function (r) {
      if (!r.ok) { app.appendChild(h('main', { class: 'plain-box' }, h('h1', { text: '開不起來' }), h('p', { text: why(r, '請從右鍵或首頁重新開啟。') }))); return; }
      var t0 = performance.now();
      S.data = r.data;
      var ss = r.data.session;
      S.marks = ss.marks || {}; S.manual = ss.manual || []; S.history = ss.history || []; S.rev = ss.rev || 0;
      S.changed = r.data.changed; S.formatRO = r.data.readonly; S.notice = r.data.notice;
      S.paras = r.data.doc.body.filter(function (b) { return b.t === 'para'; });
      S.paraBy = {};
      S.paras.forEach(function (p) {
        var pos = 0;
        p.tokens.forEach(function (t) { t.r0 = pos; pos += (t.t === 'mark' ? t.src : t.text).length; });
        p.raw = p.tokens.map(function (t) { return t.t === 'mark' ? t.src : t.text; }).join('');
        S.paraBy[p.i] = p;
      });
      document.title = r.data.name + '｜會議記錄校稿';
      S.lastSaved = ss.saved_at;
      if (ss.rev && ss.saved_at && !S.changed && !attach) {          // 提示頁（已在別的分頁開啟）不顯示接續
        var pg0 = progress();
        S.resume = '接續上次的校稿：上次儲存 ' + ymdhm(ss.saved_at) + '、已處理 ' + pg0.done + '／' + pg0.total + ' 處。';
      }
      build();
      if (S.changed || S.narrow || S.formatRO) setReadonly(true);
      else if (!attach) lease(false);
      else showAttach();
      startHeartbeat();
      channel();
      goFirstPending();
      window.mmproofLoadMs = Math.round(performance.now() - t0);
    });

    // ---- 模型（與 mmproof_model.py 相同的規則）
    function paraTokens(p) {
      var us = S.manual.filter(function (u) { return u.para === p.i; }).sort(function (a, b) { return a.start - b.start; });
      if (!us.length) return p.tokens;
      var out = [];
      p.tokens.forEach(function (t) {
        if (t.t !== 'text') { out.push(t); return; }
        var r0 = t.r0, r1 = t.r0 + t.text.length, pos = 0;
        us.filter(function (u) { return u.start >= r0 && u.end <= r1; }).forEach(function (u) {
          var s = u.start - r0, e = u.end - r0;
          if (s > pos) out.push({ t: 'text', text: t.text.slice(pos, s), r0: r0 + pos });
          out.push({ t: 'mark', id: u.id, kind: 'manual', orig: t.text.slice(s, e), sugg: u.value, guess: null, value: u.value, manual: u });
          pos = e;
        });
        if (pos < t.text.length) out.push({ t: 'text', text: t.text.slice(pos), r0: r0 + pos });
      });
      return out;
    }
    function stateOf(m) {
      if (m.kind === 'manual') return 'edited';
      var d = S.marks[m.id];
      if (!d) return 'pending';
      if (d.choice === 'free') return 'edited';
      if (d.choice === 'orig') return m.kind === 'uncertain' ? 'accepted' : 'rejected';
      return 'accepted';
    }
    function valueOf(m) {
      if (m.kind === 'manual') return m.value;
      var d = S.marks[m.id];
      if (!d) return m.kind === 'uncertain' ? m.orig : m.sugg;
      if (d.choice === 'orig') return m.orig;
      if (d.choice === 'guess') return m.guess || m.orig;
      if (d.choice === 'free') return d.value;
      return m.kind === 'uncertain' ? (m.guess || m.orig) : m.sugg;
    }
    function allMarks() {
      var out = [];
      S.paras.forEach(function (p) { paraTokens(p).forEach(function (t) { if (t.t === 'mark') out.push({ m: t, p: p }); }); });
      return out;
    }
    function findMark(mid) {
      if (mid && mid.charAt(0) === 'm') {
        var p = S.paraBy[+mid.slice(1).split('-')[0]];
        if (p) { var ts = paraTokens(p); for (var i = 0; i < ts.length; i++) if (ts[i].id === mid) return { m: ts[i], p: p }; }
      }
      var all = allMarks();
      for (var j = 0; j < all.length; j++) if (all[j].m.id === mid) return all[j];
      return null;
    }
    function progress() {
      var st = { pending: 0, accepted: 0, edited: 0, rejected: 0, total: 0 };
      allMarks().forEach(function (x) { st[stateOf(x.m)]++; st.total++; });
      st.done = st.total - st.pending;
      return st;
    }

    // ---- 版面
    function build() {
      clear(app);
      var d = S.data;
      el.prog = h('div', { class: 'prog', 'aria-label': '校稿進度' });
      el.save = h('span', { class: 'save', role: 'status', 'aria-live': 'polite' });
      el.retry = h('button', { class: 'btn small', type: 'button', onclick: function () { save({ manual: true }); } }, '立刻重試');
      el.saveBtn = h('button', { class: 'btn small', type: 'button', title: '立刻儲存（Ctrl＋S／⌘S）', onclick: function () { save({ manual: true }); } }, '儲存');
      el.saveBox = h('span', { class: 'savebox' }, el.save, el.saveBtn);
      el.errText = h('span');
      el.errbar = h('div', { class: 'errbar', role: 'alert', hidden: true }, el.errText, el.retry);
      el.toast = h('span', { class: 'toast', role: 'status', 'aria-live': 'polite' });
      el.filter = h('button', { class: 'btn', type: 'button', 'aria-pressed': 'false', onclick: toggleFilter, title: '只看還有未處理標記的段落（U）' }, '只看未處理');
      var top = h('header', { class: 'top' },
        h('a', { class: 'btn', href: '/', target: 'mmproof-home', title: '首頁：開著的稿與最近的稿' }, '⌂ 首頁'),
        h('span', { class: 'title', title: d.name, text: d.name }), el.prog, el.saveBox, el.toast, h('span', { class: 'grow' }), el.filter,
        sideBtn('list', '標記清單'), sideBtn('exp', '經驗整理'), sideBtn('final', '定稿'), sideBtn('log', '紀錄'), themeBtn(),
        h('button', { class: 'btn', type: 'button', onclick: help, title: '鍵盤操作（?）' }, '?'), el.errbar);
      el.toc = h('nav', { class: 'toc', 'aria-label': '段落' });
      el.main = h('main', { class: 'main', tabindex: '-1' });
      el.banners = h('div');
      el.side = h('aside', { class: 'side', 'aria-label': '側欄' });
      el.shell = h('div', { class: 'shell' }, top, el.toc, el.main, el.side);
      if (d.media && d.media.status === 'found') {
        el.audio = h(d.media.type === 'video' ? 'video' : 'audio', { controls: true, preload: 'metadata', src: '/api/doc/' + id + '/media' });
        el.shell.appendChild(h('footer', { class: 'dock' }, h('span', { class: 'lbl', text: '原始' + (d.media.type === 'video' ? '影片' : '錄音') + '：' + d.media.name }), el.audio));
      } else if (d.media && d.media.status === 'unsupported') {
        el.shell.appendChild(h('footer', { class: 'dock' }, h('span', { class: 'lbl', text: '原始檔格式 ' + d.media.ext + ' 瀏覽器多半不能播放，時間碼以文字顯示。' })));
      } else {
        el.shell.appendChild(h('footer', { class: 'dock' }, h('span', { class: 'lbl', text: '找不到原始錄音或影片（放在輸出資料夾旁、同檔名），時間碼以文字顯示。' })));
      }
      app.appendChild(el.shell);
      el.main.appendChild(el.banners);
      el.main.appendChild(legend());
      var frag = document.createDocumentFragment();
      el.paraEls = {};
      S.paras.forEach(function (p) { var pe = paraEl(p); el.paraEls[p.i] = pe; frag.appendChild(pe); });
      el.main.appendChild(frag);
      buildToc();
      renderSide();
      updateProgress();
      setSave(S.rev ? 'saved' : 'new', d.session.saved_at);
      el.main.addEventListener('mouseup', onSelect);
      el.main.addEventListener('keyup', function (e) { if (e.shiftKey) onSelect(); });
      el.main.addEventListener('click', onMainClick);
      document.addEventListener('keydown', onKey);
      window.addEventListener('pagehide', function () {
        if (S.dirty) save({ keepalive: true, reason: '離開分頁' });
        if (S.holder) api('POST', '/api/doc/' + id + '/bye', { tab: S.tab }, true);
      });
      window.addEventListener('beforeunload', function (e) {
        if (S.dirty || S.saving) { save({ keepalive: true, reason: '離開分頁' }); e.preventDefault(); e.returnValue = ''; }
      });
      document.addEventListener('keydown', function (e) {
        if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key && e.key.toLowerCase() === 's') { e.preventDefault(); save({ manual: true }); }
      }, true);
      banners();
    }
    function sideBtn(k, label) {
      return h('button', { class: 'btn' + (S.side === k ? ' on' : ''), type: 'button', 'data-side': k, onclick: function () { openSide(S.side === k ? null : k); } }, label);
    }
    function openSide(k) {
      S.side = k;
      el.shell.classList.toggle('no-side', !k);
      app.querySelectorAll('[data-side]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-side') === k); });
      renderSide();
    }
    function legend() {
      function sample(cls, ic, txt) { return h('span', { class: 'mk ' + cls }, h('span', { class: 'ic', 'aria-hidden': 'true', text: ic }), txt); }
      return h('div', { class: 'legend', 'aria-label': '圖例' },
        sample('k-fix s-pending', '●', '未處理（校正、刪除、補字）'), sample('k-uncertain s-pending', '?', '待確認'), sample('k-unify s-pending', '●', '用字統一'),
        sample('s-accepted', '✓', '已確認'), sample('s-edited', '✎', '已改／人工修改'), sample('s-rejected', '↺', '已退回（用原文）'),
        h('span', { text: '選取任何文字可直接修改' }));
    }
    function pendingIn(p) { return paraTokens(p).filter(function (t) { return t.t === 'mark' && stateOf(t) === 'pending'; }).length; }
    function tocItem(p) {
      var n = pendingIn(p);
      return h('a', { href: '#p-' + p.i, onclick: function (e) { e.preventDefault(); el.paraEls[p.i].scrollIntoView({ block: 'start' }); } },
        h('span', { class: 'tt', text: p.time }), h('span', { class: 'sp', text: p.speaker }), n ? h('span', { class: 'n', title: '未處理 ' + n + ' 處', text: '●' + n }) : null);
    }
    function buildToc() {
      clear(el.toc);
      el.tocEls = {};
      var frag = document.createDocumentFragment();
      S.paras.forEach(function (p) { var a = tocItem(p); el.tocEls[p.i] = a; frag.appendChild(a); });
      el.toc.appendChild(frag);
    }
    function paraEl(p) {
      var hasMedia = !!el.audio || (S.data.media && S.data.media.status === 'found');
      var t = h('button', { class: 'tc', type: 'button', 'data-t': secOf(p.time), disabled: !hasMedia, title: hasMedia ? '從這裡播放（.）' : '沒有可播放的原始錄音' }, (hasMedia ? '▶ ' : '') + p.time);
      var body = h('p', { class: 'pt' });
      paraTokens(p).forEach(function (tk) {
        if (tk.t === 'text') body.appendChild(h('span', { class: 'tx', 'data-p': p.i, 'data-s': tk.r0, text: tk.text }));
        else body.appendChild(markEl(tk, p));
      });
      var sec = h('section', { class: 'para', id: 'p-' + p.i, 'data-i': p.i }, h('div', { class: 'ph' }, t, h('span', { class: 'spk', text: p.speaker })), body);
      if (S.filterPending && !pendingIn(p)) sec.classList.add('hidden');
      return sec;
    }
    function markEl(m, p) {
      var st = stateOf(m), v = valueOf(m);
      var b = h('button', { class: 'mk k-' + m.kind + ' s-' + st + (S.cur === m.id ? ' cur' : ''), type: 'button', 'data-id': m.id, 'data-p': p.i });
      var ic = m.kind === 'uncertain' && st === 'pending' ? '?' : ICON[st];
      b.appendChild(h('span', { class: 'ic', 'aria-hidden': 'true', text: ic }));
      if (st === 'pending') {
        if (m.kind === 'uncertain') { b.appendChild(document.createTextNode(m.orig)); if (m.guess) b.appendChild(h('span', { class: 'g', text: '｜' + m.guess + '？' })); }
        else if (m.kind === 'insert') b.appendChild(h('ins', { text: '+' + m.sugg }));
        else if (m.kind === 'delete') b.appendChild(h('del', { text: m.orig }));
        else { b.appendChild(h('del', { text: m.orig })); b.appendChild(document.createTextNode('→')); b.appendChild(h('ins', { text: m.sugg })); }
      } else if (v === '') b.appendChild(h('del', { text: m.orig || '（不補字）' }));
      else b.appendChild(document.createTextNode(v));
      var target = m.kind === 'uncertain' ? (m.guess || '（沒有推測）') : (m.kind === 'manual' ? m.value : (m.sugg || '（刪除）'));
      var desc = KIND_LABEL[m.kind] + '：' + (m.orig || '（無）') + ' → ' + target + '；' + STATE_LABEL[st] + (st !== 'pending' ? '，目前寫法「' + v + '」' : '');
      b.setAttribute('title', desc);
      b.setAttribute('aria-label', desc);
      return b;
    }
    function rerender(pis) {
      var seen = {};
      pis.forEach(function (pi) {
        if (seen[pi] || !S.paraBy[pi]) return; seen[pi] = 1;
        var p = S.paraBy[pi];
        var ne = paraEl(p);
        el.paraEls[pi].replaceWith(ne);
        el.paraEls[pi] = ne;
        var a = tocItem(p); el.tocEls[pi].replaceWith(a); el.tocEls[pi] = a;
      });
      updateProgress();
      if (S.side === 'list') renderSide();
    }
    function updateProgress() {
      var st = progress(), pct = st.total ? Math.round(st.done * 100 / st.total) : 100;
      clear(el.prog);
      el.prog.appendChild(h('div', { class: 'bar', role: 'progressbar', 'aria-label': '已處理', 'aria-valuemin': '0', 'aria-valuemax': String(st.total), 'aria-valuenow': String(st.done) }, h('i', { style: 'width:' + pct + '%' })));
      el.prog.appendChild(h('span', { text: '已處理 ' + st.done + '／' + st.total + '（' + pct + '%）' }));
      el.filter.textContent = '只看未處理（' + st.pending + '）';
    }
    // 存檔狀態列：已儲存／儲存中／有未儲存的變更／儲存失敗（原因＋重試）；另有尚未修改與唯讀
    function setSave(kind, at, reason) {
      var m = { 'new': '尚未修改', saved: '✓ 已儲存 ' + hhmmss(at), dirty: '● 有未儲存的變更', saving: '儲存中…',
        err: '✕ 儲存失敗（原因見下方）', ro: '唯讀（這個分頁不會儲存）' };
      el.save.textContent = m[kind] || '';
      el.save.className = 'save s-' + kind;
      el.errbar.hidden = kind !== 'err';
      el.errText.textContent = '儲存失敗：' + (reason || '原因不明') + '。修改還在這個分頁，沒有遺失；會每 5 秒自動重試。';
      el.saveBtn.disabled = kind === 'ro';
      S.saveState = kind;
    }
    function flash(msg) {
      el.toast.textContent = msg; el.toast.classList.remove('show'); void el.toast.offsetWidth; el.toast.classList.add('show');
      clearTimeout(S.toastT); S.toastT = setTimeout(function () { el.toast.textContent = ''; el.toast.classList.remove('show'); }, 3500);
    }

    // ---- 橫幅
    function banners() {
      clear(el.banners);
      function bn(cls, text, btns) { el.banners.appendChild(h('div', { class: 'banner' + (cls ? ' ' + cls : '') }, h('p', { text: text }), btns || [])); }
      if (S.notice) bn('err', S.notice, [h('button', { class: 'btn', type: 'button', onclick: function () { S.notice = null; banners(); } }, '知道了')]);
      if (S.resume) bn('info', S.resume, [h('button', { class: 'btn', type: 'button', onclick: function () { S.resume = null; banners(); } }, '知道了')]);
      if (S.narrow) bn('info', '手機寬度只能檢視。要校稿請用電腦（視窗寬度 760px 以上）。');
      if (S.formatRO) bn('err', '這份稿的校稿暫存是較新版的會議記錄校稿寫的，這一版只能看。請升級會議記錄校稿後再開啟。');
      if (S.changed) {
        bn('', '校正版逐字稿（' + S.changed.file + '）在上次校稿之後被重新產生（例如重跑了 AI 校正）。下面是開始校稿時的版本，只能看。', [
          h('button', { class: 'btn primary', type: 'button', onclick: function () { restart(true); } }, '用新版重新開始，帶入對得上的決定'),
          h('button', { class: 'btn', type: 'button', onclick: function () { restart(false); } }, '用新版重新開始')]);
      }
      if (S.lost) bn('', '這份稿已在另一個分頁編輯，這個分頁改成只能看（你在這裡的修改都已暫存）。', [h('button', { class: 'btn', type: 'button', onclick: function () { lease(true); } }, '改回在這個分頁編輯')]);
      if (S.attachNote) el.banners.appendChild(S.attachNote);
      if (S.attention) bn('info', '你剛剛又從右鍵（或捷徑）開啟了這份稿：它就在這個分頁，繼續在這裡校稿即可。', [h('button', { class: 'btn', type: 'button', onclick: function () { S.attention = false; banners(); } }, '知道了')]);
      if (S.data.redo && S.data.redo.interrupted) bn('err', '上次的「重做' + noun() + '」沒有完成，請再按一次。');
    }
    function noun() { return S.data.kind === 'notes' ? '筆記' : '會議記錄'; }
    function showAttach() {
      S.attachNote = h('div', { class: 'banner' },
        h('p', { text: '這份稿已經在另一個分頁開啟（同一份稿只能在一個分頁修改）。請切換到瀏覽器分頁列上的「' + S.data.name + '｜會議記錄校稿」分頁；那個分頁的標題會閃爍提示。' }),
        h('button', { class: 'btn primary', type: 'button', onclick: function () { S.attachNote = null; lease(true); } }, '改在這個分頁編輯'),
        h('button', { class: 'btn', type: 'button', onclick: function () { S.attachNote = null; banners(); } }, '只看'));
      setReadonly(true);
      try { new BroadcastChannel('mmproof').postMessage({ type: 'who', id: id }); } catch (e) { /* 舊瀏覽器沒有 BroadcastChannel：原分頁靠心跳 */ }
    }
    function restart(carry) {
      api('POST', '/api/doc/' + id + '/lease', { tab: S.tab, takeover: true }).then(function () {
        return api('POST', '/api/doc/' + id + '/restart', { tab: S.tab, carry: carry });
      }).then(function (r) {
        if (r.ok) {
          var c = r.data.carried;
          modal('已用新版重新開始', [h('p', { text: c ? ('帶入標記決定 ' + c.marks + '／' + c.marks_total + ' 處、人工修改 ' + c.manual + '／' + c.manual_total + ' 處；對不上的不帶。') : '舊的暫存已備份，從頭開始校稿。' }),
            h('p', { class: 'muted', text: '舊暫存備份：' + r.data.backup })], [{ label: '好', primary: true, fn: function () { location.reload(); } }]);
        } else info('沒有重新開始', why(r));
      });
    }
    function setReadonly(ro) {
      S.readonly = ro || S.narrow || !!S.changed || !!S.formatRO;
      if (S.readonly) setSave('ro');
      banners();
    }

    // ---- 編輯權：同一份稿只有一個分頁能改
    function lease(takeover) {
      return api('POST', '/api/doc/' + id + '/lease', { tab: S.tab, takeover: !!takeover }).then(function (r) {
        if (r.ok && r.data.holder) {
          var was = S.holder;
          S.holder = true; S.lost = false;
          if (!was) {
            if (r.data.rev > S.rev && S.rev !== null) { location.reload(); return; }
            setReadonly(false); setSave(S.dirty ? 'dirty' : (S.rev ? 'saved' : 'new'), S.lastSaved);
          }
          if (r.data.attention) attention();
          if (r.data.closing && !S.closingSeen) {
            S.closingSeen = true;
            var done = function () {
              api('POST', '/api/doc/' + id + '/bye', { tab: S.tab }); S.holder = false; S.readonly = true; setSave('ro');
              modal('會議記錄校稿正在關閉', [h('p', { text: '正在升級或移除會議記錄校稿。你的修改已儲存（' + hhmmss(S.lastSaved) + '）。完成後從右鍵或捷徑重新開啟即可接續。' })], [{ label: '好', primary: true }]);
            };
            if (S.dirty) save({ reason: '服務關閉', then: done }); else done();
          }
        } else if (r.ok) {
          if (S.holder) S.lost = true;
          S.holder = false;
          if (!S.attachNote && !S.lost) showAttach(); else setReadonly(true);
        }
      });
    }
    function startHeartbeat() {
      setInterval(function () {
        if (S.closingSeen) return;
        if (S.holder || S.lost) lease(false); else api('POST', '/api/ping', {});
      }, 10000);
    }
    function attention() {
      S.attention = true; banners();
      if (reduced) return;
      var mark = '● 請看這裡｜', n = 0;
      // 原標題只在沒有閃爍時記一次（去掉前綴）；閃爍中再被提醒就重新計次，結束一定回到原標題
      if (!S.blink) S.title0 = document.title.split(mark).join('');
      var t0 = S.title0;
      clearInterval(S.blink);
      S.blink = setInterval(function () { document.title = (n % 2 ? '' : mark) + t0; if (++n > 12) { clearInterval(S.blink); S.blink = null; document.title = t0; } }, 800);
    }
    function channel() {
      try {
        var bc = new BroadcastChannel('mmproof');
        bc.onmessage = function (e) { if (e.data && e.data.type === 'who' && e.data.id === id && S.holder) attention(); };
      } catch (e) { /* 舊瀏覽器沒有 BroadcastChannel */ }
    }

    // ---- 決定、人工修改、復原
    function changed(pis) { S.ver++; rerender(pis); markDirty(); }
    function decide(items) {
      if (S.readonly) return;
      var rec = { t: 'd', items: [] }, pis = [];
      items.forEach(function (it) {
        var before = S.marks[it.id] || null;
        if (it.dec) S.marks[it.id] = it.dec; else delete S.marks[it.id];
        rec.items.push({ id: it.id, before: before, after: it.dec || null });
        pis.push(it.p);
      });
      S.history.push(rec); S.redo = [];
      changed(pis);
    }
    function addManual(u) { if (S.readonly) return; S.manual.push(u); S.history.push({ t: 'ma', u: u }); S.redo = []; changed([u.para]); }
    function editManual(u, value) {
      if (S.readonly) return;
      var before = u.value; u.value = value; S.history.push({ t: 'me', id: u.id, before: before, after: value }); S.redo = []; changed([u.para]);
    }
    function delManual(u) {
      if (S.readonly) return;
      S.manual = S.manual.filter(function (x) { return x.id !== u.id; }); S.history.push({ t: 'md', u: u }); S.redo = []; changed([u.para]);
    }
    function applyRec(rec, back) {
      var pis = [];
      if (rec.t === 'd') rec.items.forEach(function (it) {
        var v = back ? it.before : it.after;
        if (v) S.marks[it.id] = v; else delete S.marks[it.id];
        var f = findMark(it.id); if (f) pis.push(f.p.i);
      });
      else if (rec.t === 'ma' || rec.t === 'md') {
        var addIt = (rec.t === 'ma') !== back;
        S.manual = S.manual.filter(function (x) { return x.id !== rec.u.id; });
        if (addIt) S.manual.push(JSON.parse(JSON.stringify(rec.u)));
        pis.push(rec.u.para);
      } else if (rec.t === 'me') {
        var u = S.manual.filter(function (x) { return x.id === rec.id; })[0];
        if (u) { u.value = back ? rec.before : rec.after; pis.push(u.para); }
      }
      return pis;
    }
    function undo() { if (S.readonly || !S.history.length) return; var rec = S.history.pop(); S.redo.push(rec); changed(applyRec(rec, true)); flash('已復原'); }
    function redoAct() { if (S.readonly || !S.redo.length) return; var rec = S.redo.pop(); S.history.push(rec); changed(applyRec(rec, false)); flash('已重做'); }

    // ---- 暫存
    function markDirty() { S.dirty = true; setSave('dirty'); clearTimeout(S.timer); S.timer = setTimeout(save, 1200); }
    // opts：manual（按「儲存」或 Ctrl＋S：沒有變更也存一次，並明確回饋）、keepalive（離開分頁）、reason（記進操作紀錄）、then
    function save(opts) {
      opts = opts && typeof opts === 'object' ? opts : {};
      if (S.readonly) { if (opts.manual) flash('這個分頁是唯讀，不會儲存'); if (opts.then) opts.then(); return; }
      if (S.saving && !opts.keepalive) { if (opts.manual) S.manualQueued = true; return; }
      if (!S.dirty && !opts.manual) { if (opts.then) opts.then(); return; }
      clearTimeout(S.timer);
      var body = { tab: S.tab, base_rev: S.rev, marks: S.marks, manual: S.manual, history: S.history.slice(-200),
        manual_save: !!opts.manual, reason: opts.reason || null };
      var raw = JSON.stringify(body);
      if (opts.keepalive && raw.length > KEEPALIVE_MAX) { delete body.history; raw = JSON.stringify(body); }   // 歷史留在伺服器上的那份
      if (opts.keepalive && raw.length > KEEPALIVE_MAX) return;     // 太大：交給瀏覽器的「確定要離開嗎？」
      S.saving = true; setSave('saving');
      var v = S.ver;
      api('PUT', '/api/doc/' + id + '/session', raw, opts.keepalive).then(function (r) {
        S.saving = false;
        if (r.ok) {
          S.rev = r.data.rev; S.lastSaved = r.data.saved_at;
          if (S.ver === v) { S.dirty = false; setSave('saved', r.data.saved_at); } else markDirty();
          if (opts.manual) flash('已儲存 ' + hhmmss(r.data.saved_at) + '（已處理 ' + r.data.progress.done + '／' + r.data.progress.total + ' 處）');
          if (S.manualQueued) { S.manualQueued = false; save({ manual: true }); }
          if (opts.then) opts.then();
        } else if (r.status === 409 && r.data && r.data.error === 'rev') conflict(r.data);
        else if (r.status === 409) { setReadonly(true); info('沒有存到', why(r)); }
        else if (r.status === 423) { S.holder = false; S.lost = true; setReadonly(true); }
        else {
          var reason = r.status === 0 ? '連不上會議記錄校稿（服務可能已結束，請從右鍵重新開啟這份稿；修改還在這個分頁）'
            : ((r.data && r.data.message) || ('HTTP ' + r.status));
          setSave('err', null, reason);
          if (opts.manual) flash('儲存失敗：' + reason);
          S.timer = setTimeout(save, 5000);
        }
      });
    }
    function downloadMine() {
      var blob = new Blob([JSON.stringify({ marks: S.marks, manual: S.manual }, null, 1)], { type: 'application/json' });
      var a = h('a', { href: URL.createObjectURL(blob), download: S.data.name + '.未存的修改.json' }); document.body.appendChild(a); a.click(); a.remove();
    }
    function conflict(d) {
      setReadonly(true);
      modal('沒有存到：這份稿有更新的版本', [
        h('p', { text: (d && d.message) || '' }),
        h('p', { class: 'muted', text: '較新的版本存於 ' + ((d && d.saved_at) || '').replace('T', ' ').slice(0, 19) + '。為了不互相覆蓋，這個分頁的修改沒有寫進去。' })],
        [{ label: '下載這個分頁的修改（JSON）', fn: downloadMine, keep: true }, { label: '載入最新版本', primary: true, fn: function () { S.dirty = false; location.reload(); } }]);
    }
    function flushThen(fn) {
      if (S.readonly) { fn(); return; }
      if (S.dirty || S.saving) { if (!S.saving) save(); setTimeout(function () { flushThen(fn); }, 250); } else fn();
    }

    // ---- 點選標記：選單
    function onMainClick(e) {
      var t = e.target.closest('.tc');
      if (t && el.audio) { el.audio.currentTime = +t.getAttribute('data-t'); el.audio.play().catch(function () { /* 使用者可以再按一次播放 */ }); return; }
      var b = e.target.closest('.mk');
      if (b && b.hasAttribute('data-id')) { setCur(b.getAttribute('data-id')); openMenu(b); }
    }
    function setCur(mid) {
      var old = el.main.querySelector('.mk.cur'); if (old) old.classList.remove('cur');
      S.cur = mid;
      var b = el.main.querySelector('.mk[data-id="' + mid + '"]'); if (b) b.classList.add('cur');
      return b;
    }
    function closeMenu() { if (el.pop) { el.pop.remove(); el.pop = null; } }
    function place(pop, rect) {
      document.body.appendChild(pop);
      var w = pop.offsetWidth, hgt = pop.offsetHeight;
      var x = Math.min(Math.max(8, rect.left), window.innerWidth - w - 8);
      var y = rect.bottom + 6; if (y + hgt > window.innerHeight - 8) y = Math.max(8, rect.top - hgt - 6);
      pop.style.left = x + 'px'; pop.style.top = y + 'px';
    }
    function sameAs(m) {
      return allMarks().filter(function (x) {
        return x.m.id !== m.id && x.m.kind === m.kind && x.m.orig === m.orig && x.m.sugg === m.sugg && x.m.guess === m.guess && stateOf(x.m) === 'pending';
      });
    }
    function openMenu(btn, focusFree) {
      closeMenu();
      var f = findMark(btn.getAttribute('data-id')); if (!f) return;
      var m = f.m, p = f.p, d = S.marks[m.id];
      var opts = [];
      if (m.kind === 'manual') opts.push({ k: 'free', label: '改成' });
      else if (m.kind === 'uncertain') {
        if (m.guess) opts.push({ k: 'guess', label: '推測', v: m.guess });
        opts.push({ k: 'orig', label: '原文', v: m.orig || '（空白）' });
        opts.push({ k: 'free', label: '自由輸入' });
      } else {
        opts.push({ k: 'suggest', label: m.kind === 'delete' ? '刪除' : m.kind === 'unify' ? '統一為' : m.kind === 'insert' ? '補上' : '修正', v: m.sugg || '（刪除這段）' });
        opts.push({ k: 'orig', label: m.kind === 'insert' ? '不補' : '原文', v: m.orig || '（不補字）' });
        opts.push({ k: 'free', label: '自由輸入' });
      }
      var sel = m.kind === 'manual' ? 'free' : (d ? d.choice : opts[0].k);
      var input = h('input', { type: 'text', 'aria-label': '自由輸入', value: m.kind === 'manual' ? m.value : (d && d.choice === 'free' ? d.value : (m.kind === 'uncertain' ? (m.guess || m.orig) : (m.sugg || m.orig))) });
      var list = h('div', { role: 'radiogroup', 'aria-label': '選擇寫法' });
      var rows = opts.map(function (o, i) {
        var r = h('div', { class: 'opt' + (o.k === sel ? ' sel' : ''), role: 'radio', 'aria-checked': String(o.k === sel), tabindex: '-1', 'data-k': o.k, onclick: function () { pick(o.k); if (o.k !== 'free') apply(); } },
          h('span', { class: 'k', text: String(i + 1) }), h('span', { text: o.label + '：' }), o.k === 'free' ? input : h('span', { class: 'v', text: o.v }));
        list.appendChild(r); return r;
      });
      function pick(k) { sel = k; rows.forEach(function (r) { var on = r.getAttribute('data-k') === k; r.classList.toggle('sel', on); r.setAttribute('aria-checked', String(on)); }); if (k === 'free') input.focus(); }
      input.addEventListener('focus', function () { if (sel !== 'free') pick('free'); });
      var same = m.kind !== 'manual' ? sameAs(m) : [];
      var sameBox = same.length ? h('input', { type: 'checkbox', id: 'same-cb' }) : null;
      if (sameBox && m.kind !== 'uncertain') sameBox.checked = true;
      var err = h('p', { class: 'muted', role: 'alert' });
      function apply() {
        if (S.readonly) { closeMenu(); flash('這個分頁是唯讀'); return; }
        var dec;
        if (sel === 'free') {
          var v = input.value;
          if (BAD_VALUE.test(v)) { err.textContent = '不能輸入 { } 或 [? 這些標記符號，也不能換行'; return; }
          if (m.kind === 'manual') { if (v === m.orig) delManual(m.manual); else if (v !== m.value) editManual(m.manual, v); closeMenu(); next(); return; }
          dec = { choice: 'free', value: v };
        } else dec = { choice: sel };
        var items = [{ id: m.id, p: p.i, dec: dec }];
        if (sameBox && sameBox.checked) same.forEach(function (x) { items.push({ id: x.m.id, p: x.p.i, dec: dec }); });
        decide(items); closeMenu(); next();
      }
      var acts = h('div', { class: 'acts' });
      if (m.kind === 'manual') acts.appendChild(h('button', { class: 'btn warn', type: 'button', disabled: S.readonly, onclick: function () { delManual(m.manual); closeMenu(); } }, '刪除這個修改（回到原文）'));
      else if (d) acts.appendChild(h('button', { class: 'btn', type: 'button', disabled: S.readonly, onclick: function () { decide([{ id: m.id, p: p.i, dec: null }]); closeMenu(); } }, '改回未處理'));
      if (el.audio) acts.appendChild(h('button', { class: 'btn', type: 'button', onclick: function () { el.audio.currentTime = secOf(p.time); el.audio.play().catch(function () { /* 再按一次 */ }); } }, '▶ 播放這段'));
      acts.appendChild(h('button', { class: 'btn', type: 'button', onclick: function () { closeMenu(); btn.focus(); } }, '取消'));
      acts.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: apply, disabled: S.readonly }, '套用（Enter）'));
      var pop = h('div', { class: 'pop', role: 'dialog', 'aria-label': KIND_LABEL[m.kind] + '標記' },
        h('h3', null, h('span', { text: KIND_LABEL[m.kind] }), h('span', { class: 'chip ' + STATE_CHIP[stateOf(m)], text: STATE_LABEL[stateOf(m)] })),
        h('div', { class: 'ctx', text: '[' + p.time + '] ' + p.speaker + (m.kind === 'unify' ? '　同一個名詞全文用同一種寫法' : m.kind === 'uncertain' ? '　聽不清或不確定，請回聽後選擇' : '') }),
        list, sameBox ? h('label', { class: 'same', 'for': 'same-cb' }, sameBox, '同樣的標記還有 ' + same.length + ' 處未處理，一起套用') : null, err,
        S.readonly ? h('p', { class: 'note-off', text: '這個分頁是唯讀，不能修改。' }) : null, acts);
      pop.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(); btn.focus(); }
        else if (e.key === 'Enter') { e.preventDefault(); apply(); }
        else if (/^[1-3]$/.test(e.key) && e.target !== input) { var o = opts[+e.key - 1]; if (o) { e.preventDefault(); pick(o.k); } }
      });
      el.pop = pop;
      place(pop, btn.getBoundingClientRect());
      if (focusFree || m.kind === 'manual') { pick('free'); input.select(); } else (rows.filter(function (r) { return r.classList.contains('sel'); })[0] || rows[0]).focus();
    }

    // ---- 選取文字直接修改（人工修改）
    function selInfo() {
      var s = window.getSelection();
      if (!s || s.isCollapsed || !s.rangeCount) return null;
      var r = s.getRangeAt(0);
      var a = r.startContainer.parentElement, b = r.endContainer.parentElement;
      if (!a || !b || !el.main.contains(a)) return null;
      if (a !== b || !a.classList.contains('tx')) return { bad: true, rect: r.getBoundingClientRect() };
      var base = +a.getAttribute('data-s'), pi = +a.getAttribute('data-p');
      var st = base + r.startOffset, en = base + r.endOffset;
      var p = S.paraBy[pi];
      return { p: p, start: st, end: en, text: p.raw.slice(st, en), rect: r.getBoundingClientRect() };
    }
    function onSelect() {
      if (el.tool) { el.tool.remove(); el.tool = null; }
      if (S.readonly) return;
      var si = selInfo();
      if (!si) return;
      var t = si.bad ? h('div', { class: 'pop seltool', role: 'status', text: '選取範圍跨到標記了：請先處理標記，或分兩次選。' })
        : h('button', { class: 'btn primary seltool', type: 'button', onmousedown: function (e) { e.preventDefault(); }, onclick: function () { manualMenu(si); } }, '✎ 修改選取文字（E）');
      el.tool = t;
      document.body.appendChild(t);
      t.style.left = Math.max(8, Math.min(si.rect.left, window.innerWidth - 300)) + 'px';
      t.style.top = Math.max(8, si.rect.top - 40) + 'px';
      if (si.bad) setTimeout(function () { if (el.tool === t) { t.remove(); el.tool = null; } }, 2500);
    }
    function manualMenu(si) {
      if (el.tool) { el.tool.remove(); el.tool = null; }
      closeMenu();
      var input = h('input', { type: 'text', value: si.text, 'aria-label': '改成' });
      var err = h('p', { class: 'muted', role: 'alert' });
      function apply() {
        var v = input.value;
        if (v === si.text) { closeMenu(); return; }
        if (BAD_VALUE.test(v)) { err.textContent = '不能輸入 { } 或 [? 這些標記符號，也不能換行'; return; }
        var overlap = S.manual.some(function (u) { return u.para === si.p.i && si.start < u.end && u.start < si.end; });
        if (overlap) { err.textContent = '這段文字已經改過了：請點開那個人工修改再改'; return; }
        var u = { id: 'u' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6), para: si.p.i, start: si.start, end: si.end, orig: si.text, value: v };
        addManual(u); closeMenu(); window.getSelection().removeAllRanges(); setCur(u.id);
      }
      var pop = h('div', { class: 'pop', role: 'dialog', 'aria-label': '修改選取文字' },
        h('h3', { text: '修改選取文字' }), h('div', { class: 'ctx', text: '[' + si.p.time + '] ' + si.p.speaker + '　原文「' + si.text + '」' }),
        h('div', { class: 'opt sel' }, h('span', { text: '改成：' }), input), err,
        h('p', { class: 'muted', text: '改過的地方會變成「人工修改」標記，可以再點開修改或刪除。要在兩字之間補字：選取旁邊的一個字，改成「該字＋補字」。' }),
        h('div', { class: 'acts' }, h('button', { class: 'btn', type: 'button', onclick: closeMenu }, '取消'), h('button', { class: 'btn primary', type: 'button', onclick: apply }, '套用（Enter）')));
      pop.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); apply(); } else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeMenu(); } });
      el.pop = pop; place(pop, si.rect); input.focus(); input.select();
    }

    // ---- 鍵盤
    function pendingBtns() { return Array.prototype.slice.call(el.main.querySelectorAll('.para:not(.hidden) .mk.s-pending')); }
    function next(back) {
      var bs = pendingBtns(); if (!bs.length) { flash('沒有未處理的標記了'); return; }
      var all = Array.prototype.slice.call(el.main.querySelectorAll('.mk[data-id]'));
      var ci = all.findIndex(function (b) { return b.getAttribute('data-id') === S.cur; });
      var target;
      if (!back) target = bs.filter(function (b) { return all.indexOf(b) > ci; })[0] || bs[0];
      else { var prev = bs.filter(function (b) { return all.indexOf(b) < ci; }); target = prev[prev.length - 1] || bs[bs.length - 1]; }
      var b = setCur(target.getAttribute('data-id'));
      b.scrollIntoView({ block: 'center' }); b.focus({ preventScroll: true });
    }
    function goFirstPending() {
      var b = pendingBtns()[0];
      if (b) { setCur(b.getAttribute('data-id')); b.scrollIntoView({ block: 'center' }); }
    }
    function quick(choice) {
      var b = S.cur && el.main.querySelector('.mk[data-id="' + S.cur + '"]'); if (!b) return;
      var f = findMark(S.cur); if (!f || f.m.kind === 'manual') return;
      if (S.readonly) { flash('這個分頁是唯讀'); return; }
      var c = choice;
      if (c === 'suggest' && f.m.kind === 'uncertain') c = f.m.guess ? 'guess' : 'orig';
      decide([{ id: f.m.id, p: f.p.i, dec: { choice: c } }]); next();
    }
    function play() { var f = S.cur && findMark(S.cur); if (el.audio) { el.audio.currentTime = f ? secOf(f.p.time) : 0; el.audio.play().catch(function () { /* 再按一次 */ }); } }
    function onKey(e) {
      if (el.pop || document.querySelector('.modal-bg')) return;
      var tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      var k = (e.key || '').toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); if (e.shiftKey) redoAct(); else undo(); return; }
      if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); redoAct(); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (k === 'j' || k === 'n') { e.preventDefault(); next(); }
      else if (k === 'k' || k === 'p') { e.preventDefault(); next(true); }
      else if (k === 'a') { e.preventDefault(); quick('suggest'); }
      else if (k === 'r') { e.preventDefault(); quick('orig'); }
      else if (k === 'e') {
        e.preventDefault();
        var si = selInfo(); if (si && !si.bad) { if (!S.readonly) manualMenu(si); return; }
        var b = S.cur && el.main.querySelector('.mk[data-id="' + S.cur + '"]'); if (b) openMenu(b, true);
      } else if (k === 'enter' && e.target.classList && e.target.classList.contains('mk')) { e.preventDefault(); openMenu(e.target); }
      else if (k === 'enter' && S.cur) { var cb = el.main.querySelector('.mk[data-id="' + S.cur + '"]'); if (cb) { e.preventDefault(); openMenu(cb); } }
      else if (k === 'u') { e.preventDefault(); toggleFilter(); }
      else if (k === '.') { e.preventDefault(); play(); }
      else if (e.key === '?') { e.preventDefault(); help(); }
    }
    function toggleFilter() {
      S.filterPending = !S.filterPending;
      el.filter.classList.toggle('on', S.filterPending); el.filter.setAttribute('aria-pressed', String(S.filterPending));
      S.paras.forEach(function (p) { el.paraEls[p.i].classList.toggle('hidden', S.filterPending && !pendingIn(p)); });
    }
    function help() {
      var rows = [['J／N', '下一個未處理標記'], ['K／P', '上一個未處理標記'], ['Enter', '開啟目前標記的選單'], ['A', '接受建議（修正、推測、統一）並跳下一個'],
        ['R', '退回（用原文）並跳下一個'], ['E', '有選取文字時＝修改選取文字；否則＝目前標記的自由輸入'], ['1～3', '選單裡選第幾個選項'], ['Ctrl＋Z／Ctrl＋Y（⌘）', '復原／重做'],
        ['Ctrl＋S（⌘S）', '立刻儲存'], ['.', '從目前段落播放'], ['U', '只看未處理'], ['?', '這份說明'], ['Esc', '關閉選單或對話框']];
      modal('鍵盤操作', [h('table', { class: 'help' }, rows.map(function (r) { return h('tr', null, h('td', null, h('span', { class: 'kbd', text: r[0] })), h('td', { text: r[1] })); }))], [{ label: '關閉', primary: true }]);
    }

    // ---- 側欄
    function renderSide() {
      if (!el.side) return;
      clear(el.side);
      el.shell.classList.toggle('no-side', !S.side);
      if (!S.side) return;
      var tabs = h('div', { class: 'tabs', role: 'tablist' });
      [['list', '標記清單'], ['exp', '經驗整理'], ['final', '定稿'], ['log', '紀錄']].forEach(function (t) {
        tabs.appendChild(h('button', { type: 'button', role: 'tab', 'aria-selected': String(S.side === t[0]), class: S.side === t[0] ? 'on' : '', onclick: function () { openSide(t[0]); } }, t[1]));
      });
      el.side.appendChild(tabs);
      var pane = h('div', { class: 'pane', role: 'tabpanel' });
      el.side.appendChild(pane);
      if (S.side === 'list') paneList(pane);
      else if (S.side === 'exp') paneExp(pane);
      else if (S.side === 'log') paneLog(pane);
      else paneFinal(pane);
    }
    function paneList(pane) {
      var st = progress();
      pane.appendChild(h('div', { class: 'chips' }, h('span', { class: 'chip p', text: '● 未處理 ' + st.pending }), h('span', { class: 'chip a', text: '✓ 已確認 ' + st.accepted }),
        h('span', { class: 'chip e', text: '✎ 已改 ' + st.edited }), h('span', { class: 'chip r', text: '↺ 已退回 ' + st.rejected })));
      var f1 = h('div', { class: 'flt', 'aria-label': '狀態篩選' }), f2 = h('div', { class: 'flt', 'aria-label': '種類篩選' });
      [['all', '全部'], ['pending', '未處理'], ['accepted', '已確認'], ['edited', '已改'], ['rejected', '已退回']].forEach(function (x) {
        f1.appendChild(h('button', { class: 'btn' + (S.listState === x[0] ? ' on' : ''), type: 'button', 'aria-pressed': String(S.listState === x[0]), onclick: function () { S.listState = x[0]; renderSide(); } }, x[1]));
      });
      [['all', '全部種類'], ['fix', '校正'], ['uncertain', '待確認'], ['unify', '用字統一'], ['manual', '人工']].forEach(function (x) {
        f2.appendChild(h('button', { class: 'btn' + (S.listKind === x[0] ? ' on' : ''), type: 'button', 'aria-pressed': String(S.listKind === x[0]), onclick: function () { S.listKind = x[0]; renderSide(); } }, x[1]));
      });
      pane.appendChild(f1); pane.appendChild(f2);
      var ul = h('ul', { class: 'ml' });
      var n = 0;
      allMarks().forEach(function (x) {
        var s = stateOf(x.m), kd = x.m.kind === 'insert' || x.m.kind === 'delete' ? 'fix' : x.m.kind;
        if (S.listState !== 'all' && s !== S.listState) return;
        if (S.listKind !== 'all' && kd !== S.listKind) return;
        if (++n > 400) return;
        ul.appendChild(h('li', { tabindex: '0', onclick: function () { jump(x.m.id); }, onkeydown: function (e) { if (e.key === 'Enter') jump(x.m.id); } },
          h('span', { class: 'st chip ' + STATE_CHIP[s], text: ICON[s] + ' ' + STATE_LABEL[s] }),
          h('span', { text: s === 'rejected' ? (x.m.orig || '（不補字）') + '（退回：不改成「' + (x.m.sugg || '刪除') + '」）' : (x.m.orig || '（補字）') + ' → ' + (s === 'pending' ? (x.m.kind === 'uncertain' ? (x.m.guess || '?') : (x.m.sugg || '（刪除）')) : (valueOf(x.m) || '（刪除）')) }),
          h('span', { class: 'd', text: '[' + x.p.time + '] ' + KIND_LABEL[x.m.kind] })));
      });
      pane.appendChild(h('p', { class: 'muted', text: '共 ' + n + ' 處' + (n > 400 ? '（只列前 400 處，請用篩選縮小）' : '') }));
      pane.appendChild(ul);
    }
    function jump(mid) {
      var b = setCur(mid); if (!b) return;
      if (b.closest('.para').classList.contains('hidden')) toggleFilter();
      b.scrollIntoView({ block: 'center' }); b.focus({ preventScroll: true });
      if (!reduced) { b.classList.add('flash'); setTimeout(function () { b.classList.remove('flash'); }, 2600); }
    }

    // ---- 寫入動作：確認畫面與結果畫面
    function planTable(rows) {
      return h('table', { class: 'ex plan' }, h('tr', null, h('th', { text: '檔案' }), h('th', { text: '內容' }), h('th', { text: '先備份到' })),
        rows.map(function (r) {
          return h('tr', null, h('td', { class: 'mono', text: r.file }), h('td', { text: r.what || ((r.rows !== undefined ? r.rows + ' 筆' : '') + (r.edits !== undefined ? '改 ' + r.edits + ' 處' : '')) }),
            h('td', { class: 'mono why', text: r.backup || '（目前沒有這個檔，不用備份）' }));
        }));
    }
    function confirmWrite(title, intro, rows, extra, okLabel, onOk) {
      modal(title, [h('p', { text: intro }), planTable(rows)].concat(extra || []), [{ label: '取消' }, { label: okLabel, primary: true, fn: onOk }]);
    }
    function resultScreen(title, written, failed, note, target) {
      var body = [];
      if (written.length) {
        body.push(h('p', { text: '已寫入：' }));
        body.push(h('table', { class: 'ex plan' }, h('tr', null, h('th', { text: '檔案' }), h('th', { text: '結果' }), h('th', { text: '備份' })),
          written.map(function (w) {
            return h('tr', null, h('td', { class: 'mono', text: '✓ ' + w.file }), h('td', { text: w.detail || (w.rows !== undefined ? w.rows + ' 筆' : '') || (w.edits !== undefined ? '改 ' + w.edits + ' 處' : '完成') }),
              h('td', { class: 'mono why', text: w.backup || '—' }));
          })));
      }
      if (failed && failed.length) {
        body.push(h('div', { class: 'warn-box' }, h('p', { text: '沒有完成的部分（上面列的已經寫入；下面的沒有寫入）：' }),
          h('ul', { class: 'files' }, failed.map(function (f) { return h('li', null, h('span', { class: 'mono', text: '✕ ' + f.file }), '：' + f.reason); }))));
      }
      if (note) body.push(h('p', { class: 'muted', text: note }));
      modal(title, body, [{ label: '開啟資料夾', fn: function () { reveal(target || 'folder'); }, keep: true }, { label: '關閉', primary: true }]);
    }
    function failScreen(title, r) {
      var msg = why(r);
      if (!/^沒有寫入任何檔案/.test(msg)) msg = '沒有寫入任何檔案。原因：' + msg;
      modal(title, [h('div', { class: 'warn-box', text: msg })], [{ label: '關閉', primary: true }]);
    }
    function reveal(target) { api('POST', '/api/doc/' + id + '/reveal', { tab: S.tab, target: target }).then(function (r) { flash(r.ok ? '已在檔案總管開啟' : '開不起來：' + why(r)); }); }
    function readonlyNote(pane) { if (S.readonly) pane.appendChild(h('p', { class: 'note-off', text: '這個分頁是唯讀：可以看，不能匯入、定稿或同步。' })); }

    function paneExp(pane) {
      pane.appendChild(h('p', { class: 'muted', text: '從這份稿的校稿結果整理出來的「原文 → 正確寫法」。勾選的項目匯入固定錯誤對照表（corrections.tsv）與詞表（glossary.txt），下次轉寫時生效；匯入前先備份，可以復原。' }));
      readonlyNote(pane);
      var box = h('div', null, h('p', { text: '整理中…' }));
      pane.appendChild(box);
      flushThen(function () {
        api('GET', '/api/doc/' + id + '/experience').then(function (r) {
          clear(box);
          if (!r.ok) { box.appendChild(h('p', { text: '整理失敗：' + why(r) })); return; }
          var ex = r.data, cbs = [], gcbs = [];
          box.appendChild(h('h3', { text: '對照表建議（' + ex.corrections.length + '）' }));
          if (!ex.corrections.length) box.appendChild(h('p', { class: 'muted', text: '還沒有改過寫法的地方。' }));
          else {
            // 側欄只有 380px：說明放在詞對下方（不另開一欄），詞對只在箭頭兩側斷行
            var t = h('table', { class: 'ex' }, h('tr', null, h('th', { text: '' }), h('th', { text: '原文 → 正確寫法／說明' }), h('th', { text: '次數' })));
            ex.corrections.forEach(function (c) {
              var cb = h('input', { type: 'checkbox', 'aria-label': c.wrong + ' 改成 ' + (c.right || '（刪除）'), disabled: !c.importable || S.readonly });
              cb.checked = c.checked && c.importable; cbs.push({ cb: cb, c: c });
              t.appendChild(h('tr', null, h('td', null, cb), h('td', null, h('div', { class: 'pair', text: c.wrong + ' → ' + (c.right || '（刪除）') }),
                h('div', { class: 'why', text: c.kind + '｜' + c.source.join('、') }), h('div', { class: 'why', text: c.why.length ? c.why.join('；') : '符合固定錯誤條件（預設勾選）' })),
                h('td', { text: c.count + '／' + c.total })));
            });
            box.appendChild(t);
            box.appendChild(h('p', { class: 'note-off', text: '預設勾選：原文至少 2 字、不是刪除、每處都改成同一個寫法、本場出現 ' + ex.min_count + ' 次以上、不在對照表與詞表、不是 OpenCC 回復表或一般英文單字。' }));
          }
          box.appendChild(h('h3', { text: '詞表建議（' + ex.glossary.length + '）' }));
          if (!ex.glossary.length) box.appendChild(h('p', { class: 'muted', text: '沒有新的名詞。' }));
          else {
            var g = h('table', { class: 'ex' }, h('tr', null, h('th', { text: '' }), h('th', { text: '名詞' }), h('th', { text: '來源' }), h('th', { text: '說明' })));
            ex.glossary.forEach(function (x) {
              var cb = h('input', { type: 'checkbox', 'aria-label': x.term, disabled: S.readonly }); cb.checked = x.checked; gcbs.push({ cb: cb, g: x });
              g.appendChild(h('tr', null, h('td', null, cb), h('td', { text: x.term }), h('td', { class: 'why', text: x.from + ' ×' + x.count }), h('td', { class: 'why', text: x.why.join('；') || '寫法有特徵（預設勾選）' })));
            });
            box.appendChild(g);
          }
          function picked() {
            return { tab: S.tab, corrections: cbs.filter(function (x) { return x.cb.checked; }).map(function (x) { return { wrong: x.c.wrong, right: x.c.right }; }),
              glossary: gcbs.filter(function (x) { return x.cb.checked; }).map(function (x) { return x.g.term; }) };
          }
          var last = ex.imports[ex.imports.length - 1];
          box.appendChild(h('div', { class: 'acts', style: 'display:flex;gap:8px;margin-top:12px;flex-wrap:wrap' },
            h('button', { class: 'btn primary', type: 'button', disabled: S.readonly, onclick: function () {
              var body = picked(); body.dry_run = true;
              api('POST', '/api/doc/' + id + '/experience/import', body).then(function (pv) {
                if (!pv.ok) { failScreen('不能匯入', pv); return; }
                confirmWrite('匯入對照表與詞表？', '會寫入下面的檔案（加在檔尾，不改原有內容），寫入前先備份：', pv.data.plan,
                  [h('p', { class: 'muted', text: '對照表：' + (pv.data.corrections.map(function (x) { return x[0] + '→' + x[1]; }).join('、') || '（無）') }),
                    pv.data.glossary.length ? h('p', { class: 'muted', text: '詞表：' + pv.data.glossary.join('、') }) : null,
                    pv.data.skipped.length ? h('p', { class: 'muted', text: '略過（同一原文只寫第一組）：' + pv.data.skipped.map(function (x) { return x[0] + '→' + x[1]; }).join('、') }) : null,
                    h('p', { class: 'muted', text: '$MMH＝meeting-minutes-pro 的資料夾。匯入後可以按「復原上次匯入」還原。' })],
                  '匯入（先備份）', function () {
                    api('POST', '/api/doc/' + id + '/experience/import', picked()).then(function (rr) {
                      if (!rr.ok && rr.status !== 207) { failScreen('匯入失敗', rr); return; }
                      resultScreen(rr.status === 207 ? '匯入部分完成' : '✓ 已匯入對照表與詞表', rr.data.written, rr.data.failed, '下次轉寫時生效。要撤銷可按「復原上次匯入」。', 'mmh');
                      renderSide();
                    });
                  });
              });
            } }, '匯入勾選的項目…'),
            h('button', { class: 'btn', type: 'button', disabled: S.readonly || !last, onclick: function () {
              api('POST', '/api/doc/' + id + '/experience/undo', { tab: S.tab, dry_run: true }).then(function (pv) {
                if (!pv.ok) { failScreen('不能復原', pv); return; }
                confirmWrite('復原上次匯入？', '用匯入前的備份還原下面的檔案（' + ymdhm(last.at) + ' 匯入的 ' + last.corrections + ' 筆對照表、' + last.glossary + ' 個詞）：',
                  pv.data.plan, null, '復原', function () {
                    api('POST', '/api/doc/' + id + '/experience/undo', { tab: S.tab }).then(function (rr) {
                      if (!rr.ok) { failScreen('不能復原', rr); return; }
                      resultScreen('✓ 已復原上次匯入', rr.data.written, rr.data.failed, null, 'mmh');
                      renderSide();
                    });
                  });
              });
            } }, '復原上次匯入')));
        });
      });
    }
    function paneFinal(pane) {
      var st = progress();
      pane.appendChild(h('p', { text: '定稿是按下「定稿…」才做：在輸出資料夾產生 transcript.final.md（定稿逐字稿）與 transcript.final.srt（定稿字幕）。原本的 transcript.md、transcript.corrected.md 不會改。' }));
      readonlyNote(pane);
      pane.appendChild(h('div', { class: 'chips' }, h('span', { class: 'chip p', text: '● 未處理 ' + st.pending }), h('span', { class: 'chip a', text: '✓ ' + st.accepted }),
        h('span', { class: 'chip e', text: '✎ ' + st.edited }), h('span', { class: 'chip r', text: '↺ ' + st.rejected })));
      var allow = h('input', { type: 'checkbox', id: 'allow-p' });
      if (st.pending) pane.appendChild(h('div', { class: 'warn-box' }, h('p', { text: '還有 ' + st.pending + ' 處未處理。仍要定稿時：校正、用字統一照建議；待確認寫成「原文〔?推測〕」，字幕用原文。' }),
        h('label', { 'for': 'allow-p' }, allow, ' 仍要定稿')));
      var res = h('div');
      pane.appendChild(h('button', { class: 'btn primary', type: 'button', disabled: S.readonly, onclick: function () {
        flushThen(function () {
          api('POST', '/api/doc/' + id + '/finalize', { tab: S.tab, dry_run: true }).then(function (pv) {
            if (!pv.ok) { failScreen('不能定稿', pv); return; }
            if (pv.data.pending && !allow.checked) { info('還有未處理的標記', '還有 ' + pv.data.pending + ' 處未處理：先處理，或勾「仍要定稿」。'); return; }
            confirmWrite('定稿？', '會在輸出資料夾寫入下面的檔案（已有的先改名備份）。不會改 ' + pv.data.unchanged.join('、') + '。', pv.data.plan,
              [h('p', { class: 'muted', text: '已處理 ' + pv.data.progress.done + '／' + pv.data.progress.total + ' 處' + (pv.data.pending ? '；未處理 ' + pv.data.pending + ' 處照「仍要定稿」的規則寫' : '') + '。' }),
                pv.data.srt_note ? h('p', { class: 'muted', text: pv.data.srt_note }) : null],
              '定稿', function () {
                api('POST', '/api/doc/' + id + '/finalize', { tab: S.tab, allow_pending: allow.checked }).then(function (r) {
                  if (!r.ok && r.status !== 207) { failScreen('定稿失敗', r); return; }
                  resultScreen(r.data.failed.length ? '定稿部分完成' : '✓ 已定稿', r.data.written, r.data.failed, '檔案在這份稿的輸出資料夾。', 'folder');
                  S.data.files['transcript.final.md'] = true;
                  clear(res); finalDone(res, r.data);
                });
              });
          });
        });
      } }, '定稿…'));
      pane.appendChild(res);
      if (S.data.files['transcript.final.md']) redoBlock(res);
    }
    function finalDone(res, d) {
      res.appendChild(h('div', { class: 'ok-box' }, h('h4', { text: d.failed.length ? '定稿部分完成' : '✓ 已定稿' }),
        h('ul', { class: 'files' }, d.written.map(function (w) { return h('li', null, h('span', { class: 'mono', text: w.file }), '（' + w.detail + (w.backup ? '；舊檔備份 ' + w.backup : '') + '）'); }))));
      if (d.sync_preview.length) {
        var n = noun();
        res.appendChild(h('h3', { text: '名詞寫法同步到' + n }));
        res.appendChild(h('p', { class: 'muted', text: '校稿確認的寫法，在' + n + '裡還是舊寫法的地方。勾選後按「同步…」，確認後才改（先備份），網頁版一起重新產生；不會改其他內容。' }));
        var t = h('table', { class: 'ex' }, h('tr', null, h('th', { text: '' }), h('th', { text: '舊寫法 → 新寫法' }), h('th', { text: '處數' }), h('th', { text: '檔案' })));
        var cbs = [];
        d.sync_preview.forEach(function (x) {
          var cb = h('input', { type: 'checkbox', 'aria-label': x.wrong + ' 改成 ' + x.right }); cb.checked = true; cbs.push({ cb: cb, x: x });
          t.appendChild(h('tr', null, h('td', null, cb), h('td', { class: 'pair', text: x.wrong + ' → ' + x.right }), h('td', { text: String(x.count) }), h('td', { class: 'why', text: x.file })));
        });
        res.appendChild(t);
        res.appendChild(h('button', { class: 'btn', type: 'button', style: 'margin-top:8px', disabled: S.readonly, onclick: function () {
          var want = cbs.filter(function (c) { return c.cb.checked; }).map(function (c) { return c.x.wrong; });
          api('POST', '/api/doc/' + id + '/sync', { tab: S.tab, wrong: want, dry_run: true }).then(function (pv) {
            if (!pv.ok) { failScreen('不能同步', pv); return; }
            confirmWrite('同步名詞寫法？', '會改寫下面的檔案（先改名備份），有網頁版的一起重新產生：',
              pv.data.plan.map(function (x) { return { file: x.file, edits: x.edits, backup: x.backup }; }).concat(pv.data.plan.filter(function (x) { return x.html; }).map(function (x) { return { file: x.html, what: '網頁版（重新產生）', backup: '（由 .md 重新產生，不另備份）' }; })),
              null, '同步（先備份）', function () {
                api('POST', '/api/doc/' + id + '/sync', { tab: S.tab, wrong: want }).then(function (r) {
                  if (!r.ok && r.status !== 207) { failScreen('同步失敗', r); return; }
                  resultScreen(r.status === 207 ? '名詞同步部分完成' : '✓ 已同步名詞寫法', r.data.written, r.data.failed, null, 'folder');
                });
              });
          });
        } }, '同步勾選的寫法…'));
      }
      redoBlock(res);
    }
    function redoBlock(res) {
      if (res.querySelector('.redo-block')) return;
      var n = noun(), rd = S.data.redo || {};
      var blk = h('div', { class: 'redo-block' });
      res.appendChild(blk);
      blk.appendChild(h('h3', { text: '用定稿重做' + n + '（選用、要花費）' }));
      blk.appendChild(h('p', { class: 'muted', text: '會呼叫模型用 transcript.final.md 重新整理' + n + '，要花費。按了會先顯示供應商與費用估算，確認後才做；完成後網頁版一起重新產生，舊的先改名備份。' }));
      if (!rd.available) blk.appendChild(h('p', { class: 'note-off', text: '目前不能用：' + rd.reason + '。' }));
      var jres = h('div');
      blk.appendChild(h('button', { class: 'btn warn', type: 'button', disabled: !rd.available || S.readonly, title: rd.available ? '' : rd.reason, onclick: function () {
        api('POST', '/api/doc/' + id + '/redo', { tab: S.tab, dry_run: true }).then(function (pv) {
          if (!pv.ok) { failScreen('不能重做', pv); return; }
          var e = pv.data.estimate || {};
          var cost = (e.usd_low !== undefined ? '約 US$' + e.usd_low + '～' + e.usd_high : '（沒有提供估算）');
          confirmWrite('重做' + n + '？（要花費）', '會用 transcript.final.md 重新整理，寫入下面的檔案（舊的先改名備份）：', pv.data.plan,
            [h('div', { class: 'warn-box', text: '供應商：' + (e.provider || '—') + ' ' + (e.model || '') + (e.channel ? '（' + e.channel + '）' : '') + '；費用估算：' + cost }),
              h('p', { class: 'muted', text: '在背景執行，可以繼續校稿；完成後會跳出結果。' })],
            '重做（要花費）', function () {
              api('POST', '/api/doc/' + id + '/redo', { tab: S.tab }).then(function (r) {
                clear(jres);
                if (!r.ok) { failScreen('不能開始重做', r); return; }
                watchJob(jres);
              });
            });
        });
      } }, '重做' + n + '…（要花費）'));
      blk.appendChild(jres);
      if (rd.job && rd.job.status === 'running') watchJob(jres);
    }
    function watchJob(jres) {
      clear(jres);
      jres.appendChild(h('p', { role: 'status', text: '整理中…（可以繼續做別的事；完成後會跳出結果）' }));
      var iv = setInterval(function () {
        api('GET', '/api/doc/' + id + '/job').then(function (j) {
          if (!j.ok || !j.data || j.data.status === 'running') return;
          clearInterval(iv); clear(jres);
          var d = j.data, n = noun();
          var cost = d.cost_usd !== null && d.cost_usd !== undefined ? '實際費用 US$' + d.cost_usd : '實際費用見 meeting-minutes-pro 的執行 log';
          if (d.status === 'ok') {
            jres.appendChild(h('div', { class: 'ok-box', text: '✓ 已重做 ' + d.file + '（' + cost + '）' }));
            resultScreen(d.failed.length ? '重做' + n + '部分完成' : '✓ 已重做' + n, d.written, d.failed, cost + '。', 'folder');
          } else {
            jres.appendChild(h('div', { class: 'warn-box', text: '重做沒有完成：' + ((d.failed[0] || {}).reason || '原因不明') }));
            resultScreen('重做' + n + '沒有完成', d.written, d.failed, null, 'folder');
          }
          S.data.redo.interrupted = false; banners();
        });
      }, 1000);
    }
    // ---- 操作紀錄：時間、動作、檔名；不記逐字稿內容
    function paneLog(pane) {
      pane.appendChild(h('p', { class: 'muted', text: '這份稿的寫入動作。只記時間、動作、檔名與筆數，不記逐字稿內容；自動暫存不逐筆列出（最後一次見頂端的「已儲存」）。' }));
      var box = h('div', null, h('p', { text: '讀取中…' }));
      pane.appendChild(box);
      api('GET', '/api/doc/' + id + '/log').then(function (r) {
        clear(box);
        if (!r.ok) { box.appendChild(h('p', { text: '讀不到紀錄：' + why(r) })); return; }
        box.appendChild(h('p', { text: '上次儲存：' + (r.data.saved_at ? r.data.saved_at.replace('T', ' ').slice(0, 19) : '還沒有') + '（版本 ' + r.data.rev + '）' }));
        var ul = h('ul', { class: 'ml log' });
        r.data.log.slice().reverse().forEach(function (x) {
          ul.appendChild(h('li', null, h('span', { class: 'mono st', text: x.at.replace('T', ' ').slice(5, 16) }), h('span', { text: x.action + (x.note ? '（' + x.note + '）' : '') }),
            h('span', { class: 'd mono', text: (x.files || []).join('、') })));
        });
        box.appendChild(ul);
      });
    }
  }

  // ---------------------------------------------------------------- 路由
  var m = location.pathname.match(/^\/d\/([0-9a-f]{12})$/);
  if (m) docView(m[1], /[?&]attach=1/.test(location.search));
  else home();
})();
