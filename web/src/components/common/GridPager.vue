<script setup lang="ts">
/**
 * 卡片网格分页器 —— 与 DataTable 底部分页同款视觉，供卡片列表页（仓库/空间等）复用。
 *
 * 受控：v-model:pagination（{ pageIndex, pageSize }）+ total（过滤后总数）。
 * 自身不持有数据，仅渲染「显示 X 至 Y 共 N 条 + 每页 + 页码」并回写 pagination。
 */
import type { PaginationState } from '@tanstack/vue-table'
import { computed } from 'vue'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const props = withDefaults(defineProps<{
  total: number
  pageSizeOptions?: number[]
}>(), {
  pageSizeOptions: () => [9, 12, 24, 48],
})

const pagination = defineModel<PaginationState>('pagination', { required: true })

const currentPage = computed(() => pagination.value.pageIndex + 1)
const pageCount = computed(() => Math.max(1, Math.ceil(props.total / pagination.value.pageSize)))
const rangeStart = computed(() => (props.total === 0 ? 0 : pagination.value.pageIndex * pagination.value.pageSize + 1))
const rangeEnd = computed(() => Math.min(currentPage.value * pagination.value.pageSize, props.total))

/** 带省略号的页码数组，例如 [1, '...', 4, 5, 6, '...', 20]（与 DataTable 同源）。 */
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
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-3 pt-1">
    <!-- 左侧：显示范围 + 每页条数 -->
    <div class="flex items-center gap-4">
      <span class="text-sm text-muted-foreground tabular-nums">
        显示 {{ rangeStart }} 至 {{ rangeEnd }} 共 {{ total }} 条结果
      </span>
      <div class="flex items-center gap-2">
        <span class="text-sm text-muted-foreground">每页</span>
        <Select :model-value="String(pagination.pageSize)" @update:model-value="handlePageSizeChange">
          <SelectTrigger class="h-8 w-[70px] rounded-lg bg-background/90">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="size in pageSizeOptions" :key="size" :value="String(size)">
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
        :disabled="currentPage <= 1"
        @click="goToPage(currentPage - 1)"
      >
        <span class="icon-[lucide--chevron-left] w-4 h-4" />
      </Button>

      <template v-for="(page, i) in visiblePages" :key="`${page}-${i}`">
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
        :disabled="currentPage >= pageCount"
        @click="goToPage(currentPage + 1)"
      >
        <span class="icon-[lucide--chevron-right] w-4 h-4" />
      </Button>
    </div>
  </div>
</template>
