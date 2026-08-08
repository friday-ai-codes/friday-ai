/**
 * chat store 新 parts dispatch 测试。
 *
 * 测试矩阵（ 测试要求 ≥ 8 条）：
 * 1. dispatch_part_started_appends_to_streamingParts_at_index
 * 2. dispatch_part_delta_text_append_mutates_in_place
 * 3. dispatch_part_completed_marks_state_done
 * 4. dispatch_tool_use_part_completed_writes_result_and_status
 * 5. dispatch_skips_legacy_text_delta_when_protocol_is_new
 * 6. dispatch_skips_part_events_when_protocol_is_legacy
 * 7. reset_streaming_state_clears_parts
 * 8. message_complete_payload_parts_overrides_streamingParts
 *
 * E2E 模拟完整 SSE 流（parts-protocol 部分提前）：
 * 9. e2e_text_tool_text_dispatch_yields_three_ordered_parts
 */

import type { SSEEvent } from '~/types/chat'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { CHAT_PARTS_PROTOCOL_KEY } from '~/composables/useChatPartsProtocol'
import { useChatStore } from '~/stores/chat'

function setProtocol(value: 'new' | 'legacy'): void {
  window.localStorage.setItem(CHAT_PARTS_PROTOCOL_KEY, value)
}

/**
 * 测套件期望 store 暴露 `_dispatchSSE: (event: SSEEvent) => void` action
 * 作为单测入口（不进 store 公共 API，仅 vitest 访问；命名 `_` 前缀强调内部用途）。
 * 实际生产路径仍是 `sendMessage → connectSSE → onEvent → handleSSEEvent`。
 */
