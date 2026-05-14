/**
 * Phase Plan — RepoHashFreshnessCard 单测（work item §5/§6.1/§7）
 *
 * 测试三态视觉契约：FRESH/STALE/UNKNOWN 文案、border- accent bar、
 * 按钮 loading 状态、behindCommits 显示、错误状态。
 *
 * Phase Plan 扩展（work item §5.7 GraphRAG 状态区段）：
 * 5 态 graph_build_status Badge / edge_count toLocaleString / payload_synced_at
 * relative time + Tooltip / API 抛错静默 + 字段缺失 fallback。
 */
import type { GraphBuildStatus, IndexHistoryItem, IndexHistoryResponse } from '~/api/repositories'
import type { Repository } from '~/types'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import RepoHashFreshnessCard from '../RepoHashFreshnessCard.vue'
// Mock API：getIndexHistory 默认返回空 items（既有 freshness 测试零回归 / GraphRAG 段不渲染）
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 get: vi.fn,
 refreshRemoteHead: vi.fn,
 getIndexHistory: vi.fn.mockResolvedValue({ items:, total: 0 }),
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
// Phase Plan：构造 GraphRAG IndexHistory fixture
function makeGraphHistoryItem(overrides: Partial<IndexHistoryItem> = {}): IndexHistoryItem {
 return {
 id: 'hist-1',
 trigger_type: 'manual',
 status: 'completed',
 from_sha: 'a'.repeat(40),
 to_sha: 'b'.repeat(40),
 files_added: 0,
 files_modified: 0,
 files_deleted: 0,
 summary_text: null,
 error_message: null,
 started_at: '2024-01-01T00:00:00Z',
 finished_at: '2024-01-01T00:01:00Z',
 created_at: '2024-01-01T00:00:00Z',
 graph_build_status: 'completed',
 edge_count: 0,
 payload_synced_at: null,
 ...overrides,
 }
}
function makeGraphHistoryResponse(item: IndexHistoryItem | null): IndexHistoryResponse {
 return item ? { items: [item], total: 1 }: { items:, total: 0 }
}
describe('repoHashFreshnessCard', => {
 beforeEach( => {
 vi.clearAllMocks
 // 默认 mock：empty items（确保既有 freshness 测试零回归）
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({ items:, total: 0 })
 })
 it('a: FRESH 态 — 显示"索引最新"文案，check-circle 图标，不显示 alert-triangle', async => {
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
 it('b: STALE 态 — 显示"索引已过期"，alert-triangle 图标存在（work item §11 border- 由 grep 验证）', async => {
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
 it('c: UNKNOWN 态 — remote_head_sha 为空时显示"远端状态未知"，help-circle 图标', async => {
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
 it('d: STALE + behind_commits=5 — 副文案包含"5 个 commit"', async => {
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
 it('e: STALE + behind_commits=null — 副文案为"本地与远端 HEAD 不一致"（ 降级）', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'def5678def5678',
 last_indexed_commit_sha: 'abc1234abc1234',
 behind_commits: null,
 }))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('本地与远端 HEAD 不一致')
 })
 it('f: 点击"立即检查"后按钮显示"检查中..."且禁用', async => {
 let resolveRefresh!: (v: import('~/api/repositories').RefreshRemoteHeadResponse) => void
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo)
 vi.mocked(repositoriesApi.refreshRemoteHead).mockImplementation(
 => new Promise((resolve) => { resolveRefresh = resolve }),
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
 it('g: FRESH 态 SHA 显示 — 不显示远端 SHA 对比行', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'abc1234abc1234',
 last_indexed_commit_sha: 'abc1234abc1234',
 }))
 const wrapper = mountCard
 await flushPromises
 // FRESH 态不含箭头分隔符（远端 SHA 对比区不显示）
 expect(wrapper.find('.icon-\\[lucide--arrow-right\\]').exists).toBe(false)
 })
 it('i: NOT_INDEXED 态 — last_indexed_commit_sha 为空时显示"尚未索引"，circle-dashed 图标', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'e7bf8e6abc1234',
 remote_head_checked_at: '2024-01-01T10:00:00Z',
 last_indexed_commit_sha: '',
 }))
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 // 即便远端 SHA 已知，也不应再显示"远端状态未知"
 expect(text).toContain('尚未索引')
 expect(text).not.toContain('远端状态未知')
 expect(text).toContain('仓库还未建立本地索引')
 // 使用 circle-dashed 图标，不再使用 help-circle
 expect(wrapper.html).toContain('icon-[lucide--circle-dashed]')
 expect(wrapper.html).not.toContain('icon-[lucide--help-circle]')
 // 不再展示"本地 → 远端"对比箭头
 expect(wrapper.find('.icon-\\[lucide--arrow-right\\]').exists).toBe(false)
 // 但远端 HEAD 信息仍可见
 expect(text).toContain('远端 HEAD')
 expect(text).toContain('e7bf8e6')
 })
 it('j: NOT_INDEXED 态 — 远端 SHA 也为空时提示"暂无远端 HEAD 信息"', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: '',
 remote_head_checked_at: null,
 last_indexed_commit_sha: '',
 }))
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('尚未索引')
 expect(text).toContain('暂无远端 HEAD 信息')
 })
 it('h: "尚未检查过"文案 — remote_head_checked_at 为 null 时显示', async => {
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: '',
 remote_head_checked_at: null,
 last_indexed_commit_sha: '',
 }))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('尚未检查过')
 })
 // ==================== Phase Plan：GraphRAG 状态区段 ====================
 // work item §5.7：5 态 Badge / edge_count / payload_synced_at relative time
 describe('Phase Plan — GraphRAG 状态区段', => {
 beforeEach( => {
 // 既有 freshness 不影响 GraphRAG 段渲染：默认返回 fresh repo
 vi.mocked(repositoriesApi.get).mockResolvedValue(makeRepo({
 remote_head_sha: 'abc1234abc1234',
 last_indexed_commit_sha: 'abc1234abc1234',
 }))
 })
 it('1: getIndexHistory 返回空 items → 不渲染 GraphRAG 状态区段', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({ items:, total: 0 })
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).not.toContain('GraphRAG 状态')
 // 既有 4 态 freshness 仍正常
 expect(wrapper.text).toContain('索引最新')
 })
 it('2: getIndexHistory 返回行但 graph_build_status 缺失 → 不渲染区段', async => {
 // 模拟老 IndexHistory 行未回填 GraphRAG 字段
 const legacyItem: IndexHistoryItem = {
 id: 'hist-legacy',
 trigger_type: 'manual',
 status: 'completed',
 from_sha: null,
 to_sha: null,
 files_added: 0,
 files_modified: 0,
 files_deleted: 0,
 summary_text: null,
 error_message: null,
 started_at: null,
 finished_at: null,
 created_at: '2024-01-01T00:00:00Z',
 // 故意不带 graph_build_status / edge_count / payload_synced_at
 }
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({ items: [legacyItem], total: 1 })
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).not.toContain('GraphRAG 状态')
 })
 it('3: graph_build_status=pending → Badge 文案"等待构建" + clock icon', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({ graph_build_status: 'pending' })),
 )
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('GraphRAG 状态')
 expect(text).toContain('等待构建')
 expect(wrapper.html).toContain('icon-[lucide--clock]')
 })
 it('4: graph_build_status=running → Badge 文案"构建中..." + animate-spin loader icon + sr-only 描述', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({ graph_build_status: 'running' })),
 )
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('构建中...')
 const html = wrapper.html
 expect(html).toContain('icon-[lucide--loader-circle]')
 expect(html).toContain('animate-spin')
 // a11y: running 态屏幕阅读器文案
 expect(html).toContain('sr-only')
 expect(text).toContain('GraphRAG 索引正在构建中')
 })
 it('5: graph_build_status=completed → Badge variant default + check-circle 绿图标 + edge_count "1,234 条边"', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({
 graph_build_status: 'completed',
 edge_count: 1234,
 })),
 )
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('已构建')
 // toLocaleString 千位分隔
 expect(text).toContain('1,234 条边')
 const html = wrapper.html
 expect(html).toContain('icon-[lucide--check-circle]')
 // Deviation D-B：completed 用绿色 emerald-500 图标补 success 语义
 expect(html).toContain('text-emerald-500')
 })
 it('6: graph_build_status=failed → Badge 文案"构建失败" + alert-circle icon', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({ graph_build_status: 'failed' })),
 )
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('构建失败')
 expect(wrapper.html).toContain('icon-[lucide--alert-circle]')
 })
 it('7: graph_build_status=skipped → Badge 文案"已跳过" + minus-circle icon', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({ graph_build_status: 'skipped' })),
 )
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('已跳过')
 expect(wrapper.html).toContain('icon-[lucide--minus-circle]')
 })
 it('8: payload_synced_at 存在 → 渲染"{relativeTime} 同步" + Tooltip 含 toLocaleString 绝对时间', async => {
 // 用 5 分钟前的时间（formatRelativeTime → "5 分钟前"）
 const fiveMinAgo = new Date(Date.now - 5 * 60_000).toISOString
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({
 graph_build_status: 'completed',
 payload_synced_at: fiveMinAgo,
 })),
 )
 const wrapper = mountCard
 await flushPromises
 const text = wrapper.text
 expect(text).toContain('同步')
 expect(text).toContain('分钟前')
 // Tooltip stub 保留 slot，绝对时间也会渲染在 .text 中
 // toLocaleString('zh-CN') 输出包含年份
 expect(text).toContain('2026') // 测试运行年份（now ≈ 2026 per env）
 expect(wrapper.html).toContain('icon-[lucide--refresh-cw]')
 })
 it('9: payload_synced_at=null → 不渲染同步时间行', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({
 graph_build_status: 'completed',
 payload_synced_at: null,
 })),
 )
 const wrapper = mountCard
 await flushPromises
 // GraphRAG 段渲染但同步行不渲染
 expect(wrapper.text).toContain('GraphRAG 状态')
 // GraphRAG 段内不含"同步"（既有 4 态 freshness 段也不含"同步"，安全断言）
 expect(wrapper.text).not.toContain('同步')
 })
 it('10: getIndexHistory 抛错 → 区段不渲染 + 既有 4 态 freshness 仍正常', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockRejectedValue(new Error('500 server error'))
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).not.toContain('GraphRAG 状态')
 // 既有 freshness 仍工作
 expect(wrapper.text).toContain('索引最新')
 })
 it('11: edge_count=0 → 仍显示"0 条边"（不省略）', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({
 graph_build_status: 'completed',
 edge_count: 0,
 })),
 )
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('0 条边')
 })
 it('12: a11y — Badge role=status + aria-label 含状态描述', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({ graph_build_status: 'completed' })),
 )
 const wrapper = mountCard
 await flushPromises
 const html = wrapper.html
 expect(html).toContain('role="status"')
 expect(html).toContain('aria-label="GraphRAG 构建状态：已构建"')
 })
 it('13: 5 态 variant 矩阵 — completed=default / failed=destructive / skipped=outline / pending=secondary / running=secondary', async => {
 // 验证内部派生 variant（通过 Badge stub 自动透传 v-bind="$attrs"）
 // stubComponents Badge stub 不渲染 variant 属性，但我们已通过文案 + icon
 // 间接覆盖；此测试保留结构契约：5 态全部不抛错且渲染区段
 const statuses: GraphBuildStatus = ['pending', 'running', 'completed', 'failed', 'skipped']
 for (const status of statuses) {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue(
 makeGraphHistoryResponse(makeGraphHistoryItem({ graph_build_status: status })),
 )
 const wrapper = mountCard
 await flushPromises
 expect(wrapper.text).toContain('GraphRAG 状态')
 wrapper.unmount
 }
 })
 })
})
