import type { ConversationMessage } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'
import { useChatStore } from '~/stores/chat'

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

vi.mock('~/components/chat/RoutingDecisionPanel.vue', () => ({
  default: defineComponent({ name: 'RoutingDecisionPanel', setup: () => () => h('div', { 'data-test': 'routing-panel' }) }),
}))

vi.mock('~/components/chat/TechPlanCard.vue', () => ({
  default: defineComponent({ name: 'TechPlanCard', setup: () => () => h('div', { 'data-test': 'tech-plan-card' }) }),
}))

function makeMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-user',
    role: 'user',
    content: '原始问题',
    created_at: '2026-05-28T09:00:00Z',
    ...overrides,
  }
}

async function mountBubble(message: ConversationMessage, props: Record<string, unknown> = {}) {
  const wrapper = mount(ChatMessageBubble, {
    props: { message, isStreaming: false, ...props },
    global: {
      stubs: { Transition: false },
    },
  })
  await new Promise<void>(r => setTimeout(r, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('chatMessageBubble edit user message', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('renders edit action for non-streaming user messages only', async () => {
    const user = await mountBubble(makeMessage())
    expect(user.find('[data-test="edit-user-message"]').exists()).toBe(true)

    const assistant = await mountBubble(makeMessage({ role: 'assistant', content: '回答' }))
    expect(assistant.find('[data-test="edit-user-message"]').exists()).toBe(false)

    const streaming = await mountBubble(makeMessage(), { isStreaming: true })
    expect(streaming.find('[data-test="edit-user-message"]').exists()).toBe(false)
  })

  it('opens inline editor initialized with message content and cancels without submitting', async () => {
    const store = useChatStore()
    const editSpy = vi.spyOn(store, 'editMessageAndFork').mockResolvedValue(undefined)
    const wrapper = await mountBubble(makeMessage())

    await wrapper.find('[data-test="edit-user-message"]').trigger('click')
    const textarea = wrapper.find('[data-test="edit-user-message-input"]')
    expect(textarea.exists()).toBe(true)
    expect((textarea.element as HTMLTextAreaElement).value).toBe('原始问题')

    await textarea.setValue('修改但取消')
    await wrapper.find('[data-test="cancel-user-message-edit"]').trigger('click')

    expect(wrapper.find('[data-test="edit-user-message-input"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('原始问题')
    expect(editSpy).not.toHaveBeenCalled()
  })

  it('submits changed non-empty text through chat store action', async () => {
    const store = useChatStore()
    const editSpy = vi.spyOn(store, 'editMessageAndFork').mockResolvedValue(undefined)
    const wrapper = await mountBubble(makeMessage())

    await wrapper.find('[data-test="edit-user-message"]').trigger('click')
    await wrapper.find('[data-test="edit-user-message-input"]').setValue('编辑后的问题')
    await wrapper.find('[data-test="submit-user-message-edit"]').trigger('click')

    expect(editSpy).toHaveBeenCalledWith('msg-user', '编辑后的问题', [])
  })

  it('disables submit for unchanged or blank content and Escape cancels', async () => {
    const wrapper = await mountBubble(makeMessage())

    await wrapper.find('[data-test="edit-user-message"]').trigger('click')
    const submit = wrapper.find('[data-test="submit-user-message-edit"]')
    expect((submit.element as HTMLButtonElement).disabled).toBe(true)

    const textarea = wrapper.find('[data-test="edit-user-message-input"]')
    await textarea.setValue('   ')
    expect((submit.element as HTMLButtonElement).disabled).toBe(true)

    await textarea.trigger('keydown', { key: 'Escape' })
    expect(wrapper.find('[data-test="edit-user-message-input"]').exists()).toBe(false)
  })
})
