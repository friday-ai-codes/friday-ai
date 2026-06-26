/**
 * DependenciesSection 守护测试（WB-04）。
 *
 * 覆盖：外部工件分组 + PR 列表渲染 / 分支 Phase 85 占位 / 各分组空态（真实 zh-CN 文案）。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const artifactsListMock = vi.fn()
const artifactsViewMock = vi.fn()
vi.mock('~/api/artifacts', () => ({
  artifactsApi: {
    list: (...a: unknown[]) => artifactsListMock(...a),
    view: (...a: unknown[]) => artifactsViewMock(...a),
  },
}))

const mrListMock = vi.fn()
vi.mock('~/api/mergeRequests', () => ({
  mergeRequestsApi: { list: (...a: unknown[]) => mrListMock(...a) },
}))

const projectGetMock = vi.fn()
const projectGraphMock = vi.fn()
vi.mock('~/api/projects', () => ({
  projectsApi: {
    get: (...a: unknown[]) => projectGetMock(...a),
    graph: (...a: unknown[]) => projectGraphMock(...a),
  },
}))

const reposMock = vi.fn()
vi.mock('~/api/spaces', () => ({
  getSpaceRepositories: (...a: unknown[]) => reposMock(...a),
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../DependenciesSection.vue')).default

function mountSection() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function setEmptyDefaults() {
  artifactsListMock.mockResolvedValue([])
  mrListMock.mockResolvedValue([])
  projectGetMock.mockResolvedValue({ id: 'p1', space_id: 's1', name: '项目一' })
  projectGraphMock.mockResolvedValue({ project_id: 'p1', nodes: [] })
  reposMock.mockResolvedValue([])
}

describe('DependenciesSection（WB-04 外部依赖/关联）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setEmptyDefaults()
  })

  it('渲染各分组标题与分支 Phase 85 占位', async () => {
    const wrapper = mountSection()
    await flushPromises()

    expect(wrapper.find('[data-testid="deps-artifacts"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-branches"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-repos"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-knowledge"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-mrs"]').exists()).toBe(true)

    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.deps.artifactsTitle)
    expect(text).toContain(zhCN.projects.workbench.deps.branchesTitle)
    expect(text).toContain(zhCN.projects.workbench.deps.branchesDeferred)
    expect(text).toContain(zhCN.projects.workbench.deps.mergeRequestsTitle)
  })

  it('渲染外部工件分组与 PR 列表', async () => {
    artifactsListMock.mockResolvedValue([
      {
        id: 'a1',
        project_id: 'p1',
        type_id: 't1',
        type_key: 'ui_design',
        type_name: 'UI 稿',
        ragable: false,
        carrier: 'feishu_doc',
        title: '登录页 UI 稿',
        url: 'https://example.com/doc',
        content_ref: '',
        version: 2,
        contributor_id: null,
        created_at: '2026-06-20T00:00:00Z',
        updated_at: '2026-06-20T00:00:00Z',
      },
    ])
    mrListMock.mockResolvedValue([
      {
        id: 'mr1',
        project_id: 'p1',
        repository_id: 'r1',
        work_item_id: null,
        platform: 'github',
        external_id: '12',
        url: 'https://github.com/x/y/pull/12',
        title: '实现登录',
        source_branch: 'feat/login',
        target_branch: 'main',
        status: 'open',
        review_status: '',
        created_at: '2026-06-20T00:00:00Z',
        updated_at: '2026-06-20T00:00:00Z',
      },
    ])
    const wrapper = mountSection()
    await flushPromises()

    expect(wrapper.findAll('[data-testid="deps-artifact-row"]').length).toBe(1)
    expect(wrapper.text()).toContain('登录页 UI 稿')
    expect(wrapper.text()).toContain('UI 稿')

    const mrRows = wrapper.findAll('[data-testid="deps-mr-row"]')
    expect(mrRows.length).toBe(1)
    expect(wrapper.text()).toContain('实现登录')
    expect(wrapper.text()).toContain(zhCN.projects.links.mrStatus.open)
  })

  it('渲染关联仓库（经所属空间）', async () => {
    reposMock.mockResolvedValue([
      { id: 'lk1', repository_id: 'r1', repository_name: 'friday-web', permission_level: 'read', created_at: '2026-06-20T00:00:00Z' },
    ])
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="deps-repo-row"]').length).toBe(1)
    expect(wrapper.text()).toContain('friday-web')
  })

  it('各分组空态渲染 zh-CN 文案', async () => {
    const wrapper = mountSection()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.deps.artifactsEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.repositoriesEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.knowledgeEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.projectsEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.mrEmpty)
  })
})
