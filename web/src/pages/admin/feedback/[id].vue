<script setup lang="ts">
/**
 * /admin/feedback/:id —— 反馈详情处理（仅超级管理员）。
 *
 * 展示反馈正文/附件/上下文/处理记录；支持 Markdown 回复（触发站内信）与状态变更。
 */
import type { Feedback, FeedbackStatus } from '~/types/feedback'
import { useI18n } from 'vue-i18n'
import { feedbackApi } from '~/api/feedback'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import {
  categoryColorClass,
  categoryIconClass,
  statusBadgeClass,
  statusDotClass,
} from '~/components/feedback/feedbackStyles'
import MarkdownField from '~/components/feedback/MarkdownField.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import { useToast } from '~/composables/useToast'

definePage({ meta: { requiresAdmin: true, title: '反馈详情' } })

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const toast = useToast()

const feedbackId = computed(() => (route.params as { id: string }).id)
const feedback = ref<Feedback | null>(null)
const loading = ref(false)
const replyContent = ref('')
const replying = ref(false)
const updatingStatus = ref(false)

const statusOptions: FeedbackStatus[] = ['open', 'in_progress', 'resolved', 'closed', 'wont_fix']

async function fetchDetail() {
  loading.value = true
  try {
    feedback.value = await feedbackApi.adminDetail(feedbackId.value)
  }
  finally {
    loading.value = false
  }
}

async function sendReply() {
  if (!replyContent.value.trim())
    return
  replying.value = true
  try {
    feedback.value = await feedbackApi.adminReply(feedbackId.value, replyContent.value.trim())
    replyContent.value = ''
    toast.success(t('feedback.admin.replySuccess'))
  }
  catch (err: any) {
    toast.error(err?.detail || t('feedback.admin.replyError'))
  }
  finally {
    replying.value = false
  }
}

async function changeStatus(status: FeedbackStatus) {
  if (feedback.value?.status === status)
    return
  updatingStatus.value = true
  try {
    feedback.value = await feedbackApi.adminUpdateStatus(feedbackId.value, status, true)
    toast.success(t('feedback.admin.statusUpdated'))
  }
  catch (err: any) {
    toast.error(err?.detail || t('feedback.admin.statusError'))
  }
  finally {
    updatingStatus.value = false
  }
}

onMounted(fetchDetail)
</script>

