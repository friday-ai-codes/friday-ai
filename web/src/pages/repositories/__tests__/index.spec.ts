import type { Repository } from '~/types'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

const listMock = vi.fn()

vi.mock('~/api', () => ({
  repositoriesApi: {
    list: (...args: unknown[]) => listMock(...args),
  },
}))

vi.mock('vue-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue-router')>()
  return {
    ...actual,
    useRoute: vi.fn(() => ({ query: {}, params: {}, path: '/repositories' })),
    useRouter: vi.fn(() => ({ push: vi.fn(), replace: vi.fn() })),
  }
})

function makeRepository(overrides: Partial<Repository> = {}): Repository {
  return {
    id: overrides.id ?? 'repo-1',
    name: overrides.name ?? 'study-app',
    git_url: overrides.git_url ?? 'https://gitlab.yc345.tv/frontend/study-app.git',
    git_platform: overrides.git_platform ?? 'gitlab',
    default_branch: overrides.default_branch ?? 'master',
    base_branch: overrides.base_branch ?? null,
    created_at: overrides.created_at ?? '2026-06-10T10:00:00Z',
    updated_at: overrides.updated_at ?? '2026-06-10T10:00:00Z',
    has_credential: overrides.has_credential ?? true,
    spaces: overrides.spaces ?? [],
    proxy_url: overrides.proxy_url ?? '',
    auto_index_enabled: overrides.auto_index_enabled ?? true,
    webhook_secret: overrides.webhook_secret ?? null,
    linked_spaces_count: overrides.linked_spaces_count ?? 2,
    index_status: overrides.index_status ?? 'indexed',
    last_indexed_at: overrides.last_indexed_at ?? '2026-06-10T10:31:29Z',
    remote_head_sha: overrides.remote_head_sha ?? null,
    remote_head_checked_at: overrides.remote_head_checked_at ?? null,
    behind_commits: overrides.behind_commits ?? null,
    last_indexed_commit_sha: overrides.last_indexed_commit_sha ?? null,
    auto_build_graph_enabled: overrides.auto_build_graph_enabled ?? true,
    graph_build_status: overrides.graph_build_status ?? 'idle',
    graph_stage: overrides.graph_stage ?? '',
    current_graph_file: overrides.current_graph_file ?? '',
    graph_files_processed: overrides.graph_files_processed ?? 0,
    graph_files_total: overrides.graph_files_total ?? 0,
    graph_last_built_at: overrides.graph_last_built_at ?? null,
  }
}

const PageContainerStub = defineComponent({
  template: '<main><slot /></main>',
})

const PageHeaderStub = defineComponent({
  props: ['title', 'description'],
  template: '<header><h1>{{ title }}</h1><p>{{ description }}</p><slot name="actions" /></header>',
})

const StatusBadgeStub = defineComponent({
  props: ['status'],
  template: '<span class="status-badge-stub">{{ status }}</span>',
})

const PassthroughStub = defineComponent({
  template: '<div><slot /></div>',
})

const ButtonStub = defineComponent({
  template: '<button><slot /></button>',
})

const RouterLinkStub = defineComponent({
  props: ['to'],
  template: '<a :href="typeof to === `string` ? to : `#`"><slot /></a>',
})

const RepositoryIndexPage = (await import('../index.vue')).default

describe('/repositories index page', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('renders indexed repositories as quiet management cards', async () => {
    listMock.mockResolvedValue([
      makeRepository({
        id: 'repo-1',
        name: 'study-app',
        git_url: 'https://gitlab.yc345.tv/frontend/study-app.git',
      }),
    ])

    const wrapper = mount(RepositoryIndexPage, {
      global: {
        stubs: {
          Badge: PassthroughStub,
          Button: ButtonStub,
          EmptyState: PassthroughStub,
          LoadingState: PassthroughStub,
          PageContainer: PageContainerStub,
          PageHeader: PageHeaderStub,
          RouterLink: RouterLinkStub,
          StatusBadge: StatusBadgeStub,
          SddMethodologyBadge: PassthroughStub,
          GridPager: PassthroughStub,
          Tooltip: PassthroughStub,
          TooltipContent: PassthroughStub,
          TooltipProvider: PassthroughStub,
          TooltipTrigger: PassthroughStub,
        },
      },
    })
    await flushPromises()

    const card = wrapper.find('.repo-card')
    expect(card.exists()).toBe(true)
    expect(card.text()).toContain('study-app')
    expect(card.find('.status-badge-stub').text()).toBe('indexed')

    const urlChip = card.find('.repo-url-chip')
    expect(urlChip.exists()).toBe(true)
    expect(urlChip.text()).toContain('https://gitlab.yc345.tv/frontend/study-app.git')

    expect(card.findAll('.repo-meta-item').some(item => item.text().includes('索引于'))).toBe(true)
    expect(card.find('.repo-card-actions').text()).toContain('查看详情')
    expect(card.text()).toContain('代码索引')
    expect(card.text()).toContain('凭证管理')
  })
})
