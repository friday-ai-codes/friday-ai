/**
 * Chat Store — 对话状态管理
 *
 * 管理对话列表、当前对话、消息列表、流式状态、用户偏好。
 * 使用 setup function 风格（与 projects.ts 一致）。
 */
import type { ChatRole, CodingErrorData, CodingProgressData, CodingResultData, CodingSessionRuntime, Conversation, ConversationMessage, ConversationRuntime, DeepAnalysisLog, ExportToFeishuRequest, ExportToFeishuResponse, SSEEvent, StreamTimelineItem } from '~/types/chat'
import type { ProviderType } from '~/types/providerCredential'
import {
 confirmCodingSession as apiConfirmCodingSession,
 confirmCodingSessionWithBranch as apiConfirmCodingSessionWithBranch,
 createConversation,
 deleteConversation,
 exportToFeishu,
 getConversationDetail,
 getConversationRuntime,
 interruptConversation,
 listConversations,
 patchConversation,
} from '~/api/chat'
import { ApiError, get as apiGet } from '~/api/client'
import { connectSSE, getCurrentRunId } from '~/composables/useSSEStream'
import { useWebPush } from '~/composables/useWebPush'
/** Phase：preflight missing payload 契约。 */
export interface CredentialMissingPayload {
 missingProvider: ProviderType
 scopeAttempted: string
 recommendedAction: string
}
/** Phase：SSE ERROR context_window_exceeded payload 契约。 */
export interface ContextExceededPayload {
 estimated_tokens: number
 max_tokens: number
 exceeded_by: number
 model: string
 recommended_actions: Array<{ id: string, label: string, action_type: string, target: string }>
}
export const useChatStore = defineStore('chat', => {
 const { requestAndEnableWebPush, webPushReady } = useWebPush
 // ========================================================================
 // State
 // ========================================================================
 const conversations = ref<Conversation>
 const currentConversationId = ref<string | null>(null)
 const pendingConversation = ref<Conversation | null>(null)
 const messages = ref<ConversationMessage>
 const loading = ref(false)
 const messagesLoading = ref(false)
 const error = ref<string | null>(null)
 // 流式状态
 const isStreaming = ref(false)
 const streamingContent = ref('')
 const streamingThinking = ref('')
 const streamingToolCalls = ref<Array<{
 id: string
 name: string
 input: Record<string, unknown>
 result?: string
 status: 'running' | 'done'
 }>>
 const streamingTimeline = ref<StreamTimelineItem>
 const streamingMessageId = ref('')
 const streamingMetadata = ref<Record<string, unknown> | null>(null)
 const abortController = ref<AbortController | null>(null)
 const streamingStatus = ref<'streaming' | 'interrupted' | 'budget_exceeded' | null>(null)
 const budgetWarning = ref<number | null>(null)
 // 叙述/正文分离：工具调用前后的文本归为叙述，最终文本为正文
 const streamingNarrations = ref<string>
 const streamingPendingText = ref('')
 // 深度分析实时日志
 const deepAnalysisLogs = ref<DeepAnalysisLog>
 const deepAnalysisSessionId = ref<string | null>(null)
 const restoredRuntimeConversationId = ref<string | null>(null)
 // 编码会话状态 (Phase)
 const activeCodingSession = ref<{
 sessionId: string
 status: 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
 isConfirming: boolean
 confirmationStep?: 'branch_name' | 'commit_message' | 'pr_review'
 } | null>(null)
 const codingProgress = ref<CodingProgressData | null>(null)
 const codingResult = ref<CodingResultData | null>(null)
 const codingError = ref<CodingErrorData | null>(null)
 // 编码确认数据 (Phase)
 const commitConfirmData = ref<{
 suggestedCommitMessage: string
 conflictCheck: {
 has_conflicts?: boolean
 conflicting_files?: string
 behind_by?: number
 suggestion?: string
 } | null
 } | null>(null)
 const prConfirmData = ref<{
 suggestedPrTitle: string
 suggestedPrDescription: string
 targetBranch: string
 branchUrl: string
 } | null>(null)
 const diffSummaryData = ref<{
 files?: Array<{ path: string, additions: number, deletions: number, change_type: string }>
 total_additions?: number
 total_deletions?: number
 truncated?: boolean
 } | null>(null)
 // Phase：凭证缺失前置探测 payload（供 ChatMessageArea 渲染 Card）
 const credentialMissingPayload = ref<CredentialMissingPayload | null>(null)
 // Phase：上下文超限 SSE payload（供 ChatMessageArea 渲染 ContextExceededCard）
 const lastContextExceeded = ref<ContextExceededPayload | null>(null)
 // 已完成确认步骤记录（ 折叠摘要）
 const completedConfirmSteps = ref<Array<{
 step: string
 summary: string
 }>>
 // 导出多选模式 (Phase)
 const isExportSelectMode = ref(false)
 const selectedMessageIds = ref<Set<string>>(new Set)
 // Phase 感知状态（graph 运行态）
 const currentPhase = ref<string | null>(null)
 const taskProgress = ref<{ completed: number, total: number } | null>(null)
 const isInterrupting = ref(false)
 let interruptTimeout: ReturnType<typeof setTimeout> | null = null
 let runtimePollTimer: ReturnType<typeof setTimeout> | null = null
 function isTimelineToolItem(item: StreamTimelineItem): item is Extract<StreamTimelineItem, { kind: 'tool' }> {
 return item.kind === 'tool'
 }
 // 重试状态：记录最后失败的用户消息
 const lastFailedContent = ref<string | null>(null)
 // 侧边栏状态
 const sidebarCollapsed = ref(false)
 // 用户偏好（localStorage 持久化）
 const selectedSpaceId = useLocalStorage<string | null>('chat-space-id', null)
 const selectedRole = useLocalStorage<ChatRole>('chat-role', 'developer')
 const selectedModel = useLocalStorage<string>('chat-model', '__default__')
 /** 记忆上次选择的 credential+model 组合（格式：credentialId:modelId） */
 const selectedCredentialModel = useLocalStorage<string>('chat-credential-model', '')
 const forceDeepAnalysis = useLocalStorage<boolean>('chat-force-deep-analysis', false)
 const notificationsEnabled = useLocalStorage<boolean>('chat-notifications-enabled', false)
 // ========================================================================
 // Getters
 // ========================================================================
 const currentConversation = computed( =>
 conversations.value.find(c => c.id === currentConversationId.value)
 ?? (pendingConversation.value?.id === currentConversationId.value ? pendingConversation.value: null),
 )
 const hasConversation = computed( => currentConversationId.value !== null)
 // ========================================================================
 // Actions
 // ========================================================================
 async function fetchConversations {
 loading.value = true
 error.value = null
 try {
 conversations.value = await listConversations
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取对话列表失败'
 }
 finally {
 loading.value = false
 }
 }
 async function selectConversation(id: string) {
 stopRuntimePolling
 pendingConversation.value = null
 currentConversationId.value = id
 syncConversationToURL(id)
 messagesLoading.value = true
 error.value = null
 try {
 const detail = await getConversationDetail(id)
 messages.value = detail.messages
 activeCodingSession.value = null
 codingProgress.value = null
 codingResult.value = null
 codingError.value = null
 commitConfirmData.value = null
 prConfirmData.value = null
 diffSummaryData.value = null
 completedConfirmSteps.value =
 await restoreConversationRuntime(id)
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取对话详情失败'
 }
 finally {
 messagesLoading.value = false
 }
 }
 async function createNewConversation {
 stopRuntimePolling
 pendingConversation.value = null
 currentConversationId.value = null
 syncConversationToURL(null)
 messages.value =
 error.value = null
 resetStreamingState
 }
 async function removeConversation(id: string) {
 try {
 await deleteConversation(id)
 conversations.value = conversations.value.filter(c => c.id !== id)
 if (currentConversationId.value === id) {
 currentConversationId.value = null
 messages.value =
 }
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '删除对话失败'
 }
 }
 /**
 * UAT 第 3 项 hotfix：把 ChatHeader pin-confirmed 接到后端。
 *
 * 流程：
 * 1. PATCH /chat/conversations/:id/ {provider_credential_id}
 * 2. 成功 → 用响应直接覆盖 conversations 中对应条目（含新 status + provider_credential_id）
 * → currentConversation getter 反映新值 → ChatHeader props.currentCredentialId 反向回流
 * 3. 失败 → 写 error.value 并 rethrow，让 ChatHeader handleConfirm 既有 try/catch 接住
 * （PinConfirmDialog 通过 defineExpose showError 弹错；store action 不能 swallow）
 */
 async function patchConversationCredential(credentialId: string) {
 if (!currentConversationId.value) {
 const msg = '当前没有活动对话，无法切换 Provider 凭证'
 error.value = msg
 throw new Error(msg)
 }
 try {
 const updated = await patchConversation(
 currentConversationId.value,
 { provider_credential_id: credentialId },
 )
 const idx = conversations.value.findIndex(c => c.id === updated.id)
 if (idx >= 0) {
 conversations.value[idx] = { ...conversations.value[idx], ...updated }
 }
 else if (pendingConversation.value?.id === updated.id) {
 pendingConversation.value = { ...pendingConversation.value, ...updated }
 }
 error.value = null
 return updated
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '切换 Provider 凭证失败'
 throw e
 }
 }
 /**
 * UX 重设计：chat 路径折叠「凭证 + 模型」为单选时，PATCH 双字段。
 *
 * 用户在 ChatInput model-selector 选择「凭证/模型组合」并通过 PinConfirmDialog
 * 确认后调本 action。与 patchConversationCredential 区别：单次请求同时携带
 * provider_credential_id + model，避免两次 PATCH 中间态出现「凭证已切但模型仍是旧
 * Provider 的」非法组合。
 *
 * 失败语义同 patchConversationCredential：throw + 写 error.value，
 * 由消费方（PinConfirmDialog defineExpose showError 或全局 toast）兜错。
 */
 async function patchConversationProviderAndModel(
 credentialId: string,
 model: string,
 ) {
 if (!currentConversationId.value) {
 const msg = '当前没有活动对话，无法切换 Provider / 模型'
 error.value = msg
 throw new Error(msg)
 }
 try {
 const updated = await patchConversation(
 currentConversationId.value,
 { provider_credential_id: credentialId, model },
 )
 const idx = conversations.value.findIndex(c => c.id === updated.id)
 if (idx >= 0) {
 conversations.value[idx] = { ...conversations.value[idx], ...updated }
 }
 else if (pendingConversation.value?.id === updated.id) {
 pendingConversation.value = { ...pendingConversation.value, ...updated }
 }
 error.value = null
 return updated
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '切换 Provider / 模型失败'
 throw e
 }
 }
 async function stopStreaming {
 if (!currentConversationId.value)
 return
 // 乐观更新：立即进入"正在中断"过渡态
 isInterrupting.value = true
 streamingStatus.value = 'interrupted'
 // 3 秒超时：若仍未收到 message_complete，提示中断可能未完成
 if (interruptTimeout)
 clearTimeout(interruptTimeout)
 interruptTimeout = setTimeout( => {
 if (isInterrupting.value) {
 console.warn('[Chat] 中断超时，中断可能未完成')
 }
 }, 3000)
 // 先调 interrupt API 通知后端取消 SDK task
 try {
 await interruptConversation(currentConversationId.value)
 }
 catch {
 // 忽略错误（对话可能已结束）
 }
 // 1 秒后强制 abort SSE 连接
 if (abortController.value) {
 const controller = abortController.value
 setTimeout( => {
 if (abortController.value === controller) {
 controller.abort
 abortController.value = null
 stopRuntimePolling
 isStreaming.value = false
 }
 }, 1000)
 }
 }
 function toggleSidebar {
 sidebarCollapsed.value = !sidebarCollapsed.value
 }
 function resolveModelForNewConversation: string | undefined {
 const providerStore = useProviderCredentialStore
 const allModels = providerStore.allAvailableModels
 if (selectedCredentialModel.value) {
 const parts = selectedCredentialModel.value.split(':')
 if (parts.length === 2)
 return parts[1]
 }
 if (selectedModel.value !== '__default__' && selectedModel.value)
 return selectedModel.value
 if (allModels.length >= 1) {
 selectedModel.value = allModels[0].modelId
 selectedCredentialModel.value = `${allModels[0].credentialId}:${allModels[0].modelId}`
 return allModels[0].modelId
 }
 return undefined
 }
 function clearCurrentConversation {
 stopRuntimePolling
 pendingConversation.value = null
 currentConversationId.value = null
 syncConversationToURL(null)
 messages.value =
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingToolCalls.value =
 streamingTimeline.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
 streamingNarrations.value =
 deepAnalysisLogs.value =
 deepAnalysisSessionId.value = null
 streamingPendingText.value = ''
 restoredRuntimeConversationId.value = null
 }
 function resetStreamingState {
 isStreaming.value = false
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingToolCalls.value =
 streamingTimeline.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
 streamingStatus.value = null
 streamingNarrations.value =
 streamingPendingText.value = ''
 deepAnalysisLogs.value =
 deepAnalysisSessionId.value = null
 budgetWarning.value = null
 restoredRuntimeConversationId.value = null
 currentPhase.value = null
 taskProgress.value = null
 isInterrupting.value = false
 commitConfirmData.value = null
 prConfirmData.value = null
 diffSummaryData.value = null
 // completedConfirmSteps 不清理（保留已确认步骤给后续卡片展示）
 // 不清理 activeCodingSession / codingResult / codingError（保留给 UI 展示）
 codingProgress.value = null
 if (interruptTimeout) {
 clearTimeout(interruptTimeout)
 interruptTimeout = null
 }
 }
 function stopRuntimePolling {
 if (runtimePollTimer) {
 clearTimeout(runtimePollTimer)
 runtimePollTimer = null
 }
 }
 function scheduleRuntimePoll(id: string, delay = 2000) {
 stopRuntimePolling
 runtimePollTimer = setTimeout( => {
 void pollConversationRuntime(id)
 }, delay)
 }
 function applyRuntimeSnapshot(runtime: ConversationRuntime) {
 isStreaming.value = true
 streamingStatus.value = 'streaming'
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingPendingText.value = ''
 streamingMetadata.value = null
 streamingMessageId.value = ''
 deepAnalysisSessionId.value = runtime.session_id || null
 deepAnalysisLogs.value = runtime.logs ||
 restoredRuntimeConversationId.value = runtime.conversation_id
 currentPhase.value = runtime.phase || null
 taskProgress.value = runtime.task_progress || null
 if (runtime.mode === 'deep_analysis') {
 streamingToolCalls.value = [
 {
 id: runtime.session_id || 'deep-analysis-runtime',
 name: 'mcp__chat-tools__deep_analysis',
 input: runtime.task_description ? { task_description: runtime.task_description }: {},
 status: 'running',
 },
 ]
 streamingTimeline.value = [
 {
 id: runtime.session_id || 'deep-analysis-runtime',
 kind: 'tool',
 name: 'mcp__chat-tools__deep_analysis',
 input: runtime.task_description ? { task_description: runtime.task_description }: {},
 status: 'running',
 },
 ]
 }
 else if (runtime.mode === 'coding' && runtime.coding_session) {
 // 恢复编码会话状态
 const cs = runtime.coding_session as CodingSessionRuntime
 const csStatus = cs.status as 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed'
 activeCodingSession.value = {
 sessionId: cs.id,
 status: csStatus,
 isConfirming: false,
 confirmationStep: (cs.confirmation_step as 'branch_name' | 'commit_message' | 'pr_review') || undefined,
 }
 // 恢复确认数据（ 页面刷新恢复）
 if (csStatus === 'awaiting_confirmation') {
 isStreaming.value = false // 确认态不锁定输入框
 if (cs.confirmation_step === 'commit_message') {
 commitConfirmData.value = {
 suggestedCommitMessage: cs.suggested_commit_message || '',
 conflictCheck: (cs.conflict_check_result as typeof commitConfirmData.value extends null ? never: NonNullable<typeof commitConfirmData.value>['conflictCheck']) || null,
 }
 }
 else if (cs.confirmation_step === 'pr_review') {
 prConfirmData.value = {
 suggestedPrTitle: cs.suggested_pr_title || '',
 suggestedPrDescription: cs.suggested_pr_description || '',
 targetBranch: cs.target_branch || 'main',
 branchUrl: cs.branch_url || '',
 }
 }
 }
 streamingToolCalls.value =
 streamingTimeline.value =
 }
 else {
 streamingToolCalls.value =
 streamingTimeline.value =
 if (runtime.progress_message)
 streamingPendingText.value = runtime.progress_message
 }
 // 后端 _StreamingSnapshot 把 SSE 流期间的累积态写到了 OrchestrationRun.metadata，
 // runtime API 透传 streaming_snapshot 字段。刷新场景：SSE 已断、SSE 内存状态全
 // 丢；用 snapshot 把 streaming UI 恢复到刷新前的样子，避免「空气泡 + 正在整理
 // 回答」窒息体验。
 //
 // 放在 mode 分支之后：snapshot 比 deep_analysis / coding 模式的「占位 tool」
 // 更准确（snapshot 里通常已经包含同名 tool 的真实进度），有 snapshot 时覆盖
 // 占位；老对话 / 老 runtime 没 snapshot 时退回到占位逻辑，保持向后兼容。
 const snap = runtime.streaming_snapshot
 const snapNonEmpty = !!snap && (
 !!snap.pending_text
 || !!snap.thinking
 || (Array.isArray(snap.tool_calls) && snap.tool_calls.length > 0)
 || (Array.isArray(snap.timeline) && snap.timeline.length > 0)
 || (Array.isArray(snap.narrations) && snap.narrations.length > 0)
 )
 if (snap && snapNonEmpty) {
 streamingPendingText.value = snap.pending_text || ''
 streamingThinking.value = snap.thinking || ''
 streamingNarrations.value = Array.isArray(snap.narrations) ? [...snap.narrations]:
 streamingToolCalls.value = Array.isArray(snap.tool_calls)
 ? snap.tool_calls.map(tc => ({
 id: tc.id,
 name: tc.name,
 input: tc.input || {},
 result: tc.result == null ? undefined: tc.result,
 status: tc.status === 'done' ? 'done': 'running',
 batch_id: tc.batch_id == null ? undefined: tc.batch_id,
 })):
 streamingTimeline.value = Array.isArray(snap.timeline) ? [...snap.timeline]:
 }
 }
 function appendTimelineText(kind: 'thinking' | 'narration', text: string) {
 if (!text)
 return
 const last = streamingTimeline.value[streamingTimeline.value.length - 1]
 if (last && last.kind === kind) {
 last.text += text
 return
 }
 streamingTimeline.value.push({
 id: crypto.randomUUID,
 kind,
 text,
 })
 }
 function flushPendingNarrationToTimeline {
 if (!streamingPendingText.value.trim)
 return
 appendTimelineText('narration', streamingPendingText.value)
 streamingNarrations.value.push(streamingPendingText.value)
 streamingPendingText.value = ''
 }
 async function hydrateConversationMessages(id: string) {
 const detail = await getConversationDetail(id)
 messages.value = detail.messages
 }
 async function pollConversationRuntime(id: string) {
 if (currentConversationId.value !== id)
 return
 try {
 const runtime = await getConversationRuntime(id)
 if (runtime.active) {
 applyRuntimeSnapshot(runtime)
 // 检查 deep analysis 是否已失败（后端回调丢失或 resume 出错）
 const failedStatuses = ['error', 'timeout', 'cancelled']
 if (
 runtime.mode === 'deep_analysis'
 && runtime.status
 && failedStatuses.includes(runtime.status)
 ) {
 error.value = runtime.progress_message || '深度分析任务失败'
 stopRuntimePolling
 resetStreamingState
 await hydrateConversationMessages(id)
 return
 }
 if (
 runtime.deep_analysis_status
 && failedStatuses.includes(runtime.deep_analysis_status)
 ) {
 error.value = runtime.deep_analysis_error || '深度分析任务失败'
 stopRuntimePolling
 resetStreamingState
 await hydrateConversationMessages(id)
 return
 }
 scheduleRuntimePoll(id)
 return
 }
 // 检查是否有编码完成/失败
 const cs = runtime.coding_session as CodingSessionRuntime | undefined
 if (cs && cs.status === 'completed') {
 codingResult.value = {
 sessionId: cs.id,
 prUrl: cs.pr_url || '',
 branchName: cs.branch_name || '',
 modifiedFilesCount: cs.affected_files?.length || 0,
 branchUrl: cs.branch_url || '',
 }
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'completed'
 }
 }
 else if (cs && cs.status === 'failed') {
 codingError.value = {
 sessionId: cs.id,
 errorMessage: cs.error_message || '编码失败',
 }
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'failed'
 }
 }
 // 检查 deep analysis 失败（非活跃态）
 const failedStatuses = ['error', 'timeout', 'cancelled']
 if (
 runtime.deep_analysis_status
 && failedStatuses.includes(runtime.deep_analysis_status)
 ) {
 error.value = runtime.deep_analysis_error || '深度分析任务失败'
 }
 stopRuntimePolling
 const completedSessionId = deepAnalysisSessionId.value
 // 无条件刷新消息：deep_analysis 等异步任务完成后，消息已由后端落库，
 // 但前端 SSE 断开后可能尚未同步。wasRestoringRuntime 限制会漏掉
 // 任务极快失败（第一次轮询即终态）的场景。
 await hydrateConversationMessages(id)
 if (completedSessionId)
 _notifyDeepAnalysisComplete(completedSessionId)
 resetStreamingState
 }
 catch {
 scheduleRuntimePoll(id, 4000)
 }
 }
 async function restoreConversationRuntime(id: string) {
 try {
 const runtime = await getConversationRuntime(id)
 if (!runtime.active) {
 resetStreamingState
 return
 }
 applyRuntimeSnapshot(runtime)
 scheduleRuntimePoll(id)
 }
 catch {
 resetStreamingState
 }
 }
 // ========================================================================
 // SSE 流式消息 (Phase, Plan)
 // ========================================================================
 function handleSSEEvent(event: SSEEvent) {
 // 用户已中断，忽略后续事件（仅保留 message_complete 用于清理）
 if (streamingStatus.value === 'interrupted' && event.type !== 'message_complete')
 return
 switch (event.type) {
 case 'text_delta':
 streamingPendingText.value += event.text || ''
 break
 case 'thinking':
 streamingThinking.value += event.thinking || ''
 appendTimelineText('thinking', event.thinking || '')
 break
 case 'tool_use_start': {
 // 工具调用前的文本归为叙述（如"让我搜索一下..."）
 flushPendingNarrationToTimeline
 const existing = streamingToolCalls.value.find(t => t.id === event.tool_call_id)
 if (!existing) {
 streamingToolCalls.value.push({
 id: event.tool_call_id || '',
 name: event.tool_name || '',
 input: (event.input as Record<string, unknown>) || {},
 status: 'running',
 })
 }
 else if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0) {
 existing.input = event.input as Record<string, unknown>
 }
 const timelineTool = streamingTimeline.value.find((item): item is Extract<StreamTimelineItem, { kind: 'tool' }> =>
 isTimelineToolItem(item) && item.id === event.tool_call_id,
 )
 if (!timelineTool) {
 streamingTimeline.value.push({
 id: event.tool_call_id || crypto.randomUUID,
 kind: 'tool',
 name: event.tool_name || '',
 input: (event.input as Record<string, unknown>) || {},
 status: 'running',
 batch_id: event.batch_id || undefined,
 })
 }
 else {
 timelineTool.name = event.tool_name || timelineTool.name
 if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
 timelineTool.input = event.input as Record<string, unknown>
 if (event.batch_id && !timelineTool.batch_id)
 timelineTool.batch_id = event.batch_id
 }
 break
 }
 case 'tool_use_result': {
 // 防御性序列化：后端历史路径里 chat_runner 曾经把 dict 直接塞进 result，
 // 前端直接 `as string` 会得到 object，后续 JSON.parse 会因为隐式 toString
 // 成 "[object Object]" 而失败（典型现象：CodingPlanCard 的 sessionId 解析
 // 为空 → confirm URL 变成 /coding-sessions//confirm/ → 404）。
 // 这里统一把任何非 string 的 result 序列化为 JSON 字符串。
 const normalizeResult = (raw: unknown): string | undefined => {
 if (raw === null || raw === undefined)
 return undefined
 if (typeof raw === 'string')
 return raw
 try {
 return JSON.stringify(raw)
 }
 catch {
 return String(raw)
 }
 }
 const normalizedResult = normalizeResult(event.result)
 const tc = streamingToolCalls.value.find(t => t.id === event.tool_call_id)
 if (tc) {
 if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
 tc.input = event.input as Record<string, unknown>
 if (normalizedResult !== undefined)
 tc.result = normalizedResult
 tc.status = 'done'
 }
 const timelineTool = streamingTimeline.value.find((item): item is Extract<StreamTimelineItem, { kind: 'tool' }> =>
 isTimelineToolItem(item) && item.id === event.tool_call_id,
 )
 if (timelineTool) {
 if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
 timelineTool.input = event.input as Record<string, unknown>
 if (normalizedResult !== undefined)
 timelineTool.result = normalizedResult
 timelineTool.status = 'done'
 if (event.batch_id && !timelineTool.batch_id)
 timelineTool.batch_id = event.batch_id
 }
 break
 }
 case 'message_complete': {
 // deep_analysis 返回结果在 final_answer/result 中（text_delta 被过滤）
 const finalAnswer = event.final_answer || event.result || ''
 if (finalAnswer) {
 streamingContent.value = finalAnswer
 }
 else {
 streamingContent.value = streamingPendingText.value
 }
 streamingPendingText.value = ''
 if (event.message_id)
 streamingMessageId.value = event.message_id
 streamingMetadata.value = {
 ...(streamingMetadata.value || {}),
 model: event.model,
 usage: event.usage,
 input_tokens: event.usage?.input_tokens,
 output_tokens: event.usage?.output_tokens,
 cost_usd: event.cost_usd,
 status: event.status,
 // Phase：max_turns 用尽时后端走 graceful degrade
 // (status=completed + degraded=true)，把 flag 透传到 metadata
 // 供 UI 差异化展示「已尽力但不完整」，不再当 error 处理。
 degraded: (event as { degraded?: boolean }).degraded,
 degraded_reason: (event as { degraded_reason?: string }).degraded_reason,
 }
 if (event.status === 'interrupted')
 streamingStatus.value = 'interrupted'
 if (event.status === 'budget_exceeded')
 streamingStatus.value = 'budget_exceeded'
 // 重置 phase 感知状态
 currentPhase.value = null
 taskProgress.value = null
 isInterrupting.value = false
 if (interruptTimeout) {
 clearTimeout(interruptTimeout)
 interruptTimeout = null
 }
 // 深度分析完成时发送浏览器通知
 if (finalAnswer && deepAnalysisSessionId.value)
 _notifyDeepAnalysisComplete
 break
 }
 case 'phase_transition':
 currentPhase.value = event.phase || null
 if (event.blocking_task_count != null)
 taskProgress.value = { completed: 0, total: event.blocking_task_count }
 break
 case 'task_progress':
 taskProgress.value = { completed: event.completed_count || 0, total: event.total_count || 0 }
 break
 case 'budget_warning':
 budgetWarning.value = event.budget_usage_percent || null
 break
 case 'deep_analysis_progress': {
 const logType = event.log_type || 'info'
 const logContent = event.content || ''
 const sid = event.session_id || ''
 if (sid && !deepAnalysisSessionId.value)
 deepAnalysisSessionId.value = sid
 if (logContent)
 deepAnalysisLogs.value.push({ type: logType, content: logContent, ts: Date.now })
 break
 }
 case 'title_generated':
 // 更新当前对话标题
 if (event.title) {
 const conv = conversations.value.find(c => c.id === currentConversationId.value)
 if (conv)
 conv.title = event.title
 else if (pendingConversation.value?.id === currentConversationId.value)
 pendingConversation.value = { ...pendingConversation.value, title: event.title }
 }
 break
 case 'doc_summary':
 // 飞书文档摘要事件 -- 存入 streamingMetadata 供 ChatMessageBubble 渲染
 if (!streamingMetadata.value)
 streamingMetadata.value = {}
 streamingMetadata.value.docSummary = {
 type: 'summary' as const,
 title: event.doc_title,
 wordCount: event.word_count,
 preview: event.preview,
 truncated: event.truncated,
 truncatedLength: event.truncated_length,
 }
 break
 case 'doc_error':
 // 飞书文档错误事件 -- 存入 streamingMetadata 供 ChatMessageBubble 渲染
 if (!streamingMetadata.value)
 streamingMetadata.value = {}
 streamingMetadata.value.docSummary = {
 type: 'error' as const,
 errorType: event.error_type,
 errorMessage: event.message,
 }
 break
 case 'coding_progress': {
 codingProgress.value = {
 sessionId: event.coding_session_id || '',
 steps: event.steps ||,
 modifiedFilesCount: event.modified_files_count || 0,
 modifiedFiles: event.modified_files ||,
 recentToolCalls: event.recent_tool_calls ||,
 }
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'running'
 }
 break
 }
 case 'coding_complete': {
 codingResult.value = {
 sessionId: event.coding_session_id || '',
 prUrl: event.pr_url || '',
 branchName: event.branch_name || '',
 modifiedFilesCount: event.modified_files_count || 0,
 branchUrl: event.branch_url || '',
 }
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'completed'
 }
 isStreaming.value = false
 break
 }
 case 'coding_failed': {
 codingError.value = {
 sessionId: event.coding_session_id || '',
 errorMessage: event.message || '编码失败',
 }
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'failed'
 }
 isStreaming.value = false
 break
 }
 case 'awaiting_commit_confirm': {
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'awaiting_confirmation'
 activeCodingSession.value.confirmationStep = 'commit_message'
 }
 commitConfirmData.value = {
 suggestedCommitMessage: event.suggested_commit_message || '',
 conflictCheck: null,
 }
 // 恢复输入框（非 streaming 态）
 isStreaming.value = false
 break
 }
 case 'awaiting_pr_review': {
 if (activeCodingSession.value) {
 activeCodingSession.value.status = 'awaiting_confirmation'
 activeCodingSession.value.confirmationStep = 'pr_review'
 }
 prConfirmData.value = {
 suggestedPrTitle: event.suggested_pr_title || '',
 suggestedPrDescription: event.suggested_pr_description || '',
 targetBranch: event.target_branch || 'main',
 branchUrl: event.branch_url || '',
 }
 isStreaming.value = false
 break
 }
 case 'conflict_check': {
 if (commitConfirmData.value) {
 commitConfirmData.value.conflictCheck = {
 has_conflicts: event.has_conflicts,
 conflicting_files: event.conflicting_files,
 behind_by: event.behind_by,
 suggestion: event.suggestion,
 }
 }
 break
 }
 case 'error': {
 // Phase：SSE ERROR 结构化 payload 分派。
 // Pitfall 3 向后兼容：event.code 不存在时走 fallback 到既有 error.value。
 const code = (event as unknown as { code?: string }).code
 const data = (event as unknown as { data?: Record<string, unknown> }).data
 if (code === 'context_window_exceeded' && data) {
 lastContextExceeded.value = {
 estimated_tokens: Number(data.estimated_tokens ?? 0),
 max_tokens: Number(data.max_tokens ?? 0),
 exceeded_by: Number(data.exceeded_by ?? 0),
 model: String(data.model ?? ''),
 recommended_actions: Array.isArray(data.recommended_actions)
 ? (data.recommended_actions as ContextExceededPayload['recommended_actions']):,
 }
 }
 else {
 // provider_credential_missing 由 preflight 端点覆盖（Plan）；
 // 其他未知 code 沿用旧行为（error toast 路径）
 error.value = event.message || '未知错误'
 }
 break
 }
 default:
 console.warn('[Chat] 收到未知 SSE 事件类型:', event.type, event)
 break
 }
 }
 /**
 * 确认编码方案 — 调用 confirm API 并启动 runtime 轮询
 */
 async function handleConfirmCodingSession(sessionId: string, branchName?: string) {
 if (!currentConversationId.value)
 return
 if (activeCodingSession.value?.isConfirming)
 return
 // 乐观 UI: 立即显示 loading
 activeCodingSession.value = {
 sessionId,
 status: 'confirmed',
 isConfirming: true,
 }
 try {
 const result = branchName
 ? await apiConfirmCodingSessionWithBranch(sessionId, branchName): await apiConfirmCodingSession(sessionId)
 activeCodingSession.value = {
 sessionId: result.id,
 status: result.status as 'draft' | 'confirmed' | 'running' | 'awaiting_confirmation' | 'completed' | 'failed',
 isConfirming: false,
 }
 // 编码 running 期间禁用输入
 isStreaming.value = true
 // 启动 runtime 轮询（与 deep_analysis 模式一致）
 scheduleRuntimePoll(currentConversationId.value, 3000)
 }
 catch (err) {
 // 回滚
 activeCodingSession.value = {
 sessionId,
 status: 'draft',
 isConfirming: false,
 }
 error.value = err instanceof Error ? err.message: '确认失败'
 }
 }
 async function sendMessage(content: string, feishuDocId?: string) {
 if (isStreaming.value)
 return
 let materializedConversation: Conversation | null = null
 let createdForDraft = false
 if (!currentConversationId.value) {
 if (!selectedSpaceId.value) {
 error.value = '请先选择空间'
 return
 }
 loading.value = true
 try {
 materializedConversation = await createConversation({
 space_id: selectedSpaceId.value,
 model: resolveModelForNewConversation,
 })
 pendingConversation.value = materializedConversation
 currentConversationId.value = materializedConversation.id
 // 立刻把会话 id 同步到 URL —— 必须发生在 SSE 流启动之前。
 // 否则用户在流式期间刷新页面，URL 退回到草稿空页（restoreFromURL 拿不到 id），
 // 被迫从侧栏点「运行中」对话回去；而此时 SSE 已经断、后端任务可能还没结束，
 // restoreConversationRuntime 看到 active=true 直接进 polling 等待，UI 一直
 // 是空 bubble + "正在整理回答..."。先 syncURL 才能让刷新无损 resume。
 syncConversationToURL(materializedConversation.id)
 createdForDraft = true
 if (selectedCredentialModel.value) {
 const parts = selectedCredentialModel.value.split(':')
 if (parts.length === 2)
 await patchConversationProviderAndModel(parts[0], parts[1])
 }
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '创建对话失败'
 if (materializedConversation) {
 try {
 await deleteConversation(materializedConversation.id)
 }
 catch {
 // 创建后的模型绑定失败时尽力清理后端空会话。
 }
 }
 pendingConversation.value = null
 currentConversationId.value = null
 syncConversationToURL(null)
 return
 }
 finally {
 loading.value = false
 }
 }
 const conversationId = currentConversationId.value
 if (!conversationId)
 return
 stopRuntimePolling
 // 清除之前的流式状态
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingToolCalls.value =
 streamingTimeline.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
 streamingNarrations.value =
 streamingPendingText.value = ''
 deepAnalysisLogs.value =
 deepAnalysisSessionId.value = null
 error.value = null
 lastFailedContent.value = null
 // 重置 phase / restored runtime 痕迹 —— 否则刷新场景下 restoreConversationRuntime
 // 残留的 currentPhase=waiting / restoredRuntimeConversationId 会让本次发消息的
 // finally 走 waiting 早退分支（误以为是后台异步任务），导致流式内容永远不会
 // 合并到 messages，UI 永久 stuck 在空 bubble + "正在整理回答..." 状态条。
 currentPhase.value = null
 taskProgress.value = null
 restoredRuntimeConversationId.value = null
 streamingStatus.value = null
 // 添加用户消息到列表（乐观更新）
 const userMessage: ConversationMessage = {
 id: crypto.randomUUID,
 role: 'user',
 content,
 created_at: new Date.toISOString,
 }
 messages.value.push(userMessage)
 // 启动 SSE 流
 isStreaming.value = true
 const controller = new AbortController
 abortController.value = controller
 try {
 // 检索分支由 backend 自动按 base branch 选取，前端不再传 branch 字段
 // （历史 Phase 的检索分支 picker 已下线——用户从未感知多分支语义，
 // 选择面板反而误导成"每条消息可换分支"）。
 await connectSSE(
 conversationId,
 content,
 selectedRole.value,
 (event: SSEEvent) => handleSSEEvent(event),
 controller.signal,
 {
 forceDeepAnalysis: forceDeepAnalysis.value,
 feishuDocId,
 },
 )
 }
 catch (e) {
 if ((e as Error).name !== 'AbortError') {
 // SSE 断线恢复：连接异常但流仍在后端执行时，切换到 runtime 轮询
 const runId = getCurrentRunId
 if (runId && !streamingContent.value) {
 scheduleRuntimePoll(conversationId, 1000)
 return
 }
 error.value = e instanceof Error ? e.message: '发送消息失败'
 }
 }
 finally {
 isStreaming.value = false
 abortController.value = null
 // —— 草稿会话收尾（最先处理，且必须早于「waiting → scheduleRuntimePoll + return」
 // 的早退逻辑；否则下面的 return 会跳过 pendingConversation 提升，
 // deep_analysis 等 waiting 路径首次发送时侧栏看不到新对话）。
 //
 // * 成功（有任何流响应 / waiting 后台接管）→ 把 pendingConversation
 // 提升到 conversations 列表，不再清 pending 之外的状态。
 // * 彻底失败（有 error 且没收到任何流内容、也未进入 waiting）→ 清掉
 // 刚创建的后端空会话，并 return 短路，避免下面合并逻辑误把空内容
 // 当成消息塞进 messages。
 const hadStreamingResponse
 = !!streamingContent.value
 || streamingToolCalls.value.length > 0
 || currentPhase.value === 'waiting'
 if (createdForDraft && error.value && !hadStreamingResponse) {
 pendingConversation.value = null
 currentConversationId.value = null
 syncConversationToURL(null)
 if (materializedConversation) {
 try {
 await deleteConversation(materializedConversation.id)
 }
 catch {
 // 清理后端空会话失败不覆盖原始错误。
 }
 }
 // 失败短路：跳过下面 waiting / merge 路径，避免误把空 streaming 合并为消息。
 return
 }
 if (createdForDraft) {
 const committed = pendingConversation.value ?? materializedConversation
 if (committed && !conversations.value.some(c => c.id === committed.id))
 conversations.value.unshift(committed)
 pendingConversation.value = null
 }
 // ↓↓↓ 以下保持 v25.0 之前的 finally 结构不变（流式合并 / waiting 早退）↓↓↓
 // graph 进入 WAITING（deep_analysis/coding 进行中）后 SSE 正常结束，
 // 需要启动 runtime 轮询来恢复并跟踪后续状态
 if (currentPhase.value === 'waiting' && currentConversationId.value) {
 scheduleRuntimePoll(currentConversationId.value, 1000)
 return
 }
 // 错误时：记录失败内容用于重试，移除乐观更新的用户消息
 if (error.value && !streamingContent.value) {
 lastFailedContent.value = content
 messages.value = messages.value.filter(m => m.id !== userMessage.id)
 }
 // 流结束后，将流式内容合并为正式消息
 if (streamingContent.value || streamingToolCalls.value.length > 0) {
 const finalMetadata: Record<string, unknown> = {
 ...(streamingMetadata.value || {}),
 ...(streamingStatus.value ? { status: streamingStatus.value }: {}),
 }
 // 持久化 thinking 内容
 if (streamingThinking.value)
 finalMetadata.thinking = streamingThinking.value
 // 持久化 narrations（工具调用间的叙述文本）
 if (streamingNarrations.value.length > 0)
 finalMetadata.narrations = [...streamingNarrations.value]
 if (streamingTimeline.value.length > 0)
 finalMetadata.timeline = [...streamingTimeline.value]
 // 持久化 tool calls 的 result
 if (streamingToolCalls.value.length > 0) {
 finalMetadata.tool_results = streamingToolCalls.value
 .filter(tc => tc.result)
 .map(tc => ({ id: tc.id, result: tc.result }))
 }
 const assistantMessage: ConversationMessage = {
 id: streamingMessageId.value || crypto.randomUUID,
 role: 'assistant',
 content: streamingContent.value,
 tool_calls: streamingToolCalls.value.length > 0
 ? streamingToolCalls.value.map(tc => ({
 id: tc.id,
 name: tc.name,
 input: tc.input,
 result: tc.result,
 status: tc.status,
 })): undefined,
 metadata: Object.keys({
 ...finalMetadata,
 ...(deepAnalysisLogs.value.length > 0 ? { deep_analysis_logs: [...deepAnalysisLogs.value] }: {}),
 ...(deepAnalysisSessionId.value ? { deep_analysis_session_id: deepAnalysisSessionId.value }: {}),
 }).length > 0
 ? {
 ...finalMetadata,
 ...(deepAnalysisLogs.value.length > 0 ? { deep_analysis_logs: [...deepAnalysisLogs.value] }: {}),
 ...(deepAnalysisSessionId.value ? { deep_analysis_session_id: deepAnalysisSessionId.value }: {}),
 }: undefined,
 created_at: new Date.toISOString,
 }
 messages.value.push(assistantMessage)
 resetStreamingState
 }
 else {
 resetStreamingState
 }
 }
 }
 async function retryLastMessage {
 if (!lastFailedContent.value)
 return
 const content = lastFailedContent.value
 lastFailedContent.value = null
 error.value = null
 await sendMessage(content)
 }
 // ========================================================================
 // URL 路由 — 对话 ID 持久化到地址栏
 // ========================================================================
 function syncConversationToURL(id: string | null) {
 const url = new URL(window.location.href)
 if (id) {
 url.searchParams.set('conversation', id)
 }
 else {
 url.searchParams.delete('conversation')
 }
 window.history.replaceState({}, '', url.toString)
 }
 async function restoreFromURL {
 const url = new URL(window.location.href)
 const convId = url.searchParams.get('conversation')
 if (convId && convId !== currentConversationId.value) {
 await selectConversation(convId)
 }
 }
 // ========================================================================
 // 浏览器通知
 // ========================================================================
 function requestNotificationPermission {
 if (notificationsEnabled.value)
 void requestAndEnableWebPush
 }
 async function toggleNotifications(enabled: boolean) {
 notificationsEnabled.value = enabled
 if (enabled) {
 const success = await requestAndEnableWebPush
 if (!success)
 notificationsEnabled.value = false
 }
 else {
 const { disableWebPush } = useWebPush
 await disableWebPush
 }
 }
 function _notifyDeepAnalysisComplete(sessionId: string | null = deepAnalysisSessionId.value) {
 if (webPushReady.value)
 return
 if (!('Notification' in window) || Notification.permission !== 'granted')
 return
 if (document.hasFocus)
 return
 const conv = conversations.value.find(c => c.id === currentConversationId.value)
 const title = conv?.title || '对话'
 const n = new Notification('深度分析完成', {
 body: `「${title}」的深度分析已完成，点击查看结果`,
 icon: '/favicon.ico',
 tag: `deep-analysis-${sessionId || currentConversationId.value || 'chat'}`,
 })
 n.onclick = => {
 window.focus
 n.close
 }
 }
 // ========================================================================
 // 导出到飞书 (Phase)
 // ========================================================================
 /** 进入多选导出模式，默认选中最近一轮 AI 回答 (per ) */
 function enterExportSelectMode {
 isExportSelectMode.value = true
 selectedMessageIds.value = new Set
 // 默认选中最近一条 assistant 消息
 const lastAssistant = [...messages.value]
 .reverse
 .find(m => m.role === 'assistant')
 if (lastAssistant) {
 selectedMessageIds.value.add(lastAssistant.id)
 }
 }
 /** 退出多选导出模式 */
 function exitExportSelectMode {
 isExportSelectMode.value = false
 selectedMessageIds.value = new Set
 }
 /** 切换消息选中状态 (per: 仅 assistant 可选) */
 function toggleMessageSelect(messageId: string) {
 const msg = messages.value.find(m => m.id === messageId)
 if (!msg || msg.role !== 'assistant')
 return
 const next = new Set(selectedMessageIds.value)
 if (next.has(messageId)) {
 next.delete(messageId)
 }
 else {
 next.add(messageId)
 }
 selectedMessageIds.value = next
 }
 /** 全选所有 AI 回答 (per ) */
 function selectAllAssistant {
 const ids = messages.value
 .filter(m => m.role === 'assistant')
 .map(m => m.id)
 selectedMessageIds.value = new Set(ids)
 }
 /** 执行导出到飞书 */
 async function doExportToFeishu(
 title: string,
 messageIds: string,
 folderToken?: string,
 ): Promise<ExportToFeishuResponse> {
 if (!currentConversationId.value) {
 throw new Error('没有活动对话')
 }
 const data: ExportToFeishuRequest = {
 message_ids: messageIds,
 title,
 ...(folderToken ? { folder_token: folderToken }: {}),
 }
 return exportToFeishu(currentConversationId.value, data)
 }
 /**
 * Phase：对话凭证前置探测。
 *
 * 调用 GET /api/chat/conversations/{id}/preflight/：
 * - 成功（200 status=ok）→ 清空 credentialMissingPayload，返回 true
 * - 失败（400 code=provider_credential_missing）→ 写入 payload，返回 false
 * - 其他错误 → 抛出，由 caller 走 ChatErrorCard（既有路径， non-provider_credential_missing 不归本 Card）
 */
 async function preflightConversation(conversationId: string): Promise<boolean> {
 try {
 await apiGet(`/chat/conversations/${conversationId}/preflight/`)
 credentialMissingPayload.value = null
 return true
 }
 catch (e) {
 if (e instanceof ApiError && e.status === 400) {
 const body = e.body as { code?: string, data?: Record<string, unknown> } | null
 if (body && body.code === 'provider_credential_missing' && body.data) {
 credentialMissingPayload.value = {
 missingProvider: String(body.data.missing_provider ?? '') as ProviderType,
 scopeAttempted: String(body.data.scope_attempted ?? 'system'),
 recommendedAction: String(body.data.recommended_action ?? ''),
 }
 return false
 }
 }
 throw e
 }
 }
 /** 清空 credentialMissingPayload（用户切到其他对话 / 手动关闭 Card 时调用）。 */
 function clearCredentialMissingPayload: void {
 credentialMissingPayload.value = null
 }
 /** Phase：清空 lastContextExceeded（对话切换 / 清理历史后调用）。 */
 function resetContextExceeded: void {
 lastContextExceeded.value = null
 }
 return {
 // State
 conversations,
 currentConversationId,
 messages,
 loading,
 messagesLoading,
 error,
 isStreaming,
 streamingContent,
 streamingThinking,
 streamingToolCalls,
 streamingTimeline,
 streamingMessageId,
 streamingMetadata,
 abortController,
 sidebarCollapsed,
 selectedSpaceId,
 selectedRole,
 selectedModel,
 selectedCredentialModel,
 forceDeepAnalysis,
 notificationsEnabled,
 streamingStatus,
 budgetWarning,
 lastFailedContent,
 streamingNarrations,
 streamingPendingText,
 deepAnalysisLogs,
 deepAnalysisSessionId,
 restoredRuntimeConversationId,
 currentPhase,
 taskProgress,
 isInterrupting,
 webPushReady,
 // Getters
 currentConversation,
 hasConversation,
 // Actions
 fetchConversations,
 selectConversation,
 createNewConversation,
 removeConversation,
 patchConversationCredential,
 patchConversationProviderAndModel,
 stopStreaming,
 toggleSidebar,
 clearCurrentConversation,
 sendMessage,
 retryLastMessage,
 restoreFromURL,
 restoreConversationRuntime,
 requestNotificationPermission,
 toggleNotifications,
 syncConversationToURL,
 // 编码会话 (Phase)
 activeCodingSession,
 codingProgress,
 codingResult,
 codingError,
 handleConfirmCodingSession,
 // 编码确认数据 (Phase)
 commitConfirmData,
 prConfirmData,
 diffSummaryData,
 completedConfirmSteps,
 // 导出到飞书 (Phase)
 isExportSelectMode,
 selectedMessageIds,
 enterExportSelectMode,
 exitExportSelectMode,
 toggleMessageSelect,
 selectAllAssistant,
 doExportToFeishu,
 // Phase 凭证缺失前置探测
 credentialMissingPayload,
 preflightConversation,
 clearCredentialMissingPayload,
 // Phase 上下文超限引导
 lastContextExceeded,
 resetContextExceeded,
 }
})
