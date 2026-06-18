<script setup lang="ts">
/**
 * FeedbackPanel —— 「我的反馈」主从视图（列表 + 详情 + 提交）。
 *
 * 内嵌于消息中心「我的反馈」Tab，复用反馈状态/分类视觉。支持 initialId 深链选中，
 * 选中变化时 emit('select') 由父级同步 URL；内置提交弹窗，提交后自动刷新列表。
 */
import type { Feedback } from '~/types/feedback'
import { useI18n } from 'vue-i18n'
import { feedbackApi } from '~/api/feedback'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import FeedbackDialog from '~/components/feedback/FeedbackDialog.vue'
import {
  categoryColorClass,
  categoryIconClass,
  statusBadgeClass,
  statusDotClass,
} from '~/components/feedback/feedbackStyles'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'

const props = defineProps<{ initialId?: string | null }>()
const emit = defineEmits<{ select: [id: string | null] }>()

const { t } = useI18n()

const list = ref<Feedback[]>([])
const loading = ref(false)
const selected = ref<Feedback | null>(null)
const detailLoading = ref(false)
const dialogOpen = ref(false)

async function fetchList() {
  loading.value = true
  try {
    const resp = await feedbackApi.list({ limit: 50 })
    list.value = resp.items
  }
  finally {
    loading.value = false
  }
}

async function select(id: string) {
  detailLoading.value = true
  try {
    selected.value = await feedbackApi.detail(id)
    emit('select', id)
  }
  finally {
    detailLoading.value = false
  }
}

function attachmentSrc(url?: string): string {
  return url || ''
}

function initial(name: string): string {
  return (name?.trim()?.[0] || '?').toUpperCase()
}

function relTime(iso: string): string {
  if (!iso)
    return ''
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000)
    return t('notifications.justNow')
  if (diff < 3_600_000)
    return t('notifications.center.minutesAgo', { n: Math.floor(diff / 60_000) })
  if (diff < 86_400_000)
    return t('notifications.center.hoursAgo', { n: Math.floor(diff / 3_600_000) })
  if (diff < 7 * 86_400_000)
    return t('notifications.center.daysAgo', { n: Math.floor(diff / 86_400_000) })
  return new Date(iso).toLocaleDateString()
}

// 提交弹窗关闭后刷新列表（捕获新提交）
watch(dialogOpen, (open, prev) => {
  if (prev && !open)
    fetchList()
})

// 外部深链变化（如点击反馈站内信）→ 重新选中
watch(() => props.initialId, (id) => {
  if (id && id !== selected.value?.id)
    select(id).catch(() => {})
})

onMounted(async () => {
  await fetchList()
  if (props.initialId)
    await select(props.initialId).catch(() => {})
})
</script>

