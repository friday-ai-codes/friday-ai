import type { ColumnDef } from '@tanstack/vue-table'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import DataTable from '~/components/common/DataTable.vue'

// Mock useLocalStorage 避免 SSR 警告
vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  return {
    ...actual,
    useLocalStorage: (_key: string, defaultValue: unknown) => {
      return ref(defaultValue)
    },
  }
})

// 简化的 TriggerLog mock 类型（仅包含测试需要的字段）
interface MockTriggerLog {
  id: string
  event_type: string
  work_item_name: string
  status: string
  created_at: string
}

const columns: ColumnDef<MockTriggerLog>[] = [
  { accessorKey: 'status', header: '状态', enableSorting: true },
  { accessorKey: 'event_type', header: '触发类型', enableSorting: true },
  { accessorKey: 'work_item_name', header: '工作项', enableSorting: true },
  { accessorKey: 'created_at', header: '创建时间', enableSorting: true },
]

const testData: MockTriggerLog[] = [
  { id: '1', event_type: 'push', work_item_name: 'feat: 添加登录功能', status: 'completed', created_at: '2026-03-15T10:00:00Z' },
  { id: '2', event_type: 'pull_request', work_item_name: 'fix: 修复 CSS 样式', status: 'failed', created_at: '2026-03-15T11:00:00Z' },
  { id: '3', event_type: 'event', work_item_name: '定时同步任务', status: 'pending', created_at: '2026-03-15T12:00:00Z' },
  { id: '4', event_type: 'push', work_item_name: 'feat: 添加登录功能', status: 'completed', created_at: '2026-03-15T13:00:00Z' },
]

describe('logs DataTable', () => {
  it('渲染日志列表表格', () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'logs-test' } as any,
    })
    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr').length).toBe(testData.length)
  })

  it('搜索框过滤工作项名称', async () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'logs-search' } as any,
    })
    const allRows = wrapper.findAll('tbody tr').length
    const input = wrapper.find('input[placeholder]')
    await input.setValue('定时同步')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('tbody tr').length).toBeLessThan(allRows)
    expect(wrapper.findAll('tbody tr').length).toBe(1)
  })

  it('传入 onRowClick 时行有 cursor-pointer', () => {
    const wrapper = mount(DataTable, {
      props: {
        data: testData,
        columns,
        tableId: 'logs-click',
        onRowClick: () => {},
      } as any,
    })
    const firstRow = wrapper.find('tbody tr')
    expect(firstRow.classes()).toContain('cursor-pointer')
  })
})
