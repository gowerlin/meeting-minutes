// vitepress-portal-layout：圖的放大檢視
//
// 文中的圖（Mermaid、figure 裡的 SVG／圖片、HTML 畫的圖、Markdown 圖片）右上角加一個「放大檢視」按鈕，開啟後是佔滿視窗的
// 檢視層（可再進入瀏覽器的真正全螢幕），可縮放、拖曳、符合畫面、100%。
//
// - 向量：SVG 以複製的節點顯示（不轉點陣、不用 CSS scale），縮放是改 SVG 的寬高，文字仍是文字；複製時把 id 加上字尾，
//   並改寫 url(#…)、href="#…"、IDREF 屬性（aria-labelledby 等）與 SVG 自帶 <style> 裡的參照，頁面上不會有重複的 id。
//   寬高同時用行內樣式（!important）設定：站點對 SVG 自己 class 寫的 width: 100%、height: auto 這類規則擋不住放大
// - 宿主裡有多個最外層 <svg>（例：依視窗寬度只顯示其中一張）時，取目前看得見的那張；都看不見才取第一張（<img> 相同）
// - 圖片：以原檔（img 的 currentSrc）顯示，100% 是原檔的像素；符合畫面時不放大超過原尺寸
// - HTML 圖（v1.1.0）：宿主沒有 <svg>／<img> 時（<figure>、data-pl-zoom 的元素），複製整個宿主節點：
//   以原本在頁面上的寬度排版，再用 CSS transform: scale() 整體縮放（排版不變；文字仍是文字節點，瀏覽器依倍率重新繪製）。
//   複製品放在一串和原本祖先相同標籤與屬性的外殼裡（display: contents，不產生方塊），所以 .vp-doc、宿主 class 的後代選擇器、
//   Vue scoped 樣式（data-v-* 屬性）都照樣套得到；複製品是 inert（不能聚焦、按不到、不觸發原元件的事件），id 照 SVG 的做法改寫
// - 檢視層是原生 <dialog>（showModal：頁面其他部分不可操作、在最上層）；焦點鎖在檢視層內，關閉後回到原按鈕
// - 開啟時的倍率（v1.1.1；v1.1.2 加小差距的規則）：頁面倍率 > 符合畫面 × 1.02 時取 min(10, 頁面倍率)，否則取符合畫面
//   ——一打開至少和頁面上一樣大，放得下就整張看得見；頁面倍率只比符合畫面大不到 2% 時取符合畫面，整張看得見
//   （不必為了最後幾 px 拖曳；圖只比頁面上小不到 2%）。
//   頁面倍率 = 圖在頁面上的顯示寬度 ÷ 它在倍率 1 時的寬度（SVG、Mermaid：顯示寬 ÷ viewBox 寬；圖片：顯示寬 ÷ 原檔寬；
//   HTML 圖以頁面寬度排版，頁面倍率 = 1）。四種內容同一條規則。圖比檢視區大時從左上開始，可拖曳、方向鍵平移看其餘部分；
//   「符合畫面」（0）仍可縮到整張看得見
// - 鍵盤：+／− 放大縮小、0 符合畫面、1 原尺寸（100%）、方向鍵平移（Shift 加大）、F 全螢幕、Esc 關閉
// - 不載入外部資源、沒有 inline script、沒有第三方函式庫（主題模組，打包進站）
//
// 哪些元素有按鈕：options.targets 的選擇器（預設 DEFAULT_TARGETS），只找 options.scope（預設 .VPContent）裡面。
//   元素本身或祖先有 data-no-zoom（或 data-pl-no-zoom）時不加；有 data-pl-zoom-manual 的元素由自己的元件放按鈕
//   （呼叫 openFigure，例：寬圖工具列）。網頁投影片等 layout: false 的頁面沒有 .VPContent，不加。
//   HTML 圖：宿主是 <figure> 或有 data-pl-zoom，裡面沒有 <svg>／<img>，也沒有 .mermaid（還在畫的 Mermaid）與
//   video、audio、iframe、canvas、object、embed（複製不出內容）。data-pl-zoom="html" 強制放大整個宿主（裡面的 SVG 只是小圖示時）。
// - 按鈕的空間：SVG 與 HTML 宿主上方保留一條（--pl-zoom-reserve，預設 44px），圖片疊在右上角；
//   data-pl-zoom-reserve（圖或祖先）讓圖片也保留，data-pl-zoom-reserve="off" 讓任何宿主都不保留。
//   保留空間的規則權重高（figure-zoom.css：html:root 前綴＋!important），站點對宿主寫 padding: 0 也蓋不掉（v1.1.1）
// - 按鈕的位置（v1.1.1）：按鈕**不放進宿主**，插在宿主後面當兄弟（宿主的父元素是 <ol>、<table> 這類不允許 <button> 子元素的
//   元素時再往外一層），絕對定位、留在原本的靜態位置，再用 transform 移到宿主的右上角。宿主的子元素完全不變：站點的
//   :first-child／:last-child／:nth-child 規則照舊，<ol>／<ul>／<table> 也不會多一個不合法的 <button> 子元素。
//   位置在宿主或其父元素大小改變（ResizeObserver）、視窗大小改變、捲動容器捲動、字型載入、頁面內容改變時重新量。
//   圖片照舊包一層 span（skill 自己的元素）、按鈕放在 span 裡
// - data-* 屬性（data-kind、data-scale、data-tx、data-ty、data-nw、data-nh、data-page-scale、data-page-w）給
//   scripts/layout-check.mjs 的 --figure-test 用；
//   宿主的 data-pl-zoom-key 與按鈕的 data-pl-zoom-for 互相對應（layout-check.mjs 用來找按鈕的宿主）

export interface FigureZoomLabels {
  open: string
  toolbar: string
  zoomIn: string
  zoomOut: string
  fit: string
  actual: string
  fullscreen: string
  exitFullscreen: string
  close: string
  stage: string
  stageRole: string
  help: string
}

