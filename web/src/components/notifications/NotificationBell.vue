<script setup lang="ts">
/**
 * NotificationBell —— 顶部站内信通知铃铛（右上角弹窗）。
 *
 * 展示合计未读角标，点击弹出「通知 + 公告」合并列表（markdown 实时渲染、类型语义图标）。
 * 点击单条标记已读并按 link 跳转；底部跳转消息中心。
 */
import type { FeedItem } from '~/stores/notifications'
import { useI18n } from 'vue-i18n'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover'
import { useNotificationsStore } from '~/stores/notifications'

const { t } = useI18n()
const router = useRouter()
const store = useNotificationsStore()

const open = ref(false)

const badge = computed(() => (store.totalUnread > 99 ? '99+' : String(store.totalUnread)))
const recent = computed(() => store.feed.slice(0, 12))

watch(open, (isOpen) => {
  if (isOpen)
    store.fetchFeed().catch(() => {})
})

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

async function onItemClick(item: FeedItem) {
  if (!item.is_read) {
    if (item.kind === 'announcement')
      await store.markAnnouncementRead(item.id).catch(() => {})
    else
      await store.markRead(item.id).catch(() => {})
  }
  open.value = false
  if (item.link)
    router.push(item.link)
}

async function onMarkAllRead() {
  await Promise.allSettled([
    store.markAllRead(),
    store.markAllAnnouncementsRead(),
  ])
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
  return date.toLocaleDateString()
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <button
        type="button"
        class="relative flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-colors duration-200 hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :class="{ 'bg-muted/60 text-foreground': open }"
        :aria-label="t('notifications.bellAria')"
      >
        <span class="icon-[lucide--bell] text-lg" />
        <span
          v-if="store.totalUnread > 0"
          class="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-semibold leading-none text-white ring-2 ring-background"
        >
          {{ badge }}
        </span>
      </button>
    </PopoverTrigger>

    <PopoverContent align="end" :side-offset="8" class="w-[380px] overflow-hidden p-0">
      <!-- 头部 -->
      <div class="flex items-center justify-between border-b border-border px-4 py-3">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold">{{ t('notifications.title') }}</span>
          <span
            v-if="store.totalUnread > 0"
            class="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1.5 text-[11px] font-semibold leading-none text-white tabular-nums"
          >
            {{ badge }}
          </span>
        </div>
        <button
          v-if="store.totalUnread > 0"
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="onMarkAllRead"
        >
          <span class="icon-[lucide--check-check] text-sm" />
          {{ t('notifications.markAllRead') }}
        </button>
      </div>

      <!-- 列表 -->
      <div class="max-h-[420px] overflow-y-auto">
        <!-- 骨架屏 -->
        <div v-if="store.loading">
          <div v-for="i in 4" :key="i" class="flex items-start gap-2.5 border-b border-border/60 px-4 py-3 last:border-0">
            <div class="h-8 w-8 shrink-0 animate-pulse rounded-full bg-muted" />
            <div class="flex-1 space-y-2 py-0.5">
              <div class="h-3.5 w-1/2 animate-pulse rounded bg-muted" />
              <div class="h-3 w-3/4 animate-pulse rounded bg-muted" />
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-else-if="recent.length === 0"
          class="flex flex-col items-center justify-center gap-2 px-4 py-12 text-center"
        >
          <div class="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
            <span class="icon-[lucide--bell-off] text-xl text-muted-foreground" />
          </div>
          <p class="text-sm text-muted-foreground">
            {{ t('notifications.empty') }}
          </p>
        </div>

        <!-- 数据行 -->
        <button
          v-for="item in recent"
          v-else
          :key="`${item.kind}-${item.id}`"
          type="button"
          class="group relative flex w-full gap-2.5 border-b border-border/60 px-4 py-3 text-left transition-colors duration-200 last:border-0 hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          :class="{ 'bg-primary/4': !item.is_read }"
          @click="onItemClick(item)"
        >
          <span
            v-if="!item.is_read"
            class="absolute inset-y-0 left-0 w-0.5 bg-primary"
            aria-hidden="true"
          />
          <span
            class="flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
            :class="visual(item).bg"
          >
            <span class="text-sm" :class="[visual(item).icon, visual(item).color]" />
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
            <div v-if="item.body" class="mt-0.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
              <MarkdownRenderer :content="item.body" />
            </div>
          </div>
        </button>
      </div>

      <!-- 底部 -->
      <div class="border-t border-border p-1.5">
        <RouterLink
          to="/notifications"
          class="flex items-center justify-center gap-1 rounded-md py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          @click="open = false"
        >
          {{ t('notifications.viewAll') }}
          <span class="icon-[lucide--arrow-right] text-sm" />
        </RouterLink>
      </div>
    </PopoverContent>
  </Popover>
</template>
