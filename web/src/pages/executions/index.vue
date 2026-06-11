<script setup lang="ts">
import type { ColumnDef } from '@tanstack/vue-table'
import type { WorkflowExecution } from '~/stores/useExecutionsStore'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, h, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import api from '~/api/client'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { getStatusConfig } from '~/config/status'
import { useSpacesStore } from '~/stores/spaces'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

const route = useRoute()
const router = useRouter()
const spacesStore = useSpacesStore()
const workflowsStore = useWorkflowsStore()

// Filters
const statusFilter = ref<string>(route.query.status as string || 'all')
const spaceFilter = ref<string>(route.query.space_id as string || 'all')
const workflowFilter = ref<string>(route.query.workflow_id as string || 'all')
const timeRangeFilter = ref<string>(route.query.days as string || '7')

// 时间范围选项
const timeRangeOptions = [
  { value: '1', label: '近 1 天' },
  { value: '3', label: '近 3 天' },
  { value: '7', label: '近 7 天' },
  { value: '14', label: '近 14 天' },
  { value: '30', label: '近 30 天' },
  { value: 'all', label: '全部时间' },
]

const statusOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'running', label: '运行中' },
  { value: 'pending', label: '等待中' },
  { value: 'paused', label: '已暂停' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
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
    waitingApproval: execs.filter(e => e.status === 'waiting_approval' || e.node_executions?.some(n => n.status === 'waiting_approval')).length,
    completed: execs.filter(e => e.status === 'completed').length,
    failed: execs.filter(e => e.status === 'failed').length,
  }
})

const statCards = computed(() => [
  {
    key: 'running',
    label: '运行中',
    value: stats.value.running,
    icon: 'icon-[lucide--loader-2]',
    iconClass: stats.value.running > 0 ? 'animate-spin text-primary' : 'text-primary',
    surfaceClass: 'bg-primary/10 text-primary',
  },
  {
    key: 'approval',
    label: '待审批',
    value: stats.value.waitingApproval,
    icon: 'icon-[lucide--user-check]',
    iconClass: 'text-amber-600',
    surfaceClass: 'bg-amber-500/10 text-amber-700',
  },
  {
    key: 'completed',
    label: '已完成',
    value: stats.value.completed,
    icon: 'icon-[lucide--check-circle]',
    iconClass: 'text-emerald-600',
    surfaceClass: 'bg-emerald-500/10 text-emerald-700',
  },
  {
    key: 'failed',
    label: '失败',
    value: stats.value.failed,
    icon: 'icon-[lucide--x-circle]',
    iconClass: 'text-red-600',
    surfaceClass: 'bg-red-500/10 text-red-700',
  },
])

// 根据状态筛选
const filteredExecutions = computed(() => {
  let execs = executions.value || []
  if (statusFilter.value && statusFilter.value !== 'all') {
    execs = execs.filter(e => e.status === statusFilter.value)
  }
  return execs
})

// Watch filters and update URL
watch([statusFilter, spaceFilter, workflowFilter, timeRangeFilter], () => {
  const query: Record<string, string> = {}
  if (statusFilter.value && statusFilter.value !== 'all')
    query.status = statusFilter.value
  if (spaceFilter.value && spaceFilter.value !== 'all')
    query.space_id = spaceFilter.value
  if (workflowFilter.value && workflowFilter.value !== 'all')
    query.workflow_id = workflowFilter.value
  if (timeRangeFilter.value && timeRangeFilter.value !== '7')
    query.days = timeRangeFilter.value
  router.replace({ query })
})

// --- 辅助函数 ---

/** 通过 workflowsStore 反查空间名称 */
function getSpaceName(workflowId: string): string {
  const wf = workflowsStore.workflows.find(w => w.id === workflowId)
  return wf?.project_name || '-'
}

/** 触发类型中文标签映射 */
const triggerTypeLabels: Record<string, string> = {
  manual: '手动触发',
  webhook: 'Webhook',
  schedule: '定时触发',
  event: '事件触发',
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

function renderExecutionStatusPill(status: string) {
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
    cell: ({ row }) => renderExecutionStatusPill(row.original.status),
    enableSorting: false,
    enableGlobalFilter: false,
  },
  {
    accessorKey: 'workflow_name',
    header: '工作流',
    cell: ({ row }) => h('span', { class: 'text-sm font-semibold text-foreground' }, row.original.workflow_name),
    enableSorting: true,
  },
  {
    id: 'project',
    header: '空间',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, getSpaceName(row.original.workflow)),
    enableSorting: false,
  },
  {
    accessorKey: 'trigger_type',
    header: '触发类型',
    cell: ({ row }) => h('span', { class: 'text-sm text-foreground/80' }, triggerTypeLabels[row.original.trigger_type] || row.original.trigger_type),
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
      <template #actions>
        <!-- Stats cards -->
        <div class="flex flex-wrap gap-2.5">
          <div
            v-for="item in statCards"
            :key="item.key"
            class="execution-stat-card flex min-w-[132px] items-center gap-3 rounded-lg border border-border/60 bg-card/85 px-3.5 py-2 shadow-[0_1px_2px_rgba(15,23,42,0.04)]"
          >
            <div class="flex size-9 items-center justify-center rounded-lg" :class="item.surfaceClass">
              <span class="text-lg" :class="[item.icon, item.iconClass]" />
            </div>
            <div class="min-w-0">
              <span class="block text-xs font-medium text-muted-foreground">{{ item.label }}</span>
              <span class="block text-xl font-bold leading-6 tabular-nums text-foreground">{{ item.value }}</span>
            </div>
          </div>
        </div>
      </template>
    </PageHeader>

    <!-- DataTable -- 集成搜索/排序/分页/列可见性 -->
    <div class="executions-table">
      <DataTable
        :data="filteredExecutions"
        :columns="columns"
        table-id="executions-list"
        :loading="isLoading"
        :on-row-click="(execution) => router.push(`/executions/${execution.id}`)"
      >
        <template #filters>
          <div class="executions-filter-strip flex flex-wrap items-center gap-2">
            <Select v-model="statusFilter">
              <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/80">
                <SelectValue placeholder="全部状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </SelectItem>
              </SelectContent>
            </Select>

            <Select v-model="spaceFilter">
              <SelectTrigger class="h-9 w-[160px] rounded-lg bg-background/80">
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
              <SelectTrigger class="h-9 w-[180px] rounded-lg bg-background/80">
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
              <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/80">
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
      </DataTable>
    </div>
  </PageContainer>
</template>

<style scoped>
.executions-table :deep(.card) {
  border-radius: 0.5rem;
  border-color: hsl(214 32% 91% / 0.78);
  box-shadow: 0 1px 2px rgb(15 23 42 / 0.05);
}

.executions-table :deep(thead tr) {
  background: hsl(210 40% 98% / 0.72);
}

.executions-table :deep(th) {
  height: 3rem;
  color: hsl(215 16% 47%);
  font-size: 0.8125rem;
  font-weight: 600;
}

.executions-table :deep(td) {
  height: 3.625rem;
}
</style>
