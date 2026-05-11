/**
 * Phase Plan — playground.vue 单测
 * 验证：requiresAdmin route meta + PlaygroundQueryInput 挂载
 */
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
vi.mock('~/api/codegraph', => ({
 playgroundSearch: vi.fn.mockResolvedValue({
 query: 'test',
 repository_ids:,
 layers:,
 final_context: '',
 total_tokens: 0,
 }),
}))
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 list: vi.fn.mockResolvedValue,
 },
}))
// 路由 mock
vi.mock('vue-router', async (importOriginal) => {
 const actual = await importOriginal<typeof import('vue-router')>
 return {
 ...actual,
 useRouter: vi.fn( => ({ push: vi.fn })),
 useRoute: vi.fn( => ({ query: {} })),
 }
})
const stubComponents = {
 PlaygroundQueryInput: defineComponent({
 props: ['loading'],
 emits: ['search', 'chat-prefill'],
 template: '<div class="query-input-stub" />',
 }),
 LayerResultsAccordion: defineComponent({
 props: ['result', 'loading'],
 template: '<div class="layer-accordion-stub" />',
 }),
}
describe('playground.vue', => {
 it('A: 页面包含 requiresAdmin route meta', async => {
 // 检查路由 meta 文件内容（静态分析）
 const src = await import('../../../pages/codegraph/playground.vue?raw').then(m => m.default).catch( => '')
 expect(src).toContain('requiresAdmin')
 })
 it('B: 页面标题"检索测试面板"可见', async => {
 const { default: PlaygroundPage } = await import('../../../pages/codegraph/playground.vue')
 const wrapper = mount(PlaygroundPage, {
 global: { stubs: stubComponents },
 })
 await flushPromises
 expect(wrapper.text).toContain('检索测试面板')
 })
 it('C: 页面描述文案存在', async => {
 const { default: PlaygroundPage } = await import('../../../pages/codegraph/playground.vue')
 const wrapper = mount(PlaygroundPage, {
 global: { stubs: stubComponents },
 })
 await flushPromises
 expect(wrapper.text).toContain('测试分层检索各阶段召回效果')
 })
 it('D: PlaygroundQueryInput 组件已挂载', async => {
 const { default: PlaygroundPage } = await import('../../../pages/codegraph/playground.vue')
 const wrapper = mount(PlaygroundPage, {
 global: { stubs: stubComponents },
 })
 await flushPromises
 expect(wrapper.find('.query-input-stub').exists).toBe(true)
 })
})
