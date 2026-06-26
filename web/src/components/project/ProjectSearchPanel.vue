<script setup lang="ts">
import type { Project } from '~/api/projects'
import type { SearchResult } from '~/api/projectWorkspace'
import { watchDebounced } from '@vueuse/core'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'

/**
 * WB-05 全局/模糊搜索面板。
 *
 * 项目内搜索端点（84-01）按项目维度调用：本面板在「当前筛选可见」的项目范围内聚合
 * `projectWorkspaceApi.search`，结果项展示 `locator`（属哪个 仓库 / 项目）并可深链跳转到
 * 对应项目工作台搜索区块。深度项目域 RAG 召回留 Phase 85（下方预留 RAG 结果位，不杜撰）。
 */

interface PanelResult {
  text: string
  score?: number
  locator: string
  projectId: string
  projectName: string
}

const props = defineProps<{ projects: Project[] }>()

const { t } = useI18n()

const keyword = ref('')
const committed = ref('')
const loading = ref(false)
const isError = ref(false)
const results = ref<PanelResult[]>([])

const scopeCount = computed(() => props.projects.length)

async function runSearch() {
  const q = keyword.value.trim()
  committed.value = q
  if (!q || props.projects.length === 0) {
    results.value = []
    isError.value = false
    loading.value = false
    return
  }

  loading.value = true
  isError.value = false
  // 召回为 best-effort：单项目失败不影响其余；全部失败才落错误态。
  const settled = await Promise.allSettled(
    props.projects.map(p => projectWorkspaceApi.search(p.id, q)),
  )
  const merged: PanelResult[] = []
  let anyOk = false
  settled.forEach((s, i) => {
    const p = props.projects[i]
    if (s.status === 'fulfilled') {
      anyOk = true
      for (const r of s.value as SearchResult[]) {
        merged.push({
          text: String(r.text ?? ''),
          score: typeof r.score === 'number' ? r.score : undefined,
          locator: String(r.locator ?? p.name),
          projectId: p.id,
          projectName: p.name,
        })
      }
    }
  })
  isError.value = !anyOk
  results.value = anyOk ? merged : []
  loading.value = false
}

watchDebounced(keyword, runSearch, { debounce: 300 })

const hasQuery = computed(() => committed.value.trim().length > 0)
const isEmpty = computed(
  () => hasQuery.value && !loading.value && !isError.value && results.value.length === 0,
)
</script>

<template>
  <div class="card p-4 space-y-4" data-testid="global-search-panel">
    <div class="space-y-2">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--search-code] text-primary" />
        <h3 class="text-sm font-semibold text-foreground">
          {{ t('projects.search.title') }}
        </h3>
      </div>
      <p class="text-xs text-muted-foreground">
        {{ t('projects.search.hint') }}
      </p>
    </div>

    <div class="relative">
      <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 text-sm pointer-events-none" />
      <input
        v-model="keyword"
        data-testid="global-search-input"
        :placeholder="t('projects.search.placeholder')"
        class="flex h-9 w-full rounded-lg border border-border/60 bg-background/90 pl-9 pr-3 py-1 text-sm placeholder:text-muted-foreground/70 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:border-ring/50"
        @keyup.enter="runSearch"
      >
    </div>

    <p class="text-xs text-muted-foreground">
      {{ scopeCount > 0 ? t('projects.search.scope', { n: scopeCount }) : t('projects.search.scopeEmpty') }}
    </p>

    <!-- 加载 -->
    <LoadingState v-if="loading" variant="skeleton" :count="3" :text="t('projects.search.loading')" />

    <!-- 错误兜底 -->
    <div v-else-if="isError" class="py-6 text-center space-y-3">
      <p class="text-sm text-destructive">
        {{ t('projects.search.loadError') }}
      </p>
      <Button variant="outline" size="sm" @click="runSearch">
        {{ t('projects.search.retry') }}
      </Button>
    </div>

    <!-- 空态 -->
    <EmptyState
      v-else-if="isEmpty"
      icon="lucide--search-x"
      :title="t('projects.search.emptyTitle')"
      :description="t('projects.search.emptyDesc')"
    />

    <!-- 结果（带 repo/project 定位 + 深链跳转） -->
    <div v-else-if="hasQuery && results.length" class="space-y-2">
      <p class="text-xs text-muted-foreground">
        {{ t('projects.search.resultCount', { n: results.length }) }}
      </p>
      <RouterLink
        v-for="(r, i) in results"
        :key="`${r.projectId}-${i}`"
        :to="`/projects/${r.projectId}#search`"
        data-testid="search-result"
        class="block rounded-lg border border-border/60 p-3 hover:border-primary/40 hover:bg-muted/30 transition-colors"
      >
        <p class="text-sm text-foreground line-clamp-2">
          {{ r.text }}
        </p>
        <div class="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
          <span class="inline-flex items-center gap-1 text-primary/80">
            <span class="icon-[lucide--map-pin]" />
            {{ t('projects.search.locator', { locator: r.locator }) }}
          </span>
          <span v-if="r.score != null" class="tabular-nums">{{ r.score.toFixed(2) }}</span>
        </div>
      </RouterLink>

      <!-- RAG 预留位（深度项目域召回 → Phase 85，诚实留位，不杜撰） -->
      <div class="mt-3 rounded-lg border border-dashed border-border/60 p-3" data-testid="search-rag-slot">
        <div class="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <span class="icon-[lucide--sparkles]" />
          {{ t('projects.search.rag.title') }}
        </div>
        <p class="mt-1 text-xs text-muted-foreground/80">
          {{ t('projects.search.rag.deferred') }}
        </p>
      </div>
    </div>
  </div>
</template>
