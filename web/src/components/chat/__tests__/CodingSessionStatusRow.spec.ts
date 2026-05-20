/**
 * Phase：CodingSessionStatusRow.vue 单元测试。
 *
 * 覆盖 6 类断言：
 * - running：分支链 / 不显示 PR / 不显示重试
 * - completed：PR 链 / commit sha 前 8 位 / 不显示重试
 * - failed：error_message / 重试按钮
 * - 重试按钮触发 retry emit
 * - 复制 commit sha 调 navigator.clipboard.writeText
 * - branch_name 为空时不渲染分支链
 */
import type { CodingPlanSessionRuntime } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import CodingSessionStatusRow from '../CodingSessionStatusRow.vue'
vi.mock('~/composables/useToast', => ({
 useToast: => ({ success: vi.fn, error: vi.fn }),
}))
const StubBadge = defineComponent({
 name: 'Badge',
 setup(_, { slots }) {
 return => h('span', { 'data-test': 'badge' }, slots.default?.)
 },
})
const StubStatusBadge = defineComponent({
 name: 'StatusBadge',
 props: ['type', 'status'],
 setup(props) {
 return => h('span', { 'data-test': 'status-badge', 'data-status': props.status }, props.status)
 },
})
const StubButton = defineComponent({
 name: 'Button',
 props: ['variant', 'size', 'disabled', 'ariaLabel'],
 emits: ['click'],
 setup(props, { slots, emit, attrs }) {
 return => h('button', {
 'data-test': 'btn',
 'disabled': props.disabled || false,
 'aria-label': (attrs as any)['aria-label'] ?? props.ariaLabel,
 'onClick': => emit('click'),
 }, slots.default?.)
 },
})
function makeSession(overrides: Partial<CodingPlanSessionRuntime> = {}): CodingPlanSessionRuntime {
 return {
 session_id: 's1',
 repository_id: 'r1',
 repository_name: 'repo-1',
 branch_name: 'feat/foo',
 status: 'running',
 pr_url: '',
 commit_sha: '',
 error_message: '',
 ...overrides,
 }
}
const GIT_URL = 'https://gitlab.com/ns/repo-1.git'
function mountRow(session: CodingPlanSessionRuntime) {
 return mount(CodingSessionStatusRow, {
 props: { session, repoGitUrl: GIT_URL },
 global: {
 stubs: {
 Badge: StubBadge,
 Button: StubButton,
 StatusBadge: StubStatusBadge,
 },
 },
 })
}
describe('codingSessionStatusRow', => {
 beforeEach( => {
 Object.defineProperty(navigator, 'clipboard', {
 value: { writeText: vi.fn.mockResolvedValue(undefined) },
 configurable: true,
 })
 })
 it('renders branch link for running session and no PR/retry', => {
 const wrapper = mountRow(makeSession)
 expect(wrapper.html).toContain('feat/foo')
 expect(wrapper.html).toContain('/-/tree/')
 expect(wrapper.text).not.toContain('查看 PR')
 expect(wrapper.text).not.toContain('重试')
 })
 it('renders PR link and commit sha for completed session', => {
 const wrapper = mountRow(makeSession({
 status: 'completed',
 pr_url: 'https://gitlab.com/ns/repo-1/-/merge_requests/1',
 commit_sha: 'abc123def4567890',
 }))
 expect(wrapper.text).toContain('查看 PR')
 expect(wrapper.text).toContain('abc123de')
 expect(wrapper.text).not.toContain('重试')
 })
 it('renders error_message and retry button for failed session', => {
 const wrapper = mountRow(makeSession({
 status: 'failed',
 error_message: 'Runner 离线',
 }))
 expect(wrapper.text).toContain('Runner 离线')
 expect(wrapper.text).toContain('重试')
 })
 it('emits retry event when retry button clicked', async => {
 const wrapper = mountRow(makeSession({
 status: 'failed',
 error_message: 'x',
 }))
 const buttons = wrapper.findAll('button')
 const btn = buttons.find(b => b.text.includes('重试'))
 expect(btn).toBeTruthy
 await btn!.trigger('click')
 expect(wrapper.emitted('retry')).toBeTruthy
 expect(wrapper.emitted('retry')![0][0]).toBe('s1')
 })
 it('copies commit sha to clipboard when copy button clicked', async => {
 const wrapper = mountRow(makeSession({
 status: 'completed',
 commit_sha: 'abc123def4567890',
 }))
 const buttons = wrapper.findAll('button')
 const copyBtn = buttons.find(b =>
 b.attributes('aria-label')?.startsWith('复制 commit sha'),
 )
 expect(copyBtn).toBeTruthy
 await copyBtn!.trigger('click')
 expect(navigator.clipboard.writeText).toHaveBeenCalledWith('abc123def4567890')
 })
 it('does not render branch link when branch_name is empty', => {
 const wrapper = mountRow(makeSession({ branch_name: '' }))
 expect(wrapper.html).not.toContain('/-/tree/')
 })
})
