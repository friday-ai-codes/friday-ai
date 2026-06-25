<script setup lang="ts">
/**
 * 系统日志队列四计数 bar（UI-04 §5.1）。
 *
 * 消费 querySystemLogs 返回的 `counters`（即后端 log_sink.snapshot_counters()）。
 * 实测后端键名为：`queued`(当前队列深) / `max`(队列上限=5000) / `enqueued`(入队) /
 * `written`(成功落库) / `dropped`(队列满丢弃) / `write_failed`(落库失败) /
 * `sampled_out`(采样丢弃)。为兼容键名漂移，用宽松取键 + 兜底 0，缺键显示 0 不报错。
 *
 * 四计数语义（对齐 UI-SPEC §5.1）：
 * - 队列 queued/max（进度条 + x/5000）
 * - 写入 written（成功落库累计）
 * - 丢弃 dropped（>0 琥珀；含队列满；采样丢弃 sampled_out 作副注）
 * - 失败 write_failed（>0 红）
 *
 * UI-SPEC §0：tabular-nums、亮暗 token、lucide 图标无 emoji、加载骨架、语义状态色。
 */
import { computed } from 'vue'
import { Progress } from '~/components/ui/progress'
import { Skeleton } from '~/components/ui/skeleton'
import { formatNumber } from './format'

const props = withDefaults(defineProps<{
  /** querySystemLogs 返回的队列计数（log_sink.snapshot_counters），可空。 */
  counters?: Record<string, number> | null
  /** 首屏加载（无任何计数）时显示骨架。 */
  loading?: boolean
}>(), {
  counters: null,
  loading: false,
})

/** 宽松取键：按候选键名依次取第一个有效数值，全缺回退 0（绝不报错）。 */
function pick(keys: string[], fallback = 0): number {
  const c = props.counters
  if (!c)
    return fallback
  for (const k of keys) {
    const v = c[k]
    if (typeof v === 'number' && !Number.isNaN(v))
      return v
  }
  return fallback
}

const queued = computed(() => pick(['queued', 'queue_size']))
const maxSize = computed(() => pick(['max', 'maxlen', 'maxsize'], 5000) || 5000)
const written = computed(() => pick(['written', 'enqueued']))
const dropped = computed(() => pick(['dropped']))
const sampledOut = computed(() => pick(['sampled_out']))
const failed = computed(() => pick(['write_failed', 'failed']))

/** 队列占用百分比（0..100，clamp 防越界）。 */
const queuePercent = computed(() => {
  const m = maxSize.value
  if (!m)
    return 0
  return Math.min(100, Math.max(0, (queued.value / m) * 100))
})

/** 显示骨架：明确 loading 且尚无计数。 */
const showSkeleton = computed(() => props.loading && !props.counters)
</script>

<template>
  <div class="grid grid-cols-2 gap-3 lg:grid-cols-4">
    <!-- 队列深度（进度条 + x/max） -->
    <div class="rounded-xl border border-border/60 bg-card p-3.5">
      <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span class="icon-[lucide--layers] text-sm" />
        队列深度
      </div>
      <template v-if="showSkeleton">
        <Skeleton class="mt-2 h-6 w-20" />
        <Skeleton class="mt-2 h-2 w-full" />
      </template>
      <template v-else>
        <div class="mt-1.5 flex items-baseline gap-1 font-mono tabular-nums">
          <span class="text-xl font-semibold">{{ formatNumber(queued) }}</span>
          <span class="text-xs text-muted-foreground">/ {{ formatNumber(maxSize) }}</span>
        </div>
        <Progress :model-value="queuePercent" class="mt-2 h-1.5" aria-label="队列占用" />
      </template>
    </div>

    <!-- 写入（成功落库累计） -->
    <div class="rounded-xl border border-border/60 bg-card p-3.5">
      <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span class="icon-[lucide--database] text-sm" />
        已写入
      </div>
      <template v-if="showSkeleton">
        <Skeleton class="mt-2 h-6 w-20" />
      </template>
      <template v-else>
        <div class="mt-1.5 font-mono text-xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-500">
          {{ formatNumber(written) }}
        </div>
        <p class="mt-1 text-[11px] text-muted-foreground">
          成功落库累计
        </p>
      </template>
    </div>

    <!-- 丢弃（队列满，>0 琥珀） -->
    <div class="rounded-xl border border-border/60 bg-card p-3.5">
      <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span class="icon-[lucide--package-x] text-sm" />
        已丢弃
      </div>
      <template v-if="showSkeleton">
        <Skeleton class="mt-2 h-6 w-20" />
      </template>
      <template v-else>
        <div
          class="mt-1.5 font-mono text-xl font-semibold tabular-nums"
          :class="dropped > 0 ? 'text-amber-500' : 'text-foreground'"
        >
          {{ formatNumber(dropped) }}
        </div>
        <p class="mt-1 text-[11px] text-muted-foreground tabular-nums">
          采样丢弃 {{ formatNumber(sampledOut) }}
        </p>
      </template>
    </div>

    <!-- 失败（落库失败，>0 红） -->
    <div class="rounded-xl border border-border/60 bg-card p-3.5">
      <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
        <span class="icon-[lucide--circle-alert] text-sm" />
        落库失败
      </div>
      <template v-if="showSkeleton">
        <Skeleton class="mt-2 h-6 w-20" />
      </template>
      <template v-else>
        <div
          class="mt-1.5 font-mono text-xl font-semibold tabular-nums"
          :class="failed > 0 ? 'text-rose-500' : 'text-foreground'"
        >
          {{ formatNumber(failed) }}
        </div>
        <p class="mt-1 text-[11px] text-muted-foreground">
          落库失败累计
        </p>
      </template>
    </div>
  </div>
</template>
