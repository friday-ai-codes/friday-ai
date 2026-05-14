/**
 * GraphRAG 二跳扩散画布数据转换 composable（Phase Plan）
 *
 * 输入：(hop1Neighbors, hop2Neighbors, sourceChunks) 三个 reactive ref；
 * 输出：Vue Flow Node / Edge + 折叠 / 截断统计。
 *
 * 本 plan 仅落 80%：折叠 / 截断逻辑（>50 折叠、>200 截断）由 Plan 接力扩展
 * 同一文件；本 plan 的 foldedCount / truncated / hasFoldedNeighbors 永远返回静态
 * 值（0 / false / false），expandFolded 为 no-op。GraphRAGDiffusionTab.vue 模板
 * 已挂 v-if 占位，Plan 仅扩展 composable 即可激活，不需要再改组件。
 */
import type { Edge, Node } from '@vue-flow/core'
import type { Ref } from 'vue'
import type { DiffusionEdgeType, NeighborMetadata } from '~/api/codegraph'
import type { EdgeType } from '~/lib/diffusionEdgeColors'
import { computed } from 'vue'
import { useDagreLayout } from '~/composables/useDagreLayout'
import { DIFFUSION_EDGE_COLORS } from '~/lib/diffusionEdgeColors'
export interface SourceChunk {
 chunk_id: string
 file_path: string
 line_start: number | null
 line_end: number | null
 content?: string
}
export type DiffusionHop = 'source' | 1 | 2
export interface DiffusionNodeData {
 chunk_id: string
 file_path: string
 fileBasename: string
 line_start: number | null
 line_end: number | null
 hop: DiffusionHop
 content?: string
}
export interface DiffusionEdgeData {
 edgeType: DiffusionEdgeType
 weight: number
 reason: string
 hop: 1 | 2
}
const STROKE_WIDTH_MIN = 1.5
const STROKE_WIDTH_MAX = 4
function clampStrokeWidth(value: number): number {
 if (Number.isNaN(value))
 return STROKE_WIDTH_MIN
 if (value < STROKE_WIDTH_MIN)
 return STROKE_WIDTH_MIN
 if (value > STROKE_WIDTH_MAX)
 return STROKE_WIDTH_MAX
 return value
}
function basename(filePath: string): string {
 const parts = filePath.split('/')
 return parts[parts.length - 1] ?? filePath
}
function buildNode(data: DiffusionNodeData): Node<DiffusionNodeData> {
 return {
 id: data.chunk_id,
 type: 'diffusion',
 position: { x: 0, y: 0 },
 data,
 ariaLabel: `代码块 ${data.fileBasename}, ${data.hop === 'source' ? '起点': `${data.hop}-hop`}`,
 }
}
/**
 * 找到 hop1 邻居的父 source chunk：
 * - 优先 file_path 命中；
 * - 多 source 命中取第一个；
 * - 不命中 → fallback 取第一个 source；
 * - 空 source → null（调用方跳过此邻居，避免无父边）。
 */
function inferParentForHop1(
 neighbor: NeighborMetadata,
 sources: SourceChunk,
): SourceChunk | null {
 if (sources.length === 0)
 return null
 const match = sources.find(s => s.file_path === neighbor.file_path)
 return match ?? sources[0] ?? null
}
/**
 * 找到 hop2 邻居的父 hop1 节点：
 * - 优先 file_path 命中（多匹配取 weight 最高者）；
 * - 不命中 → fallback 取 hop1 中 weight 最高者；
 * - 空 hop1 → null（跳过此 hop2）。
 */
