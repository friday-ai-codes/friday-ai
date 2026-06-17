/**
 * pages/specs/index.vue 守护测试（Phase 50-05，D-50-5）。
 *
 * 覆盖：列表渲染行 + 状态徽标真实 zh-CN 文案；空结果显示 specs.empty 真实文案。
 */

import type { SddSpec } from '~/api/specs'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import SpecsIndexPage from '~/pages/specs/index.vue'

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('~/api/specs', () => ({
  specsApi: { list: vi.fn() },
}))

const { specsApi } = await import('~/api/specs')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeSpec(overrides: Partial<SddSpec> = {}): SddSpec {
  return {
    id: 's-1',
    status: 'in_review',
    change_kind: 'proposal',
    repository_id: 'repo-1',
    repository_name: 'demo-repo',
    work_item: { id: 'wi-1', title: '登录需求' },
    updated_at: '2026-06-17T00:00:00Z',
    ...overrides,
  }
}

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SpecsIndexPage, {
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('specsIndexPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders spec rows with real zh-CN status badge', async () => {
    vi.mocked(specsApi.list).mockResolvedValue([
      makeSpec({ id: 's-1', status: 'in_review', work_item: { id: 'wi-1', title: '登录需求' } }),
      makeSpec({ id: 's-2', status: 'approved', repository_name: 'repo-b', work_item: null }),
    ])
    const wrapper = mountPage()
    await flushPromises()

    const rows = wrapper.findAll('[data-testid="spec-row"]')
    expect(rows.length).toBe(2)
    expect(wrapper.text()).toContain('登录需求')
    expect(wrapper.text()).toContain(zhCN.specs.status.in_review)
    expect(wrapper.text()).toContain(zhCN.specs.status.approved)
  })

  it('shows real empty-state copy when no specs', async () => {
    vi.mocked(specsApi.list).mockResolvedValue([])
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="spec-row"]').length).toBe(0)
    expect(wrapper.text()).toContain(zhCN.specs.empty)
  })
})
