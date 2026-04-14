/**
 * Chat Store — 对话状态管理
 *
 * 管理对话列表、当前对话、消息列表、流式状态、用户偏好。
 * 使用 setup function 风格（与 projects.ts 一致）。
 */
import type { ChatRole, CodingErrorData, CodingProgressData, CodingResultData, CodingSessionRuntime, Conversation, ConversationMessage, ConversationRuntime, DeepAnalysisLog, ExportToFeishuRequest, ExportToFeishuResponse, SSEEvent, StreamTimelineItem } from '~/types/chat'
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
} from '~/api/chat'
import { connectSSE, getCurrentRunId } from '~/composables/useSSEStream'
import { useWebPush } from '~/composables/useWebPush'
import { useProjectsStore } from '~/stores/projects'
export const useChatStore = defineStore('chat', => {
 const { requestAndEnableWebPush, webPushReady } = useWebPush
 // ========================================================================
 // State
 // ========================================================================
 const conversations = ref<Conversation>
 const currentConversationId = ref<string | null>(null)
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
 const selectedProjectId = useLocalStorage<string | null>('chat-project-id', null)
 const selectedRole = useLocalStorage<ChatRole>('chat-role', 'developer')
 const selectedModel = useLocalStorage<string>('chat-model', '__default__')
 const forceDeepAnalysis = useLocalStorage<boolean>('chat-force-deep-analysis', false)
 const notificationsEnabled = useLocalStorage<boolean>('chat-notifications-enabled', false)
 /** 按仓库 ID 记忆检索分支（与仓库详情 sessionStorage 协同） */
 const searchBranchByRepository = useLocalStorage<Record<string, string>>(
 'friday:chat-search-branch',
 => ({}),
 )
 function setSearchBranchForRepository(repositoryId: string, branch: string) {
 searchBranchByRepository.value = {
 ...searchBranchByRepository.value,
 [repositoryId]: branch,
 }
 }
 // ========================================================================
 // Getters
 // ========================================================================
 const currentConversation = computed( =>
 conversations.value.find(c => c.id === currentConversationId.value) ?? null,
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
 if (!selectedProjectId.value) {
 error.value = '请先选择项目'
 return
 }
 loading.value = true
 error.value = null
 try {
 const conv = await createConversation({
 project_id: selectedProjectId.value,
 model: selectedModel.value === '__default__' ? undefined: selectedModel.value || undefined,
 })
 conversations.value.unshift(conv)
 currentConversationId.value = conv.id
 syncConversationToURL(conv.id)
 messages.value =
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '创建对话失败'
 }
 finally {
 loading.value = false
 }
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
 function clearCurrentConversation {
 stopRuntimePolling
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
 const wasRestoringRuntime = restoredRuntimeConversationId.value === id
 stopRuntimePolling
 if (wasRestoringRuntime) {
 const completedSessionId = deepAnalysisSessionId.value
 await hydrateConversationMessages(id)
 if (completedSessionId)
 _notifyDeepAnalysisComplete(completedSessionId)
 }
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
 })
 }
 else {
 timelineTool.name = event.tool_name || timelineTool.name
 if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
 timelineTool.input = event.input as Record<string, unknown>
 }
 break
 }
 case 'tool_use_result': {
 const tc = streamingToolCalls.value.find(t => t.id === event.tool_call_id)
 if (tc) {
 if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
 tc.input = event.input as Record<string, unknown>
 if (event.result)
 tc.result = event.result as string
 tc.status = 'done'
 }
 const timelineTool = streamingTimeline.value.find((item): item is Extract<StreamTimelineItem, { kind: 'tool' }> =>
 isTimelineToolItem(item) && item.id === event.tool_call_id,
 )
 if (timelineTool) {
 if (event.input && Object.keys(event.input as Record<string, unknown>).length > 0)
 timelineTool.input = event.input as Record<string, unknown>
 if (event.result)
 timelineTool.result = event.result as string
 timelineTool.status = 'done'
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
 case 'error':
 error.value = event.message || '未知错误'
 break
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
 if (!currentConversationId.value || isStreaming.value)
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
 const projectsStore = useProjectsStore
 let streamBranch: string | undefined
 const pid = selectedProjectId.value
 if (pid) {
 try {
 if (projectsStore.currentProject?.id !== pid)
 await projectsStore.fetchProject(pid)
 const repoId = projectsStore.currentProject?.repositories?.[0]?.id
 if (repoId) {
 const remembered = searchBranchByRepository.value[repoId]
 if (remembered)
 streamBranch = remembered
 }
 }
 catch {
 // 项目/仓库不可用时仍允许发消息（不带 branch）
 }
 }
 await connectSSE(
 currentConversationId.value,
 content,
 selectedRole.value,
 (event: SSEEvent) => handleSSEEvent(event),
 controller.signal,
 {
 forceDeepAnalysis: forceDeepAnalysis.value,
 feishuDocId,
 branch: streamBranch,
 },
 )
 }
 catch (e) {
 if ((e as Error).name !== 'AbortError') {
 // SSE 断线恢复：连接异常但流仍在后端执行时，切换到 runtime 轮询
 const runId = getCurrentRunId
 if (runId && currentConversationId.value && !streamingContent.value) {
 scheduleRuntimePoll(currentConversationId.value, 1000)
 return
 }
 error.value = e instanceof Error ? e.message: '发送消息失败'
 }
 }
 finally {
 isStreaming.value = false
 abortController.value = null
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
 selectedProjectId,
 selectedRole,
 selectedModel,
 forceDeepAnalysis,
 notificationsEnabled,
 searchBranchByRepository,
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
 stopStreaming,
 toggleSidebar,
 clearCurrentConversation,
 sendMessage,
 setSearchBranchForRepository,
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
 }
})
