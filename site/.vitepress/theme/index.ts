// 預設主題加上幾個讀 themeConfig 的元件（版號、下載連結、repo 連結、步驟條、會議記錄校稿介紹、開發方式連結）。
// 頁面要用版號或網址時一律用元件；.md 裡不要用 $theme（建置時錯誤會被吞掉），元件內用 useData()。
// 版型（主內容加寬、左右功能表收合、圖的放大檢視）來自 vitepress-portal-layout v1.1.2，檔案在 portal-layout/，不要改內容。
import { h } from 'vue'
import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import LayoutToggles from './portal-layout/components/LayoutToggles.vue'
import FigureZoom from './portal-layout/components/FigureZoom.vue'
import MmVersion from './components/MmVersion.vue'
import ReleaseDownload from './components/ReleaseDownload.vue'
import RepoLink from './components/RepoLink.vue'
import StepFlow from './components/StepFlow.vue'
import ProofreadIntro from './components/ProofreadIntro.vue'
import DevTools from './components/DevTools.vue'
import './portal-layout/layout.css'
import './portal-layout/figure-zoom.css'
// 站點自己的樣式放在 portal-layout 之後
import './custom.css'

export default {
  extends: DefaultTheme,
  Layout: () => h(DefaultTheme.Layout, null, {
    // 寬螢幕的左側選單、右側本頁目錄收合鈕（只在文件頁）
    'doc-top': () => h(LayoutToggles),
    // 圖的放大檢視：替文中的截圖與步驟條（StepFlow，data-pl-zoom）加「放大檢視」按鈕（本身不輸出內容）。
    // 截圖右上角常是應用程式自己的按鈕（主題、說明、改成淺色），所以截圖也在上方保留按鈕空間，不疊在圖上
    'layout-bottom': () => h(FigureZoom, { options: { reserveImages: true } })
  }),
  enhanceApp({ app }) {
    app.component('MmVersion', MmVersion)
    app.component('ReleaseDownload', ReleaseDownload)
    app.component('RepoLink', RepoLink)
    app.component('StepFlow', StepFlow)
    app.component('ProofreadIntro', ProofreadIntro)
    app.component('DevTools', DevTools)
  }
} satisfies Theme
