<script setup lang="ts" generic="T extends object">
import type { ColumnDef, PaginationState, RowSelectionState, SortingState, VisibilityState } from '@tanstack/vue-table'
import {

  FlexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,

  useVueTable,

} from '@tanstack/vue-table'
import { useLocalStorage } from '@vueuse/core'
import { computed, ref } from 'vue'
import EmptyState from '~/components/common/EmptyState.vue'
import Button from '~/components/ui/button/Button.vue'
import { Checkbox } from '~/components/ui/checkbox'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '~/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import {
  Skeleton,
} from '~/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '~/components/ui/table'

const props = defineProps<{
  data: T[]
  columns: ColumnDef<T>[]
  tableId: string
  pageSize?: number
  pageSizeOptions?: number[]
  loading?: boolean
  onRowClick?: (row: T) => void
  /**
   * 服务端分页模式：data 视为当前页（已分页好），DataTable 不再做客户端分页，
   * 也不渲染自带的"显示 X 至 Y 共 N 条"+"每页"选择器+页码按钮，由外层组件
   * 提供独立的分页控件，避免双套分页相互冲突。
   */
  serverSide?: boolean
  /** 开启行多选（渲染选择列），配合 v-model:row-selection 使用 */
  selectable?: boolean
  /** 行 ID 提取器；selectable 时建议传入业务 ID，使选择状态与数据解耦 */
  getRowId?: (row: T) => string
  /** 搜索框占位文案 */
  searchPlaceholder?: string
}>()

defineSlots<{
  filters: () => unknown
  selection: (props: { count: number, clear: () => void }) => unknown
}>()

// --- 受控状态 ---
const columnVisibility = useLocalStorage<VisibilityState>(
  `datatable-visibility-${props.tableId}`,
  {},
)
// 这些状态默认是组件内部 ref（defineModel 未绑定时退化为本地状态，向后兼容）；
// 调用方可通过 v-model:pagination / v-model:sorting / v-model:global-filter 受控，
// 用于把表格状态持久化到 URL（刷新可恢复）。
const sorting = defineModel<SortingState>('sorting', { default: () => [] })
const globalFilter = defineModel<string>('globalFilter', { default: '' })
// defineModel 默认值不能引用 props（会被提升到 setup 外），故静态默认 20；
// 下方对「未受控但传了 pageSize prop」的旧用法做一次初始化兼容。
const pagination = defineModel<PaginationState>('pagination', {
  default: () => ({ pageIndex: 0, pageSize: 20 }),
})
if (props.pageSize && props.pageSize !== 20 && pagination.value.pageSize === 20) {
  pagination.value = { ...pagination.value, pageSize: props.pageSize }
}
const rowSelection = defineModel<RowSelectionState>('rowSelection', { default: () => ({}) })

// --- useVueTable 初始化（getter 函数模式，保证响应性）---
const table = useVueTable({
  get data() { return props.data },
  get columns() { return props.columns },
  getCoreRowModel: getCoreRowModel(),
  getSortedRowModel: getSortedRowModel(),
  getFilteredRowModel: getFilteredRowModel(),
  // server-side 模式不挂客户端分页 row model：data 即为当前页全部行
  ...(props.serverSide ? {} : { getPaginationRowModel: getPaginationRowModel() }),
  enableRowSelection: props.selectable ?? false,
  ...(props.getRowId ? { getRowId: props.getRowId } : {}),
  state: {
    get sorting() { return sorting.value },
    get globalFilter() { return globalFilter.value },
    get columnVisibility() { return columnVisibility.value },
    get pagination() { return pagination.value },
    get rowSelection() { return rowSelection.value },
  },
  onSortingChange: (u) => {
    sorting.value = typeof u === 'function' ? u(sorting.value) : u
  },
  onGlobalFilterChange: (u) => {
    globalFilter.value = typeof u === 'function' ? u(globalFilter.value) : u
    // 搜索词变化时回到第一页，避免过滤后分页越界出现空白页
    pagination.value = { ...pagination.value, pageIndex: 0 }
  },
  onColumnVisibilityChange: (u) => {
    columnVisibility.value = typeof u === 'function' ? u(columnVisibility.value) : u
  },
  onPaginationChange: (u) => {
    pagination.value = typeof u === 'function' ? u(pagination.value) : u
  },
  onRowSelectionChange: (u) => {
    rowSelection.value = typeof u === 'function' ? u(rowSelection.value) : u
  },
})

// --- 选择状态 ---
const selectedCount = computed(() => Object.keys(rowSelection.value).filter(k => rowSelection.value[k]).length)
function clearSelection() {
  rowSelection.value = {}
}
const headerCheckboxState = computed<boolean | 'indeterminate'>(() => {
  if (table.getIsAllPageRowsSelected())
    return true
  if (table.getIsSomePageRowsSelected())
    return 'indeterminate'
  return false
})

// 每页条数选择（字符串适配 Select 组件）；从 pagination 派生，保证受控时同步
const pageSizeStr = computed(() => String(pagination.value.pageSize))
const effectivePageSizeOptions = computed(() => props.pageSizeOptions ?? [10, 20, 50, 100])

