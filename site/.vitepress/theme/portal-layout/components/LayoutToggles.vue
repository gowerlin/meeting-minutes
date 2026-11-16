<script setup lang="ts">
// vitepress-portal-layout：寬螢幕的收合鈕。左側選單（≥ 960px）、右側本頁目錄（≥ 1280px）各一個，
// 收合後主內容取得那一側的寬度。放在文件頁的 doc-top slot（見 index.example.ts）；
// 位置固定在側欄與內容的交界，收合後移到視窗邊緣（layout.css〈收合鈕〉）。
// 小螢幕不顯示，維持 VitePress 原本的抽屜；列印時隱藏。狀態與保存見 ../layout-state.ts。
//
// 文字可以換成站點的語言：labels 傳入四個字串（預設繁體中文）。
import { onMounted, reactive, ref } from 'vue'
import { useSidebar } from 'vitepress/theme-without-fonts'
import { isCollapsed, setCollapsed, type LayoutPanel } from '../layout-state'

const props = withDefaults(defineProps<{
  labels?: {
    collapseSidebar: string
    expandSidebar: string
    collapseAside: string
    expandAside: string
  }
}>(), {
  labels: () => ({
    collapseSidebar: '收合左側選單',
    expandSidebar: '展開左側選單',
    collapseAside: '收合右側本頁目錄',
    expandAside: '展開右側本頁目錄'
  })
})

const { hasSidebar, hasAside, leftAside } = useSidebar()

// 按鈕只在瀏覽器端（掛載後）輸出：沒有 JavaScript 時（例 VitePress 的 MPA 模式）不會出現按得下去卻沒反應的按鈕。
// 版面本身不受影響：收合狀態由 head 的 script 在首屏前套到 <html>。載入後依 <html> 的 class 設定按鈕狀態。
const mounted = ref(false)
const collapsed = reactive<Record<LayoutPanel, boolean>>({ sidebar: false, aside: false })
onMounted(() => {
  collapsed.sidebar = isCollapsed('sidebar')
  collapsed.aside = isCollapsed('aside')
  mounted.value = true
})

function toggle(panel: LayoutPanel) {
  collapsed[panel] = !collapsed[panel]
  setCollapsed(panel, collapsed[panel])
}

const label = (panel: LayoutPanel) => {
  const l = props.labels
  if (panel === 'sidebar') return collapsed.sidebar ? l.expandSidebar : l.collapseSidebar
  return collapsed.aside ? l.expandAside : l.collapseAside
}
</script>

<template>
  <button
    v-if="mounted && hasSidebar"
    type="button"
    class="pl-layout-toggle is-sidebar"
    data-pl-panel="sidebar"
    aria-controls="VPSidebarNav"
    :aria-expanded="collapsed.sidebar ? 'false' : 'true'"
    :aria-label="label('sidebar')"
    :title="label('sidebar')"
    @click="toggle('sidebar')"
  >
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <path :d="collapsed.sidebar ? 'M9 6l6 6-6 6' : 'M15 6l-6 6 6 6'" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>
  <button
    v-if="mounted && hasAside && !leftAside"
    type="button"
    class="pl-layout-toggle is-aside"
    data-pl-panel="aside"
    :aria-expanded="collapsed.aside ? 'false' : 'true'"
    :aria-label="label('aside')"
    :title="label('aside')"
    @click="toggle('aside')"
  >
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true" focusable="false">
      <path :d="collapsed.aside ? 'M15 6l-6 6 6 6' : 'M9 6l6 6-6 6'" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
  </button>
</template>
