<script setup lang="ts">
// vitepress-portal-layout：圖的放大檢視。每個有預設版面的頁面掛一次（index.example.ts 的 layout-bottom slot），
// 載入後替文中的圖加「放大檢視」按鈕；換頁、圖畫完（例：Mermaid）時自動補上。做法見 ../figure-zoom.ts。
// 本元件不輸出任何 HTML；伺服器端輸出沒有按鈕（按鈕要 JavaScript 才能用，載入後才加）。
//
// options：選取規則與文字（FigureZoomOptions），例：
//   h(FigureZoom, { options: { targets: [...DEFAULT_TARGETS, '.vp-doc .my-diagram'], skip: '.no-zoom-area' } })
import { onBeforeUnmount, onMounted } from 'vue'
import { closeFigure, installFigureZoom, type FigureZoomOptions } from '../figure-zoom'

const props = defineProps<{ options?: FigureZoomOptions }>()

let uninstall: (() => void) | null = null
onMounted(() => { uninstall = installFigureZoom(props.options ?? {}) })
onBeforeUnmount(() => { closeFigure(); uninstall?.() })
</script>

<template>
  <span hidden />
</template>
