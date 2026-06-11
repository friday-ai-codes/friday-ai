<script setup lang="ts">
/**
 * GalaxyGraphModal — 全屏弹层内的单仓库 Galaxy 图谱
 *
 * 在仓库详情页直接打开当前仓库的 detail 图谱（L1 细粒度），
 * 无需跳转到 /codegraph/galaxy。复用 GalaxySigmaGraph / GalaxyControls /
 * GalaxyLegend / GalaxyCommandPalette / NodeDetailDrawer，与独立页面
 * 唯一差异：不做 URL query 同步，节点选中状态留在组件内。
 */
import type { GalaxySearchResult } from '~/api/galaxy'
import type { GalaxyGraphNode } from '~/lib/galaxy/graph-adapter'
import { useEventListener } from '@vueuse/core'
import { defineAsyncComponent, nextTick, onUnmounted, ref, watch } from 'vue'
import GalaxyCommandPalette from '~/components/galaxy/GalaxyCommandPalette.vue'
import GalaxyControls from '~/components/galaxy/GalaxyControls.vue'
import GalaxyLegend from '~/components/galaxy/GalaxyLegend.vue'
import NodeDetailDrawer from '~/components/galaxy/NodeDetailDrawer.vue'
import { useGalaxyGraph } from '~/composables/useGalaxyGraph'

const props = defineProps<{
  repositoryId: string
  /** 仓库名（标题展示用） */
  repoLabel?: string
}>()

const open = defineModel<boolean>('open', { default: false })

// 懒加载渲染层（sigma WebGL）：避免仓库详情页把 sigma 打进首屏 chunk，
// 也避免测试环境（happy-dom 无 WebGL2）在模块加载阶段崩溃
const GalaxySigmaGraph = defineAsyncComponent(
  () => import('~/components/galaxy/GalaxySigmaGraph.vue'),
)

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

// ===== 节点交互 =====

const graphRef = ref<{ focusNode: (nodeId: string) => void } | null>(null)
const selectedNodeId = ref<string | null>(null)
const drawerOpen = ref(false)
const commandPaletteOpen = ref(false)

function openNode(nodeId: string) {
  selectedNodeId.value = nodeId
  drawerOpen.value = true
  nextTick(() => {
    graphRef.value?.focusNode(nodeId)
  })
}

function handleNodeClick(node: GalaxyGraphNode) {
  openNode(node.id)
}

function handleCommandPaletteSelect(result: GalaxySearchResult) {
  openNode(result.id)
}

function handleDrawerClose(value: boolean) {
  if (!value) {
    drawerOpen.value = false
    selectedNodeId.value = null
  }
}

// ===== 数据加载 =====

async function loadGraph() {
  await fetchGraph([props.repositoryId])
}

async function handleMaxNodesUpdate(value: number) {
  maxNodes.value = value
  await loadGraph()
}

watch(open, (isOpen) => {
  if (isOpen) {
    drawerOpen.value = false
    selectedNodeId.value = null
    commandPaletteOpen.value = false
    loadGraph()
  }
})

// 弹层打开期间锁定底层页面滚动
watch(open, (isOpen) => {
  document.body.style.overflow = isOpen ? 'hidden' : ''
}, { flush: 'post' })

onUnmounted(() => {
  if (open.value)
    document.body.style.overflow = ''
})

// Esc 关闭（Drawer / 搜索面板打开时让它们自己先处理）
useEventListener(document, 'keydown', (e: KeyboardEvent) => {
  if (e.key === 'Escape' && open.value && !drawerOpen.value && !commandPaletteOpen.value)
    open.value = false
})

function close() {
  open.value = false
}
</script>

