/**
 * Phase Plan — CallsDagTab 单测
 * 验证：空状态 + API 调用
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import CallsDagTab from '../CallsDagTab.vue'
vi.mock('~/api/codegraph', => ({
 getCallsForSymbol: vi.fn.mockResolvedValue({
 nodes:,
 edges:,
 }),
}))
vi.mock('@vue-flow/core', => ({
 VueFlow: { template: '<div class="vue-flow-stub"><slot /></div>', props: ['nodes', 'edges', 'nodeTypes', 'minZoom', 'maxZoom', 'fitViewOnInit', 'panOnScroll', 'preventScrolling', 'nodesDraggable'] },
 useVueFlow: => ({
 fitView: vi.fn,
 }),
 Panel: { template: '<div class="panel-stub"><slot /></div>', props: ['position'] },
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
vi.mock('~/components/codegraph/SymbolNode.vue', => ({
 default: defineComponent({ template: '<div class="symbol-node-stub" />' }),
}))
vi.mock('~/lib/callEdgeColors', => ({
 CALL_EDGE_COLORS: {
 DIRECT_CALL: 'hsl(217, 91%, 60%)',
 METHOD_CALL: 'hsl(142, 71%, 45%)',
 ATTRIBUTE_ACCESS: 'hsl(215, 16%, 47%)',
 INHERITANCE: 'hsl(270, 95%, 75%)',
 },
}))
vi.mock('~/composables/useDagreLayout', => ({
 useDagreLayout: => ({
 applyLayout: (nodes: unknown) => nodes,
 }),
}))
describe('CallsDagTab', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('A: selectedSymbolId=null 时显示空状态文本', async => {
 const wrapper = mount(CallsDagTab, {
 props: {
 repositoryId: 'repo-1',
 selectedSymbolId: null,
 },
 })
 await flushPromises
 expect(wrapper.text).toContain('在 Symbols 列表中选择一个符号以查看调用关系')
 })
 it('B: 有 selectedSymbolId 时调用 getCallsForSymbol', async => {
 const { getCallsForSymbol } = await import('~/api/codegraph')
 const wrapper = mount(CallsDagTab, {
 props: {
 repositoryId: 'repo-1',
 selectedSymbolId: 'uuid-1',
 },
 })
 await flushPromises
 expect(getCallsForSymbol).toHaveBeenCalledWith('repo-1', 'uuid-1', 1, 5)
 })
 it('C: selectedSymbolId 变化时重新调用 API', async => {
 const { getCallsForSymbol } = await import('~/api/codegraph')
 const wrapper = mount(CallsDagTab, {
 props: {
 repositoryId: 'repo-1',
 selectedSymbolId: null,
 },
 })
 await flushPromises
 expect(getCallsForSymbol).not.toHaveBeenCalled
 await wrapper.setProps({ selectedSymbolId: 'uuid-2' })
 await flushPromises
 expect(getCallsForSymbol).toHaveBeenCalledWith('repo-1', 'uuid-2', 1, 5)
 })
})
