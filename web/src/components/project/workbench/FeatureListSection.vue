<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// 占位组件：WB-02（feature 树 + 进度灯）由 Wave 2 plan 84-04 补全。
defineProps<{ projectId: string }>()

const { t } = useI18n()
</script>

<template>
  <section class="card" data-testid="workbench-feature-section">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
      <span class="icon-[lucide--list-tree] text-primary" />
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.workbench.feature.title') }}
      </h2>
    </header>
    <div class="p-5">
      <div class="flex flex-col items-center justify-center py-10 text-center gap-1.5">
        <span class="icon-[lucide--hammer] text-2xl text-muted-foreground/50" />
        <p class="text-sm font-medium text-foreground">
          {{ t('projects.workbench.section.buildingTitle') }}
        </p>
        <p class="text-xs text-muted-foreground">
          {{ t('projects.workbench.section.buildingDesc') }}
        </p>
      </div>
    </div>
  </section>
</template>
