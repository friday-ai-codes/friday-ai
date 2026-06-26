/**
 * 项目工作台守护测试（Phase 84 WB-01）。
 *
 * 覆盖：
 *  - WorkbenchShell 左导航 4 区块文案 + 点击切换 section + #hash 双向同步
 *  - OverviewSection 大盘人员身份徽章（PM/开发负责人/开发者/测试）
 *  - OverviewSection 工作区未就绪空态 / 人员·docs 加载错误态
 *
 * 文案以真实 zh-CN.json 断言（沿用 projects-list.spec.ts 范式）。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

// ── vue-router mock（WorkbenchShell 用 route.hash / router.replace）──
const routeState = reactive<{ hash: string }>({ hash: '' })
const replaceMock = vi.fn((loc: string | { hash?: string }) => {
  routeState.hash = typeof loc === 'string' ? loc : (loc.hash ?? '')
  return Promise.resolve()
})
vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace: replaceMock }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const listMembersMock = vi.fn()
const cursorRulesMock = vi.fn()
vi.mock('~/api/projects', () => ({
  projectsApi: {
    listMembers: (...a: unknown[]) => listMembersMock(...a),
    cursorRules: (...a: unknown[]) => cursorRulesMock(...a),
  },
}))

const listDocsMock = vi.fn()
const rebuildMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: {
    listDocs: (...a: unknown[]) => listDocsMock(...a),
    rebuildWorkspace: (...a: unknown[]) => rebuildMock(...a),
  },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const WorkbenchShell = (await import('~/components/project/workbench/WorkbenchShell.vue')).default
const OverviewSection = (await import('~/components/project/workbench/OverviewSection.vue')).default

const selectStubs = {
  Select: { template: '<div><slot /></div>' },
  SelectContent: { template: '<div><slot /></div>' },
  SelectItem: { template: '<div><slot /></div>' },
  SelectTrigger: { template: '<div><slot /></div>' },
  SelectValue: { template: '<div />' },
}

function makeSections() {
  return [
    { id: 'overview', label: zhCN.projects.workbench.nav.overview, icon: 'icon-[lucide--layout-dashboard]' },
    { id: 'docs', label: zhCN.projects.workbench.nav.docs, icon: 'icon-[lucide--files]' },
    { id: 'feature', label: zhCN.projects.workbench.nav.feature, icon: 'icon-[lucide--list-tree]' },
    { id: 'deps', label: zhCN.projects.workbench.nav.deps, icon: 'icon-[lucide--network]' },
  ]
}

function mountShell() {
  return mount(WorkbenchShell, {
    props: { sections: makeSections(), navLabel: zhCN.projects.workbench.nav.sectionLabel },
    slots: {
      default: '<template #default="{ active }"><div data-testid="active-section">{{ active }}</div></template>',
    },
    global: { plugins: [i18n], stubs: selectStubs },
  })
}

function makeProject(overrides: Record<string, unknown> = {}) {
  return {
    id: 'p1',
    space_id: 's1',
    space_name: '空间一',
    name: '登录重构',
    description: '描述',
    status: 'developing',
    feishu_project_key: 'k1',
    feishu_board_url: '',
    feishu_board_id: '',
    created_by_id: null,
    member_count: 4,
    created_at: '2026-06-20T00:00:00Z',
    updated_at: '2026-06-20T00:00:00Z',
    ...overrides,
  }
}

function makeMember(id: string, role: string) {
  return {
    id,
    user: { id: `u-${id}`, username: `user${id}`, display_name: `用户${id}` },
    role,
    created_at: '2026-06-20T00:00:00Z',
  }
}

function mountOverview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(OverviewSection, {
    props: { project: makeProject() as any, canManage: true },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('workbenchShell 左导航 + section 切换', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeState.hash = ''
  })

  it('渲染 4 个区块导航（真实 zh-CN 文案）', () => {
    const wrapper = mountShell()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.nav.overview)
    expect(text).toContain(zhCN.projects.workbench.nav.docs)
    expect(text).toContain(zhCN.projects.workbench.nav.feature)
    expect(text).toContain(zhCN.projects.workbench.nav.deps)
    // 默认激活第一个区块
    expect(wrapper.find('[data-testid="active-section"]').text()).toBe('overview')
  })

  it('点击左导航切换右侧 section 并同步 #hash', async () => {
    const wrapper = mountShell()
    await wrapper.find('[data-testid="workbench-nav-docs"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="active-section"]').text()).toBe('docs')
    expect(replaceMock).toHaveBeenCalledWith({ hash: '#docs' })
  })

  it('带 #hash 直达对应区块（深链书签）', async () => {
    routeState.hash = '#feature'
    const wrapper = mountShell()
    await flushPromises()
    expect(wrapper.find('[data-testid="active-section"]').text()).toBe('feature')
  })
})

describe('overviewSection 大盘（人员身份 + 状态栏）', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    cursorRulesMock.mockResolvedValue({ filename: 'rules.mdc', content: '# rules' })
  })

  it('人员按身份映射展示徽章（PM/开发负责人/开发者/测试）', async () => {
    listMembersMock.mockResolvedValue([
      makeMember('1', 'pm'),
      makeMember('2', 'owner'),
      makeMember('3', 'frontend'),
      makeMember('4', 'qa'),
    ])
    listDocsMock.mockResolvedValue([
      { id: 'd1', project_id: 'p1', doc_type: 'memory', feishu_document_id: '', feishu_doc_token: '', sync_status: 'synced', last_synced_revision: 1, created_at: '', updated_at: '' },
    ])
    const wrapper = mountOverview()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.overview.identity.pm)
    expect(text).toContain(zhCN.projects.workbench.overview.identity.owner)
    expect(text).toContain(zhCN.projects.workbench.overview.identity.developer)
    expect(text).toContain(zhCN.projects.workbench.overview.identity.qa)
    // 状态栏：重建工作区按钮
    expect(wrapper.find('[data-testid="rebuild-workspace-btn"]').exists()).toBe(true)
  })

  it('工作区未就绪显示空态文案', async () => {
    listMembersMock.mockResolvedValue([])
    listDocsMock.mockResolvedValue([])
    const wrapper = mountOverview()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.workbench.overview.emptyTitle)
  })

  it('docs 与人员加载失败显示错误态', async () => {
    listMembersMock.mockRejectedValue(new Error('boom'))
    listDocsMock.mockRejectedValue(new Error('boom'))
    const wrapper = mountOverview()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain(zhCN.projects.workbench.overview.peopleLoadError)
    expect(text).toContain(zhCN.projects.workbench.overview.docsLoadError)
  })
})
