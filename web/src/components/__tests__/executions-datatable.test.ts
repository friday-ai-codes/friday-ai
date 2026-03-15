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
// 简化的 WorkflowExecution mock 类型（仅包含测试需要的字段）
interface MockWorkflowExecution {
 id: string
 workflow_name: string
 status: string
 trigger_type: string
 duration: number | null
 created_at: string
}
const columns: ColumnDef<MockWorkflowExecution> = [
 { accessorKey: 'status', header: '状态', enableSorting: true },
 { accessorKey: 'workflow_name', header: '工作流', enableSorting: true },
 { accessorKey: 'trigger_type', header: '触发类型', enableSorting: false },
 { accessorKey: 'duration', header: '耗时', enableSorting: true },
 { accessorKey: 'created_at', header: '创建时间', enableSorting: true },
]
const testData: MockWorkflowExecution = [
 { id: '1', workflow_name: '代码审查', status: 'completed', trigger_type: 'manual', duration: 120, created_at: '2026-03-15T10:00:00Z' },
 { id: '2', workflow_name: '部署流水线', status: 'running', trigger_type: 'webhook', duration: null, created_at: '2026-03-15T11:00:00Z' },
 { id: '3', workflow_name: '数据同步', status: 'failed', trigger_type: 'schedule', duration: 45, created_at: '2026-03-15T12:00:00Z' },
 { id: '4', workflow_name: '代码审查', status: 'pending', trigger_type: 'manual', duration: null, created_at: '2026-03-15T13:00:00Z' },
]
describe('Executions DataTable', => {
 it('渲染执行列表表格', => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'executions-test' },
 })
 expect(wrapper.find('table').exists).toBe(true)
 expect(wrapper.findAll('tbody tr').length).toBe(testData.length)
 })
 it('搜索框过滤工作流名称', async => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'executions-search' },
 })
 const allRows = wrapper.findAll('tbody tr').length
 const input = wrapper.find('input[placeholder]')
 await input.setValue('代码审查')
 await wrapper.vm.$nextTick
 expect(wrapper.findAll('tbody tr').length).toBeLessThan(allRows)
 // "代码审查" 匹配 2 条记录
 expect(wrapper.findAll('tbody tr').length).toBe(2)
 })
 it('传入 onRowClick 时行有 cursor-pointer', => {
 const wrapper = mount(DataTable, {
 props: {
 data: testData,
 columns,
 tableId: 'executions-click',
 onRowClick: => {},
 },
 })
 const firstRow = wrapper.find('tbody tr')
 expect(firstRow.classes).toContain('cursor-pointer')
 })
})
