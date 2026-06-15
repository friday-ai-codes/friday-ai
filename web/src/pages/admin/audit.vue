<script setup lang="ts">
/**
 * 操作审计查询页面（v0.10 Phase 3 UI-01..04）。
 *
 * - DataTable 列出审计事件（actor / action / target / source / time）。
 * - 过滤器：action / source / target_type / 日期范围。
 * - 行点击 → 详情对话框（before/after JSON diff）。
 * - 导出 CSV/JSON 按钮。
 *
 * 前端 requiresAdmin 守卫仅 UX 兜底；真正授权在后端 IsSuperUser。
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { AuditEvent, AuditEventFilters } from '~/api/audit'
import { h, onMounted, ref, watch } from 'vue'
import { exportAuditEvents, listAuditEvents } from '~/api/audit'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'

definePage({
  meta: { requiresAdmin: true },
})

const { handleError } = useErrorHandler()

// ============================================================================
// State
// ============================================================================

const events = ref<AuditEvent[]>([])
const loading = ref(true)
const totalCount = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

// 过滤器
const filters = ref<AuditEventFilters>({})

// 详情对话框
const detailOpen = ref(false)
const selectedEvent = ref<AuditEvent | null>(null)

// ============================================================================
// 预设选项
// ============================================================================

const ACTION_PRESETS = [
  'credential.create',
  'credential.update',
  'credential.delete',
  'rule.create',
  'rule.update',
  'rule.delete',
  'cleanup.run',
  'member.invite',
  'member.update',
  'member.delete',
  'setting.update',
  'system.init',
]

const SOURCE_OPTIONS = [
  { value: '__all__', label: '全部来源' },
  { value: 'web', label: 'Web' },
  { value: 'api', label: 'API' },
  { value: 'system', label: 'System' },
]

// ============================================================================
// 数据加载
// ============================================================================

async function loadEvents() {
  loading.value = true
  try {
    const params: AuditEventFilters = {
      ...filters.value,
      page: currentPage.value,
      page_size: pageSize.value,
    }
    const resp = await listAuditEvents(params)
    events.value = resp.results
    totalCount.value = resp.count
  }
  catch (e: unknown) {
    handleError(e, '加载审计事件')
  }
  finally {
    loading.value = false
  }
}

// ============================================================================
// 过滤器交互
// ============================================================================

function applyFilter(key: keyof AuditEventFilters, value: string) {
  if (value) {
    filters.value = { ...filters.value, [key]: value }
  }
  else {
    const { [key]: _, ...rest } = filters.value
    filters.value = rest
  }
  currentPage.value = 1
}

const ACTION_SELECT_ALL = '__all__'

function applyFilterFromSelect(key: keyof AuditEventFilters, value: unknown) {
  const str = String(value)
  if (str === ACTION_SELECT_ALL) {
    const { [key]: _, ...rest } = filters.value
    filters.value = rest
  }
  else {
    applyFilter(key, str)
  }
}

function resetFilters() {
  filters.value = {}
  currentPage.value = 1
}

// 防抖监听过滤器变化
let filterTimer: ReturnType<typeof setTimeout> | null = null
watch(filters, () => {
  if (filterTimer) clearTimeout(filterTimer)
  filterTimer = setTimeout(() => loadEvents(), 300)
}, { deep: true })

// ============================================================================
// 分页
// ============================================================================

function goToPage(page: number) {
  currentPage.value = page
  loadEvents()
}

const totalPages = computed(() => Math.max(1, Math.ceil(totalCount.value / pageSize.value)))

// ============================================================================
// 详情对话框
// ============================================================================

function openDetail(event: AuditEvent) {
  selectedEvent.value = event
  detailOpen.value = true
}

function formatJson(obj: unknown): string {
  if (obj === null || obj === undefined) return 'null'
  try {
    return JSON.stringify(obj, null, 2)
  }
  catch {
    return String(obj)
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

// ============================================================================
// 导出
// ============================================================================

function handleExport(format: 'csv' | 'json') {
  exportAuditEvents(format, filters.value)
}

// ============================================================================
// 表格列定义
// ============================================================================

const columns: ColumnDef<AuditEvent>[] = [
  {
    accessorKey: 'created_at',
    header: '时间',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground whitespace-nowrap' }, formatDate(row.original.created_at)),
    enableSorting: true,
  },
  {
    accessorKey: 'actor',
    header: '操作人',
    cell: ({ row }) => h('span', { class: 'text-sm font-medium text-foreground' }, row.original.actor),
    enableSorting: true,
  },
  {
    accessorKey: 'action',
    header: '操作类型',
    cell: ({ row }) => h(Badge, { variant: 'secondary', class: 'text-xs font-mono' }, () => row.original.action),
    enableSorting: true,
  },
  {
    accessorKey: 'target_type',
    header: '目标类型',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, row.original.target_type || '—'),
    enableSorting: false,
  },
  {
    accessorKey: 'target_id',
    header: '目标 ID',
    cell: ({ row }) => {
      const id = row.original.target_id
      if (!id) return h('span', { class: 'text-sm text-muted-foreground' }, '—')
      const short = id.length > 12 ? `${id.slice(0, 8)}...` : id
      return h('span', { class: 'text-sm font-mono text-muted-foreground', title: id }, short)
    },
    enableSorting: false,
  },
  {
    accessorKey: 'source',
    header: '来源',
    cell: ({ row }) => {
      const variant = row.original.source === 'system' ? 'outline' : 'secondary'
      return h(Badge, { variant, class: 'text-xs' }, () => row.original.source)
    },
    enableSorting: false,
  },
  {
    id: 'detail',
    header: '详情',
    cell: ({ row }) => {
      const hasDiff = row.original.before_value !== null || row.original.after_value !== null
      return h(Button, {
        variant: 'ghost',
        size: 'sm',
        class: 'h-7 px-2 text-xs',
        onClick: (e: Event) => {
          e.stopPropagation()
          openDetail(row.original)
        },
      }, () => hasDiff ? '查看变更' : '查看')
    },
    enableSorting: false,
    enableHiding: false,
  },
]

// ============================================================================
// 生命周期
// ============================================================================

onMounted(() => {
  loadEvents()
})
</script>

<template>
  <PageContainer show-background>
    <PageHeader
      icon="lucide--shield-check"
      icon-gradient="from-emerald-500/20 to-primary/10"
      icon-color="text-emerald-600"
      title="操作审计"
      description="查看系统敏感操作的审计记录，支持过滤和导出"
    >
      <template #actions>
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <Button variant="outline" size="sm" class="gap-1.5">
              <span class="icon-[lucide--download] w-4 h-4" />
              导出
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem @click="handleExport('csv')">
              <span class="icon-[lucide--file-text] w-4 h-4 mr-2" />
              导出 CSV
            </DropdownMenuItem>
            <DropdownMenuItem @click="handleExport('json')">
              <span class="icon-[lucide--file-json] w-4 h-4 mr-2" />
              导出 JSON
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </template>
    </PageHeader>

    <DataTable
      :data="events"
      :columns="columns"
      table-id="admin-audit-list"
      :loading="loading"
      :on-row-click="openDetail"
      server-side
      search-placeholder="搜索审计事件..."
    >
      <template #filters>
        <!-- action 过滤 -->
        <Select
          :model-value="filters.action ?? ACTION_SELECT_ALL"
          @update:model-value="(v: unknown) => applyFilterFromSelect('action', v)"
        >
          <SelectTrigger class="h-9 w-[160px] rounded-lg bg-background/90">
            <SelectValue placeholder="操作类型" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem :value="ACTION_SELECT_ALL">
              全部操作
            </SelectItem>
            <SelectItem v-for="a in ACTION_PRESETS" :key="a" :value="a">
              {{ a }}
            </SelectItem>
          </SelectContent>
        </Select>

        <!-- source 过滤 -->
        <Select
          :model-value="filters.source ?? ACTION_SELECT_ALL"
          @update:model-value="(v: unknown) => applyFilterFromSelect('source', v)"
        >
          <SelectTrigger class="h-9 w-[120px] rounded-lg bg-background/90">
            <SelectValue placeholder="来源" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="s in SOURCE_OPTIONS" :key="s.value" :value="s.value">
              {{ s.label }}
            </SelectItem>
          </SelectContent>
        </Select>

        <!-- target_type 输入 -->
        <Input
          :model-value="filters.target_type ?? ''"
          placeholder="目标类型"
          class="h-9 w-[140px] rounded-lg bg-background/90"
          @update:model-value="(v: string) => applyFilter('target_type', v)"
        />

        <!-- 日期范围 -->
        <div class="flex items-center gap-1.5">
          <Label class="text-xs text-muted-foreground whitespace-nowrap">从</Label>
          <Input
            type="date"
            :model-value="filters.start_date ?? ''"
            class="h-9 w-[140px] rounded-lg bg-background/90"
            @update:model-value="(v: string) => applyFilter('start_date', v)"
          />
          <Label class="text-xs text-muted-foreground whitespace-nowrap">至</Label>
          <Input
            type="date"
            :model-value="filters.end_date ?? ''"
            class="h-9 w-[140px] rounded-lg bg-background/90"
            @update:model-value="(v: string) => applyFilter('end_date', v)"
          />
        </div>

        <!-- 重置 -->
        <Button
          v-if="Object.keys(filters).length > 0"
          variant="ghost"
          size="sm"
          class="h-9 px-2 text-xs text-muted-foreground"
          @click="resetFilters"
        >
          <span class="icon-[lucide--x] w-3.5 h-3.5 mr-1" />
          重置
        </Button>
      </template>
    </DataTable>

    <!-- 自建分页控件（server-side 模式） -->
    <div
      v-if="totalCount > 0"
      class="flex items-center justify-between px-4 py-3 border border-border/40 rounded-xl bg-card/60"
    >
      <span class="text-sm text-muted-foreground tabular-nums">
        共 {{ totalCount }} 条记录
      </span>
      <div class="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          class="h-8 w-8 rounded-lg"
          :disabled="currentPage <= 1"
          @click="goToPage(currentPage - 1)"
        >
          <span class="icon-[lucide--chevron-left] w-4 h-4" />
        </Button>
        <span class="text-sm text-muted-foreground px-2 tabular-nums">
          {{ currentPage }} / {{ totalPages }}
        </span>
        <Button
          variant="outline"
          size="icon"
          class="h-8 w-8 rounded-lg"
          :disabled="currentPage >= totalPages"
          @click="goToPage(currentPage + 1)"
        >
          <span class="icon-[lucide--chevron-right] w-4 h-4" />
        </Button>
      </div>
    </div>

    <!-- 详情对话框 -->
    <Dialog v-model:open="detailOpen">
      <DialogScrollContent class="max-w-3xl">
        <DialogHeader>
          <DialogTitle>审计事件详情</DialogTitle>
          <DialogDescription>
            {{ selectedEvent?.actor }} · {{ selectedEvent?.action }} · {{ formatDate(selectedEvent?.created_at ?? '') }}
          </DialogDescription>
        </DialogHeader>

        <div v-if="selectedEvent" class="space-y-4">
          <!-- 基本信息 -->
          <div class="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span class="text-muted-foreground">操作人：</span>
              <span class="font-medium">{{ selectedEvent.actor }}</span>
            </div>
            <div>
              <span class="text-muted-foreground">IP：</span>
              <span class="font-mono text-xs">{{ selectedEvent.actor_ip || '—' }}</span>
            </div>
            <div>
              <span class="text-muted-foreground">操作类型：</span>
              <Badge variant="secondary" class="text-xs font-mono">
                {{ selectedEvent.action }}
              </Badge>
            </div>
            <div>
              <span class="text-muted-foreground">来源：</span>
              <Badge variant="outline" class="text-xs">
                {{ selectedEvent.source }}
              </Badge>
            </div>
            <div>
              <span class="text-muted-foreground">目标类型：</span>
              <span>{{ selectedEvent.target_type || '—' }}</span>
            </div>
            <div>
              <span class="text-muted-foreground">目标 ID：</span>
              <span class="font-mono text-xs break-all">{{ selectedEvent.target_id || '—' }}</span>
            </div>
          </div>

          <!-- Before / After diff -->
          <div v-if="selectedEvent.before_value !== null || selectedEvent.after_value !== null" class="grid grid-cols-2 gap-3">
            <div>
              <Label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5 block">
                变更前
              </Label>
              <pre class="text-xs bg-muted/50 rounded-lg p-3 overflow-auto max-h-64 border border-border/50"><code>{{ formatJson(selectedEvent.before_value) }}</code></pre>
            </div>
            <div>
              <Label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5 block">
                变更后
              </Label>
              <pre class="text-xs bg-muted/50 rounded-lg p-3 overflow-auto max-h-64 border border-border/50"><code>{{ formatJson(selectedEvent.after_value) }}</code></pre>
            </div>
          </div>

          <!-- Extra 上下文 -->
          <div v-if="selectedEvent.extra && Object.keys(selectedEvent.extra).length > 0">
            <Label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5 block">
              附加信息
            </Label>
            <pre class="text-xs bg-muted/50 rounded-lg p-3 overflow-auto max-h-48 border border-border/50"><code>{{ formatJson(selectedEvent.extra) }}</code></pre>
          </div>
        </div>
      </DialogScrollContent>
    </Dialog>
  </PageContainer>
</template>
