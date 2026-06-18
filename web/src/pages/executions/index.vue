<script setup lang="ts">
import type { ColumnDef, RowSelectionState } from '@tanstack/vue-table'
import type { WorkflowExecution } from '~/stores/useExecutionsStore'
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, h, ref } from 'vue'
import { useRouter } from 'vue-router'

import api from '~/api/client'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useTableUrlState } from '~/composables/useTableUrlState'
import { getStatusConfig } from '~/config/status'
import { useAuthStore } from '~/stores/auth'
import { useSpacesStore } from '~/stores/spaces'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

const router = useRouter()
const spacesStore = useSpacesStore()
const workflowsStore = useWorkflowsStore()
const authStore = useAuthStore()
const queryClient = useQueryClient()
const { handleError } = useErrorHandler()
const { success } = useToast()

// Filters + 表格状态全部持久化到 URL（刷新可恢复）；computed 代理保持下方命名引用不变。
const { pagination, sorting, globalFilter, facets } = useTableUrlState({
  facets: {
    status: { type: 'single', default: 'all' },
    space_id: { type: 'single', default: 'all' },
    workflow_id: { type: 'single', default: 'all' },
    days: { type: 'single', default: '7' },
  },
})
const statusFilter = computed<string>({ get: () => facets.status, set: v => (facets.status = v) })
const spaceFilter = computed<string>({ get: () => facets.space_id, set: v => (facets.space_id = v) })
const workflowFilter = computed<string>({ get: () => facets.workflow_id, set: v => (facets.workflow_id = v) })
const timeRangeFilter = computed<string>({ get: () => facets.days, set: v => (facets.days = v) })

// 时间范围选项
const timeRangeOptions = [
  { value: '1', label: '近 1 天' },
  { value: '3', label: '近 3 天' },
  { value: '7', label: '近 7 天' },
  { value: '14', label: '近 14 天' },
  { value: '30', label: '近 30 天' },
  { value: 'all', label: '全部时间' },
]

// OBS-03: 状态筛选项与后端 ExecutionStatus 对齐（server/workflows/models/execution.py）
const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'running', label: '运行中' },
  { value: 'pending', label: '等待中' },
  { value: 'paused', label: '已暂停' },
  { value: 'waiting_approval', label: '待审批' },
  { value: 'suspended', label: '挂起中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
  { value: 'timeout', label: '超时' },
]

// 计算查询参数
const queryParams = computed(() => {
  const params: Record<string, string> = {}
  if (workflowFilter.value !== 'all')
    params.workflow_id = workflowFilter.value
  if (spaceFilter.value !== 'all')
    params.space_id = spaceFilter.value
  if (timeRangeFilter.value !== 'all') {
    const days = Number.parseInt(timeRangeFilter.value)
    const date = new Date()
    date.setDate(date.getDate() - days)
    params.created_after = date.toISOString()
  }
  return params
})

// 使用 TanStack Query 获取执行列表
const { data: executions, isLoading, isFetching } = useQuery({
  queryKey: ['executions', queryParams],
  queryFn: async () => {
    const response = await api.get<{ results: WorkflowExecution[] } | WorkflowExecution[]>(
      '/workflow-executions/',
      queryParams.value,
    )
    return Array.isArray(response) ? response : response.results || []
  },
  placeholderData: keepPreviousData, // 刷新时保持旧数据，避免抖动
  refetchInterval: (query) => {
    // 只有在有运行中或等待中的任务时才自动刷新
    const data = query.state.data
    if (data?.some(e => e.status === 'running' || e.status === 'pending')) {
      return 5000
    }
    return false
  },
  staleTime: 3000, // 3秒内不重新请求
})

// 加载空间和工作流列表（用于筛选下拉框）
useQuery({
  queryKey: ['projects'],
  queryFn: () => spacesStore.fetchSpaces(),
  staleTime: 60000,
})

useQuery({
  queryKey: ['workflows'],
  queryFn: () => workflowsStore.fetchWorkflows(),
  staleTime: 60000,
})

// 计算统计数据
const stats = computed(() => {
  const execs = executions.value || []
  return {
    total: execs.length,
    running: execs.filter(e => e.status === 'running').length,
    pending: execs.filter(e => e.status === 'pending').length,
    // OBS-03 / Pitfall 7: execution 级"等待"判 suspended（ExecutionStatus 无 waiting_approval，
    // 见 server/workflows/models/execution.py）；node 级 waiting_approval 经 some() 旁路保留。
    waitingApproval: execs.filter(e => e.status === 'suspended' || e.node_executions?.some(n => n.status === 'waiting_approval')).length,
    completed: execs.filter(e => e.status === 'completed').length,
    failed: execs.filter(e => e.status === 'failed').length,
  }
})

