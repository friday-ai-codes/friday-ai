/**
 * useChatSession 守护测试（项目作战室 P3）。
 *
 * 覆盖：会话分组（我的项目个人 / 项目共享）、共享非本人会话只读判定、
 * loadConversations 自动选中、归档项不进分组。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('~/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 'me' } }),
}))
vi.mock('~/composables/useSSEStream', () => ({
  connectSSE: vi.fn(),
}))

const listConversationsMock = vi.fn()
vi.mock('~/api/chat', () => ({
  listConversations: (...a: unknown[]) => listConversationsMock(...a),
  getConversationDetail: vi.fn().mockResolvedValue({ messages: [] }),
  createConversation: vi.fn(),
  cloneConversation: vi.fn(),
  deleteConversation: vi.fn(),
  patchConversation: vi.fn(),
}))

const { useChatSession } = await import('../useChatSession')

function conv(id: string, visibility: string, ownerId: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    space_id: null,
    title: `c-${id}`,
    model: '',
    status: 'completed',
    provider_credential_id: null,
    visibility,
    bound_project_id: 'proj1',
    created_by: { id: ownerId, username: ownerId, display_name: ownerId },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...extra,
  }
}

describe('useChatSession（P3）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('会话分组：我的项目个人 vs 项目共享，归档项排除', async () => {
    listConversationsMock.mockResolvedValue([
      conv('a', 'personal', 'me'),
      conv('b', 'shared', 'other'),
      conv('c', 'personal', 'me', { is_archived: true }),
    ])
    const s = useChatSession(() => 'proj1')
    await s.loadConversations()

    expect(s.groups.value.mine.map(c => c.id)).toEqual(['a'])
    expect(s.groups.value.shared.map(c => c.id)).toEqual(['b'])
  })

  it('共享且非本人创建的会话 → 只读', async () => {
    listConversationsMock.mockResolvedValue([
      conv('a', 'personal', 'me'),
      conv('b', 'shared', 'other'),
    ])
    const s = useChatSession(() => 'proj1')
    await s.loadConversations()

    await s.selectConversation('b')
    expect(s.isReadOnly.value).toBe(true)

    await s.selectConversation('a')
    expect(s.isReadOnly.value).toBe(false)
  })

  it('本人创建的共享会话 → 非只读', async () => {
    listConversationsMock.mockResolvedValue([conv('b', 'shared', 'me')])
    const s = useChatSession(() => 'proj1')
    await s.loadConversations()
    await s.selectConversation('b')
    expect(s.isReadOnly.value).toBe(false)
  })

  it('loadConversations 自动选中第一个我的会话', async () => {
    listConversationsMock.mockResolvedValue([
      conv('b', 'shared', 'other'),
      conv('a', 'personal', 'me'),
    ])
    const s = useChatSession(() => 'proj1')
    await s.loadConversations()
    expect(s.currentId.value).toBe('a')
  })
})
