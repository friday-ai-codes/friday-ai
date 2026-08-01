/**
 * 知识库「技术方案」tab 面板的页面测试（Phase 115-06）。
 *
 * 覆盖的七条（编号与 115-06-PLAN Task 3 ⑧逐条对应）：
 *  1. 列表渲染 N 张卡，且整卡是深链 `/knowledge/blueprints/{artifact_id}`（SC-4）。
 *  2. ⭐ 消费的是 **`current_status`** —— fixture 刻意**不给** `blueprint_status`，徽标仍要正常
 *     渲染。读错键的症状是徽标恒显示「旧版方案」，不报错也不空白。
 *  3. `unresolved_blocker_count` 为 0 ⇒ 阻塞徽标整块不渲染；> 0 ⇒ 渲染（正反并列）。
 *  4. 改筛选 ⇒ 写回 URL 且 query 含 `bp_status`，并**保留既有的 `tab`**（展开写法的价值就在这）。
 *  5. ⭐ 搜索输入 / 提交分离：光输入不发请求，回车才发。
 *  6. 五键分页：`total` 驱动分页器，`has_next` 为真时分页器出现。
 *  7. 空态用 `CompactEmptyState` 且 `icon` 是**裸名**（传完整类名会什么都不显示，P-6）。
 *
 * 范式照 `pages/knowledge/__tests__/entity-detail.spec.ts`（手写最小 i18n 键树，⛔ 不 import
 * `zh-CN.json`）。
 */

import type { BlueprintListItem } from '~/types/blueprint'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintsTabPanel from '~/components/knowledge/BlueprintsTabPanel.vue'

const { routeState, routerReplace, api, projectsMock, repositoriesMock } = vi.hoisted(() => ({
  routeState: { params: {} as Record<string, string>, query: {} as Record<string, string> },
  routerReplace: vi.fn(),
  api: { listBlueprints: vi.fn() },
  projectsMock: { list: vi.fn() },
  repositoriesMock: { list: vi.fn() },
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
  RouterLink: { name: 'RouterLink', props: ['to'], template: '<a :href="to"><slot /></a>' },
}))

vi.mock('~/api/blueprints', () => ({ default: api }))
vi.mock('~/api/projects', () => ({ default: projectsMock, projectsApi: projectsMock }))
vi.mock('~/api/repositories', () => ({ repositoriesApi: repositoriesMock }))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      common: { clearFilters: '清除筛选' },
      knowledge: {
        blueprints: {
          statusUnknown: '未知状态',
          status: {
            researching: '调研中',
            drafting: '产出中',
            ai_reviewing: 'AI 审查中',
            needs_clarification: '需要澄清',
            pending_review: '待人类审查',
            confirmed: '已确认',
            implementing: '实施中',
            implemented: '实施完成',
            archived: '已归档',
            failed: '已失败',
            superseded: '已废弃',
            legacy: '旧版方案',
          },
          tabPanel: {
            searchPlaceholder: '搜索方案标题或摘要…',
            search: '搜索',
            filterProject: '所属项目',
            filterStatus: '方案状态',
            filterRepository: '涉及仓库',
            filterAll: '全部',
            resultCount: '共 {total} 份技术方案',
            threadCount: '批注 {n}',
            blockerCount: '阻塞 {n}',
            revisionRound: '修订 {n} 轮',
            versionNo: 'v{n}',
            emptyTitle: '没有匹配的技术方案',
            emptyBody: '换个筛选条件，或在项目里发起一次方案编排',
          },
          error: {
            unavailable: '暂时读取不到该方案，请稍后重试',
            retry: '重试',
          },
        },
      },
    },
  },
})

const CompactEmptyStateStub = {
  name: 'CompactEmptyState',
  props: ['icon', 'title', 'description'],
  template: '<div data-testid="empty-state-stub">{{ title }}</div>',
}

const SelectStub = {
  name: 'SelectStub',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<div><slot /></div>',
}

const PaginationStub = {
  name: 'PaginationStub',
  props: ['page', 'total', 'itemsPerPage'],
  template: '<div data-testid="pagination-stub" />',
}

const STUBS = {
  CompactEmptyState: CompactEmptyStateStub,
  Select: SelectStub,
  SelectTrigger: { template: '<div><slot /></div>' },
  SelectContent: { template: '<div><slot /></div>' },
  SelectItem: { props: ['value'], template: '<div><slot /></div>' },
  SelectValue: true,
  Pagination: PaginationStub,
}

/** ⭐ 刻意**不给** `blueprint_status` —— 读错键就会掉进「旧版方案」档。 */
function makeItem(overrides: Partial<BlueprintListItem> = {}): BlueprintListItem {
  return {
    artifact_id: 'aaaa-1111',
    title: '订单履约链路重构',
    summary: '把履约链路拆成三段',
    current_status: 'pending_review',
    project_id: 'p-1',
    project_name: '履约中台',
    repositories: [{ id: 'r-1', name: 'order-svc', role: 'direct' }],
    thread_count: 3,
    unresolved_blocker_count: 0,
    revision_round: 1,
    current_version_no: 4,
    updated_at: '2026-08-01T02:00:00Z',
    ...overrides,
  } as BlueprintListItem
}

function makeResponse(items: BlueprintListItem[], overrides: Record<string, unknown> = {}) {
  return { total: items.length, items, page: 1, page_size: 12, has_next: false, ...overrides }
}

function mountPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(BlueprintsTabPanel, {
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]], stubs: STUBS },
  })
}

const flush = () => new Promise(resolve => setTimeout(resolve, 60))

