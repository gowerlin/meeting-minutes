// vitepress-portal-layout：圖的放大檢視
//
// 文中的圖（Mermaid、figure 裡的 SVG／圖片、Markdown 圖片）右上角加一個「放大檢視」按鈕，開啟後是佔滿視窗的檢視層
// （可再進入瀏覽器的真正全螢幕），可縮放、拖曳、符合畫面、100%。
//
// - 向量：SVG 以複製的節點顯示（不轉點陣、不用 CSS scale），縮放是改 SVG 的寬高，文字仍是文字；複製時把 id 加上字尾，
//   並改寫 url(#…)、href="#…"、aria-labelledby／aria-describedby 與 SVG 自帶 <style> 裡的參照，頁面上不會有重複的 id
// - 圖片：以原檔（img 的 currentSrc）顯示，100% 是原檔的像素；符合畫面時不放大超過原尺寸
// - 檢視層是原生 <dialog>（showModal：頁面其他部分不可操作、在最上層）；焦點鎖在檢視層內，關閉後回到原按鈕
// - 鍵盤：+／− 放大縮小、0 符合畫面、1 原尺寸（100%）、方向鍵平移（Shift 加大）、F 全螢幕、Esc 關閉
// - 不載入外部資源、沒有 inline script、沒有第三方函式庫（主題模組，打包進站）
//
// 哪些元素有按鈕：options.targets 的選擇器（預設 DEFAULT_TARGETS），只找 options.scope（預設 .VPContent）裡面。
//   元素本身或祖先有 data-no-zoom（或 data-pl-no-zoom）時不加；有 data-pl-zoom-manual 的元素由自己的元件放按鈕
//   （呼叫 openFigure，例：寬圖工具列）。網頁投影片等 layout: false 的頁面沒有 .VPContent，不加。
// - data-* 屬性（data-kind、data-scale、data-tx、data-ty）給 scripts/layout-check.mjs 的 --figure-test 用

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
  // 要加按鈕的元素（宿主）。宿主是 <img> 時包一層 span 放按鈕；其他宿主找裡面第一個 <svg>，沒有再找 <img>
  targets?: string[]
  // 另外要略過的選擇器（data-no-zoom、data-pl-no-zoom 一律略過）
  skip?: string
  labels?: Partial<FigureZoomLabels>
}

