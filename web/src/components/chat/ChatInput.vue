<script setup lang="ts">
import type { BranchIndexRow } from '~/api/repositories'
import type { ConversationStatus } from '~/composables/useConversationFrozen'
import type { AvailableModel, ProviderCredentialDto } from '~/types/providerCredential'
import { repositoriesApi } from '~/api/repositories'
import PinConfirmDialog from '~/components/chat/PinConfirmDialog.vue'
import BranchCombobox from '~/components/repository/BranchCombobox.vue'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { extractFirstFeishuDocId } from '~/composables/useFeishuDocDetect'
import { useToast } from '~/composables/useToast'
const emit = defineEmits<{
 'pin-confirmed': [credentialId: string, model: string]
}>
const chatStore = useChatStore
const toast = useToast
const spacesStore = useSpacesStore
const branchRows = ref<BranchIndexRow>
const selectedBranchLocal = ref<string | null>(null)
const primaryRepoId = computed( => {
 const pid = chatStore.selectedSpaceId
 if (!pid)
 return null
 const p = spacesStore.currentSpace?.id === pid ? spacesStore.currentSpace: null
 return p?.repositories?.[0]?.id ?? null
})
const branchNames = computed( => branchRows.value.map(r => r.branch_name))
const recommendedBaseBranch = computed( => {
 const row = branchRows.value.find(r => r.is_base_branch)
 if (row)
 return row.branch_name
 const repo = spacesStore.currentSpace?.repositories?.[0]
 return repo?.default_branch ?? null
})
async function syncChatBranchPicker {
 branchRows.value =
 selectedBranchLocal.value = null
 const pid = chatStore.selectedSpaceId
 if (!pid)
 return
 try {
 if (spacesStore.currentSpace?.id !== pid)
 await spacesStore.fetchSpace(pid)
 }
 catch {
 return
 }
 const rid = primaryRepoId.value
 if (!rid)
 return
 try {
 branchRows.value = await repositoriesApi.getBranchIndexes(rid)
 }
 catch {
 return
 }
 const names = branchRows.value.map(r => r.branch_name)
 const fromStore = chatStore.searchBranchByRepository[rid]
 const fromSession = sessionStorage.getItem(`friday:repo-branch:${rid}`)
 const pick
 = (fromStore && names.includes(fromStore))
 ? fromStore: (fromSession && names.includes(fromSession))
 ? fromSession: null
 if (pick) {
 selectedBranchLocal.value = pick
 }
 else {
 const base = branchRows.value.find(r => r.is_base_branch)
 selectedBranchLocal.value = base?.branch_name ?? names[0] ?? null
 }
 if (selectedBranchLocal.value)
 chatStore.setSearchBranchForRepository(rid, selectedBranchLocal.value)
}
watch(
 => chatStore.selectedSpaceId,
 => {
 void syncChatBranchPicker
 },
 { immediate: true },
)
watch(selectedBranchLocal, (name) => {
 const rid = primaryRepoId.value
 if (rid && name)
 chatStore.setSearchBranchForRepository(rid, name)
})
const inputContent = ref('')
const textarea = ref<HTMLTextAreaElement | null>(null)
const showModelMenu = ref(false)
// ============================================================================
// prefilled_query 自动填充（ Playground → Chat 联动）
// XSS 防御（T-）：仅填充到 inputContent（v-model textarea），不使用 innerHTML 或 v-html
// ============================================================================
const route = useRoute
watch(
 => route.query.prefilled_query,
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
const modelMenuRef = ref<HTMLElement | null>(null)
// ============================================================================
//：model-selector 折叠重构
// - 数据源：providerCredentialStore.activeCredentials × 各凭证 available_models
// - 选项变化弹 PinConfirmDialog → 确认 emit('pin-confirmed', credentialId, model)
// - W1 + W4：空态 / 无对话 / frozen 三态 disabled + tooltip + 双重防御 guard
// ============================================================================
const providerStore = useProviderCredentialStore
const { isSystemAdmin } = usePermission
async function loadCredentialsForChat {
 const sid = chatStore.selectedSpaceId ?? undefined
 try {
 await Promise.all([
 providerStore.fetchCredentials({ scope: 'any', spaceId: sid }),
 providerStore.fetchProviderTypes,
 ])
 }
 catch {
 // 静默；空态 UI 已兜
 }
}
onMounted(loadCredentialsForChat)
watch( => chatStore.selectedSpaceId, loadCredentialsForChat)
onClickOutside(modelMenuRef, => {
 showModelMenu.value = false
})
interface CredentialModelOption {
 credential: ProviderCredentialDto
 model: AvailableModel
 /** 唯一 key：`${credential.id}:${model.id}` */
 key: string
 /** 展示文案：`${credential.name} / ${model.id}` */
 label: string
}
const credentialModelOptions = computed<CredentialModelOption>( => {
 const opts: CredentialModelOption =
 for (const cred of providerStore.activeCredentials) {
 // 兼容历史 sessionStorage 中无 available_models 字段的旧 credential 快照
 const models = cred.available_models ??
 if (models.length > 0) {
 for (const m of models) {
 opts.push({
 credential: cred,
 model: m,
 key: `${cred.id}:${m.id}`,
 label: `${cred.name} / ${m.id}`,
 })
 }
 }
 else {
 // 尚未刷新模型清单 → fallback 到该 Provider 类型的 default_model
 const meta = providerStore.providerTypes.find(
 p => p.provider_type === cred.provider_type,
 )
 const fallbackModel = meta?.default_model
 if (fallbackModel) {
 opts.push({
 credential: cred,
 model: { id: fallbackModel, display_name: fallbackModel },
 key: `${cred.id}:${fallbackModel}`,
 label: `${cred.name} / ${fallbackModel}`,
 })
 }
 }
 }
 // 排序：scope=system 优先 → scope=project；同 scope 内按 credential.name asc → model.id asc
 return opts.sort((a, b) => {
 if (a.credential.scope !== b.credential.scope)
 return a.credential.scope === 'system' ? -1: 1
 if (a.credential.name !== b.credential.name)
 return a.credential.name.localeCompare(b.credential.name)
 return a.model.id.localeCompare(b.model.id)
 })
})
const currentSelectionKey = computed<string | null>( => {
 const conv = chatStore.currentConversation
 if (!conv?.provider_credential_id || !conv.model)
 return null
 return `${conv.provider_credential_id}:${conv.model}`
})
const currentSelectionLabel = computed<string>( => {
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
const isEmpty = computed( => credentialModelOptions.value.length === 0)
const emptyCta = computed( => {
 if (isSystemAdmin.value)
 return { text: '去 admin 添加凭证 →', to: '/admin/providers' }
 const pid = chatStore.selectedSpaceId
 return {
 text: '去空间设置添加凭证 →',
 to: pid ? `/spaces/${pid}/settings#providers`: '/spaces',
 }
})
// PinConfirmDialog 状态
const pinDialogOpen = ref(false)
const pendingOption = ref<CredentialModelOption | null>(null)
const oldProviderName = computed( => {
 const key = currentSelectionKey.value
 if (!key)
 return '未指定'
 const found = credentialModelOptions.value.find(o => o.key === key)
 return found?.credential.name ?? '当前 Provider'
})
const oldModelLabel = computed(
 => chatStore.currentConversation?.model || '默认模型',
)
// [Revision 1 — W1 + W4] frozen 态 disabled 派生
const conversationStatusRef = computed<ConversationStatus>(
 => chatStore.currentConversation?.status ?? 'draft',
)
const frozen = useConversationFrozen(conversationStatusRef, ref(false))
const isConversationFrozen = computed( => frozen.value.isFrozen)
const isSelectorDisabled = computed(
 =>
 isEmpty.value
 || isConversationFrozen.value,
)
const disabledReason = computed<string>( => {
 if (isEmpty.value)
 return '' // 空态用专属 tooltip（CTA 链接），见模板
 if (isConversationFrozen.value)
 return frozen.value.reason || '当前对话已固定，无法切换 Provider / 模型'
 return ''
})
async function onSelectCombination(opt: CredentialModelOption) {
 // [Revision 1 — W1] 顶部双重防御：button:disabled 已拦，再守一道（防 a11y / 测试 emit click）
 if (isSelectorDisabled.value) {
 showModelMenu.value = false
 return
 }
 showModelMenu.value = false
 if (opt.key === currentSelectionKey.value)
 return // 选中相同组合 → noop
 // 记住用户选择（跨新建对话复用）
 chatStore.selectedCredentialModel = opt.key
 // 没有活动对话 → 自动创建对话并绑定模型
 if (!chatStore.currentConversationId) {
 chatStore.selectedModel = opt.model.id
 await chatStore.createNewConversation
 if (!chatStore.currentConversationId)
 return
 // 对话已创建且 model 已设置（createNewConversation 用了 selectedModel），
 // 额外固定 provider_credential_id 避免被四层解析覆盖
 await chatStore.patchConversationProviderAndModel(opt.credential.id, opt.model.id)
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
function handlePinConfirm {
 if (!pendingOption.value)
 return
 const { credential, model } = pendingOption.value
 emit('pin-confirmed', credential.id, model.id)
 // 记住用户选择（跨新建对话复用）
 chatStore.selectedCredentialModel = pendingOption.value.key
 pinDialogOpen.value = false
 pendingOption.value = null
}
function handlePinCancel {
 pendingOption.value = null
 pinDialogOpen.value = false
}
/** 检查当前对话是否已选择模型 */
const hasSelectedModel = computed( => {
 const conv = chatStore.currentConversation
 return !!conv?.model
})
// ============================================================================
// 发送按钮可用性派生（避免「亮色但点了没反应」的误导）
// ============================================================================
const sendDisabledReason = computed<string>( => {
 if (chatStore.isStreaming)
 return '正在生成中，请稍候或先点「停止生成」'
 if (!inputContent.value.trim)
 return ''
 if (!chatStore.selectedSpaceId)
 return '请先在顶部选择一个空间'
 if (isEmpty.value)
 return '当前没有可用的 Provider 凭证，请先在 admin/providers 或空间设置中添加'
 return ''
})
const canSend = computed(
 => !!inputContent.value.trim && !chatStore.isStreaming && !sendDisabledReason.value,
)
async function handleSend {
 const content = inputContent.value.trim
 if (!content)
 return
 if (chatStore.isStreaming) {
 toast.warning('上一条消息正在生成中', '请等待完成或点「停止生成」后再发送')
 return
 }
 // 前置硬校验：没有空间根本无法创建对话
 if (!chatStore.selectedSpaceId) {
 toast.error('请先在顶部选择一个空间')
 return
 }
 // 前置硬校验：没有任何可用 Provider 凭证 → 引导用户去配置
 if (isEmpty.value) {
 toast.error('当前没有可用的 Provider 凭证', '请先在 admin/providers 或空间设置中创建并启用凭证')
 return
 }
 // 没有对话时自动创建（优先使用记忆的选择）
 if (!chatStore.currentConversationId) {
 if (chatStore.selectedCredentialModel) {
 const parts = chatStore.selectedCredentialModel.split(':')
 if (parts.length === 2) {
 const [, modelId] = parts
 chatStore.selectedModel = modelId
 }
 }
 await chatStore.createNewConversation
 if (!chatStore.currentConversationId) {
 toast.error('创建对话失败', chatStore.error || '请稍后重试，或检查网络与登录状态')
 return
 }
 // 创建后 patch 记忆的 credential+model
 if (chatStore.selectedCredentialModel) {
 const parts = chatStore.selectedCredentialModel.split(':')
 if (parts.length === 2) {
 const [credId, modelId] = parts
 try {
 await chatStore.patchConversationProviderAndModel(credId, modelId)
 }
 catch {
 toast.error('绑定 Provider / 模型失败', chatStore.error || '请重新选择 Provider / 模型')
 return
 }
 }
 }
 }
 // 已有对话（包括刚创建的）但没有选择模型，禁止发送
 if (!hasSelectedModel.value) {
 toast.error('请先选择 Provider / 模型')
 return
 }
 const feishuDocId = extractFirstFeishuDocId(content)
 const draft = inputContent.value
 inputContent.value = ''
 nextTick(autoResize)
 try {
 await chatStore.sendMessage(content, feishuDocId ?? undefined)
 }
 finally {
 // sendMessage 内部失败会写 chatStore.error；这里只在草稿丢失但又有错误时回填
 if (chatStore.error && !chatStore.streamingContent && inputContent.value === '') {
 inputContent.value = draft
 nextTick(autoResize)
 }
 }
}
function handleKeydown(e: KeyboardEvent) {
 if (e.key === 'Enter' && !e.shiftKey) {
 e.preventDefault
 handleSend
 }
}
function autoResize {
 const el = textarea.value
 if (!el)
 return
 el.style.height = 'auto'
 el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}
function toggleDeepAnalysis {
 chatStore.forceDeepAnalysis = !chatStore.forceDeepAnalysis
}
function toggleNotifications {
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
 <!-- Phase: 检索分支（空间关联仓库的首个仓库） -->
 <div
 v-if="branchNames.length > 0 && primaryRepoId"
 class="flex flex-col gap-1.5 px-1 pb-2 sm:flex-row sm:items-center sm:gap-3"
 >
 <span class="text-[11px] text-muted-foreground shrink-0">检索分支</span>
 <div class="w-full min-w-0 sm:max-w-xs">
 <BranchCombobox
 v-model="selectedBranchLocal":branches="branchNames":index-rows="branchRows":recommended-branch="recommendedBaseBranch":disabled="chatStore.isStreaming"
 />
 </div>
 </div>
 <!-- 停止按钮 -->
 <div v-if="chatStore.isStreaming" class="flex justify-center pb-2">
 <button class="stop-btn" @click="chatStore.stopStreaming">
 <span class="stop-icon" />
 停止生成
 </button>
 </div>
 <!-- 输入卡片 -->
 <div class="input-card":class="{ 'input-card--disabled': chatStore.isStreaming }">
 <!-- 上层：文本输入 -->
 <textarea
 ref="textarea"
 v-model="inputContent"
 placeholder="给 Friday 发消息..."
 class="input-textarea"
 rows="1":disabled="chatStore.isStreaming"
 @keydown="handleKeydown"
 @input="autoResize"
 />
 <!-- 下层：工具栏 -->
 <div class="input-toolbar">
 <!-- 左侧工具 -->
 <div class="toolbar-left">
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="toolbar-btn":class="{ 'toolbar-btn--active': chatStore.forceDeepAnalysis }"
 @click="toggleDeepAnalysis"
 >
 <span class="icon-[lucide--scan-search] text-[15px]" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ chatStore.forceDeepAnalysis ? '深度分析已开启 · Runner + Claude Code': '点击开启深度分析' }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="toolbar-btn":class="{ 'toolbar-btn--active': chatStore.notificationsEnabled }"
 @click="toggleNotifications"
 >
 <span:class="chatStore.notificationsEnabled ? 'icon-[lucide--bell-ring]': 'icon-[lucide--bell-off]'" class="text-[15px]" />
 </button>
 </TooltipTrigger>
 <TooltipContent side="top">
 <p>{{ chatStore.notificationsEnabled ? '浏览器通知已开启': '点击开启浏览器通知' }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 <!-- 右侧：模型选择 + 发送 -->
 <div class="toolbar-right">
 <!-- 模型选择器（凭证/模型组合） -->
 <div ref="modelMenuRef" class="relative">
 <!-- 三态①：空态（无可用凭证）→ CTA tooltip -->
 <TooltipProvider v-if="isEmpty":delay-duration="200">
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
 <RouterLink:to="emptyCta.to" class="text-primary hover:underline">
 {{ emptyCta.text }}
 </RouterLink>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <!-- 三态②：有凭证但 disabled（无对话 / frozen）→ 原因 tooltip -->
 <TooltipProvider v-else-if="isSelectorDisabled":delay-duration="200">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class="model-selector model-selector--disabled"
 disabled:data-test-disabled-reason="disabledReason"
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
 <button v-else class="model-selector" @click="showModelMenu = !showModelMenu">
 <span class="model-label">{{ currentSelectionLabel }}</span>
 <span
 class="icon-[lucide--chevron-down] text-[11px] transition-transform":class="{ 'rotate-180': showModelMenu }"
 />
 </button>
 <Transition
 enter-active-class="transition-all duration-150 ease-out"
 leave-active-class="transition-all duration-100 ease-in"
 enter-from-class="opacity-0 translate-y-1 scale-95"
 enter-to-class="opacity-100 translate-y-0 scale-100"
 leave-from-class="opacity-100 translate-y-0 scale-100"
 leave-to-class="opacity-0 translate-y-1 scale-95"
 >
 <div v-if="showModelMenu && !isSelectorDisabled" class="model-menu">
 <button
 v-for="opt in credentialModelOptions":key="opt.key"
 class="model-menu-item":class="{ 'model-menu-item--active': opt.key === currentSelectionKey }"
 @click="onSelectCombination(opt)"
 >
 <span class="truncate">{{ opt.label }}</span>
 <span
 v-if="opt.key === currentSelectionKey"
 class="icon-[lucide--check] text-xs text-primary shrink-0"
 />
 </button>
 </div>
 </Transition>
 </div>
 <!-- PinConfirmDialog（chat 路径凭证+模型切换确认） -->
 <PinConfirmDialog
 v-model:open="pinDialogOpen":old-provider-name="oldProviderName":old-model="oldModelLabel":new-provider-name="pendingOption?.credential.name ?? ''":new-model="pendingOption?.model.id ?? ''":message-count="chatStore.messages.length"
 @confirm="handlePinConfirm"
 @cancel="handlePinCancel"
 />
 <!-- 发送按钮 -->
 <button
 class="send-btn":class="{ 'send-btn--active': canSend }":disabled="!canSend":title="sendDisabledReason || '发送'"
 @click="handleSend"
 >
 <span class="icon-[lucide--arrow-up] text-sm" />
 </button>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
<style scoped>
.chat-input-dock {
 padding: 0 1rem 1.25rem;
 background: linear-gradient(to top, hsl(210 40% 98%) 60%, hsl(210 40% 98% / 0.95) 75%, hsl(210 40% 98% / 0) 100%);
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
.stop-btn {
 display: inline-flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.375rem 0.875rem;
 border-radius: 9999px;
 font-size: 0.75rem;
 font-weight: 500;
 color: hsl(215 16% 47%);
 background: white;
 border: 1px solid hsl(214 32% 91%);
 cursor: pointer;
 transition: all 0.15s;
 box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.stop-btn:hover {
 border-color: hsl(0 72% 51% / 0.3);
 color: hsl(0 72% 51%);
 background: hsl(0 72% 51% / 0.04);
}
.stop-icon {
 width: 10px;
 height: 10px;
 border-radius: 2px;
 background: currentColor;
}
/* ======== 输入卡片 ======== */
.input-card {
 border: 1px solid hsl(214 32% 88%);
 border-radius: 1.25rem;
 background: white;
 box-shadow:
 0 1px 3px rgba(0, 0, 0, 0.06),
 0 4px 16px rgba(0, 0, 0, 0.04),
 0 8px 32px rgba(0, 0, 0, 0.02);
 transition:
 border-color 0.2s,
 box-shadow 0.2s;
 overflow: hidden;
}
.input-card:focus-within {
 border-color: hsl(168 76% 42% / 0.5);
 box-shadow:
 0 0 0 3px hsl(168 76% 42% / 0.06),
 0 1px 3px rgba(0, 0, 0, 0.06),
 0 4px 16px rgba(0, 0, 0, 0.04);
}
.input-card--disabled {
 opacity: 0.6;
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
.input-textarea:placeholder {
 color: hsl(215 16% 60%);
}
.input-textarea:disabled {
 cursor: not-allowed;
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
.model-menu {
 position: absolute;
 bottom: calc(100% + 0.375rem);
 right: 0;
 min-width: 12rem;
 max-height: 16rem;
 overflow-y: auto;
 padding: 0.25rem;
 border-radius: 0.75rem;
 border: 1px solid hsl(214 32% 91%);
 background: white;
 box-shadow:
 0 4px 16px rgba(0, 0, 0, 0.08),
 0 8px 32px rgba(0, 0, 0, 0.04);
 z-index: 50;
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
</style>
