<script setup lang="ts">
import type { ConversationStatus } from '~/composables/useConversationFrozen'
import type { ImagePart } from '~/types/chat'
import type { AvailableModel, ProviderCredentialDto } from '~/types/providerCredential'
import { gsap } from 'gsap'
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
// 模型能力徽章：在选择器里直观展示「图片 / 上下文窗口 / 工具 / 思考」等能力，
// 帮助用户在切换模型前就知道它支持什么（避免发图后才发现模型不支持）。
//   - 图片 / 上下文 / 工具：来自 AvailableModel 的 per-model 能力字段（真源）。
//   - 思考：来自 Provider 类型 meta（supports_reasoning / supports_thinking）。
// ============================================================================
interface ModelCapabilityBadge {
  key: string
  icon: string
  label: string
  title: string
}

function formatContextLength(n?: number): string | null {
  if (!n || n <= 0)
    return null
  if (n >= 1_000_000) {
    const v = n / 1_000_000
    return `${Number.isInteger(v) ? v : v.toFixed(1)}M`
  }
  if (n >= 1000)
    return `${Math.round(n / 1000)}K`
  return `${n}`
}

function providerSupportsReasoning(providerType: string): boolean {
  const meta = providerStore.providerTypes.find(p => p.provider_type === providerType)
  return !!(meta?.supports_reasoning || meta?.supports_thinking)
}

// 推理能力目前只有 Provider 级 meta（无 per-model 字段）；对明显的非对话模型
// （TTS / ASR / 向量 / 语音克隆等）跳过「思考」徽章，避免误标。
function looksLikeNonChatModel(modelId: string): boolean {
  return /(?:^|[-_/])(?:tts|asr|whisper|embed|embedding|rerank|voice|audio|image|vision-ocr)(?:[-_/]|$)/i.test(modelId)
}

function modelCapabilities(opt: CredentialModelOption): ModelCapabilityBadge[] {
  const m = opt.model
  const badges: ModelCapabilityBadge[] = []

  const supportsImage = Array.isArray(m.input_modalities)
    ? m.input_modalities.includes('image')
    : m.supports_vision === true
  if (supportsImage)
    badges.push({ key: 'image', icon: 'icon-[lucide--image]', label: '图片', title: '支持图片输入（视觉）' })

  const ctx = formatContextLength(m.context_length)
  if (ctx) {
    badges.push({
      key: 'context',
      icon: 'icon-[lucide--scan-text]',
      label: ctx,
      title: `上下文窗口 ${m.context_length?.toLocaleString()} tokens`,
    })
  }

  if (m.supports_tools)
    badges.push({ key: 'tools', icon: 'icon-[lucide--wrench]', label: '工具', title: '支持工具调用 / Function Calling' })

  if (providerSupportsReasoning(opt.credential.provider_type) && !looksLikeNonChatModel(m.id))
    badges.push({ key: 'reasoning', icon: 'icon-[lucide--brain]', label: '思考', title: '支持推理 / 深度思考' })

  return badges
}

// 当前选中模型的能力（折叠态触发器内以纯图标紧凑展示）
const currentCapabilities = computed<ModelCapabilityBadge[]>(() =>
  currentSelectedOption.value ? modelCapabilities(currentSelectedOption.value) : [],
)

// 按 Provider（凭证）分组：组标题为 Provider 名，组内为该 Provider 的模型。
// 复用 credentialModelOptions 既有排序（默认 Provider 置顶等），按首次出现顺序成组。
interface CredentialModelGroup {
  credential: ProviderCredentialDto
  options: CredentialModelOption[]
}
const groupedModelOptions = computed<CredentialModelGroup[]>(() => {
  const groups: CredentialModelGroup[] = []
  const byId = new Map<string, CredentialModelGroup>()
  for (const opt of credentialModelOptions.value) {
    let group = byId.get(opt.credential.id)
    if (!group) {
      group = { credential: opt.credential, options: [] }
      byId.set(opt.credential.id, group)
      groups.push(group)
    }
    group.options.push(opt)
  }
  return groups
})

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
  playSendAnimation()
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

