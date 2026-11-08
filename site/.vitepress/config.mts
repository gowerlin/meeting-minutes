import fs from 'node:fs'
import { defineConfigWithTheme, type DefaultTheme, type HeadConfig } from 'vitepress'

// meeting-minutes Portal 的 VitePress 設定。
// 公開網址（repo、Releases）只寫在這個檔的常數裡；頁面一律透過元件（ReleaseDownload、RepoLink…）讀 themeConfig，
// 內文不手寫網址（去識別掃描會擋）。

export interface ReleaseAsset {
  name: string
  /** SHA-256（64 碼 hex）；首次發布前是 null */
  sha256: string | null
}

export interface MmRelease {
  proVersion: string
  proTag: string
  basicVersion: string
  basicTag: string
  /** 發布日（YYYY-MM-DD）；首次發布前是 null */
  releasedAt: string | null
  assets: { pro: ReleaseAsset[]; basic: ReleaseAsset[] }
}

export interface ThemeConfig extends DefaultTheme.Config {
  /** .vitepress/mm-release.json：Pro 與基本版的版號、Release tag、附件 */
  mmRelease: MmRelease
  /** 公開 repo 網址（結尾沒有 /） */
  repoUrl: string
  /** GitHub Releases 網址（結尾有 /）；下載連結＝releasesUrl＋download/<tag>/<檔名> */
  releasesUrl: string
}

// ---------- 設定值 ----------

// 公開 repo：只能寫在 .vitepress/ 的設定裡（帳號名由 repo 外的允許清單豁免去識別掃描）
const MM_REPO = 'gowerlin/meeting-minutes'
const MM_REPO_URL = `https://github.com/${MM_REPO}`
// Releases 網址前綴：tag 規則 pro-v<Pro 版號>、basic-v<基本版版號>，新 tag 不必改這裡
const MM_RELEASES_URL = `${MM_REPO_URL}/releases/`

const BASE = withSlashes(process.env.PORTAL_BASE || '/')
const SITE_URL = withTrailingSlash(process.env.PORTAL_SITE_URL || '')

const SITE_TITLE = 'meeting-minutes'
const SITE_DESCRIPTION =
  '在自己的電腦上把會議錄音轉成逐字稿，再讓 Claude 整理成繁體中文會議記錄；音檔不上傳。支援 Windows 與 macOS（Apple Silicon）。'
const NOT_FOUND_DESCRIPTION = '找不到這個頁面，網址可能已經移除或改名。請回首頁，或從上方選單找你要的內容。'

function withSlashes(value: string): string {
  let v = value.trim()
  if (!v.startsWith('/')) v = '/' + v
  if (!v.endsWith('/')) v += '/'
  return v
}

function withTrailingSlash(value: string): string {
  const v = value.trim()
  if (!v) return ''
  return v.endsWith('/') ? v : v + '/'
}

function readRelease(): MmRelease {
  const file = new URL('./mm-release.json', import.meta.url)
  if (!fs.existsSync(file)) throw new Error('[config] 找不到 .vitepress/mm-release.json')
  return JSON.parse(fs.readFileSync(file, 'utf8')) as MmRelease
}

// cleanUrls：faq.md → faq、install/index.md → install/、index.md → 首頁
function pageUrl(relativePath: string): string {
  return SITE_URL + relativePath.replace(/(^|\/)index\.md$/, '$1').replace(/\.md$/, '')
}

if (!SITE_URL) {
  console.warn('\n[config] WARNING: 沒有設定 PORTAL_SITE_URL；不輸出 sitemap 與 og:url\n')
}

// ---------- nav 與 sidebar ----------

const nav: DefaultTheme.NavItem[] = [
  { text: '首頁', link: '/' },
  { text: '安裝', link: '/install/', activeMatch: '^/install/' },
  { text: '功能', link: '/features/', activeMatch: '^/features/' },
  { text: '使用方式', link: '/usage/', activeMatch: '^/usage/' },
  { text: '常見問題', link: '/faq' },
  { text: '更版紀錄', link: '/releases' },
  { text: '設計理念與研究方法', link: '/design/', activeMatch: '^/design/' },
  { text: '基本版', link: '/basic' }
]

