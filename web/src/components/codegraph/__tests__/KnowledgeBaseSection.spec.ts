/**
 * Phase Plan — KnowledgeBaseSection 单测
 * 验证：折叠展开后包含 3 个 Tab trigger（Symbols / 调用关系 DAG / 导入）
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import KnowledgeBaseSection from '../KnowledgeBaseSection.vue'
vi.mock('~/api/codegraph', => ({
 getSymbols: vi.fn.mockResolvedValue({ count: 0, offset: 0, limit: 50, results: }),
 getImports: vi.fn.mockResolvedValue({ count: 0, offset: 0, limit: 50, results: }),
}))
vi.mock('@vueuse/core', async (importOriginal) => {
 const actual = await importOriginal<typeof import('@vueuse/core')>
 return {
 ...actual,
 useLocalStorage: vi.fn.mockImplementation((_key: string, defaultVal: unknown) => {
 const val = ref(defaultVal)
 return val
 }),
 useDebounceFn: (fn: (...args: unknown) => unknown) => fn,
 }
})
const stubComponents = {
 SymbolsTab: defineComponent({
 props: ['repositoryId'],
 emits: ['select-symbol'],
 template: '<div class="symbols-tab-stub" />',
 }),
 ImportsTab: defineComponent({
 props: ['repositoryId'],
 template: '<div class="imports-tab-stub" />',
 }),
 DependenciesTab: defineComponent({
 props: ['repositoryId'],
 emits: ['select-symbol'],
 template: '<div class="dependencies-tab-stub" />',
 }),
 Button: defineComponent({ template: '<button v-bind="$attrs"><slot /></button>' }),
 Badge: defineComponent({ template: '<span><slot /></span>' }),
}
function mountSection {
 return mount(KnowledgeBaseSection, {
 props: { repositoryId: 'repo-1' },
 global: { stubs: stubComponents },
 attachTo: document.body,
 })
}
describe('knowledgeBaseSection', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('a: 包含卡片标题"代码图谱"', async => {
 const wrapper = mountSection
 await flushPromises
 expect(wrapper.text).toContain('代码图谱')
 })
 it('b: 默认展开后包含 4 个 Tab trigger：Symbols / 调用关系 DAG / 依赖关系 / 导入', async => {
 const wrapper = mountSection
 await flushPromises
 await wrapper.vm.$nextTick
 const text = wrapper.text
 expect(text).toContain('Symbols')
 expect(text).toContain('调用关系 DAG')
 expect(text).toContain('依赖关系')
 expect(text).toContain('导入')
 })
 it('c: 默认展开（isOpen=true，方便用户直接看到代码图谱内容）', async => {
 const wrapper = mountSection
 await flushPromises
 expect((wrapper.vm as unknown as { isOpen: boolean }).isOpen).toBe(true)
 })
})
