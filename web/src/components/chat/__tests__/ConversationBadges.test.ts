/**
 * ConversationBadges 守护测试：按 flag 渲染 SDD / 编码 / 方案 徽标。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ConversationBadges from '~/components/chat/ConversationBadges.vue'

function mountWith(flags: {
  has_sdd_spec?: boolean
  has_coding_plan?: boolean
  has_coding_session?: boolean
}) {
  return mount(ConversationBadges, { props: { conversation: flags } })
}

describe('conversationBadges', () => {
  it('无任何 flag 时不渲染徽标', () => {
    const w = mountWith({})
    expect(w.find('[data-testid="conv-badge-sdd"]').exists()).toBe(false)
    expect(w.find('[data-testid="conv-badge-coding"]').exists()).toBe(false)
    expect(w.find('[data-testid="conv-badge-plan"]').exists()).toBe(false)
  })

  it('has_sdd_spec 渲染 SDD 徽标', () => {
    const w = mountWith({ has_sdd_spec: true })
    const badge = w.find('[data-testid="conv-badge-sdd"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('SDD')
  })

  it('has_coding_session 渲染编码徽标', () => {
    const w = mountWith({ has_coding_session: true })
    expect(w.find('[data-testid="conv-badge-coding"]').exists()).toBe(true)
  })

  it('有方案但未编码渲染方案徽标', () => {
    const w = mountWith({ has_coding_plan: true })
    expect(w.find('[data-testid="conv-badge-plan"]').exists()).toBe(true)
    expect(w.find('[data-testid="conv-badge-coding"]').exists()).toBe(false)
  })

  it('编码已隐含方案：同时为真时只显示编码徽标，不显示方案徽标', () => {
    const w = mountWith({ has_coding_plan: true, has_coding_session: true })
    expect(w.find('[data-testid="conv-badge-coding"]').exists()).toBe(true)
    expect(w.find('[data-testid="conv-badge-plan"]').exists()).toBe(false)
  })

  it('三者同真：SDD + 编码 同时展示，方案被编码抑制', () => {
    const w = mountWith({
      has_sdd_spec: true,
      has_coding_plan: true,
      has_coding_session: true,
    })
    expect(w.find('[data-testid="conv-badge-sdd"]').exists()).toBe(true)
    expect(w.find('[data-testid="conv-badge-coding"]').exists()).toBe(true)
    expect(w.find('[data-testid="conv-badge-plan"]').exists()).toBe(false)
  })
})
