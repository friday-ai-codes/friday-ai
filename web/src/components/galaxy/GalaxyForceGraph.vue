<script setup lang="ts">
import type { NodeObject } from '3d-force-graph'
import type { GalaxyEdge, GalaxyNode } from '~/api/galaxy'
import ForceGraph3D from '3d-force-graph'
import * as THREE from 'three'
import { onMounted, onUnmounted, ref, watch } from 'vue'
// ============================================================================
// Props / Emits（两引擎统一契约）
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
// State
// ============================================================================
const containerRef = ref<HTMLDivElement | null>(null)
type GraphInstance = ReturnType<ReturnType<typeof ForceGraph3D>>
let graph: GraphInstance | null = null
let resizeObserver: ResizeObserver | null = null
let animFrameId = 0
let fpsFrameCount = 0
let fpsLastTime = performance.now
let fpsStarted = false
// 邻居 map：nodeId → Set<neighborId>（hover 高亮用）
const neighborMap = new Map<string, Set<string>>
// 节点 opacity 原始值（hover 恢复用）
const NODE_DEFAULT_OPACITY = 1.0
const NODE_DIM_OPACITY = 0.15
const HOVER_DEBOUNCE_MS = 100
let hoverTimer: ReturnType<typeof setTimeout> | null = null
// ============================================================================
// 视觉编码常量
// ============================================================================
const NODE_COLORS: Record<string, string> = {
 chunk_registry: '#c0c0c0',
 symbol: '#4a90e2',
 endpoint: '#ff8c42',
 api_wrapper: '#50e3a4',
 api_call_site: '#00d4ff',
}
const NODE_SIZES: Record<string, number> = {
 chunk_registry: 4,
 symbol: 5,
 endpoint: 6,
 api_wrapper: 6,
 api_call_site: 3.5,
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
const EDGE_WIDTHS: Record<string, number> = {
 CALL: 1.5,
 IMPORT: 1.2,
 SAME_FILE: 0.8,
 TEST_OF: 1.5,
 CO_CHANGED: 1.2,
 SEMANTIC: 1.0,
 API_CALLS: 2.0,
 IMPLEMENTS: 1.2,
}
const EDGE_OPACITIES: Record<string, number> = {
 CALL: 0.8,
 IMPORT: 0.7,
 SAME_FILE: 0.3,
 TEST_OF: 0.8,
 CO_CHANGED: 0.6,
 SEMANTIC: 0.5,
 API_CALLS: 1.0,
 IMPLEMENTS: 0.7,
}
// ============================================================================
// 节点 Three.js 对象工厂
// ============================================================================
interface GalaxyNodeObject extends NodeObject {
 id: string
 type: string
 __galaxy_node?: GalaxyNode
}
interface GalaxyLinkObject {
 id: string
 source: string | GalaxyNodeObject
 target: string | GalaxyNodeObject
 edge_type: string
}
function createNodeObject(node: GalaxyNodeObject): THREE.Object3D {
 const type = node.type ?? 'chunk_registry'
 const color = new THREE.Color(NODE_COLORS[type] ?? '#c0c0c0')
 const size = NODE_SIZES[type] ?? 4
 const group = new THREE.Group
 const sphere = new THREE.Mesh(
 new THREE.SphereGeometry(size, 16, 16),
 new THREE.MeshBasicMaterial({
 color,
 transparent: true,
 opacity: NODE_DEFAULT_OPACITY,
 }),
 )
 group.add(sphere)
 // endpoint: 单发光环
 if (type === 'endpoint') {
 const ring = createRing(size + 1.5, size + 2.5, color)
 group.add(ring)
 }
 // api_wrapper: 双发光环
 if (type === 'api_wrapper') {
 const ring1 = createRing(size + 1.5, size + 2.5, color)
 const ring2 = createRing(size + 3, size + 4, color, 0.5)
 group.add(ring1, ring2)
 }
 return group
}
function createRing(innerR: number, outerR: number, color: THREE.Color, opacity = 0.8): THREE.Mesh {
 return new THREE.Mesh(
 new THREE.RingGeometry(innerR, outerR, 32),
 new THREE.MeshBasicMaterial({
 color,
 side: THREE.DoubleSide,
 transparent: true,
 opacity,
 }),
 )
}
// ============================================================================
// 太空背景
// ============================================================================
function setupSpaceBackground(scene: THREE.Scene): void {
 // 渐变背景纹理
 const canvas = document.createElement('canvas')
 canvas.width = 2
 canvas.height = 512
 const ctx = canvas.getContext('2d')
 if (ctx) {
 const gradient = ctx.createLinearGradient(0, 0, 0, 512)
 gradient.addColorStop(0, '#0a0a1f')
 gradient.addColorStop(0.5, '#1a0a2e')
 gradient.addColorStop(1, '#0f1a2e')
 ctx.fillStyle = gradient
 ctx.fillRect(0, 0, 2, 512)
 scene.background = new THREE.CanvasTexture(canvas)
 }
 // 星点粒子
 const starsGeometry = new THREE.BufferGeometry
 const starPositions = new Float32Array(1000 * 3)
 for (let i = 0; i < 1000 * 3; i++) {
 starPositions[i] = (Math.random - 0.5) * 2000
 }
 starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3))
 const starsMaterial = new THREE.PointsMaterial({
 color: 0xFFFFFF,
 size: 0.5,
 transparent: true,
 opacity: 0.6,
 })
 const stars = new THREE.Points(starsGeometry, starsMaterial)
 scene.add(stars)
}
// ============================================================================
// 邻居 Lookup 构建
// ============================================================================
function buildNeighborLookup: void {
 neighborMap.clear
 props.edges.forEach((edge) => {
 if (!neighborMap.has(edge.source))
 neighborMap.set(edge.source, new Set)
 if (!neighborMap.has(edge.target))
 neighborMap.set(edge.target, new Set)
 neighborMap.get(edge.source)!.add(edge.target)
 neighborMap.get(edge.target)!.add(edge.source)
 })
}
// ============================================================================
// 全部节点 opacity 更新
// ============================================================================
function setAllNodesOpacity(opacity: number): void {
 if (!graph)
 return
 graph.graphData.nodes.forEach((n: GalaxyNodeObject) => {
 const obj = graph!.nodeThreeObject(n) as THREE.Group | null
 if (!obj)
 return
 obj.traverse((child) => {
 if (child instanceof THREE.Mesh && child.material instanceof THREE.Material) {
 child.material.opacity = opacity
 }
 })
 })
}
function updateHoverHighlight(hoveredId: string | null): void {
 if (!graph)
 return
 graph.graphData.nodes.forEach((n: GalaxyNodeObject) => {
 const isNeighbor
 = hoveredId === null
 || n.id === hoveredId
 || neighborMap.get(hoveredId)?.has(n.id)
 const targetOpacity = isNeighbor ? NODE_DEFAULT_OPACITY: NODE_DIM_OPACITY
 const obj = n.__threeObj as THREE.Group | undefined
 if (!obj)
 return
 obj.traverse((child) => {
 if (child instanceof THREE.Mesh && child.material instanceof THREE.Material) {
 child.material.opacity = targetOpacity
 }
 })
 })
}
// ============================================================================
// FPS 监控
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
function startFpsMonitor: void {
 if (fpsStarted)
 return
 fpsStarted = true
 setTimeout( => {
 fpsLastTime = performance.now
 fpsFrameCount = 0
 animFrameId = requestAnimationFrame(measureFps)
 }, 3000)
}
// ============================================================================
// 图数据更新
// ============================================================================
function buildGraphData {
 return {
 nodes: props.nodes.map(n => ({
 ...n,
 id: n.id,
 })),
 links: props.edges.map(e => ({
 ...e,
 source: e.source,
 target: e.target,
 })),
 }
}
function updateGraphData: void {
 if (!graph)
 return
 buildNeighborLookup
 graph.graphData(buildGraphData)
}
// ============================================================================
// 图初始化
// ============================================================================
function initGraph: void {
 if (!containerRef.value)
 return
 const el = containerRef.value
 graph = ForceGraph3D({ controlType: 'orbit' })(el)
 .width(el.clientWidth)
 .height(el.clientHeight)
 .showNavInfo(false)
 .backgroundColor('transparent')
 // 节点自定义 Three.js 对象
 .nodeThreeObject((node: NodeObject) => createNodeObject(node as GalaxyNodeObject))
 .nodeThreeObjectExtend(false)
 // 节点 label（tooltip）
 .nodeLabel((node: NodeObject) => {
 const n = node as GalaxyNodeObject & { __galaxy_node?: GalaxyNode }
 const gn = props.nodes.find(x => x.id === n.id)
 if (!gn)
 return ''
 return `<div style="background:rgba(10,10,31,0.85);border:1px solid rgba(255,255,255,0.15);padding:6px 10px;border-radius:6px;backdrop-filter:blur(4px);color:#fff;font-size:12px;line-height:1.6">
 <strong>${gn.label}</strong><br/>
 <span style="opacity:0.7">${gn.type}</span><br/>
 <span style="opacity:0.7">${gn.file_path}</span><br/>
 degree: ${gn.degree}
 </div>`
 })
 // 边颜色
 .linkColor((link) => {
 const l = link as GalaxyLinkObject
 return EDGE_COLORS[l.edge_type] ?? '#ffffff'
 })
 .linkWidth((link) => {
 const l = link as GalaxyLinkObject
 return EDGE_WIDTHS[l.edge_type] ?? 1
 })
 .linkOpacity(0.7)
 // API_CALLS 粒子流动动画
 .linkParticles((link) => {
 const l = link as GalaxyLinkObject
 return l.edge_type === 'API_CALLS' ? 5: 0
 })
 .linkParticleSpeed(0.006)
 .linkParticleColor((link) => {
 const l = link as GalaxyLinkObject
 return EDGE_COLORS[l.edge_type] ?? '#ff4444'
 })
 // hover 回调（带防抖）
 .onNodeHover((node) => {
 if (hoverTimer)
 clearTimeout(hoverTimer)
 hoverTimer = setTimeout( => {
 const n = node as GalaxyNodeObject | null
 const gNode = n ? props.nodes.find(x => x.id === n.id) ?? null: null
 emit('node-hover', gNode)
 updateHoverHighlight(n?.id ?? null)
 }, HOVER_DEBOUNCE_MS)
 })
 // click 回调
 .onNodeClick((node) => {
 const n = node as GalaxyNodeObject
 const gNode = props.nodes.find(x => x.id === n.id)
 if (gNode)
 emit('node-click', gNode)
 })
 // 力参数调优
 .d3Force('charge', null)
 .cooldownTicks(200)
 .onEngineStop( => {
 // 布局稳定后设置太空背景 + camera
 const scene = graph!.scene
 setupSpaceBackground(scene)
 graph!.cameraPosition({ x: 0, y: 100, z: 300 }, { x: 0, y: 0, z: 0 }, 0)
 emit('ready')
 startFpsMonitor
 })
 // 重新添加 charge 力（默认配置）
 graph.d3Force('charge', (graph as unknown as { d3Force: (name: string, force?: unknown) => unknown }).d3Force('charge'))
 // 设置初始数据
 buildNeighborLookup
 graph.graphData(buildGraphData)
 // ResizeObserver
 resizeObserver = new ResizeObserver( => {
 if (graph && el) {
 graph.width(el.clientWidth).height(el.clientHeight)
 }
 })
 resizeObserver.observe(el)
}
// ============================================================================
// cleanup
// ============================================================================
function cleanup: void {
 if (hoverTimer)
 clearTimeout(hoverTimer)
 resizeObserver?.disconnect
 cancelAnimationFrame(animFrameId)
 if (graph) {
 graph._destructor
 graph = null
 }
 fpsStarted = false
}
// ============================================================================
// 生命周期
// ============================================================================
onMounted( => { initGraph })
onUnmounted( => { cleanup })
// shallow watch — 节点/边数组引用变化时更新（节点内容变化交由父组件传新数组）
watch(
 [ => props.nodes, => props.edges],
 => { updateGraphData },
 { deep: false },
)
</script>
<template>
 <div class="relative w-full h-full">
 <!-- 3d-force-graph canvas 容器 -->
 <div
 ref="containerRef"
 class="w-full h-full"
 role="img"
 aria-label="代码依赖关系 3D 银河图"
 />
 <!-- Loading overlay -->
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
