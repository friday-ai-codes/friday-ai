<script setup lang="ts">
/**
 * 运维大盘「告警事件页」（UI-03）。
 *
 * 路由：/admin/observability/alerts（unplugin-vue-router 文件系统注册）。
 * 守卫：definePage requiresAdmin —— 全局导航守卫拦截非 superuser；后端 IsSuperUser 纵深防御。
 *
 * 组合：顶部 ObservabilityTabs（高亮告警）+ 时间段筛选；上方 AlertRulesPanel（阈值规则
 * 配置入口），下方 AlertEventsTable（事件表，行点击打开 AlertEventDetailSheet）。规则面板
 * 与事件表的规则筛选选项共享 ['obs-alert-rules'] query 缓存；规则增删改后 invalidate 自动
 * 刷新筛选选项。
 */
import type { AlertEventRow, AlertRule } from '~/api/system'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { listAlertRules } from '~/api/system'
import AlertEventDetailSheet from '~/components/observability/AlertEventDetailSheet.vue'
import AlertEventsTable from '~/components/observability/AlertEventsTable.vue'
import AlertRulesPanel from '~/components/observability/AlertRulesPanel.vue'
import ObservabilityTabs from '~/components/observability/ObservabilityTabs.vue'
import ObservabilityTimeRange from '~/components/observability/ObservabilityTimeRange.vue'

definePage({
  meta: { requiresAdmin: true },
})

const queryClient = useQueryClient()

// 事件时间段筛选（默认近 24 小时）。
const timeRange = ref<{ start: string, end: string }>({
  start: new Date(Date.now() - 24 * 60 * 60_000).toISOString(),
  end: new Date().toISOString(),
})

// 自动刷新（默认关闭——历史事件页非实时刚需）：开启时周期 invalidate 事件查询。
const autoRefresh = ref(false)
const AUTO_REFRESH_MS = 10_000
let timer: ReturnType<typeof setInterval> | null = null

function refreshAll() {
  queryClient.invalidateQueries({
    predicate: q => typeof q.queryKey[0] === 'string' && (q.queryKey[0] as string).startsWith('obs-alert-'),
  })
}
function startTimer() {
  stopTimer()
  if (autoRefresh.value) {
    timer = setInterval(() => {
      if (!document.hidden)
        refreshAll()
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

// 规则列表（供事件表规则筛选选项；与 AlertRulesPanel 共享同 queryKey 缓存）。
const { data: rulesData } = useQuery({
  queryKey: ['obs-alert-rules'],
  queryFn: () => listAlertRules(),
  retry: 1,
})
const rules = computed<AlertRule[]>(() => rulesData.value?.items ?? [])

// 事件详情抽屉。
const detailOpen = ref(false)
const detailEvent = ref<AlertEventRow | null>(null)
function openDetail(ev: AlertEventRow) {
  detailEvent.value = ev
  detailOpen.value = true
}
</script>

<template>
  <div class="mx-auto max-w-7xl space-y-6 p-4 sm:p-6">
    <!-- 标题栏 -->
    <header class="flex flex-wrap items-center gap-3">
      <div class="flex items-center justify-center rounded-xl bg-primary/10 p-2.5">
        <span class="icon-[lucide--bell-ring] text-2xl text-primary" />
      </div>
      <div class="min-w-0 flex-1">
        <h1 class="text-2xl font-bold tracking-tight">
          告警事件
        </h1>
        <p class="text-sm text-muted-foreground">
          历史告警查询与阈值规则配置（仅超级管理员）
        </p>
      </div>
    </header>

    <!-- 三视图导航 + 时间段 -->
    <div class="space-y-3">
      <ObservabilityTabs />
      <ObservabilityTimeRange
        v-model="timeRange"
        :auto-refresh="autoRefresh"
        @update:auto-refresh="onAutoRefreshChange"
        @refresh="refreshAll"
      />
    </div>

    <!-- 阈值规则配置入口 -->
    <AlertRulesPanel />

    <!-- 告警事件表 -->
    <section class="space-y-2">
      <h2 class="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        <span class="icon-[lucide--list] h-4 w-4" /> 告警事件
      </h2>
      <AlertEventsTable :rules="rules" :time-range="timeRange" @row-click="openDetail" />
    </section>

    <!-- 事件详情抽屉 -->
    <AlertEventDetailSheet v-model:open="detailOpen" :event="detailEvent" />
  </div>
</template>