// ============================================================================
// GSAP 微交互 + Lottie（深度分析双星环绕）
// 统一遵循 prefers-reduced-motion：用户偏好减弱动效时全部跳过
// ============================================================================
const prefersReducedMotion
  = typeof window !== 'undefined'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const deepPillEl = ref<HTMLElement | null>(null)
const sendBtnEl = ref<HTMLElement | null>(null)

/* 浮动徽标入场：整体弹性浮出后，文字四段错拍点亮（Friday → × → Claude → 深度分析） */
function onBadgeEnter(el: Element, done: () => void) {
  if (prefersReducedMotion) {
    done()
    return
  }
  const spans = el.querySelectorAll('.claude-badge-text > span')
  gsap.timeline({ onComplete: done })
    .fromTo(
      el,
      { y: 12, scale: 0.7, opacity: 0 },
      { y: 0, scale: 1, opacity: 1, duration: 0.5, ease: 'back.out(1.9)' },
    )
    .fromTo(
      spans,
      { y: 5, opacity: 0 },
      { y: 0, opacity: 1, duration: 0.28, stagger: 0.055, ease: 'power2.out' },
      '-=0.3',
    )
}

function onBadgeLeave(el: Element, done: () => void) {
  if (prefersReducedMotion) {
    done()
    return
  }
  gsap.to(el, { y: 8, scale: 0.85, opacity: 0, duration: 0.18, ease: 'power2.in', onComplete: done })
}

/* 图片预览 chip：弹入 / 缩出 */
function onChipEnter(el: Element, done: () => void) {
  if (prefersReducedMotion) {
    done()
    return
  }
  gsap.fromTo(
    el,
    { scale: 0.85, opacity: 0, y: 6 },
    { scale: 1, opacity: 1, y: 0, duration: 0.35, ease: 'back.out(1.8)', onComplete: done },
  )
}

function onChipLeave(el: Element, done: () => void) {
  if (prefersReducedMotion) {
    done()
    return
  }
  gsap.to(el, { scale: 0.85, opacity: 0, duration: 0.18, ease: 'power2.in', onComplete: done })
}

/* 发送瞬间：箭头向上飞出、再从下方弹回，按钮轻微回弹 */
function playSendAnimation() {
  const btn = sendBtnEl.value
  if (!btn || prefersReducedMotion)
    return
  const arrow = btn.querySelector('span')
  if (arrow) {
    gsap.timeline()
      .to(arrow, { y: -14, opacity: 0, duration: 0.16, ease: 'power2.in' })
      .set(arrow, { y: 12 })
      .to(arrow, { y: 0, opacity: 1, duration: 0.3, ease: 'back.out(2.2)' })
  }
  gsap.fromTo(btn, { scale: 0.88 }, { scale: 1, duration: 0.4, ease: 'elastic.out(1.1, 0.6)', clearProps: 'scale' })
}

