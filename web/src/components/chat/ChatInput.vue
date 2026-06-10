<script setup lang="ts">
import type { ConversationStatus } from '~/composables/useConversationFrozen'
import type { ImagePart } from '~/types/chat'
import type { AvailableModel, ProviderCredentialDto } from '~/types/providerCredential'
import { uploadChatImage } from '~/api/chat'
import PinConfirmDialog from '~/components/chat/PinConfirmDialog.vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { extractFirstFeishuDocId } from '~/composables/useFeishuDocDetect'
import { useToast } from '~/composables/useToast'
import { randomUUID } from '~/utils/uuid'

const emit = defineEmits<{
  'pin-confirmed': [credentialId: string, model: string]
}>()
const chatStore = useChatStore()
const toast = useToast()

const inputContent = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

const showModelMenu = ref(false)

const MAX_IMAGES_PER_MESSAGE = 4
const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const SUPPORTED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp'])

interface PendingImage {
  id: string
  file: File
  previewUrl: string
  status: 'ready' | 'uploading' | 'error'
  error?: string
}

const pendingImages = ref<PendingImage[]>([])
const isUploadingImages = ref(false)

// ============================================================================
// prefilled_query 自动填充（D-16 Playground → Chat 联动）
// XSS 防御（T-249-13）：仅填充到 inputContent（v-model textarea），不使用 innerHTML 或 v-html
// ============================================================================
const route = useRoute()

watch(
  () => route.query.prefilled_query,
  (prefilled) => {
    if (prefilled && typeof prefilled === 'string') {
      try {
        inputContent.value = decodeURIComponent(prefilled)
      }
      catch {
        // URL 解码失败静默忽略（异常格式 URL，如 %zz）
      }
    }
  },
  { immediate: true },
)

// 欢迎页快捷提示 → 填充输入框并聚焦（填充而非直发，给用户修改机会）
watch(
  () => chatStore.draftPrompt,
  (draft) => {
    if (!draft)
      return
    inputContent.value = draft
    chatStore.draftPrompt = null
    nextTick(() => {
      autoResize()
      const el = textarea.value
      if (el) {
        el.focus()
        el.setSelectionRange(el.value.length, el.value.length)
      }
    })
  },
)
const modelMenuRef = ref<HTMLElement | null>(null)

// ============================================================================
// ：model-selector 折叠重构
//   - 数据源：providerCredentialStore.activeCredentials × 各凭证 available_models
//   - 选项变化弹 PinConfirmDialog → 确认 emit('pin-confirmed', credentialId, model)
//   - W1 + W4：空态 / 无对话 / frozen 三态 disabled + tooltip + 双重防御 guard
// ============================================================================

const providerStore = useProviderCredentialStore()
const { isSystemAdmin } = usePermission()

async function loadCredentialsForChat() {
  const sid = chatStore.selectedSpaceId ?? undefined
  try {
    await Promise.all([
      providerStore.fetchCredentials({ scope: 'any', spaceId: sid }),
      providerStore.fetchProviderTypes(),
    ])
  }
  catch {
    // 静默；空态 UI 已兜
  }
}
onMounted(loadCredentialsForChat)
watch(() => chatStore.selectedSpaceId, loadCredentialsForChat)

// 弹层 Teleport 到 body 后，需基于触发器 rect 做 fixed 定位（规避 .input-card
// overflow:hidden 裁剪）。menuRef 指向 teleport 后的菜单，ignore 触发器包裹层。
const menuRef = ref<HTMLElement | null>(null)
const menuStyle = ref<Record<string, string>>({})

function updateMenuPosition() {
  const el = modelMenuRef.value
  if (!el)
    return
  const r = el.getBoundingClientRect()
  menuStyle.value = {
    position: 'fixed',
    // 右对齐触发器右边缘，向上弹出（输入框在屏幕底部）
    right: `${Math.max(8, window.innerWidth - r.right)}px`,
    bottom: `${window.innerHeight - r.top + 6}px`,
    minWidth: `${Math.max(r.width, 208)}px`,
    maxWidth: 'min(22rem, calc(100vw - 1rem))',
  }
}

function toggleModelMenu() {
  showModelMenu.value = !showModelMenu.value
  if (showModelMenu.value)
    nextTick(updateMenuPosition)
}

onClickOutside(menuRef, () => {
  showModelMenu.value = false
}, { ignore: [modelMenuRef] })

function onViewportChange() {
  if (showModelMenu.value)
    updateMenuPosition()
}
onMounted(() => {
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})

interface CredentialModelOption {
  credential: ProviderCredentialDto
  model: AvailableModel
  /** 唯一 key：`${credential.id}::${model.id}` */
  key: string
  /** 展示文案：`${credential.name} / ${model.id}` */
  label: string
}

