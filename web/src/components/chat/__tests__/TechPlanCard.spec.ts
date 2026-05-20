/**
 * Phase：TechPlanCard.vue 单元测试。
 *
 * 覆盖：Markdown 渲染、affected_files file_path/path 兼容、折叠默认策略、
 * draft 「开始编码」按钮 emit、非 draft 状态 fallback 文案。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import TechPlanCard from '~/components/chat/TechPlanCard.vue'
// -- mock markdown-it 单例：直接返回 echo HTML（避免引入 shiki 的重依赖）---
vi.mock('~/composables/useMarkdownRenderer', => ({
 getMarkdownRenderer: vi.fn(async => ({
 render: (raw: string) => `<div data-test="md">${raw}</div>`,
 })),
}))
// -- stub shadcn-vue 组件，避免 Slot 渲染机制干扰断言 ---
const StubBadge = defineComponent({
 name: 'Badge',
 setup(_, { slots }) {
 return => h('span', { 'data-test': 'badge' }, slots.default?.)
 },
})
const StubButton = defineComponent({
 name: 'Button',
 props: ['disabled'],
 emits: ['click'],
 setup(props, { slots, emit }) {
 return => h('button', {
 'data-test': 'btn',
 'disabled': props.disabled || false,
 'onClick': => emit('click'),
 }, slots.default?.)
 },
})
const StubInput = defineComponent({
 name: 'Input',
 props: ['modelValue'],
 emits: ['update:modelValue'],
 setup(props, { emit }) {
 return => h('input', {
 value: props.modelValue,
 onInput: (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value),
 })
 },
})
const PassthroughSelect = defineComponent({
 name: 'Select',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'select' }, slots.default?.)
 },
})
const StubSelectItem = defineComponent({
 name: 'SelectItem',
 setup(_, { slots }) {
 return => h('div', { 'data-test': 'select-item' }, slots.default?.)
 },
})
const globalStubs = {
 Badge: StubBadge,
 Button: StubButton,
 Input: StubInput,
 Select: PassthroughSelect,
 SelectTrigger: PassthroughSelect,
 SelectContent: PassthroughSelect,
 SelectItem: StubSelectItem,
 SelectValue: PassthroughSelect,
}
function mountCard(props: Partial<InstanceType<typeof TechPlanCard>['$props']> = {}) {
 return mount(TechPlanCard, {
 props: {
 planId: 'plan-uuid',
 sessionId: 'session-uuid',
 techPlan: '# 标题\n方案内容',
 affectedFiles:,
 status: 'draft' as const,
 isConfirming: false,
 ...props,
 },
 global: {
 stubs: globalStubs,
 },
 })
}
beforeEach( => {
 vi.clearAllMocks
})
describe('techPlanCard', => {
 it('renders markdown of tech plan', async => {
 const wrapper = mountCard({ techPlan: '# 标题' })
 await flushPromises
 await nextTick
 expect(wrapper.html).toContain('<div data-test="md"># 标题</div>')
 })
 it('renders affected_files using file_path key', async => {
 const wrapper = mountCard({
 affectedFiles: [{ file_path: 'a.py', change_type: 'modify' }],
 })
 await flushPromises
 expect(wrapper.text).toContain('a.py')
 expect(wrapper.text).toContain('影响文件')
 })
 it('falls back to legacy path key when file_path missing', async => {
 const wrapper = mountCard({
 affectedFiles: [{ path: 'legacy.py', change_type: 'add' }],
 })
 await flushPromises
 expect(wrapper.text).toContain('legacy.py')
 })
 it('hides affected files section when empty', async => {
 const wrapper = mountCard({ affectedFiles: })
 await flushPromises
 expect(wrapper.text).not.toContain('影响文件')
 })
 it('shows 开始编码 button only when status==draft', async => {
 const draft = mountCard({ status: 'draft' })
 await flushPromises
 expect(draft.text).toContain('开始编码')
 const confirmed = mountCard({ status: 'confirmed', defaultCollapsed: false })
 await flushPromises
 expect(confirmed.text).not.toContain('开始编码')
 })
 it('emits confirm with planId / sessionId / branchName when draft button clicked', async => {
 const wrapper = mountCard({
 status: 'draft',
 planId: 'plan-uuid',
 sessionId: 'session-uuid',
 branchName: 'feat20260520.demo',
 })
 await flushPromises
 // 触发 stub 的 Button click
 const btn = wrapper.find('[data-test="btn"]')
 await btn.trigger('click')
 const emitted = wrapper.emitted('confirm')
 expect(emitted).toBeTruthy
 expect(emitted![0][0]).toBe('plan-uuid')
 expect(emitted![0][1]).toBe('session-uuid')
 // branchName 来自 previewBranchName（基于解析的 branch parts）
 expect(typeof emitted![0][2]).toBe('string')
 expect(emitted![0][2]).toMatch(/^feat\d{8}\./)
 })
 it('defaults to collapsed when status is not draft', async => {
 const wrapper = mountCard({ status: 'running' })
 await flushPromises
 // 折叠态：渲染摘要而非完整 markdown
 expect(wrapper.html).not.toContain('<div data-test="md">')
 expect(wrapper.text).toContain('# 标题')
 // 点击 header 后展开
 await wrapper.find('button').trigger('click')
 await flushPromises
 expect(wrapper.html).toContain('<div data-test="md">')
 })
 it('defaults to expanded when status is draft', async => {
 const wrapper = mountCard({ status: 'draft' })
 await flushPromises
 expect(wrapper.html).toContain('<div data-test="md">')
 })
 it('shows fallback hint for completed status', async => {
 const wrapper = mountCard({
 status: 'completed',
 defaultCollapsed: false,
 })
 await flushPromises
 expect(wrapper.text).toContain('编码完成')
 })
 // ---------------------------------------------------------------------------
 // Phase /：completed/failed 专属 UI + skeleton
 // ---------------------------------------------------------------------------
 it('shows green ring and PR link when status===completed and prUrl present', async => {
 const prUrl = 'https://gitlab.example.com/x/y/-/merge_requests/123'
 const wrapper = mountCard({
 status: 'completed',
 defaultCollapsed: false,
 prUrl,
 })
 await flushPromises
 expect(wrapper.html).toContain('ring-emerald-500/30')
 const link = wrapper.find('a[href]')
 expect(link.exists).toBe(true)
 expect(link.attributes('href')).toBe(prUrl)
 expect(wrapper.text).toContain('查看 PR')
 })
 it('shows placeholder when completed but prUrl empty', async => {
 const wrapper = mountCard({
 status: 'completed',
 defaultCollapsed: false,
 })
 await flushPromises
 expect(wrapper.text).toContain('PR 链接将由 multi-confirm 流程回填')
 })
 it('shows red ring and error message when status===failed', async => {
 const wrapper = mountCard({
 status: 'failed',
 defaultCollapsed: false,
 errorMessage: 'dispatch failed',
 })
 await flushPromises
 expect(wrapper.html).toContain('ring-destructive/30')
 expect(wrapper.text).toContain('dispatch failed')
 expect(wrapper.text).toContain('重试')
 })
 it('emits retry event with planId and sessionId when 重试 clicked', async => {
 const wrapper = mountCard({
 status: 'failed',
 defaultCollapsed: false,
 planId: 'plan-uuid',
 sessionId: 'session-uuid',
 errorMessage: 'oops',
 })
 await flushPromises
 // failed 状态下的「重试」按钮是 stub Button 渲染的 `data-test="btn"`
 const buttons = wrapper.findAll('[data-test="btn"]')
 // failed 路径下整张卡只有 1 个 Button（重试），不会有 开始编码
 expect(buttons.length).toBe(1)
 await buttons[0].trigger('click')
 const emitted = wrapper.emitted('retry')
 expect(emitted).toBeTruthy
 expect(emitted![0][0]).toBe('plan-uuid')
 expect(emitted![0][1]).toBe('session-uuid')
 })
 it('shows skeleton placeholder before markdown is ready', async => {
 // 让 markdown renderer 永远 pending，模拟未 ready 状态
 const { getMarkdownRenderer } = await import('~/composables/useMarkdownRenderer')
 vi.mocked(getMarkdownRenderer).mockReturnValueOnce(new Promise( => {}))
 const wrapper = mountCard({ status: 'draft' })
 // 不 flushPromises（让 onMounted 的 await 持续 pending）
 await nextTick
 const skeleton = wrapper.find('[data-test="md-skeleton"]')
 expect(skeleton.exists).toBe(true)
 expect(skeleton.findAll('.animate-pulse > div').length).toBe(3)
 })
 it('failed status without errorMessage shows default fallback', async => {
 const wrapper = mountCard({
 status: 'failed',
 defaultCollapsed: false,
 })
 await flushPromises
 expect(wrapper.text).toContain('编码失败，未提供错误信息')
 })
})
