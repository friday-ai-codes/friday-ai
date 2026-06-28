<script setup lang="ts">
import type { MergeRequest } from '~/api/mergeRequests'
import type { ProjectGraphNode } from '~/api/projects'
import { useQuery } from '@tanstack/vue-query'
import { computed, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { mergeRequestsApi } from '~/api/mergeRequests'
import { projectsApi } from '~/api/projects'

const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const projectIdRef = toRef(props, 'projectId')

const graphQuery = useQuery({
  queryKey: ['project-graph', projectIdRef],
  queryFn: () => projectsApi.graph(props.projectId, { direction: 'both', maxHops: 1 }),
})
const mrQuery = useQuery({
  queryKey: ['project-merge-requests', projectIdRef],
  queryFn: () => mergeRequestsApi.list(props.projectId),
})

const nodes = computed<ProjectGraphNode[]>(() => graphQuery.data.value?.nodes ?? [])
const mrs = computed<MergeRequest[]>(() => mrQuery.data.value ?? [])

function mrStatusClass(status: string): string {
  switch (status) {
    case 'merged':
      return 'bg-violet-500/10 text-violet-600 dark:text-violet-400'
    case 'open':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
    case 'closed':
      return 'bg-muted text-muted-foreground'
    default:
      return 'bg-muted text-muted-foreground'
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- MR / PR -->
    <section class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
        <span class="icon-[lucide--git-pull-request] text-primary" />
        {{ t('projects.links.mergeRequests') }}
      </h3>
      <div v-if="mrQuery.isLoading.value" class="text-sm text-muted-foreground py-4 text-center">
        {{ t('projects.loading') }}
      </div>
      <div v-else-if="mrQuery.isError.value" class="text-sm text-destructive py-4 text-center">
        {{ t('projects.links.mrLoadError') }}
      </div>
      <div v-else-if="mrs.length === 0" class="text-sm text-muted-foreground py-4 text-center">
        {{ t('projects.links.mrEmpty') }}
      </div>
      <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
        <li v-for="mr in mrs" :key="mr.id" class="px-4 py-3 space-y-1" data-testid="mr-row">
          <div class="flex items-center justify-between gap-2">
            <a
              :href="mr.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-sm font-medium text-primary hover:underline truncate"
            >
              {{ mr.title || `#${mr.external_id}` }}
            </a>
            <span class="px-2 py-0.5 rounded-full text-xs font-medium shrink-0" :class="mrStatusClass(mr.status)">
              {{ t(`projects.links.mrStatus.${mr.status}`) }}
            </span>
          </div>
          <p class="text-xs text-muted-foreground">
            {{ mr.platform }} · {{ mr.source_branch }} → {{ mr.target_branch }}
            <span v-if="mr.review_status"> · {{ mr.review_status }}</span>
          </p>
        </li>
      </ul>
    </section>

    <!-- 知识图谱关联 -->
    <section class="space-y-3">
      <h3 class="text-sm font-semibold text-foreground flex items-center gap-2">
        <span class="icon-[lucide--network] text-primary" />
        {{ t('projects.links.knowledge') }}
      </h3>
      <div v-if="graphQuery.isLoading.value" class="text-sm text-muted-foreground py-4 text-center">
        {{ t('projects.loading') }}
      </div>
      <div v-else-if="graphQuery.isError.value" class="text-sm text-destructive py-4 text-center">
        {{ t('projects.links.graphLoadError') }}
      </div>
      <div v-else-if="nodes.length === 0" class="text-sm text-muted-foreground py-4 text-center">
        {{ t('projects.links.graphEmpty') }}
      </div>
      <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
        <li
          v-for="(node, idx) in nodes"
          :key="node.entity_id || idx"
          class="flex items-center justify-between gap-3 px-4 py-3"
          data-testid="graph-node-row"
        >
          <div class="min-w-0">
            <p class="text-sm font-medium text-foreground truncate">
              {{ node.title || node.name || node.entity_id || '—' }}
            </p>
            <p class="text-xs text-muted-foreground">
              {{ node.kind }}<span v-if="node.relation"> · {{ node.relation }}</span>
            </p>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>
