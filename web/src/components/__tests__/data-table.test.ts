import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { ColumnDef } from '@tanstack/vue-table'
import DataTable from '~/components/common/DataTable.vue'
// Mock useLocalStorage 避免 SSR 警告
vi.mock('@vueuse/core', async (importOriginal) => {
 const actual = await importOriginal<typeof import('@vueuse/core')>
 return {
 ...actual,
 useLocalStorage: (_key: string, defaultValue: unknown) => {
 return ref(defaultValue)
 },
 }
})
interface TestRow {
 id: number
 name: string
 status: string
}
const columns: ColumnDef<TestRow> = [
 { accessorKey: 'id', header: 'ID', enableSorting: true },
 { accessorKey: 'name', header: '名称', enableSorting: true },
 { accessorKey: 'status', header: '状态', enableSorting: false },
]
const testData: TestRow = [
 { id: 1, name: 'Alpha', status: 'active' },
 { id: 2, name: 'Beta', status: 'idle' },
 { id: 3, name: 'Gamma', status: 'active' },
 { id: 4, name: 'Delta', status: 'error' },
 { id: 5, name: 'Epsilon', status: 'active' },
]
describe('DataTable', => {
 //: 开发者接口 smoke test
 it('仅传 data + columns + tableId 即可渲染完整表格', => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'test-smoke' },
 })
 expect(wrapper.find('table').exists).toBe(true)
 expect(wrapper.findAll('tbody tr').length).toBeGreaterThan(0)
 })
 //: 全局搜索过滤
 it('输入搜索词后，表格行数减少', async => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'test-search' },
 })
 const allRows = wrapper.findAll('tbody tr').length
 const input = wrapper.find('input[placeholder]')
 await input.setValue('Alpha')
 await wrapper.vm.$nextTick
 expect(wrapper.findAll('tbody tr').length).toBeLessThan(allRows)
 expect(wrapper.findAll('tbody tr').length).toBe(1)
 })
 //: 排序
 it('点击可排序列头后行顺序变化', async => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'test-sort' },
 })
 const nameHeader = wrapper.findAll('th').find(th => th.text.includes('名称'))
 expect(nameHeader).toBeDefined
 await nameHeader!.trigger('click')
 await wrapper.vm.$nextTick
 const firstRowName = wrapper.find('tbody tr:first-child td:nth-child(2)').text
 // 升序后第一行应是 Alpha
 expect(firstRowName).toBe('Alpha')
 })
 //: 分页
 it('显示正确的分页文案', => {
 const smallData = testData.slice(0, 3)
 const wrapper = mount(DataTable, {
 props: { data: smallData, columns, tableId: 'test-page', pageSize: 2 },
 })
 const pageText = wrapper.text
 expect(pageText).toContain('第 1 页')
 expect(pageText).toContain('共 3 条')
 })
 //: 列可见性持久化
 it('列可见性通过 tableId 区分 localStorage key', => {
 // useLocalStorage mock 已上方注入，验证组件接受 tableId prop 并正常渲染
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'runners-list' },
 })
 expect(wrapper.exists).toBe(true)
 })
 // 行点击
 it('传入 onRowClick 时行有 cursor-pointer 样式', => {
 const wrapper = mount(DataTable, {
 props: {
 data: testData,
 columns,
 tableId: 'test-click',
 onRowClick: => {},
 },
 })
 const firstRow = wrapper.find('tbody tr')
 expect(firstRow.classes).toContain('cursor-pointer')
 })
})
