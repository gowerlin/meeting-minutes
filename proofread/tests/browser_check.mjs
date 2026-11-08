// 瀏覽器實測（Playwright＋本機 Chrome／Edge）：外部請求 0、CSP 違規 0、寫入回饋（存檔狀態列四態、手動儲存、未存離開、
// 定稿與匯入的確認／結果畫面、接續提示、操作紀錄）、復原／重做、播放器、長稿效能。截圖與結果寫到 tests/_out/（不進版控）。
// 〔1.1.2〕浮動影片視窗：合成影片（materials.py --video，要 ffmpeg）在四種視窗的版面、三種狀態、拖曳與調整大小、記住狀態、同步。
//
//   NODE_PATH="$(npm root -g)" node browser_check.mjs
//
// 全部在暫存區的副本與假 $MMH 上跑；一次性登入網址只在記憶體裡（啟動器寫的暫存檔讀完就刪），截圖裡沒有網址列。
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const { chromium } = createRequire(path.join(process.env.NODE_PATH || HERE, 'noop.js'))('playwright')
const PY = process.env.PYTHON || 'python'
const PYEXE = execFileSync(PY, ['-c', 'import sys;print(sys.executable)']).toString().trim()
// 〔1.1.0〕本工具與 Pro 的位置由 locate.py 決定（開發 repo 與公開 repo 都能跑）。「重做會議記錄」停用的畫面要 Pro 2.2.x，
// 所以從最新的 Pro 複製一份假的 2.2.0（materials.py --fake-pro；只改版號，auto_minutes.py 換成假的）
const LOC = execFileSync(PY, ['-B', '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import locate; print(locate.APP); print(locate.PRO_SCRIPTS)', HERE])
  .toString().trim().split(/\r?\n/)
const APP = LOC[0]
const REAL_PRO = LOC[1]
let PRO = REAL_PRO
const OUT = path.join(HERE, '_out')
const SHOTS = path.join(OUT, 'screenshots')
fs.mkdirSync(SHOTS, { recursive: true })

const cases = []
let VIDEO_SKIP = null
const videoLayout = []        // 〔1.1.2〕四種視窗的量測表（寫進 browser.json）
function rec (name, ok, detail = '') {
  cases.push({ group: '瀏覽器', case: name, result: ok ? 'PASS' : 'FAIL', detail })
  console.log((ok ? 'PASS ' : 'FAIL ') + `[瀏覽器] ${name}` + (detail ? `：${detail}` : ''))
}

function prep () {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'mmproof-browser-'))
  execFileSync(PY, ['-B', path.join(HERE, 'materials.py'), path.join(work, 'demo')], { env: envFor(work) })
  execFileSync(PY, ['-B', path.join(HERE, 'materials.py'), '--long', path.join(work, 'long')], { env: envFor(work) })
  // 〔1.1.2〕合成影片（V1 1920×1080、V2 1280×720；測試時才產生，不進版控）。沒有 ffmpeg 時影片的情境略過並寫明
  try { execFileSync(PY, ['-B', path.join(HERE, 'materials.py'), '--video', path.join(work, 'video')], { env: envFor(work), stdio: 'pipe' }) } catch (e) { VIDEO_SKIP = String(e.stderr || e).trim().split(/\r?\n/).pop() }
  PRO = path.join(work, 'fake-pro-2.2.0')
  execFileSync(PY, ['-B', path.join(HERE, 'materials.py'), '--fake-pro', REAL_PRO, PRO, '2.2.0'], { env: envFor(work) })
  const home = path.join(work, 'home')
  fs.mkdirSync(home)
  fs.writeFileSync(path.join(home, 'config.json'), '{"runtime_version": "2.2.0"}')
  fs.writeFileSync(path.join(home, 'corrections.tsv'), '# 測試用假檔\n酷伯內蒂斯\tKubernetes\t示範\n')
  fs.writeFileSync(path.join(home, 'glossary.txt'), '# 測試用假詞表\n星河物流\n')
  return { work, home }
}
function envFor (work) {
  return { ...process.env, PYTHONDONTWRITEBYTECODE: '1', MMPROOF_NO_REVEAL: '1', MEETING_MINUTES_PRO_HOME: path.join(work, 'home'),
    MMPROOF_PRO_SCRIPTS: PRO, MMPROOF_PRO_PYTHON: PYEXE, PYTHONUTF8: '1' }
}
function launch (work, paths, extra = []) {
  const uf = path.join(os.tmpdir(), `mmproof-url-${process.pid}-${Date.now()}.txt`)
  execFileSync(PY, ['-B', path.join(APP, 'mmproof_launcher.py'), '--home', path.join(work, 'home'), '--no-browser', '--url-file', uf,
    '--idle', '60', ...extra, ...paths], { env: envFor(work) })
  const urls = fs.readFileSync(uf, 'utf8').split('\n').filter(Boolean)
  fs.unlinkSync(uf)
  return urls
}
function shutdown (work) {
  try { execFileSync(PY, ['-B', path.join(APP, 'mmproof_launcher.py'), '--home', path.join(work, 'home'), '--shutdown'], { env: envFor(work) }) } catch (e) { /* 已結束 */ }
}

const net = { total: 0, external: [], csp: [], errors: [], expected: [], simulating: false }
function watch (page) {
  page.on('request', r => {
    net.total++
    const u = r.url()
    if (!/^http:\/\/127\.0\.0\.1:\d+\//.test(u) && !u.startsWith('blob:') && !u.startsWith('data:')) net.external.push(u)
  })
  page.on('console', m => {
    if (m.type() !== 'error') return
    const t = m.text().slice(0, 200)
    if (net.simulating && /status of 500|net::ERR_FAILED/.test(t)) net.expected.push(t)   // 模擬的儲存失敗與斷線
    else (/Content Security Policy/i.test(t) ? net.csp : net.errors).push(t)
  })
  page.on('pageerror', e => net.errors.push(String(e).slice(0, 200)))
}
const TOPBAR = { x: 0, y: 0, width: 1440, height: 56 }
async function shot (page, name, clip) {
  await page.waitForTimeout(200)
  await page.screenshot({ path: path.join(SHOTS, name), ...(clip ? { clip } : {}) })
}
async function selectText (page, text) {
  await page.evaluate((t) => {
    const span = [...document.querySelectorAll('.tx')].find(s => s.textContent.includes(t))
    const node = span.firstChild
    const i = node.textContent.indexOf(t)
    const r = document.createRange()
    r.setStart(node, i); r.setEnd(node, i + t.length)
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r)
    span.scrollIntoView({ block: 'center' })
    span.closest('.main').dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  }, text)
}
const saveText = page => page.$eval('.save', e => e.textContent)
const stateOf = (page, id) => page.$eval(`.mk[data-id="${id}"]`, e => [...e.classList].find(c => c.startsWith('s-')))
const exists = p => fs.existsSync(p)
// 間距（相鄰區塊不得相貼）：元素下緣到下一個相鄰元素上緣的距離（px）；頂端列實際排成幾行（浮動提示不算）
const gapAfter = (page, sel) => page.$eval(sel, e => e.nextElementSibling.getBoundingClientRect().top - e.getBoundingClientRect().bottom)
const optGaps = page => page.$$eval('.pop .opt', es => es.slice(1).map((e, i) => e.getBoundingClientRect().top - es[i].getBoundingClientRect().bottom))
const topRows = page => page.$eval('.top', t => {
  const rs = [...t.children].filter(e => !e.classList.contains('errbar') && !e.classList.contains('toast') && e.getBoundingClientRect().width > 0)
    .map(e => e.getBoundingClientRect()).sort((a, b) => a.top - b.top)
  let n = 0, bottom = -1
  for (const r of rs) { if (r.top >= bottom - 2) { n++; bottom = r.bottom } else bottom = Math.max(bottom, r.bottom) }
  return n
})

