<script setup lang="ts">
/**
 * Galaxy 统一渲染组件（Sigma.js WebGL 2D）
 *
 * 替代旧的 GalaxyForceGraph（3d-force-graph）/ EchartsGraphGl 双引擎：
 * - circles-layout 确定性初始布局，首屏即成型不抖动
 * - FA2 Web Worker 短时精修，主线程零阻塞
 * - 类型过滤走 reducer hidden，切换不重建图、不丢布局
 */
import type { GalaxyEdgeType, GalaxyNodeType } from '~/api/galaxy'
import type { GalaxyGraphEdge, GalaxyGraphNode } from '~/lib/galaxy/graph-adapter'
import { computed, onMounted, ref, watch } from 'vue'
import { useGalaxySigma } from '~/composables/useGalaxySigma'
import { buildGalaxyGraph } from '~/lib/galaxy/graph-adapter'

const props = withDefaults(defineProps<{
  nodes: GalaxyGraphNode[]
  edges: GalaxyGraphEdge[]
  loading?: boolean
  activeNodeTypes?: Set<GalaxyNodeType> | null
  activeEdgeTypes?: Set<GalaxyEdgeType> | null
  selectedNodeId?: string | null
}>(), {
  loading: false,
  activeNodeTypes: null,
  activeEdgeTypes: null,
  selectedNodeId: null,
})

const emit = defineEmits<{
  (e: 'node-click', node: GalaxyGraphNode): void
  (e: 'node-hover', node: GalaxyGraphNode | null): void
  (e: 'fps-update', fps: number): void
  (e: 'ready'): void
}>()

const containerRef = ref<HTMLDivElement | null>(null)

// O(1) 节点查找（替代旧实现中每次 hover 的 O(n) find）
const nodeById = computed(() => {
  const map = new Map<string, GalaxyGraphNode>()
  for (const node of props.nodes)
    map.set(node.id, node)
  return map
})

const engine = useGalaxySigma({
  onNodeClick: (nodeId) => {
    const node = nodeById.value.get(nodeId)
    if (node)
      emit('node-click', node)
  },
  onNodeHover: (nodeId) => {
    emit('node-hover', nodeId ? nodeById.value.get(nodeId) ?? null : null)
  },
  onFpsUpdate: fps => emit('fps-update', fps),
})

const { layoutRunning } = engine
let initialized = false

function syncGraph(): void {
  if (!containerRef.value)
    return
  const graph = buildGalaxyGraph(props.nodes, props.edges)
  if (!initialized) {
    engine.init(containerRef.value, graph)
    initialized = true
    engine.setVisibleTypes(props.activeNodeTypes, props.activeEdgeTypes)
    emit('ready')
  }
  else {
    engine.setGraph(graph)
  }
}

onMounted(() => {
  if (props.nodes.length > 0)
    syncGraph()
})

watch(
  [() => props.nodes, () => props.edges],
  () => { syncGraph() },
  { deep: false },
)

watch(
  [() => props.activeNodeTypes, () => props.activeEdgeTypes],
  ([nodeTypes, edgeTypes]) => {
    engine.setVisibleTypes(nodeTypes ?? null, edgeTypes ?? null)
  },
  { deep: false },
)

watch(
  () => props.selectedNodeId,
  (nodeId) => { engine.setSelectedNode(nodeId ?? null) },
)

defineExpose({
  focusNode: (nodeId: string) => engine.focusNode(nodeId),
  zoomIn: () => engine.zoomIn(),
  zoomOut: () => engine.zoomOut(),
  resetCamera: () => engine.resetCamera(),
  runLayout: () => engine.runLayout(),
})
</script>

<template>
  <div class="relative w-full h-full">
    <div
      ref="containerRef"
      class="w-full h-full"
      role="img"
      aria-label="代码依赖关系 Galaxy 图谱"
    />

    <!-- 布局精修指示（不遮挡，仅提示） -->
    <Transition name="fade">
      <div
        v-if="layoutRunning"
        class="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 pointer-events-none"
      >
        <div class="glass-card rounded-full px-3 py-1.5 text-xs text-white/60 flex items-center gap-2">
          <span class="icon-[lucide--orbit] animate-spin text-primary" />
          <span>布局优化中…</span>
        </div>
      </div>
    </Transition>

    <!-- 相机控制（右下） -->
    <div class="absolute bottom-4 right-4 z-10 flex flex-col gap-1">
      <button
        type="button"
        class="galaxy-cam-btn"
        title="放大"
        aria-label="放大"
        @click="engine.zoomIn()"
      >
        <span class="icon-[lucide--plus]" />
      </button>
      <button
        type="button"
        class="galaxy-cam-btn"
        title="缩小"
        aria-label="缩小"
        @click="engine.zoomOut()"
      >
        <span class="icon-[lucide--minus]" />
      </button>
      <button
        type="button"
        class="galaxy-cam-btn"
        title="复位视野"
        aria-label="复位视野"
        @click="engine.resetCamera()"
      >
        <span class="icon-[lucide--maximize]" />
      </button>
      <button
        type="button"
        class="galaxy-cam-btn"
        title="重新布局"
        aria-label="重新布局"
        @click="engine.runLayout()"
      >
        <span class="icon-[lucide--refresh-cw]" />
      </button>
    </div>

    <!-- Loading 覆盖层 -->
    <Transition name="fade">
      <div
        v-if="loading"
        class="absolute inset-0 flex items-center justify-center bg-[#0a0a1f]/70 backdrop-blur-sm"
      >
        <div class="flex flex-col items-center gap-3 text-white">
          <span class="icon-[lucide--loader-circle] text-4xl animate-spin text-primary" />
          <span class="text-sm text-white/70">加载 Galaxy 图谱...</span>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.galaxy-cam-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid rgb(255 255 255 / 0.1);
  background: rgb(13 14 28 / 0.75);
  backdrop-filter: blur(8px);
  color: rgb(255 255 255 / 0.65);
  font-size: 14px;
  transition: all 0.15s ease;
}

.galaxy-cam-btn:hover {
  background: rgb(255 255 255 / 0.1);
  color: rgb(255 255 255 / 0.95);
  border-color: rgb(255 255 255 / 0.2);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
