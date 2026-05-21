/**
 * Quick Task：ChatMessageBubble.vue parts 顺序渲染契约测试。
 *
 * 测试矩阵（PLAN § 测试要求 ≥ 6 条）：
 * 1. renders_parts_in_order
 * 2. text_part_renders_markdown
 * 3. tool_use_part_renders_tool_pill_with_props
 * 4. thinking_part_renders_timeline_step--thinking
 * 5. deep_analysis_tool_use_part_renders_deep_analysis_panel
 * 6. unknown_part_type_renders_fallback_no_crash
 * + F5 反退化（来自 PLAN §1 Goal 根治证据）：长 markdown 不被 narration-block 包裹
 */
import type { ConversationMessage } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'
import v25Fixtures from './fixtures/v25-legacy-messages.json'
vi.mock('~/composables/useMarkdownRenderer', => ({
 getMarkdownRenderer: vi.fn(async => ({
 render: (raw: string) => `<div data-test="md-rendered">${raw}</div>`,
 })),
}))
// stub Checkbox / DocSummaryCard / RoutingDecisionPanel / TechPlanCard 避免重依赖
vi.mock('~/components/ui/checkbox', => ({
 Checkbox: defineComponent({ name: 'Checkbox', setup: => => h('input', { type: 'checkbox' }) }),
}))
vi.mock('~/components/chat/DocSummaryCard.vue', => ({
 default: defineComponent({ name: 'DocSummaryCard', setup: => => h('div', { 'data-test': 'doc-summary' }) }),
}))
vi.mock('~/components/chat/RoutingDecisionPanel.vue', => ({
 default: defineComponent({
 name: 'RoutingDecisionPanel',
 props: ['traceId', 'conversationId', 'messageId'],
 setup: => => h('div', { 'data-test': 'routing-panel' }),
 }),
}))
vi.mock('~/components/chat/TechPlanCard.vue', => ({
 default: defineComponent({
 name: 'TechPlanCard',
 props: ['planId', 'sessionId', 'techPlan', 'affectedFiles', 'status', 'isConfirming', 'branchName'],
 setup: (props) => => h('div', { 'data-test': 'tech-plan-card', 'data-status': props.status }),
 }),
}))
function makeMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
 return {
 id: 'msg-test',
 role: 'assistant',
 content: '',
 created_at: '2026-05-21T00:00:00Z',
 ...overrides,
 }
}
async function mountBubble(message: ConversationMessage, props: Record<string, unknown> = {}) {
 const wrapper = mount(ChatMessageBubble, {
 props: { message, isStreaming: false, ...props },
 global: {
 stubs: { Transition: false },
 },
 })
 // 等待 md renderer onMounted resolve
 await new Promise<void>(r => setTimeout(r, 0))
 await new Promise<void>(r => setTimeout(r, 0))
 await wrapper.vm.$nextTick
 return wrapper
}
describe('ChatMessageBubble parts rendering (Quick Task )', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 it('1. renders parts in order (text → tool_use → text)', async => {
 const msg = makeMessage({
 content: '基于结果：found',
 parts: [
 { type: 'text', id: 'p1', index: 0, text: '先思考一下，', state: 'done' },
 {
 type: 'tool_use',
 id: 'p2',
 index: 1,
 tool_call_id: 'call_1',
 name: 'search_repository_code',
 input: { query: 'foo' },
 status: 'done',
 result: 'ok',
 },
 { type: 'text', id: 'p3', index: 2, text: '基于结果：found', state: 'done' },
 ],
 })
 const wrapper = await mountBubble(msg)
 const flow = wrapper.find('.timeline-flow')
 expect(flow.exists).toBe(true)
 const html = flow.html
 const textIdx1 = html.indexOf('先思考一下')
 // tool_pill 渲染 toolLabel 为「搜索代码」（中文 map）—— 用此作为 tool 部分的锚点
 const toolIdx = html.indexOf('搜索代码')
 const textIdx2 = html.indexOf('基于结果')
 expect(textIdx1).toBeGreaterThan(-1)
 expect(toolIdx).toBeGreaterThan(-1)
 expect(textIdx2).toBeGreaterThan(-1)
 expect(textIdx1).toBeLessThan(toolIdx)
 expect(toolIdx).toBeLessThan(textIdx2)
 })
 it('2. text part renders markdown (via stub renderer)', async => {
 const msg = makeMessage({
 content: '# Title',
 parts: [{ type: 'text', id: 'p1', index: 0, text: '# Title', state: 'done' }],
 })
 const wrapper = await mountBubble(msg)
 const prose = wrapper.findAll('.ai-prose')
 expect(prose.length).toBeGreaterThanOrEqual(1)
 expect(prose[0].html).toContain('md-rendered')
 expect(prose[0].html).toContain('# Title')
 })
 it('3. tool_use part renders tool-pill with proper label + status', async => {
 const msg = makeMessage({
 parts: [
 {
 type: 'tool_use',
 id: 'p1',
 index: 0,
 tool_call_id: 'c1',
 name: 'search_repository_code',
 input: { query: 'foo' },
 status: 'done',
 result: 'ok',
 },
 ],
 })
 const wrapper = await mountBubble(msg)
 expect(wrapper.find('.tool-pill').exists).toBe(true)
 expect(wrapper.find('.tool-dot--done').exists).toBe(true)
 expect(wrapper.html).toContain('搜索代码')
 })
 it('4. thinking part renders timeline-step--thinking', async => {
 const msg = makeMessage({
 parts: [
 { type: 'thinking', id: 'p1', index: 0, text: '用户想要分析跨仓代码', state: 'done' },
 { type: 'text', id: 'p2', index: 1, text: '正在分析', state: 'done' },
 ],
 })
 const wrapper = await mountBubble(msg)
 expect(wrapper.find('.timeline-step--thinking').exists).toBe(true)
 expect(wrapper.html).toContain('用户想要分析跨仓代码')
 })
 it('5. deep_analysis tool_use 渲染 deep-analysis-panel（hasDeepAnalysisLogs 触发）', async => {
 const msg = makeMessage({
 parts: [
 {
 type: 'tool_use',
 id: 'p1',
 index: 0,
 tool_call_id: 'c1',
 name: 'deep_analysis',
 input: { task_description: 'analyze' },
 status: 'done',
 result: 'long result',
 },
 ],
 metadata: {
 deep_analysis_logs: [
 { type: 'text', content: '[思考] 开始分析', ts: 1715000000000 },
 { type: 'result', content: 'cost=$0.001', ts: 1715000010000 },
 ],
 },
 })
 const wrapper = await mountBubble(msg)
 expect(wrapper.find('.deep-analysis-panel').exists).toBe(true)
 expect(wrapper.html).toContain('执行记录')
 })
 it('6. unknown part type 渲染 fallback 不 crash（forward-compat）', async => {
 const msg = makeMessage({
 parts: [
 // @ts-expect-error 故意构造未知 type 模拟 v27 新增 part type 旧客户端遇到
 { type: 'image', id: 'p1', index: 0, src: 'data:image/png;base64,xxx' },
 { type: 'text', id: 'p2', index: 1, text: '正常文本', state: 'done' },
 ],
 })
 const wrapper = await mountBubble(msg)
 expect(wrapper.find('.unknown-part').exists).toBe(true)
 expect(wrapper.text).toContain('[未知 part: image]')
 expect(wrapper.text).toContain('正常文本')
 })
 it('7. F5 反退化 —— 长 markdown 答复直接渲染为顶层 ai-prose，不被 narration-block 包裹', async => {
 // F5 fixture：deep_analysis 长 markdown + 单 tool_call
 const f5 = v25Fixtures.F5 as unknown as ConversationMessage
 const wrapper = await mountBubble(f5)
 const html = wrapper.html
 // 关键不变量 1：narration-block / narration-toggle / narration-count
 // CSS class 必须不存在于渲染输出（PLAN § 要求删除）
 expect(html).not.toContain('class="narration-block"')
 expect(html).not.toContain('narration-toggle')
 expect(html).not.toContain('narration-count')
 expect(html).not.toContain('timeline-step--narration')
 // 关键不变量 2：长 markdown 标题 / 代码块 / 表格关键标记直接出现在 ai-prose 中
 const prose = wrapper.findAll('.ai-prose')
 const proseTexts = prose.map(p => p.html).join('\n')
 expect(proseTexts).toContain('# entrance 字段处理逻辑分析')
 expect(proseTexts).toContain('apps/study/views.py')
 expect(proseTexts).toContain('| 字段 | 含义 | 默认值 |')
 // 关键不变量 3：narration 字符串以独立 ai-prose text part 呈现
 // （顶层 markdown 块，不嵌套在「分析」折叠容器内）
 expect(proseTexts).toContain('让我深入分析两个仓库中 entrance 字段的处理逻辑...')
 // 关键不变量 4：deep_analysis tool_use part 仍能渲染 deep-analysis-panel
 expect(wrapper.find('.deep-analysis-panel').exists).toBe(true)
 })
})