<template>
  <Teleport to="body">
    <Transition name="galaxy-modal-fade">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex flex-col bg-[#0a0a1f]"
        role="dialog"
        aria-modal="true"
        aria-label="Galaxy 代码图谱"
      >
        <!-- 顶栏 -->
        <div class="flex items-center justify-between gap-3 px-4 py-2.5 border-b border-white/10 shrink-0">
          <div class="flex items-center gap-2 min-w-0">
            <span class="icon-[lucide--orbit] text-primary shrink-0" />
            <span class="text-sm font-medium text-white truncate">
              {{ repoLabel || '仓库' }} · Galaxy 图谱
            </span>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <div class="hidden lg:flex glass-card rounded-lg px-3 py-1.5 text-white/30 text-xs items-center gap-1.5">
              <kbd class="font-mono text-[10px]">⌘K</kbd>
              <span>搜索节点</span>
            </div>
            <button
              type="button"
              class="flex items-center justify-center w-8 h-8 rounded-lg border border-white/10 text-white/60 hover:text-white hover:bg-white/10 transition-colors"
              aria-label="关闭图谱"
              @click="close"
            >
              <span class="icon-[lucide--x]" />
            </button>
          </div>
        </div>

        <!-- 主体 -->
        <div class="flex-1 relative overflow-hidden">
          <!-- Loading -->
          <div
            v-if="loading"
            class="absolute inset-0 flex items-center justify-center"
          >
            <div class="flex flex-col items-center gap-4 text-white">
              <span class="icon-[lucide--loader-circle] text-5xl animate-spin text-primary" />
              <span class="text-sm text-white/60">加载 Galaxy 图谱...</span>
            </div>
          </div>

          <!-- 错误 -->
          <div
            v-else-if="error"
            class="absolute inset-0 flex items-center justify-center"
          >
            <div class="card text-center space-y-3 p-8 max-w-sm bg-white/5 border-red-500/20">
              <span class="icon-[lucide--alert-circle] text-5xl text-destructive block" />
              <p class="text-sm text-destructive">
                {{ error }}
              </p>
              <button class="btn btn-primary text-sm" @click="loadGraph">
                重试
              </button>
            </div>
          </div>

          <!-- 空状态 -->
          <div
            v-else-if="nodes.length === 0"
            class="absolute inset-0 flex items-center justify-center"
          >
            <div class="card text-center space-y-3 p-8 max-w-sm bg-white/5 border-white/10">
              <span class="icon-[lucide--git-branch] text-5xl text-muted-foreground block" />
              <p class="text-sm text-white/60">
                该仓库暂无图谱数据
              </p>
              <p class="text-xs text-white/40">
                请先构建代码图谱，或调整节点类型过滤
              </p>
            </div>
          </div>

          <!-- 图谱 -->
          <template v-else>
            <GalaxySigmaGraph
              ref="graphRef"
              :nodes="nodes"
              :edges="edges"
              :loading="loading"
              :active-node-types="activeNodeTypes"
              :active-edge-types="activeEdgeTypes"
              :selected-node-id="drawerOpen ? selectedNodeId : null"
              class="w-full h-full"
              @node-click="handleNodeClick"
              @fps-update="onFpsUpdate"
            />

            <!-- 采样提示 -->
            <div
              v-if="meta?.sampled"
              class="absolute top-4 left-1/2 -translate-x-1/2 z-20"
            >
              <div class="glass-card rounded-xl px-4 py-2 text-xs text-amber-300/90 flex items-center gap-2">
                <span class="icon-[lucide--alert-triangle] text-amber-400" />
                共 {{ meta.total_nodes }} 个节点，已采样 top-{{ maxNodes }}（按 degree 排序）
              </div>
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
                @refresh="loadGraph"
              />
            </div>

            <!-- 图例（左下） -->
            <div class="absolute bottom-4 left-4 z-10">
              <GalaxyLegend />
            </div>
          </template>
        </div>

        <!-- Cmd+K 搜索 -->
        <GalaxyCommandPalette
          v-model="commandPaletteOpen"
          :nodes="filteredNodes"
          @node-select="handleCommandPaletteSelect"
        />

        <!-- 节点详情 Drawer -->
        <NodeDetailDrawer
          :node-id="selectedNodeId"
          :model-value="drawerOpen"
          @update:model-value="handleDrawerClose"
          @node-select="openNode"
        />
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.galaxy-modal-fade-enter-active,
.galaxy-modal-fade-leave-active {
  transition: opacity 0.2s ease;
}

.galaxy-modal-fade-enter-from,
.galaxy-modal-fade-leave-to {
  opacity: 0;
}
</style>
