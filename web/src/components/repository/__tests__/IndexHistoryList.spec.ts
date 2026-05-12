/**
 * IndexHistoryList — RUNNING 行实时进度 + 可展开变更文件 SSE 集成测试
 *
 * 覆盖：
 * a) RUNNING 行渲染进度条 + stage 文案，进度数据来自 SSE
 * b) 列表存在 RUNNING 项时自动开 SSE；不再有 RUNNING 项时停 SSE
 * c) 点击"查看变更文件"展开/收起，按 added/modified/deleted 分组渲染
 * d) SSE 推 done → refetch 列表
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 getIndexHistory: vi.fn,
 triggerIndex: vi.fn,
 },
}))
vi.mock('~/composables/useIndexProgressStream', => ({
 connectIndexProgressStream: vi.fn,
}))
import { repositoriesApi } from '~/api/repositories'
import { connectIndexProgressStream } from '~/composables/useIndexProgressStream'
import IndexHistoryList from '../IndexHistoryList.vue'
const stubComponents = {
 StatusBadge: defineComponent({ template: '<span class="status-badge-stub"><slot /></span>' }),
 Badge: defineComponent({ template: '<span class="badge-stub"><slot /></span>' }),
 Button: defineComponent({
 props: ['variant', 'size', 'disabled'],
 emits: ['click'],
 template: '<button:disabled="disabled" @click="$emit(\'click\')"><slot /></button>',
 }),
 Tooltip: defineComponent({ template: '<span><slot /></span>' }),
 TooltipTrigger: defineComponent({ template: '<span><slot /></span>' }),
 TooltipContent: defineComponent({ template: '<span><slot /></span>' }),
 TooltipProvider: defineComponent({ template: '<span><slot /></span>' }),
}
function mkRunningItem(overrides: Record<string, unknown> = {}) {
 return {
 id: 'history-running-1',
 trigger_type: 'manual' as const,
 status: 'running' as const,
 from_sha: 'abc1234',
 to_sha: 'def5678',
 files_added: 3,
 files_modified: 2,
 files_deleted: 1,
 summary_text: '本次增量：新增 3 文件、修改 2 文件、删除 1 文件',
 error_message: null,
 started_at: '2026-05-12T07:00:00Z',
 finished_at: null,
 created_at: '2026-05-12T07:00:00Z',
 changed_files: {
 added: ['src/a.py', 'src/b.py', 'src/c.py'],
 modified: ['src/m1.py', 'src/m2.py'],
 deleted: ['src/d1.py'],
 },
 ...overrides,
 }
}
function mountList {
 return mount(IndexHistoryList, {
 props: {
 repositoryId: 'repo-1',
 gitUrl: 'https://github.com/test/repo.git',
 },
 global: { stubs: stubComponents },
 })
}
describe('indexHistoryList — RUNNING 行 + SSE 流', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('a: 列表含 RUNNING 项时自动 connectIndexProgressStream', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [mkRunningItem],
 total: 1,
 })
 vi.mocked(connectIndexProgressStream).mockReturnValue(new AbortController)
 mountList
 await flushPromises
 expect(connectIndexProgressStream).toHaveBeenCalledTimes(1)
 expect(vi.mocked(connectIndexProgressStream).mock.calls[0][0]).toBe('repo-1')
 })
 it('b: SSE 推 progress → RUNNING 行渲染进度条 + stage 文案', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [mkRunningItem],
 total: 1,
 })
 let captured: ((e: any) => void) | null = null
 vi.mocked(connectIndexProgressStream).mockImplementation((_id, opts) => {
 captured = opts.onEvent
 return new AbortController
 })
 const wrapper = mountList
 await flushPromises
 expect(captured).not.toBeNull
 captured!({
 type: 'progress',
 ts: '2026-05-12T07:01:00Z',
 repository: {
 index_status: 'indexing',
 last_indexed_at: null,
 index_error: null,
 index_total_chunks: 100,
 index_processed_chunks: 42,
 index_write_total: 100,
 index_write_processed: 10,
 overall_progress: 35,
 overall_stage: '生成向量中...',
 },
 running_history: mkRunningItem,
 })
 await flushPromises
 const html = wrapper.html
 expect(wrapper.text).toContain('生成向量中...')
 expect(wrapper.text).toContain('35%')
 // 进度条 width style 反映 35%
 expect(html).toContain('width: 35%')
 })
 it('c: 点击"查看变更文件" → 按 added/modified/deleted 分组展开渲染', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [mkRunningItem],
 total: 1,
 })
 vi.mocked(connectIndexProgressStream).mockReturnValue(new AbortController)
 const wrapper = mountList
 await flushPromises
 // 默认未展开
 expect(wrapper.text).not.toContain('+ src/a.py')
 // 找到"查看变更文件"按钮点击
 const buttons = wrapper.findAll('button')
 const expandBtn = buttons.find(b => b.text.includes('查看变更文件'))
 expect(expandBtn).toBeTruthy
 await expandBtn!.trigger('click')
 // 展开后渲染三组路径
 const text = wrapper.text
 expect(text).toContain('新增 3 个文件')
 expect(text).toContain('src/a.py')
 expect(text).toContain('修改 2 个文件')
 expect(text).toContain('src/m1.py')
 expect(text).toContain('删除 1 个文件')
 expect(text).toContain('src/d1.py')
 })
 it('d: SSE 推 done → 调用 getIndexHistory 重新拉取列表', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [mkRunningItem],
 total: 1,
 })
 let captured: ((e: any) => void) | null = null
 vi.mocked(connectIndexProgressStream).mockImplementation((_id, opts) => {
 captured = opts.onEvent
 return new AbortController
 })
 mountList
 await flushPromises
 // 初始挂载已经调用过 1 次 getIndexHistory，先记录基线
 const baseline = vi.mocked(repositoriesApi.getIndexHistory).mock.calls.length
 captured!({ type: 'done', reason: 'idle' })
 await flushPromises
 expect(
 vi.mocked(repositoriesApi.getIndexHistory).mock.calls.length,
 ).toBeGreaterThan(baseline)
 })
 it('e: 列表中没有 RUNNING 项时不应建立 SSE 连接', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [
 {
 ...mkRunningItem({ id: 'h-completed', status: 'completed' as const }),
 },
 ],
 total: 1,
 })
 vi.mocked(connectIndexProgressStream).mockReturnValue(new AbortController)
 mountList
 await flushPromises
 expect(connectIndexProgressStream).not.toHaveBeenCalled
 })
 it('f: failed 行点击「重试」按钮 → 调用 triggerIndex 并刷新列表', async => {
 const failedItem = mkRunningItem({
 id: 'h-failed',
 status: 'failed' as const,
 error_message: 'embedding 服务 502',
 finished_at: '2026-05-12T07:30:00Z',
 })
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [failedItem],
 total: 1,
 })
 vi.mocked(repositoriesApi.triggerIndex).mockResolvedValue({
 message: 'ok',
 repository_id: 'repo-1',
 status: 'indexing' as any,
 })
 vi.mocked(connectIndexProgressStream).mockReturnValue(new AbortController)
 const wrapper = mountList
 await flushPromises
 // baseline = 挂载时的 1 次 getIndexHistory 调用
 const baseline = vi.mocked(repositoriesApi.getIndexHistory).mock.calls.length
 const buttons = wrapper.findAll('button')
 const retryBtn = buttons.find(b => b.text.includes('重试'))
 expect(retryBtn, '应当渲染"重试"按钮').toBeTruthy
 await retryBtn!.trigger('click')
 await flushPromises
 expect(vi.mocked(repositoriesApi.triggerIndex)).toHaveBeenCalledWith('repo-1')
 // 重试成功后应再 fetch 一次列表（baseline + 1）
 expect(
 vi.mocked(repositoriesApi.getIndexHistory).mock.calls.length,
 ).toBeGreaterThan(baseline)
 })
 it('h: 早期阶段（克隆/对比/解析中）→ 隐藏百分比，进度条用 indeterminate 动画', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [mkRunningItem],
 total: 1,
 })
 let captured: ((e: any) => void) | null = null
 vi.mocked(connectIndexProgressStream).mockImplementation((_id, opts) => {
 captured = opts.onEvent
 return new AbortController
 })
 const wrapper = mountList
 await flushPromises
 captured!({
 type: 'progress',
 ts: '2026-05-12T07:01:00Z',
 repository: {
 index_status: 'indexing',
 last_indexed_at: null,
 index_error: null,
 index_total_chunks: 0,
 index_processed_chunks: 0,
 index_write_total: 0,
 index_write_processed: 0,
 overall_progress: 0,
 overall_stage: '克隆仓库中...',
 },
 running_history: mkRunningItem,
 })
 await flushPromises
 const html = wrapper.html
 expect(wrapper.text).toContain('克隆仓库中...')
 // 百分比应被隐藏（避免长时间停留 0%）
 expect(wrapper.text).not.toContain('0%')
 // indeterminate 动画样式应已应用
 expect(html).toContain('index-indeterminate')
 })
 it('g: 没有 RUNNING / FAILED 时按钮不存在', async => {
 vi.mocked(repositoriesApi.getIndexHistory).mockResolvedValue({
 items: [mkRunningItem({ id: 'h-ok', status: 'completed' as const, error_message: null })],
 total: 1,
 })
 const wrapper = mountList
 await flushPromises
 expect(wrapper.text).not.toContain('重试')
 })
})
