<route lang="yaml">
meta:
  requiresAdmin: true
  title: Galaxy 代码图谱
</route>

<script setup lang="ts">
import type { LocationQueryRaw } from 'vue-router'
import type { GalaxyRepoEdge, GalaxyRepoNode, GalaxySearchResult } from '~/api/galaxy'
import type { GalaxyGraphNode } from '~/lib/galaxy/graph-adapter'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getGalaxyRepoGraph } from '~/api/galaxy'
import GalaxyBreadcrumb from '~/components/galaxy/GalaxyBreadcrumb.vue'
import GalaxyCommandPalette from '~/components/galaxy/GalaxyCommandPalette.vue'
import GalaxyControls from '~/components/galaxy/GalaxyControls.vue'
import GalaxyLegend from '~/components/galaxy/GalaxyLegend.vue'
import GalaxySigmaGraph from '~/components/galaxy/GalaxySigmaGraph.vue'
import NodeDetailDrawer from '~/components/galaxy/NodeDetailDrawer.vue'
import { useGalaxyGraph } from '~/composables/useGalaxyGraph'
import { useToast } from '~/composables/useToast'

const route = useRoute()
const router = useRouter()
const { error: toastError } = useToast()

// ============================================================================
// URL query 驱动 viewMode（overview = L2 仓库节点 / detail = L1 细粒度）
// ============================================================================

const viewMode = computed<'overview' | 'detail'>(() =>
  route.query.repo_ids ? 'detail' : 'overview',
)

// 当前 detail 模式下被选中的 repo_ids（URL 同步）
const detailRepoKey = computed<string>(() => {
  const raw = route.query.repo_ids
  if (!raw)
    return ''
  return (Array.isArray(raw) ? raw.join(',') : raw)
    .split(',')
    .map(s => s.trim())
    .filter(Boolean)
    .join(',')
})

const detailRepoIds = computed<string[]>(() => {
  if (!detailRepoKey.value)
    return []
  return detailRepoKey.value.split(',')
})

// overview 模式下的空间过滤
const selectedSpaceId = ref<string | null>(
  (route.query.space_id as string) ?? null,
)

watch(selectedSpaceId, (val) => {
  const query = { ...route.query }
  if (val)
    query.space_id = val
  else delete query.space_id
  router.replace({ query })
})

// ============================================================================
// L1 detail 数据
// ============================================================================

const {
  nodes,
  edges,
  meta,
  loading,
  error,
  maxNodes,
  fps,
  activeNodeTypes,
  activeEdgeTypes,
  filteredNodes,
  fetchGraph,
  onFpsUpdate,
  toggleNodeType,
  toggleEdgeType,
  setAllNodeTypes,
  setAllEdgeTypes,
} = useGalaxyGraph()

// ============================================================================
// L2 overview 数据
// ============================================================================

const overviewNodes = ref<GalaxyRepoNode[]>([])
const overviewEdges = ref<GalaxyRepoEdge[]>([])
const overviewLoading = ref(false)
const overviewError = ref<string | null>(null)

async function loadOverview() {
  overviewLoading.value = true
  overviewError.value = null
  try {
    const result = await getGalaxyRepoGraph({ spaceId: selectedSpaceId.value })
    overviewNodes.value = result.nodes
    overviewEdges.value = result.edges
  }
  catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '加载仓库总览失败'
    overviewError.value = msg
    toastError('加载失败', msg)
  }
  finally {
    overviewLoading.value = false
  }
}

async function loadDetail() {
  if (detailRepoIds.value.length === 0)
    return
  await fetchGraph(detailRepoIds.value)
}

// 监听 viewMode + 过滤参数变化，自动加载对应数据
watch(
  [viewMode, selectedSpaceId],
  async () => {
    if (viewMode.value === 'overview') {
      await loadOverview()
    }
  },
  { immediate: false },
)

watch(
  [viewMode, detailRepoKey],
  async () => {
    if (viewMode.value === 'detail') {
      await loadDetail()
    }
  },
  { immediate: false },
)

