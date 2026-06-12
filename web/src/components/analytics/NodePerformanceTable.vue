<script setup lang="ts">
import type { Ref } from 'vue'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, inject, ref } from 'vue'
import api from '~/api/client'
import ChartCard from '~/components/analytics/ChartCard.vue'
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

function successRatePillClass(rate: number): string {
  if (rate >= 90)
    return 'bg-emerald-500/10 text-emerald-700 ring-emerald-500/20'
  if (rate >= 70)
    return 'bg-amber-500/10 text-amber-700 ring-amber-500/20'
  return 'bg-red-500/10 text-red-700 ring-red-500/20'
}

function getSortIcon(field: SortField): string {
  if (sortField.value !== field)
    return 'icon-[lucide--arrow-up-down]'
  return sortAsc.value ? 'icon-[lucide--arrow-up]' : 'icon-[lucide--arrow-down]'
}
</script>

<template>
  <ChartCard
    title="节点类型性能排行"
    description="各节点类型的执行表现与消耗"
    icon="lucide--list-ordered"
    icon-class="bg-sky-500/10 text-sky-600"
  >
    <Skeleton v-if="isLoading" class="h-[300px] w-full rounded-lg" />
    <div v-else-if="!sortedData.length" class="h-[300px] flex flex-col items-center justify-center gap-2 text-muted-foreground">
      <span class="icon-[lucide--list-ordered] text-3xl opacity-30" />
      <span class="text-sm">暂无节点执行数据</span>
    </div>

    <div v-else class="max-h-[300px] overflow-auto rounded-lg border border-border/40">
      <Table>
        <TableHeader>
          <TableRow class="bg-muted/30 hover:bg-muted/30">
            <TableHead class="w-[200px] h-10 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              节点类型
            </TableHead>
            <TableHead class="h-10 cursor-pointer select-none text-xs font-semibold uppercase tracking-wide text-muted-foreground" @click="toggleSort('execution_count')">
              执行次数 <span class="text-xs ml-1" :class="[getSortIcon('execution_count')]" />
            </TableHead>
            <TableHead class="h-10 cursor-pointer select-none text-xs font-semibold uppercase tracking-wide text-muted-foreground" @click="toggleSort('avg_duration_seconds')">
              平均时长 <span class="text-xs ml-1" :class="[getSortIcon('avg_duration_seconds')]" />
            </TableHead>
            <TableHead class="h-10 cursor-pointer select-none text-xs font-semibold uppercase tracking-wide text-muted-foreground" @click="toggleSort('success_rate')">
              成功率 <span class="text-xs ml-1" :class="[getSortIcon('success_rate')]" />
            </TableHead>
            <TableHead class="h-10 cursor-pointer select-none text-xs font-semibold uppercase tracking-wide text-muted-foreground" @click="toggleSort('total_tokens')">
              Token 消耗 <span class="text-xs ml-1" :class="[getSortIcon('total_tokens')]" />
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="node in sortedData" :key="node.node_type" class="hover:bg-muted/20">
            <TableCell>
              <code class="rounded-md bg-muted/60 px-1.5 py-0.5 font-mono text-xs text-foreground/80">{{ node.node_type }}</code>
            </TableCell>
            <TableCell class="tabular-nums text-sm">
              {{ node.execution_count }}
            </TableCell>
            <TableCell class="tabular-nums text-sm text-muted-foreground">
              {{ formatDuration(node.avg_duration_seconds) }}
            </TableCell>
            <TableCell>
              <span
                class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ring-1"
                :class="successRatePillClass(node.success_rate)"
              >
                {{ node.success_rate.toFixed(1) }}%
              </span>
            </TableCell>
            <TableCell class="tabular-nums text-sm text-muted-foreground">
              {{ formatTokens(node.total_tokens) }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </ChartCard>
</template>
