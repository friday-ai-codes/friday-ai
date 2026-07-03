<script setup lang="ts">
import type { ProjectGalaxyNode, ProjectGalaxyNodeType } from '~/api/projectGalaxy'
import { useQuery } from '@tanstack/vue-query'
import { computed, onBeforeUnmount, ref, shallowRef, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectGalaxyApi } from '~/api/projectGalaxy'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'

// P4：项目级关系星图。3d-force-graph 动态加载 + 节点详情 + a11y 兜底列表。
const props = defineProps<{ projectId: string }>()

const { t } = useI18n()
const projectIdRef = toRef(props, 'projectId')

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-galaxy', projectIdRef],
  queryFn: () => projectGalaxyApi.get(props.projectId),
})

const graphEl = ref<HTMLElement | null>(null)
const graphInstance = shallowRef<any>(null)
const graphFailed = ref(false)
const selected = ref<ProjectGalaxyNode | null>(null)

// 节点类型语义色（与大盘 design token 语义对齐：项目=primary，feature=teal，
// 工作项=sky，仓库=violet，MR=emerald，工件=amber，能力=rose）。force-graph 需具体色值。
const TYPE_COLOR: Record<ProjectGalaxyNodeType, string> = {
  project: '#2563eb',
  feature: '#14b8a6',
  work_item: '#0ea5e9',
  repository: '#8b5cf6',
  merge_request: '#10b981',
  artifact: '#f59e0b',
  capability: '#ec4899',
}
const TYPE_LABEL: Record<ProjectGalaxyNodeType, string> = {
  project: 'project',
  feature: 'feature',
  work_item: 'workItem',
  repository: 'repository',
  merge_request: 'mergeRequest',
  artifact: 'artifact',
  capability: 'capability',
}

const isEmpty = computed(() => (data.value?.nodes.length ?? 0) <= 1)

const legend = computed(() => {
  const present = new Set((data.value?.nodes ?? []).map(n => n.type))
  return (Object.keys(TYPE_COLOR) as ProjectGalaxyNodeType[])
    .filter(ty => present.has(ty))
    .map(ty => ({ type: ty, color: TYPE_COLOR[ty], label: t(`projects.warroom.galaxy.type.${TYPE_LABEL[ty]}`) }))
})

async function initGraph() {
  if (!graphEl.value || !data.value || isEmpty.value)
    return
  try {
    const mod = await import('3d-force-graph')
    const ForceGraph3D = (mod.default ?? mod) as any
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches

    const graphData = {
      nodes: data.value.nodes.map(n => ({ ...n })),
      links: data.value.edges.map(e => ({ ...e })),
    }

    const inst = ForceGraph3D()(graphEl.value)
      .backgroundColor('rgba(0,0,0,0)')
      .graphData(graphData)
      .nodeId('id')
      .nodeLabel((n: any) => `${n.label}`)
      .nodeColor((n: any) => TYPE_COLOR[n.type as ProjectGalaxyNodeType] ?? '#94a3b8')
      .nodeRelSize(5)
      .linkColor(() => 'rgba(148,163,184,0.35)')
      .linkWidth(0.5)
      .width(graphEl.value.clientWidth)
      .height(graphEl.value.clientHeight)
      .onNodeClick((n: any) => {
        selected.value = n as ProjectGalaxyNode
      })

    if (reduceMotion) {
      inst.cooldownTicks(0)
      inst.warmupTicks(0)
    }
    graphInstance.value = inst
    graphFailed.value = false
  }
  catch {
    // WebGL/加载失败 → 走兜底节点列表
    graphFailed.value = true
  }
}

function disposeGraph() {
  try {
    graphInstance.value?._destructor?.()
  }
  catch {}
  graphInstance.value = null
}

// 数据就绪后初始化（或重建）。
watch(
  () => data.value,
  async () => {
    disposeGraph()
    selected.value = null
    if (data.value && !isEmpty.value)
      await initGraph()
  },
)

onBeforeUnmount(disposeGraph)
</script>