export interface FigureZoomOptions {
  // 只在這個容器裡找圖（預設 .VPContent）
  scope?: string
  // 要加按鈕的元素（宿主）。宿主是 <img> 時包一層 span 放按鈕；其他宿主找裡面看得見的 <svg>，沒有再找 <img>，
  // 都沒有時（<figure> 或 data-pl-zoom）放大整個宿主（HTML 圖）
  targets?: string[]
  // 另外要略過的選擇器（data-no-zoom、data-pl-no-zoom 一律略過）
  skip?: string
  // HTML 圖的放大（v1.1.0，預設 true）；false 時與 v1.0.0 相同，只放大 SVG 與圖片
  html?: boolean
  // 圖片也在上方保留按鈕的空間（預設 false：按鈕疊在圖片右上角）；個別圖片用 data-pl-zoom-reserve
  reserveImages?: boolean
  labels?: Partial<FigureZoomLabels>
}

export const DEFAULT_TARGETS = [
  // Mermaid：vitepress-plugin-mermaid 與多數自寫元件都輸出 class="mermaid"；圖畫好（有 <svg>）才加按鈕
  '.vp-doc .mermaid',
  // <figure> 裡的 SVG 或圖片（寬圖、截圖）；兩者都沒有時放大整個 figure（HTML 圖）
  '.vp-doc figure',
  // 明確指定：任何元素加 data-pl-zoom（沒有 SVG 或圖片時放大整個元素；data-pl-zoom="html" 一律放大整個元素）
  '.vp-doc [data-pl-zoom]',
  // Markdown 圖片
  '.vp-doc img'
]

export const DEFAULT_LABELS: FigureZoomLabels = {
  open: '放大檢視',
  toolbar: '檢視工具',
  zoomIn: '放大（+）',
  zoomOut: '縮小（−）',
  fit: '符合畫面（0）',
  actual: '原尺寸 100%（1）',
  fullscreen: '全螢幕（F）',
  exitFullscreen: '離開全螢幕（F）',
  close: '關閉（Esc）',
  stage: '圖的檢視區',
  stageRole: '可縮放的圖',
  help: '滾輪或兩指縮放、拖曳平移；鍵盤 +／− 縮放、方向鍵平移、0 符合畫面、1 原尺寸、F 全螢幕、Esc 關閉。按住 Shift 拖曳可選取圖中的文字。'
}

const ALWAYS_SKIP = '[data-no-zoom], [data-pl-no-zoom], .pl-zoom-dialog, .VPHero, .VPFeatures'
const MANUAL = '[data-pl-zoom-manual]'
const LADDER = [0.1, 0.25, 0.33, 0.5, 0.67, 0.75, 1, 1.25, 1.5, 2, 3, 4, 6, 8]
const MIN_SCALE = 0.05
const MAX_SCALE = 10
// 開啟倍率的小差距門檻（v1.1.2）：頁面倍率超過符合畫面的這個倍數，才用頁面倍率開啟；否則用符合畫面（整張看得見）。
// 理由：頁面上顯示得只比「檢視區放得下的大小」大一點點時（例：1920 寬的截圖 79.0% 對 78.5%、390 寬的 HTML 圖 100% 對 99.2%），
// 用頁面倍率開啟只會讓最後幾 px 跑出檢視區、要拖曳才看得到；改用符合畫面時圖只比頁面上小不到 2%，看起來一樣大。
// 2%：實際站點量到的這類差距都在 1% 以內，留一倍的餘裕；差距比這個大時仍照頁面倍率開啟（一打開不比頁面上小）。
// 固定值，不開放設定
const PAGE_OVER_FIT = 1.02
const PAD = 16
const KEEP_VISIBLE = 48
const ZWSP = String.fromCharCode(0x200b)
// HTML 圖不放大：還在畫的 Mermaid、複製不出內容的媒體
const NOT_HTML = '.mermaid, video, audio, iframe, canvas, object, embed'
// 宿主上保留按鈕空間的 class；複製品要拿掉
const HOST_CLASSES = ['pl-zoom-host', 'pl-zoom-svg', 'pl-zoom-html', 'pl-zoom-reserve']
const RESERVE_CLASSES = ['pl-zoom-svg', 'pl-zoom-html', 'pl-zoom-reserve']
// 子元素不能是 <button> 的元素（內容模型只允許特定子元素，或本身是互動元素）：按鈕不放進去，往外一層
const NO_BUTTON_PARENT = 'ol, ul, menu, dl, table, colgroup, thead, tbody, tfoot, tr, select, datalist, optgroup, hgroup, picture, a, button, label, summary'
// 按鈕離宿主（padding box）上緣與右緣的距離，與圖片按鈕的 top／right 相同（figure-zoom.css）
const INSET = 6

type Kind = 'svg' | 'img' | 'html'

let config: Required<Omit<FigureZoomOptions, 'labels'>> & { labels: FigureZoomLabels } = {
  scope: '.VPContent',
  targets: DEFAULT_TARGETS,
  skip: '',
  html: true,
  reserveImages: false,
  labels: DEFAULT_LABELS
}
const skipSelector = () => (config.skip ? `${ALWAYS_SKIP}, ${config.skip}` : ALWAYS_SKIP)

const ICONS = {
  expand: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />',
  zoomIn: '<circle cx="11" cy="11" r="6.5" /><path d="M20.5 20.5l-4.9-4.9M11 8v6M8 11h6" />',
  zoomOut: '<circle cx="11" cy="11" r="6.5" /><path d="M20.5 20.5l-4.9-4.9M8 11h6" />',
  fit: '<rect x="4" y="5" width="16" height="14" rx="1.5" /><path d="M8 9h8v6H8z" />',
  fullscreen: '<path d="M3 8V3h5M21 8V3h-5M3 16v5h5M21 16v5h-5M8 8h8v8H8z" />',
  exitFullscreen: '<path d="M8 3v5H3M16 3v5h5M8 21v-5H3M16 21v-5h5" />',
  close: '<path d="M6 6l12 12M18 6L6 18" />'
}

const icon = (paths: string) =>
  `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`

// ── 標題：圖的說明文字，沒有時用前一個標題 ───────────────────────────
function headingText(h: Element): string {
  const c = h.cloneNode(true) as Element
  c.querySelectorAll('.header-anchor').forEach((a) => a.remove())
  return (c.textContent ?? '').split(ZWSP).join('').trim()
}

function previousHeading(el: Element): string {
  const root = el.closest('.vp-doc') ?? el.closest(config.scope) ?? document.body
  let found = ''
  for (const h of root.querySelectorAll('h1, h2, h3, h4')) {
    if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) found = headingText(h)
    else break
  }
  return found
}

