<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'
import type { ThemeConfig } from '../../config.mjs'

// 開發方式的兩個工具連結（網址在 config.mts 的 themeConfig.devTools；頁面不手寫網址）
// <DevTools />＝兩個名稱連結；<DevTools name="bat" />／<DevTools name="ct" />＝只放一個
const props = defineProps<{ name?: 'bat' | 'ct' }>()
const { theme } = useData<ThemeConfig>()
const links = computed(() => {
  const d = theme.value.devTools
  const all = [
    { key: 'bat', text: 'Better Agent Terminal（BAT）', url: d.bat },
    { key: 'ct', text: 'Control Tower（CT）', url: d.ct }
  ]
  return props.name ? all.filter(x => x.key === props.name) : all
})
</script>

<template>
  <span class="mm-devtools">
    <template v-for="(l, i) in links" :key="l.key">
      <span v-if="i > 0"> ＋ </span>
      <a :href="l.url" target="_blank" rel="noreferrer">{{ l.text }}</a>
    </template>
  </span>
</template>