function toggleDeepAnalysis() {
  chatStore.forceDeepAnalysis = !chatStore.forceDeepAnalysis
  if (!prefersReducedMotion && deepPillEl.value) {
    gsap.fromTo(
      deepPillEl.value,
      { scale: 0.9 },
      { scale: 1, duration: 0.45, ease: 'elastic.out(1.2, 0.5)', clearProps: 'scale' },
    )
  }
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
        <Transition :css="false" @enter="onBadgeEnter" @leave="onBadgeLeave">
          <div
            v-if="chatStore.forceDeepAnalysis"
            class="claude-badge"
            aria-hidden="true"
          >
            <!-- Claude Code 官方 logo（lobehub 静态 SVG 路径）：暖黑圆角底上的珊瑚色像素飞船 -->
            <svg class="claude-badge-logo" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <rect x="1" y="1" width="22" height="22" rx="6" fill="#34312C" />
              <path fill="#D97757" fill-rule="evenodd" clip-rule="evenodd" transform="translate(3.36 3) scale(0.72)" d="M20.998 10.949H24v3.102h-3v3.028h-1.487V20H18v-2.921h-1.487V20H15v-2.921H9V20H7.488v-2.921H6V20H4.487v-2.921H3V14.05H0V10.95h3V5h17.998v5.949zM6 10.949h1.488V8.102H6v2.847zm10.51 0H18V8.102h-1.49v2.847z" />
            </svg>
            <span class="claude-badge-text">
              <span class="claude-badge-friday">Friday</span>
              <span class="claude-badge-times">×</span>
              <span class="claude-badge-claude">Claude Code</span>
              <span class="claude-badge-mode">深度分析</span>
            </span>
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

          <TransitionGroup
            v-if="pendingImages.length > 0"
            tag="div"
            class="image-preview-strip"
            :css="false"
            @enter="onChipEnter"
            @leave="onChipLeave"
          >
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
          </TransitionGroup>

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
                      ref="deepPillEl"
                      type="button"
                      class="toolbar-pill"
                      :aria-label="chatStore.forceDeepAnalysis ? '关闭深度分析' : '开启深度分析'"
                      :aria-pressed="chatStore.forceDeepAnalysis"
                      :class="{ 'toolbar-pill--active': chatStore.forceDeepAnalysis }"
                      @click="toggleDeepAnalysis"
                    >
                      <!-- 激活态：45° 斜置星环（纯 2D 椭圆轨道），Friday × Claude Code 双 logo 对位环绕 -->
                      <span v-if="chatStore.forceDeepAnalysis" class="pill-orbit" aria-hidden="true">
                        <span class="orbit-ring" />
                        <span class="orbit-arm">
                          <span class="orbit-logo">
                            <svg class="orbit-svg orbit-svg--friday" viewBox="0 0 144 216" xmlns="http://www.w3.org/2000/svg">
                              <path d="M0 0H144V72H72Z" fill="#14b8a6" />
                              <path d="M0 72H72L144 144H0Z" fill="#FAF9F5" />
                              <path d="M0 144H72V216Z" fill="#FAF9F5" />
                            </svg>
                          </span>
                        </span>
                        <span class="orbit-arm orbit-arm--alt">
                          <span class="orbit-logo">
                            <svg class="orbit-svg orbit-svg--claude" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                              <path fill="#D97757" fill-rule="evenodd" clip-rule="evenodd" d="M20.998 10.949H24v3.102h-3v3.028h-1.487V20H18v-2.921h-1.487V20H15v-2.921H9V20H7.488v-2.921H6V20H4.487v-2.921H3V14.05H0V10.95h3V5h17.998v5.949zM6 10.949h1.488V8.102H6v2.847zm10.51 0H18V8.102h-1.49v2.847z" />
                            </svg>
                          </span>
                        </span>
                      </span>
                      <span v-else class="icon-[lucide--telescope] text-[14px]" />
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
                      提示：安装 Friday Skills（npx @friday-ai-codes/skills）后，也可以通过 MCP 在 Cursor / Claude Code 中直接使用 Friday 的代码索引与分析能力。
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
                  <span v-if="currentCapabilities.length" class="model-selector__caps" aria-hidden="true">
                    <span
                      v-for="cap in currentCapabilities"
                      :key="cap.key"
                      :class="cap.icon"
                      class="model-selector__cap-icon"
                      :title="cap.title"
                    />
                  </span>
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
                      <div
                        v-for="group in groupedModelOptions"
                        :key="group.credential.id"
                        class="model-group"
                      >
                        <div class="model-group__header">
                          <span class="model-group__name truncate">{{ group.credential.name }}</span>
                          <span v-if="group.credential.is_default" class="model-group__default">默认</span>
                        </div>
                        <button
                          v-for="opt in group.options"
                          :key="opt.key"
                          class="model-row"
                          :class="{ 'model-row--active': opt.key === effectiveSelectionKey }"
                          @click="onSelectCombination(opt)"
                        >
                          <span class="model-row__name">{{ opt.model.id }}</span>
                          <span v-if="modelCapabilities(opt).length" class="model-row__caps">
                            <span
                              v-for="cap in modelCapabilities(opt)"
                              :key="cap.key"
                              class="model-cap"
                              :title="cap.title"
                            >
                              <span :class="cap.icon" class="model-cap__icon" />
                              <span v-if="cap.key === 'context'" class="model-cap__label">{{ cap.label }}</span>
                            </span>
                          </span>
                          <span
                            v-if="opt.key === effectiveSelectionKey"
                            class="icon-[lucide--check] model-row__check"
                          />
                        </button>
                      </div>
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
                ref="sendBtnEl"
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

/* 深度分析模式：Claude Code 徽标从卡片顶部浮出（静置，无晃动）。
   采用 Claude Code 终端的暖黑（#1F1E1C 系）作底，让 Friday 青绿与
   Claude 珊瑚各自保持本色、在中性暗底上并置，而不是互相调和成脏色。 */
.claude-badge {
  position: absolute;
  top: -1rem;
  left: 1.125rem;
  z-index: 11;
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  padding: 0.3125rem 0.75rem 0.3125rem 0.4375rem;
  border-radius: 9999px;
  border: 1px solid hsl(45 8% 26%);
  background: linear-gradient(180deg, hsl(45 8% 16%), hsl(45 10% 11%));
  box-shadow:
    0 6px 16px hsl(30 20% 12% / 0.28),
    inset 0 1px 0 hsl(0 0% 100% / 0.07);
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
  display: inline-flex;
  align-items: baseline;
  gap: 0.3em;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  white-space: nowrap;
}

/* 各品牌保留本色：Friday 青绿 / Claude 珊瑚，中性奶白作为衬底文字 */
.claude-badge-friday {
  color: hsl(168 62% 52%);
}
.claude-badge-times {
  color: hsl(45 8% 52%);
  font-weight: 500;
}
.claude-badge-claude {
  color: hsl(15 76% 68%);
}
.claude-badge-mode {
  color: hsl(48 30% 92%);
}

/* 徽标入场/退场动画由 GSAP 驱动（onBadgeEnter / onBadgeLeave） */

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

/* ======== 深度分析模式边框：双色光点环游 ========
   边框主体保持中性灰（与默认卡片一致），只让一颗 Friday 青绿光点与
   一颗 Claude 珊瑚光点在边框上对向追逐——隐喻两个代理协作，而不是
   把两种高饱和色糊满整圈。通过 @property 注册角度变量使其可被动画插值。 */
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
        hsl(214 32% 87%) 0deg,
        hsl(168 76% 40%) 38deg,
        hsl(168 76% 40% / 0.3) 70deg,
        hsl(214 32% 87%) 110deg,
        hsl(214 32% 87%) 180deg,
        hsl(15 70% 56%) 218deg,
        hsl(15 70% 56% / 0.3) 250deg,
        hsl(214 32% 87%) 290deg,
        hsl(214 32% 87%) 360deg
      )
      border-box;
  animation: deep-border-weave 7s linear infinite;
  box-shadow:
    0 10px 24px hsl(215 28% 17% / 0.09),
    0 1px 2px hsl(215 28% 17% / 0.05);
}
.input-card--deep:focus-within {
  /* 覆盖基础 .input-card:focus-within 的纯色边框，保持光点描边可见。
     注意不要在此改 animation-duration：中途改时长会让动画进度重新映射、光点跳位 */
  border-color: transparent;
  box-shadow:
    0 0 0 3px hsl(168 76% 42% / 0.05),
    0 12px 28px hsl(215 28% 17% / 0.1),
    0 1px 2px hsl(215 28% 17% / 0.05);
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

/* 注意：深度分析模式不要改 textarea 的 padding——输入卡片整体高度会突变，
   导致底部锚定的卡片连同浮动徽标瞬间上下跳动。徽标的首行避让靠
   .claude-badge 的 top 偏移（上移半个徽标以上）解决，布局保持零位移。 */

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
/* 激活态：Claude Code 终端暖黑底 + 珊瑚图标 + 奶白文字，与浮动徽标呼应 */
.toolbar-pill--active {
  border-color: hsl(45 8% 24%);
  background: linear-gradient(180deg, hsl(45 8% 17%), hsl(45 10% 12%));
  color: hsl(48 30% 92%);
  box-shadow: inset 0 1px 0 hsl(0 0% 100% / 0.06);
}
.toolbar-pill--active:hover {
  background: linear-gradient(180deg, hsl(45 8% 21%), hsl(45 10% 15%));
  color: hsl(48 30% 95%);
}
.toolbar-pill--active [class*='icon-'] {
  color: hsl(15 76% 64%);
}

/* ======== 45° 星环（纯 2D 椭圆轨道）：激活态替换望远镜图标 ========
   原 CSS 3D（perspective + preserve-3d + billboard）方案在 20px 这种
   微缩尺寸下，小 perspective 会把贴近视点的 logo 投影成歪斜的大色块，
   看起来像渲染坏掉。改为纯 2D 等价实现：公转臂 rotate(-45deg)
   scaleY(0.45) rotate(θ) 把圆轨道压成斜置椭圆，logo 用精确逆变换
   rotate(-θ) scaleY(1/0.45) rotate(45deg) 抵消，保持永远端正不变形；
   「近大远小」改用同步的 scale + opacity 关键帧模拟。 */
.pill-orbit {
  position: relative;
  display: inline-flex;
  width: 1.25rem;
  height: 1.25rem;
  flex-shrink: 0;
}

/* 轨道描边：独立画一只斜置椭圆，避免被压扁的 border 出现亚像素断笔 */
.orbit-ring {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 16px;
  height: 7.2px;
  margin: -3.6px 0 0 -8px;
  border-radius: 50%;
  border: 1px solid hsl(48 30% 92% / 0.5);
  transform: rotate(-45deg);
}

.orbit-arm {
  position: absolute;
  inset: 0;
  animation: orbit-rev 4.5s linear infinite;
}

.orbit-logo {
  position: absolute;
  left: 50%;
  top: 50%;
  width: 10px;
  height: 10px;
  margin: -5px 0 0 -5px;
  display: flex;
  align-items: center;
  justify-content: center;
  animation: orbit-counter 4.5s linear infinite;
}

.orbit-svg {
  display: block;
  animation: orbit-depth 4.5s linear infinite;
}
.orbit-svg--friday {
  width: 5px;
  height: 7.5px;
}
.orbit-svg--claude {
  width: 7px;
  height: 7px;
}

/* 第二颗星：负延迟半个周期 → 始终与第一颗处于环的对侧（一前一后交替） */
.orbit-arm--alt,
.orbit-arm--alt .orbit-logo,
.orbit-arm--alt .orbit-svg {
  animation-delay: -2.25s;
}

/* 公转：先斜置（-45°）再压扁（scaleY）再转公转角 θ。
   起始相位 -45° 让 0%/50% 恰好落在椭圆最后端/最前端，方便对齐深度动画 */
@keyframes orbit-rev {
  from {
    transform: rotate(-45deg) scaleY(0.45) rotate(-45deg);
  }
  to {
    transform: rotate(-45deg) scaleY(0.45) rotate(315deg);
  }
}

/* 反变换：translateX 上环后按相反顺序逐项抵消（-θ → scaleY 倒数 → +45°），
   logo 全程端正、零形变 */
@keyframes orbit-counter {
  from {
    transform: translateX(8px) rotate(45deg) scaleY(2.2222) rotate(45deg);
  }
  to {
    transform: translateX(8px) rotate(-315deg) scaleY(2.2222) rotate(45deg);
  }
}

/* 深度提示：50% 位于椭圆最前端（最大最亮），0%/100% 绕到最后端（最小最暗） */
@keyframes orbit-depth {
  0%,
  100% {
    transform: scale(0.78);
    opacity: 0.45;
  }
  50% {
    transform: scale(1.18);
    opacity: 1;
  }
}

/* 减弱动效偏好：暂停于负延迟对应的相位帧，双星静止分立环两侧 */
@media (prefers-reduced-motion: reduce) {
  .orbit-arm,
  .orbit-logo,
  .orbit-svg {
    animation-play-state: paused;
  }
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
  min-width: 16.5rem;
  max-height: 21rem;
  overflow-y: auto;
  padding: 0.375rem;
  border-radius: 0.875rem;
  border: 1px solid hsl(214 32% 91% / 0.9);
  background: hsl(0 0% 100% / 0.98);
  backdrop-filter: blur(8px);
  box-shadow:
    0 1px 2px rgba(15, 23, 42, 0.04),
    0 12px 32px -8px rgba(15, 23, 42, 0.16);
  z-index: 9999;
}

/* ——— 分组（按 Provider）——— */
.model-group + .model-group {
  margin-top: 0.25rem;
  padding-top: 0.25rem;
  border-top: 1px solid hsl(214 32% 93%);
}
.model-group__header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.3125rem 0.625rem 0.25rem;
}
.model-group__name {
  min-width: 0;
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  color: hsl(215 16% 56%);
}
.model-group__default {
  flex-shrink: 0;
  border-radius: 0.3125rem;
  background: hsl(168 64% 95%);
  padding: 0 0.3125rem;
  font-size: 0.5625rem;
  line-height: 1.6;
  font-weight: 600;
  color: hsl(168 48% 34%);
}

