import type { ColumnDef } from '@tanstack/vue-table'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { h, ref } from 'vue'
import DataTable from '~/components/common/DataTable.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'

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

// 简化的 WorkflowExecution mock 类型（仅包含测试需要的字段）
interface MockWorkflowExecution {
  id: string
  workflow: string
  workflow_name: string
  status: string
  trigger_type: string
  duration: number | null
  created_at: string
}

// 与页面实现一致的触发类型中文标签映射（TRIG-02: 无 schedule）
const triggerTypeLabels: Record<string, string> = {
  manual: '手动触发',
  webhook: 'Webhook',
  event: '事件触发',
}

function formatDuration(duration: number | null): string {
  if (duration == null)
    return '-'
  if (duration < 60)
    return `${Math.round(duration)}s`
  const mins = Math.floor(duration / 60)
  const secs = Math.round(duration % 60)
  return `${mins}m ${secs}s`
}

// 与页面实现一致的 ColumnDef 定义
const columns: ColumnDef<MockWorkflowExecution>[] = [
  {
    accessorKey: 'status',
    header: '状态',
    cell: ({ row }) => h(StatusBadge, { type: 'execution', status: row.original.status }),
    enableSorting: false,
    enableGlobalFilter: false,
  },
  {
    accessorKey: 'workflow_name',
    header: '工作流',
    cell: ({ row }) => h('span', { class: 'font-medium text-foreground' }, row.original.workflow_name),
    enableSorting: true,
  },
  {
    id: 'project',
    header: '项目',
    cell: ({ row }) => h('span', { class: 'text-sm' }, row.original.workflow || '-'),
    enableSorting: false,
  },
  {
    accessorKey: 'trigger_type',
    header: '触发类型',
    cell: ({ row }) => h('span', { class: 'text-sm' }, triggerTypeLabels[row.original.trigger_type] || row.original.trigger_type),
    enableSorting: false,
  },
  {
    accessorKey: 'duration',
    header: '耗时',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, formatDuration(row.original.duration)),
    enableSorting: true,
  },
  {
    accessorKey: 'created_at',
    header: '创建时间',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, new Date(row.original.created_at).toLocaleString('zh-CN')),
    enableSorting: true,
  },
]

const testData: MockWorkflowExecution[] = [
  { id: '1', workflow: 'wf-1', workflow_name: '代码审查', status: 'completed', trigger_type: 'manual', duration: 45, created_at: '2026-03-15T10:00:00Z' },
  { id: '2', workflow: 'wf-2', workflow_name: '部署流水线', status: 'running', trigger_type: 'webhook', duration: null, created_at: '2026-03-15T11:00:00Z' },
  { id: '3', workflow: 'wf-1', workflow_name: '代码审查', status: 'failed', trigger_type: 'event', duration: 120, created_at: '2026-03-15T12:00:00Z' },
  { id: '4', workflow: 'wf-3', workflow_name: '数据同步', status: 'pending', trigger_type: 'event', duration: null, created_at: '2026-03-15T13:00:00Z' },
]

describe('executions DataTable', () => {
  it('渲染执行列表表格', () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'executions-test' } as any,
    })
    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.findAll('tbody tr').length).toBe(testData.length)
  })

  it('表头包含正确的列名', () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'executions-headers' } as any,
    })
    const headers = wrapper.findAll('th').map(th => th.text())
    expect(headers).toContain('状态')
    expect(headers).toContain('工作流')
    expect(headers).toContain('项目')
    expect(headers).toContain('触发类型')
    expect(headers).toContain('耗时')
    expect(headers).toContain('创建时间')
  })

  it('触发类型显示中文标签', () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'executions-trigger' } as any,
    })
    const text = wrapper.text()
    expect(text).toContain('手动触发')
    expect(text).toContain('Webhook')
    expect(text).toContain('事件触发')
  })

  it('耗时格式化正确（秒/分秒/空值）', () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'executions-duration' } as any,
    })
    const text = wrapper.text()
    // 45s
    expect(text).toContain('45s')
    // null → '-'
    expect(text).toContain('-')
    // 120s → 2m 0s
    expect(text).toContain('2m 0s')
  })

  it('搜索框过滤工作流名称', async () => {
    const wrapper = mount(DataTable, {
      props: { data: testData, columns, tableId: 'executions-search' } as any,
    })
    const allRows = wrapper.findAll('tbody tr').length
    const input = wrapper.find('input[placeholder]')
    await input.setValue('代码审查')
    await wrapper.vm.$nextTick()
    expect(wrapper.findAll('tbody tr').length).toBeLessThan(allRows)
    // "代码审查" 匹配 2 条记录
    expect(wrapper.findAll('tbody tr').length).toBe(2)
  })

  it('传入 onRowClick 时行有 cursor-pointer', () => {
    const wrapper = mount(DataTable, {
      props: {
        data: testData,
        columns,
        tableId: 'executions-click',
        onRowClick: () => {},
      } as any,
    })
    const firstRow = wrapper.find('tbody tr')
    expect(firstRow.classes()).toContain('cursor-pointer')
  })

  it('空数据时渲染空状态', () => {
    const wrapper = mount(DataTable, {
      props: { data: [], columns, tableId: 'executions-empty' } as any,
    })
    // DataTable 空状态行
    expect(wrapper.findAll('tbody tr').length).toBe(1)
  })

  it('loading 状态显示 skeleton 行', () => {
    const wrapper = mount(DataTable, {
      props: { data: [], columns, tableId: 'executions-loading', loading: true } as any,
    })
    // DataTable loading 状态渲染 8 行 skeleton
    expect(wrapper.findAll('tbody tr').length).toBe(8)
  })
})
