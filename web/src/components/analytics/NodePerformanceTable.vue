<script setup lang="ts">
import type { Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject, ref } from 'vue'
import api from '~/api/client'
import { Badge } from '~/components/ui/badge'
import { Skeleton } from '~/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '~/components/ui/table'

interface NodePerformance {
  node_type: string
  execution_count: number
  avg_duration_seconds: number | null
  success_rate: number
  total_tokens: number
}

const dateRange = inject<Ref<{ from: string, to: string }>>('analyticsDateRange')!

const queryParams = computed(() => ({
  date_from: dateRange.value.from,
  date_to: dateRange.value.to,
}))

const { data, isLoading } = useQuery({
  queryKey: ['analytics-node-performance', queryParams],
  queryFn: async () => {
    return await api.get<NodePerformance[]>('/analytics/node-performance/', queryParams.value)
  },
  placeholderData: keepPreviousData,
})

type SortField = 'execution_count' | 'avg_duration_seconds' | 'success_rate' | 'total_tokens'

const sortField = ref<SortField>('execution_count')
const sortAsc = ref(false)

function toggleSort(field: SortField) {
  if (sortField.value === field) {
    sortAsc.value = !sortAsc.value
  }
  else {
    sortField.value = field
    sortAsc.value = false
  }
}

const sortedData = computed(() => {
  const items = [...(data.value || [])]
  items.sort((a, b) => {
    const aVal = a[sortField.value] ?? 0
    const bVal = b[sortField.value] ?? 0
    return sortAsc.value ? (aVal as number) - (bVal as number) : (bVal as number) - (aVal as number)
  })
  return items
})

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined)
    return '—'
  if (seconds < 60)
    return `${seconds.toFixed(1)}s`
  return `${(seconds / 60).toFixed(1)}min`
}

function formatTokens(tokens: number): string {
  if (tokens >= 1_000_000)
    return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000)
    return `${(tokens / 1_000).toFixed(1)}K`
  return String(tokens)
}

function successRateVariant(rate: number): 'default' | 'secondary' | 'destructive' {
  if (rate >= 90)
    return 'default'
  if (rate >= 70)
    return 'secondary'
  return 'destructive'
}

function getSortIcon(field: SortField): string {
  if (sortField.value !== field)
    return 'icon-[lucide--arrow-up-down]'
  return sortAsc.value ? 'icon-[lucide--arrow-up]' : 'icon-[lucide--arrow-down]'
}
</script>

<template>
  <div class="card p-6 transition-all duration-200 hover:shadow-lg hover:border-primary/30">
    <h3 class="text-sm font-medium text-muted-foreground mb-4">
      节点类型性能排行
    </h3>

    <Skeleton v-if="isLoading" class="h-[300px] w-full" />
    <div v-else-if="!sortedData.length" class="h-[300px] flex items-center justify-center text-muted-foreground">
      暂无节点执行数据
    </div>

    <div v-else class="max-h-[300px] overflow-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead class="w-[200px]">
              节点类型
            </TableHead>
            <TableHead class="cursor-pointer select-none" @click="toggleSort('execution_count')">
              执行次数 <span class="text-xs ml-1" :class="[getSortIcon('execution_count')]" />
            </TableHead>
            <TableHead class="cursor-pointer select-none" @click="toggleSort('avg_duration_seconds')">
              平均时长 <span class="text-xs ml-1" :class="[getSortIcon('avg_duration_seconds')]" />
            </TableHead>
            <TableHead class="cursor-pointer select-none" @click="toggleSort('success_rate')">
              成功率 <span class="text-xs ml-1" :class="[getSortIcon('success_rate')]" />
            </TableHead>
            <TableHead class="cursor-pointer select-none" @click="toggleSort('total_tokens')">
              Token 消耗 <span class="text-xs ml-1" :class="[getSortIcon('total_tokens')]" />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="node in sortedData" :key="node.node_type">
            <TableCell class="font-mono text-sm">
              {{ node.node_type }}
            </TableCell>
            <TableCell>{{ node.execution_count }}</TableCell>
            <TableCell>{{ formatDuration(node.avg_duration_seconds) }}</TableCell>
            <TableCell>
              <Badge :variant="successRateVariant(node.success_rate)">
                {{ node.success_rate.toFixed(1) }}%
              </Badge>
            </TableCell>
            <TableCell>{{ formatTokens(node.total_tokens) }}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>