// ---------------------------------------------------------------- 〔1.1.2〕浮動影片視窗（規格 1.1.2 §2）
const VKEY = 'mmproof-video'
const near = (a, b, tol = 1.5) => Math.abs(a - b) <= tol
function vgeo (page) {
  return page.evaluate(() => {
    const R = e => { if (!e) return null; const r = e.getBoundingClientRect(); return { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height } }
    const win = document.querySelector('.vwin'), tab = document.querySelector('.vtab'), shell = document.querySelector('.shell')
    const vid = document.querySelector('.vwin video'), au = document.querySelector('.dock audio')
    return {
      vw: document.documentElement.clientWidth, vh: window.innerHeight,
      scrollW: Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
      rows: getComputedStyle(shell).gridTemplateRows, mainH: document.querySelector('.main').getBoundingClientRect().height,
      top: R(document.querySelector('.top')), dock: R(document.querySelector('.dock')),
      dockVideo: document.querySelectorAll('.dock video').length, audios: document.querySelectorAll('audio').length, videos: document.querySelectorAll('video').length,
      win: win && { hidden: win.hidden, max: win.classList.contains('s-max'), rect: R(win), body: R(win.querySelector('.vbody')) },
      tab: tab && { hidden: tab.hidden, rect: R(tab) },
      vid: vid && { paused: vid.paused, t: vid.currentTime, rate: vid.playbackRate, muted: vid.muted, ready: vid.readyState, w: vid.videoWidth, h: vid.videoHeight },
      au: au && { paused: au.paused, t: au.currentTime, rate: au.playbackRate },
      stored: (() => { try { return localStorage.getItem('mmproof-video') } catch (e) { return 'ERR' } })()
    }
  })
}
// 影片視窗（或標籤）在可放區域內：離頂列下緣、播放列上緣、左右邊至少 gap px
function inArea (g, rect, gap = 8) {
  return rect.top >= g.top.bottom + gap - 0.5 && rect.bottom <= g.dock.top - gap + 0.5 && rect.left >= gap - 0.5 && rect.right <= g.vw - gap + 0.5
}
const fmtRect = r => r ? `${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}×${Math.round(r.height)}` : '—'

