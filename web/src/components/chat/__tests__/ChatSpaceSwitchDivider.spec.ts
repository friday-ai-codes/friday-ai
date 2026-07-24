import type { ConversationMessage } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ChatSpaceSwitchDivider from '~/components/chat/ChatSpaceSwitchDivider.vue'

function makeMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'sys-1',
    role: 'system',
    content: '已切换空间到「示例」',
    metadata: {
      type: 'space_switch',
      from_space_id: null,
      from_space_name: '',
      to_space_id: 'space-1',
      to_space_name: '示例',
    },
    created_at: '2026-06-11T08:00:00Z',
    ...overrides,
  }
}

describe('chatSpaceSwitchDivider', () => {
  it('renders target space name from metadata', () => {
    const wrapper = mount(ChatSpaceSwitchDivider, {
      props: { message: makeMessage() },
    })
    expect(wrapper.text()).toContain('已切换空间到「示例」')
    expect(wrapper.attributes('role')).toBe('separator')
  })

  it('renders generic label when switched to no space', () => {
    const wrapper = mount(ChatSpaceSwitchDivider, {
      props: {
        message: makeMessage({
          content: '已切换为通用对话（不绑定空间）',
          metadata: { type: 'space_switch', to_space_id: null, to_space_name: '' },
        }),
      },
    })
    expect(wrapper.text()).toContain('已切换为通用对话')
  })

  it('falls back to message content when metadata incomplete', () => {
    const wrapper = mount(ChatSpaceSwitchDivider, {
      props: {
        message: makeMessage({
          content: '已切换空间到「兜底」',
          metadata: { type: 'space_switch', to_space_id: 'space-x' },
        }),
      },
    })
    expect(wrapper.text()).toContain('已切换空间到「兜底」')
  })
})
