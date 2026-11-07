<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'
import type { ThemeConfig } from '../../config.mjs'

// 下載區：版號、tag、附件與 SHA-256 讀 .vitepress/mm-release.json，網址前綴讀 themeConfig.releasesUrl。
// product：pro／basic；compact：只顯示按鈕（首頁用）
const props = withDefaults(defineProps<{ product?: 'pro' | 'basic'; compact?: boolean }>(), { product: 'pro', compact: false })
const { theme } = useData<ThemeConfig>()

const info = computed(() => {
  const r = theme.value.mmRelease
  const pro = props.product === 'pro'
  const tag = pro ? r.proTag : r.basicTag
  const assets = (pro ? r.assets.pro : r.assets.basic).map(a => ({
    ...a,
    url: `${theme.value.releasesUrl}download/${tag}/${a.name}`,
    installer: a.name.endsWith('-installer.zip')
  }))
  return {
    title: pro ? 'meeting-minutes-pro（Pro 版）' : 'meeting-minutes（基本版）',
    version: pro ? r.proVersion : r.basicVersion,
    releasedAt: r.releasedAt,
    releaseUrl: `${theme.value.releasesUrl}tag/${tag}`,
    installer: assets.find(a => a.installer),
    upload: assets.find(a => !a.installer),
    assets
  }
})
</script>

<template>
  <div class="mm-download" :class="{ compact }">
    <div class="mm-download-head">
      <strong>{{ info.title }}</strong>
      <span class="mm-download-ver">版本 {{ info.version }}</span>
      <span v-if="info.releasedAt" class="mm-download-date">{{ info.releasedAt }} 發布</span>
    </div>
    <div class="mm-download-actions">
      <a v-if="info.installer" class="mm-btn brand" :href="info.installer.url">下載安裝包</a>
      <a v-if="info.upload && !compact" class="mm-btn alt" :href="info.upload.url">只下載 Claude App 上傳檔</a>
      <a class="mm-btn alt" :href="info.releaseUrl" target="_blank" rel="noreferrer">Release 頁面</a>
    </div>
    <table v-if="!compact" class="mm-download-table">
      <thead>
        <tr><th>檔案</th><th>用途</th><th>SHA-256</th></tr>
      </thead>
      <tbody>
        <tr v-for="a in info.assets" :key="a.name">
          <td><a :href="a.url"><code>{{ a.name }}</code></a></td>
          <td v-if="a.installer">解開後執行 <code>install.cmd</code>（Windows）或 <code>install.command</code>（macOS）</td>
          <td v-else>只用 Claude 桌面 App 時，上傳這個檔當 skill（不要解開）</td>
          <td><code v-if="a.sha256" class="mm-sha">{{ a.sha256 }}</code><span v-else>發布時公布</span></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
