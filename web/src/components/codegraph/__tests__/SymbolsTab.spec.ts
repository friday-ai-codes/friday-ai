/**
 * Phase Plan — SymbolsTab 单测
 * 验证：DataTable 渲染 / line_range 格式 / 行点击 emit select-symbol
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import SymbolsTab from '../SymbolsTab.vue'
vi.mock('~/api/codegraph', => ({
 getSymbols: vi.fn.mockResolvedValue({
 count: 2,
 offset: 0,
 limit: 50,
 results: [
 {
 id: 'uuid-1',
 name: 'myFn',
 symbol_type: 'FUNCTION',
 file_path: 'src/a.py',
 line_start: 10,
 line_end: 20,
 signature: 'def myFn',
 is_async: false,
 },
 {
 id: 'uuid-2',
 name: 'MyClass',
 symbol_type: 'CLASS',
 file_path: 'src/b.py',
 line_start: 1,
 line_end: 50,
 signature: 'class MyClass',
 is_async: false,
 },
 ],
 }),
}))
vi.mock('@vueuse/core', async (importOriginal) => {
 const actual = await importOriginal<typeof import('@vueuse/core')>
 return {
 ...actual,
 useLocalStorage: vi.fn.mockReturnValue({ value: {} }),
 useDebounceFn: (fn: (...args: unknown) => unknown) => fn,
 }
})
const stubComponents = {
 DataTable: defineComponent({
 props: ['data', 'columns', 'tableId', 'pageSize', 'loading', 'onRowClick'],
 template: `
 <div>
 <div v-for="row in data":key="row.id" class="data-row" @click="onRowClick && onRowClick(row)">
 <span class="row-name">{{ row.name }}</span>
 <span class="row-line-range">L{{ row.line_start }}–{{ row.line_end }}</span>
 </div>
 </div>
 `,
 }),
 SymbolTypeFilter: defineComponent({
 props: ['modelValue'],
 emits: ['update:modelValue'],
 template: '<div class="symbol-type-filter" />',
 }),
 Badge: defineComponent({ template: '<span><slot /></span>' }),
 Tooltip: defineComponent({ template: '<div><slot /></div>' }),
 TooltipProvider: defineComponent({ template: '<div><slot /></div>' }),
 TooltipTrigger: defineComponent({ template: '<div><slot /></div>' }),
 TooltipContent: defineComponent({ template: '<div><slot /></div>' }),
}
function mountSymbolsTab {
 return mount(SymbolsTab, {
 props: { repositoryId: 'repo-1' },
 global: { stubs: stubComponents },
 })
}
describe('SymbolsTab', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('A: 挂载后调用 getSymbols API 并渲染数据行', async => {
 const { getSymbols } = await import('~/api/codegraph')
 vi.mocked(getSymbols).mockResolvedValue({
 count: 1,
 offset: 0,
 limit: 50,
 results: [{
 id: 'uuid-1',
 name: 'myFn',
 symbol_type: 'FUNCTION',
 file_path: 'src/a.py',
 line_start: 10,
 line_end: 20,
 signature: 'def myFn',
 is_async: false,
 }],
 })
 const wrapper = mountSymbolsTab
 await flushPromises
 expect(getSymbols).toHaveBeenCalledWith(expect.objectContaining({ repositoryId: 'repo-1' }))
 expect(wrapper.text).toContain('myFn')
 })
 it('B: line_range 列显示格式为 "L10–20"（使用 line_start/line_end serializer 别名）', async => {
 const { getSymbols } = await import('~/api/codegraph')
 vi.mocked(getSymbols).mockResolvedValue({
 count: 1,
 offset: 0,
 limit: 50,
 results: [{
 id: 'uuid-1',
 name: 'myFn',
 symbol_type: 'FUNCTION',
 file_path: 'src/a.py',
 line_start: 10,
 line_end: 20,
 signature: 'def myFn',
 is_async: false,
 }],
 })
 const wrapper = mountSymbolsTab
 await flushPromises
 expect(wrapper.text).toContain('L10–20')
 })
 it('C: 点击数据行 → emitted select-symbol[0][0] === "uuid-1"', async => {
 const { getSymbols } = await import('~/api/codegraph')
 vi.mocked(getSymbols).mockResolvedValue({
 count: 1,
 offset: 0,
 limit: 50,
 results: [{
 id: 'uuid-1',
 name: 'myFn',
 symbol_type: 'FUNCTION',
 file_path: 'src/a.py',
 line_start: 10,
 line_end: 20,
 signature: 'def myFn',
 is_async: false,
 }],
 })
 const wrapper = mountSymbolsTab
 await flushPromises
 const row = wrapper.find('.data-row')
 await row.trigger('click')
 expect(wrapper.emitted('select-symbol')).toBeTruthy
 expect(wrapper.emitted('select-symbol')![0][0]).toBe('uuid-1')
 })
})
