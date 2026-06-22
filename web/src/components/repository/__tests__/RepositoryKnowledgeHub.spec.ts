/**
 * RepositoryKnowledgeHub — 统一知识库区块单测
 */
import type { Repository } from '~/types'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { getCodegraphStats } from '~/api/codegraph'
import { repositoriesApi } from '~/api/repositories'
import RepositoryKnowledgeHub from '../RepositoryKnowledgeHub.vue'

vi.mock('~/api/repositories', () => ({
  IndexStatus: {
    NOT_INDEXED: 'not_indexed',
    INDEXING: 'indexing',
    INDEXED: 'indexed',
    FAILED: 'failed',
    CANCELLED: 'cancelled',
  },
  repositoriesApi: {
    get: vi.fn(),
    getIndexStatus: vi.fn(),
    getCollectionHealth: vi.fn(),
    getGraphRagStatus: vi.fn().mockResolvedValue({ edge_count: 0, status: 'pending', last_synced_at: null }),
    // ：IndexStatsPanel 触达需 mock，否则报 undefined（Pitfall C）
    getIndexStats: vi.fn().mockResolvedValue({
      chunks_total: 0,
      indexed_files_count: 0,
      coverage_percent: null,
      language_distribution: {},
      qdrant_unavailable: false,
    }),
    refreshRemoteHead: vi.fn(),
  },
}))

vi.mock('~/api/codegraph', () => ({
  listGraphHistory: vi.fn().mockResolvedValue({ count: 0, results: [], next: null, previous: null }),
  // "N 关系" 改读 codegraph 累计 stats（区别于最近一次 build 的 per-run delta）
  getCodegraphStats: vi.fn().mockResolvedValue({
    symbols: 0,
    imports: 0,
    calls: 0,
    endpoints: 0,
    total: 0,
  }),
}))

vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  return {
    ...actual,
    useLocalStorage: vi.fn().mockImplementation((_key: string, defaultVal: unknown) => ref(defaultVal)),
  }
})

const stubComponents = {
  RepositoryIndexCard: defineComponent({ props: ['repositoryId', 'embedded'], template: '<div class="index-stub" />' }),
  RepositoryGraphCard: defineComponent({ props: ['repositoryId', 'embedded'], template: '<div class="graph-stub" />' }),
  KnowledgeBaseSection: defineComponent({ props: ['repositoryId', 'embedded'], template: '<div class="kbs-stub" />' }),
  IndexStatsPanel: defineComponent({ props: ['repositoryId', 'branch'], template: '<div class="stats-stub" :data-branch="branch ?? \'\'" />' }),
  BranchCombobox: defineComponent({ props: ['branches', 'indexRows', 'recommendedBranch', 'modelValue', 'disabled'], template: '<div class="branch-combobox-stub" :data-branches="(branches ?? []).join(\',\')" :data-model="modelValue ?? \'\'" />' }),
  BranchIndexHealthSection: defineComponent({ props: ['row'], template: '<div class="branch-health-stub" />' }),
  GraphSearchModal: defineComponent({ props: ['repositoryId', 'branch', 'open'], template: '<div class="graph-search-stub" :data-branch="branch ?? \'\'" />' }),
  IndexedFilesPanel: defineComponent({ template: '<div class="files-stub" />' }),
  IndexHistoryList: defineComponent({ template: '<div class="history-stub" />' }),
  IndexProgressTimeline: defineComponent({ template: '<div class="timeline-stub" />' }),
  StatusBadge: defineComponent({ template: '<span class="status-badge-stub"><slot /></span>' }),
  Button: defineComponent({ template: '<button v-bind="$attrs"><slot /></button>' }),
  Tabs: defineComponent({ template: '<div><slot /></div>' }),
  TabsList: defineComponent({ template: '<div><slot /></div>' }),
  TabsTrigger: defineComponent({ template: '<button><slot /></button>' }),
  TabsContent: defineComponent({ template: '<div><slot /></div>' }),
  Tooltip: defineComponent({ template: '<div><slot /></div>' }),
  TooltipProvider: defineComponent({ template: '<div><slot /></div>' }),
  TooltipTrigger: defineComponent({ template: '<div><slot /></div>' }),
  TooltipContent: defineComponent({ template: '<div><slot /></div>' }),
}

function makeRepo(overrides: Partial<Repository> = {}): Repository {
  return {
    id: 'repo-1',
    name: 'test',
    git_url: 'https://github.com/a/b.git',
    git_platform: 'github',
    default_branch: 'main',
    has_credential: true,
    spaces: [],
    auto_index_enabled: false,
    auto_build_graph_enabled: true,
    index_status: 'indexed',
    last_indexed_at: '2024-01-01T00:00:00Z',
    last_indexed_commit_sha: 'abc1234abc1234',
    remote_head_sha: 'abc1234abc1234',
    remote_head_checked_at: '2024-01-01T10:00:00Z',
    graph_build_status: 'completed',
    graph_stage: '',
    current_graph_file: '',
    graph_files_processed: 0,
    graph_files_total: 0,
    graph_last_built_at: '2024-01-02T00:00:00Z',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  } as Repository
}

