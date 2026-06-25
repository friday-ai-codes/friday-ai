<script setup lang="ts">
import type { Project } from '~/api/projects'
import { useClipboard } from '@vueuse/core'
import { useQuery } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectsApi } from '~/api/projects'
import { Button } from '~/components/ui/button'

const props = defineProps<{ project: Project }>()

const { t } = useI18n()
const { copy, copied } = useClipboard()
const { success } = useToast()

const { data: rules, isLoading: rulesLoading, isError: rulesError } = useQuery({
  queryKey: ['project-cursor-rules', computed(() => props.project.id)],
  queryFn: () => projectsApi.cursorRules(props.project.id),
})

async function copyRules() {
  if (!rules.value)
    return
  await copy(rules.value.content)
  success(t('projects.overview.cursorRules.copied'))
}

function downloadRules() {
  if (!rules.value)
    return
  const blob = new Blob([rules.value.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = rules.value.filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="space-y-6">
    <!-- 描述 -->
    <section class="card p-5 space-y-2">
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.overview.description') }}
      </h2>
      <p v-if="project.description" class="text-sm text-muted-foreground whitespace-pre-wrap">
        {{ project.description }}
      </p>
      <p v-else class="text-sm text-muted-foreground/60 italic">
        {{ t('projects.overview.noDescription') }}
      </p>
    </section>

    <!-- 关键信息 -->
    <section class="grid gap-3 sm:grid-cols-3">
      <div class="card p-4">
        <p class="text-xs text-muted-foreground">
          {{ t('projects.overview.memberCount') }}
        </p>
        <p class="text-2xl font-bold text-foreground mt-1">
          {{ project.member_count }}
        </p>
      </div>
      <div class="card p-4">
        <p class="text-xs text-muted-foreground">
          {{ t('projects.overview.feishuKey') }}
        </p>
        <p class="text-sm font-medium text-foreground mt-1 truncate">
          {{ project.feishu_project_key || '—' }}
        </p>
      </div>
      <div class="card p-4">
        <p class="text-xs text-muted-foreground">
          {{ t('projects.overview.createdAt') }}
        </p>
        <p class="text-sm font-medium text-foreground mt-1">
          {{ new Date(project.created_at).toLocaleDateString() }}
        </p>
      </div>
    </section>

    <!-- Cursor rules（CURSOR-02） -->
    <section class="card p-5 space-y-3">
      <div class="flex items-start justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold text-foreground flex items-center gap-2">
            <span class="icon-[lucide--file-code-2] text-primary" />
            {{ t('projects.overview.cursorRules.title') }}
          </h2>
          <p class="text-xs text-muted-foreground mt-1">
            {{ t('projects.overview.cursorRules.desc') }}
          </p>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <Button
            size="sm"
            variant="outline"
            :disabled="!rules"
            data-testid="copy-cursor-rules"
            @click="copyRules"
          >
            <span class="icon-[lucide--copy] mr-1.5" />
            {{ copied ? t('projects.overview.cursorRules.copied') : t('projects.overview.cursorRules.copy') }}
          </Button>
          <Button size="sm" variant="outline" :disabled="!rules" @click="downloadRules">
            <span class="icon-[lucide--download] mr-1.5" />
            {{ t('projects.overview.cursorRules.download') }}
          </Button>
        </div>
      </div>

      <div v-if="rulesLoading" class="text-sm text-muted-foreground py-4">
        {{ t('projects.loading') }}
      </div>
      <div v-else-if="rulesError" class="text-sm text-destructive py-4">
        {{ t('projects.overview.cursorRules.loadError') }}
      </div>
      <pre
        v-else-if="rules"
        class="text-xs bg-muted/50 rounded-lg p-3 max-h-72 overflow-auto whitespace-pre-wrap text-muted-foreground"
      >{{ rules.content }}</pre>
    </section>
  </div>
</template>
