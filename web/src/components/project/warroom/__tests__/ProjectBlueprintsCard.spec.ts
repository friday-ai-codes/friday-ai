/**
 * 项目侧技术方案蓝图卡的读失败分档（Phase 115-06；MJ-04 回归）。
 *
 * ## 这个 spec 存在的理由
 *
 * `hideWhenEmpty` 原本的判据是「不在 loading 且 items 为空」—— **错误态也满足它**。而本卡
 * 的查询是 `retry: false`（不重试），宿主 `ProjectMaterialsPanel` 正是传 `hide-when-empty`
 * 的 ⇒ 一次失败的请求就让整张「技术方案蓝图」卡**从项目页上凭空消失**，无任何痕迹。这是
 * 三层设计各自「不反噬主流程」叠加出来的最坏形状：读失败对用户完全不可见。
 *
 * 覆盖路径：
 *  1. ⭐ `hideWhenEmpty` + 请求失败 ⇒ 卡片**仍然存在**且给出重试入口。
 *  2. 非恒真对照：`hideWhenEmpty` + 真的空 ⇒ 卡片**确实隐藏**（否则「永不隐藏」也能让 1 变绿）。
 *  3. 不传 `hideWhenEmpty` + 真的空 ⇒ 卡片在，走空态而非错误态。
 *  4. 点重试重新发一次请求。
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import ProjectBlueprintsCard from '~/components/project/warroom/ProjectBlueprintsCard.vue'

const { api } = vi.hoisted(() => ({ api: { listBlueprints: vi.fn() } }))

vi.mock('~/api/blueprints', () => ({ default: api }))
vi.mock('vue-router', () => ({
  RouterLink: { name: 'RouterLink', props: ['to'], template: '<a :href="to"><slot /></a>' },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          pageTitle: '技术方案',
          pageDescription: '结构化蓝图，含批注与人审',
          statusUnknown: '未知状态',
          status: { pending_review: '待人类审查' },
          tabPanel: { emptyTitle: '没有匹配的技术方案' },
          error: { unavailable: '暂时读取不到该方案，请稍后重试', retry: '重试' },
        },
      },
    },
  },
})

const STUBS = {
  BlueprintStatusBadge: { name: 'BlueprintStatusBadge', props: ['status', 'size'], template: '<span />' },
  CompactEmptyState: {
    name: 'CompactEmptyState',
    props: ['icon', 'title'],
    template: '<div data-testid="empty-state-stub">{{ title }}</div>',
  },
  Badge: { template: '<span><slot /></span>' },
  Skeleton: { template: '<div />' },
}

const CARD = '[data-testid="project-blueprints-card"]'

function mountCard(hideWhenEmpty = true) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ProjectBlueprintsCard, {
    props: { projectId: 'p-1', hideWhenEmpty },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]], stubs: STUBS },
  })
}

const flush = () => new Promise(resolve => setTimeout(resolve, 60))

beforeEach(() => {
  vi.clearAllMocks()
  api.listBlueprints.mockResolvedValue({ total: 0, items: [], page: 1, page_size: 5, has_next: false })
})

describe('项目蓝图卡 —— 读失败不得让卡片消失（MJ-04）', () => {
  it('1. ⭐ hideWhenEmpty 且请求失败 ⇒ 卡片仍在，且有重试入口', async () => {
    api.listBlueprints.mockRejectedValue(new Error('503 Service Unavailable'))
    const wrapper = mountCard(true)
    await flush()
    expect(wrapper.find(CARD).exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-blueprints-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-blueprints-retry"]').exists()).toBe(true)
    // ⛔ 不得与空态同形
    expect(wrapper.find('[data-testid="empty-state-stub"]').exists()).toBe(false)
  })

  it('2. 非恒真对照：hideWhenEmpty 且真的空 ⇒ 卡片确实隐藏', async () => {
    const wrapper = mountCard(true)
    await flush()
    expect(wrapper.find(CARD).exists()).toBe(false)
  })

  it('3. 不隐藏空态时，真的空走空态而非错误态', async () => {
    const wrapper = mountCard(false)
    await flush()
    expect(wrapper.find(CARD).exists()).toBe(true)
    expect(wrapper.find('[data-testid="empty-state-stub"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="project-blueprints-error"]').exists()).toBe(false)
  })

  it('4. 点重试重新发一次请求', async () => {
    api.listBlueprints.mockRejectedValue(new Error('boom'))
    const wrapper = mountCard(true)
    await flush()
    const before = api.listBlueprints.mock.calls.length
    await wrapper.find('[data-testid="project-blueprints-retry"]').trigger('click')
    await flush()
    expect(api.listBlueprints.mock.calls.length).toBeGreaterThan(before)
  })

  it('5. 列表时间精确到分钟（YYYY-MM-DD HH:mm），不含秒', async () => {
    api.listBlueprints.mockResolvedValue({
      total: 1,
      items: [{
        artifact_id: 'a-1',
        title: '履约中台 - 技术方案 - 2026-08-06 09:33',
        summary: '',
        current_status: 'pending_review',
        project_id: 'p-1',
        project_name: '履约中台',
        repositories: [],
        thread_count: 0,
        unresolved_blocker_count: 0,
        revision_round: 0,
        current_version_no: 1,
        created_at: '2026-08-06T01:33:45.123Z',
        updated_at: '2026-08-06T01:33:45.123Z',
      }],
      page: 1,
      page_size: 5,
      has_next: false,
    })
    const wrapper = mountCard(false)
    await flush()
    const time = wrapper.find('[data-testid="project-blueprint-time"]')
    expect(time.exists()).toBe(true)
    expect(time.text()).toBe('2026-08-06 09:33')
    expect(time.text()).not.toMatch(/:\d{2}:\d{2}/)
  })
})
