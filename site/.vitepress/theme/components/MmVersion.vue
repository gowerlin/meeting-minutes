<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'
import type { ThemeConfig } from '../../config.mjs'

// 行內版號：讀 .vitepress/mm-release.json
//   <MmVersion />＝Pro 版號、product="basic"＝基本版、product="proofread"＝會議記錄校稿、
//   product="proofread-min-pro"＝會議記錄校稿需要的 Pro 最低版本
type Product = 'pro' | 'basic' | 'proofread' | 'proofread-min-pro'
const props = withDefaults(defineProps<{ product?: Product }>(), { product: 'pro' })
const { theme } = useData<ThemeConfig>()
const version = computed(() => {
  const r = theme.value.mmRelease
  switch (props.product) {
    case 'basic': return r.basicVersion
    case 'proofread': return r.proofreadVersion
    case 'proofread-min-pro': return r.proofreadMinPro
    default: return r.proVersion
  }
})
</script>

<template><span class="mm-version">{{ version }}</span></template>
