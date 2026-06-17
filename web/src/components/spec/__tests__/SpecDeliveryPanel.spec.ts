/**
 * SpecDeliveryPanel 交付验收追溯面板守护测试（Phase 52-03，D-52-4，LINK-02）。
 *
 * 覆盖：全链路（WorkItem→spec→PR）渲染 + 链接可点（rel noopener）/ 缺 work_item 降级占位 /
 * 无实现 PR 降级占位 / work_item 有 title 无 url 纯文本。i18n 用真实 zh-CN messages，
 * 断言真实中文文案（验证 i18n 接通，非 mock 裸 key）。
 */

import type { SddSpecDetail } from '~/api/specs'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import SpecDeliveryPanel from '~/components/spec/SpecDeliveryPanel.vue'
import zhCN from '~/locales/zh-CN.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeSpec(overrides: Partial<SddSpecDetail> = {}): SddSpecDetail {
  return {
    id: 's-1',
    status: 'implemented',
    change_kind: 'proposal',
    repository_id: 'repo-1',
    repository_name: 'repo-1',
    updated_at: '2026-06-17T00:00:00Z',
    body: null,
    reviews: [],
    relations: {},
    implementation_prs: [],
    ...overrides,
  }
}

function mountPanel(spec: SddSpecDetail) {
  return mount(SpecDeliveryPanel, {
    props: { spec },
    global: { plugins: [i18n] },
  })
}

describe('specDeliveryPanel', () => {
  it('renders full WorkItem→spec→PR chain with clickable links', () => {
    const spec = makeSpec({
      status: 'implemented',
      relations: { work_item: { id: 'w-1', title: '登录需求', url: 'https://feishu.example/prd/1' } },
      implementation_prs: [
        { pr_url: 'https://github.com/test/r/pull/1', repository_id: 'repo-1', linked_at: '2026-06-17T01:00:00Z' },
        { pr_url: 'https://github.com/test/r/pull/2', repository_id: 'repo-2', linked_at: '2026-06-17T02:00:00Z' },
      ],
    })
    const wrapper = mountPanel(spec)

    // 标题真实中文文案
    expect(wrapper.text()).toContain(zhCN.specs.delivery.title)
    // 需求标题 + 可点链接
    const wiLink = wrapper.get('[data-testid="delivery-work-item-link"]')
    expect(wiLink.text()).toContain('登录需求')
    expect(wiLink.attributes('href')).toBe('https://feishu.example/prd/1')
    expect(wiLink.attributes('rel')).toContain('noopener')
    // 状态徽标渲染（已实现）
    expect(wrapper.find('[data-testid="spec-status-badge"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.specs.status.implemented)
    // 2 个 PR 链接，href = pr_url，rel noopener
    const prLinks = wrapper.findAll('[data-testid="delivery-pr-link"]')
    expect(prLinks.length).toBe(2)
    expect(prLinks[0].attributes('href')).toBe('https://github.com/test/r/pull/1')
    expect(prLinks[0].attributes('rel')).toContain('noopener')
    expect(prLinks[1].attributes('href')).toBe('https://github.com/test/r/pull/2')
  })

  it('shows unlinked placeholder when work_item absent (fail-soft)', () => {
    const wrapper = mountPanel(makeSpec({ relations: {} }))
    expect(wrapper.text()).toContain(zhCN.specs.delivery.workItemUnlinked)
    expect(wrapper.find('[data-testid="delivery-work-item-link"]').exists()).toBe(false)
  })

  it('shows empty placeholder when no implementation PRs', () => {
    const wrapper = mountPanel(makeSpec({ implementation_prs: undefined }))
    expect(wrapper.text()).toContain(zhCN.specs.delivery.prsEmpty)
    expect(wrapper.findAll('[data-testid="delivery-pr-link"]').length).toBe(0)
  })

  it('renders plain text title when work_item has no url', () => {
    const wrapper = mountPanel(makeSpec({
      relations: { work_item: { id: 'w-1', title: '无链接需求', url: '' } },
    }))
    expect(wrapper.text()).toContain('无链接需求')
    expect(wrapper.find('[data-testid="delivery-work-item-link"]').exists()).toBe(false)
  })
})
