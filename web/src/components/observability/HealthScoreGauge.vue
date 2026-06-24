<script setup lang="ts">
/**
 * 复合健康分圆环（UI-SPEC §2.1）：0–100 加权健康分 + 健康/警告/严重徽标。
 *
 * 圆环实现选型：用纯 SVG 圆环（stroke-dasharray）而非 echarts gauge —— 既有
 * `analytics/echarts-setup.ts` 仅按需注册了 line/bar，未注册 GaugeChart；为不触碰
 * 跨 plan 的共享注册文件、并天然支持 prefers-reduced-motion（CSS 媒体查询禁过渡），
 * 这里自绘 SVG 环更轻量可控。
 *
 * 加权算分（Claude's Discretion 公式，best-effort 缺项跳过并重新归一化分母）：
 *   factor          weight  健康度方向（越低越健康 → 1 - clamp(x)）
 *   ────────────────────────────────────────────────────────────
 *   CPU 使用率         0.25   host.cpu_percent          (0..100)
 *   内存使用率         0.20   host.mem_percent          (0..100)
 *   请求错误率         0.25   errorRate                 (0..1)
 *   上游错误率         0.15   upstreamErrorRate         (0..1)
 *   队列积压           0.15   concurrency 派生占用率     (0..1)
 * 每因子转 0..1 健康度后按权重求和 ×100；源缺失（available=false/undefined）该因子
 * 不计并把其权重从分母剔除（重新归一化），全部缺失 → 分数为 null（灰态 n/a）。
 */
import type { MetricsSnapshot } from '~/api/system'
import { computed } from 'vue'
import { healthScoreBand } from '~/components/observability/status'
import { Skeleton } from '~/components/ui/skeleton'

const props = withDefaults(defineProps<{
  snapshot: MetricsSnapshot | null
  /** 近窗请求错误率（0..1），由父页从 queryMetrics error 派生。 */
  errorRate?: number | null
  /** 近窗上游错误率（0..1）。 */
  upstreamErrorRate?: number | null
  loading?: boolean
}>(), {
  errorRate: null,
  upstreamErrorRate: null,
  loading: false,
})

function clamp01(v: number): number {
  if (Number.isNaN(v))
    return 0
  return Math.min(1, Math.max(0, v))
}

interface Factor {
  key: string
  label: string
  weight: number
  /** 0..1 健康度（1=最健康）。 */
  health: number
  /** 原始展示值（如 '42%'）。 */
  display: string
}

/** 从 concurrency 快照 best-effort 派生「队列积压」占用率（0..1），无法判定返回 null。 */
function deriveBacklogRatio(snap: MetricsSnapshot): number | null {
  const c = snap.concurrency
  if (!c || c.available === false)
    return null
  // durable_queues：todo+doing 相对软阈值（200 条积压视作满载）。
  const dq = c.durable_queues as Record<string, any> | undefined
  if (dq && typeof dq === 'object') {
    const totals = (dq.totals ?? dq) as Record<string, any>
    const todo = Number(totals?.todo ?? 0)
    const doing = Number(totals?.doing ?? 0)
    if (!Number.isNaN(todo) && !Number.isNaN(doing)) {
      const backlog = todo + doing
      return clamp01(backlog / 200)
    }
  }
  // provider_slots：尽力取占用率（used/total）。
  const slots = c.provider_slots as Record<string, any> | undefined
  if (slots && typeof slots === 'object') {
    let used = 0
    let total = 0
    for (const v of Object.values(slots)) {
      if (v && typeof v === 'object') {
        used += Number((v as any).in_use ?? (v as any).used ?? 0) || 0
        total += Number((v as any).limit ?? (v as any).total ?? 0) || 0
      }
    }
    if (total > 0)
      return clamp01(used / total)
  }
  return null
}

