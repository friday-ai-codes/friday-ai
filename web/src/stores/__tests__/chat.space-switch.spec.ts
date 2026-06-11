import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getConversationDetail, patchConversation } from '~/api/chat'
import { useChatStore } from '~/stores/chat'

vi.mock('~/api/chat', async () => {
  const actual = await vi.importActual<typeof import('~/api/chat')>('~/api/chat')
  return {
    ...actual,
    patchConversation: vi.fn(),
    getConversationDetail: vi.fn(),
  }
})

function baseConversation() {
  return {
    id: 'conv-1',
    space_id: 'space-a',
    title: '切换空间测试',
    model: 'claude-test',
    status: 'completed' as const,
    provider_credential_id: null,
    created_at: '2026-06-11T08:00:00Z',
    updated_at: '2026-06-11T08:00:00Z',
  }
}

describe('chat store switchConversationSpace', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(patchConversation).mockReset()
    vi.mocked(getConversationDetail).mockReset()
    localStorage.clear()
  })

  it('patches space_id, syncs selectedSpaceId and hydrates divider message', async () => {
    vi.mocked(patchConversation).mockResolvedValue({
      ...baseConversation(),
      space_id: 'space-b',
    })
    vi.mocked(getConversationDetail).mockResolvedValue({
      ...baseConversation(),
      space_id: 'space-b',
      messages: [
        {
          id: 'sys-1',
          role: 'system' as const,
          content: '已切换空间到「空间B」',
          metadata: { type: 'space_switch', to_space_id: 'space-b', to_space_name: '空间B' },
          created_at: '2026-06-11T08:01:00Z',
        },
      ],
    } as any)

    const store = useChatStore()
    store.conversations = [baseConversation()]
    store.currentConversationId = 'conv-1'

    await store.switchConversationSpace('space-b')

    expect(patchConversation).toHaveBeenCalledWith('conv-1', { space_id: 'space-b' })
    expect(store.conversations[0].space_id).toBe('space-b')
    expect(store.selectedSpaceId).toBe('space-b')
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].metadata?.type).toBe('space_switch')
  })

  it('draft state only updates selectedSpaceId preference without PATCH', async () => {
    const store = useChatStore()
    store.currentConversationId = null

    await store.switchConversationSpace('space-b')

    expect(patchConversation).not.toHaveBeenCalled()
    expect(store.selectedSpaceId).toBe('space-b')
  })

  it('refuses to switch while streaming', async () => {
    const store = useChatStore()
    store.conversations = [{ ...baseConversation(), status: 'running' }]
    store.currentConversationId = 'conv-1'
    store.isStreaming = true

    await expect(store.switchConversationSpace('space-b')).rejects.toThrow('对话进行中')
    expect(store.error).toBe('对话进行中，无法切换空间')
    expect(patchConversation).not.toHaveBeenCalled()
  })

  it('switching to null unbinds (通用对话)', async () => {
    vi.mocked(patchConversation).mockResolvedValue({
      ...baseConversation(),
      space_id: null,
    })
    vi.mocked(getConversationDetail).mockResolvedValue({
      ...baseConversation(),
      space_id: null,
      messages: [],
    } as any)

    const store = useChatStore()
    store.conversations = [baseConversation()]
    store.currentConversationId = 'conv-1'

    await store.switchConversationSpace(null)

    expect(patchConversation).toHaveBeenCalledWith('conv-1', { space_id: null })
    expect(store.conversations[0].space_id).toBeNull()
    expect(store.selectedSpaceId).toBeNull()
  })

  it('surfaces error and rethrows when PATCH fails', async () => {
    vi.mocked(patchConversation).mockRejectedValue(new Error('空间不存在: x'))

    const store = useChatStore()
    store.conversations = [baseConversation()]
    store.currentConversationId = 'conv-1'

    await expect(store.switchConversationSpace('space-x')).rejects.toThrow('空间不存在')
    expect(store.error).toBe('空间不存在: x')
    expect(store.conversations[0].space_id).toBe('space-a')
  })
})
