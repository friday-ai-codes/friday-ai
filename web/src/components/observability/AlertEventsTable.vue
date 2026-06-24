<script setup lang="ts">
/**
 * 告警事件表（UI-03 §4.1，列对齐 REFERENCE-UI §1.4）。
 *
 * 自取数：用 @tanstack/vue-query 调 listAlertEvents（keepPreviousData，倒序由后端保证）。
 * 多维筛选（级别 / 状态 / 规则 / 时间段）在组件内维护并映射 listAlertEvents 参数；
 * 筛选变化重置 offset；时间段由父页 timeRange 受控传入（可空）。行点击 emit rowClick
 * 供页面打开详情抽屉。规则筛选选项由父页 props.rules 传入（与规则面板共享 query 缓存，
 * 避免重复请求）。
 *
 * a11y / UI-SPEC §0：lucide 图标无 emoji、tabular-nums、亮暗 token、hover 过渡、
 * focus 可见环、骨架 / 空态、移动端横向滚动不溢出。
 */
import type { AlertEventQuery, AlertEventRow, AlertRule } from '~/api/system'
import { keepPreviousData, useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { listAlertEvents } from '~/api/system'
import { alertSeverityClass, alertStatusClass } from '~/components/observability/status'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
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
  /** 规则筛选选项（父页传入，避免重复请求 listAlertRules）。 */
  rules?: AlertRule[]
  /** 时间段（ISO8601，来自父页 ObservabilityTimeRange，可空=不限时间）。 */
  timeRange?: { start: string, end: string } | null
}>(), {
  rules: () => [],
  timeRange: null,
})

const emit = defineEmits<{
  rowClick: [event: AlertEventRow]
}>()

// ── 筛选 + 分页 state ──────────────────────────────────────────────────
const SENTINEL_ALL = 'all'
const severity = ref<string>(SENTINEL_ALL)
const status = ref<string>(SENTINEL_ALL)
const ruleId = ref<string>(SENTINEL_ALL)
const PAGE_SIZE = 20
const offset = ref(0)

// 任一筛选变化（含时间段）→ 回到第一页。
watch([severity, status, ruleId, () => props.timeRange], () => {
  offset.value = 0
})

const queryParams = computed<AlertEventQuery>(() => {
  const p: AlertEventQuery = { limit: PAGE_SIZE, offset: offset.value }
  if (severity.value !== SENTINEL_ALL)
    p.severity = severity.value
  if (status.value !== SENTINEL_ALL)
    p.status = status.value
  if (ruleId.value !== SENTINEL_ALL)
    p.rule_id = Number(ruleId.value)
  if (props.timeRange?.start)
    p.start = props.timeRange.start
  if (props.timeRange?.end)
    p.end = props.timeRange.end
  return p
})

const { data, isLoading, isError } = useQuery({
  queryKey: ['obs-alert-events', queryParams] as const,
  queryFn: () => listAlertEvents(queryParams.value),
  placeholderData: keepPreviousData,
  retry: 1,
})

const events = computed<AlertEventRow[]>(() => data.value?.items ?? [])
const total = computed(() => data.value?.total ?? 0)
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

// ── 行展示派生（纯函数，null 兜底 '—'） ────────────────────────────────
const severityOptions = [
  { value: SENTINEL_ALL, label: '全部级别' },
  { value: 'P0', label: 'P0 严重' },
  { value: 'P1', label: 'P1 警告' },
  { value: 'P2', label: 'P2 提示' },
]
const statusOptions = [
  { value: SENTINEL_ALL, label: '全部状态' },
  { value: 'firing', label: '进行中' },
  { value: 'resolved', label: '已恢复' },
]

const ruleOptions = computed(() => [
  { value: SENTINEL_ALL, label: '全部规则' },
  ...props.rules.map(r => ({ value: String(r.id), label: `#${r.id} ${r.name}` })),
])

function statusLabel(s: string): string {
  if (s === 'firing')
    return '进行中'
  if (s === 'resolved')
    return '已恢复'
  return s || EMPTY
}

/** 维度紧凑展示：target dict → `key=value · ...`；空 target → overall。 */
function formatTarget(target: Record<string, any> | null | undefined): string {
  const entries = Object.entries(target ?? {})
  if (!entries.length)
    return 'overall'
  return entries.map(([k, v]) => `${k}=${v}`).join(' · ')
}

/** 持续时长（秒）人性化；null/NaN → '—'。 */
function formatDurationSec(s: number | null | undefined): string {
  if (s == null || Number.isNaN(s))
    return EMPTY
  const sec = Math.max(0, Math.round(s))
  if (sec < 60)
    return `${sec}s`
  const m = Math.floor(sec / 60)
  const rs = sec % 60
  if (m < 60)
    return rs ? `${m}m ${rs}s` : `${m}m`
  const h = Math.floor(m / 60)
  const rm = m % 60
  return rm ? `${h}h ${rm}m` : `${h}h`
}

const OP_SYMBOL: Record<string, string> = {
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
}

/** 规则信息机器可读串：优先 rule_info.expr，否则从字段兜底拼接。 */
function eventExpr(e: AlertEventRow): string {
  const info = e.rule_info ?? {}
  if (typeof info.expr === 'string' && info.expr)
    return info.expr
  const op = OP_SYMBOL[info.op] ?? info.op ?? '?'
  const metric = info.metric ?? '?'
  const threshold = info.threshold ?? info.value ?? '?'
  const current = e.current_value ?? info.current
  const parts = [`${metric} ${op} ${threshold}`]
  if (current != null)
    parts.push(`(current ${current})`)
  if (info.window_s != null)
    parts.push(`over last ${Math.round(Number(info.window_s) / 60)}m`)
  return parts.join(' ')
}