describe('chat store - parts dispatch ', () => {
  afterEach(() => {
    window.localStorage.clear()
  })
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  it('1. part_started 在指定 index 新增 text part', () => {
    setProtocol('new')
    const store = useChatStore()
    const event: SSEEvent = {
      type: 'part_started',
      index: 0,
      part: { id: 'p_t1', index: 0, type: 'text', state: 'streaming', text: '' },
    }
    store._dispatchSSE(event)
    expect(store.streamingParts.length).toBe(1)
    expect(store.streamingParts[0]).toMatchObject({ type: 'text', id: 'p_t1', index: 0, state: 'streaming' })
  })

  it('2. part_delta text_append 累加到对应 text part', () => {
    setProtocol('new')
    const store = useChatStore()
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: { id: 'p_t1', index: 0, type: 'text', state: 'streaming', text: '' },
    })
    store._dispatchSSE({
      type: 'part_delta',
      index: 0,
      delta_type: 'text_append',
      text: '你好',
    })
    store._dispatchSSE({
      type: 'part_delta',
      index: 0,
      delta_type: 'text_append',
      text: '世界',
    })
    expect(store.streamingParts[0].type).toBe('text')
    expect((store.streamingParts[0] as { text: string }).text).toBe('你好世界')
  })

  it('2b. thinking part 的多次 part_delta 实时累加为拼接全文', () => {
    // 前端数据层必须在思考文本还在流的时候就把它拼进 streamingParts —— 渲染层的
    // 「默认展开、全文可见」全靠这一步；只在 part_completed 时才落全文的实现，
    // 会让思考过程整段延迟到收尾才出现。
    setProtocol('new')
    const store = useChatStore()
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: { id: 'p_th', index: 0, type: 'thinking', state: 'streaming', text: '' },
    })
    for (const text of ['先确认', '索引状态，', '再枚举候选仓库'])
      store._dispatchSSE({ type: 'part_delta', index: 0, delta_type: 'text_append', text })

    expect(store.streamingParts.length).toBe(1)
    expect(store.streamingParts[0].type).toBe('thinking')
    expect((store.streamingParts[0] as { text: string }).text).toBe('先确认索引状态，再枚举候选仓库')
    // 收尾前就已是全文（state 仍是 streaming）
    expect((store.streamingParts[0] as { state: string }).state).toBe('streaming')

    store._dispatchSSE({ type: 'part_completed', index: 0, part: { index: 0, state: 'done' } })
    expect((store.streamingParts[0] as { text: string }).text).toBe('先确认索引状态，再枚举候选仓库')
  })

  it('3. part_completed 标记 text part state=done', () => {
    setProtocol('new')
    const store = useChatStore()
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: { id: 'p_t1', index: 0, type: 'text', state: 'streaming', text: 'hi' },
    })
    store._dispatchSSE({
      type: 'part_completed',
      index: 0,
      part: { index: 0, state: 'done' },
    })
    expect((store.streamingParts[0] as { state: string }).state).toBe('done')
  })

  it('4. tool_use part_completed 写 result + status', () => {
    setProtocol('new')
    const store = useChatStore()
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: {
        id: 'p_tool',
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_x',
        name: 'search_repository_code',
        input: { query: 'foo' },
        status: 'running',
      },
    })
    store._dispatchSSE({
      type: 'part_completed',
      index: 0,
      part: {
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_x',
        status: 'done',
        result: '{"matches": ["a.py"]}',
      },
    })
    const part = store.streamingParts[0]
    expect(part.type).toBe('tool_use')
    expect((part as { status: string }).status).toBe('done')
    expect((part as { result: string }).result).toBe('{"matches": ["a.py"]}')
  })

  it('5. protocol=new 时 legacy text_delta 被跳过，不写 streamingPendingText', () => {
    setProtocol('new')
    const store = useChatStore()
    store._dispatchSSE({ type: 'text_delta', text: '老路径文本' })
    expect(store.streamingPendingText).toBe('')
    expect(store.streamingParts.length).toBe(0)
  })

  it('6. protocol=legacy 时 part_* 事件被跳过，走老路径', () => {
    setProtocol('legacy')
    const store = useChatStore()
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: { id: 'p_x', index: 0, type: 'text', state: 'streaming', text: '' },
    })
    expect(store.streamingParts.length).toBe(0)
    // 老路径仍正常
    store._dispatchSSE({ type: 'text_delta', text: 'legacy ok' })
    expect(store.streamingPendingText).toBe('legacy ok')
  })

  it('7. clearCurrentConversation 清空 streamingParts', () => {
    setProtocol('new')
    const store = useChatStore()
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: { id: 'p1', index: 0, type: 'text', state: 'streaming', text: 'abc' },
    })
    expect(store.streamingParts.length).toBe(1)
    store.clearCurrentConversation()
    expect(store.streamingParts.length).toBe(0)
  })

  it('8. message_complete 的 parts payload 覆盖 streamingParts（断线重连兜底）', () => {
    setProtocol('new')
    const store = useChatStore()
    // 模拟 SSE 中段断开，streamingParts 残缺
    store._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: { id: 'p1', index: 0, type: 'text', state: 'streaming', text: '半截' },
    })
    store._dispatchSSE({
      type: 'message_complete',
      final_answer: '完整正文',
      parts: [
        { type: 'text', id: 'p1', index: 0, text: '完整正文', state: 'done' },
        {
          type: 'tool_use',
          id: 'p2',
          index: 1,
          tool_call_id: 'call_a',
          name: 'search_repository_code',
          input: { query: 'foo' },
          status: 'done',
          result: 'ok',
        },
      ],
    })
    expect(store.streamingParts.length).toBe(2)
    expect((store.streamingParts[0] as { text: string }).text).toBe('完整正文')
    expect(store.streamingParts[1].type).toBe('tool_use')
  })

  it('9. E2E: text → tool_use → text 三段事件序列产出三个有序 parts', () => {
    setProtocol('new')
    const store = useChatStore()
    const seq: SSEEvent[] = [
      { type: 'part_started', index: 0, part: { id: 'pa', index: 0, type: 'text', state: 'streaming', text: '' } },
      { type: 'part_delta', index: 0, delta_type: 'text_append', text: '先思考' },
      { type: 'part_completed', index: 0, part: { index: 0, state: 'done' } },
      {
        type: 'part_started',
        index: 1,
        part: {
          id: 'pb',
          index: 1,
          type: 'tool_use',
          tool_call_id: 'call_1',
          name: 'search_repository_code',
          input: { query: 'x' },
          status: 'running',
        },
      },
      {
        type: 'part_completed',
        index: 1,
        part: { index: 1, type: 'tool_use', tool_call_id: 'call_1', status: 'done', result: 'ok' },
      },
      { type: 'part_started', index: 2, part: { id: 'pc', index: 2, type: 'text', state: 'streaming', text: '' } },
      { type: 'part_delta', index: 2, delta_type: 'text_append', text: '基于结果：found' },
      { type: 'part_completed', index: 2, part: { index: 2, state: 'done' } },
    ]
    for (const e of seq) store._dispatchSSE(e)
    const types = store.streamingParts.map(p => p.type)
    expect(types).toEqual(['text', 'tool_use', 'text'])
    expect((store.streamingParts[0] as { state: string }).state).toBe('done')
    expect((store.streamingParts[1] as { status: string }).status).toBe('done')
    expect((store.streamingParts[2] as { text: string }).text).toBe('基于结果：found')
  })
})