<template>
  <PageContainer>
    <Button variant="ghost" size="sm" class="mb-3" @click="router.push('/admin/feedback')">
      <span class="icon-[lucide--arrow-left] mr-1.5" />
      {{ t('feedback.admin.backToList') }}
    </Button>

    <div v-if="loading" class="py-12 text-center text-sm text-muted-foreground">
      {{ t('feedback.admin.loading') }}
    </div>

    <div v-else-if="feedback" class="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
      <!-- 主体 -->
      <div class="space-y-4">
        <div class="rounded-xl border border-border bg-background p-5">
          <div class="mb-3 flex items-center justify-between gap-2">
            <h1 class="text-lg font-semibold">
              {{ feedback.title || t('feedback.content') }}
            </h1>
            <span
              class="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset"
              :class="statusBadgeClass(feedback.status)"
            >
              <span class="h-1.5 w-1.5 rounded-full" :class="statusDotClass(feedback.status)" />
              {{ feedback.status_label }}
            </span>
          </div>
          <div class="mb-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <span class="inline-flex items-center gap-1.5 font-medium">
              <span :class="[categoryIconClass(feedback.category), categoryColorClass(feedback.category)]" class="text-sm" />
              {{ feedback.category_label }}
            </span>
            <span class="inline-flex items-center gap-1">
              <span class="icon-[lucide--user] opacity-70" />{{ feedback.created_by_name }}
            </span>
            <span class="inline-flex items-center gap-1 tabular-nums">
              <span class="icon-[lucide--clock] opacity-70" />{{ new Date(feedback.created_at).toLocaleString() }}
            </span>
          </div>

          <MarkdownRenderer :content="feedback.content" />

          <div v-if="feedback.attachments.length" class="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-4">
            <template v-for="(att, idx) in feedback.attachments" :key="idx">
              <a
                v-if="att.kind === 'image'"
                :href="att.url"
                target="_blank"
                class="block aspect-square overflow-hidden rounded-lg border border-border"
              >
                <img :src="att.url" :alt="att.name" class="h-full w-full object-cover">
              </a>
              <video
                v-else
                :src="att.url"
                controls
                class="aspect-square w-full rounded-lg border border-border object-cover"
              />
            </template>
          </div>
        </div>

        <!-- 处理记录 -->
        <div class="rounded-xl border border-border bg-background p-5">
          <h3 class="mb-3 text-sm font-semibold">
            {{ t('feedback.admin.replies') }}
          </h3>
          <div v-if="feedback.replies.length === 0" class="text-sm text-muted-foreground">
            {{ t('feedback.admin.noReplies') }}
          </div>
          <div v-else class="space-y-3">
            <div
              v-for="reply in feedback.replies"
              :key="reply.id"
              class="rounded-lg px-3 py-2"
              :class="reply.is_admin ? 'bg-primary/5' : 'bg-muted/40'"
            >
              <div class="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
                <Badge v-if="reply.is_admin" variant="default" class="h-4 px-1.5 text-[10px]">
                  官方
                </Badge>
                <span>{{ reply.author_name }}</span>
                <span>{{ new Date(reply.created_at).toLocaleString() }}</span>
              </div>
              <MarkdownRenderer :content="reply.content" />
            </div>
          </div>

          <!-- 回复输入 -->
          <div class="mt-4 space-y-2 border-t border-border pt-4">
            <label class="text-sm font-medium">{{ t('feedback.admin.replyLabel') }}</label>
            <MarkdownField v-model="replyContent" :placeholder="t('feedback.admin.replyPlaceholder')" />
            <div class="flex justify-end">
              <Button :disabled="replying || !replyContent.trim()" @click="sendReply">
                <span v-if="replying" class="icon-[lucide--loader-circle] mr-1.5 animate-spin" />
                {{ t('feedback.admin.sendReply') }}
              </Button>
            </div>
          </div>
        </div>
      </div>

      <!-- 侧栏：状态 + 上下文 -->
      <div class="space-y-4">
        <div class="rounded-xl border border-border bg-background p-4">
          <h3 class="mb-3 text-sm font-semibold">
            {{ t('feedback.admin.changeStatus') }}
          </h3>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="s in statusOptions"
              :key="s"
              type="button"
              :disabled="updatingStatus"
              class="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              :class="feedback.status === s
                ? `border-transparent ring-1 ring-inset ${statusBadgeClass(s)}`
                : 'border-border text-muted-foreground hover:bg-muted hover:text-foreground'"
              @click="changeStatus(s)"
            >
              <span class="h-1.5 w-1.5 rounded-full" :class="statusDotClass(s)" />
              {{ t(`feedback.status.${s}`) }}
            </button>
          </div>
        </div>

        <div class="rounded-xl border border-border bg-background p-4 text-xs">
          <h3 class="mb-2 text-sm font-semibold">
            {{ t('feedback.admin.context') }}
          </h3>
          <div class="space-y-2 text-muted-foreground">
            <div class="break-all">
              <span class="icon-[lucide--link] mr-1 align-middle" />
              {{ feedback.page_url || '/' }}
            </div>
            <div v-if="feedback.conversation_id">
              <RouterLink
                :to="`/chat?conversation=${feedback.conversation_id}`"
                class="text-primary hover:underline"
              >
                <span class="icon-[lucide--message-circle] mr-1 align-middle" />
                {{ t('feedback.admin.openConversation') }}
              </RouterLink>
            </div>
          </div>
        </div>
      </div>
    </div>
  </PageContainer>
</template>