export function figureLabel(host: Element): string {
  const caption = host.querySelector('figcaption')?.textContent?.trim()
  const img = host instanceof HTMLImageElement ? host : host.querySelector('img')
  const alt = img?.getAttribute('alt')?.trim()
  const svgTitle = host.querySelector('svg > title')?.textContent?.trim()
  const aria = host.getAttribute('aria-label')?.trim()
  const text = caption || aria || alt || svgTitle || previousHeading(host) || document.title
  return text.length > 80 ? `${text.slice(0, 79)}…` : text
}

// ── 複製：id 加字尾，並改寫指向它們的參照（url(#…)、href="#…"、IDREF 屬性、<style>） ──────────
let cloneSeq = 0
// 值是 id（或以空白分隔的多個 id）的屬性
const IDREF = /^(aria-(labelledby|describedby|controls|owns|flowto|details|errormessage|activedescendant)|for|headers|list|form|itemref)$/

function rewriteIds(root: Element): void {
  const suffix = `-pl-zoom${++cloneSeq}`
  const map = new Map<string, string>()
  const withId = [root, ...root.querySelectorAll('[id]')].filter((e) => e.id)
  for (const e of withId) {
    const n = e.id + suffix
    map.set(e.id, n)
    e.id = n
  }
  if (!map.size) return
  const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const keys = [...map.keys()].sort((a, b) => b.length - a.length).map(esc)
  const re = new RegExp(`#(${keys.join('|')})(?![\\w-])`, 'g')
  const fix = (v: string) => v.replace(re, (_m, id: string) => `#${map.get(id)}`)
  for (const e of [root, ...root.querySelectorAll('*')]) {
    for (const a of [...e.attributes]) {
      if (a.name === 'id') continue
      if (IDREF.test(a.name)) {
        e.setAttribute(a.name, a.value.split(/\s+/).map((t) => map.get(t) ?? t).join(' '))
      } else if (a.value.includes('#')) {
        const v = fix(a.value)
        if (v !== a.value) e.setAttributeNS(a.namespaceURI, a.name, v)
      }
    }
  }
  root.querySelectorAll('style').forEach((s) => { s.textContent = fix(s.textContent ?? '') })
}

// 行內 !important：作者 CSS（含 !important）都蓋不過
const force = (el: HTMLElement | SVGElement, prop: string, value: string) => el.style.setProperty(prop, value, 'important')

function cloneSvg(src: SVGSVGElement): SVGSVGElement {
  const svg = src.cloneNode(true) as SVGSVGElement
  rewriteIds(svg)
  svg.removeAttribute('style')
  // 站點對 SVG 自己 class 寫的尺寸、外距、顯示規則（例 width: 100%、height: auto、min-width: 960px、display: none）在檢視層不適用
  for (const [p, v] of [['display', 'block'], ['max-width', 'none'], ['max-height', 'none'], ['min-width', '0'], ['min-height', '0'], ['margin', '0']]) force(svg, p, v)
  return svg
}

function svgSize(svg: SVGSVGElement): { w: number; h: number } {
  const vb = svg.viewBox?.baseVal
  if (vb && vb.width > 0 && vb.height > 0) return { w: vb.width, h: vb.height }
  const r = svg.getBoundingClientRect()
  return { w: Math.max(1, r.width), h: Math.max(1, r.height) }
}

// HTML 宿主：外殼（祖先的標籤與屬性，display: contents）＋ 宿主的複製品（原本的寬度）
// 外殼不帶 id（頁面上不能有重複的 id）、樣式、可聚焦或會載入資源的屬性、事件
const SHELL_SKIP_ATTR = /^(id|style|tabindex|href|src|srcset|action|formaction|contenteditable|autofocus|popover|aria-.*|on.*)$/i

function shellOf(a: Element): HTMLElement {
  // 自訂元素（標籤有 -）用 div 代替：建立同名元素會執行它的建構子
  const html = a.namespaceURI === 'http://www.w3.org/1999/xhtml' && !a.localName.includes('-')
  const e = document.createElement(html ? a.localName : 'div')
  for (const at of [...a.attributes]) if (!SHELL_SKIP_ATTR.test(at.name)) e.setAttribute(at.name, at.value)
  force(e, 'display', 'contents')
  return e
}

// 宿主在沒有保留空間時的 padding-top（站點自己的 padding）：暫時拿掉保留空間的 class 量（同一個工作內還原，不會畫出來）
function basePaddingTop(host: HTMLElement): string {
  const had = RESERVE_CLASSES.filter((c) => host.classList.contains(c))
  if (!had.length) return getComputedStyle(host).paddingTop
  host.classList.remove(...had)
  const v = getComputedStyle(host).paddingTop
  host.classList.add(...had)
  return v
}

function cloneHtml(host: HTMLElement): { root: HTMLElement; width: number } {
  const clone = host.cloneNode(true) as HTMLElement
  // 頁面上的放大按鈕不帶過去（v1.1.1 起按鈕不在宿主裡；自己放按鈕的元件可能有）
  clone.querySelectorAll('.pl-zoom-btn').forEach((b) => b.remove())
  for (const e of [clone, ...clone.querySelectorAll('*')]) {
    if (e.classList.length) {
      e.classList.remove(...HOST_CLASSES)
      if (!e.classList.length) e.removeAttribute('class')
    }
    e.removeAttribute('data-pl-zoom-state')
    e.removeAttribute('data-pl-zoom-key')
    for (const a of [...e.attributes]) if (/^on/i.test(a.name) || a.name === 'autofocus') e.removeAttribute(a.name)
  }
  // 複製品不帶放大按鈕的保留空間（v1.1.1）：padding-top 還原成宿主沒有保留空間時的值（站點自己的 padding 保留）。
  // 拿掉 class 之外再明確寫一次，站點對宿主 class 組合另寫的保留空間規則也不會跟過去
  force(clone, 'padding-top', basePaddingTop(host))
  rewriteIds(clone)
  // 以原本在頁面上的寬度排版（border-box），不在檢視層重新排成別的樣子；外距、浮動、定位不帶過去
  const width = Math.max(1, host.getBoundingClientRect().width)
  force(clone, 'box-sizing', 'border-box')
  force(clone, 'width', `${width}px`)
  for (const [p, v] of [['min-width', '0'], ['max-width', 'none'], ['margin', '0'], ['position', 'relative'], ['inset', 'auto'], ['float', 'none']]) force(clone, p, v)
  // 祖先外殼：選擇器（.vp-doc …、宿主 class 的祖先、scoped 的 data-v-*）與繼承的字型、顏色都和頁面上相同
  let node: HTMLElement = clone
  for (let a = host.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
    const sh = shellOf(a)
    sh.append(node)
    node = sh
  }
  const root = document.createElement('div')
  root.append(node)
  return { root, width }
}

