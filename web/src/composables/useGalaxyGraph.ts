import type { GalaxyEdge, GalaxyEdgeType, GalaxyMeta, GalaxyNode, GalaxyNodeType, GetGalaxyParams } from '~/api/galaxy'
import { computed, ref } from 'vue'
import { getGalaxyGraph } from '~/api/galaxy'
const RENDER_MODE_KEY = 'galaxy_render_mode'
const FPS_LOW_THRESHOLD = 30
const FPS_LOW_CONSECUTIVE_REQUIRED = 2
export type GalaxyRenderMode = 'force3d' | 'echarts'
export function useGalaxyGraph {
 const nodes = ref<GalaxyNode>
 const edges = ref<GalaxyEdge>
 const meta = ref<GalaxyMeta | null>(null)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // 渲染模式：从 localStorage 初始化
 const savedMode = localStorage.getItem(RENDER_MODE_KEY) as GalaxyRenderMode | null
 const renderMode = ref<GalaxyRenderMode>(savedMode ?? 'force3d')
 // 采样参数
 const maxNodes = ref(500)
 // 节点/边类型过滤（默认全选）
 const activeNodeTypes = ref<Set<GalaxyNodeType>>(
 new Set(['chunk_registry', 'symbol', 'endpoint', 'api_wrapper', 'api_call_site']),
 )
 const activeEdgeTypes = ref<Set<GalaxyEdgeType>>(
 new Set(['CALL', 'IMPORT', 'SAME_FILE', 'TEST_OF', 'CO_CHANGED', 'SEMANTIC', 'API_CALLS', 'IMPLEMENTS']),
 )
 // FPS 监控
 const fps = ref(60)
 let lowFpsCount = 0
 const lowFpsDetected = ref(false)
 // 前端过滤（不重拉 API，即时响应）
 const filteredNodes = computed( =>
 nodes.value.filter(n => activeNodeTypes.value.has(n.type)),
 )
 // 过滤边时同步过滤掉节点已被过滤的边
 const filteredEdges = computed( => {
 const nodeIds = new Set(filteredNodes.value.map(n => n.id))
 return edges.value.filter(
 e =>
 activeEdgeTypes.value.has(e.edge_type)
 && nodeIds.has(e.source)
 && nodeIds.has(e.target),
 )
 })
 async function fetchGraph(repoIds: string) {
 loading.value = true
 error.value = null
 const params: GetGalaxyParams = {
 repoIds,
 maxNodes: maxNodes.value,
 }
 try {
 const result = await getGalaxyGraph(params)
 nodes.value = result.nodes
 edges.value = result.edges
 meta.value = result.meta
 }
 catch (e: unknown) {
 error.value = e instanceof Error ? e.message: '加载 Galaxy 图谱失败'
 }
 finally {
 loading.value = false
 }
 }
 function setRenderMode(mode: GalaxyRenderMode) {
 renderMode.value = mode
 localStorage.setItem(RENDER_MODE_KEY, mode)
 }
 function onFpsUpdate(currentFps: number) {
 fps.value = currentFps
 if (currentFps < FPS_LOW_THRESHOLD) {
 lowFpsCount++
 if (lowFpsCount >= FPS_LOW_CONSECUTIVE_REQUIRED) {
 lowFpsDetected.value = true
 }
 }
 else {
 lowFpsCount = 0
 lowFpsDetected.value = false
 }
 }
 function toggleNodeType(type: GalaxyNodeType) {
 if (activeNodeTypes.value.has(type)) {
 activeNodeTypes.value.delete(type)
 }
 else {
 activeNodeTypes.value.add(type)
 }
 }
 function toggleEdgeType(type: GalaxyEdgeType) {
 if (activeEdgeTypes.value.has(type)) {
 activeEdgeTypes.value.delete(type)
 }
 else {
 activeEdgeTypes.value.add(type)
 }
 }
 function setAllNodeTypes(active: boolean) {
 if (active) {
 activeNodeTypes.value = new Set(['chunk_registry', 'symbol', 'endpoint', 'api_wrapper', 'api_call_site'])
 }
 else {
 activeNodeTypes.value = new Set
 }
 }
 function setAllEdgeTypes(active: boolean) {
 if (active) {
 activeEdgeTypes.value = new Set(['CALL', 'IMPORT', 'SAME_FILE', 'TEST_OF', 'CO_CHANGED', 'SEMANTIC', 'API_CALLS', 'IMPLEMENTS'])
 }
 else {
 activeEdgeTypes.value = new Set
 }
 }
 return {
 nodes,
 edges,
 meta,
 loading,
 error,
 renderMode,
 maxNodes,
 activeNodeTypes,
 activeEdgeTypes,
 fps,
 lowFpsDetected,
 filteredNodes,
 filteredEdges,
 fetchGraph,
 setRenderMode,
 onFpsUpdate,
 toggleNodeType,
 toggleEdgeType,
 setAllNodeTypes,
 setAllEdgeTypes,
 }
}