const statCards = computed(() => [
  {
    key: 'total',
    label: '总执行',
    value: stats.value.total,
    icon: 'icon-[lucide--activity]',
    iconClass: 'text-foreground/70',
    surfaceClass: 'bg-foreground/6 text-foreground/70',
    barClass: 'bg-foreground/20',
  },
  {
    key: 'running',
    label: '运行中',
    value: stats.value.running,
    icon: 'icon-[lucide--loader-2]',
    iconClass: stats.value.running > 0 ? 'animate-spin text-primary' : 'text-primary',
    surfaceClass: 'bg-primary/10 text-primary',
    barClass: 'bg-primary',
  },
  {
    key: 'approval',
    label: '待审批',
    value: stats.value.waitingApproval,
    icon: 'icon-[lucide--user-check]',
    iconClass: 'text-amber-600',
    surfaceClass: 'bg-amber-500/10 text-amber-700',
    barClass: 'bg-amber-500',
  },
  {
    key: 'completed',
    label: '已完成',
    value: stats.value.completed,
    icon: 'icon-[lucide--check-circle]',
    iconClass: 'text-emerald-600',
    surfaceClass: 'bg-emerald-500/10 text-emerald-700',
    barClass: 'bg-emerald-500',
  },
  {
    key: 'failed',
    label: '失败',
    value: stats.value.failed,
    icon: 'icon-[lucide--x-circle]',
    iconClass: 'text-red-600',
    surfaceClass: 'bg-red-500/10 text-red-700',
    barClass: 'bg-red-500',
  },
])

// 根据状态筛选
const filteredExecutions = computed(() => {
  let execs = executions.value || []
  if (statusFilter.value && statusFilter.value !== 'all') {
    execs = statusFilter.value === 'waiting_approval'
      ? execs.filter(e => hasWaitingApproval(e))
      : execs.filter(e => e.status === statusFilter.value)
  }
  return execs
})

// --- admin 批量删除 ---
const isAdmin = computed(() => authStore.isAdmin)
const rowSelection = ref<RowSelectionState>({})
const selectedIds = computed(() => Object.keys(rowSelection.value).filter(k => rowSelection.value[k]))
const batchDeleteOpen = ref(false)
const batchDeleting = ref(false)

interface BatchDeleteResult {
  deleted: number
  skipped_active: string[]
  forbidden: string[]
  not_found: string[]
}

async function handleBatchDelete() {
  if (!selectedIds.value.length)
    return
  batchDeleting.value = true
  try {
    const result = await api.post<BatchDeleteResult>(
      '/workflow-executions/batch-delete/',
      { ids: selectedIds.value },
    )
    const skipped = result.skipped_active.length
    success(
      `已删除 ${result.deleted} 条执行`,
      skipped > 0 ? `${skipped} 条运行中/等待中的执行已跳过` : undefined,
    )
    rowSelection.value = {}
    batchDeleteOpen.value = false
    await queryClient.invalidateQueries({ queryKey: ['executions'] })
  }
  catch (e: unknown) {
    handleError(e, '批量删除执行')
  }
  finally {
    batchDeleting.value = false
  }
}

// --- 辅助函数 ---

/** 通过 workflowsStore 反查空间名称 */
function getSpaceName(workflowId: string): string {
  const wf = workflowsStore.workflows.find(w => w.id === workflowId)
  return wf?.project_name || '-'
}

/** 触发类型中文标签映射（TRIG-02: 移除 schedule 定时触发） */
const triggerTypeLabels: Record<string, string> = {
  manual: '手动触发',
  webhook: 'Webhook',
  event: '事件触发',
}

const triggerTypeIcons: Record<string, string> = {
  manual: 'icon-[lucide--mouse-pointer-click]',
  webhook: 'icon-[lucide--webhook]',
  event: 'icon-[lucide--zap]',
}

/** 格式化耗时 */
function formatDuration(duration: number | null): string {
  if (duration == null)
    return '-'
  if (duration < 60)
    return `${Math.round(duration)}s`
  const mins = Math.floor(duration / 60)
  const secs = Math.round(duration % 60)
  return `${mins}m ${secs}s`
}

/** 相对时间 + 完整时间 */
function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

const executionStatusPillClasses: Record<string, string> = {
  pending: 'bg-slate-500/10 text-slate-600 ring-slate-500/15',
  queued: 'bg-slate-500/10 text-slate-600 ring-slate-500/15',
  running: 'bg-teal-500/10 text-teal-700 ring-teal-500/20',
  paused: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  completed: 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20',
  failed: 'bg-red-500/10 text-red-700 ring-red-500/20',
  cancelled: 'bg-slate-500/10 text-slate-600 ring-slate-500/15',
  timeout: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  waiting_approval: 'bg-amber-500/10 text-amber-700 ring-amber-500/20',
  waiting_input: 'bg-blue-500/10 text-blue-700 ring-blue-500/20',
}