interface EmailState { label: string, variant: 'success' | 'muted' | 'destructive' | 'outline' }
function emailState(v: string): EmailState {
  switch (v) {
    case 'sent':
      return { label: '已发送', variant: 'success' }
    case 'skipped':
      return { label: '已忽略', variant: 'muted' }
    case 'failed':
      return { label: '失败', variant: 'destructive' }
    default:
      return { label: EMPTY, variant: 'outline' }
  }
}

function onRowClick(e: AlertEventRow) {
  emit('rowClick', e)
}
</script>

<template>
  <div class="space-y-3">
    <!-- 多维筛选条 -->
    <div class="flex flex-wrap items-center gap-2.5">
      <Select v-model="severity">
        <SelectTrigger class="h-9 w-[140px] rounded-lg bg-background/90" aria-label="按级别筛选">
          <span class="icon-[lucide--signal] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in severityOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="status">
        <SelectTrigger class="h-9 w-[130px] rounded-lg bg-background/90" aria-label="按状态筛选">
          <span class="icon-[lucide--activity] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="ruleId">
        <SelectTrigger class="h-9 w-[200px] rounded-lg bg-background/90" aria-label="按规则筛选">
          <span class="icon-[lucide--list-filter] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem v-for="opt in ruleOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </SelectItem>
        </SelectContent>
      </Select>
    </div>

    <!-- 事件表（横向滚动不溢出） -->
    <div class="overflow-x-auto rounded-lg border border-border/60">
      <Table class="min-w-[860px]">
        <TableHeader>
          <TableRow class="hover:bg-transparent">
            <TableHead class="w-[150px]">
              时间
            </TableHead>
            <TableHead class="w-[80px]">
              级别
            </TableHead>
            <TableHead class="w-[88px]">
              状态
            </TableHead>
            <TableHead class="w-[140px]">
              维度
            </TableHead>
            <TableHead class="w-[88px]">
              规则ID
            </TableHead>
            <TableHead>标题 + 规则信息</TableHead>
            <TableHead class="w-[96px] text-right">
              持续时长
            </TableHead>
            <TableHead class="w-[96px] text-right">
              邮件状态
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <!-- 骨架行 -->
          <template v-if="isLoading && !events.length">
            <TableRow v-for="i in 6" :key="`sk-${i}`" class="hover:bg-transparent">
              <TableCell v-for="c in 8" :key="c">
                <Skeleton class="h-4 w-full" />
              </TableCell>
            </TableRow>
          </template>

          <!-- 错误态 -->
          <TableRow v-else-if="isError" class="hover:bg-transparent">
            <TableCell colspan="8" class="py-10 text-center text-sm text-destructive">
              <span class="icon-[lucide--circle-alert] mr-1.5 align-middle" />
              加载告警事件失败
            </TableCell>
          </TableRow>

          <!-- 空态 -->
          <TableRow v-else-if="!events.length" class="hover:bg-transparent">
            <TableCell colspan="8" class="py-12 text-center text-sm text-muted-foreground">
              <span class="icon-[lucide--bell-off] mb-2 block text-2xl opacity-60" />
              暂无告警事件
            </TableCell>
          </TableRow>

          <!-- 数据行 -->
          <TableRow
            v-for="ev in events"
            v-else
            :key="ev.id"
            class="cursor-pointer transition-colors"
            tabindex="0"
            @click="onRowClick(ev)"
            @keydown.enter="onRowClick(ev)"
          >
            <TableCell class="font-mono text-xs whitespace-nowrap tabular-nums text-muted-foreground">
              {{ formatDateTime(ev.started_at) }}
            </TableCell>
            <TableCell>
              <span
                class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold"
                :class="alertSeverityClass(ev.severity)"
              >{{ ev.severity }}</span>
            </TableCell>
            <TableCell>
              <span
                class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
                :class="alertStatusClass(ev.status)"
              >
                <span
                  class="text-[10px]"
                  :class="ev.status === 'firing' ? 'icon-[lucide--flame]' : 'icon-[lucide--circle-check]'"
                />
                {{ statusLabel(ev.status) }}
              </span>
            </TableCell>
            <TableCell class="font-mono text-xs text-muted-foreground">
              {{ formatTarget(ev.target) }}
            </TableCell>
            <TableCell class="font-mono text-xs whitespace-nowrap">
              <span v-if="ev.rule != null">#{{ ev.rule }}</span>
              <span v-else class="text-muted-foreground">{{ EMPTY }}（已删）</span>
            </TableCell>
            <TableCell class="max-w-[280px]">
              <div class="truncate font-medium" :title="ev.title_zh">
                {{ ev.title_zh || EMPTY }}
              </div>
              <div class="truncate font-mono text-[11px] text-muted-foreground" :title="eventExpr(ev)">
                {{ eventExpr(ev) }}
              </div>
            </TableCell>
            <TableCell class="text-right font-mono text-xs tabular-nums">
              <span v-if="ev.status === 'firing'" class="text-amber-500">进行中</span>
              <span v-else>{{ formatDurationSec(ev.duration_s) }}</span>
            </TableCell>
            <TableCell class="text-right">
              <Badge :variant="emailState(ev.email_sent).variant" class="text-[11px]">
                {{ emailState(ev.email_sent).label }}
              </Badge>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <!-- 分页（倒序由后端保证） -->
    <div v-if="events.length" class="flex items-center justify-between gap-3 text-xs text-muted-foreground">
      <span class="tabular-nums">第 {{ rangeStart }}–{{ rangeEnd }} 条 / 共 {{ total }} 条</span>
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
