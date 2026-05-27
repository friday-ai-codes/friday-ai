/**
 * Phase：chat store 协商卡片状态机测试。
 */
import type { ClarificationPayload } from '~/types/clarification'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useChatStore } from '~/stores/chat'
function makePayload(overrides: Partial<ClarificationPayload> = {}): ClarificationPayload {
 return {
 clarification_id: 'clar-1',
 question: 'A or B?',
 options: [
 { id: 'opt-A', label: 'A' },
 { id: 'opt-B', label: 'B' },
 ],
 allow_freeform: true,
 status: 'pending',
 ...overrides,
 }
}
describe('chat store - clarifications', => {
 beforeEach( => {
 setActivePinia(createPinia)
 })
 it('upsertClarification 添加一条记录', => {
 const store = useChatStore
 expect(store.pendingClarifications.size).toBe(0)
 store.upsertClarification(makePayload)
 expect(store.pendingClarifications.size).toBe(1)
 expect(store.getClarification('clar-1')?.status).toBe('pending')
 })
 it('upsertClarification 重复 id 覆盖原值', => {
 const store = useChatStore
 store.upsertClarification(makePayload({ question: '第一次' }))
 store.upsertClarification(makePayload({ question: '第二次' }))
 expect(store.getClarification('clar-1')?.question).toBe('第二次')
 expect(store.pendingClarifications.size).toBe(1)
 })
 it('markClarificationAnswered 切换 status + 写 answer', => {
 const store = useChatStore
 store.upsertClarification(makePayload)
 store.markClarificationAnswered('clar-1', {
 selected_option_id: 'opt-A',
 freeform_text: '',
 answered_at: '2026-05-21T00:00:00Z',
 })
 const result = store.getClarification('clar-1')
 expect(result?.status).toBe('answered')
 expect(result?.answer?.selected_option_id).toBe('opt-A')
 })
 it('markClarificationAnswered 不存在的 id 静默忽略', => {
 const store = useChatStore
 expect( => store.markClarificationAnswered('not-exist', {
 selected_option_id: 'x',
 answered_at: 'now',
 })).not.toThrow
 expect(store.pendingClarifications.size).toBe(0)
 })
 it('clearAllClarifications 清空 Map', => {
 const store = useChatStore
 store.upsertClarification(makePayload({ clarification_id: 'a' }))
 store.upsertClarification(makePayload({ clarification_id: 'b' }))
 expect(store.pendingClarifications.size).toBe(2)
 store.clearAllClarifications
 expect(store.pendingClarifications.size).toBe(0)
 })
 it('answered 后保留在 Map 中（消息流不删）', => {
 const store = useChatStore
 store.upsertClarification(makePayload)
 store.markClarificationAnswered('clar-1', {
 selected_option_id: 'opt-A',
 answered_at: 'now',
 })
 expect(store.pendingClarifications.size).toBe(1)
 expect(store.getClarification('clar-1')?.status).toBe('answered')
 })
 /**
 * UAT 2026-05-27 hotfix（review review round）：跨 conversation 串单回归。
 *
 * 复现 work-item.md review round Gap：用户在 conv 78681e45 (entrance) 视图里
 * 看到了 conv 3673d77b (operationResource) 的 ClarificationCard。
 */
 describe('跨 conversation 串单防护（review review round hotfix）', => {
 it('upsertClarification 显式传 conversationId 写入 payload', => {
 const store = useChatStore
 store.upsertClarification(makePayload({ clarification_id: 'c-a' }), 'conv-A')
 const saved = store.getClarification('c-a')
 expect(saved?.conversation_id).toBe('conv-A')
 })
 it('upsertClarification 不传 conversationId 时回退到当前 conv', => {
 const store = useChatStore
 store.currentConversationId = 'conv-fallback'
 store.upsertClarification(makePayload({ clarification_id: 'c-b' }))
 expect(store.getClarification('c-b')?.conversation_id).toBe('conv-fallback')
 })
 it('payload 已带 conversation_id 时优先用 caller 传入值（caller wins）', => {
 const store = useChatStore
 store.currentConversationId = 'conv-current'
 store.upsertClarification(
 makePayload({ clarification_id: 'c-c', conversation_id: 'conv-from-payload' }),
 'conv-from-caller',
 )
 expect(store.getClarification('c-c')?.conversation_id).toBe('conv-from-caller')
 })
 it('两个 conv 的 clarification 共存于 Map 时各自带 conv 维度（前端 filter 可分流）', => {
 const store = useChatStore
 store.upsertClarification(makePayload({ clarification_id: 'c-A' }), 'conv-A')
 store.upsertClarification(makePayload({ clarification_id: 'c-B' }), 'conv-B')
 expect(store.pendingClarifications.size).toBe(2)
 const onlyA = [...store.pendingClarifications.values].filter(
 p => p.conversation_id === 'conv-A',
 )
 expect(onlyA.length).toBe(1)
 expect(onlyA[0].clarification_id).toBe('c-A')
 })
 it('legacy payload (无 conversation_id) + 未设 currentConversationId 时 conversation_id 为 undefined（向后兼容）', => {
 const store = useChatStore
 // currentConversationId 保持 null（未设）
 store.upsertClarification(makePayload({ clarification_id: 'c-legacy' }))
 const saved = store.getClarification('c-legacy')
 expect(saved?.conversation_id).toBeUndefined
 })
 })
 /**
 * review review round Fix C-1：phase_transition(waiting_clarification) event 直接 upsert。
 *
 * 编排层 `_extract_relev_low_confidence_pending` 自动构造的 clarification
 * 不会产生 `tool_use_result(ask_clarification)` 事件（LLM 没主动调工具）—— 前
 * 端必须在 `phase_transition` 事件携带 question/options 时直接 upsert，否则
 * ClarificationCard 永远不渲染、用户答不了 → graph 永久 hang。
 */
 describe('phase_transition event 路径自动 upsert（review review round Fix C-1）', => {
 it('phase=waiting_clarification + question/options 完整时调 upsertClarification', => {
 const store = useChatStore
 store.currentConversationId = 'conv-pt-1'
 store._dispatchSSE({
 type: 'phase_transition',
 phase: 'waiting_clarification',
 clarification_id: 'c-from-pt-1',
 question: '请确认要看哪个仓库？',
 options: [
 { id: 'opt-A', label: 'study-app' },
 { id: 'opt-B', label: 'problem-app' },
 ],
 allow_freeform: true,
 })
 const saved = store.getClarification('c-from-pt-1')
 expect(saved).toBeDefined
 expect(saved?.question).toBe('请确认要看哪个仓库？')
 expect(saved?.options.length).toBe(2)
 expect(saved?.allow_freeform).toBe(true)
 expect(saved?.status).toBe('pending')
 expect(saved?.conversation_id).toBe('conv-pt-1')
 })
 it('phase=waiting_clarification 但 question 缺失 → 不 upsert（防空卡片）', => {
 const store = useChatStore
 store.currentConversationId = 'conv-pt-2'
 store._dispatchSSE({
 type: 'phase_transition',
 phase: 'waiting_clarification',
 clarification_id: 'c-no-question',
 })
 expect(store.getClarification('c-no-question')).toBeUndefined
 })
 it('phase 是其他态（如 waiting / executing）→ 不 upsert', => {
 const store = useChatStore
 store.currentConversationId = 'conv-pt-3'
 store._dispatchSSE({
 type: 'phase_transition',
 phase: 'waiting',
 blocking_task_count: 2,
 })
 store._dispatchSSE({
 type: 'phase_transition',
 phase: 'executing',
 })
 expect(store.pendingClarifications.size).toBe(0)
 })
 it('allow_freeform 缺失时默认 true（兼容老后端 payload）', => {
 const store = useChatStore
 store.currentConversationId = 'conv-pt-4'
 store._dispatchSSE({
 type: 'phase_transition',
 phase: 'waiting_clarification',
 clarification_id: 'c-no-freeform-flag',
 question: '请选择',
 options: [{ id: 'opt-A', label: 'A' }],
 // allow_freeform 缺失
 })
 expect(store.getClarification('c-no-freeform-flag')?.allow_freeform).toBe(true)
 })
 it('options 缺失或非数组时 fallback 空数组（防类型异常）', => {
 const store = useChatStore
 store.currentConversationId = 'conv-pt-5'
 store._dispatchSSE({
 type: 'phase_transition',
 phase: 'waiting_clarification',
 clarification_id: 'c-bad-options',
 question: '请选择',
 // options 缺失
 })
 expect(store.getClarification('c-bad-options')?.options).toEqual
 })
 })
})