const credentialModelOptions = computed<CredentialModelOption[]>(() => {
  const opts: CredentialModelOption[] = []
  for (const cred of providerStore.activeCredentials) {
    // 兼容历史 sessionStorage 中无 available_models 字段的旧 credential 快照
    const models = cred.available_models ?? []
    if (models.length > 0) {
      for (const m of models) {
        opts.push({
          credential: cred,
          model: m,
          key: `${cred.id}::${m.id}`,
          label: `${cred.name} / ${m.id}`,
        })
      }
    }
    else {
      // 尚未刷新 available_models → fallback 到凭证自身配置的 default_model
      // （Provider fallback 修复：旧代码 fallback 用 provider-type meta 的
      //  default_model，但 /types/ 端点不返回该字段恒为 undefined，导致有 active 凭证
      //  却产生 0 选项，误显示「无可用 Provider」）。
      const fallbackModel
        = cred.default_model
          || providerStore.providerTypes.find(p => p.provider_type === cred.provider_type)?.default_model
      if (fallbackModel) {
        opts.push({
          credential: cred,
          model: { id: fallbackModel, display_name: fallbackModel },
          key: `${cred.id}::${fallbackModel}`,
          label: `${cred.name} / ${fallbackModel}`,
        })
      }
    }
  }
  // 排序优先级：
  //   1. 默认 provider（is_default）置顶 —— 默认模型应排在最上面（用户诉求）
  //   2. 同一凭证内：default_model 置顶
  //   3. scope=system 优先于 project
  //   4. 同 scope 内按 credential.name → model.id 升序
  return opts.sort((a, b) => {
    if (a.credential.is_default !== b.credential.is_default)
      return a.credential.is_default ? -1 : 1
    if (a.credential.id === b.credential.id) {
      const dm = a.credential.default_model
      if (dm) {
        if (a.model.id === dm)
          return -1
        if (b.model.id === dm)
          return 1
      }
    }
    if (a.credential.scope !== b.credential.scope)
      return a.credential.scope === 'system' ? -1 : 1
    if (a.credential.name !== b.credential.name)
      return a.credential.name.localeCompare(b.credential.name)
    return a.model.id.localeCompare(b.model.id)
  })
})

// 默认选项 = 排序后首项（即默认 provider 的默认模型）
const defaultOptionKey = computed<string | null>(
  () => credentialModelOptions.value[0]?.key ?? null,
)

const currentSelectionKey = computed<string | null>(() => {
  const conv = chatStore.currentConversation
  if (!conv?.provider_credential_id || !conv.model)
    return null
  return `${conv.provider_credential_id}::${conv.model}`
})

// 当前生效的选中项：优先对话已绑定，否则用户级记忆（含自动选中的默认）
const effectiveSelectionKey = computed<string | null>(
  () => currentSelectionKey.value || chatStore.selectedCredentialModel || null,
)

const currentSelectedOption = computed<CredentialModelOption | null>(() => {
  const key = effectiveSelectionKey.value
  if (!key)
    return null
  return credentialModelOptions.value.find(o => o.key === key) ?? null
})

// 无当前对话绑定、且无用户级记忆时，自动选中默认 provider 的默认模型并持久化（用户诉求②）
watch(
  [credentialModelOptions, currentSelectionKey],
  ([opts, currentKey]) => {
    if (opts.length === 0 || currentKey)
      return
    if (chatStore.selectedCredentialModel)
      return
    if (defaultOptionKey.value)
      chatStore.selectedCredentialModel = defaultOptionKey.value
  },
  { immediate: true },
)

const currentSelectionLabel = computed<string>(() => {
  const key = currentSelectionKey.value
  if (!key) {
    // 无当前对话时，优先显示记忆的选择
    const rememberedKey = chatStore.selectedCredentialModel
    if (rememberedKey) {
      const found = credentialModelOptions.value.find(o => o.key === rememberedKey)
      if (found)
        return found.label
    }
    return '请选择 Provider · 模型'
  }
  const found = credentialModelOptions.value.find(o => o.key === key)
  if (found)
    return found.label
  // 凭证已被删除或不在 active 列表 → fallback 显示原始 ID（I1 已知降级链）
  const conv = chatStore.currentConversation
  return `${conv?.provider_credential_id ?? '未知'} / ${conv?.model ?? '默认'}`
})

const isEmpty = computed(() => credentialModelOptions.value.length === 0)

const emptyCta = computed(() => {
  if (isSystemAdmin.value)
    return { text: '去 admin 添加凭证 →', to: '/admin/providers' }
  const pid = chatStore.selectedSpaceId
  return {
    text: '去空间设置添加凭证 →',
    to: pid ? `/spaces/${pid}/settings#providers` : '/spaces',
  }
})

// PinConfirmDialog 状态
const pinDialogOpen = ref(false)
const pendingOption = ref<CredentialModelOption | null>(null)

const oldProviderName = computed(() => {
  const key = currentSelectionKey.value
  if (!key)
    return '未指定'
  const found = credentialModelOptions.value.find(o => o.key === key)
  return found?.credential.name ?? '当前 Provider'
})
const oldModelLabel = computed(
  () => chatStore.currentConversation?.model || '默认模型',
)

// [Revision 1 — W1 + W4] frozen 态 disabled 派生
const conversationStatusRef = computed<ConversationStatus>(
  () => chatStore.currentConversation?.status ?? 'draft',
)
const frozen = useConversationFrozen(conversationStatusRef, ref(false))
const isConversationFrozen = computed(() => frozen.value.isFrozen)
const isSelectorDisabled = computed(
  () =>
    isEmpty.value
    || isConversationFrozen.value,
)
const disabledReason = computed<string>(() => {
  if (isEmpty.value)
    return '' // 空态用专属 tooltip（CTA 链接），见模板
  if (isConversationFrozen.value)
    return frozen.value.reason || '当前对话已固定，无法切换 Provider / 模型'
  return ''
})

