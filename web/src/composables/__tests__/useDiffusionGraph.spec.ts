import type { SourceChunk } from '../useDiffusionGraph'
/**
 * Phase Plan — useDiffusionGraph 单测
 * 验证：节点 / 边构造 + 去重 + 父节点推断 + 边样式公式 + clamp。
 */
import type { NeighborMetadata } from '~/api/codegraph'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
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
})