// 当前 detail 仓库 label（用于面包屑）
const detailRepoLabel = computed<string>(() => {
  const id = detailRepoIds.value[0]
  if (!id)
    return ''
  const found = overviewNodes.value.find(n => n.repository_id === id)
  if (found)
    return found.label
  return ''
})

// ============================================================================
// 移动端 fallback
// ============================================================================

const isMobile = computed(() => typeof window !== 'undefined' && window.innerWidth < 1024)

// ============================================================================
// 节点交互（overview 仓库节点 → 下钻；detail 细粒度节点 → drawer）
// ============================================================================

const graphRef = ref<InstanceType<typeof GalaxySigmaGraph> | null>(null)
const selectedNodeId = ref<string | null>(null)
const drawerOpen = ref(false)
const commandPaletteOpen = ref(false)

function openNode(nodeId: string) {
  selectedNodeId.value = nodeId
  drawerOpen.value = true
  router.replace({ query: { ...route.query, node: nodeId } })
  nextTick(() => {
    graphRef.value?.focusNode(nodeId)
  })
}

function handleOverviewNodeClick(node: GalaxyGraphNode) {
  // overview 模式：点击仓库节点下钻到 L1
  if (node.type === 'repository') {
    const repoUuid = node.repository_id || node.id.replace(/^repo:/, '')
    const nextQuery: LocationQueryRaw = { ...route.query, repo_ids: repoUuid }
    delete nextQuery.node
    router.push({ query: nextQuery })
  }
}

function handleDetailNodeClick(node: GalaxyGraphNode) {
  openNode(node.id)
}

function handleCommandPaletteSelect(result: GalaxySearchResult) {
  openNode(result.id)
}

function handleDrawerClose(open: boolean) {
  if (!open) {
    drawerOpen.value = false
    selectedNodeId.value = null
    const next = { ...route.query }
    delete next.node
    router.replace({ query: next })
  }
}

function handleDrawerNodeSelect(nodeId: string) {
  openNode(nodeId)
}

function handleBackToOverview() {
  const next = { ...route.query }
  delete next.repo_ids
  delete next.node
  router.push({ query: next })
}

// ============================================================================
// URL 中带 ?node= 时数据就绪后自动打开 Drawer
// ============================================================================

const urlNodeHandled = ref(false)
watch(filteredNodes, (list) => {
  if (urlNodeHandled.value || list.length === 0 || viewMode.value !== 'detail')
    return
  const urlNode = route.query.node as string | undefined
  if (urlNode) {
    urlNodeHandled.value = true
    openNode(urlNode)
  }
})

defineExpose({
  openNode,
  handleOverviewNodeClick,
  handleDetailNodeClick,
  handleCommandPaletteSelect,
  handleDrawerClose,
  handleDrawerNodeSelect,
  handleBackToOverview,
  drawerOpen,
  selectedNodeId,
  commandPaletteOpen,
  viewMode,
})

async function handleRefresh() {
  if (viewMode.value === 'overview') {
    await loadOverview()
  }
  else {
    await loadDetail()
  }
}

async function handleMaxNodesUpdate(value: number) {
  maxNodes.value = value
  if (viewMode.value === 'detail') {
    await loadDetail()
  }
}

onMounted(async () => {
  if (viewMode.value === 'overview') {
    await loadOverview()
  }
  else {
    // detail 模式首屏：先加载 overview（拿 repo label），再加载 detail
    await Promise.all([loadOverview(), loadDetail()])
  }
})
</script>

