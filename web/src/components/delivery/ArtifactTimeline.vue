<script setup lang="ts">
import type {
  ArtifactSummary,
  ArtifactVersionTimelineEntry,
} from '~/api/deliveryArtifacts'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import {
  getArtifactTimeline,
  getArtifactVersionDownstream,
  listArtifacts,
} from '~/api/deliveryArtifacts'

/**
 * ArtifactTimeline —— 交付物版本轨 / 时间线（Chassis v2 · P7，只读呈现）。
 *
 * 回答三问：
 *  - 当前最新版本是什么：当前版本徽标 + render_markdown 摘要（可折叠）。
 *  - 为何变成它：每版本 produced_by_ref + supersedes 链（“替换 vN”）。
 *  - 哪些下游产物引用它：选中版本时按需拉 RepoCodingTask / SddSpec / ArchitectMerge。
 *
 * 不在画布塞伪节点；按 space / artifact_type / work_item 过滤列出交付物，
 * 选一个看其版本时间线（least-invasive，挂在项目工作台资料面板）。
 * 文案内联中文，避免改动整份 i18n 资源。
 */
const props = defineProps<{
  /** 按所属空间过滤（项目工作台传 project.space_id）。 */
  spaceId?: string
  /** 按交付物类型过滤（如 technical_plan）。 */
  artifactType?: string
  /** 按工作项过滤。 */
  workItemId?: string
}>()

const listParams = computed(() => ({
  space_id: props.spaceId,
  artifact_type: props.artifactType,
  work_item_id: props.workItemId,
}))

const artifactsQuery = useQuery({
  queryKey: ['delivery-artifacts', listParams],
  queryFn: () => listArtifacts(listParams.value),
})
const artifacts = computed<ArtifactSummary[]>(() => artifactsQuery.data.value ?? [])

const selectedArtifactId = ref<string | null>(null)
watch(
  artifacts,
  (list) => {
    if (list.length === 0) {
      selectedArtifactId.value = null
      return
    }
    if (!selectedArtifactId.value || !list.some(a => a.id === selectedArtifactId.value))
      selectedArtifactId.value = list[0].id
  },
  { immediate: true },
)

const timelineQuery = useQuery({
  queryKey: ['delivery-artifact-timeline', selectedArtifactId],
  queryFn: () => getArtifactTimeline(selectedArtifactId.value!),
  enabled: computed(() => !!selectedArtifactId.value),
})
const timeline = computed(() => timelineQuery.data.value)

/** id → version_no 映射，用于把 supersedes_id 显示成“替换 vN”。 */
const versionNoById = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  for (const v of timeline.value?.versions ?? [])
    map[v.id] = v.version_no
  return map
})

const selectedVersionId = ref<string | null>(null)
watch(timeline, (t) => {
  if (!t) {
    selectedVersionId.value = null
    return
  }
  selectedVersionId.value = t.current_version?.id ?? t.versions[0]?.id ?? null
})

function selectVersion(v: ArtifactVersionTimelineEntry) {
  selectedVersionId.value = v.id
}

const downstreamQuery = useQuery({
  queryKey: ['delivery-artifact-downstream', selectedVersionId],
  queryFn: () => getArtifactVersionDownstream(selectedVersionId.value!),
  enabled: computed(() => !!selectedVersionId.value),
})
const downstream = computed(() => downstreamQuery.data.value)

function fmtTime(iso: string): string {
  if (!iso)
    return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
}

function approvalLabel(status: string): string {
  switch (status) {
    case 'approved':
      return '已批准'
    case 'pending':
      return '待审批'
    case 'rejected':
      return '已驳回'
    default:
      return '无审批'
  }
}
</script>

