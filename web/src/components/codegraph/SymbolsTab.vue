<script setup lang="ts">
import type { ColumnDef } from '@tanstack/vue-table'
import type { SymbolRow } from '~/api/codegraph'
import { useDebounceFn } from '@vueuse/core'
import { computed, h, onMounted, ref, watch } from 'vue'
import { getSymbols } from '~/api/codegraph'
import DataTable from '~/components/common/DataTable.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import SymbolTypeFilter from './SymbolTypeFilter.vue'
const props = defineProps<{
 repositoryId: string
}>
const emit = defineEmits<{
 'select-symbol': [id: string]
}>
// 服务端分页状态
const symbols = ref<SymbolRow>
const total = ref(0)
const offset = ref(0)
const limit = 50
const loading = ref(false)
const error = ref<string | null>(null)
// 过滤状态
const selectedTypes = ref<string>
const nameQuery = ref('')
const filePathQuery = ref('')
const BADGE_VARIANTS: Record<string, 'info' | 'success' | 'secondary' | 'muted'> = {
 FUNCTION: 'info',
 CLASS: 'success',
 METHOD: 'info',
 VARIABLE: 'muted',
}
const SYMBOL_TYPE_LABELS: Record<string, string> = {
 FUNCTION: '函数',
 CLASS: '类',
 METHOD: '方法',
 VARIABLE: '变量',
}
const columns: ColumnDef<SymbolRow> = [
 {
 id: 'name',
 header: '名称',
 accessorKey: 'name',
 enableSorting: true,
 cell: ({ row }) =>
 h(
 'button',
 {
 class: 'font-mono text-sm text-primary hover:underline text-left',
 onClick: (e: MouseEvent) => {
 e.stopPropagation
 emit('select-symbol', row.original.id)
 },
 },
 row.original.name,
 ),
 },
 {
 id: 'symbol_type',
 header: '类型',
 accessorKey: 'symbol_type',
 enableSorting: true,
 cell: ({ row }) =>
 h(
 Badge,
 { variant: BADGE_VARIANTS[row.original.symbol_type] ?? 'secondary' },
 => SYMBOL_TYPE_LABELS[row.original.symbol_type] ?? row.original.symbol_type,
 ),
 },
 {
 id: 'file_path',
 header: '文件路径',
 accessorKey: 'file_path',
 cell: ({ row }) =>
 h(TooltipProvider, { delayDuration: 300 }, =>
 h(Tooltip, null, {
 default: => [
 h(TooltipTrigger, { asChild: true }, =>
 h(
 'span',
 { class: 'font-mono text-xs truncate max-w-[200px] block', title: row.original.file_path },
 row.original.file_path,
 )),
 h(TooltipContent, null, => row.original.file_path),
 ],
 })),
 },
 {
 id: 'line_range',
 header: '行范围',
 accessorFn: (row: SymbolRow) => `L${row.line_start}–${row.line_end}`,
 cell: ({ row }) =>
 h(
 'span',
 { class: 'font-mono text-xs text-muted-foreground' },
 `L${row.original.line_start}–${row.original.line_end}`,
 ),
 },
]
async function fetchSymbols {
 loading.value = true
 error.value = null
 try {
 const res = await getSymbols({
 repositoryId: props.repositoryId,
 symbolTypes: selectedTypes.value.length > 0 ? selectedTypes.value: undefined,
 name: nameQuery.value || undefined,
 filePath: filePathQuery.value || undefined,
 limit,
 offset: offset.value,
 })
 symbols.value = res.results
 total.value = res.count
 }
 catch (e: unknown) {
 error.value = e instanceof Error ? e.message: '加载失败'
 }
 finally {
 loading.value = false
 }
}
const debouncedFetch = useDebounceFn(fetchSymbols, 300)
watch([selectedTypes, filePathQuery], => {
 offset.value = 0
 fetchSymbols
})
watch(nameQuery, => {
 offset.value = 0
 debouncedFetch
})
function handleRowClick(row: SymbolRow) {
 emit('select-symbol', row.id)
}
function prevPage {
 if (offset.value >= limit) {
 offset.value -= limit
 fetchSymbols
 }
}
function nextPage {
 if (offset.value + limit < total.value) {
 offset.value += limit
 fetchSymbols
 }
}
function clearFilters {
 selectedTypes.value =
 nameQuery.value = ''
 filePathQuery.value = ''
 offset.value = 0
 fetchSymbols
}
const hasFilters = computed( =>
 selectedTypes.value.length > 0 || !!nameQuery.value || !!filePathQuery.value,
)
const currentPage = computed( => Math.floor(offset.value / limit) + 1)
const totalPages = computed( => Math.ceil(total.value / limit))
onMounted(fetchSymbols)
</script>
<template>
 <div class="space-y-3">
 <!-- 过滤栏 -->
 <SymbolTypeFilter
 v-model="selectedTypes"
 v-model:name-query="nameQuery"
 v-model:file-path-query="filePathQuery"
 />
 <!-- 错误提示 -->
 <p v-if="error" class="text-xs text-destructive">
 加载失败：{{ error }}。请稍后重试。
 </p>
 <!-- DataTable -->
 <DataTable:data="symbols":columns="columns"
 table-id="symbols-tab":page-size="200":page-size-options="[50, 100, 200]":loading="loading":on-row-click="handleRowClick"
 />
 <!-- 空状态（无数据 + 无过滤条件） -->
 <div
 v-if="!loading && symbols.length === 0 && !hasFilters"
 class="flex flex-col items-center justify-center py-8 text-center"
 >
 <span class="icon-[lucide--database] text-3xl text-muted-foreground mb-3" />
 <p class="text-base font-semibold">
 仓库暂无 Symbol 数据
 </p>
 <p class="text-sm text-muted-foreground mt-1">
 请先完成代码索引，系统将自动提取 Symbol 结构。
 </p>
 <Button variant="outline" size="sm" class="mt-3 text-xs">
 前往索引设置
 </Button>
 </div>
 <!-- 空状态（有过滤条件但无结果） -->
 <div
 v-if="!loading && symbols.length === 0 && hasFilters"
 class="flex flex-col items-center justify-center py-6 text-center"
 >
 <span class="icon-[lucide--search-x] text-2xl text-muted-foreground mb-2" />
 <p class="text-sm font-semibold">
 未找到匹配结果
 </p>
 <p class="text-xs text-muted-foreground mt-1">
 尝试调整过滤条件或清除搜索内容。
 </p>
 <Button variant="ghost" size="sm" class="mt-2 text-xs" @click="clearFilters">
 清除过滤
 </Button>
 </div>
 <!-- 服务端分页控制 -->
 <div v-if="totalPages > 1" class="flex items-center justify-between px-1">
 <span class="text-xs text-muted-foreground">
 第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条
 </span>
 <div class="flex gap-2">
 <Button
 variant="outline"
 size="sm"
 class=" text-xs":disabled="currentPage <= 1"
 @click="prevPage"
 >
 上一页
 </Button>
 <Button
 variant="outline"
 size="sm"
 class=" text-xs":disabled="currentPage >= totalPages"
 @click="nextPage"
 >
 下一页
 </Button>
 </div>
 </div>
 </div>
</template>