export const DEFAULT_TARGETS = [
  // Mermaid：vitepress-plugin-mermaid 與多數自寫元件都輸出 class="mermaid"；圖畫好（有 <svg>）才加按鈕
  '.vp-doc .mermaid',
  // <figure> 裡的 SVG 或圖片（寬圖、截圖）
  '.vp-doc figure',
  // 明確指定：任何元素加 data-pl-zoom
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
const PAD = 16
const KEEP_VISIBLE = 48
const ZWSP = String.fromCharCode(0x200b)

type Kind = 'svg' | 'img'

let config: Required<Omit<FigureZoomOptions, 'labels'>> & { labels: FigureZoomLabels } = {
  scope: '.VPContent',
  targets: DEFAULT_TARGETS,
  skip: '',
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

// ── 複製 SVG：id 加字尾，並改寫指向它們的參照（url(#…)、href="#…"、aria-*by、<style>） ──
let cloneSeq = 0
function cloneSvg(src: SVGSVGElement): SVGSVGElement {
  const svg = src.cloneNode(true) as SVGSVGElement
  const suffix = `-pl-zoom${++cloneSeq}`
  const map = new Map<string, string>()
  const withId = [svg, ...svg.querySelectorAll('[id]')].filter((e) => e.id)
  for (const e of withId) {
    const n = e.id + suffix
    map.set(e.id, n)
    e.id = n
  }
  if (map.size) {
    const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const keys = [...map.keys()].sort((a, b) => b.length - a.length).map(esc)
    const re = new RegExp(`#(${keys.join('|')})(?![\\w-])`, 'g')
    const fix = (v: string) => v.replace(re, (_m, id: string) => `#${map.get(id)}`)
    for (const e of [svg, ...svg.querySelectorAll('*')]) {
      for (const a of [...e.attributes]) {
        if (a.name === 'id') continue
        if (/^aria-(labelledby|describedby)$/.test(a.name)) {
          e.setAttribute(a.name, a.value.split(/\s+/).map((t) => map.get(t) ?? t).join(' '))
        } else if (a.value.includes('#')) {
          const v = fix(a.value)
          if (v !== a.value) e.setAttributeNS(a.namespaceURI, a.name, v)
        }
      }
    }
    svg.querySelectorAll('style').forEach((s) => { s.textContent = fix(s.textContent ?? '') })
  }
  svg.removeAttribute('style')
  svg.style.maxWidth = 'none'
  svg.style.display = 'block'
  return svg
}

function svgSize(svg: SVGSVGElement): { w: number; h: number } {
  const vb = svg.viewBox?.baseVal
  if (vb && vb.width > 0 && vb.height > 0) return { w: vb.width, h: vb.height }
  const r = svg.getBoundingClientRect()
  return { w: Math.max(1, r.width), h: Math.max(1, r.height) }
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
  content: SVGSVGElement | HTMLImageElement | null
  kind: Kind
  nw: number
  nh: number
  scale: number
  tx: number
  ty: number
  fitted: boolean
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

  const v: View = { dialog, title, level, stage, canvas, fsBtn, trigger: null, content: null, kind: 'svg', nw: 1, nh: 1, scale: 1, tx: 0, ty: 0, fitted: true }

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
  new ResizeObserver(() => { if (dialog.open && v.fitted) fitView() }).observe(stage)
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
  // 改寬高（不用 CSS scale）：SVG 依新尺寸重新繪製，放大不會糊
  if (v.content instanceof SVGSVGElement) {
    v.content.setAttribute('width', String(w))
    v.content.setAttribute('height', String(h))
  } else {
    v.content.style.width = `${w}px`
    v.content.style.height = `${h}px`
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
  v.fitted = false
  apply()
}

function step(dir: 1 | -1, at: { x: number; y: number }) {
  const v = view
  if (!v) return
  const s = v.scale
  const next = dir > 0 ? LADDER.find((x) => x > s * 1.001) ?? s * 1.5 : [...LADDER].reverse().find((x) => x < s / 1.001) ?? s / 1.5
  zoomTo(next, at)
}

function fitView() {
  const v = view
  if (!v?.content) return
  const W = v.stage.clientWidth
  const H = v.stage.clientHeight
  let s = Math.min((W - PAD * 2) / v.nw, (H - PAD * 2) / v.nh)
  // 圖片不放大超過原尺寸（點陣放大只會糊）；向量圖照檢視區放大
  if (v.kind === 'img') s = Math.min(s, 1)
  v.scale = Math.min(MAX_SCALE, Math.max(MIN_SCALE, s))
  v.tx = (W - v.nw * v.scale) / 2
  v.ty = (H - v.nh * v.scale) / 2
  v.fitted = true
  apply()
}

function pan(dx: number, dy: number) {
  const v = view
  if (!v) return
  v.tx += dx
  v.ty += dy
  v.fitted = false
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
  return [...view.dialog.querySelectorAll<HTMLElement>('button, [tabindex="0"]')].filter((e) => !e.hidden && !(e as HTMLButtonElement).disabled)
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

function sourceOf(host: Element): { kind: Kind; el: SVGSVGElement | HTMLImageElement } | null {
  if (host instanceof HTMLImageElement) return { kind: 'img', el: host }
  // 最外層的 <svg>（不是巢狀在另一個 svg 裡的），不含按鈕自己的圖示
  const svg = [...host.querySelectorAll<SVGSVGElement>('svg')].find((e) => notOwnIcon(e) && !e.parentElement?.closest('svg'))
  if (svg) return { kind: 'svg', el: svg }
  const img = [...host.querySelectorAll<HTMLImageElement>('img')].find(notOwnIcon)
  return img ? { kind: 'img', el: img } : null
}

export async function openFigure(host: Element, trigger: HTMLElement | null, label = figureLabel(host)): Promise<void> {
  const src = sourceOf(host)
  if (!src) return
  view ??= build()
  const v = view
  v.trigger = trigger
  v.kind = src.kind
  v.title.textContent = label
  v.canvas.replaceChildren()
  v.content = null
  if (src.kind === 'svg') {
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
  if (!v.dialog.open) v.dialog.showModal()
  // 開啟時頁面不捲動（也不顯示頁面的捲軸）；捲動位置不變
  document.documentElement.classList.add('pl-zoom-open')
  fitView()
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

function attach(host: HTMLElement, target: Element = host) {
  const label = figureLabel(target)
  const b = zoomButton(label)
  b.addEventListener('click', () => { void openFigure(target, b, label) })
  host.classList.add('pl-zoom-host')
  // SVG（Mermaid、流程圖）常常撐滿寬度：上方留一條放按鈕的空間，按鈕不壓在圖的文字上（figure-zoom.css）
  if (sourceOf(target)?.kind === 'svg') host.classList.add('pl-zoom-svg')
  host.dataset.plZoomState = 'ready'
  host.append(b)
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
}

let observer: MutationObserver | null = null
let queued = false

export function installFigureZoom(options: FigureZoomOptions = {}): () => void {
  if (observer) return () => {}
  config = {
    scope: options.scope ?? '.VPContent',
    targets: options.targets ?? DEFAULT_TARGETS,
    skip: options.skip ?? '',
    labels: { ...DEFAULT_LABELS, ...(options.labels ?? {}) }
  }
  const run = () => { queued = false; scan() }
  observer = new MutationObserver(() => {
    if (queued) return
    queued = true
    requestAnimationFrame(run)
  })
  observer.observe(document.body, { childList: true, subtree: true })
  scan()
  return () => { observer?.disconnect(); observer = null }
}
