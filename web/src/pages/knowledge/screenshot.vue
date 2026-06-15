<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import ScreenshotRecallPanel from '~/components/knowledge/ScreenshotRecallPanel.vue'
import PageContainer from '~/components/layout/PageContainer.vue'

const { t } = useI18n()
</script>

<template>
  <PageContainer>
    <div class="space-y-4 max-w-3xl">
      <h1 class="text-xl font-semibold">
        {{ t('screenshotRecall.title') }}
      </h1>
      <ScreenshotRecallPanel />
    </div>
  </PageContainer>
</template>
