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
// 简化的 SystemUser mock 类型（仅包含测试需要的字段）
interface MockSystemUser {
 id: string
 username: string
 display_name: string
 is_active: boolean
 is_superuser: boolean
 created_at: string
}
const columns: ColumnDef<MockSystemUser> = [
 { accessorKey: 'username', header: '用户名', enableSorting: true },
 { accessorKey: 'display_name', header: '显示名', enableSorting: true },
 { accessorKey: 'is_active', header: '状态', enableSorting: false },
 { accessorKey: 'is_superuser', header: '角色', enableSorting: false },
 { accessorKey: 'created_at', header: '注册时间', enableSorting: true },
]
const testData: MockSystemUser = [
 { id: '1', username: 'admin', display_name: '管理员', is_active: true, is_superuser: true, created_at: '2026-01-01T00:00:00Z' },
 { id: '2', username: 'alice', display_name: 'Alice Wang', is_active: true, is_superuser: false, created_at: '2026-02-15T00:00:00Z' },
 { id: '3', username: 'bob', display_name: 'Bob Li', is_active: false, is_superuser: false, created_at: '2026-03-01T00:00:00Z' },
]
describe('Users DataTable', => {
 it('渲染用户列表表格', => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'users-test' } as Record<string, unknown>,
 })
 expect(wrapper.find('table').exists).toBe(true)
 expect(wrapper.findAll('tbody tr').length).toBe(testData.length)
 })
 it('搜索框过滤用户名', async => {
 const wrapper = mount(DataTable, {
 props: { data: testData, columns, tableId: 'users-search' } as Record<string, unknown>,
 })
 const allRows = wrapper.findAll('tbody tr').length
 const input = wrapper.find('input[placeholder]')
 await input.setValue('admin')
 await wrapper.vm.$nextTick
 expect(wrapper.findAll('tbody tr').length).toBeLessThan(allRows)
 expect(wrapper.findAll('tbody tr').length).toBe(1)
 })
})
