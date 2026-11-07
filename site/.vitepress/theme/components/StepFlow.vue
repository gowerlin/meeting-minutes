<script setup lang="ts">
// 步驟條（寬螢幕橫排、手機自動折行）：<StepFlow :steps="[{ title: '…', text: '…' }]" />
defineProps<{ steps: { title: string; text?: string }[] }>()
</script>

<template>
  <ol class="mm-steps">
    <li v-for="(s, i) in steps" :key="i">
      <span class="mm-step-no" aria-hidden="true">{{ i + 1 }}</span>
      <span class="mm-step-title">{{ s.title }}</span>
      <span v-if="s.text" class="mm-step-text">{{ s.text }}</span>
    </li>
  </ol>
</template>
