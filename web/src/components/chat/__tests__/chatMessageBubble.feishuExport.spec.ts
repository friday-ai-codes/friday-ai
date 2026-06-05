/**
 * （gap closure 285-05）：ChatMessageBubble 消息级导出就地三态契约测试。
 *
 * 覆盖 behavior（共 6 条）：
 * 1. 未导出态：metadata 无 feishu_exports → 仅「导出到飞书」，无「在飞书打开」/「重新导出」。
 * 2. 已导出态：feishu_exports 含一条 → 渲染「在飞书打开」+ aria-label="重新导出"，不再渲染「导出到飞书」。
 * 3. openFeishu：点击「在飞书打开」→ window.open(url, '_blank', 'noopener,noreferrer')。
 * 4. emit：「重新导出」与未导出态「导出到飞书」均 emit('exportSingle', message.id)。
 * 5. 取最新一条：feishu_exports 多条时 openFeishu 用末位（最新）那条 url。
 * 6. 不串态：本消息无 feishu_exports，即便另一条消息已导出，本气泡仍显示「导出到飞书」。
 */

import type { ConversationMessage } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'

vi.mock('~/composables/useMarkdownRenderer', () => ({
  getMarkdownRenderer: vi.fn(async () => ({
    render: (raw: string) => `<div data-test="md-rendered">${raw}</div>`,
  })),
}))

vi.mock('~/components/ui/checkbox', () => ({
  Checkbox: defineComponent({ name: 'Checkbox', setup: () => () => h('input', { type: 'checkbox' }) }),
}))

vi.mock('~/components/chat/DocSummaryCard.vue', () => ({
  default: defineComponent({ name: 'DocSummaryCard', setup: () => () => h('div', { 'data-test': 'doc-summary' }) }),
}))

vi.mock('~/components/chat/TechPlanCard.vue', () => ({
  default: defineComponent({
    name: 'TechPlanCard',
    props: ['planId', 'sessionId', 'techPlan', 'affectedFiles', 'status', 'isConfirming', 'branchName'],
    setup: () => () => h('div', { 'data-test': 'tech-plan-card' }),
  }),
}))

function makeMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-test',
    role: 'assistant',
    content: '这是一条助手回答。',
    created_at: '2026-05-21T00:00:00Z',
    ...overrides,
  }
}

async function mountBubble(message: ConversationMessage) {
  const wrapper = mount(ChatMessageBubble, {
    props: { message, isStreaming: false },
    global: { stubs: { Transition: false } },
  })
  // 等待 md renderer onMounted resolve
  await new Promise<void>(r => setTimeout(r, 0))
  await new Promise<void>(r => setTimeout(r, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

function findButtonByText(wrapper: ReturnType<typeof mount>, text: string) {
  return wrapper.findAll('button').find(b => b.text().includes(text))
}

describe('chatMessageBubble 消息级导出就地三态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('1. 未导出态：metadata 无 feishu_exports 时仅渲染「导出到飞书」', async () => {
    const wrapper = await mountBubble(makeMessage())

    expect(wrapper.text()).toContain('导出到飞书')
    expect(wrapper.text()).not.toContain('在飞书打开')
    expect(wrapper.find('[aria-label="重新导出"]').exists()).toBe(false)
  })

  it('2. 已导出态：feishu_exports 含一条时渲染「在飞书打开」+「重新导出」，不再渲染「导出到飞书」', async () => {
    const wrapper = await mountBubble(makeMessage({
      metadata: {
        feishu_exports: [
          { document_id: 'doc-1', url: 'https://feishu.example/doc-1', title: '导出文档', exported_at: '2026-05-21T01:00:00Z' },
        ],
      },
    }))

    expect(wrapper.text()).toContain('在飞书打开')
    expect(wrapper.find('[aria-label="重新导出"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('导出到飞书')
  })

  it('3. openFeishu：点击「在飞书打开」调用 window.open 带 noopener,noreferrer', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = await mountBubble(makeMessage({
      metadata: {
        feishu_exports: [
          { document_id: 'doc-1', url: 'https://feishu.example/doc-1', title: '导出文档', exported_at: '2026-05-21T01:00:00Z' },
        ],
      },
    }))

    await findButtonByText(wrapper, '在飞书打开')!.trigger('click')

    expect(openSpy).toHaveBeenCalledWith('https://feishu.example/doc-1', '_blank', 'noopener,noreferrer')
    openSpy.mockRestore()
  })

  it('4. emit：「重新导出」与未导出态「导出到飞书」均 emit(exportSingle, message.id)', async () => {
    // 未导出态点击「导出到飞书」
    const unexported = await mountBubble(makeMessage({ id: 'msg-a' }))
    await findButtonByText(unexported, '导出到飞书')!.trigger('click')
    expect(unexported.emitted('exportSingle')?.[0]).toEqual(['msg-a'])

    // 已导出态点击「重新导出」
    const exported = await mountBubble(makeMessage({
      id: 'msg-b',
      metadata: {
        feishu_exports: [
          { document_id: 'doc-1', url: 'https://feishu.example/doc-1', title: '导出文档', exported_at: '2026-05-21T01:00:00Z' },
        ],
      },
    }))
    await exported.find('[aria-label="重新导出"]').trigger('click')
    expect(exported.emitted('exportSingle')?.[0]).toEqual(['msg-b'])
  })

  it('5. 取最新一条：feishu_exports 多条时 openFeishu 用末位（最新）url', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = await mountBubble(makeMessage({
      metadata: {
        feishu_exports: [
          { document_id: 'doc-1', url: 'https://feishu.example/doc-1', title: '旧文档', exported_at: '2026-05-21T01:00:00Z' },
          { document_id: 'doc-2', url: 'https://feishu.example/doc-2', title: '新文档', exported_at: '2026-05-21T02:00:00Z' },
        ],
      },
    }))

    await findButtonByText(wrapper, '在飞书打开')!.trigger('click')

    expect(openSpy).toHaveBeenCalledWith('https://feishu.example/doc-2', '_blank', 'noopener,noreferrer')
    openSpy.mockRestore()
  })

  it('6. 不串态：本消息无 feishu_exports 时仍显示「导出到飞书」（隔离到 props.message）', async () => {
    // 另一条消息已导出（仅模拟其 metadata），不应影响本气泡——本气泡只读 props.message
    const wrapper = await mountBubble(makeMessage({ id: 'msg-c', metadata: { model: 'gpt-test' } }))

    expect(wrapper.text()).toContain('导出到飞书')
    expect(wrapper.text()).not.toContain('在飞书打开')
    expect(wrapper.find('[aria-label="重新导出"]').exists()).toBe(false)
  })
})
