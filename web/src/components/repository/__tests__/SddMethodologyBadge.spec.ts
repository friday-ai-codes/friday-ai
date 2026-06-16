import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import SddMethodologyBadge from '~/components/repository/SddMethodologyBadge.vue'
import zhCN from '~/locales/zh-CN.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN },
})

function mountBadge(methodology?: string | null) {
  return mount(SddMethodologyBadge, {
    props: { methodology },
    global: { plugins: [i18n] },
  })
}

describe('sddMethodologyBadge', () => {
  it('renders SDD badge with real zh-CN label when methodology === SDD', () => {
    const wrapper = mountBadge('SDD')
    const badge = wrapper.find('[data-testid="sdd-methodology-badge"]')
    expect(badge.exists()).toBe(true)
    // 文案取自真实 zh-CN.json，绝不内联硬编码。
    expect(badge.text()).toBe(zhCN.repositories.tree.sddBadge)
    expect(badge.attributes('title')).toBe(zhCN.repositories.tree.sddBadgeTitle)
  })

  it('does not render badge for other methodology values', () => {
    const wrapper = mountBadge('维护中')
    expect(wrapper.find('[data-testid="sdd-methodology-badge"]').exists()).toBe(false)
  })

  it('does not render badge when methodology is undefined', () => {
    const wrapper = mountBadge(undefined)
    expect(wrapper.find('[data-testid="sdd-methodology-badge"]').exists()).toBe(false)
  })

  it('does not render badge when methodology is null', () => {
    const wrapper = mountBadge(null)
    expect(wrapper.find('[data-testid="sdd-methodology-badge"]').exists()).toBe(false)
  })
})
