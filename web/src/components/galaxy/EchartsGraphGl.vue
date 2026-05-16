<script setup lang="ts">
/**
 * ECharts GraphGL 备选引擎
 *
 * 与 GalaxyForceGraph.vue 保持完全一致的 Props/Emits 契约，
 * 通过 lazy import 按需加载，不增加 main bundle 体积。
 *
 * 性能优势：5000+ 节点 60+ FPS（vs 3d-force-graph 30-60 FPS）
 * 视觉局限：银河感（发光/粒子）效果不如 Three.js 版本
 */
import type { GalaxyEdge, GalaxyNode } from '~/api/galaxy'
import { computed, onMounted, onUnmounted, ref } from 'vue'
// ============================================================================
// Props / Emits（与 GalaxyForceGraph.vue 完全一致）
// ============================================================================
const props = withDefaults(defineProps<{
 nodes: GalaxyNode
 edges: GalaxyEdge
 loading?: boolean
}>, { loading: false })
const emit = defineEmits<{
 (e: 'node-click', node: GalaxyNode): void
 (e: 'node-hover', node: GalaxyNode | null): void
 (e: 'fps-update', fps: number): void
 (e: 'ready'): void
}>
// ============================================================================
// ECharts 动态 import
// ============================================================================
const chartRef = ref<HTMLDivElement | null>(null)
let echartsInstance: unknown = null
let animFrameId = 0
let fpsFrameCount = 0
let fpsLastTime = performance.now
const NODE_COLORS: Record<string, string> = {
 chunk_registry: '#c0c0c0',
 symbol: '#4a90e2',
 endpoint: '#ff8c42',
 api_wrapper: '#50e3a4',
 api_call_site: '#00d4ff',
}
const NODE_SIZES: Record<string, number> = {
 chunk_registry: 8,
 symbol: 10,
 endpoint: 14,
 api_wrapper: 14,
 api_call_site: 7,
}
const EDGE_COLORS: Record<string, string> = {
 CALL: '#4a90e2',
 IMPORT: '#50e3a4',
 SAME_FILE: '#555555',
 TEST_OF: '#ff8c42',
 CO_CHANGED: '#9b59b6',
 SEMANTIC: '#e91e63',
 API_CALLS: '#ff4444',
 IMPLEMENTS: '#7c3aed',
}
// ============================================================================
// ECharts option 构建
// ============================================================================
const chartOption = computed( => ({
 backgroundColor: '#0a0a1f',
 tooltip: {
 formatter: (params: Record<string, unknown>) => {
 if (params.dataType === 'node') {
 const data = params.data as { id?: string } | undefined
 if (!data?.id)
 return ''
 const node = props.nodes.find(n => n.id === data.id)
 if (!node)
 return ''
 return `<div style="color:#fff"><b>${node.label}</b><br/>${node.type}<br/>${node.file_path}</div>`
 }
 return ''
 },
 },
 series: [
 {
 type: 'graph',
 layout: 'force',
 animation: false,
 data: props.nodes.map(node => ({
 id: node.id,
 name: node.label,
 symbolSize: NODE_SIZES[node.type] ?? 10,
 itemStyle: {
 color: NODE_COLORS[node.type] ?? '#c0c0c0',
 },
 label: { show: false },
 })),
 links: props.edges.map(edge => ({
 id: edge.id,
 source: edge.source,
 target: edge.target,
 lineStyle: {
 color: EDGE_COLORS[edge.edge_type] ?? '#ffffff',
 width: edge.edge_type === 'API_CALLS' ? 2: 1,
 opacity: edge.edge_type === 'SAME_FILE' ? 0.3: 0.7,
 curveness: edge.edge_type === 'API_CALLS' ? 0.2: 0,
 },
 // API_CALLS 使用 effect 动画（近似粒子流动）
 ...(edge.edge_type === 'API_CALLS'
 ? {
 effect: {
 show: true,
 period: 4,
 trailLength: 0.4,
 color: '#ff4444',
 symbolSize: 5,
 },
 }: {}),
 })),
 roam: true,
 force: {
 repulsion: 80,
 gravity: 0.1,
 edgeLength: [50, 200],
 layoutAnimation: true,
 },
 emphasis: {
 focus: 'adjacency',
 lineStyle: { width: 2 },
 },
 },
 ],
}))
// ============================================================================
// FPS 监控（与 GalaxyForceGraph.vue 同逻辑）
// ============================================================================
function measureFps: void {
 fpsFrameCount++
 const now = performance.now
 if (now - fpsLastTime >= 1000) {
 const currentFps = Math.round(fpsFrameCount * 1000 / (now - fpsLastTime))
 fpsFrameCount = 0
 fpsLastTime = now
 emit('fps-update', currentFps)
 }
 animFrameId = requestAnimationFrame(measureFps)
}
// ============================================================================
// 生命周期
// ============================================================================
async function initChart {
 if (!chartRef.value)
 return
 try {
 const echarts = await import('echarts/core')
 const { CanvasRenderer } = await import('echarts/renderers')
 const { GraphChart } = await import('echarts/charts')
 const { TooltipComponent } = await import('echarts/components')
 // echarts-gl 需要 echarts 注册后才能注册 GL 功能
 // 如果 echarts-gl 不可用，降级到 2D graph
 echarts.use([CanvasRenderer, GraphChart, TooltipComponent])
 const instance = echarts.init(chartRef.value, null, {
 renderer: 'canvas',
 width: 'auto',
 height: 'auto',
 })
 echartsInstance = instance
 instance.setOption(chartOption.value)
 // 事件绑定
 instance.on('click', (params: Record<string, unknown>) => {
 if (params.dataType === 'node') {
 const data = params.data as { id?: string } | undefined
 if (data?.id) {
 const node = props.nodes.find(n => n.id === data.id)
 if (node)
 emit('node-click', node)
 }
 }
 })
 instance.on('mouseover', (params: Record<string, unknown>) => {
 if (params.dataType === 'node') {
 const data = params.data as { id?: string } | undefined
 if (data?.id) {
 const node = props.nodes.find(n => n.id === data.id)
 emit('node-hover', node ?? null)
 }
 }
 })
 instance.on('mouseout', => {
 emit('node-hover', null)
 })
 emit('ready')
 // FPS 监控（延迟 3s）
 setTimeout( => {
 fpsLastTime = performance.now
 animFrameId = requestAnimationFrame(measureFps)
 }, 3000)
 }
 catch (e) {
 console.error('[EchartsGraphGl] 初始化失败', e)
 }
}
function cleanup {
 cancelAnimationFrame(animFrameId)
 if (echartsInstance) {
 const inst = echartsInstance as { dispose: => void }
 inst.dispose
 echartsInstance = null
 }
}
onMounted( => { initChart })
onUnmounted( => { cleanup })
</script>
<template>
 <div class="relative w-full h-full">
 <div
 ref="chartRef"
 class="w-full h-full"
 role="img"
 aria-label="代码依赖关系银河图（ECharts 模式）"
 />
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
.fade-enter-active,
.fade-leave-active {
 transition: opacity 0.3s ease;
}
.fade-enter-from,
.fade-leave-to {
 opacity: 0;
}
</style>
