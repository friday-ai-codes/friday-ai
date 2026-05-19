/**
 * RepositoryKnowledgeHub — 统一知识库区块单测
 */
import type { Repository } from '~/types'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import RepositoryKnowledgeHub from '../RepositoryKnowledgeHub.vue'
vi.mock('~/api/repositories', => ({
 IndexStatus: {
 NOT_INDEXED: 'not_indexed',
 INDEXING: 'indexing',
 INDEXED: 'indexed',
 FAILED: 'failed',
 CANCELLED: 'cancelled',
 },
 repositoriesApi: {
 get: vi.fn,
 getIndexStatus: vi.fn,
 getCollectionHealth: vi.fn,
 getIndexHistory: vi.fn.mockResolvedValue({ items:, total: 0 }),
 refreshRemoteHead: vi.fn,
 },
}))
vi.mock('~/api/codegraph', => ({
 listGraphHistory: vi.fn.mockResolvedValue({ count: 0, results:, next: null, previous: null }),
}))
vi.mock('@vueuse/core', async (importOriginal) => {
 const actual = await importOriginal<typeof import('@vueuse/core')>
 return {
 ...actual,
 useLocalStorage: vi.fn.mockImplementation((_key: string, defaultVal: unknown) => ref(defaultVal)),
 }
})
const stubComponents = {
 RepositoryIndexCard: defineComponent({ props: ['repositoryId', 'embedded'], template: '<div class="index-stub" />' }),
 RepositoryGraphCard: defineComponent({ props: ['repositoryId', 'embedded'], template: '<div class="graph-stub" />' }),
 KnowledgeBaseSection: defineComponent({ props: ['repositoryId', 'embedded'], template: '<div class="kbs-stub" />' }),
 IndexStatsPanel: defineComponent({ props: ['repositoryId'], template: '<div class="stats-stub" />' }),
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
 spaces:,
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
function mountHub {
 return mount(RepositoryKnowledgeHub, {
 props: { repositoryId: 'repo-1', gitUrl: 'https://github.com/a/b.git' },
 global: { stubs: stubComponents },
 })
}
describe('repositoryKnowledgeHub', => {
 beforeEach( => {
 vi.clearAllMocks
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo)
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
 it('渲染统一标题「知识库」与三阶段 pipeline', async => {
 const wrapper = mountHub
 await flushPromises
 expect(wrapper.text).toContain('知识库')
 expect(wrapper.text).toContain('向量索引')
 expect(wrapper.text).toContain('结构化图谱')
 expect(wrapper.text).toContain('GraphRAG')
 })
 it('包含四个 Tab：索引管理 / 图谱构建 / 图谱浏览 / 统计与历史', async => {
 const wrapper = mountHub
 await flushPromises
 expect(wrapper.text).toContain('索引管理')
 expect(wrapper.text).toContain('图谱构建')
 expect(wrapper.text).toContain('图谱浏览')
 expect(wrapper.text).toContain('统计与历史')
 })
})
