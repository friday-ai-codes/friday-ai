<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import IngestPanel from '~/components/knowledge/IngestPanel.vue'
import PageContainer from '~/components/layout/PageContainer.vue'

const { t } = useI18n()
</script>

<template>
  <PageContainer>
    <div class="space-y-4 max-w-3xl">
      <h1 class="text-xl font-semibold">
        {{ t('ingest.title') }}
      </h1>
      <IngestPanel />
    </div>
  </PageContainer>
</template>