async function onSelectCombination(opt: CredentialModelOption) {
  // [Revision 1 — W1] 顶部双重防御：button :disabled 已拦，再守一道（防 a11y / 测试 emit click）
  if (isSelectorDisabled.value) {
    showModelMenu.value = false
    return
  }
  showModelMenu.value = false
  if (opt.key === currentSelectionKey.value)
    return // 选中相同组合 → noop

  // 记住用户选择（跨新建对话复用）
  chatStore.selectedCredentialModel = opt.key

  // 没有活动对话时只记住选择，真正创建会话交给首次发送。
  if (!chatStore.currentConversationId) {
    chatStore.selectedModel = opt.model.id
    return
  }

  // 已有对话但尚未绑定 Provider / 模型 → 直接应用，不弹确认
  if (!currentSelectionKey.value) {
    emit('pin-confirmed', opt.credential.id, opt.model.id)
    return
  }

  pendingOption.value = opt
  pinDialogOpen.value = true
}

function handlePinConfirm() {
  if (!pendingOption.value)
    return
  const { credential, model } = pendingOption.value
  emit('pin-confirmed', credential.id, model.id)
  // 记住用户选择（跨新建对话复用）
  chatStore.selectedCredentialModel = pendingOption.value.key
  pinDialogOpen.value = false
  pendingOption.value = null
}

function handlePinCancel() {
  pendingOption.value = null
  pinDialogOpen.value = false
}

/** 检查当前对话是否已选择模型 */
const hasSelectedModel = computed(() => {
  const conv = chatStore.currentConversation
  return !!conv?.model || !!chatStore.selectedCredentialModel || (chatStore.selectedModel !== '__default__' && !!chatStore.selectedModel)
})

function selectedModelSupportsImage(): boolean {
  const model = currentSelectedOption.value?.model
  if (!model)
    return false
  if (Array.isArray(model.input_modalities))
    return model.input_modalities.includes('image')
  return model.supports_vision === true
}

const supportsImageInput = computed(() => selectedModelSupportsImage())

// ============================================================================
// 发送按钮可用性派生（避免「亮色但点了没反应」的误导）
// ============================================================================
const hasDraftContent = computed(() => !!inputContent.value.trim() || pendingImages.value.length > 0)
const sendDisabledReason = computed<string>(() => {
  if (chatStore.isStreaming)
    return '正在生成中，请稍候或先点「停止生成」'
  if (isUploadingImages.value)
    return '图片上传中'
  if (!hasDraftContent.value)
    return ''
  // 无空间也允许对话（通用对话）；任务涉及空间知识时由 AI 引导用户选择空间
  if (isEmpty.value)
    return '当前没有可用的 Provider 凭证，请先在 admin/providers 或空间设置中添加'
  return ''
})
const canSend = computed(
  () => hasDraftContent.value && !chatStore.isStreaming && !isUploadingImages.value && !sendDisabledReason.value,
)

