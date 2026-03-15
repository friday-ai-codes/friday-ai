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
import { ref } from 'vue'
import EmptyState from '~/components/common/EmptyState.vue'
import Button from '~/components/ui/button/Button.vue'
import {
 DropdownMenu,
 DropdownMenuCheckboxItem,
 DropdownMenuContent,
 DropdownMenuLabel,
 DropdownMenuSeparator,
 DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
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
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-2xl overflow-hidden">
 <!-- 工具栏：搜索框 + #filters slot + 列可见性按钮 -->
 <div class="flex items-center justify-between gap-3 ">
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
 <DropdownMenu>
 <DropdownMenuTrigger as-child>
 <Button variant="outline" size="sm" class="gap-1.5">
 <span class="icon-[lucide--columns]" />
 列
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent align="end">
 <DropdownMenuLabel>显示/隐藏列</DropdownMenuLabel>
 <DropdownMenuSeparator />
 <DropdownMenuCheckboxItem
 v-for="column in table.getAllLeafColumns.filter(c => c.getCanHide)":key="column.id":checked="column.getIsVisible"
 @update:checked="column.toggleVisibility($event)"
 >
 {{ getColumnLabel(column) }}
 </DropdownMenuCheckboxItem>
 </DropdownMenuContent>
 </DropdownMenu>
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
 <div class="flex items-center justify-between px-4 py-3 border-t border-border/50">
 <span class="text-sm text-muted-foreground">
 第 {{ table.getState.pagination.pageIndex + 1 }} 页 /
 共 {{ table.getFilteredRowModel.rows.length }} 条
 </span>
 <div class="flex items-center gap-2">
 <Button
 variant="outline"
 size="sm":disabled="!table.getCanPreviousPage"
 @click="table.previousPage"
 >
 <span class="icon-[lucide--chevron-left]" />
 上一页
 </Button>
 <Button
 variant="outline"
 size="sm":disabled="!table.getCanNextPage"
 @click="table.nextPage"
 >
 下一页
 <span class="icon-[lucide--chevron-right]" />
 </Button>
 </div>
 </div>
 </div>
</template>
