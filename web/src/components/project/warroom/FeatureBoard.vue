<script setup lang="ts">
import type { FeatureListDraft, FeatureNode, FeatureState } from '~/api/projectWorkspace'
import { useQuery } from '@tanstack/vue-query'
import { computed, markRaw, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import EmptyState from '~/components/common/EmptyState.vue'
import InlineMarkdown from '~/components/common/InlineMarkdown.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { ToggleGroup, ToggleGroupItem } from '~/components/ui/toggle-group'
import { useModal } from '~/composables/useModal'
import FeatureDetailModal from './FeatureDetailModal.vue'

// P1：Feature 大盘——「按状态 / 按模块」视图切换。数据同源 getFeatureList（与 ProjectHealthCard 共享 queryKey，vue-query 去重）。
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const projectIdRef = toRef(props, 'projectId')

// 实时回显：暂无 feature 时轻量轮询（异步/Agent/节点生成的 feature list 自动浮现），
// 一旦解析出 feature 即停止轮询；切回窗口也刷新。
function _featureCount(d: unknown): number {
  const mods = Array.isArray(d) ? d : ((d as { modules?: FeatureNode[] } | undefined)?.modules ?? [])
  let n = 0
  const walk = (ns: FeatureNode[]) => {
    for (const node of ns ?? []) {
      if (node.kind === 'feature')
        n += 1
      if (node.children?.length)
        walk(node.children)
    }
  }
  walk(mods as FeatureNode[])
  return n
}

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-features', projectIdRef],
  queryFn: () => projectWorkspaceApi.getFeatureList(props.projectId),
  refetchOnWindowFocus: true,
  refetchInterval: query => (_featureCount(query.state.data) === 0 ? 5000 : false),
})

// 草稿异步解析进度：解析中轮询回显「功能点解析中 x%」徽标（异步/后台生成也能感知）。
const { data: draftData } = useQuery({
  queryKey: ['project-feature-draft', projectIdRef],
  queryFn: () => projectWorkspaceApi.getFeatureListDraft(props.projectId),
  refetchOnWindowFocus: true,
  refetchInterval: (query) => {
    const s = (query.state.data as FeatureListDraft | undefined)?.status
    return s === 'parsing' || s === 'partial' ? 3000 : false
  },
})
const draftParsing = computed(() => {
  const s = draftData.value?.status
  return s === 'parsing' || s === 'partial'
})

// feature-list 端点返回 { modules: FeatureNode[] }；兼容历史/测试里的纯数组形态。
const modules = computed<FeatureNode[]>(() => {
  const d = data.value as FeatureNode[] | { modules?: FeatureNode[] } | undefined
  if (Array.isArray(d))
    return d
  return d?.modules ?? []
})

const view = ref<'status' | 'module'>('status')

const STATE_CLASS: Record<FeatureState, string> = {
  todo: 'bg-muted text-muted-foreground',
  in_progress: 'bg-primary/15 text-primary',
  testing: 'bg-amber-500/15 text-amber-500',
  done: 'bg-emerald-500/15 text-emerald-500',
}
const STATE_ORDER: FeatureState[] = ['in_progress', 'testing', 'todo', 'done']

function normalizeState(state?: FeatureState): FeatureState {
  return state && state in STATE_CLASS ? state : 'todo'
}

interface FeatureRow {
  name: string
  module: string
  state: FeatureState
  acceptance: FeatureNode[]
  statusDisplay?: string
  node: FeatureNode
}

// 拍平：模块 → 功能点，带模块归属（按状态视图用）。
const rows = computed<FeatureRow[]>(() => {
  const out: FeatureRow[] = []
  for (const mod of modules.value) {
    for (const feat of mod.children ?? []) {
      if (feat.kind !== 'feature')
        continue
      out.push({
        name: feat.name,
        module: feat.module_normalized || mod.name,
        state: normalizeState(feat.state),
        acceptance: (feat.children ?? []).filter(c => c.kind === 'acceptance'),
        statusDisplay: feat.status_display_name,
        node: feat,
      })
    }
  }
  return out
})

// 点开功能点详情（按需结构化为 sections，含流程图）。
function openDetail(node: FeatureNode) {
  const { open } = useModal({
    component: markRaw(FeatureDetailModal),
    attrs: { projectId: props.projectId, node },
  })
  void open()
}

const byState = computed(() => {
  const map: Record<FeatureState, FeatureRow[]> = { in_progress: [], testing: [], todo: [], done: [] }
  for (const r of rows.value)
    map[r.state].push(r)
  return map
})

const isEmpty = computed(() => rows.value.length === 0 && modules.value.length === 0)
</script>

