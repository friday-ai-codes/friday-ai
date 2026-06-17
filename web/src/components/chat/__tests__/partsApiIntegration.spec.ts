/**
 * 既有专属组件接入 parts API 集成测试。
 *
 * 验证 happy path 在新 parts 路径下 byte-identical：
 *   1. routing trace：tool_use part_completed → store 反查 → RoutingDecisionPanel 展示
 *   2. TechPlanCard：create_coding_plan tool_use part → codingPlanData 派生 → 卡片渲染
 *   3. DocSummaryCard：metadata.docSummary → 卡片渲染
 *   4. ChatToolCall：part prop 优先级高于平铺字段
 */

import type { ConversationMessage, ToolUsePart } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'
import ChatToolCall from '~/components/chat/ChatToolCall.vue'
import { CHAT_PARTS_PROTOCOL_KEY } from '~/composables/useChatPartsProtocol'
import { useChatStore } from '~/stores/chat'
import { useRoutingStore } from '~/stores/routing'

vi.mock('~/composables/useMarkdownRenderer', () => ({
  getMarkdownRenderer: vi.fn(async () => ({
    render: (raw: string) => `<div data-test="md">${raw}</div>`,
  })),
}))

vi.mock('~/components/ui/checkbox', () => ({
  Checkbox: defineComponent({ name: 'Checkbox', setup: () => () => h('input') }),
}))

vi.mock('~/components/chat/DocSummaryCard.vue', () => ({
  default: defineComponent({
    name: 'DocSummaryCard',
    props: ['type', 'title', 'wordCount', 'preview'],
    setup: props => () => h('div', { 'data-test': 'doc-summary', 'data-title': props.title }),
  }),
}))

vi.mock('~/components/chat/RoutingDecisionPanel.vue', () => ({
  default: defineComponent({
    name: 'RoutingDecisionPanel',
    props: ['traceId', 'conversationId', 'messageId'],
    setup: props => () => h('div', { 'data-test': 'routing-panel', 'data-trace': props.traceId }),
  }),
}))

vi.mock('~/components/chat/TechPlanCard.vue', () => ({
  default: defineComponent({
    name: 'TechPlanCard',
    props: ['planId', 'codingPlanId', 'sessionId', 'techPlan', 'affectedFiles', 'status', 'isConfirming', 'branchName'],
    setup: props => () => h('div', {
      'data-test': 'tech-plan-card',
      'data-coding-plan-id': props.codingPlanId || '',
      'data-session': props.sessionId,
      'data-plan': props.planId,
      'data-techplan': props.techPlan,
    }),
  }),
}))