function mountHub(props: Record<string, unknown> = {}) {
  return mount(RepositoryKnowledgeHub, {
    props: {
      repositoryId: 'repo-1',
      gitUrl: 'https://github.com/a/b.git',
      branches: ['main', 'feature-x'],
      indexRows: [],
      recommendedBranch: 'main',
      selectedBranch: 'main',
      ...props,
    },
    global: { stubs: stubComponents },
  })
}

describe('repositoryKnowledgeHub', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo())
    vi.mocked(repositoriesApi.getIndexStatus).mockResolvedValue({
      index_status: 'indexed',
      last_indexed_at: '2024-01-01T00:00:00Z',
    } as never)
    vi.mocked(repositoriesApi.getCollectionHealth).mockResolvedValue({
      status: 'healthy',
      points_count: 12345,
      indexed_files_count: 100,
    } as never)
  })

  it('渲染统一标题「知识库」与三阶段 pipeline', async () => {
    const wrapper = mountHub()
    await flushPromises()
    expect(wrapper.text()).toContain('知识库')
    expect(wrapper.text()).toContain('向量索引')
    expect(wrapper.text()).toContain('结构化图谱')
    expect(wrapper.text()).toContain('GraphRAG')
  })

  it('包含四个 Tab：索引管理 / 图谱构建 / 图谱浏览 / 统计与历史', async () => {
    const wrapper = mountHub()
    await flushPromises()
    expect(wrapper.text()).toContain('索引管理')
    expect(wrapper.text()).toContain('图谱构建')
    expect(wrapper.text()).toContain('图谱浏览')
    expect(wrapper.text()).toContain('统计与历史')
  })

  it('graphRAG 卡展示真实 ChunkEdge 计数（修复「0 语义边」误显示）', async () => {
    vi.mocked(repositoriesApi.getGraphRagStatus).mockResolvedValue({
      edge_count: 35900,
      status: 'completed',
      last_synced_at: '2024-01-02T00:00:00Z',
    })
    const wrapper = mountHub()
    await flushPromises()
    // 真实计数应渲染（toLocaleString 千分位），而非旧快照漏写的 0/—
    expect(wrapper.text()).toContain('35,900 语义边')
  })

  it('结构化图谱「N 关系」读 codegraph 累计 stats（而非最近一次 build 的 per-run delta）', async () => {
    vi.mocked(getCodegraphStats).mockResolvedValue({
      symbols: 12678,
      imports: 2107,
      calls: 29206,
      endpoints: 0,
      total: 43991,
    })
    const wrapper = mountHub()
    await flushPromises()
    expect(getCodegraphStats).toHaveBeenCalledWith('repo-1')
    // 43991 = 12678 + 2107 + 29206 + 0（累计），千分位渲染
    expect(wrapper.text()).toContain('43,991 关系')
    expect(wrapper.text()).toContain('12678 符号 · 29206 调用')
  })

  it('hub 头部渲染 BranchCombobox 并透传 branches', async () => {
    const wrapper = mountHub()
    await flushPromises()
    const combobox = wrapper.find('.branch-combobox-stub')
    expect(combobox.exists()).toBe(true)
    expect(combobox.attributes('data-branches')).toBe('main,feature-x')
    expect(combobox.attributes('data-model')).toBe('main')
  })

  it('切分支即时带 branch（UX-02 红线）', async () => {
    const wrapper = mountHub({ selectedBranch: 'main' })
    await flushPromises()
    // 初始以 main 拉取
    expect(repositoriesApi.getGraphRagStatus).toHaveBeenLastCalledWith('repo-1', 'main')

    await wrapper.setProps({ selectedBranch: 'feature-x' })
    await flushPromises()
    // 切分支后 graphrag-status 以新 branch 重拉
    expect(repositoriesApi.getGraphRagStatus).toHaveBeenLastCalledWith('repo-1', 'feature-x')
    // GraphSearchModal 收到新 branch
    expect(wrapper.find('.graph-search-stub').attributes('data-branch')).toBe('feature-x')
    // IndexStatsPanel 收到新 branch
    expect(wrapper.find('.stats-stub').attributes('data-branch')).toBe('feature-x')
  })

  it('base 态（selectedBranch=null）不污染 query', async () => {
    mountHub({ selectedBranch: null })
    await flushPromises()
    // base 态传 falsy branch；getGraphRagStatus 内部 `branch || undefined` 再归一化为
    // 不发 branch query（client.ts 仅跳过 undefined），保持与现状字节级一致。
    const lastCall = vi.mocked(repositoriesApi.getGraphRagStatus).mock.lastCall
    expect(lastCall?.[0]).toBe('repo-1')
    expect(lastCall?.[1] ?? undefined).toBeFalsy()
  })
})
