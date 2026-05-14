/**
 * GraphRAG 二跳扩散画布数据转换 composable（Phase Plan + Plan）
 *
 * 输入：(hop1Neighbors, hop2Neighbors, sourceChunks) 三个 reactive ref；
 * 输出：Vue Flow Node / Edge + 折叠 / 截断统计 + expandFolded 控制函数。
 *
 * Plan 落地：节点 / 边构造 + 父节点推断 + 边样式 + 去重；折叠 / 截断为静态占位。
 * Plan 接力：FOLD_THRESHOLD=50 / HARD_LIMIT=200 / BATCH_SIZE=50 完整折叠 / 截断 /
 * 排序逻辑 + expandFolded 状态机；新查询触发时（hop1Ref / hop2Ref 引用变化）watch
 * 自动 reset visibleLimit 到 FOLD_THRESHOLD，避免上次查询的展开状态污染下一次。
 *
 * GraphRAGDiffusionTab.vue 模板已挂折叠按钮 / 截断 banner 的 v-if 占位（条件由本
 * composable 决定），Plan 仅扩展 composable 即激活，**模板零改**。
 */
import type { Edge, Node } from '@vue-flow/core'
import type { Ref } from 'vue'
import type { DiffusionEdgeType, NeighborMetadata } from '~/api/codegraph'
import type { EdgeType } from '~/lib/diffusionEdgeColors'
import { computed, ref, watch } from 'vue'
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
/**
 * 折叠 / 截断阈值（per work item §5.6 + ROADMAP §SC3）：
 * - FOLD_THRESHOLD：默认渲染前 N 个邻居，多余通过 "显示更多" 折叠按钮加载；
 * - HARD_LIMIT：硬截断上限，超过显示 banner，画布最多渲染 HARD_LIMIT 个节点；
 * - BATCH_SIZE：每次 expandFolded 调用扩展的邻居数量。
 */
const FOLD_THRESHOLD = 50
const HARD_LIMIT = 200
const BATCH_SIZE = 50
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
 * - 空 hop1 → null（跳过此 hop2，防孤儿边）。
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
 /**
 * 邻居合并 + 排序：weight desc，tie-break hop asc（一跳优先）。
 * Array.prototype.sort 在现代 JS 引擎中是稳定排序（ 2019+），
 * 同 weight 同 hop 的邻居保持原始 hop1Ref / hop2Ref 内的相对顺序。
 */
 const sortedNeighbors = computed<NeighborMetadata>( => {
 const all = [...hop1Ref.value, ...hop2Ref.value]
 return all.sort((a, b) => {
 if (b.weight !== a.weight)
 return b.weight - a.weight
 return a.hop - b.hop
 })
 })
 /**
 * 当前可见邻居上限。新查询触发（hop1Ref / hop2Ref 引用变化）时由 watch 重置。
 */
 const visibleLimit = ref(FOLD_THRESHOLD)
 const totalNeighbors = computed( => sortedNeighbors.value.length)
 const truncated = computed( => sortedNeighbors.value.length > HARD_LIMIT)
 const visibleNeighbors = computed<NeighborMetadata>( => {
 const sorted = sortedNeighbors.value
 const cap = Math.min(sorted.length, HARD_LIMIT)
 const limit = Math.min(visibleLimit.value, cap)
 return sorted.slice(0, limit)
 })
 const foldedCount = computed( => {
 const cap = Math.min(sortedNeighbors.value.length, HARD_LIMIT)
 return cap - visibleNeighbors.value.length
 })
 /**
 * 截断态（>HARD_LIMIT）只显示 banner，禁止 "显示更多" 按钮 —— 避免
 * banner + 按钮双重提示让用户误以为继续点能加载更多被截断的节点
 * （T- spoofing mitigation）。
 */
 const hasFoldedNeighbors = computed(
 => !truncated.value && foldedCount.value > 0,
 )
 /**
 * 把 visibleLimit 增加 BATCH_SIZE，但不允许超过 min(total, HARD_LIMIT) cap
 * （T- tampering mitigation：阻止用户通过反复点击突破 HARD_LIMIT）。
 */
 function expandFolded {
 const cap = Math.min(sortedNeighbors.value.length, HARD_LIMIT)
 visibleLimit.value = Math.min(visibleLimit.value + BATCH_SIZE, cap)
 }
 /**
 * 新查询时（hop1Ref / hop2Ref 引用变化）reset visibleLimit，避免上次查询的
 * 展开状态污染下一次：用户点过 "显示更多" 后切到新查询不应继承大 limit。
 */
 watch([hop1Ref, hop2Ref], => {
 visibleLimit.value = FOLD_THRESHOLD
 })
 const visibleHop1 = computed( => visibleNeighbors.value.filter(n => n.hop === 1))
 const visibleHop2 = computed( => visibleNeighbors.value.filter(n => n.hop === 2))
 /**
 * 节点集去重：source > visibleHop1 > visibleHop2 优先级（后写不覆盖）。
 * 折叠 / 截断后画布只渲染 visibleNeighbors 的节点，性能受控。
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
 for (const n of visibleHop1.value) {
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
 for (const n of visibleHop2.value) {
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
 * hop2 父推断基于 visibleHop1，避免折叠后 hop2 边指向被折叠掉的 hop1 节点（孤儿边）。
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
 for (const neighbor of visibleHop1.value) {
 const parent = inferParentForHop1(neighbor, sourceRef.value)
 if (!parent)
 continue
 upsert(parent.chunk_id, neighbor)
 }
 for (const neighbor of visibleHop2.value) {
 const parent = inferParentForHop2(neighbor, visibleHop1.value)
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