// ── 檢視層 ────────────────────────────────────────────────────────────
interface View {
  dialog: HTMLDialogElement
  title: HTMLElement
  level: HTMLElement
  stage: HTMLElement
  canvas: HTMLElement
  fsBtn: HTMLButtonElement
  trigger: HTMLElement | null
  content: SVGSVGElement | HTMLImageElement | HTMLElement | null
  kind: Kind
  // 頁面倍率：開啟時的倍率不小於它（圖在頁面上的大小）；開啟前量好，0 表示量不到
  pageScale: number
  resize: ResizeObserver | null
  nw: number
  nh: number
  scale: number
  tx: number
  ty: number
  // initial：開啟時的檢視（initialView：頁面倍率 > 符合畫面 × 1.02 時頁面倍率，否則符合畫面）；fit：符合畫面；free：使用者縮放或平移過。
  // 前兩種在檢視區大小、HTML 圖高度改變時重新計算
  mode: 'initial' | 'fit' | 'free'
}

let view: View | null = null

function button(cls: string, label: string, paths: string, extraText = ''): HTMLButtonElement {
  const b = document.createElement('button')
  b.type = 'button'
  b.className = `pl-zoom-tool ${cls}`
  b.setAttribute('aria-label', label)
  b.title = label
  b.innerHTML = (paths ? icon(paths) : '') + extraText
  return b
}

const fullscreenSupported = () => !!(document.fullscreenEnabled && HTMLElement.prototype.requestFullscreen)

function build(): View {
  const L = config.labels
  const dialog = document.createElement('dialog')
  dialog.className = 'pl-zoom-dialog'
  dialog.setAttribute('role', 'dialog')
  dialog.setAttribute('aria-modal', 'true')
  dialog.setAttribute('aria-labelledby', 'pl-zoom-title')
  dialog.setAttribute('aria-describedby', 'pl-zoom-help')

  const bar = document.createElement('div')
  bar.className = 'pl-zoom-bar'
  const title = document.createElement('h2')
  title.id = 'pl-zoom-title'
  title.className = 'pl-zoom-title'
  const level = document.createElement('span')
  level.className = 'pl-zoom-level'
  level.setAttribute('aria-live', 'polite')
  const tools = document.createElement('div')
  tools.className = 'pl-zoom-tools'
  tools.setAttribute('role', 'toolbar')
  tools.setAttribute('aria-label', L.toolbar)

  const out = button('is-out', L.zoomOut, ICONS.zoomOut)
  const inn = button('is-in', L.zoomIn, ICONS.zoomIn)
  const fit = button('is-fit', L.fit, ICONS.fit)
  const actual = button('is-actual', L.actual, '', '<span class="pl-zoom-tool-text" aria-hidden="true">100%</span>')
  const fsBtn = button('is-fullscreen', L.fullscreen, ICONS.fullscreen)
  fsBtn.setAttribute('aria-pressed', 'false')
  if (!fullscreenSupported()) fsBtn.hidden = true
  const close = button('is-close', L.close, ICONS.close)
  tools.append(out, inn, fit, actual, fsBtn, close)
  bar.append(title, level, tools)

  const stage = document.createElement('div')
  stage.className = 'pl-zoom-stage'
  stage.tabIndex = 0
  stage.setAttribute('role', 'group')
  stage.setAttribute('aria-roledescription', L.stageRole)
  stage.setAttribute('aria-label', L.stage)
  const canvas = document.createElement('div')
  canvas.className = 'pl-zoom-canvas'
  stage.append(canvas)

  const help = document.createElement('p')
  help.id = 'pl-zoom-help'
  help.className = 'pl-zoom-help'
  help.textContent = L.help

  dialog.append(bar, stage, help)
  document.body.append(dialog)

  const v: View = { dialog, title, level, stage, canvas, fsBtn, trigger: null, content: null, kind: 'svg', pageScale: 0, resize: null, nw: 1, nh: 1, scale: 1, tx: 0, ty: 0, mode: 'initial' }

  const center = () => ({ x: stage.clientWidth / 2, y: stage.clientHeight / 2 })
  out.addEventListener('click', () => step(-1, center()))
  inn.addEventListener('click', () => step(1, center()))
  fit.addEventListener('click', () => fitView())
  actual.addEventListener('click', () => zoomTo(1, center()))
  fsBtn.addEventListener('click', () => toggleFullscreen())
  close.addEventListener('click', () => closeFigure())

  dialog.addEventListener('cancel', (e) => { e.preventDefault(); closeFigure() })
  dialog.addEventListener('keydown', onKey)
  stage.addEventListener('wheel', onWheel, { passive: false })
  stage.addEventListener('pointerdown', onPointerDown)
  stage.addEventListener('pointermove', onPointerMove)
  stage.addEventListener('pointerup', onPointerUp)
  stage.addEventListener('pointercancel', onPointerUp)
  stage.addEventListener('dragstart', (e) => e.preventDefault())
  document.addEventListener('fullscreenchange', syncFullscreen)
  window.addEventListener('popstate', () => { if (dialog.open) closeFigure() })
  new ResizeObserver(() => { if (dialog.open) relayout() }).observe(stage)
  return v
}

