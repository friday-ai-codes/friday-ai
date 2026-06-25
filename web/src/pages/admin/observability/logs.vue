<script setup lang="ts">
/**
 * 运维大盘「系统日志页」（UI-04）。
 *
 * 路由：/admin/observability/logs（unplugin-vue-router 文件系统注册）。
 * 守卫：definePage requiresAdmin —— 全局导航守卫拦截非 superuser；后端 IsSuperUser 纵深防御。
 *
 * 组合：顶部 ObservabilityTabs（高亮日志）+ 时间段 / 自动刷新；QueueCountersBar（消费
 * SystemLogTable 上抛的 counters，与列表同源刷新）；SystemLogTable（多维筛选 + 倒序 +
 * 分页 + 行点击下钻）；按当前筛选清理（alert-dialog 二次确认，无筛选强制 confirm_all）；
 * 底部折叠 RuntimeLogConfigForm（运行时日志配置，保存实时生效）。
 */
import type { SystemLogQuery, SystemLogRow } from '~/api/system'
import type { DrilldownContext } from '~/components/observability/LogDrilldownSheet.vue'
import { useQueryClient } from '@tanstack/vue-query'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { clearSystemLogs } from '~/api/system'
import LogDrilldownSheet from '~/components/observability/LogDrilldownSheet.vue'
import ObservabilityTabs from '~/components/observability/ObservabilityTabs.vue'
import ObservabilityTimeRange from '~/components/observability/ObservabilityTimeRange.vue'
import QueueCountersBar from '~/components/observability/QueueCountersBar.vue'
import RuntimeLogConfigForm from '~/components/observability/RuntimeLogConfigForm.vue'
import SystemLogTable from '~/components/observability/SystemLogTable.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '~/components/ui/alert-dialog'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

definePage({
  meta: { requiresAdmin: true },
})

const queryClient = useQueryClient()
const { success } = useToast()
const { handleError } = useErrorHandler()

// 日志时间段（默认近 1 小时）。
const timeRange = ref<{ start: string, end: string }>({
  start: new Date(Date.now() - 60 * 60_000).toISOString(),
  end: new Date().toISOString(),
})

// 自动刷新（默认关闭——日志页非实时刚需，避免高频拉取）。
const autoRefresh = ref(false)
const AUTO_REFRESH_MS = 8000
let timer: ReturnType<typeof setInterval> | null = null

function refreshLogs() {
  queryClient.invalidateQueries({
    predicate: q => typeof q.queryKey[0] === 'string' && (q.queryKey[0] as string).startsWith('obs-system-logs'),
  })
}
function startTimer() {
  stopTimer()
  if (autoRefresh.value) {
    timer = setInterval(() => {
      if (!document.hidden)
        refreshLogs()
    }, AUTO_REFRESH_MS)
  }
}
function stopTimer() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}
function onAutoRefreshChange(v: boolean) {
  autoRefresh.value = v
  startTimer()
}
onMounted(startTimer)
onUnmounted(stopTimer)

// 顶部四计数（来自列表查询的 counters，同源刷新）。
const counters = ref<Record<string, number> | null>(null)
function onCounters(c: Record<string, number>) {
  counters.value = c
}

// 当前筛选（去分页）——「按当前筛选清理」复用同款条件。
const currentFilters = ref<SystemLogQuery>({})
function onFiltersChange(f: SystemLogQuery) {
  currentFilters.value = f
}
const hasAnyFilter = computed(() => Object.values(currentFilters.value).some(v => v != null && v !== ''))

// ── 下钻抽屉 ────────────────────────────────────────────────────────────
const drilldownOpen = ref(false)
const drilldownContext = ref<DrilldownContext | null>(null)

function asNumber(v: unknown): number | undefined {
  if (v == null)
    return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

function onRowClick(row: SystemLogRow) {
  const corr = row.correlation ?? {}
  drilldownContext.value = {
    conversationId: (corr.conversation_id as string) || undefined,
    runId: (corr.run_id as string) || undefined,
    requestId: row.request_id || (corr.request_id as string) || undefined,
    webhookEventId: asNumber(corr.webhook_event_id ?? corr.webhook_id ?? corr.event_id),
  }
  drilldownOpen.value = true
}

// ── 按当前筛选清理 ──────────────────────────────────────────────────────
const clearOpen = ref(false)
const clearing = ref(false)

async function confirmClear() {
  clearing.value = true
  try {
    const body: SystemLogQuery & { confirm_all?: boolean } = { ...currentFilters.value }
    // 无任何筛选条件时强制 confirm_all（对齐后端防误清）。
    if (!hasAnyFilter.value)
      body.confirm_all = true
    const { deleted } = await clearSystemLogs(body)
    success('日志已清理', `共删除 ${deleted} 条`)
    clearOpen.value = false
    refreshLogs()
  }
  catch (e) {
    handleError(e, '清理日志')
  }
  finally {
    clearing.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
    <!-- 标题栏 -->
    <header class="flex flex-wrap items-center gap-3">
      <div class="flex items-center justify-center rounded-xl bg-primary/10 p-2.5">
        <span class="icon-[lucide--scroll-text] text-2xl text-primary" />
      </div>
      <div class="min-w-0 flex-1">
        <h1 class="text-2xl font-bold tracking-tight">
          系统日志
        </h1>
        <p class="text-sm text-muted-foreground">
          持久化日志查询、调用下钻与运行时配置（仅超级管理员）
        </p>
      </div>
      <Button variant="destructive" size="sm" aria-label="按当前筛选清理日志" @click="clearOpen = true">
        <span class="icon-[lucide--trash-2]" />
        按当前筛选清理
      </Button>
    </header>

    <!-- 三视图导航 + 时间段 -->
    <div class="space-y-3">
      <ObservabilityTabs />
      <ObservabilityTimeRange
        v-model="timeRange"
        :auto-refresh="autoRefresh"
        @update:auto-refresh="onAutoRefreshChange"
        @refresh="refreshLogs"
      />
    </div>

    <!-- 顶部四计数 -->
    <QueueCountersBar :counters="counters" :loading="!counters" />

    <!-- 日志列表 -->
    <section class="space-y-2">
      <SystemLogTable
        :time-range="timeRange"
        @counters="onCounters"
        @row-click="onRowClick"
        @filters-change="onFiltersChange"
      />
    </section>

    <!-- 运行时日志配置（折叠） -->
    <RuntimeLogConfigForm />

    <!-- 下钻抽屉 -->
    <LogDrilldownSheet v-model:open="drilldownOpen" :context="drilldownContext" />

    <!-- 清理二次确认 -->
    <AlertDialog v-model:open="clearOpen">
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {{ hasAnyFilter ? '清理符合筛选条件的日志' : '清空全部日志' }}
          </AlertDialogTitle>
          <AlertDialogDescription>
            <template v-if="hasAnyFilter">
              将删除<strong>符合当前筛选条件</strong>的全部日志，此操作<strong>不可逆</strong>。请确认筛选范围后再继续。
            </template>
            <template v-else>
              当前<strong>未设置任何筛选条件</strong>，将<strong>清空全部系统日志</strong>（confirm_all）。此操作<strong>不可逆</strong>，请谨慎操作。
            </template>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel :disabled="clearing">
            取消
          </AlertDialogCancel>
          <AlertDialogAction :disabled="clearing" @click="confirmClear">
            <span v-if="clearing" class="icon-[lucide--loader-2] mr-1.5 animate-spin" />
            {{ hasAnyFilter ? '确认清理' : '确认清空全部' }}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </div>
</template>