async function videoChecks (ctx, work, port, d1id) {
  if (VIDEO_SKIP) { console.log(`SKIP [瀏覽器] 〔1.1.2〕浮動影片視窗：${VIDEO_SKIP}`); return }
  const VF = n => path.join(work, 'video', `${n}-demo_minutes`)
  const vu = launch(work, [VF('V1'), VF('V2')])
  const idOf = u => decodeURIComponent(u).match(/\/d\/([0-9a-f]{12})/)[1]
  const v1 = idOf(vu[0]), v2 = idOf(vu[1])
  const base = `http://127.0.0.1:${port}`
  const pg = await ctx.newPage()
  watch(pg)
  const clearStore = () => pg.evaluate(k => { try { localStorage.removeItem(k) } catch (e) { /* 沒有 */ } }, VKEY).catch(() => {})
  const waitMeta = () => pg.waitForFunction(() => { const v = document.querySelector('.vwin video'); return v && v.readyState >= 1 }, null, { timeout: 8000 })
  async function open (id, w, hgt, video = true) {
    await pg.setViewportSize({ width: w, height: hgt })
    await pg.goto(`${base}/d/${id}`)
    await pg.waitForSelector('.mk')
    if (video) await waitMeta()
    await pg.waitForTimeout(250)
  }

  // ---- 四種視窗：錄音（D1）與影片（V1 1920×1080）各開一次
  for (const [w, hgt] of [[1440, 900], [1707, 735], [1280, 720], [375, 812]]) {
    await open(d1id, w, hgt, false)
    const a = await vgeo(pg)
    await clearStore()
    await open(v1, w, hgt)
    const g = await vgeo(pg)
    let gs = g
    await shot(pg, `video-${w}x${hgt}-dark.png`)
    if (g.win.hidden) { await pg.click('.vtab'); await pg.waitForTimeout(200); gs = await vgeo(pg); await shot(pg, `video-${w}x${hgt}-dark-restored.png`) }
    const narrow = w <= 760
    const row = { viewport: `${w}×${hgt}`, rows_video: g.rows, rows_audio: a.rows, main_h: Math.round(g.mainH), scroll_w: g.scrollW, vw: g.vw,
      dock_h_video: g.dock.height, dock_h_audio: a.dock.height, default_state: g.win.hidden ? 'min' : (g.win.max ? 'max' : 'small'),
      window: fmtRect(gs.win.rect), tab: g.tab.hidden ? '—' : fmtRect(g.tab.rect),
      gap_top: Math.round(gs.win.rect.top - g.top.bottom), gap_dock: Math.round(gs.dock.top - gs.win.rect.bottom), gap_right: Math.round(gs.vw - gs.win.rect.right) }
    videoLayout.push(row)
    const ok = g.mainH > 0 && a.mainH > 0 && g.scrollW <= g.vw && gs.scrollW <= gs.vw && near(g.dock.height, a.dock.height, 0.5) && g.dockVideo === 0 &&
      inArea(gs, gs.win.rect) && (!narrow || (g.win.hidden && !g.tab.hidden && inArea(g, g.tab.rect))) && (narrow || !g.win.hidden)
    rec(`〔1.1.2〕${w}×${hgt}：正文列 > 0、沒有橫向捲動、播放列與錄音同高、影片視窗不蓋頂列與播放列${narrow ? '（窄畫面預設最小化標籤）' : ''}`, ok,
      `grid rows「${g.rows}」、正文 ${row.main_h} px、scrollWidth ${g.scrollW}／${g.vw}、播放列 ${g.dock.height}／錄音 ${a.dock.height} px、預設 ${row.default_state}、視窗 ${row.window}（離頂列 ${row.gap_top}、離播放列 ${row.gap_dock}、離右邊 ${row.gap_right} px）`)
  }
  {
    const a = await (async () => { await open(d1id, 1440, 900, false); return pg.evaluate(() => ({ win: !!document.querySelector('.vwin, .vtab'), audio: document.querySelectorAll('.dock audio').length, video: document.querySelectorAll('video').length })) })()
    rec('〔1.1.2〕錄音檔：沒有影片視窗與標籤，播放列只有 <audio>（同 1.1.1）', !a.win && a.audio === 1 && a.video === 0, JSON.stringify(a))
  }

  // ---- 預設小視窗（1440×900）、同步
  await clearStore()
  await open(v1, 1440, 900)
  let g = await vgeo(pg)
  const s0 = g.win.rect
  const bodyRatio = g.win.body.width / g.win.body.height
  rec('〔1.1.2〕預設小視窗：右下角、影片 320×180（保持 16:9）、離邊與播放列 12 px', !g.win.hidden && !g.win.max && near(g.win.body.width, 320) && near(g.win.body.height, 180) &&
    near(g.vw - s0.right, 12) && near(g.dock.top - s0.bottom, 12) && g.vid.w === 1920 && g.vid.h === 1080,
    `視窗 ${fmtRect(s0)}、畫面 ${g.win.body.width.toFixed(0)}×${g.win.body.height.toFixed(0)}（${bodyRatio.toFixed(3)}）、影片 ${g.vid.w}×${g.vid.h}`)
  await pg.evaluate(() => { document.querySelector('.dock audio').muted = true })
  await pg.click('#p-4 .tc')
  await pg.waitForTimeout(1500)
  const gp = await vgeo(pg)
  await pg.evaluate(() => { document.querySelector('.dock audio').playbackRate = 1.5 })
  await pg.waitForTimeout(300)
  const gr = await vgeo(pg)
  await pg.evaluate(() => { document.querySelector('.dock audio').currentTime = 100 })
  await pg.waitForTimeout(1000)
  const gk = await vgeo(pg)
  await pg.evaluate(() => { document.querySelector('.dock audio').playbackRate = 1 })
  rec('〔1.1.2〕同步：點時間碼播放、跳轉、播放速度，影片跟著播放列；聲音只有播放列一個（影片靜音）',
    !gp.au.paused && !gp.vid.paused && gp.au.t >= 44 && Math.abs(gp.vid.t - gp.au.t) < 0.5 && gr.vid.rate === 1.5 && Math.abs(gk.vid.t - gk.au.t) < 0.5 && gk.au.t >= 100 &&
    gp.vid.muted && gp.audios === 1 && gp.videos === 1,
    `播放 音 ${gp.au.t.toFixed(2)}／影 ${gp.vid.t.toFixed(2)}；速度 ${gr.au.rate}／${gr.vid.rate}；跳到 100 秒後 音 ${gk.au.t.toFixed(2)}／影 ${gk.vid.t.toFixed(2)}；audio ${gp.audios}、video ${gp.videos}（muted ${gp.vid.muted}）`)
  await shot(pg, 'video-small-1440-dark.png')

  // ---- 最大化：頂列與播放列之間、保持比例置中；標記選單與對話框在上面；Esc 先關選單，再按才還原
  await pg.click('.vwin .vbtn[data-act="max"]')
  await pg.waitForTimeout(200)
  g = await vgeo(pg)
  const mr = g.win.rect, aw = g.vw - 24, ah = g.dock.top - g.top.bottom - 24
  const fill = near(mr.width, aw, 2) || near(mr.height, ah, 2)
  const centered = near(mr.left - 12, g.vw - 12 - mr.right, 2) && near(mr.top - g.top.bottom - 12, g.dock.top - 12 - mr.bottom, 2)
  await shot(pg, 'video-max-1440-dark.png')
  rec('〔1.1.2〕最大化：放大到頂列與播放列之間（扣 12 px 間距）、保持比例置中；按鈕改成「還原」', g.win.max && inArea(g, mr, 11.5) && fill && centered &&
    near(g.win.body.width / g.win.body.height, 16 / 9, 0.02) && await pg.$eval('.vwin .vbtn[data-act="max"]', b => b.getAttribute('aria-label') === '還原成小視窗' && b.getAttribute('aria-pressed') === 'true'),
    `視窗 ${fmtRect(mr)}；區域 ${aw}×${ah.toFixed(0)}`)
  await pg.evaluate(() => document.activeElement && document.activeElement.blur())
  await pg.keyboard.press('Enter')
  await pg.waitForSelector('.pop')
  const popTop = await pg.$eval('.pop', p => { const r = p.getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!(e && e.closest('.pop')) })
  await shot(pg, 'video-max-menu-1440-dark.png')
  await pg.keyboard.press('Escape')
  const afterEsc1 = await vgeo(pg)
  const popGone = !(await pg.$('.pop'))
  await pg.evaluate(() => document.activeElement && document.activeElement.blur())
  await pg.keyboard.press('?')
  await pg.waitForSelector('.modal')
  const modalTop = await pg.$eval('.modal', m => { const r = m.getBoundingClientRect(); const e = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!(e && e.closest('.modal')) })
  const helpTxt = await pg.$eval('.modal', m => m.textContent)
  await pg.keyboard.press('Escape')
  const afterEsc2 = await vgeo(pg)
  await pg.keyboard.press('Escape')
  const afterEsc3 = await vgeo(pg)
  rec('〔1.1.2〕最大化時標記選單與對話框在影片上面；Esc 先關選單（對話框），再按一次才還原成原本的小視窗位置與大小',
    popTop && modalTop && popGone && afterEsc1.win.max && afterEsc2.win.max && !afterEsc3.win.max && near(afterEsc3.win.rect.left, s0.left) && near(afterEsc3.win.rect.top, s0.top) &&
    near(afterEsc3.win.rect.width, s0.width) && /影片最大化時還原成小視窗/.test(helpTxt),
    `選單最上層 ${popTop}、對話框最上層 ${modalTop}；Esc 後 ${afterEsc1.win.max}／${afterEsc2.win.max}／${afterEsc3.win.max}；還原 ${fmtRect(afterEsc3.win.rect)}`)
  await pg.click('.vwin .vbtn[data-act="max"]')
  await pg.click('.vwin .vbtn[data-act="max"]')
  const twice = await vgeo(pg)
  rec('〔1.1.2〕最大化按鈕再按一次：回到原本的小視窗', !twice.win.max && near(twice.win.rect.left, s0.left) && near(twice.win.rect.top, s0.top), fmtRect(twice.win.rect))

  // ---- 最小化：右下標籤、聲音照常；點一下還原
  await pg.evaluate(() => { const a = document.querySelector('.dock audio'); if (a.paused) a.play() })
  await pg.click('.vwin .vbtn[data-act="min"]')
  await pg.waitForTimeout(400)
  g = await vgeo(pg)
  await shot(pg, 'video-min-1440-dark.png')
  const tr = g.tab.rect
  const minOk = g.win.hidden && !g.tab.hidden && !g.au.paused && g.vid.paused && inArea(g, tr, 11.5) && near(g.vw - tr.right, 12) && near(g.dock.top - tr.bottom, 12) &&
    /▶ 影片/.test(await pg.$eval('.vtab', b => b.textContent)) && await pg.evaluate(() => document.activeElement === document.querySelector('.vtab'))
  await pg.click('.vtab')
  await pg.waitForTimeout(500)
  const back = await vgeo(pg)
  rec('〔1.1.2〕最小化：收成右下「▶ 影片」標籤（離播放列 12 px）、聲音照常播放；點一下還原、影片接著播', minOk && !back.win.hidden && back.tab.hidden &&
    near(back.win.rect.left, s0.left) && !back.vid.paused && Math.abs(back.vid.t - back.au.t) < 0.5,
    `標籤 ${fmtRect(tr)}、聲音 ${g.au.paused ? '停' : '播放中'}、影片 ${g.vid.paused ? '暫停' : '播放'}；還原 ${fmtRect(back.win.rect)}、影 ${back.vid.t.toFixed(2)}／音 ${back.au.t.toFixed(2)}`)
  await pg.evaluate(() => document.querySelector('.dock audio').pause())

  // ---- 拖曳：移動；拖出去會收回可視範圍；調整大小（比例、最小、最大）
  const dragBy = async (sel, dx, dy, ox = 0, oy = 0) => {
    const p0 = await pg.$eval(sel, (e, o) => { const r = e.getBoundingClientRect(); return { x: r.left + (o[0] || r.width / 2), y: r.top + (o[1] || r.height / 2) } }, [ox, oy])
    await pg.mouse.move(p0.x, p0.y); await pg.mouse.down(); await pg.mouse.move(p0.x + dx, p0.y + dy, { steps: 6 }); await pg.mouse.up()
    await pg.waitForTimeout(100)
    return (await vgeo(pg))
  }
  const m1 = await dragBy('.vwin .vt', -300, -200)
  const m2 = await dragBy('.vwin .vt', -5000, -5000)
  const m3 = await dragBy('.vwin .vt', 5000, 5000)
  rec('〔1.1.2〕拖曳標題列移動；拖到外面會停在可視範圍內（離頂列與左邊 12 px）', near(m1.win.rect.left, s0.left - 300) && near(m1.win.rect.top, s0.top - 200) &&
    near(m2.win.rect.left, 12) && near(m2.win.rect.top, m2.top.bottom + 12) && near(m3.win.rect.right, s0.right) && near(m3.win.rect.bottom, s0.bottom) && inArea(m2, m2.win.rect, 11.5),
    `移動 ${fmtRect(m1.win.rect)}；拖到左上外 ${fmtRect(m2.win.rect)}；拖到右下外 ${fmtRect(m3.win.rect)}`)
  const z1 = await dragBy('.vwin .vgrip', -160, 0, 4, 4)
  const z2 = await dragBy('.vwin .vgrip', -3000, -3000, 4, 4)
  const z3 = await dragBy('.vwin .vgrip', 3000, 3000, 4, 4)
  const z4 = await dragBy('.vwin .vgrip', -200, 0, 4, 4)
  await shot(pg, 'video-resized-1440-dark.png')
  rec('〔1.1.2〕從左上角調整大小：右下角固定、保持比例；最小 200 px 寬、最大 960 px 寬',
    near(z1.win.body.width, 480) && near(z1.win.rect.right, s0.right) && near(z1.win.rect.bottom, s0.bottom) && near(z1.win.body.width / z1.win.body.height, 16 / 9, 0.02) &&
    near(z2.win.body.width, 960) && near(z3.win.body.width, 200) && near(z4.win.body.width, 400),
    `+160 → ${z1.win.body.width.toFixed(0)}×${z1.win.body.height.toFixed(0)}；最大 ${z2.win.body.width.toFixed(0)}；最小 ${z3.win.body.width.toFixed(0)}；再拉 ${z4.win.body.width.toFixed(0)}`)

  // ---- 瀏覽器視窗縮小 → 收回可視範圍；再放大 → 回到原位
  const before = z4.win.rect
  await pg.setViewportSize({ width: 700, height: 460 })
  await pg.waitForTimeout(300)
  const sm = await vgeo(pg)
  await shot(pg, 'video-shrunk-700x460-dark.png')
  await pg.setViewportSize({ width: 1440, height: 900 })
  await pg.waitForTimeout(300)
  const bg = await vgeo(pg)
  rec('〔1.1.2〕瀏覽器視窗縮小（700×460）時收回可視範圍、沒有橫向捲動；放大後回到原本位置', inArea(sm, sm.win.rect, 11.5) && sm.scrollW <= sm.vw &&
    near(bg.win.rect.left, before.left) && near(bg.win.rect.top, before.top) && near(bg.win.rect.width, before.width),
    `縮小後 ${fmtRect(sm.win.rect)}（頂列下緣 ${sm.top.bottom.toFixed(0)}、播放列上緣 ${sm.dock.top.toFixed(0)}）；放大後 ${fmtRect(bg.win.rect)}`)

  // ---- 鍵盤與 aria：標題列方向鍵移動、Shift＋方向鍵調整大小、Enter 最大化、Esc 還原；按鈕有 title 與 aria-label
  await pg.focus('.vwin .vbar')
  await pg.keyboard.press('ArrowLeft'); await pg.keyboard.press('ArrowLeft'); await pg.keyboard.press('ArrowUp')
  const k1 = await vgeo(pg)
  await pg.keyboard.press('Shift+ArrowLeft')
  const k2 = await vgeo(pg)
  await pg.keyboard.press('Enter')
  const k3 = await vgeo(pg)
  await pg.keyboard.press('Escape')
  const k4 = await vgeo(pg)
  const aria = await pg.$$eval('.vwin .vbtn, .vtab', bs => bs.every(b => b.title && b.getAttribute('aria-label') && b.tagName === 'BUTTON'))
  const curNotMoved = await pg.$eval('.mk.cur', e => e.dataset.id)
  rec('〔1.1.2〕鍵盤：標題列方向鍵移動 16 px、Shift＋方向鍵放大、Enter 最大化、Esc 還原；不觸發校稿快捷鍵；按鈕都有 title 與 aria-label',
    near(k1.win.rect.left, before.left - 32) && near(k1.win.rect.top, before.top - 16) && near(k2.win.body.width, 432) && k3.win.max && !k4.win.max && aria && !(await pg.$('.pop')),
    `移動後 ${fmtRect(k1.win.rect)}、放大後畫面寬 ${k2.win.body.width.toFixed(0)}、Enter ${k3.win.max}、Esc ${k4.win.max}；目前標記 ${curNotMoved}`)

  // ---- 記住狀態：重新載入（同一份與另一份稿）
  const kept = k4.win.rect
  await pg.reload(); await pg.waitForSelector('.mk'); await waitMeta(); await pg.waitForTimeout(200)
  const r1 = await vgeo(pg)
  await pg.click('.vwin .vbtn[data-act="min"]')
  await pg.reload(); await pg.waitForSelector('.mk'); await pg.waitForTimeout(400)
  const r2 = await vgeo(pg)
  await pg.click('.vtab')
  await pg.click('.vwin .vbtn[data-act="max"]')
  await open(v2, 1440, 900)
  const r3 = await vgeo(pg)
  await shot(pg, 'video-v2-1280x720-max-1440-dark.png')
  await pg.click('.vwin .vbtn[data-act="max"]')
  const r4 = await vgeo(pg)
  rec('〔1.1.2〕記住狀態：重新載入後位置與大小相同；最小化與最大化也記住；開另一份稿（V2 1280×720）沿用，還原回同一個小視窗',
    near(r1.win.rect.left, kept.left) && near(r1.win.rect.top, kept.top) && near(r1.win.rect.width, kept.width) && r2.win.hidden && !r2.tab.hidden &&
    r3.win.max && r3.vid.w === 1280 && near(r4.win.rect.left, kept.left) && near(r4.win.rect.width, kept.width) && /"state":"small"/.test(r4.stored),
    `重新載入 ${fmtRect(r1.win.rect)}；最小化 → ${r2.win.hidden ? 'min' : '?'}；V2 ${r3.vid.w}×${r3.vid.h} ${r3.win.max ? 'max' : '?'} → 還原 ${fmtRect(r4.win.rect)}；${r4.stored}`)

  // ---- 記住的位置在可視範圍外、內容壞掉、localStorage 不能用 → 收回或用預設，頁面照常
  await pg.evaluate(k => localStorage.setItem(k, JSON.stringify({ state: 'small', rest: 'small', w: 5000, r: 99999, b: 99999 })), VKEY)
  await open(v1, 1280, 720)
  const o1 = await vgeo(pg)
  await pg.evaluate(k => localStorage.setItem(k, '{壞掉'), VKEY)
  await open(v1, 1440, 900)
  const o2 = await vgeo(pg)
  const pb = await ctx.newPage()
  watch(pb)
  await pb.addInitScript(() => { Object.defineProperty(window, 'localStorage', { configurable: true, get () { throw new Error('blocked（測試）') } }) })
  await pb.setViewportSize({ width: 1440, height: 900 })
  await pb.goto(`${base}/d/${v1}`)
  await pb.waitForSelector('.mk')
  await pb.waitForFunction(() => { const v = document.querySelector('.vwin video'); return v && v.readyState >= 1 }, null, { timeout: 8000 })
  await pb.click('.vwin .vbtn[data-act="max"]')
  const o3 = await vgeo(pb)
  await pb.close()
  rec('〔1.1.2〕記住的位置在可視範圍外 → 收回；內容壞掉或 localStorage 不能用 → 用預設（小視窗、右下），按鈕照常',
    inArea(o1, o1.win.rect, 11.5) && !o2.win.hidden && near(o2.win.body.width, 320) && near(o2.vw - o2.win.rect.right, 12) && o3.win.max && o3.stored === 'ERR',
    `超出 → ${fmtRect(o1.win.rect)}；壞掉 → ${fmtRect(o2.win.rect)}；不能用 → ${o3.win.max ? '最大化可用' : '?'}`)

  // ---- 間距、深淺色截圖
  await clearStore()
  await open(v1, 1440, 900)
  const sp = await pg.evaluate(() => {
    const r = s => document.querySelector(s).getBoundingClientRect()
    const vt = r('.vwin .vt'), bmin = r('.vwin .vbtn[data-act="min"]'), bmax = r('.vwin .vbtn[data-act="max"]'), grip = r('.vwin .vgrip'), bar = r('.vwin .vbar')
    return { textToMin: bmin.left - vt.right, minToMax: bmax.left - bmin.right, maxToEdge: bar.right - bmax.right, gripToText: vt.left - grip.right }
  })
  g = await vgeo(pg)
  rec('〔1.1.2〕間距：標題文字與按鈕 ≥ 4 px、兩個按鈕之間 ≥ 4 px、按鈕與視窗邊 ≥ 2 px、調整大小角與文字 ≥ 4 px；小視窗離播放列與右邊 12 px',
    sp.textToMin >= 4 && sp.minToMax >= 4 && sp.maxToEdge >= 2 && sp.gripToText >= 4 && near(g.dock.top - g.win.rect.bottom, 12) && near(g.vw - g.win.rect.right, 12),
    `文字→按鈕 ${sp.textToMin.toFixed(1)}、按鈕之間 ${sp.minToMax.toFixed(1)}、按鈕→邊 ${sp.maxToEdge.toFixed(1)}、角→文字 ${sp.gripToText.toFixed(1)} px`)
  await pg.click('.top button[title="切換深色／淺色"]')
  const light = await pg.evaluate(() => ({ theme: document.documentElement.getAttribute('data-theme'), bar: getComputedStyle(document.querySelector('.vbar')).backgroundColor,
    win: getComputedStyle(document.querySelector('.vwin')).backgroundColor }))
  await shot(pg, 'video-small-1440-light.png')
  await pg.click('.vwin .vbtn[data-act="max"]'); await shot(pg, 'video-max-1440-light.png')
  await pg.click('.vwin .vbtn[data-act="min"]'); await shot(pg, 'video-min-1440-light.png')
  await pg.click('.vtab'); await pg.click('.vwin .vbtn[data-act="max"]')
  await pg.click('.top button[title="切換深色／淺色"]')
  const dark = await pg.evaluate(() => ({ bar: getComputedStyle(document.querySelector('.vbar')).backgroundColor, win: getComputedStyle(document.querySelector('.vwin')).backgroundColor }))
  rec('〔1.1.2〕深色與淺色：影片視窗的標題列與外框跟著主題變（截圖小、大、最小化各一張）', light.theme === 'light' && light.bar !== dark.bar && light.win !== dark.win,
    `淺色 標題列 ${light.bar}、外框 ${light.win}；深色 ${dark.bar}、${dark.win}`)
  await clearStore()
  await pg.close()
}

