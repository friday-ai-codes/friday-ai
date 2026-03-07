/**
 * Chat Store — 对话状态管理
 *
 * 管理对话列表、当前对话、消息列表、流式状态、用户偏好。
 * 使用 setup function 风格（与 projects.ts 一致）。
 */
import type { ChatRole, Conversation, ConversationMessage } from '~/types/chat'
import {
 createConversation,
 deleteConversation,
 getConversationDetail,
 listConversations,
} from '~/api/chat'
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
 // 侧边栏状态
 const sidebarCollapsed = ref(false)
 // 用户偏好（localStorage 持久化）
 const selectedProjectId = useLocalStorage<string | null>('chat-project-id', null)
 const selectedRole = useLocalStorage<ChatRole>('chat-role', 'developer')
 const selectedModel = useLocalStorage<string>('chat-model', '')
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
 model: selectedModel.value || undefined,
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
 function stopStreaming {
 if (abortController.value) {
 abortController.value.abort
 abortController.value = null
 }
 isStreaming.value = false
 }
 function toggleSidebar {
 sidebarCollapsed.value = !sidebarCollapsed.value
 }
 function clearCurrentConversation {
 currentConversationId.value = null
 messages.value =
 streamingContent.value = ''
 streamingToolCalls.value =
 streamingMessageId.value = ''
 streamingMetadata.value = null
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
 streamingToolCalls,
 streamingMessageId,
 streamingMetadata,
 abortController,
 sidebarCollapsed,
 selectedProjectId,
 selectedRole,
 selectedModel,
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
 }
})