// ── 縮放與平移 ────────────────────────────────────────────────────────
function apply() {
  const v = view
  if (!v?.content) return
  const w = v.nw * v.scale
  const h = v.nh * v.scale
  // 限制平移：圖至少留 KEEP_VISIBLE px 在檢視區內
  const W = v.stage.clientWidth
  const H = v.stage.clientHeight
  const kx = Math.min(KEEP_VISIBLE, w / 2)
  const ky = Math.min(KEEP_VISIBLE, h / 2)
  v.tx = Math.min(W - kx, Math.max(kx - w, v.tx))
  v.ty = Math.min(H - ky, Math.max(ky - h, v.ty))
  if (v.kind === 'html') {
    // HTML：排版固定在原本的寬度，整體縮放（transform 不改排版；文字是文字節點，瀏覽器依倍率重新繪製）
    force(v.content, 'transform', `scale(${v.scale})`)
  } else {
    // SVG／圖片：改寬高（不用 CSS scale），SVG 依新尺寸重新繪製，放大不會糊。
    // 用行內 !important：width／height 屬性只是預設值，站點對 SVG class 寫的 width: 100%、height: auto 會蓋過它
    if (v.content instanceof SVGSVGElement) {
      v.content.setAttribute('width', String(w))
      v.content.setAttribute('height', String(h))
    }
    force(v.content, 'width', `${w}px`)
    force(v.content, 'height', `${h}px`)
  }
  v.canvas.style.transform = `translate(${v.tx}px, ${v.ty}px)`
  v.level.textContent = `${Math.round(v.scale * 100)}%`
  v.dialog.dataset.scale = v.scale.toFixed(4)
  v.dialog.dataset.tx = v.tx.toFixed(1)
  v.dialog.dataset.ty = v.ty.toFixed(1)
}

function zoomTo(s: number, at: { x: number; y: number }) {
  const v = view
  if (!v) return
  const next = Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))
  const k = next / v.scale
  v.tx = at.x - (at.x - v.tx) * k
  v.ty = at.y - (at.y - v.ty) * k
  v.scale = next
  v.mode = 'free'
  apply()
}

function step(dir: 1 | -1, at: { x: number; y: number }) {
  const v = view
  if (!v) return
  const s = v.scale
  const next = dir > 0 ? LADDER.find((x) => x > s * 1.001) ?? s * 1.5 : [...LADDER].reverse().find((x) => x < s / 1.001) ?? s / 1.5
  zoomTo(next, at)
}

// 符合畫面的倍率：整張圖放進檢視區（四周各留 PAD）
function fitScale(v: View): number {
  let s = Math.min((v.stage.clientWidth - PAD * 2) / v.nw, (v.stage.clientHeight - PAD * 2) / v.nh)
  // 圖片不放大超過原尺寸（點陣放大只會糊）；向量圖照檢視區放大
  if (v.kind === 'img') s = Math.min(s, 1)
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))
}

function fitView() {
  const v = view
  if (!v?.content) return
  v.scale = fitScale(v)
  v.tx = (v.stage.clientWidth - v.nw * v.scale) / 2
  v.ty = (v.stage.clientHeight - v.nh * v.scale) / 2
  v.mode = 'fit'
  apply()
}

// 圖在頁面上的顯示寬度（內容寬，不含 padding、border）；沒有方塊時 0
function pageWidth(el: Element): number {
  if (!el.isConnected || !el.getClientRects().length) return 0
  const r = el.getBoundingClientRect()
  const cs = getComputedStyle(el)
  const edge = ['padding-left', 'padding-right', 'border-left-width', 'border-right-width'].reduce((n, k) => n + (parseFloat(cs.getPropertyValue(k)) || 0), 0)
  return Math.max(0, r.width - edge)
}

// 頁面倍率：圖在頁面上的大小 ÷ 倍率 1 時的大小（nw）。HTML 圖以頁面上的寬度（border-box）排版，倍率 1 就是頁面上的大小。
// 量不到（圖在頁面上沒有方塊）時 0，開啟時的倍率就是符合畫面。
// 在開啟前量：開啟後 <html> 加上 pl-zoom-open（overflow: hidden），頁面的捲軸消失、頁面可能重新排版，量到的就不是使用者看到的大小
function measurePage(v: View, el: Element): void {
  const w = v.kind === 'html' ? (el.getClientRects().length ? el.getBoundingClientRect().width : 0) : pageWidth(el)
  v.pageScale = v.kind === 'html' ? 1 : w > 0 && v.nw > 0 ? w / v.nw : 0
  v.dialog.dataset.pageW = w.toFixed(1)
  v.dialog.dataset.pageScale = v.pageScale.toFixed(4)
}

// 開啟時的檢視（v1.1.1；v1.1.2 加小差距的規則）：頁面倍率 > 符合畫面 × PAGE_OVER_FIT 時倍率 min(10, 頁面倍率)
// ——一打開至少和頁面上一樣大；否則符合畫面（整張看得見；頁面倍率只比它大不到 2% 時也是）。
// 放得下的方向置中；放不下的方向從頭開始（左、上留 PAD），其餘部分拖曳、方向鍵平移
function initialView() {
  const v = view
  if (!v?.content) return
  const W = v.stage.clientWidth
  const H = v.stage.clientHeight
  const fit = fitScale(v)
  v.scale = v.pageScale > fit * PAGE_OVER_FIT ? Math.min(MAX_SCALE, Math.max(MIN_SCALE, v.pageScale)) : fit
  const w = v.nw * v.scale
  const h = v.nh * v.scale
  v.tx = w <= W - PAD * 2 ? (W - w) / 2 : PAD
  v.ty = h <= H - PAD * 2 ? (H - h) / 2 : PAD
  v.mode = 'initial'
  apply()
}

// 檢視區或內容大小改變：開啟時的檢視與符合畫面重新計算；縮放、平移過就只套用（保持倍率與位置）
function relayout() {
  const v = view
  if (!v) return
  if (v.mode === 'initial') initialView()
  else if (v.mode === 'fit') fitView()
  else apply()
}

function pan(dx: number, dy: number) {
  const v = view
  if (!v) return
  v.tx += dx
  v.ty += dy
  v.mode = 'free'
  apply()
}

function onWheel(e: WheelEvent) {
  const v = view
  if (!v) return
  e.preventDefault()
  const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1
  // 觸控板的捏合縮放以 ctrlKey＋小的 deltaY 送來，係數大一點
  const k = Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0015))
  const r = v.stage.getBoundingClientRect()
  zoomTo(v.scale * k, { x: e.clientX - r.left, y: e.clientY - r.top })
}

const pointers = new Map<number, { x: number; y: number }>()
let pinch: { dist: number; mid: { x: number; y: number } } | null = null

function pinchInfo() {
  const [a, b] = [...pointers.values()]
  const r = view!.stage.getBoundingClientRect()
  return { dist: Math.hypot(a.x - b.x, a.y - b.y) || 1, mid: { x: (a.x + b.x) / 2 - r.left, y: (a.y + b.y) / 2 - r.top } }
}

