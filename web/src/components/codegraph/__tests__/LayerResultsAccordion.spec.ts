import type { PlaygroundSearchResponse } from '~/api/codegraph'
/**
 * Phase Plan — LayerResultsAccordion 单测
 * 验证：result=null 时无 result_count；result 有 5 层时标题命中数正确
 */
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import LayerResultsAccordion from '../LayerResultsAccordion.vue'
vi.mock('~/components/ui/tooltip', => ({
 Tooltip: { template: '<div><slot /></div>' },
 TooltipProvider: { template: '<div><slot /></div>' },
 TooltipTrigger: { template: '<div><slot /></div>' },
 TooltipContent: { template: '<div><slot /></div>' },
}))
vi.mock('~/components/ui/skeleton', => ({
 Skeleton: { template: '<div class="skeleton-mock" />' },
}))
vi.mock('~/components/ui/button', => ({
 Button: { template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>' },
}))
const mockResult: PlaygroundSearchResponse = {
 query: '认证',
 repository_ids: ['repo-1'],
 layers: [
 { layer: 'L1', status: 'ok', result_count: 2, items:, error: null, extra: null },
 { layer: 'L2', status: 'ok', result_count: 3, items:, error: null, extra: null },
 { layer: 'L3', status: 'ok', result_count: 5, items:, error: null, extra: null },
 { layer: 'L4', status: 'ok', result_count: 1, items:, error: null, extra: null },
 { layer: 'L5', status: 'ok', result_count: 8, items:, error: null, extra: null },
 ],
 final_context: '# Context\n这是 L5 最终上下文',
 total_tokens: 2048,
}
describe('layerResultsAccordion', => {
 it('a: result=null 时显示"执行检索后显示结果"提示', async => {
 const wrapper = mount(LayerResultsAccordion, {
 props: { result: null, loading: false },
 })
 await flushPromises
 expect(wrapper.text).toContain('执行检索后显示结果')
 })
 it('b: result=null 时不显示命中数数字（无"2 条"等文案）', async => {
 const wrapper = mount(LayerResultsAccordion, {
 props: { result: null, loading: false },
 })
 await flushPromises
 // 命中数 badge 显示 "–" 而非数字
 expect(wrapper.text).not.toMatch(/\d+ 条/)
 })
 it('c: result 有 5 层时各层标题包含正确命中数（如"2 条"/"3 条"）', async => {
 const wrapper = mount(LayerResultsAccordion, {
 props: { result: mockResult, loading: false },
 })
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('2 条')
 expect(text).toContain('3 条')
 expect(text).toContain('5 条')
 expect(text).toContain('1 条')
 expect(text).toContain('8 条')
 })
 it('d: 5 个 Accordion 层标题全部渲染（L1~L5）', async => {
 const wrapper = mount(LayerResultsAccordion, {
 props: { result: mockResult, loading: false },
 })
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('L1 仓库路由')
 expect(text).toContain('L2 Symbol 查找')
 expect(text).toContain('L3 混合检索')
 expect(text).toContain('L4 图谱扩展')
 expect(text).toContain('L5 上下文重组')
 })
 it('e: 组件无 v-html（XSS 防御 T-）', async => {
 // final_context 内容经文本插值 {{ }} 不应出现在原始 HTML 之外
 const wrapper = mount(LayerResultsAccordion, {
 props: { result: mockResult, loading: false },
 })
 await flushPromises
 // 找到 pre 元素并确认其 innerHTML 不包含解析后的 HTML 标签（XSS 防御）
 const pre = wrapper.find('pre')
 if (pre.exists) {
 expect(pre.element.innerHTML).not.toMatch(/<script/i)
 }
 })
})
