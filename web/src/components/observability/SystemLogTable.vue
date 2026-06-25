<script setup lang="ts">
/**
 * 系统日志列表（UI-04 §5.2）：倒序 + 多维筛选 + 分页 + message 展开 + 行点击下钻。
 *
 * 自取数：用 @tanstack/vue-query 调 querySystemLogs（keepPreviousData），内部维护筛选 +
 * 分页 state（变化即 refetch）。倒序由后端 order_by('-ts') 保证。返回的 `counters`
 * 经 emit('counters') 上抛，由页面顶部 QueueCountersBar 同源消费（与列表同一次请求刷新）。
 * 行点击 emit('rowClick', row) 供页面打开下钻抽屉。
 *
 * 筛选维度说明（全部服务端全量筛选）：
 * - 顶层列：component/level/user_id/source/keyword(message 全文) + start/end 时间段。
 * - 高级维度：call_source/provider/credential/model 经后端 payload jsonb 顶层键精确筛选；
 *   关联键 correlation 经后端 correlation jsonb 文本化子串检索（见 log_views._apply_filters）。
 *   均作为真实查询参数下发（服务端全量过滤，非当前页 narrowing），参数随分页一并 refetch。
 *
 * UI-SPEC §0：lucide 无 emoji、tabular-nums、亮暗 token、hover 过渡、focus 可见环、
 * 骨架 / 空态、移动端横向滚动不溢出。
 */
import type { SystemLogQuery, SystemLogRow } from '~/api/system'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { querySystemLogs } from '~/api/system'
import { eventMessageLabel } from '~/components/observability/eventLabels'
import { logLevelClass } from '~/components/observability/status'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Skeleton } from '~/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '~/components/ui/table'
import { EMPTY, formatDateTime } from './format'

const props = withDefaults(defineProps<{
  /** 时间段（ISO8601，来自父页 ObservabilityTimeRange，可空=不限时间）。 */
  timeRange?: { start: string, end: string } | null
}>(), {
  timeRange: null,
})

const emit = defineEmits<{
  /** 每次查询返回的队列四计数上抛（页面顶部 bar 消费）。 */
  counters: [counters: Record<string, number>]
  /** 行点击（下钻入口）。 */
  rowClick: [row: SystemLogRow]
  /** 当前筛选条件变化上抛（页面「按当前筛选清理」复用同款条件）。 */
  filtersChange: [filters: SystemLogQuery]
}>()

// ── 顶层筛选 + 分页 state ──────────────────────────────────────────────
const SENTINEL_ALL = 'all'
const level = ref<string>(SENTINEL_ALL)
const source = ref<string>(SENTINEL_ALL)
const component = ref('')
const userId = ref('')
const keywordInput = ref('')
const keyword = ref('') // debounce 后的实际查询值

const PAGE_SIZE = 100
const offset = ref(0)

// keyword 输入防抖（300ms），避免逐字触发查询。
let kwTimer: ReturnType<typeof setTimeout> | null = null
watch(keywordInput, (v) => {
  if (kwTimer)
    clearTimeout(kwTimer)
  kwTimer = setTimeout(() => {
    keyword.value = v.trim()
  }, 300)
})

// ── 高级（payload/correlation）服务端筛选 ──────────────────────────────
// advKey 取值与 SystemLogQuery 的高级维度键一一对应（call_source/provider/credential/
// model/correlation），直接映射为后端查询参数（服务端全量过滤）。
type AdvKey = 'call_source' | 'provider' | 'credential' | 'model' | 'correlation'
const advKey = ref<string>(SENTINEL_ALL)
const advValue = ref('')
const advValueInput = ref('')

// 高级维度值输入防抖（300ms），与 keyword 同款，避免逐字 refetch。
let advTimer: ReturnType<typeof setTimeout> | null = null
watch(advValueInput, (v) => {
  if (advTimer)
    clearTimeout(advTimer)
  advTimer = setTimeout(() => {
    advValue.value = v.trim()
  }, 300)
})
// 切换高级维度时清空已输入的值（避免跨维度残留）。
watch(advKey, () => {
  advValueInput.value = ''
  advValue.value = ''
})

// 任一筛选（含时间段 / 高级维度）变化 → 回第一页。
watch(
  [level, source, component, userId, keyword, advKey, advValue, () => props.timeRange],
  () => { offset.value = 0 },
)

