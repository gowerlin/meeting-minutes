// vitepress-portal-layout：寬螢幕版面的收合狀態（左側選單、右側本頁目錄）
//
// 狀態只存在瀏覽器：<html> 上的 class（給 CSS 用）＋ localStorage（重新整理、換頁後保留）。
// 不需要登入或伺服器；localStorage 讀寫失敗（私密視窗、被封鎖）時當作展開。
//
// layoutHeadScript 要放進每一頁的 <head>（config.mts 的 head），在畫面繪製前依 localStorage 套用 class，
// 載入時不會先展開再收合。它是固定字串：站點有 CSP 時，把它的 SHA-256 雜湊加進 script-src
// （算法見 references/csp.md），內容一改雜湊就要重算。

export const LAYOUT_STORAGE_KEY = 'pl-layout'

export const LAYOUT_PANELS = {
  sidebar: { cls: 'pl-sidebar-collapsed', minWidth: 960 },
  aside: { cls: 'pl-aside-collapsed', minWidth: 1280 }
} as const

export type LayoutPanel = keyof typeof LAYOUT_PANELS

// localStorage 存一個 JSON 物件，例如 {"sidebar":true}；沒有的鍵就是展開
type Stored = Partial<Record<LayoutPanel, boolean>>

export const layoutHeadScript = `(function(){try{var d=document.documentElement,v=JSON.parse(window.localStorage.getItem(${JSON.stringify(LAYOUT_STORAGE_KEY)})||"{}");${
  Object.entries(LAYOUT_PANELS).map(([panel, p]) => `if(v&&v[${JSON.stringify(panel)}]===true)d.classList.add(${JSON.stringify(p.cls)});`).join('')
}}catch(e){}})()`

function read(): Stored {
  try {
    const v = JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY) || '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    return {}
  }
}

export function isCollapsed(panel: LayoutPanel): boolean {
  return document.documentElement.classList.contains(LAYOUT_PANELS[panel].cls)
}

export function setCollapsed(panel: LayoutPanel, collapsed: boolean): void {
  document.documentElement.classList.toggle(LAYOUT_PANELS[panel].cls, collapsed)
  try {
    const v = read()
    if (collapsed) v[panel] = true
    else delete v[panel]
    if (Object.keys(v).length) window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(v))
    else window.localStorage.removeItem(LAYOUT_STORAGE_KEY)
  } catch {
    // 存不了就只在這一頁有效（下次載入當作展開）
  }
}
