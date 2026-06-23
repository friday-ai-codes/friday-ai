import type { SSEEvent } from '~/types/chat'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useChatStore } from '~/stores/chat'

/**
 * Phase 65：AI 对话串流隔离守护。
 *
 * 验证后台流（owner 会话 ≠ 当前会话）的 SSE 事件不写入当前会话 UI，
 * 仅 `title_generated` 允许更新所属会话在列表中的标题；前台（owner === 当前）
 * 行为零回归。
 */
describe('chat store 串流跨会话隔离', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  function textPartStarted(index: number, text: string): SSEEvent {
    return {
      type: 'part_started',
      index,
      part: { type: 'text', id: `p${index}`, index, text, state: 'streaming' },
    } as unknown as SSEEvent
  }

  it('后台会话流事件不写入当前会话 streaming state', () => {
    const store = useChatStore()
    // 用户当前停留在会话 B
    store.currentConversationId = 'conv-B'

    // 会话 A 的后台流派发 part_started（owner = conv-A）
    store._dispatchSSE(textPartStarted(0, 'A 的回答 token'), 'conv-A')

    // 当前会话 B 的 streaming state 不应被写入
    expect(store.streamingParts.length).toBe(0)
    expect(store.streamingContent).toBe('')
  })

  it('前台会话流事件正常写入当前会话 streaming state（零回归）', () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-A'

    store._dispatchSSE(textPartStarted(0, 'A 的回答 token'), 'conv-A')

    expect(store.streamingParts.length).toBe(1)
    const part = store.streamingParts[0]
    expect(part.type).toBe('text')
    expect(part.type === 'text' ? part.text : '').toBe('A 的回答 token')
  })

  it('未传 owner（旧调用 / _dispatchSSE 单测入口）按前台处理，零回归', () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-A'

    store._dispatchSSE(textPartStarted(0, 'hello'))

    expect(store.streamingParts.length).toBe(1)
  })

  it('后台会话的 title_generated 更新列表标题但不影响当前会话视图', () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-B'
    store.conversations = [
      { id: 'conv-A', space_id: 's', title: '旧标题 A', status: 'running', created_at: '', updated_at: '' } as any,
      { id: 'conv-B', space_id: 's', title: '标题 B', status: 'completed', created_at: '', updated_at: '' } as any,
    ]

    store._dispatchSSE({ type: 'title_generated', title: '新标题 A' } as SSEEvent, 'conv-A')

    expect(store.conversations.find(c => c.id === 'conv-A')?.title).toBe('新标题 A')
    expect(store.conversations.find(c => c.id === 'conv-B')?.title).toBe('标题 B')
    // 当前视图未被污染
    expect(store.streamingParts.length).toBe(0)
  })

  it('前台 title_generated 更新当前会话标题（零回归）', () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-A'
    store.conversations = [
      { id: 'conv-A', space_id: 's', title: '旧标题 A', status: 'running', created_at: '', updated_at: '' } as any,
    ]

    store._dispatchSSE({ type: 'title_generated', title: '新标题 A' } as SSEEvent, 'conv-A')

    expect(store.conversations.find(c => c.id === 'conv-A')?.title).toBe('新标题 A')
  })
})
