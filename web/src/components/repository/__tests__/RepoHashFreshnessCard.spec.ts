/**
 * Phase Plan — RepoHashFreshnessCard 单测（work item §5/§6.1/§7）
 *
 * 测试三态视觉契约：FRESH/STALE/UNKNOWN 文案、border- accent bar、
 * 按钮 loading 状态、behindCommits 显示、错误状态。
 */
import type { Repository } from '~/types'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import RepoHashFreshnessCard from '../RepoHashFreshnessCard.vue'
// Mock API
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 get: vi.fn,
 refreshRemoteHead: vi.fn,
 },
}))
// Mock useToast / useClipboard（auto-imported composables）
vi.mock('~/composables/useToast', => ({ useToast: => ({ success: vi.fn }) }))
vi.mock('@vueuse/core', async (importOriginal) => {
 const actual = await importOriginal<typeof import('@vueuse/core')>
 return { ...actual, useClipboard: => ({ copy: vi.fn }) }
})
// Stub shadcn 组件避免 provider 依赖
const stubComponents = {
 Button: defineComponent({ template: '<button v-bind="$attrs"><slot /></button>' }),
 Badge: defineComponent({ template: '<span><slot /></span>' }),
 Tooltip: defineComponent({ template: '<div><slot /></div>' }),
 TooltipProvider: defineComponent({ template: '<div><slot /></div>' }),
 TooltipTrigger: defineComponent({ template: '<div><slot /></div>' }),
 TooltipContent: defineComponent({ template: '<div><slot /></div>' }),
}
import { repositoriesApi } from '~/api/repositories'
function makeRepo(overrides: Partial<Repository> = {}): Repository {
 return {
 id: 'repo-1',
 name: 'test-repo',
 git_url: 'https://github.com/test/repo.git',
 git_platform: 'github',
 default_branch: 'main',
 has_credential: true,
 spaces:,
 auto_index_enabled: false,
 index_status: 'indexed',
 last_indexed_at: '2024-01-01T00:00:00Z',
 created_at: '2024-01-01T00:00:00Z',
 updated_at: '2024-01-01T00:00:00Z',
 remote_head_sha: 'abc1234abc1234',
 remote_head_checked_at: '2024-01-01T10:00:00Z',
 last_indexed_commit_sha: 'abc1234abc1234',
 behind_commits: 0,
 ...overrides,
 } as Repository
}
function mountCard {
 return mount(RepoHashFreshnessCard, {
 props: { repositoryId: 'repo-1' },
 global: { stubs: stubComponents },
 })
}
describe('RepoHashFreshnessCard', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('A: FRESH 态 — 显示"索引最新"文案，check-circle 图标，不显示 alert-triangle', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'abc1234abc1234',
 last_indexed_commit_sha: 'abc1234abc1234',
 }))
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('索引最新')
 expect(text).toContain('本地与远程 HEAD 一致')
 // FRESH 态使用 check-circle-2 图标，不显示 STALE 专属的 alert-triangle
 expect(wrapper.html).toContain('icon-[lucide--check-circle-2]')
 expect(wrapper.html).not.toContain('icon-[lucide--alert-triangle]')
 })
 it('B: STALE 态 — 显示"索引已过期"，alert-triangle 图标存在（work item §11 border- 由 grep 验证）', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'def5678def5678',
 last_indexed_commit_sha: 'abc1234abc1234',
 behind_commits: null,
 }))
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('索引已过期')
 // STALE 态必须显示 alert-triangle 图标（work item §5.2）
 expect(wrapper.html).toContain('icon-[lucide--alert-triangle]')
 expect(wrapper.html).toContain('text-amber-500')
 })
 it('C: UNKNOWN 态 — remote_head_sha 为空时显示"远端状态未知"，help-circle 图标', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: '',
 remote_head_checked_at: null,
 }))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('远端状态未知')
 expect(wrapper.text).toContain('请点击「立即检查」获取最新提交')
 // UNKNOWN 态使用 help-circle 图标，不显示 STALE 专属图标
 expect(wrapper.html).toContain('icon-[lucide--help-circle]')
 expect(wrapper.html).not.toContain('icon-[lucide--alert-triangle]')
 })
 it('D: STALE + behind_commits=5 — 副文案包含"5 个 commit"', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'def5678def5678',
 last_indexed_commit_sha: 'abc1234abc1234',
 behind_commits: 5,
 }))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('5')
 expect(wrapper.text).toContain('个 commit')
 })
 it('E: STALE + behind_commits=null — 副文案为"本地与远端 HEAD 不一致"（ 降级）', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'def5678def5678',
 last_indexed_commit_sha: 'abc1234abc1234',
 behind_commits: null,
 }))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('本地与远端 HEAD 不一致')
 })
 it('F: 点击"立即检查"后按钮显示"检查中..."且禁用', async => {
 let resolveRefresh!: (v: import('~/api/repositories').RefreshRemoteHeadResponse) => void
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo)
 vi.mocked(repositoriesApi.refreshRemoteHead).mockImplementation(
 => new Promise(resolve => { resolveRefresh = resolve }),
 )
 const wrapper = mountCard
 await flushPromises
 const btn = wrapper.find('button')
 await btn.trigger('click')
 // 此时 checking=true，按钮应 disabled，文案应为"检查中..."
 await wrapper.vm.$nextTick
 expect(wrapper.text).toContain('检查中...')
 expect(btn.attributes('disabled')).toBeDefined
 // 清理
 resolveRefresh({ remote_head_sha: 'abc1234', freshness: 'fresh' })
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo)
 })
 it('G: FRESH 态 SHA 显示 — 不显示远端 SHA 对比行', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'abc1234abc1234',
 last_indexed_commit_sha: 'abc1234abc1234',
 }))
 const wrapper = mountCard
 await flushPromises
 // FRESH 态不含箭头分隔符（远端 SHA 对比区不显示）
 expect(wrapper.find('.icon-\\[lucide--arrow-right\\]').exists).toBe(false)
 })
 it('H: "尚未检查过"文案 — remote_head_checked_at 为 null 时显示', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: '',
 remote_head_checked_at: null,
 last_indexed_commit_sha: '',
 }))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('尚未检查过')
 })
})