<template>
  <div class="flex flex-col h-screen bg-[#0a0a1f] overflow-hidden">
    <!-- 移动端 fallback -->
    <div
      v-if="isMobile"
      class="flex-1 flex items-center justify-center"
    >
      <div class="card text-center space-y-3 p-8 max-w-sm">
        <span class="icon-[lucide--monitor] text-5xl text-muted-foreground block" />
        <p class="text-sm text-muted-foreground">
          Galaxy 图谱需要桌面端访问
        </p>
        <p class="text-xs text-muted-foreground/60">
          请在 ≥ 1024px 宽度的浏览器中访问
        </p>
      </div>
    </div>

    <!-- 桌面端主视图 -->
    <template v-else>
      <!-- Overview 模式 (L2 仓库节点) -->
      <template v-if="viewMode === 'overview'">
        <!-- Loading -->
        <div
          v-if="overviewLoading"
          class="flex-1 flex items-center justify-center"
        >
          <div class="flex flex-col items-center gap-4 text-white">
            <span class="icon-[lucide--loader-circle] text-5xl animate-spin text-primary" />
            <span class="text-sm text-white/60">加载仓库总览...</span>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-else-if="!overviewError && overviewNodes.length === 0"
          class="flex-1 flex items-center justify-center"
        >
          <div class="card text-center space-y-3 p-8 max-w-sm bg-white/5 border-white/10">
            <span class="icon-[lucide--git-branch] text-5xl text-muted-foreground block" />
            <p class="text-sm text-white/60">
              当前空间下暂无仓库数据
            </p>
            <p class="text-xs text-white/40">
              换个空间试试，或先为仓库建立索引
            </p>
          </div>
        </div>

        <!-- 错误 -->
        <div
          v-else-if="overviewError"
          class="flex-1 flex items-center justify-center"
        >
          <div class="card text-center space-y-3 p-8 max-w-sm bg-white/5 border-red-500/20">
            <span class="icon-[lucide--alert-circle] text-5xl text-destructive block" />
            <p class="text-sm text-destructive">
              {{ overviewError }}
            </p>
            <button class="btn btn-primary text-sm" @click="handleRefresh">
              重试
            </button>
          </div>
        </div>

        <!-- 仓库总览图 -->
        <div
          v-else
          class="flex-1 relative overflow-hidden"
        >
          <GalaxySigmaGraph
            :nodes="overviewNodes"
            :edges="overviewEdges"
            :loading="overviewLoading"
            class="w-full h-full"
            @node-click="handleOverviewNodeClick"
            @fps-update="onFpsUpdate"
          />

          <!-- 面包屑 + 空间下拉（顶部左） -->
          <div class="absolute top-4 left-4 z-10">
            <GalaxyBreadcrumb
              mode="overview"
              :space-id="selectedSpaceId"
              @update:space-id="selectedSpaceId = $event"
            />
          </div>

          <!-- 操作提示（右上） -->
          <div class="absolute top-4 right-4 z-10">
            <div class="glass-card rounded-lg px-3 py-1.5 text-white/60 text-xs flex items-center gap-2">
              <span class="icon-[lucide--mouse-pointer-click]" />
              <span>点击仓库节点查看内部细节</span>
            </div>
          </div>
        </div>
      </template>

      <!-- Detail 模式 (L1 细粒度) -->
      <template v-else>
        <div
          v-if="loading"
          class="flex-1 flex items-center justify-center"
        >
          <div class="flex flex-col items-center gap-4 text-white">
            <span class="icon-[lucide--loader-circle] text-5xl animate-spin text-primary" />
            <span class="text-sm text-white/60">加载 Galaxy 图谱...</span>
          </div>
        </div>

        <div
          v-else-if="!loading && nodes.length === 0 && !error"
          class="flex-1 flex items-center justify-center"
        >
          <div class="card text-center space-y-3 p-8 max-w-sm bg-white/5 border-white/10">
            <span class="icon-[lucide--git-branch] text-5xl text-muted-foreground block" />
            <p class="text-sm text-white/60">
              该仓库暂无图谱数据
            </p>
            <p class="text-xs text-white/40">
              请先建立索引，或调整节点类型过滤
            </p>
            <button class="btn btn-sm btn-outline mt-2" @click="handleBackToOverview">
              返回总览
            </button>
          </div>
        </div>

        <div
          v-else-if="error"
          class="flex-1 flex items-center justify-center"
        >
          <div class="card text-center space-y-3 p-8 max-w-sm bg-white/5 border-red-500/20">
            <span class="icon-[lucide--alert-circle] text-5xl text-destructive block" />
            <p class="text-sm text-destructive">
              {{ error }}
            </p>
            <button class="btn btn-primary text-sm" @click="handleRefresh">
              重试
            </button>
          </div>
        </div>

        <div
          v-else
          class="flex-1 relative overflow-hidden"
        >
          <GalaxySigmaGraph
            ref="graphRef"
            :nodes="nodes"
            :edges="edges"
            :loading="loading"
            :active-node-types="activeNodeTypes"
            :active-edge-types="activeEdgeTypes"
            :selected-node-id="drawerOpen ? selectedNodeId : null"
            class="w-full h-full"
            @node-click="handleDetailNodeClick"
            @fps-update="onFpsUpdate"
          />

          <Transition name="slide-down">
            <div
              v-if="meta?.sampled"
              class="absolute top-16 left-1/2 -translate-x-1/2 z-20"
            >
              <div class="glass-card rounded-xl px-4 py-2 text-xs text-amber-300/90 flex items-center gap-2">
                <span class="icon-[lucide--alert-triangle] text-amber-400" />
                共 {{ meta.total_nodes }} 个节点，已采样 top-{{ maxNodes }}（按 degree 排序）
              </div>
            </div>
          </Transition>

          <!-- 面包屑（顶部左） -->
          <div class="absolute top-4 left-4 z-10">
            <GalaxyBreadcrumb
              mode="detail"
              :space-id="selectedSpaceId"
              :repo-label="detailRepoLabel"
              @back="handleBackToOverview"
            />
          </div>

          <!-- 控制面板（右上） -->
          <div class="absolute top-4 right-4 z-10">
            <GalaxyControls
              :max-nodes="maxNodes"
              :fps="fps"
              :meta="meta"
              :active-node-types="activeNodeTypes"
              :active-edge-types="activeEdgeTypes"
              @update:max-nodes="handleMaxNodesUpdate"
              @toggle-node-type="toggleNodeType"
              @toggle-edge-type="toggleEdgeType"
              @set-all-node-types="setAllNodeTypes"
              @set-all-edge-types="setAllEdgeTypes"
              @refresh="handleRefresh"
            />
          </div>

          <!-- 图例（左下） -->
          <div class="absolute bottom-4 left-4 z-10">
            <GalaxyLegend />
          </div>

          <!-- Cmd+K 提示（顶部中间） -->
          <div class="absolute top-4 left-1/2 -translate-x-1/2 z-10">
            <div class="glass-card rounded-lg px-3 py-1.5 text-white/30 text-xs flex items-center gap-1.5">
              <kbd class="font-mono text-[10px]">⌘K</kbd>
              <span>搜索节点</span>
            </div>
          </div>
        </div>
      </template>
    </template>

    <!-- Cmd+K 搜索（detail 模式才生效） -->
    <GalaxyCommandPalette
      v-if="viewMode === 'detail'"
      v-model="commandPaletteOpen"
      :nodes="filteredNodes"
      @node-select="handleCommandPaletteSelect"
    />

    <!-- 节点详情 Drawer（detail 模式） -->
    <NodeDetailDrawer
      v-if="viewMode === 'detail'"
      :node-id="selectedNodeId"
      :model-value="drawerOpen"
      @update:model-value="handleDrawerClose"
      @node-select="handleDrawerNodeSelect"
    />
  </div>
</template>

<style scoped>
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
}

.slide-down-enter-from,
.slide-down-leave-to {
  opacity: 0;
  transform: translateY(-10px) translateX(-50%);
}

.slide-down-enter-to,
.slide-down-leave-from {
  opacity: 1;
  transform: translateY(0) translateX(-50%);
}
</style>