function onPointerDown(e: PointerEvent) {
  // Shift＋滑鼠拖曳：保留瀏覽器原本的文字選取
  if (e.pointerType === 'mouse' && (e.shiftKey || e.button !== 0)) return
  e.preventDefault()
  view!.stage.setPointerCapture(e.pointerId)
  pointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  view!.stage.classList.add('is-dragging')
  pinch = pointers.size === 2 ? pinchInfo() : null
}

function onPointerMove(e: PointerEvent) {
  const p = pointers.get(e.pointerId)
  if (!p || !view) return
  const dx = e.clientX - p.x
  const dy = e.clientY - p.y
  p.x = e.clientX
  p.y = e.clientY
  if (pointers.size === 2 && pinch) {
    const now = pinchInfo()
    zoomTo(view.scale * (now.dist / pinch.dist), now.mid)
    pan(now.mid.x - pinch.mid.x, now.mid.y - pinch.mid.y)
    pinch = now
  } else if (pointers.size === 1) {
    pan(dx, dy)
  }
}

function onPointerUp(e: PointerEvent) {
  pointers.delete(e.pointerId)
  pinch = pointers.size === 2 ? pinchInfo() : null
  if (!pointers.size) view?.stage.classList.remove('is-dragging')
}

// ── 鍵盤與焦點 ────────────────────────────────────────────────────────
function focusables(): HTMLElement[] {
  if (!view) return []
  // 複製的 HTML 圖是 inert，裡面的按鈕不算
  return [...view.dialog.querySelectorAll<HTMLElement>('button, [tabindex="0"]')].filter((e) => !e.hidden && !(e as HTMLButtonElement).disabled && !e.closest('[inert]'))
}

function onKey(e: KeyboardEvent) {
  const v = view
  if (!v) return
  if (e.key === 'Tab') {
    // 焦點鎖在檢視層內：最後一個往後回到第一個、第一個往前到最後一個
    const list = focusables()
    if (!list.length) return
    const i = list.indexOf(document.activeElement as HTMLElement)
    if (e.shiftKey && i <= 0) { e.preventDefault(); list[list.length - 1].focus() }
    else if (!e.shiftKey && (i === list.length - 1 || i < 0)) { e.preventDefault(); list[0].focus() }
    return
  }
  if (e.key === 'Escape') { e.preventDefault(); closeFigure(); return }
  if (e.ctrlKey || e.metaKey || e.altKey) return
  const c = { x: v.stage.clientWidth / 2, y: v.stage.clientHeight / 2 }
  const d = e.shiftKey ? 200 : 50
  switch (e.key) {
    case '+': case '=': step(1, c); break
    case '-': case '_': step(-1, c); break
    case '0': fitView(); break
    case '1': zoomTo(1, c); break
    case 'ArrowLeft': pan(d, 0); break
    case 'ArrowRight': pan(-d, 0); break
    case 'ArrowUp': pan(0, d); break
    case 'ArrowDown': pan(0, -d); break
    case 'f': case 'F': if (!v.fsBtn.hidden) toggleFullscreen(); else return; break
    default: return
  }
  e.preventDefault()
}

// ── 全螢幕（瀏覽器不支援時檢視層本身就是滿視窗） ──────────────────────
function toggleFullscreen() {
  const v = view
  if (!v) return
  if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
  else void v.dialog.requestFullscreen?.().catch(() => { v.fsBtn.hidden = true })
}

function syncFullscreen() {
  const v = view
  if (!v) return
  const on = document.fullscreenElement === v.dialog
  v.fsBtn.setAttribute('aria-pressed', String(on))
  const label = on ? config.labels.exitFullscreen : config.labels.fullscreen
  v.fsBtn.setAttribute('aria-label', label)
  v.fsBtn.title = label
  v.fsBtn.innerHTML = icon(on ? ICONS.exitFullscreen : ICONS.fullscreen)
  v.dialog.classList.toggle('is-fullscreen', on)
}

// ── 開啟與關閉 ────────────────────────────────────────────────────────
const notOwnIcon = (e: Element) => !e.closest('.pl-zoom-btn, .pl-zoom-tool')
// 看得見：本身與祖先都不是 display: none（有方塊）、有寬度
const visible = (e: Element) => e.getClientRects().length > 0 && e.getBoundingClientRect().width > 0
// 多個候選時取看得見的第一個；都看不見才取第一個
const pick = <T extends Element>(list: T[]): T | undefined => list.find(visible) ?? list[0]

function htmlEligible(host: Element): boolean {
  if (!config.html || !(host instanceof HTMLElement) || host instanceof HTMLImageElement) return false
  if (!host.matches('figure, [data-pl-zoom]') || host.matches('.mermaid') || host.querySelector(NOT_HTML)) return false
  return host.children.length > 0 || !!host.textContent?.trim()
}

function sourceOf(host: Element): { kind: Kind; el: SVGSVGElement | HTMLImageElement | HTMLElement } | null {
  if (host instanceof HTMLImageElement) return { kind: 'img', el: host }
  // 明確指定放大整個宿主（裡面的 SVG 只是小圖示的 HTML 圖）
  if (config.html && host instanceof HTMLElement && host.getAttribute('data-pl-zoom') === 'html') return { kind: 'html', el: host }
  // 最外層的 <svg>（不是巢狀在另一個 svg 裡的），不含按鈕自己的圖示；有好幾張時取看得見的
  const svg = pick([...host.querySelectorAll<SVGSVGElement>('svg')].filter((e) => notOwnIcon(e) && !e.parentElement?.closest('svg')))
  if (svg) return { kind: 'svg', el: svg }
  const img = pick([...host.querySelectorAll<HTMLImageElement>('img')].filter(notOwnIcon))
  if (img) return { kind: 'img', el: img }
  return htmlEligible(host) ? { kind: 'html', el: host as HTMLElement } : null
}

