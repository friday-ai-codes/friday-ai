<script setup lang="ts">
import type { CrawlQueueItem, CrawlQueueStatus } from '~/api/ingest'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ingestApi } from '~/api/ingest'
import CompactEmptyState from '~/components/common/CompactEmptyState.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { t } = useI18n()
const { confirm } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()
const router = useRouter()

// 队列 query key（DB 真相源；刷新/容器重建后由该 query 自动恢复，无内存 batchId 依赖）。
const QUEUE_KEY = ['crawl-ingest-queue'] as const

// ==================== 队列恢复（GET /delivery/ingest/queue/） ====================
const queueQuery = useQuery({
  queryKey: QUEUE_KEY,
  queryFn: () => ingestApi.listQueue(),
  // 仅存在 running 项 → 2s 轮询；否则停轮（契约：queued 未点开始不会自行推进，
  // 纳入轮询将永久空转，故按 UI-SPEC 仅 running 触发，沿用 ReconcilePanel 范式）。
  refetchInterval: query =>
    (query.state.data?.some(r => r.status === 'running') ? 2000 : false),
})

const queueItems = computed<CrawlQueueItem[]>(() => queueQuery.data.value ?? [])
const isLoading = computed(() => queueQuery.isLoading.value)
const isError = computed(() => queueQuery.isError.value)
const queueCount = computed(() => queueItems.value.length)
const showEmpty = computed(() => !isLoading.value && !isError.value && queueCount.value === 0)

// ==================== 入队（爬取 → enqueue） ====================
const crawlInput = ref('')
const crawlMessage = ref('')
const crawlMessageKind = ref<'empty' | 'error' | ''>('')
const feishuNotConfigured = ref(false)
const feishuDeeplink = ref('/admin#integration')

type EnqueueOutcome
  = | { kind: 'enqueued', count: number }
    | { kind: 'feishu', message: string, deeplink: string }
    | { kind: 'message', tone: 'empty' | 'error', message: string }

const enqueueMutation = useMutation({
  // 入队前预处理：crawlUrl 抽取条目 → enqueueQueue 入队（列表与状态一律以后端为准）。
  mutationFn: async (url: string): Promise<EnqueueOutcome> => {
    const res = await ingestApi.crawlUrl(url)
    if (res.status === 'feishu_not_configured') {
      return {
        kind: 'feishu',
        message: res.message,
        deeplink: res.settings_deeplink || '/admin#integration',
      }
    }
    if (res.status === 'ok' && res.items.length) {
      await ingestApi.enqueueQueue(res.items)
      return { kind: 'enqueued', count: res.items.length }
    }
    return {
      kind: 'message',
      tone: res.status === 'empty' ? 'empty' : 'error',
      message: res.message || '',
    }
  },
  onSuccess: (outcome) => {
    if (outcome.kind === 'enqueued') {
      success(t('crawlQueue.enqueued'))
      crawlInput.value = ''
      queryClient.invalidateQueries({ queryKey: QUEUE_KEY })
    }
    else if (outcome.kind === 'feishu') {
      feishuNotConfigured.value = true
      feishuDeeplink.value = outcome.deeplink
      crawlMessage.value = outcome.message
    }
    else {
      crawlMessageKind.value = outcome.tone
      crawlMessage.value = outcome.message
    }
  },
  onError: (e) => {
    handleError(e, t('crawlQueue.enqueueFailed'))
  },
})

const enqueuing = computed(() => enqueueMutation.isPending.value)

function doEnqueue() {
  const url = crawlInput.value.trim()
  if (!url || enqueuing.value)
    return
  crawlMessage.value = ''
  crawlMessageKind.value = ''
  feishuNotConfigured.value = false
  enqueueMutation.mutate(url)
}

function goConfigureFeishu() {
  router.push(feishuDeeplink.value)
}

// ==================== 行内动作（start/stop/retry） ====================
// 进行中按钮 disabled + spinner：以 `${batchId}:${action}` 标记当前正在执行的行内动作。
const actingKey = ref('')

function isActing(batchId: string, action: 'start' | 'stop' | 'retry') {
  return actingKey.value === `${batchId}:${action}`
}

function isRowBusy(batchId: string) {
  return actingKey.value.startsWith(`${batchId}:`)
}

async function runAction(batchId: string, action: 'start' | 'stop' | 'retry') {
  if (actingKey.value)
    return
  // stop 为破坏性动作：经全局确认弹窗（GlobalConfirmDialog 已挂载于 App.vue）。
  if (action === 'stop') {
    const ok = await confirm({
      title: t('crawlQueue.stopConfirm.title'),
      description: t('crawlQueue.stopConfirm.description'),
      confirmText: t('crawlQueue.stopConfirm.confirmText'),
      variant: 'destructive',
    })
    if (!ok)
      return
  }
  actingKey.value = `${batchId}:${action}`
  try {
    if (action === 'start')
      await ingestApi.startRun(batchId)
    else if (action === 'stop')
      await ingestApi.stopRun(batchId)
    else
      await ingestApi.retryRun(batchId)
    queryClient.invalidateQueries({ queryKey: QUEUE_KEY })
  }
  catch (e) {
    handleError(e, t(`crawlQueue.actions.${action}`))
  }
  finally {
    actingKey.value = ''
  }
}

