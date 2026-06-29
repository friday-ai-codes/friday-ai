/**
 * DependenciesSection 守护测试（WB-04）。
 *
 * 覆盖：外部工件 / 分支(Phase85) / 仓库 / 知识 / 项目 / PR 分组渲染 /
 * PR 列表渲染 / 工件按类型分组可查看 / 各分组空态真实 zh-CN 文案。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
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
const graphMock = vi.fn()
const getProjectMock = vi.fn()
const getReposMock = vi.fn()
const listBranchesMock = vi.fn()
const bindBranchMock = vi.fn()
const unbindBranchMock = vi.fn()
vi.mock('~/api/projects', () => ({
  projectsApi: {
    graph: (...a: unknown[]) => graphMock(...a),
    get: (...a: unknown[]) => getProjectMock(...a),
    // #4：关联仓库改为项目级端点（业务关联 ∪ 分支绑定），不再走空间仓库池。
    repositories: (...a: unknown[]) => getReposMock(...a),
    // #3：关联分支改为 ProjectBranch 绑定。
    listBranches: (...a: unknown[]) => listBranchesMock(...a),
    bindBranch: (...a: unknown[]) => bindBranchMock(...a),
    unbindBranch: (...a: unknown[]) => unbindBranchMock(...a),
  },
}))
const getSpaceReposMock = vi.fn()
vi.mock('~/api/spaces', () => ({
  getSpaceRepositories: (...a: unknown[]) => getSpaceReposMock(...a),
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../DependenciesSection.vue')).default

function mountComp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function setupEmpty() {
  artifactsListMock.mockResolvedValue([])
  mrListMock.mockResolvedValue([])
  graphMock.mockResolvedValue({ project_id: 'p1', nodes: [] })
  getProjectMock.mockResolvedValue({ id: 'p1', space_id: 's1' })
  getReposMock.mockResolvedValue([])
  listBranchesMock.mockResolvedValue([])
  getSpaceReposMock.mockResolvedValue([])
}

describe('dependenciesSection（WB-04）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('渲染六个依赖分组（含分支 Phase85 占位）', async () => {
    setupEmpty()
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.find('[data-testid="deps-artifacts"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-branches"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-repos"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-knowledge"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-projects"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="deps-mrs"]').exists()).toBe(true)
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.deps.artifactsTitle)
    expect(text).toContain(zhCN.projects.workbench.deps.branchesTitle)
    expect(text).toContain(zhCN.projects.workbench.deps.branchesEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.mergeRequestsTitle)
  })

  it('PR 列表渲染（外链 + 状态徽标）', async () => {
    setupEmpty()
    mrListMock.mockResolvedValue([
      {
        id: 'mr1',
        project_id: 'p1',
        repository_id: 'r1',
        work_item_id: null,
        platform: 'github',
        external_id: '12',
        url: 'https://github.com/x/y/pull/12',
        title: '登录重构 PR',
        source_branch: 'feat/login',
        target_branch: 'main',
        status: 'open',
        review_status: '',
        created_at: '2026-06-20T00:00:00Z',
        updated_at: '2026-06-20T00:00:00Z',
      },
    ])
    const wrapper = mountComp()
    await flushPromises()
    const rows = wrapper.findAll('[data-testid="deps-mr-row"]')
    expect(rows.length).toBe(1)
    expect(wrapper.text()).toContain('登录重构 PR')
    expect(wrapper.text()).toContain(zhCN.projects.links.mrStatus.open)
  })

  it('外部工件按类型分组渲染并可查看', async () => {
    setupEmpty()
    artifactsListMock.mockResolvedValue([
      {
        id: 'a1',
        project_id: 'p1',
        type_id: 't1',
        type_key: 'ui_design',
        type_name: 'UI 稿',
        ragable: false,
        carrier: 'external_link',
        title: '登录页 UI',
        url: 'https://figma.com/x',
        content_ref: '',
        version: 1,
        contributor_id: null,
        created_at: '2026-06-20T00:00:00Z',
        updated_at: '2026-06-20T00:00:00Z',
      },
    ])
    const wrapper = mountComp()
    await flushPromises()
    expect(wrapper.findAll('[data-testid="deps-artifact-row"]').length).toBe(1)
    expect(wrapper.text()).toContain('UI 稿')
    expect(wrapper.find('[data-testid="deps-view-artifact-btn"]').exists()).toBe(true)
  })

  it('各分组空态渲染真实 zh-CN 文案', async () => {
    setupEmpty()
    const wrapper = mountComp()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.deps.artifactsEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.repositoriesEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.knowledgeEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.projectsEmpty)
    expect(text).toContain(zhCN.projects.workbench.deps.mrEmpty)
  })
})
