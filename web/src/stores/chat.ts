/**
 * Chat Store — 对话状态管理
 *
 * 管理对话列表、当前对话、消息列表、流式状态、用户偏好。
 * 使用 setup function 风格（与 projects.ts 一致）。
 */
import type { ChatRole, Conversation, ConversationMessage, SSEEvent } from '~/types/chat'
import {
 createConversation,
 deleteConversation,
 getConversationDetail,
 interruptConversation,
 listConversations,
} from '~/api/chat'
import { connectSSE } from '~/composables/useSSEStream'
export const useChatStore = defineStore('chat', => {
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
 const streamingMessageId = ref('')
 const streamingMetadata = ref<Record<string, unknown> | null>(null)
 const abortController = ref<AbortController | null>(null)
 const streamingStatus = ref<'streaming' | 'interrupted' | 'budget_exceeded' | null>(null)
 const budgetWarning = ref<number | null>(null)
 // 侧边栏状态
 const sidebarCollapsed = ref(false)
 // 用户偏好（localStorage 持久化）
 const selectedProjectId = useLocalStorage<string | null>('chat-project-id', null)
 const selectedRole = useLocalStorage<ChatRole>('chat-role', 'developer')
 const selectedModel = useLocalStorage<string>('chat-model', '__default__')
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
 currentConversationId.value = id
 messagesLoading.value = true
 error.value = null
 try {
 const detail = await getConversationDetail(id)
 messages.value = detail.messages
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
 // 标记中断状态（前端立即响应）
 streamingStatus.value = 'interrupted'
 // 先调 interrupt API 通知后端取消 SDK task
 try {
 await interruptConversation(currentConversationId.value)
 }
 catch {
 // 忽略错误（对话可能已结束）
 }
 // 不立即 abort SSE 连接，让后端有时间发送 message_complete 事件
 // 设置 3 秒超时保底：正常情况下后端中断后流会在几百毫秒内结束
 if (abortController.value) {
 const controller = abortController.value
 setTimeout( => {
 // 仅在 controller 仍是当前活跃的时候才 abort（防止误断新请求）
 if (abortController.value === controller) {
 controller.abort
 abortController.value = null
 isStreaming.value = false
 }
 }, 3000)
 }
 }
 function toggleSidebar {
 sidebarCollapsed.value = !sidebarCollapsed.value
 }
 function clearCurrentConversation {
 currentConversationId.value = null
 messages.value =
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingToolCalls.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
 }
 // ========================================================================
 // SSE 流式消息 (Phase, Plan)
 // ========================================================================
 function handleSSEEvent(event: SSEEvent) {
 switch (event.type) {
 case 'text_delta':
 streamingContent.value += event.text || ''
 break
 case 'thinking':
 streamingThinking.value += event.thinking || ''
 break
 case 'tool_use_start':
 streamingToolCalls.value.push({
 id: event.tool_call_id || '',
 name: event.tool_name || '',
 input: event.input || {},
 status: 'running',
 })
 break
 case 'tool_use_result': {
 const tc = streamingToolCalls.value.find(t => t.id === event.tool_call_id)
 if (tc) {
 tc.result = event.result
 tc.status = 'done'
 }
 break
 }
 case 'message_complete':
 if (event.message_id)
 streamingMessageId.value = event.message_id
 streamingMetadata.value = {
 model: event.model,
 usage: event.usage,
 input_tokens: event.usage?.input_tokens,
 output_tokens: event.usage?.output_tokens,
 status: event.status,
 }
 if (event.status === 'interrupted')
 streamingStatus.value = 'interrupted'
 if (event.status === 'budget_exceeded')
 streamingStatus.value = 'budget_exceeded'
 break
 case 'budget_warning':
 budgetWarning.value = event.budget_usage_percent || null
 break
 case 'title_generated':
 // 更新当前对话标题
 if (event.title) {
 const conv = conversations.value.find(c => c.id === currentConversationId.value)
 if (conv)
 conv.title = event.title
 }
 break
 case 'error':
 error.value = event.message || '未知错误'
 break
 default:
 console.warn('[Chat] 收到未知 SSE 事件类型:', event.type, event)
 break
 }
 }
 async function sendMessage(content: string) {
 if (!currentConversationId.value || isStreaming.value)
 return
 // 清除之前的流式状态
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingToolCalls.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
 error.value = null
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
 await connectSSE(
 currentConversationId.value,
 content,
 selectedRole.value,
 (event: SSEEvent) => handleSSEEvent(event),
 controller.signal,
 )
 }
 catch (e) {
 if ((e as Error).name !== 'AbortError') {
 error.value = e instanceof Error ? e.message: '发送消息失败'
 }
 }
 finally {
 isStreaming.value = false
 abortController.value = null
 // 流结束后，将流式内容合并为正式消息
 if (streamingContent.value) {
 // 将 streamingStatus 写入 metadata
 const finalMetadata = {
 ...(streamingMetadata.value || {}),
 ...(streamingStatus.value ? { status: streamingStatus.value }: {}),
 }
 const assistantMessage: ConversationMessage = {
 id: streamingMessageId.value || crypto.randomUUID,
 role: 'assistant',
 content: streamingContent.value,
 tool_calls: streamingToolCalls.value.length > 0
 ? streamingToolCalls.value.map(tc => ({ id: tc.id, name: tc.name, input: tc.input })): undefined,
 metadata: Object.keys(finalMetadata).length > 0 ? finalMetadata: undefined,
 created_at: new Date.toISOString,
 }
 messages.value.push(assistantMessage)
 streamingContent.value = ''
 streamingThinking.value = ''
 streamingToolCalls.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
 }
 streamingStatus.value = null
 budgetWarning.value = null
 }
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
 streamingMessageId,
 streamingMetadata,
 abortController,
 sidebarCollapsed,
 selectedProjectId,
 selectedRole,
 selectedModel,
 streamingStatus,
 budgetWarning,
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
 }
})
