<script setup lang="ts">
import { computed } from 'vue'
import { useData } from 'vitepress'
import type { ThemeConfig } from '../../config.mjs'

// 行內版號：<MmVersion />＝Pro 版號，<MmVersion product="basic" />＝基本版版號。讀 .vitepress/mm-release.json
const props = withDefaults(defineProps<{ product?: 'pro' | 'basic' }>(), { product: 'pro' })
const { theme } = useData<ThemeConfig>()
const version = computed(() => (props.product === 'basic' ? theme.value.mmRelease.basicVersion : theme.value.mmRelease.proVersion))
</script>

<template><span class="mm-version">{{ version }}</span></template>
