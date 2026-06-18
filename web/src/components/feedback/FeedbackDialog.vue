<script setup lang="ts">
/**
 * FeedbackDialog —— 用户反馈提交弹窗。
 *
 * 分类 + 标题 + Markdown 正文（编辑/预览）+ 图片/视频附件（粘贴/拖拽/选择上传）。
 * 提交时自动采集当前页面 route.fullPath，以及（若在 AI 对话页）关联的 conversation_id
 * 与最后一条 message_id。
 */
import type { FeedbackCategory } from '~/types/feedback'
import { useI18n } from 'vue-i18n'
import { feedbackApi } from '~/api/feedback'
import MarkdownField from '~/components/feedback/MarkdownField.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useToast } from '~/composables/useToast'
import { useChatStore } from '~/stores/chat'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const { t } = useI18n()
const toast = useToast()
const route = useRoute()
const chatStore = useChatStore()

const IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])
const VIDEO_TYPES = new Set(['video/mp4', 'video/webm'])
const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const MAX_VIDEO_BYTES = 50 * 1024 * 1024
const MAX_ATTACHMENTS = 9

interface PendingAttachment {
  id: string
  kind: 'image' | 'video'
  name: string
  previewUrl: string
  status: 'uploading' | 'ready' | 'error'
  storageRef?: string
  url?: string
  mime?: string
  size?: number
}

const category = ref<FeedbackCategory>('bug')
const title = ref('')
const content = ref('')
const attachments = ref<PendingAttachment[]>([])
const submitting = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

// 提交上下文（弹窗打开时快照）
const pageUrl = ref('')
const conversationId = ref<string | null>(null)
const messageId = ref<string | null>(null)

const isOpen = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

const categoryOptions: { value: FeedbackCategory, labelKey: string }[] = [
  { value: 'bug', labelKey: 'feedback.categories.bug' },
  { value: 'question', labelKey: 'feedback.categories.question' },
  { value: 'feature', labelKey: 'feedback.categories.feature' },
  { value: 'other', labelKey: 'feedback.categories.other' },
]

const hasUploading = computed(() => attachments.value.some(a => a.status === 'uploading'))

function captureContext() {
  pageUrl.value = route.fullPath
  if (route.path === '/chat') {
    conversationId.value = chatStore.currentConversationId ?? null
    try {
      const msgs = (chatStore as any).messages
      const list = Array.isArray(msgs?.value) ? msgs.value : Array.isArray(msgs) ? msgs : []
      messageId.value = list.length ? list[list.length - 1]?.id ?? null : null
    }
    catch {
      messageId.value = null
    }
  }
  else {
    conversationId.value = null
    messageId.value = null
  }
}

function resetForm() {
  for (const a of attachments.value)
    URL.revokeObjectURL(a.previewUrl)
  category.value = 'bug'
  title.value = ''
  content.value = ''
  attachments.value = []
}

watch(isOpen, (open) => {
  if (open)
    captureContext()
})

function classifyFile(file: File): 'image' | 'video' | null {
  if (IMAGE_TYPES.has(file.type))
    return 'image'
  if (VIDEO_TYPES.has(file.type))
    return 'video'
  return null
}

async function uploadOne(entry: PendingAttachment, file: File) {
  try {
    const res = await feedbackApi.uploadAttachment(file)
    entry.status = 'ready'
    entry.storageRef = res.storage_ref
    entry.url = res.url
    entry.mime = res.mime
    entry.size = res.size
    entry.kind = res.kind
  }
  catch (err: any) {
    entry.status = 'error'
    toast.error(err?.detail || t('feedback.submitError'))
    attachments.value = attachments.value.filter(a => a.id !== entry.id)
    URL.revokeObjectURL(entry.previewUrl)
  }
}

function addFiles(files: File[]) {
  for (const file of files) {
    if (attachments.value.length >= MAX_ATTACHMENTS) {
      toast.warning(t('feedback.tooManyAttachments'))
      break
    }
    const kind = classifyFile(file)
    if (!kind) {
      toast.error(t('feedback.unsupportedType'))
      continue
    }
    if (kind === 'image' && file.size > MAX_IMAGE_BYTES) {
      toast.error(t('feedback.imageTooLarge'))
      continue
    }
    if (kind === 'video' && file.size > MAX_VIDEO_BYTES) {
      toast.error(t('feedback.videoTooLarge'))
      continue
    }
    const entry: PendingAttachment = {
      id: crypto.randomUUID(),
      kind,
      name: file.name,
      previewUrl: URL.createObjectURL(file),
      status: 'uploading',
    }
    attachments.value.push(entry)
    uploadOne(entry, file)
  }
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || [])
  const media = files.filter(f => f.type.startsWith('image/') || f.type.startsWith('video/'))
  if (media.length === 0)
    return
  event.preventDefault()
  addFiles(media)
}

function handleDrop(event: DragEvent) {
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length)
    addFiles(files)
}

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files)
    addFiles(Array.from(input.files))
  if (fileInput.value)
    fileInput.value.value = ''
}

function removeAttachment(id: string) {
  const item = attachments.value.find(a => a.id === id)
  if (item)
    URL.revokeObjectURL(item.previewUrl)
  attachments.value = attachments.value.filter(a => a.id !== id)
}