// 分页信息
const totalRows = computed(() => table.getFilteredRowModel().rows.length)
const pageCount = computed(() => table.getPageCount())
const currentPage = computed(() => table.getState().pagination.pageIndex + 1)
const rangeStart = computed(() => totalRows.value === 0 ? 0 : (currentPage.value - 1) * pagination.value.pageSize + 1)
const rangeEnd = computed(() => Math.min(currentPage.value * pagination.value.pageSize, totalRows.value))

/** 生成带省略号的页码数组，例如 [1, '...', 4, 5, 6, '...', 20] */
const visiblePages = computed<(number | '...')[]>(() => {
  const total = pageCount.value
  const current = currentPage.value
  if (total <= 7)
    return Array.from({ length: total }, (_, i) => i + 1)

  const pages: (number | '...')[] = [1]
  if (current > 3)
    pages.push('...')

  const start = Math.max(2, current - 1)
  const end = Math.min(total - 1, current + 1)
  for (let i = start; i <= end; i++) pages.push(i)

  if (current < total - 2)
    pages.push('...')
  pages.push(total)
  return pages
})

function goToPage(page: number) {
  pagination.value = { ...pagination.value, pageIndex: page - 1 }
}

function handlePageSizeChange(val: unknown) {
  pagination.value = { pageIndex: 0, pageSize: Number(val) }
}

/**
 * 从 ColumnDef 中提取人类可读的列名，用于列可见性 Dropdown。
 * header 为字符串时直接使用，否则 fallback 到 column.id。
 */
function getColumnLabel(column: ReturnType<typeof table.getAllLeafColumns>[number]): string {
  const header = column.columnDef.header
  if (typeof header === 'string')
    return header
  return column.id
}

const colSpanCount = computed(() => table.getAllColumns().length + (props.selectable ? 1 : 0))
</script>