<template>
  <section class="card" data-testid="warroom-galaxy-card">
    <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2.5">
      <span class="section-chip"><span class="icon-[lucide--orbit]" /></span>
      <h2 class="text-sm font-semibold text-foreground">
        {{ t('projects.warroom.galaxy.title') }}
      </h2>
      <div v-if="data && !isEmpty" class="ml-auto flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          v-for="l in legend"
          :key="l.type"
          class="inline-flex items-center gap-1 text-[11px] text-muted-foreground"
        >
          <span class="size-2 rounded-full" :style="{ backgroundColor: l.color }" />
          {{ l.label }}
        </span>
      </div>
    </header>

    <div class="p-5">
      <LoadingState v-if="isLoading" variant="skeleton" :count="2" />

      <div v-else-if="isError" class="py-8 text-center space-y-2">
        <p class="text-sm text-destructive">
          {{ t('projects.warroom.galaxy.loadError') }}
        </p>
        <button class="text-sm text-primary underline" @click="() => refetch()">
          {{ t('projects.retry') }}
        </button>
      </div>

      <CompactEmptyState
        v-else-if="isEmpty"
        icon="lucide--orbit"
        :title="t('projects.warroom.galaxy.emptyTitle')"
        :description="t('projects.warroom.galaxy.emptyDesc')"
      />

      <div v-else class="space-y-3">
        <!-- 力导星图（reduced-motion 自动静态） -->
        <div
          v-show="!graphFailed"
          ref="graphEl"
          class="relative h-80 w-full rounded-lg border border-border/40 bg-muted/10 overflow-hidden"
          data-testid="galaxy-canvas"
        />

        <!-- 兜底：节点列表（图渲染失败 / 屏幕阅读器） -->
        <div v-if="graphFailed" class="rounded-lg border border-border/40 p-3" data-testid="galaxy-fallback">
          <ul class="space-y-1 max-h-72 overflow-auto">
            <li
              v-for="n in data!.nodes"
              :key="n.id"
              class="flex items-center gap-2 text-sm"
            >
              <span class="size-2 rounded-full shrink-0" :style="{ backgroundColor: TYPE_COLOR[n.type] }" />
              <span class="text-foreground truncate">{{ n.label }}</span>
              <span class="text-[11px] text-muted-foreground">{{ t(`projects.warroom.galaxy.type.${TYPE_LABEL[n.type]}`) }}</span>
            </li>
          </ul>
        </div>

        <!-- 选中节点详情 -->
        <div
          v-if="selected"
          class="rounded-lg bg-muted/30 px-4 py-3 flex items-start gap-2"
          data-testid="galaxy-node-detail"
        >
          <span class="size-2 mt-1.5 rounded-full shrink-0" :style="{ backgroundColor: TYPE_COLOR[selected.type] }" />
          <div class="min-w-0 flex-1">
            <p class="text-sm font-medium text-foreground truncate">
              {{ selected.label }}
            </p>
            <p class="text-xs text-muted-foreground">
              {{ t(`projects.warroom.galaxy.type.${TYPE_LABEL[selected.type]}`) }}
              <span v-if="selected.module"> · {{ selected.module }}</span>
            </p>
            <a
              v-if="selected.url"
              :href="selected.url"
              target="_blank"
              rel="noopener noreferrer"
              class="text-xs text-primary underline inline-flex items-center gap-1 mt-1"
            >
              <span class="icon-[lucide--external-link]" />{{ t('projects.warroom.galaxy.open') }}
            </a>
          </div>
          <button
            class="text-muted-foreground hover:text-foreground"
            :aria-label="t('projects.warroom.galaxy.clearSelection')"
            @click="selected = null"
          >
            <span class="icon-[lucide--x] text-sm" />
          </button>
        </div>

        <p v-if="data!.meta.truncated" class="text-[11px] text-muted-foreground">
          {{ t('projects.warroom.galaxy.truncated', { n: data!.meta.total_nodes }) }}
        </p>
      </div>
    </div>
  </section>
</template>
