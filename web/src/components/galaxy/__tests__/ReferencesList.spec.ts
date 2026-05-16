/**
 * Phase Plan — ReferencesList.vue 组件测试
 */
import type { GalaxyEdgeType, GalaxyNode } from '~/api/galaxy'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ReferencesList from '../ReferencesList.vue'
function makeNode(overrides: Partial<GalaxyNode> = {}): GalaxyNode {
 return {
 id: 'symbol:abc',
 type: 'symbol',
 label: 'MyFunction',
 file_path: 'src/utils.ts',
 repository_id: 'repo-1',
 line_start: 10,
 line_end: 20,
 metadata: {},
 degree: 5,
 ...overrides,
 }
}
describe('ReferencesList', => {
 it('渲染 called_by 段落', async => {
 const wrapper = mount(ReferencesList, {
 props: {
 calledBy: [
 { caller_node_id: 'symbol:caller1', edge_type: 'CALL' as GalaxyEdgeType },
 { caller_node_id: 'symbol:caller2', edge_type: 'IMPORT' as GalaxyEdgeType },
 ],
 },
 })
 await flushPromises
 expect(wrapper.text).toContain('被调用')
 expect(wrapper.text).toContain('symbol:caller1')
 expect(wrapper.text).toContain('symbol:caller2')
 wrapper.unmount
 })
 it('渲染 calls 段落', async => {
 const wrapper = mount(ReferencesList, {
 props: {
 calls: [
 { source_node_id: 'symbol:callee1', edge_type: 'CALL' as GalaxyEdgeType },
 ],
 },
 })
 await flushPromises
 expect(wrapper.text).toContain('调用')
 expect(wrapper.text).toContain('symbol:callee1')
 wrapper.unmount
 })
 it('渲染 neighbors 段落', async => {
 const wrapper = mount(ReferencesList, {
 props: {
 neighbors: [
 { node: makeNode({ id: 'n1', label: 'HelperFn' }), edge_type: 'SEMANTIC' as GalaxyEdgeType, direction: 'out' as const },
 ],
 },
 })
 await flushPromises
 expect(wrapper.text).toContain('关联节点')
 expect(wrapper.text).toContain('HelperFn')
 wrapper.unmount
 })
 it('点击 called_by 项 emit node-select', async => {
 const wrapper = mount(ReferencesList, {
 props: {
 calledBy: [
 { caller_node_id: 'symbol:caller', edge_type: 'CALL' as GalaxyEdgeType },
 ],
 },
 })
 await flushPromises
 const items = wrapper.findAll('li')
 await items[0].trigger('click')
 expect(wrapper.emitted('node-select')).toBeTruthy
 expect(wrapper.emitted('node-select')![0]).toEqual(['symbol:caller'])
 wrapper.unmount
 })
 it('点击 neighbors 项 emit node-select 正确 nodeId', async => {
 const wrapper = mount(ReferencesList, {
 props: {
 neighbors: [
 { node: makeNode({ id: 'symbol:nbr' }), edge_type: 'CALL' as GalaxyEdgeType, direction: 'in' as const },
 ],
 },
 })
 await flushPromises
 const items = wrapper.findAll('li')
 await items[0].trigger('click')
 expect(wrapper.emitted('node-select')![0]).toEqual(['symbol:nbr'])
 wrapper.unmount
 })
 it('全空时显示空状态', async => {
 const wrapper = mount(ReferencesList, {
 props: {},
 })
 await flushPromises
 expect(wrapper.text).toContain('暂无引用关系')
 wrapper.unmount
 })
 it('loading=true 时显示骨架', async => {
 const wrapper = mount(ReferencesList, {
 props: { loading: true },
 })
 await flushPromises
 expect(wrapper.find('.animate-pulse').exists).toBe(true)
 wrapper.unmount
 })
})
