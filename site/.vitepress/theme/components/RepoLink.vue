<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'
import type { ThemeConfig } from '../../config.mjs'

// 連到公開 repo 的檔案或目錄：<RepoLink path="docs/spec/" />（結尾 / 或 tree 屬性＝目錄）。
// path 空白＝repo 首頁；網址由 themeConfig.repoUrl 組出
const props = withDefaults(defineProps<{ path?: string; tree?: boolean }>(), { path: '', tree: false })
const { theme } = useData<ThemeConfig>()
const href = computed(() => {
  if (!props.path) return theme.value.repoUrl
  const kind = props.tree || props.path.endsWith('/') ? 'tree' : 'blob'
  return `${theme.value.repoUrl}/${kind}/main/${props.path.replace(/\/$/, '')}`
})
</script>

<template>
  <a :href="href" target="_blank" rel="noreferrer"><slot>{{ path || 'GitHub repo' }}</slot></a>
</template>
