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
})