export async function openFigure(host: Element, trigger: HTMLElement | null, label = figureLabel(host)): Promise<void> {
  const src = sourceOf(host)
  if (!src) return
  view ??= build()
  const v = view
  v.trigger = trigger
  v.kind = src.kind
  v.title.textContent = label
  v.resize?.disconnect()
  v.resize = null
  v.canvas.replaceChildren()
  v.content = null
  if (src.kind === 'html') {
    const { root, width } = cloneHtml(src.el as HTMLElement)
    root.className = 'pl-zoom-content pl-zoom-html'
    // 複製品不能聚焦、按不到、不觸發事件，也不進無障礙樹（原本的內容在頁面上；檢視層的標題是圖的說明）
    root.inert = true
    v.canvas.append(root)
    v.content = root
    v.nw = width
    v.nh = 1
  } else if (src.kind === 'svg') {
    const svg = cloneSvg(src.el as SVGSVGElement)
    const { w, h } = svgSize(src.el as SVGSVGElement)
    v.nw = w
    v.nh = h
    svg.classList.add('pl-zoom-content')
    v.canvas.append(svg)
    v.content = svg
  } else {
    const orig = src.el as HTMLImageElement
    const img = new Image()
    img.className = 'pl-zoom-content'
    img.alt = orig.alt
    img.decoding = 'async'
    img.draggable = false
    img.src = orig.currentSrc || orig.src
    try { await img.decode() } catch { /* 載入失敗時照樣顯示（替代文字） */ }
    v.nw = img.naturalWidth || orig.naturalWidth || 800
    v.nh = img.naturalHeight || orig.naturalHeight || 600
    v.canvas.append(img)
    v.content = img
  }
  v.dialog.dataset.kind = src.kind
  measurePage(v, src.el)
  if (!v.dialog.open) v.dialog.showModal()
  // 開啟時頁面不捲動（也不顯示頁面的捲軸）；捲動位置不變
  document.documentElement.classList.add('pl-zoom-open')
  if (v.kind === 'html') {
    // 高度要在檢視層裡排版後才量得到（transform 不影響 offsetHeight）；裡面的字型晚到而改變高度時重新量
    const root = v.content as HTMLElement
    v.nh = Math.max(1, root.offsetHeight)
    v.resize = new ResizeObserver(() => {
      const h = Math.max(1, root.offsetHeight)
      if (Math.abs(h - v.nh) < 0.5) return
      v.nh = h
      v.dialog.dataset.nh = String(Math.round(h))
      relayout()
    })
    v.resize.observe(root)
  }
  v.dialog.dataset.nw = String(Math.round(v.nw))
  v.dialog.dataset.nh = String(Math.round(v.nh))
  initialView()
  v.stage.focus({ preventScroll: true })
}

export function closeFigure(): void {
  const v = view
  if (!v?.dialog.open) return
  if (document.fullscreenElement === v.dialog) void document.exitFullscreen().catch(() => {})
  v.dialog.close()
  pointers.clear()
  pinch = null
  v.stage.classList.remove('is-dragging')
  v.resize?.disconnect()
  v.resize = null
  v.canvas.replaceChildren()
  v.content = null
  document.documentElement.classList.remove('pl-zoom-open')
  const t = v.trigger
  v.trigger = null
  if (t?.isConnected) t.focus({ preventScroll: true })
}

// ── 在頁面上的圖加按鈕 ───────────────────────────────────────────────
// 自己放按鈕的元件（例：寬圖的工具列）可以用 zoomButton 產生同樣的按鈕，或用自己的 <button> 呼叫 openFigure；
// 宿主加 data-pl-zoom-manual，掃描時就不會再加一個
export function zoomButton(label: string): HTMLButtonElement {
  const b = document.createElement('button')
  b.type = 'button'
  b.className = 'pl-zoom-btn'
  b.setAttribute('aria-label', `${config.labels.open}：${label}`)
  b.setAttribute('aria-haspopup', 'dialog')
  b.title = config.labels.open
  b.innerHTML = icon(ICONS.expand)
  return b
}

// ── 放在宿主外的按鈕：位置（v1.1.1） ─────────────────────────────────
// 按鈕插在宿主（或不允許 <button> 子元素的祖先）後面，絕對定位、top／left 都是 auto，所以留在原本的靜態位置；
// 量宿主與按鈕的矩形，用 transform 把按鈕移到宿主右上角（距 padding box 上緣、右緣各 INSET）。
// 靜態位置跟著頁面一起移動（上方內容變高時兩者一起往下），只有寬度、高度、捲動改變時要重新量
interface Placed { btn: HTMLButtonElement; host: HTMLElement; anchor: Element; dx: number; dy: number; hidden: boolean }
const placed = new Set<Placed>()
let keySeq = 0
let resizeWatch: ResizeObserver | null = null
let placeQueued = false

function anchorOf(host: Element): Element {
  let a = host
  while (a.parentElement && a.parentElement !== document.body && a.parentElement.matches(NO_BUTTON_PARENT)) a = a.parentElement
  return a
}

// 宿主不在了：按鈕一起拿掉；按鈕被移走或離開宿主旁邊（例：元件重新排列）：放回去
function settle(p: Placed): boolean {
  if (!p.host.isConnected) {
    p.btn.remove()
    resizeWatch?.unobserve(p.host)
    placed.delete(p)
    return false
  }
  if (p.anchor !== p.host && !p.anchor.contains(p.host)) p.anchor = anchorOf(p.host)
  if (p.btn.previousElementSibling !== p.anchor) p.anchor.after(p.btn)
  return true
}

function placeAll() {
  placeQueued = false
  const list = [...placed].filter(settle)
  // 先寫（隱藏的按鈕先顯示才量得到），再一次讀完，最後一次寫：只排版一次
  for (const p of list) if (p.hidden) { p.btn.style.removeProperty('display'); p.hidden = false }
  const dpr = window.devicePixelRatio || 1
  const snap = (v: number) => Math.round(v * dpr) / dpr
  const moves = list.map((p) => {
    // 宿主沒有方塊（display: none、在收起的 <details> 裡）：按鈕也不顯示
    if (!p.host.getClientRects().length) return null
    const hr = p.host.getBoundingClientRect()
    if (hr.width === 0) return null
    const cs = getComputedStyle(p.host)
    const br = p.btn.getBoundingClientRect()
    // 靜態位置 = 目前位置扣掉目前的位移（只有 translate）
    const sx = br.left - p.dx
    const sy = br.top - p.dy
    const left = snap(hr.right - parseFloat(cs.borderRightWidth) - INSET - br.width)
    const top = snap(hr.top + parseFloat(cs.borderTopWidth) + INSET)
    return { dx: left - sx, dy: top - sy }
  })
  list.forEach((p, i) => {
    const m = moves[i]
    if (!m) { force(p.btn, 'display', 'none'); p.hidden = true; return }
    if (Math.abs(m.dx - p.dx) < 0.01 && Math.abs(m.dy - p.dy) < 0.01) return
    p.dx = m.dx
    p.dy = m.dy
    force(p.btn, 'transform', `translate(${m.dx}px, ${m.dy}px)`)
  })
}

