<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import PageContainer from '~/components/layout/PageContainer.vue'

const { t } = useI18n()
</script>

<template>
  <PageContainer>
    <div class="card p-8 space-y-3 max-w-xl">
      <h1 class="text-xl font-semibold">
        {{ t('knowledge.entity.pageTitle') }}
      </h1>
      <p class="text-sm text-muted-foreground">
        从工作流、对话检索结果或 MCP 工具返回的 entity_id 深链访问实体详情页。
      </p>
    </div>
  </PageContainer>
</template>
