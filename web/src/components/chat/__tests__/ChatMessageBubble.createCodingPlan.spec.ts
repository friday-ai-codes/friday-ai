import type { ConversationMessage } from '~/types/chat'
import type { RoutingDecisionData } from '~/types/routing'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'
import { useChatStore } from '~/stores/chat'
import { useRoutingStore } from '~/stores/routing'
vi.mock('~/composables/useMarkdownRenderer', => ({
 getMarkdownRenderer: vi.fn(async => ({
 render: (raw: string) => `<div data-test="md-rendered">${raw}</div>`,
 })),
}))
vi.mock('~/components/ui/checkbox', => ({
 Checkbox: defineComponent({ name: 'Checkbox', setup: => => h('input', { type: 'checkbox' }) }),
}))
vi.mock('~/components/chat/DocSummaryCard.vue', => ({
 default: defineComponent({ name: 'DocSummaryCard', setup: => => h('div', { 'data-test': 'doc-summary' }) }),
}))
vi.mock('~/components/chat/TechPlanCard.vue', => ({
 default: defineComponent({ name: 'TechPlanCard', setup: => => h('div', { 'data-test': 'tech-plan-card' }) }),
}))
// RoutingDecisionPanel 桩：渲染一个按钮，点击时 emit createCodingPlanFromTrace，
// 模拟「基于这些仓库创建编码方案」点击 → 让我们验证父组件 ChatMessageBubble 的处理。
vi.mock('~/components/chat/RoutingDecisionPanel.vue', => ({
 default: defineComponent({
 name: 'RoutingDecisionPanel',
 props: ['traceId', 'conversationId', 'messageId'],
 emits: ['createCodingPlanFromTrace', 'manualSelectRequested'],
 setup(props, { emit }) {
 return => h('button', {
 'data-test': 'stub-create-plan',
 'onClick': => emit('createCodingPlanFromTrace', props.traceId),
 }, 'create')
 },
 }),
}))
function makeTrace: RoutingDecisionData {
 return {
 trace_id: 'trace-x',
 query: '统一入口配置中心',
 threshold: 0.5,
 triggered_by: 'chat_tool',
 candidates: [
 { repository_id: 'r1', repository_name: 'study-app', score: 0.8, level: 'high', evidence: 'e', selected_by_ai: true, selected_by_user_final: true },
 { repository_id: 'r2', repository_name: 'problem-app', score: 0.79, level: 'high', evidence: 'e', selected_by_ai: true, selected_by_user_final: true },
 { repository_id: 'r3', repository_name: 'onion-practice', score: 0.77, level: 'high', evidence: 'e', selected_by_ai: true, selected_by_user_final: false },
 ],
 }
}
function makeAssistantMessage: ConversationMessage {
 return {
 id: 'msg-assistant',
 role: 'assistant',
 content: '路由分析',
 created_at: '2026-05-29T03:00:00Z',
 metadata: { routing_trace_id: 'trace-x', conversation_id: 'conv-1' },
 } as ConversationMessage
}
describe('ChatMessageBubble — 基于路由决策创建编码方案', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 it('点击创建编码方案 → 发出自包含 message：含选中仓库名 + 指示调用 create_coding_plan', async => {
 const routingStore = useRoutingStore
 routingStore.upsertTrace(makeTrace, 'conv-1')
 const chatStore = useChatStore
 const sendSpy = vi.spyOn(chatStore, 'sendMessage').mockResolvedValue(undefined as never)
 const wrapper = mount(ChatMessageBubble, {
 props: { message: makeAssistantMessage, isStreaming: false },
 global: { stubs: { Transition: false } },
 })
 await new Promise<void>(r => setTimeout(r, 0))
 await wrapper.vm.$nextTick
 const btn = wrapper.find('[data-test="stub-create-plan"]')
 expect(btn.exists).toBe(true)
 await btn.trigger('click')
 expect(sendSpy).toHaveBeenCalledTimes(1)
 const sent = sendSpy.mock.calls[0][0] as string
 // 含明确工具指示
 expect(sent).toContain('create_coding_plan')
 // 仅内联 selected_by_user_final=true 的仓库（study-app / problem-app），排除未选的 onion-practice
 expect(sent).toContain('study-app')
 expect(sent).toContain('problem-app')
 expect(sent).not.toContain('onion-practice')
 // 提示后端自动推断、无需重新分析
 expect(sent).toContain('recommended_repository_ids')
 })
})
