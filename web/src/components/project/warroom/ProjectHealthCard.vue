<script setup lang="ts">
import type { Project } from '~/api/projects'
import type { FeatureNode, FeatureState, ProjectDoc } from '~/api/projectWorkspace'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { mergeRequestsApi } from '~/api/mergeRequests'
import { projectsApi } from '~/api/projects'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

// P1 健康总览：复用现有 feature-list / MR / docs 端点聚合真实交付状态 + 规则化下一步建议。
const props = defineProps<{ project: Project, canManage?: boolean }>()
// 「补充 feature list」CTA 由父级（资料面板）接管，打开 feature list 录入入口。
const emit = defineEmits<{ 'add-feature-list': [] }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const projectId = computed(() => props.project.id)

// ── feature 四态计数 ─────────────────────────────────────────
const featuresQuery = useQuery({
  queryKey: ['project-features', projectId],
  queryFn: () => projectWorkspaceApi.getFeatureList(props.project.id),
})

function flattenFeatures(nodes: FeatureNode[]): FeatureNode[] {
  const out: FeatureNode[] = []
  const walk = (ns: FeatureNode[]) => {
    if (!Array.isArray(ns))
      return
    for (const n of ns) {
      if (n.kind === 'feature')
        out.push(n)
      if (n.children?.length)
        walk(n.children)
    }
  }
  walk(nodes)
  return out
}

// feature-list 端点返回 { modules: FeatureNode[] }；兼容历史/测试里的纯数组形态。
const featureModules = computed<FeatureNode[]>(() => {
  const d = featuresQuery.data.value as FeatureNode[] | { modules?: FeatureNode[] } | undefined
  if (Array.isArray(d))
    return d
  return d?.modules ?? []
})
const features = computed(() => flattenFeatures(featureModules.value))
const counts = computed(() => {
  const c: Record<FeatureState, number> = { todo: 0, in_progress: 0, testing: 0, done: 0 }
  for (const f of features.value) {
    const s: FeatureState = f.state && f.state in c ? f.state : 'todo'
    c[s] += 1
  }
  return c
})
const featureTotal = computed(() => features.value.length)

// ── 待合并 MR ────────────────────────────────────────────────
const mrQuery = useQuery({
  queryKey: ['project-merge-requests', projectId],
  queryFn: () => mergeRequestsApi.list(props.project.id),
})
const openMrCount = computed(
  () => (mrQuery.data.value ?? []).filter(m => m.status === 'open').length,
)

// ── 工作区 docs 同步态 + 重建 ────────────────────────────────
const docsQuery = useQuery({
  queryKey: ['project-docs', projectId],
  queryFn: () => projectWorkspaceApi.listDocs(props.project.id),
  refetchInterval: query =>
    (query.state.data?.some((d: ProjectDoc) => d.sync_status === 'syncing') ? 2000 : false),
})
const docs = computed<ProjectDoc[]>(() => docsQuery.data.value ?? [])
const anySyncing = computed(() => docs.value.some(d => d.sync_status === 'syncing'))
const anyDocError = computed(() => docs.value.some(d => d.sync_status === 'error'))
const docsReady = computed(() => docs.value.length > 0)
const syncSummary = computed(() => {
  if (anySyncing.value)
    return t('projects.warroom.health.syncing')
  if (anyDocError.value)
    return t('projects.warroom.health.syncError')
  if (docsReady.value)
    return t('projects.warroom.health.synced')
  return t('projects.warroom.health.syncIdle')
})