const queryParams = computed<SystemLogQuery>(() => {
  const p: SystemLogQuery = { limit: PAGE_SIZE, offset: offset.value }
  if (level.value !== SENTINEL_ALL)
    p.level = level.value
  if (source.value !== SENTINEL_ALL)
    p.source = source.value
  if (component.value.trim())
    p.component = component.value.trim()
  if (userId.value.trim())
    p.user_id = userId.value.trim()
  if (keyword.value)
    p.keyword = keyword.value
  // 高级维度作为真实服务端查询参数下发（键名即 advKey）。
  if (advKey.value !== SENTINEL_ALL && advValue.value)
    p[advKey.value as AdvKey] = advValue.value
  if (props.timeRange?.start)
    p.start = props.timeRange.start
  if (props.timeRange?.end)
    p.end = props.timeRange.end
  return p
})

// 上抛当前筛选（去掉分页参数，供页面清理复用）。
watch(queryParams, (p) => {
  const { limit: _limit, offset: _offset, ...filters } = p
  emit('filtersChange', filters)
}, { immediate: true })

const { data, isLoading, isError } = useQuery({
  queryKey: ['obs-system-logs', queryParams] as const,
  queryFn: () => querySystemLogs(queryParams.value),
  placeholderData: keepPreviousData,
  retry: 1,
})

// counters 上抛（页面顶部 bar 同源刷新）。
watch(() => data.value?.counters, (c) => {
  if (c)
    emit('counters', c)
}, { immediate: true })

const rawItems = computed<SystemLogRow[]>(() => data.value?.items ?? [])
// 服务端已全量筛选，列表直接展示返回行（不再做当前页客户端 narrowing）。
const items = rawItems
const total = computed(() => data.value?.total ?? 0)

// 高级维度筛选已激活（用于显示「服务端筛选生效」提示）。
const advFilterActive = computed(() => advKey.value !== SENTINEL_ALL && !!advValue.value)

const rangeStart = computed(() => (total.value === 0 ? 0 : offset.value + 1))
const rangeEnd = computed(() => Math.min(offset.value + PAGE_SIZE, total.value))
const canPrev = computed(() => offset.value > 0)
const canNext = computed(() => offset.value + PAGE_SIZE < total.value)

function prevPage() {
  if (canPrev.value)
    offset.value = Math.max(0, offset.value - PAGE_SIZE)
}
function nextPage() {
  if (canNext.value)
    offset.value += PAGE_SIZE
}

// ── 选项 ────────────────────────────────────────────────────────────────
const levelOptions = [
  { value: SENTINEL_ALL, label: '全部级别' },
  { value: 'debug', label: 'DEBUG' },
  { value: 'info', label: 'INFO' },
  { value: 'warn', label: 'WARN' },
  { value: 'error', label: 'ERROR' },
]
const sourceOptions = [
  { value: SENTINEL_ALL, label: '全部来源' },
  { value: 'mcp', label: 'MCP' },
  { value: 'chat', label: '对话' },
  { value: 'compat', label: '兼容接口' },
  { value: 'rest', label: 'REST' },
  { value: 'webhook', label: 'Webhook' },
  { value: 'workflow', label: '工作流' },
  { value: 'task', label: '任务' },
  { value: 'scheduler', label: '调度器' },
]
const advKeyOptions = [
  { value: SENTINEL_ALL, label: '高级维度（服务端）' },
  { value: 'call_source', label: 'call_source' },
  { value: 'provider', label: 'provider' },
  { value: 'credential', label: 'credential' },
  { value: 'model', label: 'model' },
  { value: 'correlation', label: '关联键' },
]

// ── category 徽标 ────────────────────────────────────────────────────────
function categoryLabel(c: string): string {
  if (c === 'caller')
    return '调用'
  if (c === 'sampling')
    return '采样'
  return c || EMPTY
}
function categoryClass(c: string): string {
  if (c === 'caller')
    return 'text-teal-600 bg-teal-500/10 dark:text-teal-400'
  if (c === 'sampling')
    return 'text-muted-foreground bg-muted'
  return 'text-muted-foreground bg-muted'
}

// ── message 中文化 + 展开 ────────────────────────────────────────────────
// 「消息」列优先展示中文事件说明（见 eventLabels.ts），未收录时回退原始 message。
// 原始英文事件名仍保留在「事件」列，不影响筛选/检索。
function rowMessage(row: SystemLogRow): string {
  return eventMessageLabel(row.event ?? '', row.message ?? '')
}