beforeEach(() => {
  vi.clearAllMocks()
  routeState.query = {}
  api.listBlueprints.mockResolvedValue(makeResponse([makeItem()]))
  projectsMock.list.mockResolvedValue([])
  repositoriesMock.list.mockResolvedValue([])
})

describe('蓝图列表 tab 面板', () => {
  it('1. 列表渲染 N 张卡，整卡是直达查看器的深链（SC-4）', async () => {
    api.listBlueprints.mockResolvedValue(makeResponse([
      makeItem({ artifact_id: 'aaaa-1111' }),
      makeItem({ artifact_id: 'bbbb-2222', title: '第二份' }),
    ]))
    const wrapper = mountPanel()
    await flush()
    const cards = wrapper.findAll('[data-testid="blueprint-list-card"]')
    expect(cards).toHaveLength(2)
    expect(cards[0].attributes('href')).toBe('/knowledge/blueprints/aaaa-1111')
    expect(cards[1].attributes('href')).toBe('/knowledge/blueprints/bbbb-2222')
  })

  it('2. ⭐ 消费的是 current_status（fixture 不带 blueprint_status，徽标仍正常）', async () => {
    const wrapper = mountPanel()
    await flush()
    expect(wrapper.text()).toContain('待人类审查')
    expect(wrapper.text()).not.toContain('旧版方案')
  })

  it('3. 阻塞计数为 0 ⇒ 不渲染；> 0 ⇒ 渲染（正反并列）', async () => {
    const wrapper = mountPanel()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-list-blocker"]').exists()).toBe(false)

    api.listBlueprints.mockResolvedValue(makeResponse([makeItem({ unresolved_blocker_count: 2 })]))
    const withBlocker = mountPanel()
    await flush()
    const badge = withBlocker.find('[data-testid="blueprint-list-blocker"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('2')
  })

  it('4. 改筛选 ⇒ 写回 URL 且含 bp_status，并保留既有的 tab', async () => {
    routeState.query = { tab: 'blueprints' }
    const wrapper = mountPanel()
    await flush()
    wrapper.findAllComponents(SelectStub)[0].vm.$emit('update:modelValue', 'pending_review')
    await flush()
    expect(routerReplace).toHaveBeenCalled()
    const query = routerReplace.mock.calls.at(-1)?.[0]?.query as Record<string, string>
    expect(query.bp_status).toBe('pending_review')
    expect(query.tab).toBe('blueprints')
  })

  it('5. ⭐ 搜索输入 / 提交分离：光输入不发请求，回车才发', async () => {
    const wrapper = mountPanel()
    await flush()
    const before = api.listBlueprints.mock.calls.length
    const input = wrapper.find('[data-testid="blueprint-search-input"]')
    await input.setValue('履约')
    await flush()
    expect(api.listBlueprints.mock.calls.length).toBe(before)

    await input.trigger('keydown.enter')
    await flush()
    expect(api.listBlueprints.mock.calls.length).toBe(before + 1)
    expect(api.listBlueprints.mock.calls.at(-1)?.[0]).toMatchObject({ q: '履约' })
  })

  it('6. 五键分页：total 驱动分页器，has_next 为真时分页器出现', async () => {
    api.listBlueprints.mockResolvedValue(makeResponse([makeItem()], { total: 30, has_next: true }))
    const wrapper = mountPanel()
    await flush()
    const pagination = wrapper.findComponent(PaginationStub)
    expect(pagination.exists()).toBe(true)
    expect(pagination.props('total')).toBe(30)
    expect(wrapper.text()).toContain('共 30 份技术方案')
  })

  it('7. 空态用 CompactEmptyState 且 icon 是裸名（⛔ 不是完整类名）', async () => {
    api.listBlueprints.mockResolvedValue(makeResponse([]))
    const wrapper = mountPanel()
    await flush()
    const empty = wrapper.findComponent(CompactEmptyStateStub)
    expect(empty.exists()).toBe(true)
    expect(String(empty.props('icon'))).not.toContain('icon-[')
    expect(empty.props('icon')).toBe('lucide--file-x')
  })
})

/**
 * ⭐ MJ-04 回归：读失败与「真的没数据」在界面上必须可分辨。
 *
 * 后端已改为聚合失败如实 503，但只改后端不够 —— 前端没有 `isError` 分档时，503 / 400 /
 * 网络断线一律落进 `v-else` 的空态，显示成「没有匹配的技术方案」。两层各自都「不反噬主
 * 流程」，合起来就是数据读失败对用户完全不可见。
 */
describe('蓝图列表 tab 面板 —— 读失败分档（MJ-04）', () => {
  it('8. ⭐ 请求失败 ⇒ 出现重试按钮，且⛔ 不出现「没有匹配的技术方案」', async () => {
    api.listBlueprints.mockRejectedValue(new Error('503 Service Unavailable'))
    const wrapper = mountPanel()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-list-error"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-list-retry"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="empty-state-stub"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('没有匹配的技术方案')
  })

  it('9. 非恒真对照：真的空 ⇒ 仍走空态，⛔ 不出现错误档', async () => {
    api.listBlueprints.mockResolvedValue(makeResponse([]))
    const wrapper = mountPanel()
    await flush()
    expect(wrapper.find('[data-testid="empty-state-stub"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('没有匹配的技术方案')
    expect(wrapper.find('[data-testid="blueprint-list-error"]').exists()).toBe(false)
  })

  it('10. 点重试重新发一次请求', async () => {
    api.listBlueprints.mockRejectedValue(new Error('boom'))
    const wrapper = mountPanel()
    await flush()
    const before = api.listBlueprints.mock.calls.length
    await wrapper.find('[data-testid="blueprint-list-retry"]').trigger('click')
    await flush()
    expect(api.listBlueprints.mock.calls.length).toBeGreaterThan(before)
  })
})
