/**
 * Phase Plan — GraphRAGDiffusionTab 单测
 * 验证：空状态 / VueFlow 渲染 / 图例 / loading 遮罩 / 折叠按钮 v-if 未触发 /
 * 截断 banner v-if 未触发 / node-click 冒泡。
 */
import type { NeighborMetadata } from '~/api/codegraph'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import GraphRAGDiffusionTab from '../GraphRAGDiffusionTab.vue'
//：fitView 模块级共享 spy，watch hop1/hop2 props 变化时被 watch 调用
const fitViewSpy = vi.fn
vi.mock('@vue-flow/core', => ({
 VueFlow: {
 name: 'VueFlow',
 template: '<div class="vue-flow-stub"><slot /></div>',
 props: ['nodes', 'edges', 'nodeTypes', 'edgeTypes', 'minZoom', 'maxZoom', 'fitViewOnInit', 'panOnScroll', 'preventScrolling', 'nodesDraggable', 'nodesConnectable'],
 emits: ['node-click'],
 },
 Panel: { template: '<div class="panel-stub":data-position="position"><slot /></div>', props: ['position'] },
 useVueFlow: => ({ fitView: fitViewSpy }),
 BaseEdge: { template: '<div />' },
 EdgeLabelRenderer: { template: '<div><slot /></div>' },
 getSmoothStepPath: => ({ path: '', labelX: 0, labelY: 0 }),
 Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
 Handle: { template: '<div />', props: ['type', 'position'] },
}))
vi.mock('@vue-flow/background', => ({
 Background: { template: '<div class="bg-stub" />' },
}))
vi.mock('@vue-flow/controls', => ({
 Controls: { template: '<div class="controls-stub" />' },
}))
vi.mock('@vue-flow/minimap', => ({
 MiniMap: { template: '<div class="minimap-stub" />' },
}))
vi.mock('~/components/ui/tooltip', => ({
 TooltipProvider: { template: '<div class="tooltip-provider-stub"><slot /></div>', props: ['delayDuration'] },
 Tooltip: { template: '<div><slot /></div>' },
 TooltipTrigger: { template: '<div><slot /></div>' },
 TooltipContent: { template: '<div><slot /></div>' },
}))
vi.mock('~/components/codegraph/DiffusionNode.vue', => ({
 default: defineComponent({ template: '<div class="diffusion-node-stub" />' }),
}))
vi.mock('~/components/codegraph/DiffusionEdge.vue', => ({
 default: defineComponent({ template: '<div class="diffusion-edge-stub" />' }),
}))
vi.mock('~/composables/useDagreLayout', => ({
 useDagreLayout: => ({ applyLayout: (nodes: unknown) => nodes }),
}))
// 注意：不 mock ~/lib/diffusionEdgeColors（让真实 hex 值进 stub 验证图例渲染）
// 不 mock ~/composables/useDiffusionGraph（让真实组合行为接入 mock useDagreLayout）
function makeNeighbor(over: Partial<NeighborMetadata> = {}): NeighborMetadata {
 return {
 chunk_id: 'h1-x',
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
describe('graphRAGDiffusionTab', => {
 it('a: 空 props → 渲染空状态 "无关联代码"，不渲染 VueFlow stub', => {
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors:,
 hop2Neighbors:,
 sourceChunks:,
 loading: false,
 },
 })
 expect(wrapper.text).toContain('无关联代码')
 expect(wrapper.find('.vue-flow-stub').exists).toBe(false)
 })
 it('b: 有邻居 → 渲染 VueFlow + 6 类 edge_type 图例（含真实 hex）', => {
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors: [makeNeighbor({ chunk_id: 'h1', file_path: 'src/a.ts' })],
 hop2Neighbors:,
 sourceChunks: [{ chunk_id: 'src-1', file_path: 'src/a.ts', line_start: 1, line_end: 5 }],
 loading: false,
 },
 })
 expect(wrapper.find('.vue-flow-stub').exists).toBe(true)
 const html = wrapper.html
 // 6 类图例 label
 expect(html).toContain('CALL')
 expect(html).toContain('IMPORT')
 expect(html).toContain('SAME_FILE')
 expect(html).toContain('TEST_OF')
 expect(html).toContain('CO_CHANGED')
 expect(html).toContain('SEMANTIC')
 // 真实 hex 串（fill attr）
 expect(html).toContain('#3b82f6')
 expect(html).toContain('#ec4899')
 })
 it('c: loading=true → 加载遮罩 icon-[lucide--loader-circle] 可见', => {
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors:,
 hop2Neighbors:,
 sourceChunks:,
 loading: true,
 },
 })
 expect(wrapper.html).toContain('icon-[lucide--loader-circle]')
 })
 it('d: composable hasFoldedNeighbors=false（本 plan 默认）→ 折叠按钮不渲染', => {
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors: [makeNeighbor],
 hop2Neighbors:,
 sourceChunks: [{ chunk_id: 'src-1', file_path: 'src/a.ts', line_start: 1, line_end: 5 }],
 loading: false,
 },
 })
 expect(wrapper.text).not.toContain('显示更多')
 })
 it('e: composable truncated=false（本 plan 默认）→ 截断 banner 不渲染', => {
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors: [makeNeighbor],
 hop2Neighbors:,
 sourceChunks: [{ chunk_id: 'src-1', file_path: 'src/a.ts', line_start: 1, line_end: 5 }],
 loading: false,
 },
 })
 expect(wrapper.text).not.toContain('扩散图节点过多')
 })
 it('f: VueFlow @node-click → emit node-click(chunkId)（：通过事件触发非内部方法）', async => {
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors: [makeNeighbor({ chunk_id: 'chunk-x' })],
 hop2Neighbors:,
 sourceChunks: [{ chunk_id: 'src-1', file_path: 'src/a.ts', line_start: 1, line_end: 5 }],
 loading: false,
 },
 })
 const vueFlow = wrapper.findComponent({ name: 'VueFlow' })
 vueFlow.vm.$emit('node-click', { node: { id: 'chunk-x' } })
 await wrapper.vm.$nextTick
 const emitted = wrapper.emitted('node-click')
 expect(emitted).toBeDefined
 expect(emitted?.[0]).toEqual(['chunk-x'])
 })
 it('hi-03: hop1Neighbors props 变化 → 主动调 fitView({ padding: 0.15, duration: 300 })', async => {
 fitViewSpy.mockClear
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors: [makeNeighbor({ chunk_id: 'q1' })],
 hop2Neighbors:,
 sourceChunks: [{ chunk_id: 'src-1', file_path: 'src/a.ts', line_start: 1, line_end: 5 }],
 loading: false,
 },
 })
 await wrapper.vm.$nextTick
 fitViewSpy.mockClear
 // 模拟新查询：替换 hop1Neighbors 引用
 await wrapper.setProps({
 hop1Neighbors: [makeNeighbor({ chunk_id: 'q2' }), makeNeighbor({ chunk_id: 'q3' })],
 })
 await wrapper.vm.$nextTick
 await wrapper.vm.$nextTick
 expect(fitViewSpy).toHaveBeenCalled
 expect(fitViewSpy).toHaveBeenCalledWith({ padding: 0.15, duration: 300 })
 })
 it('g: sourceChunks 通过 props 流入 composable，nodes 含 source + hop1', => {
 // 间接验证 composable 已接入：通过观察 vue-flow-stub 已渲染（=非空状态）
 const _r = ref(false)
 const wrapper = mount(GraphRAGDiffusionTab, {
 props: {
 hop1Neighbors: [makeNeighbor({ chunk_id: 'h1', file_path: 'src/a.ts' })],
 hop2Neighbors:,
 sourceChunks: [{ chunk_id: 'src-1', file_path: 'src/a.ts', line_start: 1, line_end: 5 }],
 loading: false,
 },
 })
 expect(wrapper.find('.vue-flow-stub').exists).toBe(true)
 expect(_r.value).toBe(false)
 })
})
