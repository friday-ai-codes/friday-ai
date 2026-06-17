/**
 * SpecReviewTimeline 守护测试（Phase 50-04，D-50-5）。
 *
 * 覆盖：2 条评审按传入顺序（后端倒序）渲染 + approve/reject 真实文案；空数组显示
 * specs.detail.reviewEmpty 真实文案。i18n 用真实 zh-CN messages。
 */

import type { SddSpecReview } from '~/api/specs'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import SpecReviewTimeline from '~/components/spec/SpecReviewTimeline.vue'
import zhCN from '~/locales/zh-CN.json'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function mountTimeline(reviews: SddSpecReview[]) {
  return mount(SpecReviewTimeline, {
    props: { reviews },
    global: { plugins: [i18n] },
  })
}

function makeReview(overrides: Partial<SddSpecReview> = {}): SddSpecReview {
  return {
    id: 'r-1',
    reviewer: 'alice',
    decision: 'approve',
    comment: '',
    created_at: '2026-06-17T00:00:00Z',
    ...overrides,
  }
}

describe('specReviewTimeline', () => {
  it('renders reviews in given order with approve/reject labels', () => {
    const reviews = [
      makeReview({ id: 'r-2', decision: 'reject', comment: '需修订', reviewer: 'bob' }),
      makeReview({ id: 'r-1', decision: 'approve', comment: 'LGTM', reviewer: 'alice' }),
    ]
    const wrapper = mountTimeline(reviews)
    const items = wrapper.findAll('[data-testid="spec-review-item"]')
    expect(items.length).toBe(2)
    // 第一条为 reject（与传入顺序一致）
    expect(items[0].text()).toContain(zhCN.specs.detail.decisionReject)
    expect(items[0].text()).toContain('bob')
    expect(items[1].text()).toContain(zhCN.specs.detail.decisionApprove)
    expect(items[1].text()).toContain('alice')
  })

  it('renders unknown reviewer for null reviewer', () => {
    const wrapper = mountTimeline([makeReview({ reviewer: null })])
    expect(wrapper.text()).toContain(zhCN.specs.detail.unknownReviewer)
  })

  it('shows real empty-state copy for empty reviews', () => {
    const wrapper = mountTimeline([])
    expect(wrapper.text()).toContain(zhCN.specs.detail.reviewEmpty)
    expect(wrapper.findAll('[data-testid="spec-review-item"]').length).toBe(0)
  })
})
