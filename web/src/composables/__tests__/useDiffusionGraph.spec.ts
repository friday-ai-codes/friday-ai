import type { DiffusionEdgeData, SourceChunk } from '../useDiffusionGraph'
/**
 * Phase Plan + Plan — useDiffusionGraph 单测
 * 验证：
 * - 节点 / 边构造 + 去重 + 父节点推断 + 边样式公式 + clamp（Plan a-i 9 条）
 * - 折叠 / 截断 / 排序 / expandFolded / watch reset（Plan j-q 8 条）
 */
import type { NeighborMetadata } from '~/api/codegraph'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
vi.mock('~/composables/useDagreLayout', => ({
 useDagreLayout: => ({
 applyLayout: (nodes: unknown) => nodes,
 }),
}))
const { useDiffusionGraph } = await import('../useDiffusionGraph')
function makeNeighbor(over: Partial<NeighborMetadata> = {}): NeighborMetadata {
 return {
 chunk_id: 'chunk-x',
 file_path: 'src/x.ts',
 line_start: 1,
 line_end: 10,
 edge_type: 'CALL',
 weight: 0.5,
 reason: '',
 hop: 1,
 ...over,
 }
}
function makeSource(over: Partial<SourceChunk> = {}): SourceChunk {
 return {
 chunk_id: 'src-1',
 file_path: 'src/main.ts',
 line_start: 1,
 line_end: 20,
 ...over,
 }
}
describe('useDiffusionGraph', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('a: 空输入 → flowNodes/edges 均空，totalNeighbors=0，hasFoldedNeighbors=false', => {
 const { flowNodes, flowEdges, totalNeighbors, hasFoldedNeighbors, truncated } = useDiffusionGraph(
 ref<NeighborMetadata>,
 ref<NeighborMetadata>,
 ref<SourceChunk>,
 )
 expect(flowNodes.value).toHaveLength(0)
 expect(flowEdges.value).toHaveLength(0)
 expect(totalNeighbors.value).toBe(0)
 expect(hasFoldedNeighbors.value).toBe(false)
 expect(truncated.value).toBe(false)
 })
 it('b: 1 source + 2 hop1 + 1 hop2 → nodes=4，edges=3（含 hop2 父推断）', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const hop1 = [
 makeNeighbor({ chunk_id: 'h1-a', file_path: 'src/a.ts', weight: 0.6 }),
 makeNeighbor({ chunk_id: 'h1-b', file_path: 'src/b.ts', weight: 0.3 }),
 ]
 const hop2 = [
 makeNeighbor({ chunk_id: 'h2-a', file_path: 'src/a.ts', hop: 2, weight: 0.2 }),
 ]
 const { flowNodes, flowEdges } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref([source]),
 )
 expect(flowNodes.value).toHaveLength(4)
 expect(flowEdges.value).toHaveLength(3)
 const edgeTargets = flowEdges.value.map(e => `${e.source}->${e.target}`)
 expect(edgeTargets).toContain('src-1->h1-a')
 expect(edgeTargets).toContain('src-1->h1-b')
 // hop2 父推断：file_path 命中 hop1[0]
 expect(edgeTargets).toContain('h1-a->h2-a')
 })
 it('c: 同一 (source, target) 多 edge_type → 仅 1 条边，取最大 weight', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const hop1 = [
 makeNeighbor({ chunk_id: 'h1-x', file_path: 'src/a.ts', edge_type: 'CALL', weight: 0.2, reason: 'call-reason' }),
 makeNeighbor({ chunk_id: 'h1-x', file_path: 'src/a.ts', edge_type: 'IMPORT', weight: 0.9, reason: 'import-reason' }),
 ]
 const { flowEdges } = useDiffusionGraph(
 ref(hop1),
 ref<NeighborMetadata>,
 ref([source]),
 )
 expect(flowEdges.value).toHaveLength(1)
 const edge = flowEdges.value[0]
 expect((edge.data as { edgeType: string, weight: number, reason: string }).edgeType).toBe('IMPORT')
 expect((edge.data as { weight: number }).weight).toBe(0.9)
 expect((edge.data as { reason: string }).reason).toBe('import-reason')
 })
 it('d: 自环（source === target）被丢弃', => {
 const source = makeSource({ chunk_id: 'self', file_path: 'src/a.ts' })
 const hop1 = [
 makeNeighbor({ chunk_id: 'self', file_path: 'src/a.ts', weight: 0.5 }),
 ]
 const { flowEdges } = useDiffusionGraph(
 ref(hop1),
 ref<NeighborMetadata>,
 ref([source]),
 )
 expect(flowEdges.value).toHaveLength(0)
 })
 it('e: strokeWidth 公式 + clamp [1.5, 4]', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const hop1 = [
 // hop=1 / weight=0.5 → 2 + 0.5 * 1.5 = 2.75
 makeNeighbor({ chunk_id: '', file_path: 'src/a.ts', hop: 1, weight: 0.5 }),
 // hop=1 / weight=2.0 → 2 + 3 = 5 → clamp 4
 makeNeighbor({ chunk_id: 'h-clampHigh', file_path: 'src/a.ts', hop: 1, weight: 2.0 }),
 // hop=2 / weight=-0.5 → 1.5 - 0.75 = 0.75 → clamp 1.5
 makeNeighbor({ chunk_id: 'h-clampLow', file_path: 'src/a.ts', hop: 2, weight: -0.5 }),
 // hop=2 / weight=0 → 1.5
 makeNeighbor({ chunk_id: '', file_path: 'src/a.ts', hop: 2, weight: 0 }),
 ]
 const { flowEdges } = useDiffusionGraph(
 ref([hop1[0], hop1[1]]),
 ref([hop1[2], hop1[3]]),
 ref([source]),
 )
 const byTarget = Object.fromEntries(
 flowEdges.value.map(e => [e.target, e.style as Record<string, unknown>]),
 )
 expect(byTarget['']?.strokeWidth).toBeCloseTo(2.75, 5)
 expect(byTarget['h-clampHigh']?.strokeWidth).toBe(4)
 expect(byTarget['h-clampLow']?.strokeWidth).toBe(1.5)
 expect(byTarget['']?.strokeWidth).toBe(1.5)
 })
 it('f: hop=1 实线 opacity=0.9；hop=2 虚线 dasharray="6 4" opacity=0.5', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const hop1 = [makeNeighbor({ chunk_id: 'h1-a', file_path: 'src/a.ts', hop: 1, weight: 0.5 })]
 const hop2 = [makeNeighbor({ chunk_id: 'h2-a', file_path: 'src/a.ts', hop: 2, weight: 0.5 })]
 const { flowEdges } = useDiffusionGraph(ref(hop1), ref(hop2), ref([source]))
 const e1 = flowEdges.value.find(e => e.target === 'h1-a')!
 const e2 = flowEdges.value.find(e => e.target === 'h2-a')!
 expect((e1.style as Record<string, unknown>).strokeDasharray).toBeUndefined
 expect((e1.style as Record<string, unknown>).opacity).toBe(0.9)
 expect((e2.style as Record<string, unknown>).strokeDasharray).toBe('6 4')
 expect((e2.style as Record<string, unknown>).opacity).toBe(0.5)
 })
 it('g: unknown edge_type → stroke 退到 #6b7280 gray-500', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const bogus = makeNeighbor({
 chunk_id: 'h-bogus',
 file_path: 'src/a.ts',
 // 类型断言：用 unknown 字面值模拟后端枚举漂移
 edge_type: 'BOGUS_TYPE' as unknown as NeighborMetadata['edge_type'],
 weight: 0.5,
 })
 const { flowEdges } = useDiffusionGraph(ref([bogus]), ref<NeighborMetadata>, ref([source]))
 const edge = flowEdges.value[0]
 expect((edge.style as Record<string, unknown>).stroke).toBe('#6b7280')
 })
 it('h: hop2 fallback —— file_path 不命中 → 取 hop1 中 weight 最高者作父', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const hop1 = [
 makeNeighbor({ chunk_id: 'h1-low', file_path: 'src/b.ts', weight: 0.1 }),
 makeNeighbor({ chunk_id: 'h1-high', file_path: 'src/c.ts', weight: 0.9 }),
 ]
 const hop2 = [
 makeNeighbor({ chunk_id: 'h2-orphan', file_path: 'src/zzz.ts', hop: 2, weight: 0.4 }),
 ]
 const { flowEdges } = useDiffusionGraph(ref(hop1), ref(hop2), ref([source]))
 const hop2Edge = flowEdges.value.find(e => e.target === 'h2-orphan')
 expect(hop2Edge).toBeDefined
 expect(hop2Edge!.source).toBe('h1-high')
 })
 it('i: 空 sourceChunks 但有 hop1 → 跳过建边，但节点仍登记（去重 Map 已写）', => {
 const hop1 = [
 makeNeighbor({ chunk_id: 'h1-a', file_path: 'src/a.ts', weight: 0.5 }),
 ]
 const { flowNodes, flowEdges } = useDiffusionGraph(
 ref(hop1),
 ref<NeighborMetadata>,
 ref<SourceChunk>,
 )
 expect(flowNodes.value).toHaveLength(1)
 expect(flowNodes.value[0].id).toBe('h1-a')
 expect(flowEdges.value).toHaveLength(0)
 })
 /**
 * Plan 折叠 / 截断 / 排序 / expandFolded / watch reset 8 条单测。
 * 阈值：FOLD_THRESHOLD=50，HARD_LIMIT=200，BATCH_SIZE=50。
 *
 * Helper：构造 N 个邻居，weight 从 0.99 递减到 0.99 - (N-1)*0.001（保严格 desc，
 * 单元测试范围内不会与默认 0.5 重复，方便排序断言）。
 */
 function makeManyNeighbors(
 count: number,
 over: Partial<NeighborMetadata> & { idPrefix?: string } = {},
 ): NeighborMetadata {
 const { idPrefix = 'n', ...rest } = over
 return Array.from({ length: count }, (_, i) =>
 makeNeighbor({
 chunk_id: `${idPrefix}-${i}`,
 file_path: `src/${idPrefix}-${i}.ts`,
 weight: Number((0.99 - i * 0.001).toFixed(4)),
 ...rest,
 }))
 }
 it('j: 50 邻居（hop1=30 + hop2=20）→ 全量渲染，hasFoldedNeighbors=false，truncated=false', => {
 const hop1 = makeManyNeighbors(30, { idPrefix: 'h1', hop: 1 })
 const hop2 = makeManyNeighbors(20, { idPrefix: 'h2', hop: 2 })
 const { totalNeighbors, visibleNeighbors, foldedCount, hasFoldedNeighbors, truncated } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expect(totalNeighbors.value).toBe(50)
 expect(visibleNeighbors.value).toHaveLength(50)
 expect(foldedCount.value).toBe(0)
 expect(hasFoldedNeighbors.value).toBe(false)
 expect(truncated.value).toBe(false)
 })
 it('k: 80 邻居（hop1=50 + hop2=30）→ 默认显示前 50 按 weight desc，hasFoldedNeighbors=true / foldedCount=30 / truncated=false', => {
 // hop1 weight 0.99..0.941（前 50 段），hop2 weight 0.94..0.911（后 30 段）—— 全部按 weight desc 排序后，前 50 应为 hop1 全部
 const hop1 = makeManyNeighbors(50, { idPrefix: 'h1', hop: 1 })
 const hop2 = Array.from({ length: 30 }, (_, i) =>
 makeNeighbor({
 chunk_id: `h2-${i}`,
 file_path: `src/h2-${i}.ts`,
 hop: 2,
 weight: Number((0.94 - i * 0.001).toFixed(4)),
 }))
 const { totalNeighbors, visibleNeighbors, foldedCount, hasFoldedNeighbors, truncated } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expect(totalNeighbors.value).toBe(80)
 expect(visibleNeighbors.value).toHaveLength(50)
 expect(foldedCount.value).toBe(30)
 expect(hasFoldedNeighbors.value).toBe(true)
 expect(truncated.value).toBe(false)
 // 前 50 全部来自 hop1（weight 排序前 50）
 expect(visibleNeighbors.value.every(n => n.hop === 1)).toBe(true)
 // weight 严格降序
 for (let i = 1; i < visibleNeighbors.value.length; i++)
 expect(visibleNeighbors.value[i - 1].weight).toBeGreaterThanOrEqual(visibleNeighbors.value[i].weight)
 })
 it('l: 80 邻居 + expandFolded 一次 → visibleNeighbors.length=80（cap 触底），hasFoldedNeighbors=false', => {
 const hop1 = makeManyNeighbors(50, { idPrefix: 'h1', hop: 1 })
 const hop2 = Array.from({ length: 30 }, (_, i) =>
 makeNeighbor({
 chunk_id: `h2-${i}`,
 file_path: `src/h2-${i}.ts`,
 hop: 2,
 weight: Number((0.94 - i * 0.001).toFixed(4)),
 }))
 const { visibleNeighbors, foldedCount, hasFoldedNeighbors, expandFolded } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(80)
 expect(foldedCount.value).toBe(0)
 expect(hasFoldedNeighbors.value).toBe(false)
 })
 it('m: 250 邻居 → totalNeighbors=250，visibleNeighbors.length=50，truncated=true，hasFoldedNeighbors=false（截断态禁折叠按钮）', => {
 const hop1 = makeManyNeighbors(150, { idPrefix: 'h1', hop: 1 })
 const hop2 = Array.from({ length: 100 }, (_, i) =>
 makeNeighbor({
 chunk_id: `h2-${i}`,
 file_path: `src/h2-${i}.ts`,
 hop: 2,
 weight: Number((0.5 - i * 0.001).toFixed(4)),
 }))
 const { totalNeighbors, visibleNeighbors, truncated, hasFoldedNeighbors, foldedCount } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expect(totalNeighbors.value).toBe(250)
 expect(visibleNeighbors.value).toHaveLength(50)
 expect(truncated.value).toBe(true)
 expect(hasFoldedNeighbors.value).toBe(false)
 // truncated 态：foldedCount = HARD_LIMIT(200) - visible(50) = 150（仍 > 0，但 hasFoldedNeighbors=false 由 truncated 短路）
 expect(foldedCount.value).toBe(150)
 })
 it('n: 250 邻居 + expandFolded 多次 → visibleNeighbors.length 50→100→150→200 后停（不突破 HARD_LIMIT）', => {
 const hop1 = makeManyNeighbors(150, { idPrefix: 'h1', hop: 1 })
 const hop2 = Array.from({ length: 100 }, (_, i) =>
 makeNeighbor({
 chunk_id: `h2-${i}`,
 file_path: `src/h2-${i}.ts`,
 hop: 2,
 weight: Number((0.5 - i * 0.001).toFixed(4)),
 }))
 const { visibleNeighbors, expandFolded } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expect(visibleNeighbors.value).toHaveLength(50)
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(100)
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(150)
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(200)
 // 第 4 次起 cap 触底，长度恒为 200
 expandFolded
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(200)
 })
 it('o: 排序 tie-break — 同 weight 0.5 的 1 hop1 + 1 hop2 → visibleNeighbors[0].hop === 1（一跳优先）', => {
 const hop1 = [makeNeighbor({ chunk_id: 'h1-tie', file_path: 'src/x.ts', hop: 1, weight: 0.5 })]
 const hop2 = [makeNeighbor({ chunk_id: 'h2-tie', file_path: 'src/y.ts', hop: 2, weight: 0.5 })]
 const { visibleNeighbors } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expect(visibleNeighbors.value).toHaveLength(2)
 expect(visibleNeighbors.value[0].hop).toBe(1)
 expect(visibleNeighbors.value[1].hop).toBe(2)
 })
 it('p: watch hop1Ref / hop2Ref 变化 → visibleLimit reset 到 50（旧查询展开状态不污染新查询）', async => {
 const hop1Ref = ref<NeighborMetadata>(makeManyNeighbors(50, { idPrefix: 'a-h1', hop: 1 }))
 const hop2Ref = ref<NeighborMetadata>(
 Array.from({ length: 30 }, (_, i) =>
 makeNeighbor({
 chunk_id: `a-h2-${i}`,
 file_path: `src/a-h2-${i}.ts`,
 hop: 2,
 weight: Number((0.94 - i * 0.001).toFixed(4)),
 })),
 )
 const { visibleNeighbors, expandFolded } = useDiffusionGraph(
 hop1Ref,
 hop2Ref,
 ref<SourceChunk>,
 )
 // 初始 50，expandFolded 后 80
 expect(visibleNeighbors.value).toHaveLength(50)
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(80)
 // 模拟新查询触发：替换 hop1Ref.value 引用
 hop1Ref.value = makeManyNeighbors(70, { idPrefix: 'b-h1', hop: 1 })
 await nextTick
 // 新数据 70 + 30 = 100，visibleLimit reset 到 50 → 仅显示 50
 expect(visibleNeighbors.value).toHaveLength(50)
 })
 it('hi-04: weight=null/NaN/undefined → buildEdge 防御 → safeWeight=0，ariaLabel 含 "weight 0.00"，不抛 TypeError', => {
 const source = makeSource({ chunk_id: 'src-1', file_path: 'src/a.ts' })
 const hop1 = [
 makeNeighbor({
 chunk_id: 'h-null-weight',
 file_path: 'src/a.ts',
 // 模拟后端 partial mock 路径下 weight 字段缺失
 weight: null as unknown as number,
 }),
 ]
 const { flowEdges } = useDiffusionGraph(
 ref(hop1),
 ref<NeighborMetadata>,
 ref([source]),
 )
 expect(flowEdges.value).toHaveLength(1)
 const edge = flowEdges.value[0]
 expect(edge.ariaLabel).toContain('weight 0.00')
 // strokeWidth 计算用 safeWeight=0 → HOP1_BASE_WIDTH(2) + 0 * 1.5 = 2
 expect((edge.style as Record<string, unknown>).strokeWidth).toBe(2)
 expect((edge.data as DiffusionEdgeData).weight).toBe(0)
 })
 it('q: truncated=true 场景 expandFolded 受 HARD_LIMIT cap 严格限制（多次调用后 visibleLimit 不超过 200）', => {
 const hop1 = makeManyNeighbors(120, { idPrefix: 'h1', hop: 1 })
 const hop2 = Array.from({ length: 100 }, (_, i) =>
 makeNeighbor({
 chunk_id: `h2-${i}`,
 file_path: `src/h2-${i}.ts`,
 hop: 2,
 weight: Number((0.5 - i * 0.001).toFixed(4)),
 }))
 const { visibleNeighbors, truncated, expandFolded } = useDiffusionGraph(
 ref(hop1),
 ref(hop2),
 ref<SourceChunk>,
 )
 expect(truncated.value).toBe(true)
 // 跳调 10 次（远超 /50 = 3 次）
 for (let i = 0; i < 10; i++)
 expandFolded
 expect(visibleNeighbors.value).toHaveLength(200)
 })
})