<template>
  <section class="card" data-testid="warroom-feature-board">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--list-tree]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.workbench.feature.title') }}
      </h2>
      <ToggleGroup
        v-model="view"
        type="single"
        size="sm"
        class="ml-auto"
        :aria-label="t('projects.warroom.feature.viewLabel')"
      >
        <ToggleGroupItem value="status" data-testid="feature-view-status">
          {{ t('projects.warroom.feature.byStatus') }}
        </ToggleGroupItem>
        <ToggleGroupItem value="module" data-testid="feature-view-module">
          {{ t('projects.warroom.feature.byModule') }}
        </ToggleGroupItem>
      </ToggleGroup>
    </header>

    <div class="p-5">
      <div
        v-if="draftParsing"
        class="mb-3 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary"
        data-testid="feature-draft-progress"
      >
        <span class="icon-[lucide--loader-2] animate-spin" />
        功能点解析中 · {{ draftData?.progress ?? 0 }}%
      </div>

      <LoadingState v-if="isLoading" variant="skeleton" :count="3" />

      <div v-else-if="isError" class="py-8 text-center space-y-2" data-testid="feature-error">
        <p class="text-sm text-destructive">
          {{ t('projects.workbench.feature.loadError') }}
        </p>
        <button class="text-sm text-primary underline" @click="() => refetch()">
          {{ t('projects.retry') }}
        </button>
      </div>

      <EmptyState
        v-else-if="isEmpty"
        icon="lucide--list-tree"
        :title="t('projects.workbench.feature.emptyTitle')"
        :description="t('projects.workbench.feature.emptyDesc')"
      />

      <!-- 按状态 -->
      <div v-else-if="view === 'status'" class="space-y-5" data-testid="feature-status-view">
        <div v-for="st in STATE_ORDER" :key="st">
          <div class="flex items-center gap-2 mb-2">
            <span
              class="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium"
              :class="STATE_CLASS[st]"
            >
              <span class="w-1.5 h-1.5 rounded-full bg-current" />
              {{ t(`projects.workbench.feature.state.${st}`) }}
            </span>
            <span class="text-xs text-muted-foreground tabular-nums">{{ byState[st].length }}</span>
          </div>
          <p v-if="byState[st].length === 0" class="pl-1 text-xs text-muted-foreground/70">
            {{ t('projects.warroom.feature.emptyGroup') }}
          </p>
          <div v-else class="space-y-1">
            <Collapsible
              v-for="(row, i) in byState[st]"
              :key="`${st}-${i}`"
              class="rounded-lg border border-border/40"
            >
              <div class="flex items-center gap-2 px-3 py-2">
                <CollapsibleTrigger
                  class="group flex min-w-0 flex-1 items-center gap-2 text-left"
                  data-testid="feature-row"
                >
                  <span class="icon-[lucide--chevron-right] text-xs text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
                  <span class="icon-[lucide--git-branch] text-muted-foreground shrink-0" />
                  <span class="text-sm text-foreground truncate"><InlineMarkdown :text="row.name" /></span>
                  <span class="text-xs text-muted-foreground truncate hidden sm:inline">· <InlineMarkdown :text="row.module" /></span>
                </CollapsibleTrigger>
                <span class="text-[11px] text-muted-foreground shrink-0 tabular-nums">
                  {{ t('projects.warroom.feature.acceptanceCount', { n: row.acceptance.length }) }}
                </span>
                <button
                  type="button"
                  class="shrink-0 inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-primary hover:bg-primary/5"
                  data-testid="feature-detail-btn"
                  @click="openDetail(row.node)"
                >
                  <span class="icon-[lucide--panel-right-open] text-[11px]" /> 详情
                </button>
              </div>
              <CollapsibleContent class="px-3 pb-2 pl-9">
                <p v-if="row.acceptance.length === 0" class="py-1 text-xs text-muted-foreground">
                  {{ t('projects.workbench.feature.noAcceptance') }}
                </p>
                <ul v-else class="space-y-0.5">
                  <li
                    v-for="(acc, ai) in row.acceptance"
                    :key="ai"
                    class="flex items-center gap-2 py-1 text-xs"
                  >
                    <span class="icon-[lucide--check] text-emerald-500/70" />
                    <span class="truncate text-foreground/80"><InlineMarkdown :text="acc.name" /></span>
                  </li>
                </ul>
              </CollapsibleContent>
            </Collapsible>
          </div>
        </div>
      </div>

      <!-- 按模块 -->
      <div v-else class="space-y-2" data-testid="feature-module-view">
        <Collapsible
          v-for="(mod, mi) in modules"
          :key="`m-${mi}`"
          default-open
          class="rounded-lg border border-border/40 bg-card"
        >
          <CollapsibleTrigger class="group flex w-full items-center gap-2 px-3 py-2.5 text-left">
            <span class="icon-[lucide--chevron-right] text-xs text-muted-foreground transition-transform group-data-[state=open]:rotate-90" />
            <span class="icon-[lucide--folder] text-primary" />
            <span class="text-sm font-medium text-foreground truncate"><InlineMarkdown :text="mod.name" /></span>
          </CollapsibleTrigger>
          <CollapsibleContent class="px-3 pb-2">
            <p v-if="(mod.children ?? []).filter(c => c.kind === 'feature').length === 0" class="pl-7 py-2 text-xs text-muted-foreground">
              {{ t('projects.workbench.feature.noFeatures') }}
            </p>
            <div
              v-for="(feat, fi) in (mod.children ?? []).filter(c => c.kind === 'feature')"
              :key="`f-${mi}-${fi}`"
              class="flex items-center justify-between gap-2 pl-5 py-2 border-t border-border/30 first:border-t-0"
            >
              <button
                type="button"
                class="flex min-w-0 items-center gap-2 text-left group/feat"
                data-testid="feature-detail-btn"
                @click="openDetail(feat)"
              >
                <span class="icon-[lucide--git-branch] text-muted-foreground shrink-0" />
                <span class="text-sm text-foreground truncate group-hover/feat:text-primary group-hover/feat:underline"><InlineMarkdown :text="feat.name" /></span>
              </button>
              <span
                class="inline-flex items-center gap-1.5 shrink-0 rounded-full px-2 py-0.5 text-xs font-medium"
                :class="STATE_CLASS[normalizeState(feat.state)]"
                :title="feat.status_display_name || undefined"
              >
                <span class="w-1.5 h-1.5 rounded-full bg-current" />
                {{ t(`projects.workbench.feature.state.${normalizeState(feat.state)}`) }}
              </span>
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  </section>
</template>