const schedulePlace = () => {
  if (placeQueued || !placed.size) return
  placeQueued = true
  requestAnimationFrame(placeAll)
}
// 捲動容器（overflow: auto 的外層）捲動時，宿主跟著捲、按鈕不一定（包含塊在捲動容器外時）：重新量。頁面本身的捲動不必
const onScroll = (e: Event) => { if (e.target instanceof Element && [...placed].some((p) => (e.target as Element).contains(p.host))) schedulePlace() }

function attach(host: HTMLElement, target: Element = host) {
  const label = figureLabel(target)
  const b = zoomButton(label)
  b.addEventListener('click', () => { void openFigure(target, b, label) })
  host.classList.add('pl-zoom-host')
  // SVG（Mermaid、流程圖）與 HTML 圖常常撐滿寬度：上方留一條放按鈕的空間，按鈕不壓在圖的文字上（figure-zoom.css）。
  // 圖片照常疊在右上角；data-pl-zoom-reserve（或 reserveImages）讓圖片也保留，="off" 讓任何宿主都不保留
  const kind = sourceOf(target)?.kind
  const reserve = target.closest('[data-pl-zoom-reserve]')?.getAttribute('data-pl-zoom-reserve')
  if (reserve !== 'off') {
    if (kind === 'svg') host.classList.add('pl-zoom-svg')
    else if (kind === 'html') host.classList.add('pl-zoom-html')
    else if (reserve != null || config.reserveImages) host.classList.add('pl-zoom-reserve')
  }
  host.dataset.plZoomState = 'ready'
  const key = String(++keySeq)
  host.dataset.plZoomKey = key
  b.dataset.plZoomFor = key
  if (host.classList.contains('pl-zoom-inline')) {
    // 圖片：skill 自己包的 span，按鈕放在裡面（figure-zoom.css 的 top／right）
    host.append(b)
    return
  }
  // 其他宿主：按鈕放在宿主外（宿主的子元素不變），定位到宿主右上角
  b.classList.add('is-placed')
  const p: Placed = { btn: b, host, anchor: anchorOf(host), dx: 0, dy: 0, hidden: false }
  p.anchor.after(b)
  placed.add(p)
  // 滑鼠在宿主上時按鈕明顯（按鈕不是宿主的子元素，CSS 的 :hover > 選不到）
  host.addEventListener('pointerenter', () => b.classList.add('is-host-hover'))
  host.addEventListener('pointerleave', () => b.classList.remove('is-host-hover'))
  resizeWatch?.observe(host)
  if (p.anchor.parentElement) resizeWatch?.observe(p.anchor.parentElement)
}

function skipped(el: Element): boolean {
  return !!el.closest(skipSelector()) || !!el.closest(MANUAL) || !!el.closest('.pl-zoom-btn, .pl-zoom-tool')
}

function scan() {
  const scope = document.querySelector(config.scope)
  if (!scope) return
  const seen = new Set<Element>()
  for (const sel of config.targets) {
    let list: Element[]
    try { list = [...scope.querySelectorAll(sel)] } catch { continue }
    for (const el of list) {
      if (seen.has(el) || !(el instanceof HTMLElement)) continue
      seen.add(el)
      if ((el as HTMLElement).dataset.plZoomState || skipped(el)) continue
      // 已經在另一個有按鈕的宿主裡（例：figure 裡的圖片）
      if (el.parentElement?.closest('.pl-zoom-host')) continue
      // 裡面已經有加了按鈕的圖（例：figure 裡的 Mermaid）：外層不再加
      if (el.querySelector('.pl-zoom-host')) continue
      if (el instanceof HTMLImageElement) {
        // 圖片：包一層 span 放按鈕；圖在連結裡時包住連結
        el.dataset.plZoomState = 'ready'
        const wrapTarget = (el.parentElement?.tagName === 'A' ? el.parentElement : el) as HTMLElement
        const wrap = document.createElement('span')
        wrap.className = 'pl-zoom-inline'
        wrapTarget.parentNode?.insertBefore(wrap, wrapTarget)
        wrap.append(wrapTarget)
        attach(wrap, el)
        continue
      }
      // 其他宿主：裡面有圖（SVG 或圖片）才加；還沒有（例：Mermaid 還在畫）就等下一次掃描
      if (!sourceOf(el)) continue
      // 宿主裡的圖片不另外加按鈕
      el.querySelectorAll<HTMLImageElement>('img').forEach((img) => { img.dataset.plZoomState = 'inside' })
      attach(el)
    }
  }
  placeAll()
}

let observer: MutationObserver | null = null
let queued = false

export function installFigureZoom(options: FigureZoomOptions = {}): () => void {
  if (observer) return () => {}
  config = {
    scope: options.scope ?? '.VPContent',
    targets: options.targets ?? DEFAULT_TARGETS,
    skip: options.skip ?? '',
    html: options.html ?? true,
    reserveImages: options.reserveImages ?? false,
    labels: { ...DEFAULT_LABELS, ...(options.labels ?? {}) }
  }
  const run = () => { queued = false; scan() }
  observer = new MutationObserver(() => {
    if (queued) return
    queued = true
    requestAnimationFrame(run)
  })
  observer.observe(document.body, { childList: true, subtree: true })
  // 放在宿主外的按鈕：宿主、宿主的父元素大小改變時重新定位（ResizeObserver 的回呼在排版後、繪製前，不會先畫在舊位置）
  resizeWatch = new ResizeObserver(() => placeAll())
  window.addEventListener('resize', schedulePlace)
  document.addEventListener('scroll', onScroll, { capture: true, passive: true })
  document.fonts?.addEventListener?.('loadingdone', schedulePlace)
  scan()
  return () => {
    observer?.disconnect()
    observer = null
    resizeWatch?.disconnect()
    resizeWatch = null
    window.removeEventListener('resize', schedulePlace)
    document.removeEventListener('scroll', onScroll, { capture: true })
    document.fonts?.removeEventListener?.('loadingdone', schedulePlace)
    for (const p of placed) p.btn.remove()
    placed.clear()
  }
}
