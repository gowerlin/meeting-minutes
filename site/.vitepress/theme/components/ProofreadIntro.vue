<script setup lang="ts">
import { withBase } from 'vitepress'
import ReleaseDownload from './ReleaseDownload.vue'
import MmVersion from './MmVersion.vue'

// 首頁的「會議記錄校稿」介紹：左文右圖（窄螢幕上下）。版號與下載讀 mm-release.json
const points = [
  { icon: '✓', text: '點選標記確認或改寫' },
  { icon: '💾', text: '自動存檔、隨時接續' },
  { icon: '📄', text: '定稿與經驗匯入' }
]
</script>

<template>
  <div class="mm-proofread">
    <div class="mm-proofread-text">
      <p>
        AI 校正完，打開「會議記錄校稿」逐處確認：標記一目了然，點一下選修正或原文，任何地方都能直接改；隨時自動存檔、下次接著校；校完產出定稿逐字稿與字幕，還能把常錯的詞記進對照表。在你的電腦上執行，不上傳。
      </p>
      <ul class="mm-proofread-points">
        <li v-for="p in points" :key="p.text"><span aria-hidden="true">{{ p.icon }}</span>{{ p.text }}</li>
      </ul>
      <p class="mm-proofread-note">
        這是 meeting-minutes-pro 的附屬工具：要先安裝 Pro <MmVersion product="proofread-min-pro" /> 以上。
      </p>
      <ReleaseDownload product="proofread" compact />
      <div class="mm-proofread-links">
        <a class="mm-btn alt" :href="withBase('/features/proofread')">功能介紹</a>
        <a class="mm-btn alt" :href="withBase('/usage/proofread')">使用方法</a>
      </div>
    </div>
    <figure class="mm-proofread-shot">
      <img :src="withBase('/images/proofread/proofread-main.png')" alt="會議記錄校稿的主畫面：左邊是段落目錄，中間是逐字稿與標記，右邊是標記清單" loading="lazy" />
      <figcaption>主畫面（合成的示範逐字稿）</figcaption>
    </figure>
  </div>
</template>