const expanded = ref<Set<number>>(new Set())
function toggleExpand(id: number) {
  const next = new Set(expanded.value)
  if (next.has(id))
    next.delete(id)
  else next.add(id)
  expanded.value = next
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  }
  catch {
    return String(value)
  }
}
function hasDetail(row: SystemLogRow): boolean {
  return Object.keys(row.payload ?? {}).length > 0 || Object.keys(row.correlation ?? {}).length > 0
}

function onRowClick(row: SystemLogRow) {
  emit('rowClick', row)
}

defineExpose({ rawItems })
</script>

<template>
  <div class="space-y-3">
    <!-- 多维筛选条 -->
    <div class="flex flex-wrap items-center gap-2.5">
      <Select v-model="level">
        <SelectTrigger class="h-9 w-[120px] rounded-lg bg-background/90" aria-label="按级别筛选">
          <span class="icon-[lucide--signal] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in levelOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="source">
        <SelectTrigger class="h-9 w-[120px] rounded-lg bg-background/90" aria-label="按来源筛选">
          <span class="icon-[lucide--split] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Input
        v-model="component"
        placeholder="组件 component"
        class="h-9 w-[150px] rounded-lg bg-background/90"
        aria-label="按组件筛选"
      />
      <Input
        v-model="userId"
        placeholder="用户 user_id"
        class="h-9 w-[150px] rounded-lg bg-background/90"
        aria-label="按用户筛选"
      />
      <Input
        v-model="keywordInput"
        placeholder="关键词（message 全文）"
        class="h-9 w-[200px] rounded-lg bg-background/90"
        aria-label="按关键词全文搜索"
      />
    </div>

    <!-- 高级（payload/correlation）筛选：服务端全量过滤 -->
    <div class="flex flex-wrap items-center gap-2.5">
      <Select v-model="advKey">
        <SelectTrigger class="h-9 w-[170px] rounded-lg bg-background/90" aria-label="高级维度筛选（服务端）">
          <span class="icon-[lucide--filter] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in advKeyOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>
      <Input
        v-model="advValueInput"
        :disabled="advKey === SENTINEL_ALL"
        :placeholder="advKey === 'correlation' ? '关联键值（子串）' : '值（精确匹配）'"
        class="h-9 w-[200px] rounded-lg bg-background/90"
        aria-label="高级维度取值"
      />
      <p v-if="advFilterActive" class="text-[11px] text-muted-foreground">
        <span class="icon-[lucide--info] mr-1 align-middle" />
        高级维度服务端全量筛选{{ advKey === 'correlation' ? '（关联键子串匹配）' : '（精确匹配）' }}
      </p>
    </div>

    <!-- 日志表（横向滚动不溢出） -->
    <div class="overflow-x-auto rounded-lg border border-border/60">
      <Table class="min-w-[920px]">
        <TableHeader>
          <TableRow class="hover:bg-transparent">
            <TableHead class="w-[150px]">
              时间
            </TableHead>
            <TableHead class="w-[80px]">
              级别
            </TableHead>
            <TableHead class="w-[130px]">
              组件
            </TableHead>
            <TableHead class="w-[72px]">
              类别
            </TableHead>
            <TableHead class="w-[120px]">
              用户
            </TableHead>
            <TableHead class="w-[100px]">
              来源
            </TableHead>
            <TableHead class="w-[160px]">
              事件
            </TableHead>
            <TableHead>消息</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <!-- 骨架行 -->
          <template v-if="isLoading && !rawItems.length">
            <TableRow v-for="i in 8" :key="`sk-${i}`" class="hover:bg-transparent">
              <TableCell v-for="c in 8" :key="c">
                <Skeleton class="h-4 w-full" />
              </TableCell>
            </TableRow>
          </template>

          <!-- 错误态 -->
          <TableRow v-else-if="isError" class="hover:bg-transparent">
            <TableCell colspan="8" class="py-10 text-center text-sm text-destructive">
              <span class="icon-[lucide--circle-alert] mr-1.5 align-middle" />
              加载系统日志失败
            </TableCell>
          </TableRow>

          <!-- 空态 -->
          <TableRow v-else-if="!items.length" class="hover:bg-transparent">
            <TableCell colspan="8" class="py-12 text-center text-sm text-muted-foreground">
              <span class="icon-[lucide--scroll-text] mx-auto mb-2 block text-2xl opacity-60" />
              {{ advFilterActive ? '无匹配筛选条件的日志' : '暂无系统日志' }}
            </TableCell>
          </TableRow>

          <!-- 数据行 -->
          <template v-for="row in items" v-else :key="row.id">
            <TableRow
              class="cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:ring-inset"
              tabindex="0"
              @click="onRowClick(row)"
              @keydown.enter="onRowClick(row)"
            >
              <TableCell class="font-mono text-xs whitespace-nowrap tabular-nums text-muted-foreground">
                {{ formatDateTime(row.ts) }}
              </TableCell>
              <TableCell>
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold uppercase"
                  :class="logLevelClass(row.level)"
                >{{ row.level || EMPTY }}</span>
              </TableCell>
              <TableCell class="font-mono text-xs">
                {{ row.component || EMPTY }}
              </TableCell>
              <TableCell>
                <span
                  class="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium"
                  :class="categoryClass(row.category)"
                >{{ categoryLabel(row.category) }}</span>
              </TableCell>
              <TableCell class="font-mono text-xs">
                {{ row.user_id || EMPTY }}
              </TableCell>
              <TableCell class="font-mono text-xs text-muted-foreground">
                {{ row.source || EMPTY }}
              </TableCell>
              <TableCell class="font-mono text-xs">
                {{ row.event || EMPTY }}
              </TableCell>
              <TableCell class="max-w-[360px]">
                <div class="flex items-start gap-1.5">
                  <span class="min-w-0 flex-1 truncate" :title="row.message || row.event">{{ rowMessage(row) || EMPTY }}</span>
                  <Button
                    v-if="hasDetail(row) || (rowMessage(row).length > 40)"
                    variant="ghost"
                    size="icon-sm"
                    class="-my-1 shrink-0"
                    :aria-label="expanded.has(row.id) ? '收起详情' : '展开详情'"
                    @click.stop="toggleExpand(row.id)"
                  >
                    <span
                      class="text-sm"
                      :class="expanded.has(row.id) ? 'icon-[lucide--chevron-up]' : 'icon-[lucide--chevron-down]'"
                    />
                  </Button>
                </div>
              </TableCell>
            </TableRow>

            <!-- 展开行：完整 message + payload/correlation（pre 文本，禁 v-html） -->
            <TableRow v-if="expanded.has(row.id)" :key="`exp-${row.id}`" class="hover:bg-transparent">
              <TableCell colspan="8" class="bg-muted/30">
                <div class="space-y-3 py-1 text-xs">
                  <div>
                    <div class="mb-1 font-semibold text-muted-foreground">
                      完整消息
                    </div>
                    <pre class="overflow-auto rounded-md bg-background/60 p-2 font-mono break-all whitespace-pre-wrap">{{ rowMessage(row) || EMPTY }}</pre>
                    <div v-if="row.event" class="mt-1 text-[11px] text-muted-foreground">
                      原始事件：<span class="font-mono">{{ row.event }}</span>
                    </div>
                  </div>
                  <div v-if="Object.keys(row.payload ?? {}).length" class="grid gap-3 md:grid-cols-2">
                    <div>
                      <div class="mb-1 font-semibold text-muted-foreground">
                        payload
                      </div>
                      <pre class="max-h-64 overflow-auto rounded-md bg-background/60 p-2 font-mono">{{ prettyJson(row.payload) }}</pre>
                    </div>
                    <div v-if="Object.keys(row.correlation ?? {}).length">
                      <div class="mb-1 font-semibold text-muted-foreground">
                        correlation
                      </div>
                      <pre class="max-h-64 overflow-auto rounded-md bg-background/60 p-2 font-mono">{{ prettyJson(row.correlation) }}</pre>
                    </div>
                  </div>
                  <div v-else-if="Object.keys(row.correlation ?? {}).length">
                    <div class="mb-1 font-semibold text-muted-foreground">
                      correlation
                    </div>
                    <pre class="max-h-64 overflow-auto rounded-md bg-background/60 p-2 font-mono">{{ prettyJson(row.correlation) }}</pre>
                  </div>
                </div>
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>
    </div>

    <!-- 分页（倒序由后端保证） -->
    <div v-if="rawItems.length" class="flex items-center justify-between gap-3 text-xs text-muted-foreground">
      <span class="tabular-nums">
        第 {{ rangeStart }}–{{ rangeEnd }} 条 / 共 {{ total }} 条
      </span>
      <div class="flex items-center gap-1">
        <Button variant="outline" size="sm" :disabled="!canPrev" aria-label="上一页" @click="prevPage">
          <span class="icon-[lucide--chevron-left]" />
          上一页
        </Button>
        <Button variant="outline" size="sm" :disabled="!canNext" aria-label="下一页" @click="nextPage">
          下一页
          <span class="icon-[lucide--chevron-right]" />
        </Button>
      </div>
    </div>
  </div>
</template>
