<route lang="yaml">
meta:
 requiresAdmin: true
 title: Galaxy 代码图谱
</route>
<script setup lang="ts">
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
import type { Repository } from '~/types'
import { repositoriesApi } from '~/api/repositories'
import GalaxyCommandPalette from '~/components/galaxy/GalaxyCommandPalette.vue'
import GalaxyControls from '~/components/galaxy/GalaxyControls.vue'
import GalaxyForceGraph from '~/components/galaxy/GalaxyForceGraph.vue'
import GalaxyLegend from '~/components/galaxy/GalaxyLegend.vue'
import NodeDetailDrawer from '~/components/galaxy/NodeDetailDrawer.vue'
import { useGalaxyGraph } from '~/composables/useGalaxyGraph'
import { useToast } from '~/composables/useToast'
import { computed, defineAsyncComponent, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
// 备选引擎：lazy import（不增 main bundle）
const EchartsGraphGl = defineAsyncComponent( =>
 import('~/components/galaxy/EchartsGraphGl.vue'),
)
const route = useRoute
const router = useRouter
const { warning: toastWarning, error: toastError } = useToast
const {
 meta,
 loading,
 error,
 renderMode,
 maxNodes,
 fps,
 lowFpsDetected,
 activeNodeTypes,
 activeEdgeTypes,
 filteredNodes,
 filteredEdges,
 fetchGraph,
 setRenderMode,
 onFpsUpdate,
 toggleNodeType,
 toggleEdgeType,
 setAllNodeTypes,
 setAllEdgeTypes,
} = useGalaxyGraph
// 仓库选择
const repositories = ref<Repository>
const selectedRepoIds = ref<string>
const repositoriesLoading = ref(false)
// 移动端检测
const isMobile = computed( => typeof window !== 'undefined' && window.innerWidth < 1024)
// 低帧率 Toast（只提示一次）
const hasShownFpsWarning = ref(false)
watch(lowFpsDetected, (val) => {
 if (val && !hasShownFpsWarning.value) {
 hasShownFpsWarning.value = true
 toastWarning('帧率较低', '检测到帧率持续 < 30 FPS，建议切换到 ECharts 高性能模式 ⚡')
 }
})
// ============================================================================
// Phase: NodeDetailDrawer + CommandPalette 状态
// ============================================================================
const graphRef = ref<InstanceType<typeof GalaxyForceGraph> | null>(null)
const selectedNodeId = ref<string | null>(null)
const drawerOpen = ref(false)
const commandPaletteOpen = ref(false)
function openNode(nodeId: string) {
 selectedNodeId.value = nodeId
 drawerOpen.value = true
 router.replace({ query: { ...route.query, node: nodeId } })
 // 中心化定位（需等 tick 后 graphRef 可能已就绪）
 nextTick( => {
 graphRef.value?.focusNode(nodeId)
 })
}
function handleNodeClick(node: GalaxyNode) {
 openNode(node.id)
}
function handleCommandPaletteSelect(result: GalaxySearchResult) {
 openNode(result.id)
}
function handleDrawerClose(open: boolean) {
 if (!open) {
 drawerOpen.value = false
 router.replace({ query: { ...route.query, node: undefined } })
 }
}
function handleDrawerNodeSelect(nodeId: string) {
 openNode(nodeId)
}
// 页面加载时读取 ?node= 参数，数据就绪后自动打开 Drawer
const urlNodeHandled = ref(false)
watch(filteredNodes, (nodes) => {
 if (urlNodeHandled.value || nodes.length === 0) return
 const urlNode = route.query.node as string | undefined
 if (urlNode) {
 urlNodeHandled.value = true
 openNode(urlNode)
 }
})
// Phase 测试钩子：暴露关键函数以便集成测试通过 vm 直接调用
defineExpose({
 openNode,
 handleNodeClick,
 handleCommandPaletteSelect,
 handleDrawerClose,
 handleDrawerNodeSelect,
 drawerOpen,
 selectedNodeId,
 commandPaletteOpen,
})
async function loadRepositories {
 repositoriesLoading.value = true
 try {
 repositories.value = await repositoriesApi.list
 // 默认选择全部仓库
 selectedRepoIds.value = repositories.value.map(r => r.id)
 if (selectedRepoIds.value.length > 0) {
 await fetchGraph(selectedRepoIds.value)
 }
 }
 catch (e: unknown) {
 const msg = e instanceof Error ? e.message: '加载仓库列表失败'
 toastError('加载失败', msg)
 }
 finally {
 repositoriesLoading.value = false
 }
}
async function handleRefresh {
 if (selectedRepoIds.value.length > 0) {
 await fetchGraph(selectedRepoIds.value)
 }
}
async function handleMaxNodesUpdate(value: number) {
 maxNodes.value = value
 if (selectedRepoIds.value.length > 0) {
 await fetchGraph(selectedRepoIds.value)
 }
}
onMounted( => {
 loadRepositories
})
</script>
<template>
 <div class="flex flex-col h-screen bg-[#0a0a1f] overflow-hidden">
 <!-- 移动端 fallback -->
 <div
 v-if="isMobile"
 class="flex-1 flex items-center justify-center"
 >
 <div class="card text-center space-y-3 max-w-sm">
 <span class="icon-[lucide--monitor] text-5xl text-muted-foreground block" />
 <p class="text-sm text-muted-foreground">
 3D Galaxy 图谱需要桌面端访问
 </p>
 <p class="text-xs text-muted-foreground/60">
 请在 ≥ 1024px 宽度的浏览器中访问
 </p>
 </div>
 </div>
 <!-- 主视图（桌面端） -->
 <template v-else>
 <!-- 加载仓库时的全屏 loading -->
 <div
 v-if="repositoriesLoading"
 class="flex-1 flex items-center justify-center"
 >
 <div class="flex flex-col items-center gap-4 text-white">
 <span class="icon-[lucide--loader-circle] text-5xl animate-spin text-primary" />
 <span class="text-sm text-white/60">加载 Galaxy 图谱...</span>
 </div>
 </div>
 <!-- 空状态 -->
 <div
 v-else-if="!loading && filteredNodes.length === 0 && !error"
 class="flex-1 flex items-center justify-center"
 >
 <div class="card text-center space-y-3 max-w-sm bg-white/5 border-white/10">
 <span class="icon-[lucide--git-branch] text-5xl text-muted-foreground block" />
 <p class="text-sm text-white/60">
 暂无图谱数据
 </p>
 <p class="text-xs text-white/40">
 请先为仓库建立索引，或调整节点类型过滤
 </p>
 </div>
 </div>
 <!-- 错误状态 -->
 <div
 v-else-if="error"
 class="flex-1 flex items-center justify-center"
 >
 <div class="card text-center space-y-3 max-w-sm bg-white/5 border-red-500/20">
 <span class="icon-[lucide--alert-circle] text-5xl text-destructive block" />
 <p class="text-sm text-destructive">
 {{ error }}
 </p>
 <button class="btn btn-primary text-sm" @click="handleRefresh">
 重试
 </button>
 </div>
 </div>
 <!-- 3D 图谱主体 -->
 <div
 v-else
 class="flex-1 relative overflow-hidden"
 >
 <!-- 渲染引擎 -->
 <GalaxyForceGraph
 v-if="renderMode === 'force3d'"
 ref="graphRef":nodes="filteredNodes":edges="filteredEdges":loading="loading"
 class="w-full h-full"
 @node-click="handleNodeClick"
 @fps-update="onFpsUpdate"
 />
 <Suspense v-else>
 <component:is="EchartsGraphGl":nodes="filteredNodes":edges="filteredEdges":loading="loading"
 class="w-full h-full"
 @node-click="handleNodeClick"
 @fps-update="onFpsUpdate"
 />
 <template #fallback>
 <div class="flex-1 flex items-center justify-center">
 <span class="icon-[lucide--loader-circle] text-4xl animate-spin text-primary" />
 </div>
 </template>
 </Suspense>
 <!-- 采样提示 banner -->
 <Transition name="slide-down">
 <div
 v-if="meta?.sampled"
 class="absolute top-4 left-1/2 -translate-x-1/2 z-20"
 >
 <div class="glass-card rounded-xl px-4 py-2 text-xs text-amber-300/90 flex items-center gap-2">
 <span class="icon-[lucide--alert-triangle] text-amber-400" />
 共 {{ meta.total_nodes }} 个节点，已采样 top-{{ maxNodes }}（按 degree 排序）
 </div>
 </div>
 </Transition>
 <!-- 控制面板（右上角） -->
 <div class="absolute top-4 right-4 z-10">
 <GalaxyControls:max-nodes="maxNodes":fps="fps":low-fps-detected="lowFpsDetected":render-mode="renderMode":meta="meta":active-node-types="activeNodeTypes":active-edge-types="activeEdgeTypes"
 @update:max-nodes="handleMaxNodesUpdate"
 @update:render-mode="setRenderMode"
 @toggle-node-type="toggleNodeType"
 @toggle-edge-type="toggleEdgeType"
 @set-all-node-types="setAllNodeTypes"
 @set-all-edge-types="setAllEdgeTypes"
 @refresh="handleRefresh"
 />
 </div>
 <!-- 图例面板（左下角） -->
 <div class="absolute bottom-4 left-4 z-10">
 <GalaxyLegend />
 </div>
 <!-- Cmd+K 快捷键提示（左上角，半透明） -->
 <div class="absolute top-4 left-4 z-10">
 <div class="glass-card rounded-lg px-3 py-1.5 text-white/30 text-xs flex items-center gap-1.5">
 <kbd class="font-mono text-[10px]">⌘K</kbd>
 <span>搜索节点</span>
 </div>
 </div>
 </div>
 </template>
 <!-- Phase: Cmd+K 全局搜索面板 -->
 <GalaxyCommandPalette
 v-model="commandPaletteOpen":nodes="filteredNodes"
 @node-select="handleCommandPaletteSelect"
 />
 <!-- Phase: 节点详情 Drawer -->
 <NodeDetailDrawer:node-id="selectedNodeId":model-value="drawerOpen"
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
