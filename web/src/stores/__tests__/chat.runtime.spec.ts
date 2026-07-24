import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { confirmCodingSession, createSessionsForPlan, getConversationDetail, getConversationRuntime } from '~/api/chat'
import { useChatStore } from '~/stores/chat'

vi.mock('~/api/chat', async () => {
  const actual = await vi.importActual<typeof import('~/api/chat')>('~/api/chat')
  return {
    ...actual,
    confirmCodingSession: vi.fn(),
    createSessionsForPlan: vi.fn(),
    getConversationRuntime: vi.fn(),
    getConversationDetail: vi.fn(),
  }
})

describe('chat store runtime restore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(confirmCodingSession).mockReset()
    vi.mocked(createSessionsForPlan).mockReset()
    vi.mocked(getConversationRuntime).mockReset()
    vi.mocked(getConversationDetail).mockReset()
    window.localStorage.clear()
  })

  it('selectConversation 回显已回复澄清 + 路由 trace + 瞬时态（localStorage）', async () => {
    window.localStorage.setItem('friday-chat-transient:conv-x', JSON.stringify({
      error: '上次请求失败',
      budgetWarning: 80,
    }))
    vi.mocked(getConversationDetail).mockResolvedValue({
      id: 'conv-x',
      space_id: 's',
      title: 't',
      status: 'completed',
      created_at: '',
      updated_at: '',
      messages: [],
      clarifications: [{
        clarification_id: 'c1',
        question: 'Q',
        options: [{ id: 'a', label: 'A' }],
        allow_freeform: true,
        status: 'answered',
        answer: { selected_option_id: 'a', freeform_text: '', answered_at: '2026-01-01' },
      }],
      routing_trace: { trace_id: 'tr1', query: 'q', candidates: [], threshold: 0.5, triggered_by: 'chat_tool' },
    } as any)
    vi.mocked(getConversationRuntime).mockResolvedValue({
      conversation_id: 'conv-x',
      active: false,
      status: 'completed',
    } as any)

    const store = useChatStore()
    await store.selectConversation('conv-x')

    const clar = store.pendingClarifications.get('c1')
    expect(clar?.status).toBe('answered')
    expect(clar?.answer?.selected_option_id).toBe('a')
    expect(store.error).toBe('上次请求失败')
    expect(store.budgetWarning).toBe(80)
  })

  it('瞬时态清空时同步移除 localStorage（不复活旧错误）', async () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-y'
    store.error = '失败了'
    expect(window.localStorage.getItem('friday-chat-transient:conv-y')).toContain('失败了')
    // 清空 → 同步 removeItem
    store.error = null
    expect(window.localStorage.getItem('friday-chat-transient:conv-y')).toBeNull()
  })

  it('inactive runtime still restores coding_plan snapshot', async () => {
    vi.mocked(getConversationRuntime).mockResolvedValue({
      conversation_id: 'conv-1',
      active: false,
      status: 'completed',
      coding_plan: {
        plan_id: 'plan-1',
        title: '方案',
        sessions: [
          {
            session_id: 'session-1',
            repository_id: 'repo-1',
            repository_name: 'example-app',
            branch_name: 'fix/example',
            status: 'confirmed',
            pr_url: '',
            commit_sha: '',
            error_message: '',
          },
        ],
      },
    })

    const store = useChatStore()
    await store.restoreConversationRuntime('conv-1')

    expect(store.activeCodingPlan?.plan_id).toBe('plan-1')
    expect(store.activeCodingPlan?.sessions[0].status).toBe('confirmed')
    expect(store.isStreaming).toBe(false)
  })

  it('applyRuntimeSnapshot 写入 codingProgress 当 runtime.coding_session.coding_progress 存在 (runtime restore)', async () => {
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

    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    await store.restoreConversationRuntime('conv-1')

    expect(store.codingProgress).not.toBeNull()
    expect(store.codingProgress?.sessionId).toBe('session-1')
    expect(store.codingProgress?.modifiedFilesCount).toBe(2)
    expect(store.codingProgress?.modifiedFiles?.[0].file_path).toBe('src/main.py')
    expect(store.codingProgress?.recentToolCalls?.[0].tool).toBe('Edit')
    // polling 路径不带 steps；UI 已容忍空数组
    expect(store.codingProgress?.steps).toEqual([])
  })

  it('applyRuntimeSnapshot 不在 coding_progress 缺失时写入 codingProgress', async () => {
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

    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    await store.restoreConversationRuntime('conv-1')

    expect(store.codingProgress).toBeNull()
  })

  it('applyRuntimeSnapshot 在 session_id 切换时清掉旧 codingProgress', async () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    // 预置一份旧 session 的 progress（模拟之前 polling 写过）
    store.codingProgress = {
      sessionId: 'session-old',
      steps: [],
      modifiedFilesCount: 1,
      modifiedFiles: [{ file_path: 'old.py', change_type: 'modify' }],
      recentToolCalls: [],
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

    expect(store.codingProgress).toBeNull()
  })

  it('waiting_clarification 时从 runtime 恢复 pendingClarifications（刷新不丢卡片）', async () => {
    vi.mocked(getConversationRuntime).mockResolvedValue({
      conversation_id: 'conv-1',
      active: true,
      status: 'waiting',
      phase: 'waiting_clarification',
      pending_clarification: {
        clarification_id: 'clar-abc',
        question: '选 A 还是 B？',
        options: [
          { id: 'a', label: 'A' },
          { id: 'b', label: 'B' },
        ],
        allow_freeform: true,
      },
    } as any)

    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    await store.restoreConversationRuntime('conv-1')

    const restored = store.pendingClarifications.get('clar-abc')
    expect(restored).toBeDefined()
    expect(restored?.question).toBe('选 A 还是 B？')
    expect(restored?.options.length).toBe(2)
    expect(restored?.status).toBe('pending')
    expect(restored?.conversation_id).toBe('conv-1')
    // active=true → 恢复 streaming_snapshot（助手已产出的正文/工具），
    // waiting_clarification 的打字光标/空气泡由 ChatMessageBubble 按 phase 抑制。
    expect(store.isStreaming).toBe(true)
    expect(store.currentPhase).toBe('waiting_clarification')
  })

  it('runtime 无 pending_clarification 时不恢复任何卡片', async () => {
    vi.mocked(getConversationRuntime).mockResolvedValue({
      conversation_id: 'conv-1',
      active: false,
      status: 'completed',
      pending_clarification: null,
    } as any)

    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    await store.restoreConversationRuntime('conv-1')

    expect(store.pendingClarifications.size).toBe(0)
  })

  it('creating sessions for a plan immediately confirms created draft sessions', async () => {
    vi.mocked(createSessionsForPlan).mockResolvedValue({
      created: [
        {
          session_id: 'session-1',
          repository_id: 'repo-1',
          branch_name: 'fix/test',
        },
      ],
      failed: [],
    })
    vi.mocked(confirmCodingSession).mockResolvedValue({
      id: 'session-1',
      status: 'confirmed',
      tech_plan: '',
      affected_files: [],
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

    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    store.openRepoMultiSelector('plan-1', ['repo-1'])

    const result = await store.submitRepoMultiSelector(['repo-1'])

    expect(result).toEqual({ createdCount: 1, failedCount: 0 })
    expect(createSessionsForPlan).toHaveBeenCalledWith('plan-1', {
      repository_ids: ['repo-1'],
      branch_template: undefined,
    })
    expect(confirmCodingSession).toHaveBeenCalledWith('session-1')
    expect(store.activeCodingSession?.sessionId).toBe('session-1')
    expect(store.activeCodingSession?.status).toBe('confirmed')
    expect(store.isStreaming).toBe(true)
  })
})