function formatBytes(size: number): string {
  if (size >= 1024 * 1024)
    return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(size / 1024))} KB`
}

function openFilePicker() {
  if (chatStore.isStreaming || isUploadingImages.value)
    return
  if (!supportsImageInput.value) {
    toast.error('当前模型不支持图片', '请切换支持图片的模型后再粘贴或上传')
    return
  }
  fileInput.value?.click()
}

function resetFileInput() {
  if (fileInput.value)
    fileInput.value.value = ''
}

function addImageFiles(files: Iterable<File>) {
  const incoming = Array.from(files).filter(file => file.type.startsWith('image/'))
  if (incoming.length === 0)
    return
  if (!supportsImageInput.value) {
    toast.error('当前模型不支持图片', '请切换支持图片的模型后再粘贴或上传')
    return
  }

  for (const file of incoming) {
    if (pendingImages.value.length >= MAX_IMAGES_PER_MESSAGE) {
      toast.warning(`一次最多添加 ${MAX_IMAGES_PER_MESSAGE} 张图片`)
      break
    }
    if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
      toast.error('不支持的图片格式', '请使用 PNG、JPEG、GIF 或 WebP')
      continue
    }
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error('图片过大', '请上传 10MB 以内的图片')
      continue
    }
    pendingImages.value.push({
      id: randomUUID(),
      file,
      previewUrl: URL.createObjectURL(file),
      status: 'ready',
    })
  }
}

function handleFileSelect(event: Event) {
  const input = event.target as HTMLInputElement
  if (input.files)
    addImageFiles(Array.from(input.files))
  resetFileInput()
}

function handlePaste(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files || [])
  const imageFiles = files.filter(file => file.type.startsWith('image/'))
  if (imageFiles.length === 0)
    return
  event.preventDefault()
  addImageFiles(imageFiles)
}

function handleDrop(event: DragEvent) {
  const files = Array.from(event.dataTransfer?.files || [])
  addImageFiles(files)
}

function removePendingImage(id: string) {
  const item = pendingImages.value.find(image => image.id === id)
  if (item)
    URL.revokeObjectURL(item.previewUrl)
  pendingImages.value = pendingImages.value.filter(image => image.id !== id)
}

function clearPendingImages(images: PendingImage[]) {
  const ids = new Set(images.map(image => image.id))
  for (const image of images)
    URL.revokeObjectURL(image.previewUrl)
  pendingImages.value = pendingImages.value.filter(image => !ids.has(image.id))
}

onBeforeUnmount(() => {
  for (const image of pendingImages.value)
    URL.revokeObjectURL(image.previewUrl)
})

async function handleSend() {
  const typedContent = inputContent.value.trim()
  if (!typedContent && pendingImages.value.length === 0)
    return
  if (chatStore.isStreaming) {
    toast.warning('上一条消息正在生成中', '请等待完成或点「停止生成」后再发送')
    return
  }

  // 前置硬校验：没有任何可用 Provider 凭证 → 引导用户去配置
  if (isEmpty.value) {
    toast.error('当前没有可用的 Provider 凭证', '请先在 admin/providers 或空间设置中创建并启用凭证')
    return
  }

  // 没有对话时只准备模型选择；sendMessage 会在首次发送时创建真实会话。
  if (!chatStore.currentConversationId && chatStore.selectedCredentialModel) {
    if (chatStore.selectedCredentialModel) {
      const parts = chatStore.selectedCredentialModel.split('::')
      if (parts.length === 2) {
        const [, modelId] = parts
        chatStore.selectedModel = modelId
      }
    }
  }

  // 没有可用模型时禁止发送；本地草稿允许依赖记忆的模型选择。
  if (!hasSelectedModel.value) {
    toast.error('请先选择 Provider / 模型')
    return
  }

  const content = typedContent || '请分析这张图片'
  const feishuDocId = typedContent ? extractFirstFeishuDocId(typedContent) : null
  const draft = inputContent.value
  const draftImages = [...pendingImages.value]
  if (draftImages.length > 0 && !supportsImageInput.value) {
    toast.error('当前模型不支持图片', '请切换支持图片的模型后再发送')
    return
  }
  try {
    isUploadingImages.value = draftImages.length > 0
    const uploadedImageParts: ImagePart[] = []
    for (const image of draftImages) {
      image.status = 'uploading'
      try {
        uploadedImageParts.push(await uploadChatImage(image.file))
        image.status = 'ready'
        image.error = undefined
      }
      catch (error) {
        image.status = 'error'
        image.error = error instanceof Error ? error.message : '上传失败'
        throw error
      }
    }

    inputContent.value = ''
    nextTick(autoResize)
    await chatStore.sendMessage(content, feishuDocId ?? undefined, uploadedImageParts)
    if (!chatStore.error)
      clearPendingImages(draftImages)
  }
  catch (error) {
    toast.error('发送失败', error instanceof Error ? error.message : '请稍后重试')
  }
  finally {
    isUploadingImages.value = false
    // sendMessage 内部失败会写 chatStore.error；这里只在草稿丢失但又有错误时回填
    if (chatStore.error && !chatStore.streamingContent && inputContent.value === '') {
      inputContent.value = draft
      nextTick(autoResize)
    }
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function autoResize() {
  const el = textarea.value
  if (!el)
    return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

function toggleDeepAnalysis() {
  chatStore.forceDeepAnalysis = !chatStore.forceDeepAnalysis
}

function toggleNotifications() {
  void chatStore.toggleNotifications(!chatStore.notificationsEnabled)
}
</script>

<template>
  <div class="chat-input-dock">
    <div class="chat-input-center">
      <!-- 预算警告 -->
      <Transition
        enter-active-class="transition-all duration-300 ease-out"
        leave-active-class="transition-all duration-200 ease-in"
        enter-from-class="opacity-0 -translate-y-1"
        enter-to-class="opacity-100 translate-y-0"
        leave-from-class="opacity-100 translate-y-0"
        leave-to-class="opacity-0 -translate-y-1"
      >
        <div v-if="chatStore.budgetWarning" class="budget-bar">
          <span class="icon-[lucide--alert-triangle] text-xs" />
          本次对话已使用 {{ chatStore.budgetWarning }}% 预算
        </div>
      </Transition>

      <!-- 输入卡片（外层 wrap 承载深度分析模式的浮动 Claude 徽标） -->
      <div class="input-card-wrap">
        <Transition name="claude-float">
          <div
            v-if="chatStore.forceDeepAnalysis"
            class="claude-badge"
            aria-hidden="true"
          >
            <!-- Claude Code 终端图标：深色终端窗 + 珊瑚色 prompt 提示符 -->
            <svg class="claude-badge-logo" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <rect x="1.5" y="1.5" width="21" height="21" rx="5.5" fill="#1F1E1C" />
              <path d="M6.8 8.4 10.6 12l-3.8 3.6" stroke="#D97757" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round" fill="none" />
              <path d="M12.6 16.2h4.6" stroke="#FAF9F5" stroke-width="2.1" stroke-linecap="round" fill="none" />
            </svg>
            <span class="claude-badge-text">Friday × Claude Code 深度分析</span>
          </div>
        </Transition>

        <div
          class="input-card"
          :class="{
            'input-card--disabled': chatStore.isStreaming,
            'input-card--deep': chatStore.forceDeepAnalysis,
          }"
          @paste="handlePaste"
          @dragover.prevent
          @drop.prevent="handleDrop"
        >
          <input
            ref="fileInput"
            type="file"
            class="sr-only"
            accept="image/png,image/jpeg,image/gif,image/webp"
            multiple
            @change="handleFileSelect"
          >
          <!-- 上层：文本输入 -->
          <textarea
            ref="textarea"
            v-model="inputContent"
            placeholder="给 Friday 发消息..."
            class="input-textarea"
            rows="1"
            :disabled="chatStore.isStreaming"
            @keydown="handleKeydown"
            @input="autoResize"
          />

          <div v-if="pendingImages.length > 0" class="image-preview-strip">
            <div
              v-for="image in pendingImages"
              :key="image.id"
              class="image-preview-chip"
              :class="{ 'image-preview-chip--error': image.status === 'error' }"
            >
              <img :src="image.previewUrl" alt="" class="image-preview-thumb">
              <div class="image-preview-meta">
                <span class="image-preview-name">{{ image.file.name }}</span>
                <span class="image-preview-size">
                  {{ image.status === 'uploading' ? '上传中...' : image.error || formatBytes(image.file.size) }}
                </span>
              </div>
              <button
                type="button"
                class="image-preview-remove"
                title="移除图片"
                :disabled="image.status === 'uploading'"
                @click="removePendingImage(image.id)"
              >
                <span class="icon-[lucide--x] text-[12px]" />
              </button>
            </div>
          </div>

          <!-- 下层：工具栏 -->
          <div class="input-toolbar">
            <!-- 左侧工具 -->
            <div class="toolbar-left">
              <!-- 模型不支持图片时整体隐藏（disabled 灰按钮反而让人困惑） -->
              <TooltipProvider v-if="supportsImageInput" :delay-duration="300">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <button
                      type="button"
                      class="toolbar-btn"
                      aria-label="添加图片"
                      title="添加图片"
                      :disabled="chatStore.isStreaming || isUploadingImages"
                      @click="openFilePicker"
                    >
                      <span class="icon-[lucide--image-plus] text-[15px]" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>添加图片</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <TooltipProvider :delay-duration="300">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <button
                      type="button"
                      class="toolbar-pill"
                      :aria-label="chatStore.forceDeepAnalysis ? '关闭深度分析' : '开启深度分析'"
                      :aria-pressed="chatStore.forceDeepAnalysis"
                      :class="{ 'toolbar-pill--active': chatStore.forceDeepAnalysis }"
                      @click="toggleDeepAnalysis"
                    >
                      <span class="icon-[lucide--telescope] text-[14px]" />
                      <span>深度分析</span>
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top" class="max-w-xs">
                    <p class="font-semibold">
                      深度分析 · Claude Code
                    </p>
                    <p class="mt-1 text-xs font-normal leading-relaxed opacity-90">
                      {{ chatStore.forceDeepAnalysis ? '已开启：' : '开启后' }}由 Runner 调度 Claude Code 编码代理深入探索代码库，结果更全面但耗时更长。
                    </p>
                    <p class="mt-1.5 text-xs font-normal leading-relaxed opacity-70">
                      提示：安装 friday-codebase-agent Skill 后，也可以通过 MCP 在 Cursor / Claude Code 中直接使用 Friday 的代码索引与分析能力。
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>

              <TooltipProvider :delay-duration="300">
                <Tooltip>
                  <TooltipTrigger as-child>
                    <button
                      type="button"
                      class="toolbar-btn"
                      :aria-label="chatStore.notificationsEnabled ? '关闭浏览器通知' : '开启浏览器通知'"
                      :title="chatStore.notificationsEnabled ? '关闭浏览器通知' : '开启浏览器通知'"
                      :class="{ 'toolbar-btn--active': chatStore.notificationsEnabled }"
                      @click="toggleNotifications"
                    >
                      <span :class="chatStore.notificationsEnabled ? 'icon-[lucide--bell-ring]' : 'icon-[lucide--bell-off]'" class="text-[15px]" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>{{ chatStore.notificationsEnabled ? '浏览器通知已开启' : '点击开启浏览器通知' }}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>

            <!-- 右侧：模型选择 + 发送 -->
            <div class="toolbar-right">
              <!-- 模型选择器（凭证/模型组合） -->
              <div ref="modelMenuRef" class="relative">
                <!-- 三态①：空态（无可用凭证）→ CTA tooltip -->
                <TooltipProvider v-if="isEmpty" :delay-duration="200">
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button class="model-selector model-selector--disabled" disabled>
                        <span class="model-label">无可用 Provider</span>
                        <span class="icon-[lucide--alert-triangle] text-[11px]" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" class="max-w-xs text-xs font-normal">
                      <p class="mb-1">
                        请先在 admin/providers 或空间设置创建并启用 Provider 凭证。
                      </p>
                      <RouterLink :to="emptyCta.to" class="text-primary hover:underline">
                        {{ emptyCta.text }}
                      </RouterLink>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>

                <!-- 三态②：有凭证但 disabled（无对话 / frozen）→ 原因 tooltip -->
                <TooltipProvider v-else-if="isSelectorDisabled" :delay-duration="200">
                  <Tooltip>
                    <TooltipTrigger as-child>
                      <button
                        class="model-selector model-selector--disabled"
                        disabled
                        :data-test-disabled-reason="disabledReason"
                      >
                        <span class="model-label">{{ currentSelectionLabel }}</span>
                        <span class="icon-[lucide--lock] text-[11px]" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent side="top" class="max-w-xs text-xs font-normal">
                      {{ disabledReason }}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>

                <!-- 三态③：可用态 → 正常 dropdown -->
                <button v-else class="model-selector" @click="toggleModelMenu">
                  <span class="model-label">{{ currentSelectionLabel }}</span>
                  <span
                    class="icon-[lucide--chevron-down] text-[11px] transition-transform"
                    :class="{ 'rotate-180': showModelMenu }"
                  />
                </button>

                <!-- Teleport 到 body + fixed 定位，规避 .input-card overflow:hidden 裁剪 -->
                <Teleport to="body">
                  <Transition
                    enter-active-class="transition-all duration-150 ease-out"
                    leave-active-class="transition-all duration-100 ease-in"
                    enter-from-class="opacity-0 translate-y-1 scale-95"
                    enter-to-class="opacity-100 translate-y-0 scale-100"
                    leave-from-class="opacity-100 translate-y-0 scale-100"
                    leave-to-class="opacity-0 translate-y-1 scale-95"
                  >
                    <div
                      v-if="showModelMenu && !isSelectorDisabled"
                      ref="menuRef"
                      class="model-menu"
                      :style="menuStyle"
                    >
                      <button
                        v-for="opt in credentialModelOptions"
                        :key="opt.key"
                        class="model-menu-item"
                        :class="{ 'model-menu-item--active': opt.key === effectiveSelectionKey }"
                        @click="onSelectCombination(opt)"
                      >
                        <span class="truncate">{{ opt.label }}</span>
                        <span
                          v-if="opt.key === defaultOptionKey"
                          class="ml-1 shrink-0 rounded bg-primary/10 px-1 text-[10px] text-primary"
                        >默认</span>
                        <span
                          v-if="opt.key === effectiveSelectionKey"
                          class="icon-[lucide--check] text-xs text-primary shrink-0 ml-auto"
                        />
                      </button>
                    </div>
                  </Transition>
                </Teleport>
              </div>

              <!-- PinConfirmDialog（chat 路径凭证+模型切换确认） -->
              <PinConfirmDialog
                v-model:open="pinDialogOpen"
                :old-provider-name="oldProviderName"
                :old-model="oldModelLabel"
                :new-provider-name="pendingOption?.credential.name ?? ''"
                :new-model="pendingOption?.model.id ?? ''"
                :message-count="chatStore.messages.length"
                @confirm="handlePinConfirm"
                @cancel="handlePinCancel"
              />

              <!-- 发送 / 停止按钮（同位切换：流式中显示停止，否则显示发送） -->
              <button
                v-if="chatStore.isStreaming"
                type="button"
                class="send-btn send-btn--stop"
                :disabled="chatStore.isInterrupting"
                :title="chatStore.isInterrupting ? '正在停止...' : '停止生成'"
                @click="chatStore.stopStreaming()"
              >
                <span v-if="chatStore.isInterrupting" class="icon-[lucide--loader-circle] text-sm animate-spin" />
                <span v-else class="send-btn__stop-square" aria-hidden="true" />
              </button>
              <button
                v-else
                type="button"
                class="send-btn"
                :class="{ 'send-btn--active': canSend }"
                :disabled="!canSend"
                :title="sendDisabledReason || '发送'"
                @click="handleSend"
              >
                <span class="icon-[lucide--arrow-up] text-sm" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-input-dock {
  padding: 0 1rem 1.25rem;
  background: linear-gradient(
    to top,
    hsl(210 40% 96.5%) 58%,
    hsl(210 40% 96.5% / 0.88) 76%,
    hsl(210 40% 96.5% / 0) 100%
  );
  pointer-events: none;
}
.chat-input-dock > * {
  pointer-events: auto;
}

.chat-input-center {
  max-width: 48rem;
  margin: 0 auto;
}

.budget-bar {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.75rem;
  margin-bottom: 0.5rem;
  border-radius: 0.625rem;
  background: hsl(38 92% 50% / 0.08);
  border: 1px solid hsl(38 92% 50% / 0.2);
  color: hsl(38 80% 40%);
  font-size: 0.6875rem;
}

/* ======== 输入卡片 ======== */
.input-card-wrap {
  position: relative;
}

/* 深度分析模式：Claude Code 徽标从卡片顶部浮出（静置，无晃动） */
.claude-badge {
  position: absolute;
  top: -0.8125rem;
  left: 1.125rem;
  z-index: 11;
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  padding: 0.25rem 0.6875rem 0.25rem 0.375rem;
  border-radius: 9999px;
  border: 1px solid transparent;
  /* 双色描边：与输入框的交织边框呼应（Friday 青绿 × Claude 珊瑚） */
  background:
    linear-gradient(hsl(0 0% 100% / 0.97), hsl(0 0% 100% / 0.97)) padding-box,
    linear-gradient(110deg, hsl(168 76% 42% / 0.55), hsl(15 63% 55% / 0.55)) border-box;
  box-shadow:
    0 4px 12px hsl(215 28% 17% / 0.1),
    inset 0 1px 0 hsl(0 0% 100% / 0.8);
  pointer-events: none;
  user-select: none;
}

.claude-badge-logo {
  width: 1rem;
  height: 1rem;
  border-radius: 0.3125rem;
  flex-shrink: 0;
}

.claude-badge-text {
  font-size: 0.6875rem;
  font-weight: 650;
  letter-spacing: 0.01em;
  /* Friday × Claude 渐变文字，呼应「共同协作」 */
  background: linear-gradient(100deg, hsl(168 70% 30%), hsl(15 58% 42%));
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  white-space: nowrap;
}

/* 入场：从卡片后方向上浮出 */
.claude-float-enter-active {
  transition:
    opacity 0.3s ease-out,
    transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.claude-float-leave-active {
  transition:
    opacity 0.18s ease-in,
    transform 0.18s ease-in;
}
.claude-float-enter-from,
.claude-float-leave-to {
  opacity: 0;
  transform: translateY(0.625rem) scale(0.85);
}

.input-card {
  border: 1px solid hsl(214 32% 88%);
  border-radius: 1.375rem;
  background: hsl(0 0% 100% / 0.94);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  box-shadow:
    0 10px 24px hsl(215 28% 17% / 0.08),
    0 1px 2px hsl(215 28% 17% / 0.05),
    inset 0 1px 0 hsl(0 0% 100% / 0.86);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
  overflow: hidden;
}
.input-card:focus-within {
  border-color: hsl(168 76% 42% / 0.5);
  box-shadow:
    0 0 0 3px hsl(168 76% 42% / 0.08),
    0 12px 28px hsl(215 28% 17% / 0.09),
    0 1px 2px hsl(215 28% 17% / 0.05);
}
.input-card--disabled {
  opacity: 0.6;
}

/* ======== 深度分析模式边框：Friday 青绿 × Claude 珊瑚 交织流动 ========
   隐喻 Friday 和 Claude Code 协作分析。conic-gradient 双色绕卡片缓慢
   旋转；通过 @property 注册角度变量使其可被动画插值。 */
@property --friday-deep-angle {
  syntax: '<angle>';
  inherits: false;
  initial-value: 0deg;
}

.input-card--deep {
  border: 1px solid transparent;
  background:
    linear-gradient(hsl(0 0% 100% / 0.96), hsl(0 0% 100% / 0.96)) padding-box,
    conic-gradient(
        from var(--friday-deep-angle),
        hsl(168 76% 42% / 0.9) 0deg,
        hsl(15 63% 55% / 0.9) 90deg,
        hsl(168 76% 42% / 0.9) 180deg,
        hsl(15 63% 55% / 0.9) 270deg,
        hsl(168 76% 42% / 0.9) 360deg
      )
      border-box;
  animation: deep-border-weave 6s linear infinite;
  box-shadow:
    0 0 0 3px hsl(168 76% 42% / 0.05),
    0 10px 24px hsl(215 28% 17% / 0.09),
    0 1px 2px hsl(215 28% 17% / 0.05);
}
.input-card--deep:focus-within {
  /* 覆盖基础 .input-card:focus-within 的纯色边框，保持渐变描边可见 */
  border-color: transparent;
  animation-duration: 3.5s;
  box-shadow:
    0 0 0 3px hsl(168 76% 42% / 0.08),
    0 0 18px hsl(15 63% 55% / 0.12),
    0 12px 28px hsl(215 28% 17% / 0.1);
}

@keyframes deep-border-weave {
  to {
    --friday-deep-angle: 360deg;
  }
}

@media (prefers-reduced-motion: reduce) {
  .input-card--deep {
    animation: none;
  }
}

/* 给浮出的徽标让出首行空间，避免文字与徽标下沿重叠 */
.input-card--deep .input-textarea {
  padding-top: 1.125rem;
}

.input-textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  background: transparent;
  font-size: 0.9375rem;
  line-height: 1.6;
  color: hsl(215 28% 17%);
  max-height: 200px;
  padding: 0.875rem 1rem 0.25rem;
}
.input-textarea::placeholder {
  color: hsl(215 16% 60%);
}
.input-textarea:disabled {
  cursor: not-allowed;
}

.image-preview-strip {
  display: flex;
  gap: 0.5rem;
  overflow-x: auto;
  padding: 0.125rem 0.75rem 0.375rem;
  scrollbar-width: thin;
}

.image-preview-chip {
  display: grid;
  grid-template-columns: 3rem minmax(0, 8rem) 1.5rem;
  align-items: center;
  gap: 0.5rem;
  min-width: 13.25rem;
  max-width: 16rem;
  padding: 0.375rem;
  border-radius: 0.75rem;
  border: 1px solid hsl(214 32% 88% / 0.9);
  background: hsl(210 40% 98% / 0.8);
}

.image-preview-chip--error {
  border-color: hsl(0 72% 51% / 0.28);
  background: hsl(0 72% 51% / 0.05);
}

.image-preview-thumb {
  width: 3rem;
  height: 3rem;
  border-radius: 0.5rem;
  object-fit: cover;
  background: hsl(214 32% 91%);
}

.image-preview-meta {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.image-preview-name,
.image-preview-size {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-preview-name {
  color: hsl(215 28% 17%);
  font-size: 0.75rem;
  font-weight: 700;
}

.image-preview-size {
  color: hsl(215 16% 47%);
  font-size: 0.6875rem;
  font-weight: 600;
}

.image-preview-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 0.5rem;
  color: hsl(215 16% 47%);
  transition:
    background-color 0.15s ease,
    color 0.15s ease;
}

.image-preview-remove:hover:not(:disabled),
.image-preview-remove:focus-visible:not(:disabled) {
  background: hsl(0 72% 51% / 0.08);
  color: hsl(0 72% 45%);
  outline: none;
}

.image-preview-remove:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

/* ======== 工具栏 ======== */
.input-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.375rem 0.5rem 0.5rem;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.125rem;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 0.375rem;
}

.toolbar-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  border: none;
  background: transparent;
  color: hsl(215 16% 60%);
  cursor: pointer;
  transition: all 0.15s;
}
.toolbar-btn:hover {
  background: hsl(210 40% 96%);
  color: hsl(215 28% 30%);
}
.toolbar-btn--active {
  color: hsl(168 76% 42%);
  background: hsl(168 76% 42% / 0.08);
}
.toolbar-btn--active:hover {
  background: hsl(168 76% 42% / 0.14);
  color: hsl(167 76% 36%);
}

/* 带文字的功能开关 pill（深度分析）：参考 ChatGPT 工具开关样式 */
.toolbar-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.3125rem;
  height: 2rem;
  padding: 0 0.6875rem;
  border-radius: 9999px;
  border: 1px solid hsl(214 32% 89%);
  background: transparent;
  color: hsl(215 16% 47%);
  font-size: 0.8125rem;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
  transition: all 0.15s;
}
.toolbar-pill:hover {
  background: hsl(210 40% 96%);
  color: hsl(215 28% 25%);
}
/* 激活态与 Claude 品牌色保持一致（深度分析 = Claude Code 模式） */
.toolbar-pill--active {
  border-color: hsl(15 63% 55% / 0.45);
  background: hsl(15 63% 55% / 0.1);
  color: hsl(15 58% 40%);
}
.toolbar-pill--active:hover {
  background: hsl(15 63% 55% / 0.16);
}

/* ======== 模型选择器 ======== */
.model-selector {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.625rem;
  border-radius: 0.5rem;
  border: none;
  background: transparent;
  color: hsl(215 16% 47%);
  font-size: 0.8125rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.model-selector:hover {
  background: hsl(210 40% 96%);
  color: hsl(215 28% 17%);
}
.model-selector--disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.model-selector--disabled:hover {
  background: transparent;
  color: hsl(215 16% 47%);
}

.model-label {
  max-width: 10rem;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 定位（position/right/bottom/min-width）由内联 menuStyle 提供（Teleport + fixed）。 */
.model-menu {
  min-width: 13rem;
  max-height: 16rem;
  overflow-y: auto;
  padding: 0.25rem;
  border-radius: 0.75rem;
  border: 1px solid hsl(214 32% 91%);
  background: white;
  box-shadow:
    0 4px 16px rgba(0, 0, 0, 0.08),
    0 8px 32px rgba(0, 0, 0, 0.04);
  z-index: 9999;
}

.model-menu-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  border: none;
  background: transparent;
  color: hsl(215 28% 17%);
  font-size: 0.8125rem;
  text-align: left;
  cursor: pointer;
  transition: background 0.1s;
}
.model-menu-item:hover {
  background: hsl(210 40% 96%);
}
.model-menu-item--active {
  color: hsl(168 76% 42%);
}

/* ======== 发送按钮 ======== */
.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border-radius: 0.5rem;
  border: none;
  background: hsl(214 32% 91% / 0.5);
  color: hsl(215 16% 60%);
  cursor: not-allowed;
  transition: all 0.15s;
  flex-shrink: 0;
}
.send-btn--active {
  background: hsl(168 76% 42%);
  color: white;
  cursor: pointer;
  box-shadow: 0 1px 3px hsl(168 76% 42% / 0.3);
}
.send-btn--active:hover {
  background: hsl(167 76% 36%);
}
/* 流式期间同位切换：保持 send-btn 几何，换成红色「停止」 */
.send-btn--stop {
  background: hsl(0 72% 51%);
  color: white;
  cursor: pointer;
  box-shadow: 0 1px 3px hsl(0 72% 51% / 0.3);
}
.send-btn--stop:hover {
  background: hsl(0 72% 45%);
}
.send-btn--stop:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.send-btn__stop-square {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: currentColor;
}
</style>