// ==================== 状态徽标 / 动作可见性 / 展示辅助 ==================== //
const STATUS_VARIANT: Record<CrawlQueueStatus, 'muted' | 'info' | 'warning' | 'destructive' | 'success'> = {
  queued: 'muted',
  running: 'info',
  stopped: 'warning',
  failed: 'destructive',
  completed: 'success',
}

const STATUS_ICON: Record<CrawlQueueStatus, string> = {
  queued: 'icon-[lucide--clock]',
  running: 'icon-[lucide--loader-circle] animate-spin',
  stopped: 'icon-[lucide--circle-pause]',
  failed: 'icon-[lucide--alert-circle]',
  completed: 'icon-[lucide--check-circle-2]',
}

function canStart(s: CrawlQueueStatus) {
  return s === 'queued' || s === 'stopped' || s === 'failed'
}
function canStop(s: CrawlQueueStatus) {
  return s === 'running' || s === 'queued'
}
function canRetry(s: CrawlQueueStatus) {
  return s === 'failed' || s === 'stopped' || s === 'completed'
}

function fmtTime(iso: string | null): string {
  if (!iso)
    return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime()))
    return '—'
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="card" data-testid="crawl-queue-panel">
    <!-- 卡片头 -->
    <div class="px-5 py-3.5 border-b border-border/50">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--link-2] text-primary" />
        <h3 class="text-sm font-semibold">
          {{ t('crawlQueue.title') }}
        </h3>
      </div>
      <p class="text-xs text-muted-foreground mt-0.5">
        {{ t('crawlQueue.subtitle') }}
      </p>
    </div>

    <!-- 入队区 -->
    <div class="p-5 space-y-3 border-b border-border/50">
      <div class="flex items-center gap-2">
        <input
          v-model="crawlInput"
          type="url"
          data-testid="crawl-url-input"
          :placeholder="t('crawlQueue.input.placeholder')"
          class="flex-1 h-9 rounded border border-border bg-background px-3 text-sm outline-none focus:ring-1 focus:ring-primary/40"
          :disabled="enqueuing"
          @keydown.enter="doEnqueue"
        >
        <Button
          data-testid="crawl-enqueue-button"
          :disabled="enqueuing || !crawlInput.trim()"
          @click="doEnqueue"
        >
          <span v-if="enqueuing" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
          <span v-else class="icon-[lucide--plus] mr-1.5" />
          {{ enqueuing ? t('crawlQueue.input.enqueuing') : t('crawlQueue.input.enqueue') }}
        </Button>
      </div>

      <!-- 未配置飞书：引导去系统设置（既有行为不回退） -->
      <div
        v-if="feishuNotConfigured"
        class="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2"
      >
        <span class="icon-[lucide--alert-triangle] text-amber-600 dark:text-amber-400 mt-0.5" />
        <div class="flex-1 min-w-0">
          <p class="text-xs text-amber-700 dark:text-amber-400">
            {{ crawlMessage }}
          </p>
          <Button
            data-testid="crawl-feishu-deeplink"
            variant="outline"
            size="sm"
            class="h-7 mt-2"
            @click="goConfigureFeishu"
          >
            <span class="icon-[lucide--settings] mr-1.5" />
            {{ t('crawlQueue.feishuNotConfigured.configure') }}
          </Button>
        </div>
      </div>

      <!-- 爬取为空 / 出错提示 -->
      <p
        v-else-if="crawlMessage"
        class="text-xs"
        :class="crawlMessageKind === 'error' ? 'text-destructive' : 'text-muted-foreground'"
      >
        {{ crawlMessage }}
      </p>
    </div>

    <!-- 列表头 -->
    <div class="px-5 py-3 flex items-center justify-between gap-3 border-b border-border/50">
      <span class="text-sm font-medium">
        {{ t('crawlQueue.listTitle', { count: queueCount }) }}
      </span>
      <Button
        variant="outline"
        size="sm"
        class="h-8"
        :disabled="queueQuery.isFetching.value"
        @click="queueQuery.refetch()"
      >
        <span
          class="icon-[lucide--refresh-cw] mr-1.5"
          :class="{ 'animate-spin': queueQuery.isFetching.value }"
        />
        {{ t('crawlQueue.refresh') }}
      </Button>
    </div>

    <!-- loading：骨架占位（含读屏可读 loading 文案，对视觉无侵入） -->
    <div v-if="isLoading" class="p-5 space-y-3" role="status" aria-live="polite">
      <span class="sr-only">{{ t('crawlQueue.loading') }}</span>
      <Skeleton v-for="n in 3" :key="n" class="h-14 w-full" />
    </div>

    <!-- error：加载失败 + 重试加载 -->
    <div v-else-if="isError" class="p-5 space-y-2">
      <p class="text-xs text-destructive">
        {{ t('crawlQueue.loadError') }}
      </p>
      <Button variant="outline" size="sm" class="h-8" @click="queueQuery.refetch()">
        <span class="icon-[lucide--rotate-cw] mr-1.5" />
        {{ t('crawlQueue.retryLoad') }}
      </Button>
    </div>

    <!-- empty：空队列 -->
    <div v-else-if="showEmpty" data-testid="crawl-queue-empty">
      <CompactEmptyState
        icon="lucide--inbox"
        :title="t('crawlQueue.empty.title')"
        :description="t('crawlQueue.empty.body')"
      />
    </div>

    <!-- populated：队列列表 -->
    <ul v-else data-testid="crawl-queue-list" class="divide-y divide-border/40">
      <li
        v-for="item in queueItems"
        :key="item.batch_id"
        data-testid="crawl-queue-item"
        class="px-5 py-3 space-y-2"
      >
        <!-- 第一行：url 集合摘要 + 状态徽标 -->
        <div class="flex items-center justify-between gap-3 flex-wrap">
          <span class="text-sm font-medium truncate max-w-[55%]">
            {{ t('crawlQueue.item.urlSummary', { count: item.url_count }) }}
          </span>
          <Badge
            data-testid="crawl-item-status"
            :variant="STATUS_VARIANT[item.status]"
          >
            <span :class="STATUS_ICON[item.status]" />
            {{ t(`crawlQueue.status.${item.status}`) }}
          </Badge>
        </div>

        <!-- 第二行：进度 + 时间戳 -->
        <div class="flex items-center gap-3 flex-wrap text-xs text-muted-foreground">
          <span>{{ t('crawlQueue.item.progress', { done: item.done, total: item.total }) }}</span>
          <span>{{ t('crawlQueue.item.enqueuedAt', { time: fmtTime(item.started_at) }) }}</span>
          <span>{{ t('crawlQueue.item.updatedAt', { time: fmtTime(item.updated_at) }) }}</span>
        </div>

        <!-- failed：展开后端 error 红字 -->
        <p v-if="item.status === 'failed' && item.error" class="text-xs text-destructive">
          {{ t('crawlQueue.item.error', { message: item.error }) }}
        </p>

        <!-- 行内动作（按 status 条件渲染） -->
        <div class="flex items-center gap-2 flex-wrap">
          <Button
            v-if="canStart(item.status)"
            data-testid="crawl-item-start"
            variant="outline"
            size="sm"
            class="h-8"
            :disabled="isRowBusy(item.batch_id)"
            @click="runAction(item.batch_id, 'start')"
          >
            <span
              v-if="isActing(item.batch_id, 'start')"
              class="icon-[lucide--loader-circle] animate-spin mr-1.5"
            />
            <span v-else class="icon-[lucide--play] mr-1.5" />
            {{ isActing(item.batch_id, 'start') ? t('crawlQueue.actions.starting') : t('crawlQueue.actions.start') }}
          </Button>

          <Button
            v-if="canStop(item.status)"
            data-testid="crawl-item-stop"
            variant="outline"
            size="sm"
            class="h-8 text-destructive hover:text-destructive"
            :disabled="isRowBusy(item.batch_id)"
            @click="runAction(item.batch_id, 'stop')"
          >
            <span
              v-if="isActing(item.batch_id, 'stop')"
              class="icon-[lucide--loader-circle] animate-spin mr-1.5"
            />
            <span v-else class="icon-[lucide--circle-pause] mr-1.5" />
            {{ isActing(item.batch_id, 'stop') ? t('crawlQueue.actions.stopping') : t('crawlQueue.actions.stop') }}
          </Button>

          <Button
            v-if="canRetry(item.status)"
            data-testid="crawl-item-retry"
            variant="outline"
            size="sm"
            class="h-8"
            :disabled="isRowBusy(item.batch_id)"
            @click="runAction(item.batch_id, 'retry')"
          >
            <span
              v-if="isActing(item.batch_id, 'retry')"
              class="icon-[lucide--loader-circle] animate-spin mr-1.5"
            />
            <span v-else class="icon-[lucide--rotate-cw] mr-1.5" />
            {{ isActing(item.batch_id, 'retry') ? t('crawlQueue.actions.retrying') : t('crawlQueue.actions.retry') }}
          </Button>
        </div>
      </li>
    </ul>
  </div>
</template>
