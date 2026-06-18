<script setup lang="ts">
/**
 * /notifications —— 消息中心（通知 + 公告 + 我的反馈统一中心）。
 *
 * Data-Dense Dashboard 风格：分段 Tab（全部 / 通知 / 公告 / 我的反馈，含未读计数）。
 * 消息类 Tab 复用合并 feed（类型语义图标、未读高亮、骨架、空状态）；「我的反馈」Tab
 * 内嵌 FeedbackPanel 主从视图。Tab 与选中项同步到 URL（?tab= & ?fid=）支持深链与刷新保持。
 */
import type { FeedItem } from '~/stores/notifications'
import { useI18n } from 'vue-i18n'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import FeedbackPanel from '~/components/feedback/FeedbackPanel.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { useNotificationsStore } from '~/stores/notifications'

definePage({ meta: { title: '消息中心' } })

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const store = useNotificationsStore()

type Tab = 'all' | 'notification' | 'announcement' | 'feedback'
const tab = ref<Tab>('all')
const unreadOnly = ref(false)

const tabs: { key: Tab, icon: string }[] = [
  { key: 'all', icon: 'icon-[lucide--inbox]' },
  { key: 'notification', icon: 'icon-[lucide--bell]' },
  { key: 'announcement', icon: 'icon-[lucide--megaphone]' },
  { key: 'feedback', icon: 'icon-[lucide--message-square-text]' },
]

const isMessageTab = computed(() => tab.value !== 'feedback')

/** 各消息 Tab 的未读计数（用于角标；反馈不计）。 */
const unreadByTab = computed(() => ({
  all: store.feed.filter(it => !it.is_read).length,
  notification: store.feed.filter(it => it.kind === 'notification' && !it.is_read).length,
  announcement: store.feed.filter(it => it.kind === 'announcement' && !it.is_read).length,
  feedback: 0,
}))

const items = computed<FeedItem[]>(() => {
  if (!isMessageTab.value)
    return []
  let list = store.feed
  if (tab.value !== 'all')
    list = list.filter(it => it.kind === tab.value)
  if (unreadOnly.value)
    list = list.filter(it => !it.is_read)
  return list
})

const feedbackInitialId = ref<string | null>(
  (route.query.fid as string) || (route.query.id as string) || null,
)

/** 类型 → 图标 + 语义色。 */
function visual(item: FeedItem): { icon: string, color: string, bg: string } {
  if (item.kind === 'announcement')
    return { icon: 'icon-[lucide--megaphone]', color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-500/10' }
  switch (item.type) {
    case 'feedback_reply':
      return { icon: 'icon-[lucide--message-circle]', color: 'text-blue-600 dark:text-blue-400', bg: 'bg-blue-500/10' }
    case 'feedback_status':
      return { icon: 'icon-[lucide--activity]', color: 'text-violet-600 dark:text-violet-400', bg: 'bg-violet-500/10' }
    default:
      return { icon: 'icon-[lucide--bell]', color: 'text-slate-600 dark:text-slate-300', bg: 'bg-slate-500/10' }
  }
}

function setTab(next: Tab) {
  tab.value = next
  const query: Record<string, string> = { ...route.query as Record<string, string> }
  if (next === 'all')
    delete query.tab
  else
    query.tab = next
  if (next !== 'feedback')
    delete query.fid
  router.replace({ query })
}

function onFeedbackSelect(id: string | null) {
  const query: Record<string, string> = { ...route.query as Record<string, string> }
  if (id)
    query.fid = id
  else
    delete query.fid
  delete query.id
  router.replace({ query })
}

async function refresh() {
  await store.fetchFeed().catch(() => {})
}

async function onItemClick(item: FeedItem) {
  if (!item.is_read) {
    if (item.kind === 'announcement')
      await store.markAnnouncementRead(item.id).catch(() => {})
    else
      await store.markRead(item.id).catch(() => {})
  }
  if (item.link)
    router.push(item.link)
}

async function onMarkAllRead() {
  await Promise.allSettled([store.markAllRead(), store.markAllAnnouncementsRead()])
}

function formatTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  const diff = Date.now() - date.getTime()
  if (diff < 60_000)
    return t('notifications.justNow')
  if (diff < 3_600_000)
    return t('notifications.center.minutesAgo', { n: Math.floor(diff / 60_000) })
  if (diff < 86_400_000)
    return t('notifications.center.hoursAgo', { n: Math.floor(diff / 3_600_000) })
  if (diff < 7 * 86_400_000)
    return t('notifications.center.daysAgo', { n: Math.floor(diff / 86_400_000) })
  return date.toLocaleDateString()
}

const emptyHint = computed(() => {
  if (unreadOnly.value)
    return t('notifications.center.emptyUnread')
  if (tab.value === 'announcement')
    return t('notifications.center.emptyAnnouncement')
  if (tab.value === 'notification')
    return t('notifications.center.emptyNotification')
  return t('notifications.empty')
})

// 响应 URL 变化（如在消息中心内点击反馈站内信 → 切到反馈 Tab 并选中）
watch(() => route.query.tab, (qTab) => {
  const next: Tab = (qTab === 'notification' || qTab === 'announcement' || qTab === 'feedback')
    ? qTab
    : 'all'
  if (next !== tab.value)
    tab.value = next
})
watch(() => route.query.fid, (fid) => {
  feedbackInitialId.value = (fid as string) || null
})

onMounted(() => {
  const qTab = route.query.tab as string | undefined
  if (qTab === 'notification' || qTab === 'announcement' || qTab === 'feedback')
    tab.value = qTab
  refresh()
})
</script>