function inferParentForHop2(
 neighbor: NeighborMetadata,
 hop1List: NeighborMetadata,
): NeighborMetadata | null {
 if (hop1List.length === 0)
 return null
 const sameFile = hop1List.filter(n => n.file_path === neighbor.file_path)
 if (sameFile.length > 0)
 return sameFile.reduce((acc, cur) => (cur.weight > acc.weight ? cur: acc))
 return hop1List.reduce((acc, cur) => (cur.weight > acc.weight ? cur: acc))
}
function buildEdge(
 sourceId: string,
 neighbor: NeighborMetadata,
): Edge<DiffusionEdgeData> {
 const stroke = DIFFUSION_EDGE_COLORS[neighbor.edge_type as EdgeType] ?? '#6b7280'
 const baseWidth = neighbor.hop === 1 ? 2: 1.5
 const baseOpacity = neighbor.hop === 1 ? 0.9: 0.5
 const strokeWidth = clampStrokeWidth(baseWidth + neighbor.weight * 1.5)
 return {
 id: `${sourceId}-${neighbor.chunk_id}-${neighbor.edge_type}`,
 source: sourceId,
 target: neighbor.chunk_id,
 type: 'diffusion',
 style: {
 stroke,
 strokeWidth,
 strokeDasharray: neighbor.hop === 2 ? '6 4': undefined,
 opacity: baseOpacity,
 },
 data: {
 edgeType: neighbor.edge_type,
 weight: neighbor.weight,
 reason: neighbor.reason,
 hop: neighbor.hop,
 },
 ariaLabel: `${neighbor.edge_type} 边 weight ${neighbor.weight.toFixed(2)} hop ${neighbor.hop}`,
 }
}
export function useDiffusionGraph(
 hop1Ref: Ref<NeighborMetadata>,
 hop2Ref: Ref<NeighborMetadata>,
 sourceRef: Ref<SourceChunk>,
) {
 const { applyLayout } = useDagreLayout
 const totalNeighbors = computed(
 => hop1Ref.value.length + hop2Ref.value.length,
 )
 // 本 plan 不做折叠 / 截断，Plan 接力扩展时改这里返回真值
 const visibleNeighbors = computed<NeighborMetadata>(
 => [...hop1Ref.value, ...hop2Ref.value],
 )
 const foldedCount = computed( => 0)
 const truncated = computed( => false)
 const hasFoldedNeighbors = computed( => false)
 function expandFolded {
 // Plan 接力：切换 visibleNeighbors 内部 state 让 hasFoldedNeighbors 由 true → false
 }
 /**
 * 节点集去重：source > hop1 > hop2 优先级（后写不覆盖）。
 */
 const nodeMap = computed<Map<string, Node<DiffusionNodeData>>>( => {
 const map = new Map<string, Node<DiffusionNodeData>>
 for (const src of sourceRef.value) {
 if (!map.has(src.chunk_id)) {
 map.set(
 src.chunk_id,
 buildNode({
 chunk_id: src.chunk_id,
 file_path: src.file_path,
 fileBasename: basename(src.file_path),
 line_start: src.line_start,
 line_end: src.line_end,
 hop: 'source',
 content: src.content,
 }),
 )
 }
 }
 for (const n of hop1Ref.value) {
 if (!map.has(n.chunk_id)) {
 map.set(
 n.chunk_id,
 buildNode({
 chunk_id: n.chunk_id,
 file_path: n.file_path,
 fileBasename: basename(n.file_path),
 line_start: n.line_start,
 line_end: n.line_end,
 hop: 1,
 }),
 )
 }
 }
 for (const n of hop2Ref.value) {
 if (!map.has(n.chunk_id)) {
 map.set(
 n.chunk_id,
 buildNode({
 chunk_id: n.chunk_id,
 file_path: n.file_path,
 fileBasename: basename(n.file_path),
 line_start: n.line_start,
 line_end: n.line_end,
 hop: 2,
 }),
 )
 }
 }
 return map
 })
 /**
 * 边集去重：同 (source, target) 不论 edge_type 仅渲染一条，取 weight 最大者。
 * 同时丢弃自环（source === target）。
 */
 const edgeMap = computed<Map<string, Edge<DiffusionEdgeData>>>( => {
 const map = new Map<string, Edge<DiffusionEdgeData>>
 function upsert(parentId: string, neighbor: NeighborMetadata) {
 if (parentId === neighbor.chunk_id)
 return
 const key = `${parentId}->${neighbor.chunk_id}`
 const existing = map.get(key)
 if (!existing) {
 map.set(key, buildEdge(parentId, neighbor))
 return
 }
 const existingWeight = (existing.data as DiffusionEdgeData | undefined)?.weight ?? -Infinity
 if (neighbor.weight > existingWeight)
 map.set(key, buildEdge(parentId, neighbor))
 }
 for (const neighbor of hop1Ref.value) {
 const parent = inferParentForHop1(neighbor, sourceRef.value)
 if (!parent)
 continue
 upsert(parent.chunk_id, neighbor)
 }
 for (const neighbor of hop2Ref.value) {
 const parent = inferParentForHop2(neighbor, hop1Ref.value)
 if (!parent)
 continue
 upsert(parent.chunk_id, neighbor)
 }
 return map
 })
 const flowEdges = computed<Edge<DiffusionEdgeData>>(
 => Array.from(edgeMap.value.values),
 )
 const flowNodes = computed<Node<DiffusionNodeData>>( => {
 const nodes = Array.from(nodeMap.value.values)
 return applyLayout(nodes, flowEdges.value, {
 rankdir: 'TB',
 ranksep: 80,
 nodesep: 40,
 marginx: 20,
 marginy: 20,
 }) as Node<DiffusionNodeData>
 })
 return {
 flowNodes,
 flowEdges,
 totalNeighbors,
 visibleNeighbors,
 foldedCount,
 truncated,
 hasFoldedNeighbors,
 expandFolded,
 }
}