const rebuildMutation = useMutation({
  mutationFn: () => projectWorkspaceApi.rebuildWorkspace(props.project.id),
  onSuccess: () => {
    success(t('projects.warroom.health.rebuilt'))
    queryClient.invalidateQueries({ queryKey: ['project-docs', projectId] })
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.health.rebuildFailed')),
})
const isRebuilding = computed(() => rebuildMutation.isPending.value)

// #2：按 feature list 用 AI 生成/更新项目描述（手动触发；features 更新时后端已自动重写）。
const genDescMutation = useMutation({
  mutationFn: () => projectsApi.generateDescription(props.project.id),
  onSuccess: () => {
    success(t('projects.warroom.health.descGenerated'))
    queryClient.invalidateQueries({ queryKey: ['project', projectId] })
  },
  onError: (e: unknown) => handleError(e, t('projects.warroom.health.descGenerateFailed')),
})

// ── 下一步建议（规则版，仅基于真实数据）────────────────────────
// key=noFeature 时附带「补充 feature list」可点 CTA（#2）。
const nextStep = computed(() => {
  if (counts.value.testing > 0)
    return { key: 'testing', icon: 'icon-[lucide--clipboard-check]', text: t('projects.warroom.health.next.testing') }
  if (counts.value.in_progress > 0)
    return { key: 'in_progress', icon: 'icon-[lucide--hammer]', text: t('projects.warroom.health.next.inProgress') }
  if (openMrCount.value > 0)
    return { key: 'mr', icon: 'icon-[lucide--git-pull-request]', text: t('projects.warroom.health.next.mr') }
  if (featureTotal.value === 0)
    return { key: 'noFeature', icon: 'icon-[lucide--list-plus]', text: t('projects.warroom.health.next.noFeature') }
  return { key: 'good', icon: 'icon-[lucide--check-circle-2]', text: t('projects.warroom.health.next.good') }
})
const hasFeatures = computed(() => featureTotal.value > 0)

const isLoading = computed(() => featuresQuery.isLoading.value || mrQuery.isLoading.value)

const STATS = computed(() => [
  { key: 'total', label: t('projects.warroom.health.featureTotal'), value: featureTotal.value, icon: 'icon-[lucide--layers]', cls: 'text-foreground', chip: 'bg-foreground/5 text-foreground/70' },
  { key: 'in_progress', label: t('projects.workbench.feature.state.in_progress'), value: counts.value.in_progress, icon: 'icon-[lucide--hammer]', cls: 'text-primary', chip: 'bg-primary/10 text-primary' },
  { key: 'testing', label: t('projects.workbench.feature.state.testing'), value: counts.value.testing, icon: 'icon-[lucide--flask-conical]', cls: 'text-amber-500', chip: 'bg-amber-500/10 text-amber-500' },
  { key: 'done', label: t('projects.workbench.feature.state.done'), value: counts.value.done, icon: 'icon-[lucide--check-check]', cls: 'text-emerald-500', chip: 'bg-emerald-500/10 text-emerald-500' },
  { key: 'todo', label: t('projects.workbench.feature.state.todo'), value: counts.value.todo, icon: 'icon-[lucide--circle-dashed]', cls: 'text-muted-foreground', chip: 'bg-muted text-muted-foreground' },
  { key: 'mr', label: t('projects.warroom.health.openMr'), value: openMrCount.value, icon: 'icon-[lucide--git-pull-request]', cls: 'text-sky-600 dark:text-sky-400', chip: 'bg-sky-500/10 text-sky-600 dark:text-sky-400' },
])
</script>

<template>
  <section class="card" data-testid="warroom-health-card">
    <header class="px-5 py-3.5 border-b border-border/50 flex flex-wrap items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--gauge]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.warroom.health.title') }}
      </h2>
      <span class="text-sm text-muted-foreground inline-flex items-center gap-1.5 ml-1">
        <span
          class="size-2 rounded-full"
          :class="anySyncing ? 'bg-amber-500 animate-pulse' : anyDocError ? 'bg-destructive' : docsReady ? 'bg-emerald-500' : 'bg-muted-foreground/40'"
        />
        {{ syncSummary }}
      </span>
      <Button
        v-if="canManage"
        size="sm"
        variant="outline"
        class="ml-auto"
        :disabled="isRebuilding"
        data-testid="warroom-rebuild-btn"
        @click="() => rebuildMutation.mutate()"
      >
        <span class="icon-[lucide--refresh-cw] mr-1.5" :class="isRebuilding ? 'animate-spin' : ''" />
        {{ isRebuilding ? t('projects.warroom.health.rebuilding') : t('projects.warroom.health.rebuild') }}
      </Button>
    </header>

    <div class="p-5 space-y-5">
      <!-- 项目描述（可选；features 更新时后端按 AI 自动重写，管理员也可手动触发） -->
      <div class="space-y-1.5">
        <p v-if="project.description" class="text-sm text-muted-foreground whitespace-pre-wrap line-clamp-3">
          {{ project.description }}
        </p>
        <p v-else class="text-sm italic text-muted-foreground/70">
          {{ t('projects.overview.noDescription') }}
        </p>
        <!-- #3：AI 生成描述依赖 feature list，无 feature 时按钮无意义 → 仅在有 feature 时展示；
             否则给一句解释，避免用户点了没反应。 -->
        <Button
          v-if="canManage && hasFeatures"
          size="sm"
          variant="ghost"
          class="h-7 -ml-2 text-xs text-primary hover:text-primary"
          :disabled="genDescMutation.isPending.value"
          data-testid="gen-desc-btn"
          @click="() => genDescMutation.mutate()"
        >
          <span
            class="icon-[lucide--sparkles] mr-1"
            :class="genDescMutation.isPending.value ? 'animate-pulse' : ''"
          />
          {{ project.description ? t('projects.warroom.health.regenerateDesc') : t('projects.warroom.health.generateDesc') }}
        </Button>
        <p
          v-else-if="canManage && !project.description"
          class="text-xs text-muted-foreground/60"
          data-testid="gen-desc-hint"
        >
          {{ t('projects.warroom.health.descNeedsFeature') }}
        </p>
      </div>

      <!-- 统计卡 -->
      <div class="grid grid-cols-3 gap-2.5" :aria-busy="isLoading">
        <div
          v-for="s in STATS"
          :key="s.key"
          class="group relative rounded-lg border border-border/60 bg-muted/30 px-3.5 py-3 min-h-[80px] flex flex-col gap-2.5 transition-colors duration-200 hover:border-primary/30 hover:bg-primary/4"
          :data-testid="`warroom-stat-${s.key}`"
        >
          <span
            class="inline-flex size-7 items-center justify-center rounded-md text-sm"
            :class="s.chip"
          >
            <span :class="s.icon" />
          </span>
          <div class="min-w-0">
            <p class="text-[26px] font-bold tabular-nums leading-none tracking-tight" :class="s.cls">
              {{ s.value }}
            </p>
            <p class="text-xs text-muted-foreground truncate mt-1.5">
              {{ s.label }}
            </p>
          </div>
        </div>
      </div>

      <!-- 下一步建议 -->
      <div
        class="flex items-center gap-3 rounded-lg border border-primary/15 bg-primary/5 px-4 py-3"
        data-testid="warroom-next-step"
      >
        <span class="inline-flex size-9 items-center justify-center rounded-md bg-primary/12 text-primary shrink-0">
          <span :class="nextStep.icon" />
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-[11px] font-medium uppercase tracking-wider text-primary/70">
            {{ t('projects.warroom.health.nextLabel') }}
          </p>
          <p class="text-sm font-medium text-foreground">
            {{ nextStep.text }}
          </p>
        </div>
        <!-- #2：可点 CTA——无 feature 时直达「补充 feature list」入口 -->
        <Button
          v-if="nextStep.key === 'noFeature' && canManage"
          size="sm"
          class="shrink-0"
          data-testid="next-step-add-feature"
          @click="emit('add-feature-list')"
        >
          <span class="icon-[lucide--plus] mr-1" />
          {{ t('projects.warroom.health.addFeatureCta') }}
        </Button>
      </div>
    </div>
  </section>
</template>
