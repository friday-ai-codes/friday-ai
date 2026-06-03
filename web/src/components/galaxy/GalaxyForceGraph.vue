<script setup lang="ts">
import type { ForceGraph3DInstance, NodeObject } from '3d-force-graph'
import type { GalaxyEdge, GalaxyNode, GalaxyRepoEdge, GalaxyRepoNode } from '~/api/galaxy'
import ForceGraph3D from '3d-force-graph'
import * as THREE from 'three'
import { onMounted, onUnmounted, ref, watch } from 'vue'
type GalaxyGraphNode = GalaxyNode | GalaxyRepoNode
type GalaxyGraphEdge = GalaxyEdge | GalaxyRepoEdge
// ============================================================================
// Props / Emits（两引擎统一契约）
// ============================================================================
const props = withDefaults(defineProps<{
 nodes: GalaxyGraphNode
 edges: GalaxyGraphEdge
 loading?: boolean
}>, { loading: false })
const emit = defineEmits<{
 (e: 'node-click', node: GalaxyGraphNode): void
 (e: 'node-hover', node: GalaxyGraphNode | null): void
 (e: 'fps-update', fps: number): void
 (e: 'ready'): void
}>
// ============================================================================
// 内部扩展类型（与 3d-force-graph 的 NodeObject 兼容）
// ============================================================================
interface GalaxyNodeObject extends NodeObject {
 id: string
 type?: string
 label?: string
 file_path?: string
 degree?: number
 // 3d-force-graph 内部注入的 Three.js 对象引用
 __threeObj?: THREE.Object3D
}
// ============================================================================
// State
// ============================================================================
const containerRef = ref<HTMLDivElement | null>(null)
type GraphType = ForceGraph3DInstance<GalaxyNodeObject, GalaxyGraphEdge>
type ForceGraph3DConstructor = new (
 element: HTMLElement,
 config?: Record<string, unknown>,
) => GraphType
let graph: GraphType | null = null
let resizeObserver: ResizeObserver | null = null
let animFrameId = 0
let fpsFrameCount = 0
let fpsLastTime = performance.now
let fpsStarted = false
const neighborMap = new Map<string, Set<string>>
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
 repository: '#ffd166',
}
const NODE_SIZES: Record<string, number> = {
 chunk_registry: 4,
 symbol: 5,
 endpoint: 6,
 api_wrapper: 6,
 api_call_site: 3.5,
 repository: 12,
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
 REPO_API_CALL: '#ff6b9d',
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
 REPO_API_CALL: 2.5,
}
// ============================================================================
// 节点 Three.js 对象工厂
// ============================================================================
function createNodeObject(node: NodeObject): THREE.Object3D {
 const n = node as GalaxyNodeObject
 const type = n.type ?? 'chunk_registry'
 const color = new THREE.Color(NODE_COLORS[type] ?? '#c0c0c0')
 const size = NODE_SIZES[type] ?? 4
 const group = new THREE.Group
 const sphere = new THREE.Mesh(
 new THREE.SphereGeometry(size, 16, 16),
 new THREE.MeshBasicMaterial({ color, transparent: true, opacity: NODE_DEFAULT_OPACITY }),
 )
 group.add(sphere)
 if (type === 'endpoint') {
 group.add(createRing(size + 1.5, size + 2.5, color))
 }
 else if (type === 'api_wrapper') {
 group.add(createRing(size + 1.5, size + 2.5, color))
 group.add(createRing(size + 3, size + 4, color, 0.5))
 }
 else if (type === 'repository') {
 // 仓库节点：双环 + 微光晕，强化"星系核心"感
 group.add(createRing(size + 2, size + 3, color, 0.9))
 group.add(createRing(size + 5, size + 6.5, color, 0.4))
 }
 return group
}
function createRing(innerR: number, outerR: number, color: THREE.Color, opacity = 0.8): THREE.Mesh {
 return new THREE.Mesh(
 new THREE.RingGeometry(innerR, outerR, 32),
 new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, transparent: true, opacity }),
 )
}
// ============================================================================
// 太空背景
// ============================================================================
function setupSpaceBackground(scene: THREE.Scene): void {
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
 const starsGeometry = new THREE.BufferGeometry
 const starPositions = new Float32Array(1000 * 3)
 for (let i = 0; i < 1000 * 3; i++) {
 starPositions[i] = (Math.random - 0.5) * 2000
 }
 starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3))
 const stars = new THREE.Points(
 starsGeometry,
 new THREE.PointsMaterial({ color: 0xFFFFFF, size: 0.5, transparent: true, opacity: 0.6 }),
 )
 scene.add(stars)
}
// ============================================================================
// 邻居 Lookup + hover 高亮
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
function updateHoverHighlight(hoveredId: string | null): void {
 if (!graph)
 return
 graph.graphData.nodes.forEach((n: GalaxyNodeObject) => {
 const isNeighbor
 = hoveredId === null
 || n.id === hoveredId
 || neighborMap.get(hoveredId)?.has(n.id)
 const targetOpacity = isNeighbor ? NODE_DEFAULT_OPACITY: NODE_DIM_OPACITY
 const obj = n.__threeObj
 if (!obj)
 return
 obj.traverse((child) => {
 if (child instanceof THREE.Mesh && child.material instanceof THREE.Material) {
 (child.material as THREE.MeshBasicMaterial).opacity = targetOpacity
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
 // eslint-disable-next-line vue/custom-event-name-casing -- 父组件契约使用 kebab-case
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
// 图数据
// ============================================================================
function buildGraphData {
 return {
 nodes: props.nodes.map(n => ({ ...n })),
 links: props.edges.map(e => ({ ...e, source: e.source, target: e.target })),
 }
}
function updateGraphData: void {
 if (!graph)
 return
 buildNeighborLookup
 graph.graphData(buildGraphData)
}
// ============================================================================
// 初始化
// ============================================================================
function getEdgeType(link: Pick<GalaxyGraphEdge, 'edge_type'>): string {
 return link.edge_type ?? ''
}
function escapeHtml(value: unknown): string {
 return String(value ?? '')
 .replaceAll('&', '&amp;')
 .replaceAll('<', '&lt;')
 .replaceAll('>', '&gt;')
 .replaceAll('"', '&quot;')
 .replaceAll('\'', '&#39;')
}
function formatNodeLabel(node: GalaxyNodeObject): string {
 const source = props.nodes.find(x => x.id === node.id) ?? node
 const label = escapeHtml(source.label ?? node.id)
 const type = escapeHtml(source.type ?? 'unknown')
 const filePath = escapeHtml(source.file_path ?? '')
 const degree = escapeHtml(source.degree ?? '—')
 return `<div style="background:rgba(10,10,31,0.85);border:1px solid rgba(255,255,255,0.15);padding:6px 10px;border-radius:6px;backdrop-filter:blur(4px);color:#fff;font-size:12px;line-height:1.6">
 <strong>${label}</strong><br/>
 <span style="opacity:0.7">${type}</span><br/>
 <span style="opacity:0.7">${filePath}</span><br/>
 degree: ${degree}
 </div>`
}
function initGraph: void {
 if (!containerRef.value)
 return
 const el = containerRef.value
 // ForceGraph3D 的运行时 API 是可 new 的构造器，包类型声明没有直接暴露构造签名。
 const ForceGraphCtor = ForceGraph3D as unknown as ForceGraph3DConstructor
 const instance = new ForceGraphCtor(el, { controlType: 'orbit' })
 instance.width(el.clientWidth)
 .height(el.clientHeight)
 .showNavInfo(false)
 .backgroundColor('rgba(0,0,0,0)')
 .nodeThreeObject(createNodeObject)
 .nodeThreeObjectExtend(false)
 .nodeLabel((node: NodeObject) => {
 return formatNodeLabel(node as GalaxyNodeObject)
 })
 .linkColor(link => EDGE_COLORS[getEdgeType(link)] ?? '#ffffff')
 .linkWidth(link => EDGE_WIDTHS[getEdgeType(link)] ?? 1)
 .linkOpacity(0.7)
 .linkDirectionalParticles((link) => {
 const t = getEdgeType(link)
 if (t === 'API_CALLS')
 return 5
 if (t === 'REPO_API_CALL')
 return 4
 return 0
 })
 .linkDirectionalParticleSpeed(0.006)
 .linkDirectionalParticleColor(link => EDGE_COLORS[getEdgeType(link)] ?? '#ff4444')
 .onNodeHover((node: NodeObject | null) => {
 if (hoverTimer)
 clearTimeout(hoverTimer)
 hoverTimer = setTimeout( => {
 const n = node as GalaxyNodeObject | null
 const gNode = n ? props.nodes.find(x => x.id === n.id) ?? null: null
 // eslint-disable-next-line vue/custom-event-name-casing -- 父组件契约使用 kebab-case
 emit('node-hover', gNode)
 updateHoverHighlight(n?.id ?? null)
 }, HOVER_DEBOUNCE_MS)
 })
 .onNodeClick((node: NodeObject) => {
 const n = node as GalaxyNodeObject
 const gNode = props.nodes.find(x => x.id === n.id)
 if (gNode) {
 // eslint-disable-next-line vue/custom-event-name-casing -- 父组件契约使用 kebab-case
 emit('node-click', gNode)
 }
 })
 .d3Force('charge', null)
 .warmupTicks(80)
 .cooldownTicks(60)
 .d3VelocityDecay(0.45)
 .onEngineStop( => {
 const scene = instance.scene
 setupSpaceBackground(scene)
 instance.cameraPosition({ x: 0, y: 100, z: 300 }, { x: 0, y: 0, z: 0 }, 0)
 emit('ready')
 startFpsMonitor
 })
 graph = instance
 buildNeighborLookup
 graph.graphData(buildGraphData)
 resizeObserver = new ResizeObserver( => {
 const g = graph
 if (g && el) {
 g.width(el.clientWidth).height(el.clientHeight)
 }
 })
 resizeObserver.observe(el)
}
// ============================================================================
// Cleanup
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
onMounted( => {
 initGraph
})
onUnmounted( => {
 cleanup
})
watch(
 [ => props.nodes, => props.edges],
 => { updateGraphData },
 { deep: false },
)
// ============================================================================
// defineExpose — 供父组件（galaxy.vue）调用中心化定位
// ============================================================================
defineExpose({
 focusNode(nodeId: string) {
 if (!graph)
 return
 const data = graph.graphData as { nodes: Array<GalaxyNodeObject & { x?: number, y?: number, z?: number }> }
 const target = data.nodes.find(n => n.id === nodeId)
 if (!target)
 return
 const x = target.x ?? 0
 const y = target.y ?? 0
 const z = (target.z ?? 0) + 150
 graph.cameraPosition({ x, y, z }, { x, y, z: z - 150 }, 1000)
 },
})
</script>
<template>
 <div class="relative w-full h-full">
 <div
 ref="containerRef"
 class="w-full h-full"
 role="img"
 aria-label="代码依赖关系 3D 银河图"
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