function hasWaitingApproval(execution: WorkflowExecution): boolean {
  return execution.status === 'suspended'
    || execution.node_executions?.some(n => n.status === 'waiting_approval')
}

function getExecutionDisplayStatus(execution: WorkflowExecution): string {
  return hasWaitingApproval(execution) ? 'waiting_approval' : execution.status
}

function renderExecutionStatusPill(execution: WorkflowExecution) {
  const status = getExecutionDisplayStatus(execution)
  const config = getStatusConfig('execution', status)
  return h(
    'span',
    {
      class: [
        'execution-status-pill',
        `execution-status-pill--${status}`,
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1',
        executionStatusPillClasses[status] ?? 'bg-muted text-muted-foreground ring-border/60',
      ],
    },
    [
      h('span', {
        class: [
          `icon-[${config.icon}]`,
          'text-xs',
          config.animate ? 'animate-spin' : '',
        ],
      }),
      config.label,
    ],
  )
}

// --- DataTable 列定义 ---
const columns: ColumnDef<WorkflowExecution>[] = [
  {
    accessorKey: 'status',
    header: '状态',
    cell: ({ row }) => renderExecutionStatusPill(row.original),
    enableSorting: false,
    enableGlobalFilter: false,
  },
  {
    accessorKey: 'workflow_name',
    header: '工作流',
    cell: ({ row }) => h('div', { class: 'flex flex-col gap-0.5 min-w-0' }, [
      h('span', { class: 'text-sm font-semibold text-foreground truncate' }, row.original.workflow_name),
      h('span', { class: 'text-xs text-muted-foreground font-mono' }, `#${row.original.id.slice(0, 8)}`),
    ]),
    enableSorting: true,
  },
  {
    id: 'project',
    header: '空间',
    cell: ({ row }) => h('span', { class: 'inline-flex items-center gap-1.5 text-sm text-muted-foreground' }, [
      h('span', { class: 'icon-[lucide--folder] text-xs text-muted-foreground/70' }),
      getSpaceName(row.original.workflow),
    ]),
    enableSorting: false,
  },
  {
    accessorKey: 'trigger_type',
    header: '触发类型',
    cell: ({ row }) => h('span', { class: 'inline-flex items-center gap-1.5 rounded-md bg-muted/60 px-2 py-1 text-xs font-medium text-foreground/80' }, [
      h('span', { class: [triggerTypeIcons[row.original.trigger_type] ?? 'icon-[lucide--circle-dot]', 'text-xs text-muted-foreground'] }),
      triggerTypeLabels[row.original.trigger_type] || row.original.trigger_type,
    ]),
    enableSorting: false,
  },
  {
    accessorKey: 'duration',
    header: '耗时',
    cell: ({ row }) => h('span', { class: 'inline-flex items-center gap-1 text-sm tabular-nums text-muted-foreground' }, [
      h('span', { class: 'icon-[lucide--timer] text-xs text-muted-foreground/60' }),
      formatDuration(row.original.duration),
    ]),
    enableSorting: true,
  },
  {
    accessorKey: 'created_at',
    header: '创建时间',
    cell: ({ row }) => h('span', { class: 'text-sm tabular-nums text-muted-foreground' }, formatDateTime(row.original.created_at)),
    enableSorting: true,
  },
  {
    id: 'actions',
    header: '操作',
    cell: ({ row }) => {
      if (!hasWaitingApproval(row.original)) {
        return h('span', { class: 'text-xs text-muted-foreground' }, '-')
      }

      return h(
        Button,
        {
          variant: 'outline',
          size: 'sm',
          class: 'h-8 gap-1.5 text-amber-700 border-amber-500/30 hover:bg-amber-500/10',
          onClick: (event: MouseEvent) => {
            event.stopPropagation()
            router.push(`/executions/${row.original.id}`)
          },
        },
        () => [
          h('span', { class: 'icon-[lucide--user-check] text-sm' }),
          '处理审批',
        ],
      )
    },
    enableSorting: false,
    enableGlobalFilter: false,
  },
]
</script>

