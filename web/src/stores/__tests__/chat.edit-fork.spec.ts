import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { forkConversationForMessage } from '~/api/chat'
import { connectSSE } from '~/composables/useSSEStream'
import { useChatStore } from '~/stores/chat'
vi.mock('~/api/chat', async => {
 const actual = await vi.importActual<typeof import('~/api/chat')>('~/api/chat')
 return {
 ...actual,
 forkConversationForMessage: vi.fn,
 }
})
vi.mock('~/composables/useSSEStream', => ({
 connectSSE: vi.fn(async => {}),
 getCurrentRunId: vi.fn( => null),
}))
function forkedConversation {
 return {
 id: 'conv-fork',
 space_id: 'space-1',
 title: '原始对话（编辑）',
 model: 'claude-test',
 status: 'draft' as const,
 provider_credential_id: null,
 created_at: '2026-05-28T09:00:00Z',
 updated_at: '2026-05-28T09:00:00Z',
 messages: [
 {
 id: 'prior-1',
 role: 'user' as const,
 content: '之前的问题',
 created_at: '2026-05-28T08:59:00Z',
 },
 ],
 }
}
describe('chat store editMessageAndFork', => {
 beforeEach( => {
 setActivePinia(createPinia)
 vi.mocked(forkConversationForMessage).mockReset
 vi.mocked(connectSSE).mockReset
 vi.mocked(connectSSE).mockResolvedValue(undefined)
 window.history.replaceState({}, '', '/chat')
 })
 it('forks current conversation, switches state and sends edited content through existing SSE path', async => {
 vi.mocked(forkConversationForMessage).mockResolvedValue(forkedConversation)
 const store = useChatStore
 store.conversations = [
 {
 id: 'conv-old',
 space_id: 'space-1',
 title: '原始对话',
 model: 'claude-test',
 status: 'completed',
 provider_credential_id: null,
 created_at: '2026-05-28T08:00:00Z',
 updated_at: '2026-05-28T08:00:00Z',
 },
 ]
 store.currentConversationId = 'conv-old'
 await store.editMessageAndFork('msg-2', ' 编辑后的问题 ')
 expect(forkConversationForMessage).toHaveBeenCalledWith('conv-old', 'msg-2', {
 content: '编辑后的问题',
 })
 expect(store.currentConversationId).toBe('conv-fork')
 expect(window.location.href).toContain('conversation=conv-fork')
 expect(store.conversations[0].id).toBe('conv-fork')
 expect(store.conversations.some(c => c.id === 'conv-old')).toBe(true)
 expect(store.messages.map(m => m.content)).toEqual(['之前的问题', '编辑后的问题'])
 expect(connectSSE).toHaveBeenCalledWith(
 'conv-fork',
 '编辑后的问题',
 store.selectedRole,
 expect.any(Function),
 expect.any(AbortSignal),
 expect.objectContaining({ forceDeepAnalysis: store.forceDeepAnalysis }),
 )
 })
 it('refuses to fork without current conversation, while streaming, or with blank content', async => {
 const store = useChatStore
 await store.editMessageAndFork('msg-1', '新内容')
 expect(store.error).toBe('当前没有活动对话，无法编辑历史提问')
 store.currentConversationId = 'conv-old'
 store.isStreaming = true
 await store.editMessageAndFork('msg-1', '新内容')
 expect(store.error).toBe('当前正在生成回复，请稍后再编辑历史提问')
 store.isStreaming = false
 await store.editMessageAndFork('msg-1', ' ')
 expect(store.error).toBe('编辑后的内容不能为空')
 expect(forkConversationForMessage).not.toHaveBeenCalled
 })
 it('clears runtime and retry state before sending from the forked conversation', async => {
 vi.mocked(forkConversationForMessage).mockResolvedValue(forkedConversation)
 const store = useChatStore
 store.currentConversationId = 'conv-old'
 store.activeCodingSession = { sessionId: 'session-1', status: 'running', isConfirming: false }
 store.codingProgress = { sessionId: 'session-1', steps:, modifiedFilesCount: 1 }
 store.codingResult = {
 sessionId: 'session-1',
 prUrl: '',
 branchName: 'b',
 branchUrl: '',
 modifiedFilesCount: 1,
 }
 store.codingError = { sessionId: 'session-1', errorMessage: 'failed' }
 store.pendingClarifications.set('clarify-1', {
 clarification_id: 'clarify-1',
 conversation_id: 'conv-old',
 question: '继续吗',
 options:,
 allow_freeform: false,
 status: 'pending',
 })
 store.enterExportSelectMode
 store.lastFailedContent = '旧失败内容'
 await store.editMessageAndFork('msg-2', '编辑后的问题')
 expect(store.activeCodingSession).toBeNull
 expect(store.codingProgress).toBeNull
 expect(store.codingResult).toBeNull
 expect(store.codingError).toBeNull
 expect(store.pendingClarifications.size).toBe(0)
 expect(store.isExportSelectMode).toBe(false)
 expect(store.selectedMessageIds.size).toBe(0)
 expect(store.lastFailedContent).toBeNull
 })
 it('keeps normal sendMessage behavior unchanged', async => {
 const store = useChatStore
 store.currentConversationId = 'conv-existing'
 await store.sendMessage('普通新消息')
 expect(forkConversationForMessage).not.toHaveBeenCalled
 expect(connectSSE).toHaveBeenCalledWith(
 'conv-existing',
 '普通新消息',
 store.selectedRole,
 expect.any(Function),
 expect.any(AbortSignal),
 expect.any(Object),
 )
 })
})