async function mountBubble(message: ConversationMessage, props: Record<string, unknown> = {}) {
  const wrapper = mount(ChatMessageBubble, {
    props: { message, isStreaming: false, ...props },
  })
  await new Promise<void>(r => setTimeout(r, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('fE-04 既有组件接入 parts API', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  it('1. routing trace —— part_completed 触发 maybeParseRoutingTraceFromToolResult → store 写入 trace', () => {
    window.localStorage.setItem(CHAT_PARTS_PROTOCOL_KEY, 'new')
    const chatStore = useChatStore()
    const routingStore = useRoutingStore()
    chatStore.currentConversationId = 'conv-1'

    chatStore._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: {
        id: 'p_routing',
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_relev',
        name: 'analyze_repository_relevance',
        input: { query: 'foo' },
        status: 'running',
      },
    })
    chatStore._dispatchSSE({
      type: 'part_completed',
      index: 0,
      part: {
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_relev',
        status: 'done',
        result: JSON.stringify({
          output: {
            data: {
              trace_id: 'trace-xyz',
              candidates: [{ repository_id: 'r1', name: 'study', score: 0.9 }],
              threshold: 0.5,
            },
          },
        }),
      },
    })

    expect(routingStore.tracesByTraceId.has('trace-xyz')).toBe(true)
    expect(chatStore.streamingMetadata?.routing_trace_id).toBe('trace-xyz')
  })

  it('2. TechPlanCard —— create_coding_plan tool_use part 触发卡片渲染', async () => {
    const part: ToolUsePart = {
      type: 'tool_use',
      id: 'p_plan',
      index: 0,
      tool_call_id: 'call_plan',
      name: 'create_coding_plan',
      input: {
        tech_plan: '## 方案\n实现 foo',
        affected_files: [{ file_path: 'a.py', change_type: 'modify' }],
      },
      status: 'done',
      result: JSON.stringify({
        coding_session_id: 'sess-1',
        coding_plan_id: 'plan-1',
        status: 'draft',
        branch_name: 'feat/foo',
      }),
    }
    const msg: ConversationMessage = {
      id: 'msg-plan',
      role: 'assistant',
      content: '已生成编码方案',
      parts: [part],
      created_at: '2026-05-21T00:00:00Z',
    }
    const wrapper = await mountBubble(msg)
    const card = wrapper.find('[data-test="tech-plan-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-coding-plan-id')).toBe('plan-1')
    expect(card.attributes('data-session')).toBe('sess-1')
    expect(card.attributes('data-plan')).toBe('plan-1')
    expect(card.attributes('data-techplan')).toContain('实现 foo')
  })

  it('3. DocSummaryCard —— streamingDocSummary prop 透传渲染', async () => {
    const msg: ConversationMessage = {
      id: 'msg-doc',
      role: 'assistant',
      content: '已读取文档',
      parts: [{ type: 'text', id: 't1', index: 0, text: '已读取文档', state: 'done' }],
      created_at: '2026-05-21T00:00:00Z',
    }
    const wrapper = await mountBubble(msg, {
      isStreaming: true,
      streamingDocSummary: {
        type: 'summary' as const,
        title: '产品文档',
        wordCount: 1024,
        preview: '本文档介绍...',
      },
    })
    const card = wrapper.find('[data-test="doc-summary"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-title')).toBe('产品文档')
  })

  it('4. RoutingDecisionPanel 已下线：即便 routing_trace_id + store 有 trace 也不渲染（与底部澄清卡去重）', async () => {
    const routingStore = useRoutingStore()
    routingStore.upsertTrace({
      trace_id: 'trace-rendered',
      query: 'q',
      candidates: [{
        repository_id: 'r1',
        repository_name: 'study',
        score: 0.9,
        level: 'high',
        evidence: 'matched',
        selected_by_ai: true,
        selected_by_user_final: true,
      }],
      threshold: 0.5,
      triggered_by: 'chat_tool',
    }, 'conv-1')

    const msg: ConversationMessage = {
      id: 'msg-routing',
      role: 'assistant',
      content: '已选中仓库',
      parts: [{ type: 'text', id: 't1', index: 0, text: '已选中仓库', state: 'done' }],
      metadata: { routing_trace_id: 'trace-rendered', conversation_id: 'conv-1' },
      created_at: '2026-05-21T00:00:00Z',
    }
    const wrapper = await mountBubble(msg)
    expect(wrapper.find('[data-test="routing-panel"]').exists()).toBe(false)
  })

  it('5. ChatToolCall part prop 渲染（FE-04 新 props 路径）', () => {
    const part: ToolUsePart = {
      type: 'tool_use',
      id: 'p1',
      index: 0,
      tool_call_id: 'call_x',
      name: 'search_repository_code',
      input: { query: 'foo' },
      status: 'done',
      result: '{"matches": []}',
    }
    const wrapper = mount(ChatToolCall, { props: { part } })
    expect(wrapper.text()).toContain('RAG 代码检索')
    expect(wrapper.find('.tool-dot--done').exists()).toBe(true)
  })

  it('6. ChatToolCall 平铺字段兼容（legacy 老调用方零回归）', () => {
    const wrapper = mount(ChatToolCall, {
      props: {
        name: 'browse_file_content',
        input: { file_path: 'apps/main.py' },
        result: 'file content',
        status: 'done',
      },
    })
    expect(wrapper.text()).toContain('浏览文件')
    expect(wrapper.text()).toContain('apps/main.py')
  })
})