async function submit() {
  if (!content.value.trim()) {
    toast.warning(t('feedback.contentRequired'))
    return
  }
  if (hasUploading.value) {
    toast.warning(t('feedback.waitUpload'))
    return
  }
  submitting.value = true
  try {
    await feedbackApi.create({
      category: category.value,
      title: title.value.trim(),
      content: content.value.trim(),
      attachments: attachments.value
        .filter(a => a.status === 'ready' && a.storageRef)
        .map(a => ({
          storage_ref: a.storageRef!,
          kind: a.kind,
          name: a.name,
          size: a.size,
          mime: a.mime,
          url: a.url,
        })),
      page_url: pageUrl.value,
      conversation_id: conversationId.value,
      message_id: messageId.value,
    })
    toast.success(t('feedback.submitSuccess'))
    resetForm()
    isOpen.value = false
  }
  catch (err: any) {
    toast.error(err?.detail || t('feedback.submitError'))
  }
  finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => {
  for (const a of attachments.value)
    URL.revokeObjectURL(a.previewUrl)
})
</script>

<template>
  <Dialog v-model:open="isOpen">
    <DialogContent class="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{{ t('feedback.dialogTitle') }}</DialogTitle>
        <DialogDescription>{{ t('feedback.dialogDescription') }}</DialogDescription>
      </DialogHeader>

      <div class="space-y-4 py-2">
        <!-- 类型 -->
        <div class="space-y-2">
          <Label>{{ t('feedback.category') }}</Label>
          <Select v-model="category">
            <SelectTrigger class="w-full">
              <SelectValue :placeholder="t('feedback.categoryPlaceholder')" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="opt in categoryOptions" :key="opt.value" :value="opt.value">
                {{ t(opt.labelKey) }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        <!-- 标题 -->
        <div class="space-y-2">
          <Label>{{ t('feedback.title') }}</Label>
          <Input v-model="title" :placeholder="t('feedback.titlePlaceholder')" />
        </div>

        <!-- 正文 -->
        <div class="space-y-2">
          <Label>{{ t('feedback.content') }}</Label>
          <MarkdownField
            v-model="content"
            :placeholder="t('feedback.contentPlaceholder')"
            @paste="handlePaste"
            @drop="handleDrop"
          />
        </div>

        <!-- 附件 -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <Label>{{ t('feedback.attachments') }}</Label>
            <Button type="button" variant="outline" size="sm" @click="fileInput?.click()">
              <span class="icon-[lucide--paperclip] mr-1.5 text-sm" />
              {{ t('feedback.addAttachment') }}
            </Button>
            <input
              ref="fileInput"
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm"
              multiple
              class="hidden"
              @change="handleFileSelect"
            >
          </div>
          <p class="text-xs text-muted-foreground">
            {{ t('feedback.attachmentHint') }}
          </p>

          <div v-if="attachments.length" class="grid grid-cols-3 gap-2 sm:grid-cols-4">
            <div
              v-for="a in attachments"
              :key="a.id"
              class="group relative aspect-square overflow-hidden rounded-lg border border-border bg-muted/30"
            >
              <img
                v-if="a.kind === 'image'"
                :src="a.previewUrl"
                :alt="a.name"
                class="h-full w-full object-cover"
              >
              <video v-else :src="a.previewUrl" class="h-full w-full object-cover" muted />

              <div
                v-if="a.status === 'uploading'"
                class="absolute inset-0 flex items-center justify-center bg-black/40 text-xs text-white"
              >
                <span class="icon-[lucide--loader-circle] mr-1 animate-spin" />
                {{ t('feedback.uploading') }}
              </div>

              <button
                type="button"
                class="absolute right-1 top-1 hidden rounded-full bg-black/60 p-1 text-white group-hover:block"
                @click="removeAttachment(a.id)"
              >
                <span class="icon-[lucide--x] text-xs" />
              </button>

              <span
                v-if="a.kind === 'video'"
                class="absolute bottom-1 left-1 rounded bg-black/60 px-1 text-[10px] text-white"
              >
                <span class="icon-[lucide--video] align-middle" />
              </span>
            </div>
          </div>
        </div>

        <!-- 上下文提示 -->
        <div class="rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground space-y-1">
          <div class="truncate">
            <span class="icon-[lucide--link] mr-1 align-middle" />
            {{ t('feedback.contextPage') }}：{{ pageUrl || '/' }}
          </div>
          <div v-if="conversationId" class="truncate">
            <span class="icon-[lucide--message-circle] mr-1 align-middle" />
            {{ t('feedback.contextConversation') }}：{{ conversationId }}
          </div>
        </div>
      </div>

      <DialogFooter>
        <Button variant="outline" :disabled="submitting" @click="isOpen = false">
          {{ t('feedback.cancel') }}
        </Button>
        <Button :disabled="submitting || hasUploading" @click="submit">
          <span v-if="submitting" class="icon-[lucide--loader-circle] mr-1.5 animate-spin" />
          {{ submitting ? t('feedback.submitting') : t('feedback.submit') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
