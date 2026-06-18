<script setup lang="ts">
/**
 * AnnouncementPopup —— 系统公告登录弹窗。
 *
 * 消费 notifications store 的 `popupQueue`（popup 模式 + 未读公告，登录后拉取 / WS 实时推送
 * 时填充）。逐条弹出，markdown 实时渲染；点击「知道了」标记已读并展示下一条。
 * 多条公告时显示进度（如 1/3）。
 */
import { useI18n } from 'vue-i18n'
import MarkdownRenderer from '~/components/execution/MarkdownRenderer.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { useNotificationsStore } from '~/stores/notifications'

const { t } = useI18n()
const router = useRouter()
const store = useNotificationsStore()

const open = ref(false)
const submitting = ref(false)

const current = computed(() => store.popupQueue[0] ?? null)
const total = computed(() => store.popupQueue.length)

watch(
  () => store.popupQueue.length,
  (len) => {
    if (len > 0 && !open.value)
      open.value = true
    if (len === 0)
      open.value = false
  },
)

async function acknowledge() {
  const item = current.value
  if (!item)
    return
  submitting.value = true
  try {
    await store.markAnnouncementRead(item.id)
  }
  finally {
    submitting.value = false
  }
}

async function viewDetail() {
  const item = current.value
  if (!item)
    return
  const link = item.link
  await acknowledge()
  if (link)
    router.push(link)
}

// 禁止点击遮罩/Esc 关闭：必须显式「知道了」（确保已读落库）
function onOpenChange(value: boolean) {
  if (!value && store.popupQueue.length > 0)
    return
  open.value = value
}
</script>

<template>
  <Dialog :open="open" @update:open="onOpenChange">
    <DialogContent
      class="max-w-lg gap-0 overflow-hidden p-0"
      @escape-key-down.prevent
      @pointer-down-outside.prevent
      @interact-outside.prevent
    >
      <!-- 顶部强调条 -->
      <div class="h-1 w-full bg-linear-to-r from-amber-400 to-amber-600" aria-hidden="true" />

      <DialogHeader class="space-y-0 px-6 pb-3 pt-5 text-left">
        <div class="flex items-start gap-3">
          <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-amber-500/15">
            <span class="icon-[lucide--megaphone] text-xl text-amber-600 dark:text-amber-400" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="text-[11px] font-medium uppercase tracking-wide text-amber-600 dark:text-amber-400">
                {{ t('notifications.announcementTag') }}
              </span>
              <span
                v-if="total > 1"
                class="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground tabular-nums"
              >
                {{ t('announcements.popup.remaining', { count: total }) }}
              </span>
            </div>
            <DialogTitle class="mt-1 text-base leading-snug">
              {{ current?.title }}
            </DialogTitle>
          </div>
        </div>
      </DialogHeader>

      <div class="max-h-[55vh] overflow-y-auto px-6 pb-2 text-sm leading-relaxed text-foreground/90">
        <MarkdownRenderer v-if="current?.body" :content="current.body" />
      </div>

      <DialogFooter class="gap-2 border-t border-border/60 bg-muted/30 px-6 py-3">
        <Button
          v-if="current?.link"
          variant="outline"
          :disabled="submitting"
          @click="viewDetail"
        >
          {{ t('announcements.popup.viewDetail') }}
        </Button>
        <Button :disabled="submitting" @click="acknowledge">
          <span v-if="total > 1" class="icon-[lucide--arrow-right] mr-1.5" />
          <span v-else class="icon-[lucide--check] mr-1.5" />
          {{ total > 1 ? t('announcements.popup.next') : t('announcements.popup.gotIt') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