<template>
  <PageContainer>
    <!-- 标题区 -->
    <div class="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <span class="icon-[lucide--inbox] text-primary" />
          {{ t('notifications.center.title') }}
          <span
            v-if="store.totalUnread > 0"
            class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-semibold leading-none text-white tabular-nums"
          >
            {{ store.totalUnread > 99 ? '99+' : store.totalUnread }}
          </span>
        </h1>
        <p class="mt-0.5 text-sm text-muted-foreground">
          {{ t('notifications.center.subtitle') }}
        </p>
      </div>
      <Button
        v-if="isMessageTab && store.totalUnread > 0"
        size="sm"
        @click="onMarkAllRead"
      >
        <span class="icon-[lucide--check-check] mr-1.5" />
        {{ t('notifications.markAllRead') }}
      </Button>
    </div>

    <!-- 过滤条：分段 Tab（含计数）+ 仅看未读 -->
    <div class="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-background p-1.5 shadow-sm">
      <div class="flex flex-wrap items-center gap-1">
        <button
          v-for="tb in tabs"
          :key="tb.key"
          type="button"
          class="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-3 text-sm font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          :class="tab === tb.key
            ? 'bg-primary text-primary-foreground shadow-sm'
            : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
          :aria-pressed="tab === tb.key"
          @click="setTab(tb.key)"
        >
          <span :class="tb.icon" />
          {{ t(`notifications.center.tabs.${tb.key}`) }}
          <span
            v-if="unreadByTab[tb.key] > 0"
            class="inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold leading-none tabular-nums"
            :class="tab === tb.key ? 'bg-primary-foreground/20 text-primary-foreground' : 'bg-red-500 text-white'"
          >
            {{ unreadByTab[tb.key] > 99 ? '99+' : unreadByTab[tb.key] }}
          </span>
        </button>
      </div>
      <button
        v-if="isMessageTab"
        type="button"
        class="mr-1 inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-sm transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :class="unreadOnly
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
        :aria-pressed="unreadOnly"
        @click="unreadOnly = !unreadOnly"
      >
        <span :class="unreadOnly ? 'icon-[lucide--check-circle-2]' : 'icon-[lucide--circle]'" />
        {{ t('notifications.center.unreadOnly') }}
      </button>
    </div>

    <!-- 我的反馈 Tab -->
    <FeedbackPanel
      v-if="tab === 'feedback'"
      :initial-id="feedbackInitialId"
      @select="onFeedbackSelect"
    />

    <!-- 消息列表（全部 / 通知 / 公告） -->
    <div v-else class="overflow-hidden rounded-xl border border-border bg-background shadow-sm">
      <!-- 骨架屏 -->
      <div v-if="store.loading">
        <div v-for="i in 5" :key="i" class="flex items-start gap-3 border-b border-border/60 px-4 py-4 last:border-0">
          <div class="h-9 w-9 shrink-0 animate-pulse rounded-full bg-muted" />
          <div class="flex-1 space-y-2">
            <div class="h-4 w-1/3 animate-pulse rounded bg-muted" />
            <div class="h-3 w-2/3 animate-pulse rounded bg-muted" />
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div
        v-else-if="items.length === 0"
        class="flex flex-col items-center justify-center gap-3 px-4 py-20 text-center"
      >
        <div class="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
          <span class="icon-[lucide--bell-off] text-2xl text-muted-foreground" />
        </div>
        <div>
          <p class="text-sm font-medium text-foreground">
            {{ emptyHint }}
          </p>
          <p class="mt-0.5 text-xs text-muted-foreground">
            {{ t('notifications.center.emptyTip') }}
          </p>
        </div>
        <Button v-if="unreadOnly" variant="outline" size="sm" @click="unreadOnly = false">
          {{ t('notifications.center.showAll') }}
        </Button>
      </div>

      <!-- 数据行 -->
      <button
        v-for="item in items"
        v-else
        :key="`${item.kind}-${item.id}`"
        type="button"
        class="group relative flex w-full gap-3 border-b border-border/60 px-4 py-4 text-left transition-colors duration-200 last:border-0 hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        :class="{ 'bg-primary/4': !item.is_read }"
        @click="onItemClick(item)"
      >
        <span
          v-if="!item.is_read"
          class="absolute inset-y-0 left-0 w-0.5 bg-primary"
          aria-hidden="true"
        />
        <span
          class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          :class="visual(item).bg"
        >
          <span class="text-base" :class="[visual(item).icon, visual(item).color]" />
        </span>

        <div class="min-w-0 flex-1">
          <div class="flex items-start justify-between gap-2">
            <p class="flex min-w-0 items-center gap-1.5 text-sm font-medium text-foreground">
              <span class="truncate">{{ item.title }}</span>
              <span
                v-if="!item.is_read"
                class="h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                aria-hidden="true"
              />
            </p>
            <span class="shrink-0 whitespace-nowrap text-[11px] text-muted-foreground tabular-nums">
              {{ formatTime(item.created_at) }}
            </span>
          </div>
          <div v-if="item.body" class="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
            <MarkdownRenderer :content="item.body" />
          </div>
          <span
            v-if="item.link"
            class="mt-1.5 inline-flex items-center gap-0.5 text-[11px] font-medium text-primary opacity-80 transition-opacity group-hover:opacity-100"
          >
            {{ t('notifications.center.viewDetail') }}
            <span class="icon-[lucide--chevron-right] transition-transform group-hover:translate-x-0.5" />
          </span>
        </div>
      </button>
    </div>
  </PageContainer>
</template>