<template>
  <section class="card" data-testid="artifact-timeline">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--git-commit-horizontal]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        交付物版本轨
      </h2>
    </header>

    <div class="p-5 space-y-4">
      <!-- 加载 / 错误 / 空 -->
      <div
        v-if="artifactsQuery.isLoading.value"
        class="text-sm text-muted-foreground py-6 text-center"
        data-testid="artifact-loading"
      >
        加载中…
      </div>
      <div
        v-else-if="artifactsQuery.isError.value"
        class="py-6 text-center space-y-2"
        data-testid="artifact-error"
      >
        <p class="text-sm text-destructive">
          加载交付物失败
        </p>
        <button class="text-sm text-primary underline" @click="() => artifactsQuery.refetch()">
          重试
        </button>
      </div>
      <div
        v-else-if="artifacts.length === 0"
        class="text-sm text-muted-foreground py-6 text-center"
        data-testid="artifact-empty"
      >
        暂无交付物
      </div>

      <template v-else>
        <!-- 交付物切换 -->
        <div class="flex flex-wrap gap-2" data-testid="artifact-switcher">
          <button
            v-for="a in artifacts"
            :key="a.id"
            type="button"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-colors"
            :class="selectedArtifactId === a.id
              ? 'border-primary/40 bg-primary/8 text-primary font-medium'
              : 'border-border/50 text-muted-foreground hover:text-foreground hover:bg-muted/40'"
            :data-testid="`artifact-tab-${a.id}`"
            @click="selectedArtifactId = a.id"
          >
            <span class="icon-[lucide--file-text] shrink-0" />
            {{ a.title || a.artifact_type }}
            <span v-if="a.current_version" class="text-xs opacity-70">v{{ a.current_version.version_no }}</span>
          </button>
        </div>

        <!-- 选中交付物时间线 -->
        <div v-if="timelineQuery.isLoading.value" class="text-sm text-muted-foreground py-6 text-center">
          加载版本时间线…
        </div>
        <template v-else-if="timeline">
          <!-- 当前最新版本：是什么 -->
          <div
            class="rounded-lg border border-border/50 bg-muted/30 px-3.5 py-3 space-y-1.5"
            data-testid="artifact-current"
          >
            <div class="flex items-center gap-2 text-sm">
              <span class="inline-flex items-center gap-1 rounded-full bg-emerald-500/12 text-emerald-600 px-2 py-0.5 text-xs font-medium">
                <span class="icon-[lucide--badge-check]" /> 当前版本
              </span>
              <span class="font-semibold text-foreground">v{{ timeline.current_version?.version_no ?? '—' }}</span>
              <span class="text-xs text-muted-foreground">{{ approvalLabel(timeline.current_version?.approval_status ?? 'none') }}</span>
            </div>
            <details v-if="timeline.current_version_markdown" data-testid="artifact-current-md">
              <summary class="text-xs text-primary cursor-pointer select-none">
                查看当前版本内容
              </summary>
              <pre class="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words text-xs text-foreground/90 bg-background rounded-md p-2.5 border border-border/40">{{ timeline.current_version_markdown }}</pre>
            </details>
          </div>

          <!-- 版本时间线：为何变成它（produced_by_ref + supersedes 链） -->
          <ul class="space-y-2" data-testid="artifact-versions">
            <li
              v-for="v in timeline.versions"
              :key="v.id"
              class="rounded-lg border px-3.5 py-2.5 cursor-pointer transition-colors"
              :class="selectedVersionId === v.id
                ? 'border-primary/40 bg-primary/5'
                : 'border-border/50 hover:bg-muted/30'"
              :data-testid="`artifact-version-${v.version_no}`"
              @click="selectVersion(v)"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2 text-sm">
                  <span class="font-semibold text-foreground">v{{ v.version_no }}</span>
                  <span
                    v-if="v.is_current"
                    class="rounded-full bg-emerald-500/12 text-emerald-600 px-1.5 py-0.5 text-[11px] font-medium"
                  >当前</span>
                </div>
                <span class="text-xs text-muted-foreground">{{ fmtTime(v.created_at) }}</span>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                <span v-if="v.produced_by_ref" data-testid="version-produced-by">
                  来源：{{ v.produced_by_ref }}
                </span>
                <span v-if="v.supersedes_id" data-testid="version-supersedes">
                  替换 v{{ versionNoById[v.supersedes_id] ?? '?' }}
                </span>
                <span v-else>初始版本</span>
              </div>
            </li>
          </ul>

          <!-- 下游引用：哪些下游产物引用它 -->
          <div
            class="rounded-lg border border-border/50 px-3.5 py-3 space-y-2"
            data-testid="artifact-downstream"
          >
            <h3 class="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <span class="icon-[lucide--git-branch]" />
              下游引用
              <span v-if="downstream" class="text-muted-foreground font-normal">（{{ downstream.total }}）</span>
            </h3>
            <div v-if="downstreamQuery.isLoading.value" class="text-xs text-muted-foreground">
              加载下游引用…
            </div>
            <template v-else-if="downstream">
              <p v-if="downstream.total === 0" class="text-xs text-muted-foreground" data-testid="downstream-empty">
                暂无下游产物引用此版本
              </p>
              <ul v-else class="space-y-1 text-xs">
                <li
                  v-for="t in downstream.coding_tasks"
                  :key="`ct-${t.id}`"
                  class="flex items-center gap-2"
                  data-testid="downstream-coding-task"
                >
                  <span class="rounded bg-sky-500/12 text-sky-600 px-1.5 py-0.5">编码任务</span>
                  <span class="text-muted-foreground">wave {{ t.wave }} · {{ t.status }}</span>
                </li>
                <li
                  v-for="s in downstream.sdd_specs"
                  :key="`spec-${s.id}`"
                  class="flex items-center gap-2"
                  data-testid="downstream-sdd-spec"
                >
                  <span class="rounded bg-violet-500/12 text-violet-600 px-1.5 py-0.5">SDD 规格</span>
                  <span class="text-muted-foreground">{{ s.change_kind }} · {{ s.status }}</span>
                </li>
                <li
                  v-for="m in downstream.architect_merges"
                  :key="`merge-${m.id}`"
                  class="flex items-center gap-2"
                  data-testid="downstream-architect-merge"
                >
                  <span class="rounded bg-amber-500/12 text-amber-600 px-1.5 py-0.5">架构融合</span>
                  <span class="text-muted-foreground">{{ m.validation_status }} · 第 {{ m.attempt }} 次</span>
                </li>
              </ul>
            </template>
          </div>
        </template>
      </template>
    </div>
  </section>
</template>
