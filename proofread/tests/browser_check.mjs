// 瀏覽器實測（Playwright＋本機 Chrome／Edge）：外部請求 0、CSP 違規 0、寫入回饋（存檔狀態列四態、手動儲存、未存離開、
// 定稿與匯入的確認／結果畫面、接續提示、操作紀錄）、復原／重做、播放器、長稿效能。截圖與結果寫到 tests/_out/（不進版控）。
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
const APP = path.join(HERE, '..', 'meeting-minutes-proofread-v1.0.0', 'payload', 'app')
const PRO = process.env.MMPROOF_TEST_PRO_SCRIPTS ||
  path.join(HERE, '..', '..', 'meeting-minutes-pro-skill', 'meeting-minutes-pro-v2.2.0', 'payload', 'runtime', 'scripts')
const OUT = path.join(HERE, '_out')
const SHOTS = path.join(OUT, 'screenshots')
fs.mkdirSync(SHOTS, { recursive: true })

const cases = []
function rec (name, ok, detail = '') {
  cases.push({ group: '瀏覽器', case: name, result: ok ? 'PASS' : 'FAIL', detail })
  console.log((ok ? 'PASS ' : 'FAIL ') + `[瀏覽器] ${name}` + (detail ? `：${detail}` : ''))
}

function prep () {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), 'mmproof-browser-'))
  execFileSync(PY, ['-B', path.join(HERE, 'materials.py'), path.join(work, 'demo')], { env: envFor(work) })
  execFileSync(PY, ['-B', path.join(HERE, 'materials.py'), '--long', path.join(work, 'long')], { env: envFor(work) })
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
  const homeUrl = launch(work, [], ['--home-page'])
  const p4 = await ctx.newPage()
  watch(p4)
  await p4.goto(homeUrl[0])
  await p4.waitForSelector('.card')
  const homeTxt = await p4.$eval('.home', e => e.textContent)
  await shot(p4, 'home-1440-dark.png')
  rec('首頁：開著的稿、最近的稿（上次儲存、已處理 n／N（p%））、自動結束說明', /開著的稿（\d+）/.test(homeTxt) && /上次儲存 \d{4}-\d\d-\d\d \d\d:\d\d/.test(homeTxt) &&
    /已處理 \d+／\d+（\d+%）/.test(homeTxt) && /自動結束/.test(homeTxt))
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
    external: net.external.length, csp: net.csp.length, errors: net.errors, cases }, null, 1))
  console.log(`\nbrowser ${pass}/${cases.length} PASS；截圖 ${fs.readdirSync(SHOTS).length} 張 → tests/_out/screenshots/`)
  fs.rmSync(work, { recursive: true, force: true })
  process.exit(pass === cases.length ? 0 : 1)
}
main().catch(e => { console.error(e); process.exit(2) })