<template>
  <div class="grid grid-cols-1 gap-4 lg:grid-cols-[340px_1fr]">
    <!-- 列表 -->
    <div class="flex max-h-[72vh] flex-col overflow-hidden rounded-xl border border-border bg-background shadow-sm">
      <div class="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div class="flex items-center gap-2">
          <span class="text-sm font-semibold">{{ t('feedback.myFeedback') }}</span>
          <span
            v-if="list.length"
            class="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground tabular-nums"
          >
            {{ list.length }}
          </span>
        </div>
        <Button size="sm" class="h-7 px-2" @click="dialogOpen = true">
          <span class="icon-[lucide--plus] mr-1" />
          {{ t('feedback.submit') }}
        </Button>
      </div>

      <!-- 骨架 -->
      <div v-if="loading" class="flex-1 overflow-hidden">
        <div v-for="i in 5" :key="i" class="flex flex-col gap-2 border-b border-border/60 px-4 py-3 last:border-0">
          <div class="h-4 w-2/3 animate-pulse rounded bg-muted" />
          <div class="h-3 w-1/2 animate-pulse rounded bg-muted" />
        </div>
      </div>

      <!-- 空 -->
      <div
        v-else-if="list.length === 0"
        class="flex flex-1 flex-col items-center justify-center gap-3 px-4 py-12 text-center"
      >
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <span class="icon-[lucide--message-square-text] text-xl text-muted-foreground" />
        </div>
        <p class="text-sm text-muted-foreground">
          {{ t('feedback.noFeedback') }}
        </p>
        <Button variant="outline" size="sm" @click="dialogOpen = true">
          <span class="icon-[lucide--plus] mr-1.5" />
          {{ t('feedback.submit') }}
        </Button>
      </div>

      <!-- 列表项 -->
      <div v-else class="flex-1 overflow-y-auto">
        <button
          v-for="item in list"
          :key="item.id"
          type="button"
          class="group relative flex w-full gap-3 border-b border-border/60 px-4 py-3 text-left transition-colors duration-200 last:border-0 hover:bg-muted/40 focus-visible:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          :class="{ 'bg-primary/5': selected?.id === item.id }"
          @click="select(item.id)"
        >
          <span
            v-if="selected?.id === item.id"
            class="absolute inset-y-0 left-0 w-0.5 bg-primary"
            aria-hidden="true"
          />
          <span class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
            <span class="text-sm" :class="[categoryIconClass(item.category), categoryColorClass(item.category)]" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-2">
              <span class="truncate text-sm font-medium text-foreground">
                {{ item.title || item.content.slice(0, 30) }}
              </span>
              <span
                class="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[10px] font-medium ring-1 ring-inset"
                :class="statusBadgeClass(item.status)"
              >
                <span class="h-1.5 w-1.5 rounded-full" :class="statusDotClass(item.status)" />
                {{ item.status_label }}
              </span>
            </div>
            <div class="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span>{{ item.category_label }}</span>
              <span class="opacity-50">·</span>
              <span class="tabular-nums">{{ relTime(item.created_at) }}</span>
              <span v-if="item.replies.length" class="ml-auto inline-flex items-center gap-0.5">
                <span class="icon-[lucide--message-circle]" />{{ item.replies.length }}
              </span>
            </div>
          </div>
        </button>
      </div>
    </div>

    <!-- 详情 -->
    <div class="min-h-[320px] rounded-xl border border-border bg-background p-5 shadow-sm">
      <!-- 未选中 -->
      <div v-if="!selected && !detailLoading" class="flex h-full min-h-[280px] flex-col items-center justify-center gap-3 text-center">
        <div class="flex h-14 w-14 items-center justify-center rounded-full bg-muted">
          <span class="icon-[lucide--inbox] text-2xl text-muted-foreground" />
        </div>
        <div>
          <p class="text-sm font-medium text-foreground">
            {{ t('feedback.selectToView') }}
          </p>
          <p class="mt-0.5 text-xs text-muted-foreground">
            {{ t('feedback.selectToViewTip') }}
          </p>
        </div>
      </div>

      <!-- 详情加载骨架 -->
      <div v-else-if="detailLoading" class="space-y-3">
        <div class="h-6 w-1/2 animate-pulse rounded bg-muted" />
        <div class="h-3 w-1/3 animate-pulse rounded bg-muted" />
        <div class="mt-4 h-24 w-full animate-pulse rounded bg-muted" />
      </div>

      <template v-else-if="selected">
        <div class="mb-3 flex items-start justify-between gap-2">
          <h2 class="text-lg font-semibold leading-snug">
            {{ selected.title || t('feedback.content') }}
          </h2>
          <span
            class="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset"
            :class="statusBadgeClass(selected.status)"
          >
            <span class="h-1.5 w-1.5 rounded-full" :class="statusDotClass(selected.status)" />
            {{ selected.status_label }}
          </span>
        </div>
        <div class="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted-foreground">
          <span class="inline-flex items-center gap-1.5 font-medium">
            <span :class="[categoryIconClass(selected.category), categoryColorClass(selected.category)]" class="text-sm" />
            {{ selected.category_label }}
          </span>
          <span class="inline-flex items-center gap-1 tabular-nums">
            <span class="icon-[lucide--clock] opacity-70" />{{ new Date(selected.created_at).toLocaleString() }}
          </span>
        </div>

        <MarkdownRenderer :content="selected.content" class="mb-4" />

        <!-- 附件 -->
        <div v-if="selected.attachments.length" class="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-4">
          <template v-for="(att, idx) in selected.attachments" :key="idx">
            <a
              v-if="att.kind === 'image'"
              :href="attachmentSrc(att.url)"
              target="_blank"
              class="block aspect-square overflow-hidden rounded-lg border border-border transition-transform duration-200 hover:scale-[1.02] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <img :src="attachmentSrc(att.url)" :alt="att.name || t('feedback.attachment')" class="h-full w-full object-cover" loading="lazy">
            </a>
            <video
              v-else
              :src="attachmentSrc(att.url)"
              controls
              class="aspect-square w-full rounded-lg border border-border object-cover"
            />
          </template>
        </div>

        <!-- 处理记录 -->
        <div class="border-t border-border pt-4">
          <h3 class="mb-3 flex items-center gap-1.5 text-sm font-semibold">
            <span class="icon-[lucide--messages-square] text-muted-foreground" />
            {{ t('feedback.admin.replies') }}
            <span v-if="selected.replies.length" class="rounded-full bg-muted px-1.5 text-[11px] font-normal text-muted-foreground tabular-nums">
              {{ selected.replies.length }}
            </span>
          </h3>
          <div
            v-if="selected.replies.length === 0"
            class="rounded-lg border border-dashed border-border px-3 py-6 text-center text-sm text-muted-foreground"
          >
            {{ t('feedback.admin.noReplies') }}
          </div>
          <div v-else class="space-y-3">
            <div
              v-for="reply in selected.replies"
              :key="reply.id"
              class="flex gap-2.5"
            >
              <span
                class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
                :class="reply.is_admin ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'"
              >
                {{ reply.is_admin ? '官' : initial(reply.author_name) }}
              </span>
              <div
                class="min-w-0 flex-1 rounded-lg px-3 py-2"
                :class="reply.is_admin ? 'bg-primary/5 ring-1 ring-inset ring-primary/10' : 'bg-muted/40'"
              >
                <div class="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                  <Badge v-if="reply.is_admin" variant="default" class="h-4 px-1.5 text-[10px]">
                    {{ t('feedback.official') }}
                  </Badge>
                  <span class="font-medium text-foreground/80">{{ reply.author_name }}</span>
                  <span class="tabular-nums">{{ relTime(reply.created_at) }}</span>
                </div>
                <MarkdownRenderer :content="reply.content" />
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <FeedbackDialog v-model:open="dialogOpen" />
  </div>
</template>