<template>
  <PageContainer show-background>
    <!-- Header -->
    <PageHeader
      icon="lucide--play-circle"
      icon-gradient="from-primary/20 to-primary/10"
      icon-color="text-primary"
      title="执行监控"
      description="实时追踪工作流执行状态"
    >
      <template #title-suffix>
        <!-- 后台刷新指示器 -->
        <span
          v-if="isFetching && !isLoading"
          class="icon-[lucide--refresh-cw] text-muted-foreground animate-spin"
          title="正在刷新..."
        />
      </template>
    </PageHeader>

    <!-- Stats cards -->
    <div class="mt-5 mb-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <div
        v-for="item in statCards"
        :key="item.key"
        class="execution-stat-card group relative overflow-hidden rounded-xl border border-border/60 bg-card/90 px-4 py-3.5 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md"
      >
        <span class="absolute inset-x-0 top-0 h-0.5 opacity-70" :class="item.barClass" />
        <div class="flex items-center gap-3">
          <div class="flex size-10 shrink-0 items-center justify-center rounded-lg" :class="item.surfaceClass">
            <span class="text-lg" :class="[item.icon, item.iconClass]" />
          </div>
          <div class="min-w-0">
            <span class="block text-xs font-medium text-muted-foreground">{{ item.label }}</span>
            <span class="block text-2xl font-bold leading-7 tabular-nums text-foreground">{{ item.value }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- DataTable -- 集成搜索/排序/分页/列可见性/批量选择 -->
    <DataTable
      v-model:row-selection="rowSelection"
      v-model:pagination="pagination"
      v-model:sorting="sorting"
      v-model:global-filter="globalFilter"
      :data="filteredExecutions"
      :columns="columns"
      table-id="executions-list"
      :loading="isLoading"
      :selectable="isAdmin"
      :get-row-id="(e: WorkflowExecution) => e.id"
      search-placeholder="搜索工作流..."
      :on-row-click="(execution) => router.push(`/executions/${execution.id}`)"
    >
      <template #filters>
        <div class="executions-filter-strip flex flex-wrap items-center gap-2">
          <Select v-model="statusFilter">
            <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/90">
              <SelectValue placeholder="全部状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </SelectItem>
            </SelectContent>
          </Select>

          <Select v-model="spaceFilter">
            <SelectTrigger class="h-9 w-[160px] rounded-lg bg-background/90">
              <SelectValue placeholder="全部空间" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                全部空间
              </SelectItem>
              <SelectItem v-for="project in spacesStore.spaces" :key="project.id" :value="project.id">
                {{ project.name }}
              </SelectItem>
            </SelectContent>
          </Select>

          <Select v-model="workflowFilter">
            <SelectTrigger class="h-9 w-[180px] rounded-lg bg-background/90">
              <SelectValue placeholder="全部工作流" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">
                全部工作流
              </SelectItem>
              <SelectItem v-for="workflow in workflowsStore.workflows" :key="workflow.id" :value="workflow.id">
                {{ workflow.name }}
              </SelectItem>
            </SelectContent>
          </Select>

          <Select v-model="timeRangeFilter">
            <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/90">
              <SelectValue placeholder="时间范围" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="opt in timeRangeOptions" :key="opt.value" :value="opt.value">
                {{ opt.label }}
              </SelectItem>
            </SelectContent>
          </Select>

          <Button
            v-if="statusFilter !== 'all' || spaceFilter !== 'all' || workflowFilter !== 'all' || timeRangeFilter !== '7'"
            variant="ghost"
            size="sm"
            class="h-9 text-muted-foreground hover:text-foreground"
            @click="statusFilter = 'all'; spaceFilter = 'all'; workflowFilter = 'all'; timeRangeFilter = '7'"
          >
            <span class="icon-[lucide--x] mr-1" />
            清除筛选
          </Button>
        </div>
      </template>

      <!-- 批量操作（仅 admin 勾选行后出现） -->
      <template #selection="{ count }">
        <Button
          variant="destructive"
          size="sm"
          class="h-8 gap-1.5"
          @click="batchDeleteOpen = true"
        >
          <span class="icon-[lucide--trash-2] text-sm" />
          删除所选（{{ count }}）
        </Button>
      </template>
    </DataTable>

    <!-- 批量删除确认 -->
    <AlertDialog v-model:open="batchDeleteOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>批量删除执行</AlertDialogTitle>
          <AlertDialogDescription>
            确定要删除选中的 {{ selectedIds.length }} 条执行记录吗？
            运行中或等待中的执行会被自动跳过。此操作无法撤销。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel :disabled="batchDeleting">
            取消
          </AlertDialogCancel>
          <AlertDialogAction
            class="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            :disabled="batchDeleting"
            @click.prevent="handleBatchDelete"
          >
            <span v-if="batchDeleting" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
            {{ batchDeleting ? '删除中...' : '确认删除' }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </PageContainer>
</template>
