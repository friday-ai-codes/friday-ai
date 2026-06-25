<script setup lang="ts">
/**
 * 快照行（UI-SPEC §3.1）：CPU / 内存 / DB / Redis / Qdrant / 协程 / 后台任务一排卡，
 * 卡内内联阈值（超阈变色 绿→琥珀→红），源 available=false / 字段缺失 → n/a 灰态降级
 * （best-effort，绝不抛异常，对齐 snapshot_service envelope）。
 *
 * 阈值默认值（内置，注释来源——对齐 REFERENCE-UI §1.2 示例与运维经验软阈值）：
 *   CPU   警告 60  严重 95
 *   内存  警告 70  严重 90
 *   协程  警告 8000 严重 15000
 *   DB/Redis 连接占比 警告 70% 严重 90%（相对 max_connections / maxclients）
 */
import type { MetricsSnapshot } from '~/api/system'
import { computed } from 'vue'
import { EMPTY, formatNumber, formatPercent } from '~/components/observability/format'
import { healthBandClass } from '~/components/observability/status'
import { Card, CardContent } from '~/components/ui/card'
import { Skeleton } from '~/components/ui/skeleton'

const props = withDefaults(defineProps<{
  snapshot: MetricsSnapshot | null
  loading?: boolean
}>(), {
  loading: false,
})

interface SnapshotCard {
  key: string
  label: string
  icon: string
  available: boolean
  /** 不可用时的灰态说明（如 'n/a (sqlite dev)'）。 */
  naText?: string
  /** 主值字符串。 */
  value: string
  /** 主值文本色 class（取自 healthBandClass 的文本部分）。 */
  valueClass: string
  /** 明细副行（如 'active 3 · idle 5 / 20'）。 */
  detail?: string
  /** 内联阈值说明（如 '警告 60 · 严重 95'）。 */
  threshold?: string
}

/** 从 healthBandClass 返回串中抽取文本色（'text-rose-500 bg-...' → 'text-rose-500'）。 */
function bandText(value: number, warn: number, crit: number, invert = false): string {
  const cls = healthBandClass(value, warn, crit, invert)
  return cls.split(' ').find(c => c.startsWith('text-')) ?? 'text-foreground'
}

