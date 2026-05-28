import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { confirmCodingSession, createSessionsForPlan, getConversationRuntime } from '~/api/chat'
import { useChatStore } from '~/stores/chat'
vi.mock('~/api/chat', async => {
 const actual = await vi.importActual<typeof import('~/api/chat')>('~/api/chat')
 return {
 ...actual,
 confirmCodingSession: vi.fn,
 createSessionsForPlan: vi.fn,
 getConversationRuntime: vi.fn,
 }
})
describe('chat store runtime restore', => {
 beforeEach( => {
 setActivePinia(createPinia)
 vi.mocked(confirmCodingSession).mockReset
 vi.mocked(createSessionsForPlan).mockReset
 vi.mocked(getConversationRuntime).mockReset
 })
 it('inactive runtime still restores coding_plan snapshot', async => {
 vi.mocked(getConversationRuntime).mockResolvedValue({
 conversation_id: 'conv-1',
 active: false,
 status: 'completed',
 coding_plan: {
 plan_id: 'Plan',
 title: '方案',
 sessions: [
 {
 session_id: 'session-1',
 repository_id: 'repo-1',
 repository_name: 'study-app',
 branch_name: 'fix/example',
 status: 'confirmed',
 pr_url: '',
 commit_sha: '',
 error_message: '',
 },
 ],
 },
 })
 const store = useChatStore
 await store.restoreConversationRuntime('conv-1')
 expect(store.activeCodingPlan?.plan_id).toBe('Plan')
 expect(store.activeCodingPlan?.sessions[0].status).toBe('confirmed')
 expect(store.isStreaming).toBe(false)
 })
 it('applyRuntimeSnapshot 写入 codingProgress 当 runtime.coding_session.coding_progress 存在 (Quick)', async => {
 vi.mocked(getConversationRuntime).mockResolvedValue({
 conversation_id: 'conv-1',
 active: true,
 mode: 'coding',
 status: 'running',
 coding_session: {
 id: 'session-1',
 status: 'running',
 coding_progress: {
 modified_files: [
 { file_path: 'src/main.py', change_type: 'modify' },
 { file_path: 'src/utils.py', change_type: 'add' },
 ],
 recent_tool_calls: [
 { tool: 'Edit', summary: 'Updated main.py' },
 ],
 updated_at: '2026-05-28T10:48:00Z',
 },
 },
 } as any)
 const store = useChatStore
 store.currentConversationId = 'conv-1'
 await store.restoreConversationRuntime('conv-1')
 expect(store.codingProgress).not.toBeNull
 expect(store.codingProgress?.sessionId).toBe('session-1')
 expect(store.codingProgress?.modifiedFilesCount).toBe(2)
 expect(store.codingProgress?.modifiedFiles?.[0].file_path).toBe('src/main.py')
 expect(store.codingProgress?.recentToolCalls?.[0].tool).toBe('Edit')
 // polling 路径不带 steps；UI 已容忍空数组
 expect(store.codingProgress?.steps).toEqual
 })
 it('applyRuntimeSnapshot 不在 coding_progress 缺失时写入 codingProgress', async => {
 vi.mocked(getConversationRuntime).mockResolvedValue({
 conversation_id: 'conv-1',
 active: true,
 mode: 'coding',
 status: 'running',
 coding_session: {
 id: 'session-1',
 status: 'running',
 // 没 coding_progress 字段（编码刚启动，runner 还没回调 progress）
 },
 } as any)
 const store = useChatStore
 store.currentConversationId = 'conv-1'
 await store.restoreConversationRuntime('conv-1')
 expect(store.codingProgress).toBeNull
 })
 it('applyRuntimeSnapshot 在 session_id 切换时清掉旧 codingProgress', async => {
 const store = useChatStore
 store.currentConversationId = 'conv-1'
 // 预置一份旧 session 的 progress（模拟之前 polling 写过）
 store.codingProgress = {
 sessionId: 'session-old',
 steps:,
 modifiedFilesCount: 1,
 modifiedFiles: [{ file_path: 'old.py', change_type: 'modify' }],
 recentToolCalls:,
 }
 vi.mocked(getConversationRuntime).mockResolvedValue({
 conversation_id: 'conv-1',
 active: true,
 mode: 'coding',
 status: 'running',
 coding_session: {
 id: 'session-new',
 status: 'running',
 // 新 session 还没有 progress
 },
 } as any)
 await store.restoreConversationRuntime('conv-1')
 expect(store.codingProgress).toBeNull
 })
 it('creating sessions for a plan immediately confirms created draft sessions', async => {
 vi.mocked(createSessionsForPlan).mockResolvedValue({
 created: [
 {
 session_id: 'session-1',
 repository_id: 'repo-1',
 branch_name: 'fix/test',
 },
 ],
 failed:,
 })
 vi.mocked(confirmCodingSession).mockResolvedValue({
 id: 'session-1',
 status: 'confirmed',
 tech_plan: '',
 affected_files:,
 revision_count: 0,
 repository_id: 'repo-1',
 branch_name: 'fix/test',
 pr_url: '',
 error_message: '',
 confirmation_step: '',
 suggested_commit_message: '',
 suggested_pr_title: '',
 suggested_pr_description: '',
 conflict_check_result: null,
 diff_summary: null,
 created_at: '',
 updated_at: '',
 } as any)
 const store = useChatStore
 store.currentConversationId = 'conv-1'
 store.openRepoMultiSelector('Plan', ['repo-1'])
 const result = await store.submitRepoMultiSelector(['repo-1'])
 expect(result).toEqual({ createdCount: 1, failedCount: 0 })
 expect(createSessionsForPlan).toHaveBeenCalledWith('Plan', {
 repository_ids: ['repo-1'],
 branch_template: undefined,
 })
 expect(confirmCodingSession).toHaveBeenCalledWith('session-1')
 expect(store.activeCodingSession?.sessionId).toBe('session-1')
 expect(store.activeCodingSession?.status).toBe('confirmed')
 expect(store.isStreaming).toBe(true)
 })
})
