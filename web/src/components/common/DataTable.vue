<script setup lang="ts" generic="T extends object">
import {
 FlexRender,
 getCoreRowModel,
 getFilteredRowModel,
 getPaginationRowModel,
 getSortedRowModel,
 useVueTable,
 type ColumnDef,
 type PaginationState,
 type SortingState,
 type VisibilityState,
} from '@tanstack/vue-table'
import { useLocalStorage } from '@vueuse/core'
import { computed, ref } from 'vue'
import EmptyState from '~/components/common/EmptyState.vue'
import Button from '~/components/ui/button/Button.vue'
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
 data: T
 columns: ColumnDef<T>
 tableId: string
 pageSize?: number
 pageSizeOptions?: number
 loading?: boolean
 onRowClick?: (row: T) => void
}>
defineSlots<{
 filters: unknown
}>
// --- 受控状态 ---
const columnVisibility = useLocalStorage<VisibilityState>(
 `datatable-visibility-${props.tableId}`,
 {},
)
const sorting = ref<SortingState>
const globalFilter = ref('')
const pagination = ref<PaginationState>({
 pageIndex: 0,
 pageSize: props.pageSize ?? 20,
})
// --- useVueTable 初始化（getter 函数模式，保证响应性）---
const table = useVueTable({
 get data { return props.data },
 get columns { return props.columns },
 getCoreRowModel: getCoreRowModel,
 getSortedRowModel: getSortedRowModel,
 getFilteredRowModel: getFilteredRowModel,
 getPaginationRowModel: getPaginationRowModel,
 state: {
 get sorting { return sorting.value },
 get globalFilter { return globalFilter.value },
 get columnVisibility { return columnVisibility.value },
 get pagination { return pagination.value },
 },
 onSortingChange: (u) => {
 sorting.value = u instanceof Function ? u(sorting.value): u
 },
 onGlobalFilterChange: (u) => {
 globalFilter.value = u instanceof Function ? u(globalFilter.value): u
 // 搜索词变化时回到第一页，避免过滤后分页越界出现空白页
 pagination.value = { ...pagination.value, pageIndex: 0 }
 },
 onColumnVisibilityChange: (u) => {
 columnVisibility.value = u instanceof Function ? u(columnVisibility.value): u
 },
 onPaginationChange: (u) => {
 pagination.value = u instanceof Function ? u(pagination.value): u
 },
})
// 每页条数选择（字符串适配 Select 组件）
const pageSizeStr = ref(String(props.pageSize ?? 20))
const effectivePageSizeOptions = computed( => props.pageSizeOptions ?? [10, 20, 50, 100])
// 分页信息
const totalRows = computed( => table.getFilteredRowModel.rows.length)
const pageCount = computed( => table.getPageCount)
const currentPage = computed( => table.getState.pagination.pageIndex + 1)
const rangeStart = computed( => totalRows.value === 0 ? 0: (currentPage.value - 1) * pagination.value.pageSize + 1)
const rangeEnd = computed( => Math.min(currentPage.value * pagination.value.pageSize, totalRows.value))
/** 生成带省略号的页码数组，例如 [1, '...', 4, 5, 6, '...', 20] */
const visiblePages = computed<(number | '...')>( => {
 const total = pageCount.value
 const current = currentPage.value
 if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
 const pages: (number | '...') = [1]
 if (current > 3) pages.push('...')
 const start = Math.max(2, current - 1)
 const end = Math.min(total - 1, current + 1)
 for (let i = start; i <= end; i++) pages.push(i)
 if (current < total - 2) pages.push('...')
 pages.push(total)
 return pages
})
function goToPage(page: number) {
 pagination.value = { ...pagination.value, pageIndex: page - 1 }
}
function handlePageSizeChange(val: string) {
 pageSizeStr.value = val
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
</script>
<template>
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl overflow-hidden shadow-[var(--shadow-glass)]">
 <!-- 工具栏：搜索框 + #filters slot + 列可见性按钮 -->
 <div class="flex items-center justify-between gap-3 px-4 py-3 border-b border-border/30">
 <div class="flex items-center gap-3 flex-1">
 <!-- 全局搜索框 -->
 <input
 v-model="globalFilter"
 placeholder="搜索..."
 class="flex w-64 rounded-xl border border-border/50 bg-card/70 backdrop-blur-sm px-3 py-1 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
 >
 <!-- 调用方额外筛选控件 slot -->
 <slot name="filters" />
 </div>
 <!-- 列可见性控件 -->
 <Popover>
 <PopoverTrigger as-child>
 <Button variant="outline" size="sm" class="gap-1.5">
 <span class="icon-[lucide--columns]" />
 列
 </Button>
 </PopoverTrigger>
 <PopoverContent align="end" class="w-48 ">
 <p class="px-2 py-1.5 text-sm font-semibold text-muted-foreground">显示/隐藏列</p>
 <div class="border-t border-border/50 my-1" />
 <label
 v-for="column in table.getAllLeafColumns.filter(c => c.getCanHide)":key="column.id"
 class="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm cursor-pointer hover:bg-accent"
 >
 <input
 type="checkbox":checked="column.getIsVisible"
 class="accent-primary w-4 rounded"
 @change="column.toggleVisibility(($event.target as HTMLInputElement).checked)"
 >
 {{ getColumnLabel(column) }}
 </label>
 </PopoverContent>
 </Popover>
 </div>
 <!-- 表格区域 -->
 <Table>
 <TableHeader>
 <TableRow
 v-for="headerGroup in table.getHeaderGroups":key="headerGroup.id"
 >
 <TableHead
 v-for="header in headerGroup.headers":key="header.id":class="header.column.getCanSort ? 'cursor-pointer select-none': ''"
 @click="header.column.getCanSort ? header.column.toggleSorting: undefined"
 >
 <div v-if="!header.isPlaceholder" class="flex items-center gap-1">
 <FlexRender:render="header.column.columnDef.header":props="header.getContext"
 />
 <span
 v-if="header.column.getCanSort"
 class="text-muted-foreground/60":class="{
 'icon-[lucide--chevron-up]': header.column.getIsSorted === 'asc',
 'icon-[lucide--chevron-down]': header.column.getIsSorted === 'desc',
 'icon-[lucide--chevrons-up-down]': !header.column.getIsSorted,
 }"
 />
 </div>
 </TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <!-- Loading skeleton -->
 <template v-if="props.loading">
 <TableRow v-for="i in 8":key="i">
 <TableCell
 v-for="col in table.getAllColumns":key="col.id"
 >
 <Skeleton class=" w-full" />
 </TableCell>
 </TableRow>
 </template>
 <!-- 数据行 -->
 <template v-else-if="table.getRowModel.rows.length">
 <TableRow
 v-for="row in table.getRowModel.rows":key="row.id":class="props.onRowClick ? 'cursor-pointer hover:bg-muted/50': ''"
 @click="props.onRowClick?.(row.original)"
 >
 <TableCell v-for="cell in row.getVisibleCells":key="cell.id">
 <FlexRender:render="cell.column.columnDef.cell":props="cell.getContext"
 />
 </TableCell>
 </TableRow>
 </template>
 <!-- 空状态 -->
 <template v-else>
 <TableRow>
 <TableCell:colspan="table.getAllColumns.length" class="py-12">
 <EmptyState />
 </TableCell>
 </TableRow>
 </template>
 </TableBody>
 </Table>
 <!-- 分页区域 -->
 <div class="flex items-center justify-between px-4 py-3 border-t border-border/30">
 <!-- 左侧：显示范围 + 每页条数 -->
 <div class="flex items-center gap-4">
 <span class="text-sm text-muted-foreground">
 显示 {{ rangeStart }} 至 {{ rangeEnd }} 共 {{ totalRows }} 条结果
 </span>
 <div class="flex items-center gap-2">
 <span class="text-sm text-muted-foreground">每页:</span>
 <Select:model-value="pageSizeStr" @update:model-value="handlePageSizeChange">
 <SelectTrigger class=" w-[70px]">
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="size in effectivePageSizeOptions":key="size":value="String(size)">
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
 class=" w-8":disabled="!table.getCanPreviousPage"
 @click="table.previousPage"
 >
 <span class="icon-[lucide--chevron-left] w-4 " />
 </Button>
 <template v-for="page in visiblePages":key="page">
 <span v-if="page === '...'" class="px-1 text-sm text-muted-foreground">...</span>
 <Button
 v-else:variant="page === currentPage ? 'default': 'outline'"
 size="icon"
 class=" w-8 text-xs"
 @click="goToPage(page)"
 >
 {{ page }}
 </Button>
 </template>
 <Button
 variant="outline"
 size="icon"
 class=" w-8":disabled="!table.getCanNextPage"
 @click="table.nextPage"
 >
 <span class="icon-[lucide--chevron-right] w-4 " />
 </Button>
 </div>
 </div>
 </div>
</template>