const sidebar: DefaultTheme.Sidebar = {
  '/install/': [
    {
      text: '安裝',
      items: [
        { text: '安裝', link: '/install/' },
        { text: 'GPU 說話者分離（選用）', link: '/install/gpu' },
        { text: 'Hugging Face 白話引導', link: '/install/hugging-face' },
        { text: '升級與解除安裝', link: '/install/upgrade' }
      ]
    }
  ],
  '/features/': [
    {
      text: '功能',
      items: [
        { text: '總覽', link: '/features/' },
        { text: '7 種內容類型', link: '/features/content-types' },
        { text: '自訂範本', link: '/features/custom-templates' },
        { text: '字幕', link: '/features/subtitles' },
        { text: '網頁版', link: '/features/web' },
        { text: '參考資料', link: '/features/reference' },
        { text: '全文用字統一', link: '/features/consistency' },
        { text: '說話者分離與講者人數', link: '/features/diarization' },
        { text: 'AI 校正與會議摘要', link: '/features/ai-correction' },
        { text: '提升準確度', link: '/features/accuracy' },
        { text: '執行 log 與費用', link: '/features/run-log' }
      ]
    }
  ],
  '/usage/': [
    {
      text: '使用方式',
      items: [
        { text: '總覽', link: '/usage/' },
        { text: '右鍵「傳送到」與拖放', link: '/usage/send-to' },
        { text: 'Claude CLI／Code 分頁', link: '/usage/cli' },
        { text: 'Claude 桌面 App', link: '/usage/claude-app' },
        { text: '手動執行與參數', link: '/usage/advanced' }
      ]
    }
  ],
  '/design/': [
    {
      text: '設計理念與研究方法',
      items: [
        { text: '設計理念', link: '/design/' },
        { text: '研究方法', link: '/design/research' }
      ]
    }
  ]
}

// local search 的繁中翻譯（沿用 Control Tower Portal）
const search: DefaultTheme.Config['search'] = {
  provider: 'local',
  options: {
    translations: {
      button: { buttonText: '搜尋', buttonAriaLabel: '搜尋' },
      modal: {
        displayDetails: '顯示詳細清單',
        resetButtonTitle: '清除搜尋',
        backButtonTitle: '關閉搜尋',
        noResultsText: '找不到相關結果',
        footer: {
          selectText: '選擇',
          selectKeyAriaLabel: 'Enter',
          navigateText: '切換',
          navigateUpKeyAriaLabel: '向上',
          navigateDownKeyAriaLabel: '向下',
          closeText: '關閉',
          closeKeyAriaLabel: 'Esc'
        }
      }
    }
  }
}

export default () => {
  const mmRelease = readRelease()

  const head: HeadConfig[] = [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${BASE}favicon.svg` }],
    ['meta', { name: 'theme-color', content: '#0f3d3e' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:site_name', content: SITE_TITLE }],
    ['meta', { property: 'og:locale', content: 'zh_TW' }]
  ]

  return defineConfigWithTheme<ThemeConfig>({
    base: BASE,
    lang: 'zh-TW',
    title: SITE_TITLE,
    description: SITE_DESCRIPTION,
    cleanUrls: true,
    lastUpdated: false,

    // 不是頁面的檔：規劃文件（不匯出）、公開 repo 根目錄檔的來源、工具
    srcExclude: ['PORTAL-PLAN.md', 'repo-root/**', 'scripts/**', 'README.md'],

    ...(SITE_URL ? { sitemap: { hostname: SITE_URL } } : {}),

    head,

    transformHead({ pageData, title, description }) {
      const pageDescription = pageData.isNotFound ? NOT_FOUND_DESCRIPTION : description
      const tags: HeadConfig[] = [
        ['meta', { property: 'og:title', content: title }],
        ['meta', { property: 'og:description', content: pageDescription }]
      ]
      if (pageData.isNotFound) tags.push(['meta', { name: 'description', content: NOT_FOUND_DESCRIPTION }])
      else if (SITE_URL) tags.push(['meta', { property: 'og:url', content: pageUrl(pageData.relativePath) }])
      return tags
    },

    themeConfig: {
      mmRelease,
      repoUrl: MM_REPO_URL,
      releasesUrl: MM_RELEASES_URL,

      logo: { src: '/logo.svg', alt: '' },
      siteTitle: '會議記錄 meeting-minutes',

      nav,
      sidebar,

      socialLinks: [{ icon: 'github', link: MM_REPO_URL, ariaLabel: 'GitHub' }],

      footer: {
        message: `內容基準：meeting-minutes-pro ${mmRelease.proVersion}、基本版 meeting-minutes ${mmRelease.basicVersion}`,
        copyright: 'MIT License'
      },

      search,

      outline: { level: [2, 3], label: '本頁目錄' },
      docFooter: { prev: '上一頁', next: '下一頁' },
      notFound: {
        title: '找不到頁面',
        quote: '這個網址沒有對應的頁面，可能已經移除或改名。',
        linkLabel: '回首頁',
        linkText: '回首頁'
      },
      darkModeSwitchLabel: '外觀',
      lightModeSwitchTitle: '切換為淺色',
      darkModeSwitchTitle: '切換為深色',
      sidebarMenuLabel: '選單',
      returnToTopLabel: '回到頂端',
      langMenuLabel: '切換語言',
      skipToContentLabel: '跳至內容',
      externalLinkIcon: true
    }
  })
}
