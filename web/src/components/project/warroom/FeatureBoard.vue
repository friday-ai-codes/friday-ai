<script setup lang="ts">
import type { FeatureListDraft, FeatureNode, FeatureState } from '~/api/projectWorkspace'
import { useQuery } from '@tanstack/vue-query'
import { computed, markRaw, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import EmptyState from '~/components/common/EmptyState.vue'
import InlineMarkdown from '~/components/common/InlineMarkdown.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { useModal } from '~/composables/useModal'
import FeatureDetailModal from './FeatureDetailModal.vue'
import { useFeatureListEditor } from './useFeatureListEditor'

// P1：Feature 大盘——按「feature list → 模块 → 功能点」层级展示，状态用指示灯（顶部图例示意）。
// 数据同源 getFeatureList（与 ProjectHealthCard 共享 queryKey，vue-query 去重）。
const props = defineProps<{ projectId: string, canManage?: boolean }>()

// 常驻编辑入口：不受 feature 数量限制，随时可重新编辑/追加 feature list。
const { openFeatureListEditor } = useFeatureListEditor()
function openEditor() {
  openFeatureListEditor(props.projectId)
}

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

// 状态指示灯配色（不展示文字，仅圆点；顶部图例给出示意）。
const STATE_DOT_CLASS: Record<FeatureState, string> = {
  todo: 'bg-muted-foreground/40',
  in_progress: 'bg-primary',
  testing: 'bg-amber-500',
  done: 'bg-emerald-500',
}
const STATE_ORDER: FeatureState[] = ['todo', 'in_progress', 'testing', 'done']

function normalizeState(state?: FeatureState): FeatureState {
  return state && state in STATE_DOT_CLASS ? state : 'todo'
}

function moduleFeatures(mod: FeatureNode): FeatureNode[] {
  return (mod.children ?? []).filter(c => c.kind === 'feature')
}
function featureAcceptance(feat: FeatureNode): FeatureNode[] {
  return (feat.children ?? []).filter(c => c.kind === 'acceptance')
}

// 点开功能点详情（按需结构化为 sections，含流程图）。
function openDetail(node: FeatureNode) {
  const { open } = useModal({
    component: markRaw(FeatureDetailModal),
    attrs: { projectId: props.projectId, node },
  })
  void open()
}

const totalFeatures = computed(() =>
  modules.value.reduce((n, m) => n + moduleFeatures(m).length, 0),
)
const isEmpty = computed(() => totalFeatures.value === 0 && modules.value.length === 0)
</script>

<template>
  <section class="card" data-testid="warroom-feature-board">
    <header class="px-5 py-3.5 border-b border-border/50 flex flex-wrap items-center gap-x-2.5 gap-y-2">
      <span class="section-chip"><span class="icon-[lucide--list-tree]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.workbench.feature.title') }}
      </h2>
      <!-- 状态图例（示意）：功能点行只显示指示灯圆点，不展示状态文字。 -->
      <div class="ml-auto flex items-center gap-2.5" data-testid="feature-state-legend">
        <span
          v-for="st in STATE_ORDER"
          :key="st"
          class="inline-flex items-center gap-1 text-[11px] text-muted-foreground"
        >
          <span class="size-1.5 rounded-full" :class="STATE_DOT_CLASS[st]" />
          {{ t(`projects.workbench.feature.state.${st}`) }}
        </span>
      </div>
      <!-- 常驻入口（窄面板用紧凑图标按钮，避免与视图切换器挤占空间）：随时可编辑/增删改/拖动排序/追加解析。 -->
      <Button
        v-if="canManage"
        size="icon-sm"
        variant="ghost"
        class="shrink-0 text-muted-foreground hover:text-primary"
        :title="t('projects.warroom.health.editFeatureList')"
        :aria-label="t('projects.warroom.health.editFeatureList')"
        data-testid="feature-board-edit-btn"
        @click="openEditor"
      >
        <span class="icon-[lucide--pencil]" />
      </Button>
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

      <!-- feature list → 模块 → 功能点 层级（状态只用指示灯圆点，图例见顶部） -->
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
            <span class="ml-auto text-xs text-muted-foreground shrink-0 tabular-nums">
              {{ moduleFeatures(mod).length }}
            </span>
          </CollapsibleTrigger>
          <CollapsibleContent class="px-3 pb-2">
            <p v-if="moduleFeatures(mod).length === 0" class="pl-7 py-2 text-xs text-muted-foreground">
              {{ t('projects.workbench.feature.noFeatures') }}
            </p>
            <Collapsible
              v-for="(feat, fi) in moduleFeatures(mod)"
              :key="`f-${mi}-${fi}`"
              class="border-t border-border/30 first:border-t-0"
            >
              <div class="flex items-center gap-2 pl-5 py-2">
                <CollapsibleTrigger
                  class="group/feat flex min-w-0 flex-1 items-center gap-2 text-left"
                  data-testid="feature-row"
                >
                  <span class="icon-[lucide--chevron-right] text-xs text-muted-foreground transition-transform group-data-[state=open]/feat:rotate-90" />
                  <!-- 状态指示灯（无文字，hover 提示状态名） -->
                  <span
                    class="size-2 rounded-full shrink-0"
                    :class="STATE_DOT_CLASS[normalizeState(feat.state)]"
                    :title="feat.status_display_name || t(`projects.workbench.feature.state.${normalizeState(feat.state)}`)"
                    data-testid="feature-state-dot"
                  />
                  <span class="text-sm text-foreground truncate"><InlineMarkdown :text="feat.name" /></span>
                </CollapsibleTrigger>
                <span class="text-[11px] text-muted-foreground shrink-0 tabular-nums">
                  {{ t('projects.warroom.feature.acceptanceCount', { n: featureAcceptance(feat).length }) }}
                </span>
                <button
                  type="button"
                  class="shrink-0 inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-primary hover:bg-primary/5"
                  data-testid="feature-detail-btn"
                  @click="openDetail(feat)"
                >
                  <span class="icon-[lucide--panel-right-open] text-[11px]" /> 详情
                </button>
              </div>
              <CollapsibleContent class="pb-2 pl-12 pr-3">
                <p v-if="featureAcceptance(feat).length === 0" class="py-1 text-xs text-muted-foreground">
                  {{ t('projects.workbench.feature.noAcceptance') }}
                </p>
                <ul v-else class="space-y-0.5">
                  <li
                    v-for="(acc, ai) in featureAcceptance(feat)"
                    :key="ai"
                    class="flex items-center gap-2 py-1 text-xs"
                  >
                    <span class="icon-[lucide--check] text-emerald-500/70" />
                    <span class="truncate text-foreground/80"><InlineMarkdown :text="acc.name" /></span>
                  </li>
                </ul>
              </CollapsibleContent>
            </Collapsible>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  </section>
</template>
