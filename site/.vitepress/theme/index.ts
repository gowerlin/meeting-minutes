// 預設主題加上幾個讀 themeConfig 的元件（版號、下載連結、repo 連結、步驟條）。
// 頁面要用版號或網址時一律用元件；.md 裡不要用 $theme（建置時錯誤會被吞掉），元件內用 useData()。
import DefaultTheme from 'vitepress/theme'
import type { Theme } from 'vitepress'
import MmVersion from './components/MmVersion.vue'
import ReleaseDownload from './components/ReleaseDownload.vue'
import RepoLink from './components/RepoLink.vue'
import StepFlow from './components/StepFlow.vue'
import './custom.css'

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component('MmVersion', MmVersion)
    app.component('ReleaseDownload', ReleaseDownload)
    app.component('RepoLink', RepoLink)
    app.component('StepFlow', StepFlow)
  }
} satisfies Theme