async function main () {
  const { work, home } = prep()
  const D = n => path.join(work, 'demo', `${n}-demo_minutes`)
  const browser = await chromium.launch({ channel: 'chrome', headless: true })
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'zh-TW' })
  const page = await ctx.newPage()
  watch(page)
  const urls = launch(work, [D('D1'), D('D2')])

  // ---- 開稿：捲到第一個未處理、存檔狀態列「尚未修改」
  await page.goto(urls[0])
  await page.waitForSelector('.mk')
  rec('開稿：焦點在第一個未處理的標記、狀態列「尚未修改」', await page.$eval('.mk.cur', e => e.dataset.id) === 'm0-0' && (await saveText(page)) === '尚未修改')

  // ---- 鍵盤、選單、人工修改；自動暫存 → 已儲存
  await page.keyboard.press('a')                                    // 星荷→星河
  await page.keyboard.press('a')                                    // kafka→Kafka
  await page.click('.mk[data-id="m0-2"]'); await page.waitForSelector('.pop')
  await page.click('.pop .opt[data-k="orig"]')                     // 全線→權限 退回
  await selectText(page, '密等')
  await page.click('.seltool')
  await page.fill('.pop input[type=text]', '冪等')
  await page.keyboard.press('Enter')
  const dirty0 = await saveText(page)
  await page.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✓ 已儲存'), null, { timeout: 5000 })
  rec('做決定 →「● 有未儲存的變更」→ 1.2 秒後自動暫存「✓ 已儲存 HH:MM:SS」', dirty0 === '● 有未儲存的變更' && /^✓ 已儲存 \d\d:\d\d:\d\d$/.test(await saveText(page)), await saveText(page))
  rec('三種操作的狀態：已確認、已退回、人工修改', await stateOf(page, 'm0-0') === 's-accepted' && await stateOf(page, 'm0-2') === 's-rejected' &&
    await page.$$eval('.mk.k-manual', es => es.length) === 1)
  await page.evaluate(() => document.querySelector('.main').scrollTo(0, 0))
  await shot(page, 'proofread-1440-dark.png')
  const gaps = { listChipsToFilter: await gapAfter(page, '.pane .chips'), topRowsSaved: await topRows(page) }
  await shot(page, 'save-1-saved.png', TOPBAR)

  // ---- 存檔狀態列：儲存中（延遲）、儲存失敗（500＋原因＋重試）、恢復
  await page.route('**/session', async r => { await new Promise(res => setTimeout(res, 2500)); await r.continue() })
  await page.keyboard.press('j'); await page.keyboard.press('a')
  await shot(page, 'save-2-dirty.png', TOPBAR)
  await page.waitForTimeout(1500)
  const saving = await saveText(page)
  await shot(page, 'save-3-saving.png', TOPBAR)
  await page.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✓'), null, { timeout: 8000 })
  await page.unroute('**/session')
  rec('儲存中…（請求送出、還沒回應）', saving === '儲存中…', saving)
  net.simulating = true
  await page.route('**/session', r => r.fulfill({ status: 500, contentType: 'application/json',
    body: JSON.stringify({ error: 'write', message: '寫不進 .proofread/session.json（PermissionError：模擬）' }) }))
  await page.keyboard.press('a')
  await page.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✕'), null, { timeout: 5000 })
  const errbar = await page.$eval('.errbar', e => !e.hidden && e.textContent)
  await shot(page, 'save-4-error.png', TOPBAR)
  await shot(page, 'save-error-1440-dark.png')
  gaps.topRowsError = await topRows(page)
  rec('儲存失敗：狀態列＋紅色提示（原因、沒有遺失、5 秒重試、立刻重試）', /寫不進 \.proofread\/session\.json/.test(errbar) && /每 5 秒自動重試/.test(errbar) && /立刻重試/.test(errbar), errbar)
  await page.unroute('**/session')
  await page.click('.errbar button')
  await page.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✓'), null, { timeout: 5000 })
  rec('立刻重試成功 → 回到「已儲存」、紅色提示消失', await page.$eval('.errbar', e => e.hidden))
  await page.route('**/session', r => r.abort())
  await page.keyboard.press('a')
  await page.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✕'), null, { timeout: 5000 })
  const offline = await page.$eval('.errbar', e => e.textContent)
  await page.unroute('**/session')
  rec('連不上服務的原因用白話寫出', /連不上會議記錄校稿/.test(offline), offline.slice(0, 60))
  await page.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✓'), null, { timeout: 8000 })
  rec('失敗後每 5 秒自動重試，成功後回到已儲存', (await saveText(page)).startsWith('✓ 已儲存'))
  net.simulating = false

  // ---- 手動儲存：Ctrl+S（在輸入框裡也有效）與按鈕
  await page.keyboard.press('Control+s')
  await page.waitForFunction(() => /已儲存 \d\d:\d\d:\d\d（已處理 \d+／\d+ 處）/.test(document.querySelector('.toast').textContent), null, { timeout: 4000 })
  const toast = await page.$eval('.toast', e => e.textContent)
  await shot(page, 'save-5-manual.png', TOPBAR)
  await page.click('.mk[data-id="m6-0"]'); await page.waitForSelector('.pop input')
  await page.focus('.pop input')
  await page.keyboard.press('Control+s')
  await page.waitForTimeout(600)
  const toast2 = await page.$eval('.toast', e => e.textContent)
  await page.keyboard.press('Escape')
  await page.click('.savebox button')
  await page.waitForTimeout(600)
  const did = decodeURIComponent(urls[0]).match(/\/d\/([0-9a-f]{12})/)[1]
  const log1 = await page.evaluate(id => fetch(`/api/doc/${id}/log`).then(r => r.json()), did)
  rec('Ctrl＋S／⌘S 與「儲存」按鈕：浮出「已儲存 HH:MM:SS（已處理 n／N 處）」、記進操作紀錄', /已處理/.test(toast) && /已儲存/.test(toast2) &&
    log1.log.filter(x => x.action === '儲存（手動）').length >= 3, toast)

  // ---- 復原／重做：決定、一起套用、人工修改；存檔後重新整理仍可復原
  await page.click('.mk[data-id="m5-0"]'); await page.waitForSelector('.pop')
  await page.click('.pop .opt[data-k="suggest"]')                  // notebook lm → NotebookLM
  await page.evaluate(() => document.activeElement.blur())
  const s1 = await stateOf(page, 'm5-0')
  await page.keyboard.press('Control+z')
  const s2 = await stateOf(page, 'm5-0')
  await page.keyboard.press('Control+y')
  const s3 = await stateOf(page, 'm5-0')
  rec('一個決定的復原（Ctrl＋Z）與重做（Ctrl＋Y）', [s1, s2, s3].join() === 's-accepted,s-pending,s-accepted', `${s1}→${s2}→${s3}`)
  // 一起套用：瑞迪斯→Redis 有 2 處
  // 一起套用：瑞迪斯→Redis 有 2 處（m4-0、m9-0）。先把 m4-0 改回未處理，再從 m4-0 一起套用「原文」
  const ids = ['m4-0', 'm9-0']
  const states = async () => Promise.all(ids.map(i => stateOf(page, i)))
  await page.click('.mk[data-id="m4-0"]'); await page.waitForSelector('.pop')
  const resetBtn = await page.$('.pop .acts button:not(.primary)')
  if (resetBtn && /改回未處理/.test(await resetBtn.textContent())) await resetBtn.click(); else await page.keyboard.press('Escape')
  const before = await states()
  await page.click('.mk[data-id="m4-0"]'); await page.waitForSelector('.pop #same-cb')
  const sameChecked = await page.$eval('#same-cb', e => e.checked)
  await page.click('.pop .opt[data-k="orig"]')
  const both = await states()
  await page.evaluate(() => document.activeElement.blur())
  await page.keyboard.press('Control+z')
  const bothUndo = await states()
  await page.keyboard.press('Control+Shift+z')
  const bothRedo = await states()
  rec('同樣的標記一起套用（預設勾選）與一起復原、重做', sameChecked && both.join() === 's-rejected,s-rejected' && bothUndo.join() === before.join() &&
    bothRedo.join() === both.join(), `套用前 ${before}｜套用 ${both}｜復原 ${bothUndo}｜重做 ${bothRedo}`)
  await selectText(page, '退幣')
  await page.click('.seltool')
  await page.fill('.pop input[type=text]', '退避')
  await page.keyboard.press('Enter')
  const nManual = await page.$$eval('.mk.k-manual', es => es.length)
  await page.evaluate(() => document.activeElement.blur())
  await page.keyboard.press('Control+z')
  const nManualUndo = await page.$$eval('.mk.k-manual', es => es.length)
  await page.keyboard.press('Control+y')
  const nManualRedo = await page.$$eval('.mk.k-manual', es => es.length)
  rec('人工修改的復原與重做', nManual === 2 && nManualUndo === 1 && nManualRedo === 2, `${nManual}→${nManualUndo}→${nManualRedo}`)
  await page.keyboard.press('Control+s')
  await page.waitForTimeout(800)
  await page.reload()
  await page.waitForSelector('.mk')
  await page.evaluate(() => document.activeElement.blur())
  await page.keyboard.press('Control+z')
  await page.waitForTimeout(200)
  const afterReload = await page.$$eval('.mk.k-manual', es => es.length)
  rec('存檔後重新整理，仍可復原（歷史存在 session.json）', afterReload === 1, `人工修改 2 → ${afterReload}`)
  await page.keyboard.press('Control+y')
  await page.waitForTimeout(1500)

  // ---- 選單截圖、淺色
  await page.click('.mk[data-id="m6-0"]'); await page.waitForSelector('.pop')
  await shot(page, 'menu-uncertain-1440-dark.png')
  gaps.menuOptions = Math.min(...await optGaps(page))
  await page.keyboard.press('Escape')
  await page.click('.top button[title="切換深色／淺色"]')
  await shot(page, 'proofread-1440-light.png')
  await page.click('.top button[title="切換深色／淺色"]')

  // ---- 播放器：點時間碼跳到該秒播放
  await page.evaluate(() => { document.querySelector('audio').muted = true })
  await page.click('#p-4 .tc')
  await page.waitForTimeout(700)
  const player = await page.$eval('audio', a => ({ t: a.currentTime, paused: a.paused }))
  rec('點時間碼：播放器跳到該段開始播放', player.t >= 44 && player.t < 47 && !player.paused, `currentTime ${player.t.toFixed(1)}、paused ${player.paused}`)

  // ---- 全部處理 → 定稿確認畫面（不寫檔）→ 結果畫面
  for (let i = 0; i < 20; i++) await page.keyboard.press('a')
  await page.waitForTimeout(1600)
  await page.click('.top [data-side="final"]')
  await page.click('.pane .btn.primary')
  await page.waitForSelector('.modal')
  const confirmTxt = await page.$eval('.modal', e => e.textContent)
  const wroteEarly = exists(path.join(D('D1'), 'transcript.final.md'))
  await shot(page, 'final-confirm-1440-dark.png')
  rec('定稿確認畫面：問句標題、要寫的檔、不會改的檔、已處理數；按之前沒寫檔', /定稿？/.test(confirmTxt) && /transcript\.final\.md/.test(confirmTxt) &&
    /transcript\.final\.srt/.test(confirmTxt) && /不會改 transcript\.md、transcript\.corrected\.md/.test(confirmTxt) && !wroteEarly)
  await page.click('.modal .btn.primary')
  await page.waitForFunction(() => /已定稿/.test(document.querySelector('.modal h2')?.textContent || ''), null, { timeout: 8000 })
  const resultTxt = await page.$eval('.modal', e => e.textContent)
  await shot(page, 'final-result-1440-dark.png')
  rec('定稿結果畫面：實際寫入的檔、段數、條數與對時方式、開啟資料夾', /✓ transcript\.final\.md/.test(resultTxt) && /12 段/.test(resultTxt) &&
    /條；Pro subtitles\.map_corrected 對時，對應失敗 0 段/.test(resultTxt) && /開啟資料夾/.test(resultTxt) && exists(path.join(D('D1'), 'transcript.final.srt')))
  await page.click('.modal .acts button:first-child')                 // 開啟資料夾（測試模式不真的開）
  await page.waitForTimeout(400)
  const revealToast = await page.$eval('.toast', e => e.textContent)
  await page.click('.modal .btn.primary')
  rec('「開啟資料夾」有回饋', /已在檔案總管開啟/.test(revealToast), revealToast)
  await page.waitForSelector('.redo-block')
  const redo = await page.$eval('.redo-block', e => ({ text: e.textContent, disabled: e.querySelector('button').disabled }))
  await shot(page, 'final-1440-dark.png')
  rec('重做會議記錄：Pro 2.2.x 時按鈕停用並說明原因', redo.disabled && /升級 meeting-minutes-pro 到 2\.3\.0 以上就能用/.test(redo.text))
  gaps.finalChipsToButton = await gapAfter(page, '.pane .chips')
  rec('間距：相鄰區塊不相貼（徽章列與篩選列、徽章列與「定稿…」≥ 8px，選單選項之間 ≥ 4px，1440 寬頂端列一行，存檔失敗時也一行）',
    gaps.listChipsToFilter >= 8 && gaps.finalChipsToButton >= 8 && gaps.menuOptions >= 4 && gaps.topRowsSaved === 1 && gaps.topRowsError === 1,
    `徽章列→篩選列 ${gaps.listChipsToFilter.toFixed(1)} px、徽章列→定稿… ${gaps.finalChipsToButton.toFixed(1)} px、選項 ${gaps.menuOptions.toFixed(1)} px、頂端列 ${gaps.topRowsSaved}／${gaps.topRowsError} 行`)
  // 名詞同步確認
  await page.click('.pane .ex + button')
  await page.waitForSelector('.modal')
  const syncTxt = await page.$eval('.modal', e => e.textContent)
  await shot(page, 'sync-confirm-1440-dark.png')
  rec('名詞同步確認畫面：每個檔改幾處、備份檔名', /同步名詞寫法？/.test(syncTxt) && /meeting-minutes\.md/.test(syncTxt) && /\.bak\.md/.test(syncTxt))
  await page.click('.modal .acts button:first-child')

  // ---- 經驗匯入：確認畫面（dry_run，不寫檔）→ 結果畫面
  const corrBefore = fs.readFileSync(path.join(home, 'corrections.tsv'))
  await page.click('.top [data-side="exp"]')
  await page.waitForSelector('.pane table.ex')
  await shot(page, 'experience-1440-dark.png')
  const disabledConflict = await page.$$eval('.pane table.ex input:disabled', es => es.length)
  await page.click('.pane .btn.primary')
  await page.waitForSelector('.modal')
  const impTxt = await page.$eval('.modal', e => e.textContent)
  await shot(page, 'import-confirm-1440-dark.png')
  rec('匯入確認畫面（試跑）：檔、筆數、備份位置與要匯入的詞對；按之前不寫檔', /匯入對照表與詞表？/.test(impTxt) && /\$MMH\/corrections\.tsv/.test(impTxt) &&
    /\$MMH\/backups\/corrections\./.test(impTxt) && fs.readFileSync(path.join(home, 'corrections.tsv')).equals(corrBefore) && !exists(path.join(home, 'backups')))
  await page.click('.modal .btn.primary')
  await page.waitForFunction(() => /已匯入/.test(document.querySelector('.modal h2')?.textContent || ''), null, { timeout: 5000 })
  const impRes = await page.$eval('.modal', e => e.textContent)
  await shot(page, 'import-result-1440-dark.png')
  rec('匯入結果畫面：實際筆數、備份檔名、下次轉寫時生效', /✓ \$MMH\/corrections\.tsv/.test(impRes) && /\$MMH\/backups\/corrections\.\d{8}-\d{6}\.tsv/.test(impRes) &&
    /下次轉寫時生效/.test(impRes) && fs.readdirSync(path.join(home, 'backups')).some(n => n.startsWith('corrections.')), `衝突不能勾 ${disabledConflict} 項`)
  await page.click('.modal .btn.primary')

  // ---- 操作紀錄
  await page.click('.top [data-side="log"]')
  await page.waitForSelector('.pane .ml.log li')
  const logTxt = await page.$eval('.pane', e => e.textContent)
  await shot(page, 'log-1440-dark.png')
  rec('操作紀錄畫面：時間、動作、檔名，不含逐字稿文字', /定稿/.test(logTxt) && /匯入對照表與詞表/.test(logTxt) && /儲存（手動）/.test(logTxt) &&
    !/冪等|退避|星河物流倉儲/.test(logTxt))

  // ---- 未存離開：有未儲存的變更時關分頁 → beforeunload
  await page.click('.top [data-side="log"]')
  await page.evaluate(() => document.activeElement && document.activeElement.blur())
  await page.click('.mk[data-id="m0-0"]'); await page.waitForSelector('.pop')
  await page.click('.pop .opt[data-k="orig"]')
  let sawUnload = false
  page.on('dialog', async d => { if (d.type() === 'beforeunload') sawUnload = true; await d.accept() })
  await page.close({ runBeforeUnload: true })
  await new Promise(res => setTimeout(res, 1500))
  rec('有未儲存的變更時關分頁 → 瀏覽器問「確定要離開嗎？」', sawUnload)

  // ---- 接續提示、首頁、同一份再開（提示頁）
  const p2 = await ctx.newPage()
  watch(p2)
  await p2.goto(`http://127.0.0.1:${new URL(urls[0]).port}/d/${did}`)
  await p2.waitForSelector('.banner.info')
  const resume = await p2.$eval('.banner.info p', e => e.textContent)
  await shot(p2, 'resume-1440-dark.png')
  rec('接續提示：「接續上次的校稿：上次儲存 YYYY-MM-DD HH:MM、已處理 n／N 處。」', /^接續上次的校稿：上次儲存 \d{4}-\d\d-\d\d \d\d:\d\d、已處理 \d+／\d+ 處。$/.test(resume), resume)
  const att = launch(work, [D('D1')])
  const p3 = await ctx.newPage()
  watch(p3)
  await p3.goto(att[0])
  await p3.waitForSelector('.banner')
  const attTxt = await p3.$eval('.main', e => [...e.querySelectorAll('.banner p')].map(p => p.textContent).join('｜'))
  await shot(p3, 'attach-1440-dark.png')
  await p2.waitForTimeout(500)
  const flashed = await p2.$$eval('.banner.info p', es => es.some(e => /又從右鍵/.test(e.textContent)))
  rec('同一份再開：提示頁（不開第二個可編輯分頁）、原分頁收到提示', /已經在另一個分頁開啟/.test(attTxt) && (await p3.$eval('.save', e => e.textContent)) === '唯讀（這個分頁不會儲存）' && flashed)
  await p3.close()
  // ---- 〔1.1.0〕本機限定（Pro 2.4.0 的機敏會議）：D3 放標記檔 local-only.json → 頁首標示、提示列；首頁卡片標示
  fs.writeFileSync(path.join(D('D3'), 'local-only.json'), '{"local_only": true, "source": "sendto"}\n')
  const loUrl = launch(work, [D('D3')])
  const pLo = await ctx.newPage()
  watch(pLo)
  await pLo.goto(loUrl[0])
  await pLo.waitForSelector('.top .tag.lo')
  const lo = await pLo.evaluate(() => ({ tag: document.querySelector('.top .tag.lo').textContent,
    title: document.querySelector('.top .tag.lo').title,
    banner: [...document.querySelectorAll('.banner p')].map(p => p.textContent).join('｜') }))
  const loRows = await topRows(pLo)
  await shot(pLo, 'local-only-1440-dark.png', TOPBAR)
  rec('本機限定：頁首「本機限定」標示（含原因與解除方法）、提示列寫重做停用與其他照常，頂端列一行',
    lo.tag === '本機限定' && /local-only\.json/.test(lo.title) && /刪除/.test(lo.title) &&
    /本機限定：這份不送 GPT 或 Claude。人工修改、定稿、經驗匯入照常；「用定稿重做會議記錄」停用。/.test(lo.banner) && loRows === 1,
    `${lo.tag}｜${lo.banner}｜頂端列 ${loRows} 行`)
  await pLo.close()
  const homeUrl = launch(work, [], ['--home-page'])
  const p4 = await ctx.newPage()
  watch(p4)
  await p4.goto(homeUrl[0])
  await p4.waitForSelector('.card')
  const homeTxt = await p4.$eval('.home', e => e.textContent)
  await shot(p4, 'home-1440-dark.png')
  rec('首頁：開著的稿、最近的稿（上次儲存、已處理 n／N（p%））、自動結束說明', /開著的稿（\d+）/.test(homeTxt) && /上次儲存 \d{4}-\d\d-\d\d \d\d:\d\d/.test(homeTxt) &&
    /已處理 \d+／\d+（\d+%）/.test(homeTxt) && /自動結束/.test(homeTxt))
  const loCards = await p4.$$eval('.card', es => es.map(e => ({ name: e.querySelector('.name span').textContent, lo: !!e.querySelector('.tag.lo') })))
  const tagGap = await p4.$eval('.card .tag.lo', e => e.getBoundingClientRect().left - e.previousElementSibling.getBoundingClientRect().right)
  await shot(p4, 'home-local-only-1440-dark.png')
  rec('本機限定：首頁只有放了標記檔的那份標「本機限定」（標示與名稱間距 ≥ 4px）',
    loCards.some(c => c.lo) && loCards.every(c => c.lo === /^D3-/.test(c.name)) && tagGap >= 4,
    loCards.map(c => c.name + (c.lo ? '［本機限定］' : '')).join('｜') + `；間距 ${tagGap.toFixed(1)} px`)
  // 〔1.1.1〕首頁卡片的提示字依來源寫（loTag()）：標記檔、全域設定、config.json 讀不了；頁首與說明列寫出 config 讀不了的原因
  const cardTitles = async () => p4.$$eval('.card', es => es.map(e => ({ name: e.querySelector('.name span').textContent,
    title: (e.querySelector('.tag.lo') || {}).title || '' })))
  const headTag = async () => p4.$$eval('.home-head .tag.lo', es => es.map(e => ({ text: e.textContent, title: e.title })))
  const cfgPath = path.join(work, 'home', 'config.json')
  const cfgOrig = fs.readFileSync(cfgPath)
  const t0 = await cardTitles()
  const markerOnly = t0.filter(c => /^D3-/.test(c.name)).every(c => c.title === '這份不送 GPT 或 Claude（輸出資料夾有 local-only.json）')
  fs.writeFileSync(cfgPath, '{"runtime_version": "2.2.0", "privacy": {"local_only": true}}')
  await p4.reload(); await p4.waitForSelector('.card')
  const t1 = await cardTitles(); const h1 = await headTag()
  const globalOk = h1.length === 1 && h1[0].text === '本機限定（整部電腦）' &&
    t1.filter(c => !/^D3-/.test(c.name)).every(c => c.title === '這份不送 GPT 或 Claude（meeting-minutes-pro 的 config.json 設了 privacy.local_only（整部電腦））') &&
    t1.filter(c => /^D3-/.test(c.name)).every(c => /privacy\.local_only/.test(c.title) && /local-only\.json/.test(c.title))
  fs.writeFileSync(cfgPath, '{"runtime_version": "2.2.0", "privacy": {"local_only": "true"}')
  await p4.reload(); await p4.waitForSelector('.card')
  const t2 = await cardTitles(); const h2 = await headTag()
  await shot(p4, 'home-config-unreadable-1440-dark.png')
  const cuOk = h2.length === 1 && h2[0].text === '本機限定（config.json 讀不了）' && /config\.json 讀不了：不是合法的 JSON/.test(h2[0].title) &&
    t2.every(c => /config\.json 讀不了或值看不懂，為了不外送已當成本機限定（整部電腦）/.test(c.title)) &&
    t2.filter(c => /^D3-/.test(c.name)).every(c => /local-only\.json/.test(c.title)) &&
    t2.filter(c => !/^D3-/.test(c.name)).every(c => !/local-only\.json/.test(c.title))
  rec('〔1.1.1〕首頁卡片提示字依來源：標記檔「輸出資料夾有 local-only.json」、全域設定「config.json 設了 privacy.local_only」（不再誤寫 local-only.json）、config.json 讀不了；標題旁標示',
    markerOnly && globalOk && cuOk, `${t1.map(c => c.title).join('｜')}｜${h2.map(x => x.text).join('')}`)
  const pCu = await ctx.newPage()
  watch(pCu)
  await pCu.goto(`http://127.0.0.1:${new URL(urls[0]).port}/d/${decodeURIComponent(urls[1]).match(/\/d\/([0-9a-f]{12})/)[1]}?attach=1`)
  await pCu.waitForSelector('.top .tag.lo')
  const cu = await pCu.evaluate(() => ({ title: document.querySelector('.top .tag.lo').title,
    banner: [...document.querySelectorAll('.banner p')].map(p => p.textContent).join('｜') }))
  await shot(pCu, 'local-only-config-unreadable-1440-dark.png', TOPBAR)
  rec('〔1.1.1〕config.json 讀不了：頁首標示的說明寫原因與恢復方法、說明列寫「config.json 讀不了或值看不懂，為了不外送已當成本機限定」',
    /config\.json 讀不了：不是合法的 JSON/.test(cu.title) && /為了不外送，已當成本機限定/.test(cu.title) && /修好 meeting-minutes-pro 的 config\.json/.test(cu.title) &&
    /本機限定（meeting-minutes-pro 的 config\.json 讀不了或值看不懂，為了不外送已當成本機限定；/.test(cu.banner), cu.banner.slice(0, 120))
  await pCu.close()
  fs.writeFileSync(cfgPath, cfgOrig)
  await p4.close()

  // ---- 手機寬度：只讀
  const p5 = await ctx.newPage()
  watch(p5)
  await p5.setViewportSize({ width: 375, height: 800 })
  const d2id = decodeURIComponent(urls[1]).match(/\/d\/([0-9a-f]{12})/)[1]
  await p5.goto(`http://127.0.0.1:${new URL(urls[0]).port}/d/${d2id}`)
  await p5.waitForSelector('.banner')
  const narrow = await p5.$eval('.main', e => e.textContent)
  await shot(p5, 'proofread-375-dark-readonly.png')
  rec('手機寬度只能檢視（不取得編輯權）', /手機寬度只能檢視/.test(narrow) && (await p5.$eval('.save', e => e.textContent)).startsWith('唯讀'))
  await p5.close()

  // ---- 分頁標題提醒：短時間內連續提醒 3 次，閃爍時前綴只有一個、結束後回到原標題；減少動態效果時不閃爍
  const TITLE = 'D1-demo_minutes｜會議記錄校稿'
  const PREFIX = '● 請看這裡｜'
  const who = (pg, id) => pg.evaluate(i => new BroadcastChannel('mmproof').postMessage({ type: 'who', id: i }), id)
  const titles = []
  const sampler = setInterval(() => { p2.title().then(t => titles.push(t), () => {}) }, 150)
  for (let i = 0; i < 3; i++) {
    await who(p2, did)
    await p2.waitForTimeout(1000)                                    // 等第一次閃爍（標題帶前綴）之後再提醒
  }
  await p2.waitForFunction(t => {                                    // 標題連續 1.7 秒等於原標題 = 閃爍已結束
    const now = Date.now()
    if (document.title !== t) { window.__titleSince = 0; return false }
    window.__titleSince = window.__titleSince || now
    return now - window.__titleSince > 1700
  }, TITLE, { timeout: 25000, polling: 100 }).catch(() => {})
  clearInterval(sampler)
  const endTitle = await p2.title()
  const doubled = titles.filter(t => t.split(PREFIX).length > 2).length
  rec('連續提醒 3 次：閃爍時前綴只有一個、結束後標題回到原標題', endTitle === TITLE && doubled === 0 && titles.some(t => t.startsWith(PREFIX)),
    `結束「${endTitle}」；取樣 ${titles.length} 次、前綴重複 ${doubled} 次`)
  const p6 = await ctx.newPage()
  watch(p6)
  await p6.emulateMedia({ reducedMotion: 'reduce' })
  await p6.goto(`http://127.0.0.1:${new URL(urls[0]).port}/d/${d2id}`)
  await p6.waitForSelector('.mk')
  await p6.waitForFunction(() => !document.querySelector('.save').textContent.startsWith('唯讀'), null, { timeout: 5000 })
  const calmTitle = await p6.title()
  const calm = []
  await who(p6, d2id)
  for (let i = 0; i < 12; i++) { calm.push(await p6.title()); await p6.waitForTimeout(250) }
  const calmBanner = await p6.$$eval('.banner.info p', es => es.some(e => /又從右鍵/.test(e.textContent)))
  rec('減少動態效果（prefers-reduced-motion）時：只顯示提示、標題不閃爍', calmBanner && calm.every(t => t === calmTitle) && !calmTitle.includes(PREFIX),
    `標題「${calmTitle}」、3 秒內變動 ${calm.filter(t => t !== calmTitle).length} 次`)
  await p6.close()
  await p2.close()
  await videoChecks(ctx, work, new URL(urls[0]).port, did)      // 〔1.1.2〕浮動影片視窗
  shutdown(work)

  // ---- 長稿效能：Chrome 與 Edge
  const perf = {}
  for (const channel of ['chrome', 'msedge']) {
    const b = channel === 'chrome' ? browser : await chromium.launch({ channel, headless: true })
    const c = await b.newContext({ viewport: { width: 1440, height: 900 }, locale: 'zh-TW' })
    const pg = await c.newPage()
    watch(pg)
    const lu = launch(work, [path.join(work, 'long', 'LONG-demo_minutes')])
    const t0 = Date.now()
    await pg.goto(lu[0])
    await pg.waitForFunction(() => document.querySelectorAll('.para').length === 900 && document.querySelector('.mk.cur'), null, { timeout: 20000 })
    const openMs = Date.now() - t0
    const marks = await pg.$$eval('.mk', es => es.length)
    const decide = await pg.evaluate(async () => {
      const out = []
      for (let i = 0; i < 20; i++) {
        const t = performance.now()
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
        out.push(performance.now() - t)
        await new Promise(r => setTimeout(r, 30))
      }
      return { avg: out.reduce((a, b) => a + b, 0) / out.length, max: Math.max(...out) }
    })
    await pg.waitForFunction(() => document.querySelector('.save').textContent.startsWith('✓'), null, { timeout: 8000 })
    const saveMs = await pg.evaluate(() => {
      const es = performance.getEntriesByType('resource').filter(e => /\/session$/.test(e.name))
      return es.length ? Math.max(...es.map(e => e.duration)) : null
    })
    perf[channel] = { open_ms: openMs, load_js_ms: await pg.evaluate(() => window.mmproofLoadMs), decide_avg_ms: +decide.avg.toFixed(1),
      decide_max_ms: +decide.max.toFixed(1), save_ms: saveMs && +saveMs.toFixed(1), paras: 900, marks }
    rec(`長稿效能（${channel}）：開啟 < 2 秒、每次決定 < 50 ms、暫存 < 200 ms`, openMs < 2000 && decide.avg < 50 && saveMs !== null && saveMs < 200,
      `開啟 ${openMs} ms（前端渲染 ${perf[channel].load_js_ms} ms）、決定平均 ${perf[channel].decide_avg_ms} ms／最長 ${perf[channel].decide_max_ms} ms、暫存 ${perf[channel].save_ms} ms；${marks} 處標記`)
    await pg.close()
    await c.close()
    if (b !== browser) await b.close()
    shutdown(work)
  }
  await browser.close()

  rec('外部請求 0（只連 127.0.0.1）', net.external.length === 0, `共 ${net.total} 個請求，非 127.0.0.1 ${net.external.length} 個`)
  rec('CSP 違規 0、頁面錯誤 0', net.csp.length === 0 && net.errors.length === 0,
    `CSP ${net.csp.length}、錯誤 ${net.errors.length}（另有預期的模擬儲存失敗與斷線 ${net.expected.length} 筆）${net.errors.slice(0, 3).join('｜')}`)
  const pass = cases.filter(c => c.result === 'PASS').length
  fs.writeFileSync(path.join(OUT, 'browser.json'), JSON.stringify({ pass, total: cases.length, perf, requests: net.total,
    external: net.external.length, csp: net.csp.length, errors: net.errors, video_layout: videoLayout, video_skip: VIDEO_SKIP, cases }, null, 1))
  console.log(`\nbrowser ${pass}/${cases.length} PASS；截圖 ${fs.readdirSync(SHOTS).length} 張 → tests/_out/screenshots/`)
  fs.rmSync(work, { recursive: true, force: true })
  process.exit(pass === cases.length ? 0 : 1)
}
main().catch(e => { console.error(e); process.exit(2) })
