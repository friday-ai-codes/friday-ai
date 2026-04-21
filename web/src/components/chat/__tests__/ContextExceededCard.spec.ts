/**
 * Phase Plan Task 02 — ContextExceededCard 组件测试。
 *
 * 覆盖 /：SSE ERROR context_window_exceeded payload → 结构化卡片 + 3 按钮。
 *
 * Test matrix:
 * A: props 渲染 estimated / max / exceeded_by 数值（font-mono / toLocaleString）
 * B: 3 按钮按 recommended_actions 顺序渲染（风险倒序：精简 prompt / 换大模型 / 清理历史）
 * C: 按钮 1 "精简 system prompt" 点击 → RouterLink push '/prompts/'
 * D: 按钮 2 "换大 context 模型" 点击 → emit('switch-model-click')
 * E: 按钮 3 "清理对话历史" 点击 → emit('cleanup-click')
 * F: 清理历史按钮 variant=destructive（高风险视觉警示）
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
// Mock vue-router's useRouter composable (setup 阶段就被调用，必须 hoist)
const pushSpy = vi.fn
vi.mock('vue-router', => ({
 useRouter: => ({ push: pushSpy }),
 RouterLink: {
 name: 'RouterLink',
 props: ['to'],
 template: '<a:data-to="to"><slot /></a>',
 },
}))
import ContextExceededCard from '~/components/chat/ContextExceededCard.vue'
/** RouterLink stub：透传 to 属性供断言；capture 点击。 */
const RouterLinkStub = {
 name: 'RouterLink',
 props: ['to'],
 template: '<a:data-to="to"><slot /></a>',
}
const defaultActions = [
 { id: 'trim_prompt', label: '精简 system prompt', action_type: 'navigate', target: '/prompts/' },
 { id: 'switch_model', label: '换大 context 模型', action_type: 'navigate', target: 'settings.model' },
 { id: 'cleanup_history', label: '清理对话历史', action_type: 'dialog', target: 'CleanupDialog' },
]
function makeProps(overrides: Record<string, unknown> = {}) {
 return {
 estimatedTokens: 200000,
 maxTokens: 150000,
 exceededBy: 50000,
 model: 'claude-3-5-sonnet-20241022',
 recommendedActions: defaultActions,
 ...overrides,
 }
}
describe('contextExceededCard', => {
 beforeEach( => {
 pushSpy.mockReset
 })
 it('A: 渲染 estimated / max / exceeded_by / model', => {
 const wrapper = mount(ContextExceededCard, {
 props: makeProps,
 global: {
 stubs: {
 RouterLink: RouterLinkStub,
 // Vue Router 全局不挂，push 用事件 assertion 替代（见 C）
 },
 },
 })
 const text = wrapper.text
 expect(text).toContain('上下文已超出模型上限')
 // toLocaleString('en-US') → "200,000" / "150,000" / "50,000"
 expect(text).toContain('200,000')
 expect(text).toContain('150,000')
 expect(text).toContain('50,000')
 expect(text).toContain('claude-3-5-sonnet-20241022')
 })
 it('B: 3 按钮按 recommended_actions 顺序渲染', => {
 const wrapper = mount(ContextExceededCard, {
 props: makeProps,
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 const buttons = wrapper.findAll('button')
 // 至少 3 个按钮（可能有 shadcn button 隐藏元素，采文本匹配更稳）
 const labels = buttons.map(b => b.text.trim).filter(Boolean)
 expect(labels).toContain('精简 system prompt')
 expect(labels).toContain('换大 context 模型')
 expect(labels).toContain('清理对话历史')
 // 顺序：trim_prompt → switch_model → cleanup_history
 const idxTrim = labels.findIndex(l => l.includes('精简 system prompt'))
 const idxSwitch = labels.findIndex(l => l.includes('换大 context 模型'))
 const idxCleanup = labels.findIndex(l => l.includes('清理对话历史'))
 expect(idxTrim).toBeLessThan(idxSwitch)
 expect(idxSwitch).toBeLessThan(idxCleanup)
 })
 it('C: 点击 "精简 system prompt" → router.push("/prompts/")', async => {
 const wrapper = mount(ContextExceededCard, {
 props: makeProps,
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 // 定位 trim_prompt 按钮并点击
 const button = wrapper.findAll('button').find(b => b.text.includes('精简 system prompt'))
 expect(button).toBeTruthy
 await button!.trigger('click')
 expect(pushSpy).toHaveBeenCalledWith('/prompts/')
 })
 it('D: 点击 "换大 context 模型" → emit("switch-model-click")', async => {
 const wrapper = mount(ContextExceededCard, {
 props: makeProps,
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 const button = wrapper.findAll('button').find(b => b.text.includes('换大 context 模型'))
 expect(button).toBeTruthy
 await button!.trigger('click')
 expect(wrapper.emitted('switch-model-click')).toBeTruthy
 expect(wrapper.emitted('switch-model-click')!.length).toBe(1)
 })
 it('E: 点击 "清理对话历史" → emit("cleanup-click")', async => {
 const wrapper = mount(ContextExceededCard, {
 props: makeProps,
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 const button = wrapper.findAll('button').find(b => b.text.includes('清理对话历史'))
 expect(button).toBeTruthy
 await button!.trigger('click')
 expect(wrapper.emitted('cleanup-click')).toBeTruthy
 expect(wrapper.emitted('cleanup-click')!.length).toBe(1)
 })
 it('F: 清理历史按钮 variant=destructive（视觉高风险警示）', => {
 const wrapper = mount(ContextExceededCard, {
 props: makeProps,
 global: { stubs: { RouterLink: RouterLinkStub } },
 })
 // 查找含 destructive class token 的按钮文本（shadcn Button destructive 变体会注入
 // bg-destructive 等类名；匹配 html 任一位置以覆盖 Button 组件内部渲染差异）
 const html = wrapper.html
 expect(html).toContain('destructive')
 // 并且精简 prompt 应渲染为 primary / default variant（不含 outline 标识）
 // 与清理历史按钮相邻：只做 destructive 存在性断言（视觉层级验证）
 })
})