const cards = computed<SnapshotCard[]>(() => {
  const snap = props.snapshot
  const muted = 'text-muted-foreground'
  if (!snap) {
    return []
  }

  const list: SnapshotCard[] = []
  const host = snap.host
  const hostOk = host?.available !== false

  // CPU
  {
    const v = host?.cpu_percent
    const ok = hostOk && v != null
    list.push({
      key: 'cpu',
      label: 'CPU',
      icon: 'lucide--cpu',
      available: ok,
      value: ok ? formatPercent(v, 1) : EMPTY,
      valueClass: ok ? bandText(v!, 60, 95) : muted,
      threshold: '警告 60% · 严重 95%',
    })
  }

  // 内存
  {
    const v = host?.mem_percent
    const ok = hostOk && v != null
    list.push({
      key: 'mem',
      label: '内存',
      icon: 'lucide--memory-stick',
      available: ok,
      value: ok ? formatPercent(v, 1) : EMPTY,
      valueClass: ok ? bandText(v!, 70, 90) : muted,
      detail: host?.mem_used_mb != null && host?.mem_total_mb != null
        ? `${formatNumber(host.mem_used_mb)} / ${formatNumber(host.mem_total_mb)} MB`
        : undefined,
      threshold: '警告 70% · 严重 90%',
    })
  }

  // DB 连接
  {
    const db = snap.db
    const ok = db?.available !== false
    const conn = db?.connections
    const total = conn?.total
    const max = db?.max_connections
    let value = EMPTY
    let valueClass = muted
    let detail: string | undefined
    if (ok && total != null) {
      value = formatNumber(total)
      detail = `活跃 ${formatNumber(conn?.active)} · 空闲 ${formatNumber(conn?.idle)}${max ? ` / 上限 ${formatNumber(max)}` : ''}`
      if (max && max > 0)
        valueClass = bandText((total / max) * 100, 70, 90)
      else
        valueClass = 'text-foreground'
    }
    list.push({
      key: 'db',
      label: 'DB 连接',
      icon: 'lucide--database',
      available: ok && total != null,
      naText: ok ? undefined : (db?.vendor === 'sqlite' ? 'n/a (sqlite dev)' : 'n/a'),
      value,
      valueClass,
      detail,
      threshold: max ? '占比 警告 70% · 严重 90%' : undefined,
    })
  }

  // Redis（取第一路有效 client；通常 cache）
  {
    const redis = snap.redis
    const clients = redis?.clients ?? {}
    const entry = Object.entries(clients).find(([, c]) => c?.available !== false)
    const client = entry?.[1]
    const ok = redis?.available !== false && !!client
    const connected = client?.connected_clients
    const maxc = client?.maxclients
    const hit = client?.hit_rate
    let value = EMPTY
    let valueClass = muted
    let detail: string | undefined
    if (ok && connected != null) {
      value = formatNumber(connected)
      detail = `${maxc ? `/ ${formatNumber(maxc)} 上限 · ` : ''}命中率 ${hit != null ? formatPercent(hit * 100, 1) : EMPTY}`
      if (maxc && maxc > 0)
        valueClass = bandText((connected / maxc) * 100, 70, 90)
      else
        valueClass = 'text-foreground'
    }
    list.push({
      key: 'redis',
      label: 'Redis 连接',
      icon: 'lucide--square-stack',
      available: ok && connected != null,
      naText: ok ? undefined : 'n/a',
      value,
      valueClass,
      detail,
      threshold: maxc ? '占比 警告 70% · 严重 90%' : undefined,
    })
  }

  // Qdrant
  {
    const q = snap.qdrant
    const ok = q?.available !== false && q?.liveness !== false
    list.push({
      key: 'qdrant',
      label: 'Qdrant',
      icon: 'lucide--boxes',
      available: ok,
      naText: ok ? undefined : 'n/a',
      value: ok ? (q?.liveness ? '可用' : EMPTY) : EMPTY,
      valueClass: ok ? 'text-emerald-500' : muted,
      detail: ok && q?.collection_count != null ? `集合 ${formatNumber(q.collection_count)} 个` : undefined,
    })
  }

  // 协程数
  {
    const v = host?.asyncio_tasks
    const ok = hostOk && v != null
    list.push({
      key: 'coroutines',
      label: '协程数',
      icon: 'lucide--git-branch',
      available: ok,
      naText: ok ? undefined : 'n/a',
      value: ok ? formatNumber(v!) : EMPTY,
      valueClass: ok ? bandText(v!, 8000, 15000) : muted,
      detail: host?.threads != null ? `线程 ${formatNumber(host.threads)}` : undefined,
      threshold: '警告 8000 · 严重 15000',
    })
  }

  // 后台任务数
  {
    const bg = host?.background_tasks
    const totalActive = bg?.total_active
    const ok = hostOk && totalActive != null
    list.push({
      key: 'background',
      label: '后台任务',
      icon: 'lucide--layers',
      available: ok,
      naText: ok ? undefined : 'n/a',
      value: ok ? formatNumber(totalActive!) : EMPTY,
      valueClass: 'text-foreground',
      detail: bg
        ? `队列 ${formatNumber(bg.durable_active)} · 容器 ${formatNumber(bg.subagent_active)}`
        : undefined,
    })
  }

  return list
})
</script>

<template>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
    <template v-if="loading">
      <Card v-for="i in 7" :key="i" class="rounded-xl border-border/70">
        <CardContent class="space-y-2 p-4">
          <Skeleton class="h-4 w-16" />
          <Skeleton class="h-7 w-20" />
          <Skeleton class="h-3 w-full" />
        </CardContent>
      </Card>
    </template>

    <Card
      v-for="card in cards"
      v-else
      :key="card.key"
      class="rounded-xl border-border/70 transition-colors duration-200"
      :class="card.available ? '' : 'opacity-70'"
    >
      <CardContent class="space-y-1.5 p-4">
        <div class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <span class="text-sm" :class="`icon-[${card.icon}]`" />
          {{ card.label }}
        </div>

        <div v-if="card.available" class="text-2xl font-bold tabular-nums" :class="card.valueClass">
          {{ card.value }}
        </div>
        <div v-else class="text-lg font-semibold text-muted-foreground/70">
          {{ card.naText || 'n/a' }}
        </div>

        <p v-if="card.available && card.detail" class="truncate text-[11px] text-muted-foreground" :title="card.detail">
          {{ card.detail }}
        </p>
        <p v-if="card.available && card.threshold" class="text-[10px] text-muted-foreground/60">
          {{ card.threshold }}
        </p>
        <p v-else-if="!card.available" class="text-[10px] text-muted-foreground/50">
          数据源不可用
        </p>
      </CardContent>
    </Card>
  </div>
</template>