/* ——— 单行模型项 ——— */
.model-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  padding: 0.4375rem 0.625rem;
  border-radius: 0.5rem;
  border: none;
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s ease;
}
.model-row:hover {
  background: hsl(214 32% 95% / 0.7);
}
.model-row--active {
  background: hsl(168 64% 96%);
}
.model-row__name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8125rem;
  font-weight: 500;
  color: hsl(215 25% 24%);
}
.model-row--active .model-row__name {
  color: hsl(168 52% 30%);
  font-weight: 600;
}
.model-row__check {
  flex-shrink: 0;
  font-size: 0.875rem;
  color: hsl(168 70% 40%);
}

/* 能力：右侧极简内联图标（context 带数字），统一中性灰、无 pill 底，更精致；
   图标 + 文字并存（context）满足无障碍 color-not-only。 */
.model-row__caps {
  display: inline-flex;
  align-items: center;
  gap: 0.4375rem;
  flex-shrink: 0;
  color: hsl(215 13% 60%);
}
.model-cap {
  display: inline-flex;
  align-items: center;
  gap: 0.1875rem;
}
.model-cap__icon {
  font-size: 0.875rem;
}
.model-cap__label {
  font-size: 0.6875rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.model-row--active .model-row__caps {
  color: hsl(168 42% 40%);
}

/* 折叠态触发器内的能力图标（紧凑、纯图标、克制） */
.model-selector__caps {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin-left: 0.125rem;
  padding-left: 0.375rem;
  border-left: 1px solid hsl(214 24% 88%);
}
.model-selector__cap-icon {
  font-size: 0.8125rem;
  color: hsl(215 12% 62%);
}
.model-selector:hover .model-selector__cap-icon {
  color: hsl(215 18% 45%);
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