<template>
  <div class="card overflow-hidden rounded-xl border-border/70 shadow-[0_1px_3px_rgba(15,23,42,0.06)]">
    <!-- 工具栏：搜索框 + #filters slot + 列可见性按钮 -->
    <div class="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-border/40 bg-muted/20">
      <div class="flex flex-wrap items-center gap-2.5 flex-1 min-w-0">
        <!-- 全局搜索框 -->
        <div class="relative">
          <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 text-sm pointer-events-none" />
          <input
            v-model="globalFilter"
            :placeholder="props.searchPlaceholder ?? '搜索...'"
            class="flex h-9 w-56 rounded-lg border border-border/60 bg-background/90 pl-9 pr-3 py-1 text-sm placeholder:text-muted-foreground/70 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:border-ring/50"
          >
        </div>
        <!-- 调用方额外筛选控件 slot -->
        <slot name="filters" />
      </div>

      <!-- 列可见性控件 -->
      <Popover>
        <PopoverTrigger as-child>
          <Button variant="outline" size="sm" class="h-9 gap-1.5 rounded-lg bg-background/90">
            <span class="icon-[lucide--sliders-horizontal] text-sm" />
            列
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" class="w-48 p-2">
          <p class="px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            显示/隐藏列
          </p>
          <div class="border-t border-border/50 my-1" />
          <label
            v-for="column in table.getAllLeafColumns().filter(c => c.getCanHide())"
            :key="column.id"
            class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-accent"
          >
            <input
              type="checkbox"
              :checked="column.getIsVisible()"
              class="accent-primary h-4 w-4 rounded"
              @change="column.toggleVisibility(($event.target as HTMLInputElement).checked)"
            >
            {{ getColumnLabel(column) }}
          </label>
        </PopoverContent>
      </Popover>
    </div>

    <!-- 批量选择操作条 -->
    <Transition
      enter-active-class="transition-all duration-200 ease-out"
      enter-from-class="opacity-0 -translate-y-1"
      leave-active-class="transition-all duration-150 ease-in"
      leave-to-class="opacity-0 -translate-y-1"
    >
      <div
        v-if="props.selectable && selectedCount > 0"
        class="flex items-center gap-3 px-4 py-2.5 border-b border-primary/20 bg-primary/6"
      >
        <span class="inline-flex items-center gap-1.5 text-sm font-medium text-primary">
          <span class="icon-[lucide--check-square] text-sm" />
          已选择 {{ selectedCount }} 项
        </span>
        <Button
          variant="ghost"
          size="sm"
          class="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
          @click="clearSelection"
        >
          取消选择
        </Button>
        <div class="flex-1" />
        <slot name="selection" :count="selectedCount" :clear="clearSelection" />
      </div>
    </Transition>

    <!-- 表格区域 -->
    <Table>
      <TableHeader>
        <TableRow
          v-for="headerGroup in table.getHeaderGroups()"
          :key="headerGroup.id"
          class="bg-muted/30 hover:bg-muted/30"
        >
          <TableHead v-if="props.selectable" class="w-10 pl-4 pr-0">
            <Checkbox
              :model-value="headerCheckboxState"
              aria-label="全选当前页"
              @update:model-value="(v) => table.toggleAllPageRowsSelected(v === true)"
            />
          </TableHead>
          <TableHead
            v-for="header in headerGroup.headers"
            :key="header.id"
            class="h-11 text-xs font-semibold uppercase tracking-wide text-muted-foreground"
            :class="header.column.getCanSort() ? 'cursor-pointer select-none' : ''"
            @click="header.column.getCanSort() ? header.column.toggleSorting() : undefined"
          >
            <div v-if="!header.isPlaceholder" class="flex items-center gap-1">
              <FlexRender
                :render="header.column.columnDef.header"
                :props="header.getContext()"
              />
              <span
                v-if="header.column.getCanSort()"
                class="text-muted-foreground/60"
                :class="{ 'icon-[lucide--chevron-up]': header.column.getIsSorted() === 'asc', 'icon-[lucide--chevron-down]': header.column.getIsSorted() === 'desc', 'icon-[lucide--chevrons-up-down]': !header.column.getIsSorted() }"
              />
            </div>
          </TableHead>
        </TableRow>
      </TableHeader>

      <TableBody>
        <!-- Loading skeleton -->
        <template v-if="props.loading">
          <TableRow v-for="i in 8" :key="i">
            <TableCell v-if="props.selectable" class="w-10 pl-4 pr-0">
              <Skeleton class="h-4 w-4 rounded-sm" />
            </TableCell>
            <TableCell
              v-for="col in table.getAllColumns()"
              :key="col.id"
            >
              <Skeleton class="h-4 w-full" />
            </TableCell>
          </TableRow>
        </template>

        <!-- 数据行 -->
        <template v-else-if="table.getRowModel().rows.length">
          <TableRow
            v-for="row in table.getRowModel().rows"
            :key="row.id"
            class="group/row transition-colors"
            :class="[
              props.onRowClick ? 'cursor-pointer hover:bg-muted/40' : 'hover:bg-muted/20',
              row.getIsSelected() ? 'bg-primary/4 hover:bg-primary/7' : '',
            ]"
            @click="props.onRowClick?.(row.original)"
          >
            <TableCell v-if="props.selectable" class="w-10 pl-4 pr-0" @click.stop>
              <Checkbox
                :model-value="row.getIsSelected()"
                :disabled="!row.getCanSelect()"
                aria-label="选择行"
                @update:model-value="(v) => row.toggleSelected(v === true)"
              />
            </TableCell>
            <TableCell v-for="cell in row.getVisibleCells()" :key="cell.id">
              <FlexRender
                :render="cell.column.columnDef.cell"
                :props="cell.getContext()"
              />
            </TableCell>
          </TableRow>
        </template>

        <!-- 空状态 -->
        <template v-else>
          <TableRow>
            <TableCell :colspan="colSpanCount" class="py-12">
              <EmptyState />
            </TableCell>
          </TableRow>
        </template>
      </TableBody>
    </Table>

    <!-- 分页区域：server-side 模式由外层接管，DataTable 自身不渲染 -->
    <div v-if="!props.serverSide" class="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-t border-border/40 bg-muted/20">
      <!-- 左侧：显示范围 + 每页条数 -->
      <div class="flex items-center gap-4">
        <span class="text-sm text-muted-foreground tabular-nums">
          显示 {{ rangeStart }} 至 {{ rangeEnd }} 共 {{ totalRows }} 条结果
        </span>
        <div class="flex items-center gap-2">
          <span class="text-sm text-muted-foreground">每页</span>
          <Select :model-value="pageSizeStr" @update:model-value="handlePageSizeChange">
            <SelectTrigger class="h-8 w-[70px] rounded-lg bg-background/90">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="size in effectivePageSizeOptions" :key="size" :value="String(size)">
                {{ size }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <!-- 右侧：页码按钮 -->
      <div v-if="pageCount > 1" class="flex items-center gap-1">
        <Button
          variant="outline"
          size="icon"
          class="h-8 w-8 rounded-lg"
          :disabled="!table.getCanPreviousPage()"
          @click="table.previousPage()"
        >
          <span class="icon-[lucide--chevron-left] w-4 h-4" />
        </Button>

        <template v-for="page in visiblePages" :key="page">
          <span v-if="page === '...'" class="px-1 text-sm text-muted-foreground">...</span>
          <Button
            v-else
            :variant="page === currentPage ? 'default' : 'outline'"
            size="icon"
            class="h-8 w-8 rounded-lg text-xs tabular-nums"
            @click="goToPage(page)"
          >
            {{ page }}
          </Button>
        </template>

        <Button
          variant="outline"
          size="icon"
          class="h-8 w-8 rounded-lg"
          :disabled="!table.getCanNextPage()"
          @click="table.nextPage()"
        >
          <span class="icon-[lucide--chevron-right] w-4 h-4" />
        </Button>
      </div>
    </div>
  </div>
</template>