const factors = computed<Factor[]>(() => {
  const snap = props.snapshot
  if (!snap)
    return []
  const list: Factor[] = []

  const host = snap.host
  if (host?.available !== false && host?.cpu_percent != null) {
    const x = clamp01(host.cpu_percent / 100)
    list.push({ key: 'cpu', label: 'CPU', weight: 0.25, health: 1 - x, display: `${host.cpu_percent.toFixed(0)}%` })
  }
  if (host?.available !== false && host?.mem_percent != null) {
    const x = clamp01(host.mem_percent / 100)
    list.push({ key: 'mem', label: '内存', weight: 0.20, health: 1 - x, display: `${host.mem_percent.toFixed(0)}%` })
  }
  if (props.errorRate != null) {
    // 错误率以 20% 为「完全不健康」基准放大灵敏度。
    const x = clamp01(props.errorRate / 0.2)
    list.push({ key: 'err', label: '错误率', weight: 0.25, health: 1 - x, display: `${(props.errorRate * 100).toFixed(1)}%` })
  }
  if (props.upstreamErrorRate != null) {
    const x = clamp01(props.upstreamErrorRate / 0.2)
    list.push({ key: 'upstream', label: '上游错误', weight: 0.15, health: 1 - x, display: `${(props.upstreamErrorRate * 100).toFixed(1)}%` })
  }
  const backlog = deriveBacklogRatio(snap)
  if (backlog != null)
    list.push({ key: 'queue', label: '队列积压', weight: 0.15, health: 1 - backlog, display: `${(backlog * 100).toFixed(0)}%` })

  return list
})

/** 加权 + 缺项重新归一化的 0–100 分；无任何因子 → null。 */
const score = computed<number | null>(() => {
  const list = factors.value
  if (!list.length)
    return null
  const denom = list.reduce((s, f) => s + f.weight, 0)
  if (denom <= 0)
    return null
  const weighted = list.reduce((s, f) => s + f.weight * f.health, 0)
  return Math.round((weighted / denom) * 100)
})

const band = computed(() => (score.value == null ? null : healthScoreBand(score.value)))

const ringColor = computed(() => {
  const s = score.value
  if (s == null)
    return 'rgb(148 163 184)' // muted
  if (s >= 80)
    return 'rgb(16 185 129)' // emerald
  if (s >= 60)
    return 'rgb(245 158 11)' // amber
  return 'rgb(244 63 94)' // rose
})

// SVG 环几何：半径 54，周长 = 2πr。
const RADIUS = 54
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
const dashOffset = computed(() => {
  const s = score.value ?? 0
  return CIRCUMFERENCE * (1 - clamp01(s / 100))
})
</script>

<template>
  <div class="flex h-full flex-col items-center justify-center gap-4 rounded-xl border border-border/70 bg-card p-5">
    <div class="flex items-center gap-2 self-start text-sm font-medium text-muted-foreground">
      <span class="icon-[lucide--gauge] text-base text-primary" />
      复合健康分
    </div>

    <template v-if="loading">
      <Skeleton class="size-36 rounded-full" />
      <Skeleton class="h-5 w-40" />
    </template>

    <template v-else>
      <div class="relative flex items-center justify-center">
        <svg width="148" height="148" viewBox="0 0 148 148" class="-rotate-90" role="img" :aria-label="score == null ? '健康分暂无数据' : `健康分 ${score} 分，${band?.label}`">
          <circle
            cx="74"
            cy="74"
            :r="RADIUS"
            fill="none"
            stroke="currentColor"
            class="text-muted/40"
            stroke-width="12"
          />
          <circle
            cx="74"
            cy="74"
            :r="RADIUS"
            fill="none"
            :stroke="ringColor"
            stroke-width="12"
            stroke-linecap="round"
            :stroke-dasharray="CIRCUMFERENCE"
            :stroke-dashoffset="dashOffset"
            class="health-ring"
          />
        </svg>
        <div class="absolute inset-0 flex flex-col items-center justify-center">
          <span v-if="score == null" class="text-2xl font-bold tabular-nums text-muted-foreground">n/a</span>
          <template v-else>
            <span class="text-4xl font-bold tabular-nums" :style="{ color: ringColor }">{{ score }}</span>
            <span class="text-[11px] text-muted-foreground">满分 100</span>
          </template>
        </div>
      </div>

      <span
        v-if="band"
        class="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm font-medium"
        :class="band.class"
      >
        <span
          class="size-1.5 rounded-full"
          :class="score! >= 80 ? 'bg-emerald-500' : score! >= 60 ? 'bg-amber-500' : 'bg-rose-500'"
        />
        {{ band.label }}
      </span>
      <span v-else class="rounded-full bg-muted px-3 py-1 text-sm text-muted-foreground">
        暂无数据
      </span>

      <div v-if="factors.length" class="flex flex-wrap justify-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span v-for="f in factors" :key="f.key" class="tabular-nums">
          {{ f.label }} {{ f.display }}
        </span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.health-ring {
  transition:
    stroke-dashoffset 600ms ease,
    stroke 300ms ease;
}

@media (prefers-reduced-motion: reduce) {
  .health-ring {
    transition: none;
  }
}
</style>
