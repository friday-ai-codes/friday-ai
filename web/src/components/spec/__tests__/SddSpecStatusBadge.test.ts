/**
 * SddSpecStatusBadge 守护测试（Phase 50-04，D-50-5/D-50-6）。
 *
 * 覆盖：5 态逐一渲染真实 zh-CN.json 的 specs.status.<status> 文案 + 对应色彩 class；
 * archived 附 archive 图标。i18n 用真实 locale 文件（防文案被改空，对齐 D-50-5 守护）。
 */

import type { SddSpecStatus } from '~/api/specs'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import SddSpecStatusBadge from '~/components/spec/SddSpecStatusBadge.vue'
import zhCN from '~/locales/zh-CN.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function mountBadge(status: SddSpecStatus) {
  return mount(SddSpecStatusBadge, {
    props: { status },
    global: { plugins: [i18n] },
  })
}

const CASES: Array<[SddSpecStatus, string, string]> = [
  ['draft', zhCN.specs.status.draft, 'text-gray-600'],
  ['in_review', zhCN.specs.status.in_review, 'text-amber-700'],
  ['approved', zhCN.specs.status.approved, 'text-emerald-700'],
  ['implemented', zhCN.specs.status.implemented, 'text-blue-700'],
  ['archived', zhCN.specs.status.archived, 'text-muted-foreground'],
]

describe('sddSpecStatusBadge', () => {
  it.each(CASES)('renders %s with real zh-CN label + color class', (status, label, colorClass) => {
    const wrapper = mountBadge(status)
    const badge = wrapper.find('[data-testid="spec-status-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain(label)
    expect(badge.attributes('title')).toBe(label)
    expect(badge.html()).toContain(colorClass)
  })

  it('archived shows archive icon', () => {
    const wrapper = mountBadge('archived')
    expect(wrapper.html()).toContain('icon-[lucide--archive]')
  })

  it('non-archived does not show archive icon', () => {
    const wrapper = mountBadge('draft')
    expect(wrapper.html()).not.toContain('icon-[lucide--archive]')
  })
})
