/**
 * Phase：useRoutingStore 单元测试。
 *
 * 覆盖：upsertTrace 双索引 / 去重 / 跨 conversation 隔离 /
 * getLatestSelectedRepoIds / applyManualOverride success / failure。
 */
import type { RoutingDecisionData } from '~/types/routing'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useRoutingStore } from '~/stores/routing'
const mockPostManualOverride = vi.fn
vi.mock('~/api/routing', => ({
 postManualOverride: (...args: unknown) => mockPostManualOverride(...args),
}))
function makeTrace(overrides: Partial<RoutingDecisionData> = {}): RoutingDecisionData {
 return {
 trace_id: 'trace-1',
 query: 'q',
 threshold: 0.5,
 triggered_by: 'chat_tool',
 candidates: [
 {
 repository_id: 'repo-a',
 repository_name: 'A',
 score: 0.9,
 level: 'high',
 evidence: 'ev',
 selected_by_ai: true,
 selected_by_user_final: true,
 },
 {
 repository_id: 'repo-b',
 repository_name: 'B',
 score: 0.3,
 level: 'low',
 evidence: 'ev',
 selected_by_ai: false,
 selected_by_user_final: false,
 },
 ],
 ...overrides,
 }
}
describe('useRoutingStore', => {
 beforeEach( => {
 setActivePinia(createPinia)
 mockPostManualOverride.mockReset
 })
 it('upsertTrace 写入双索引 + latest 指针', => {
 const store = useRoutingStore
 store.upsertTrace(makeTrace, 'conv-1')
 expect(store.tracesByTraceId.get('trace-1')).toBeTruthy
 expect(store.tracesByConversationId.get('conv-1')).toEqual(['trace-1'])
 expect(store.latestTraceIdByConversationId.get('conv-1')).toBe('trace-1')
 })
 it('同 trace_id upsert 第二次不重复（list 长度仍 1）', => {
 const store = useRoutingStore
 store.upsertTrace(makeTrace, 'conv-1')
 store.upsertTrace(makeTrace, 'conv-1')
 expect(store.tracesByConversationId.get('conv-1')).toEqual(['trace-1'])
 })
 it('不同 conversation_id 各自维护独立 list', => {
 const store = useRoutingStore
 store.upsertTrace(makeTrace({ trace_id: 't-a' }), 'conv-1')
 store.upsertTrace(makeTrace({ trace_id: 't-b' }), 'conv-2')
 expect(store.tracesByConversationId.get('conv-1')).toEqual(['t-a'])
 expect(store.tracesByConversationId.get('conv-2')).toEqual(['t-b'])
 })
 it('getLatestSelectedRepoIds 取最新 trace 中 selected_by_user_final=true 的 IDs', => {
 const store = useRoutingStore
 store.upsertTrace(makeTrace, 'conv-1')
 expect(store.getLatestSelectedRepoIds('conv-1')).toEqual(['repo-a'])
 })
 it('applyManualOverride 成功 → 新 trace 写入 + latest 更新', async => {
 const store = useRoutingStore
 store.upsertTrace(makeTrace, 'conv-1')
 mockPostManualOverride.mockResolvedValue({
 trace_id: 'trace-2',
 original_trace_id: 'trace-1',
 triggered_by: 'manual_override',
 candidates: [
 {
 repository_id: 'repo-a',
 repository_name: 'A',
 score: 0.9,
 level: 'high',
 evidence: 'ev',
 selected_by_ai: true,
 selected_by_user_final: false,
 },
 {
 repository_id: 'repo-b',
 repository_name: 'B',
 score: 0.3,
 level: 'low',
 evidence: 'ev',
 selected_by_ai: false,
 selected_by_user_final: true,
 },
 ],
 })
 const result = await store.applyManualOverride('conv-1', 'trace-1', [
 { repository_id: 'repo-a', selected: false },
 { repository_id: 'repo-b', selected: true },
 ])
 expect(result?.trace_id).toBe('trace-2')
 expect(store.latestTraceIdByConversationId.get('conv-1')).toBe('trace-2')
 expect(store.getLatestSelectedRepoIds('conv-1')).toEqual(['repo-b'])
 expect(mockPostManualOverride).toHaveBeenCalledTimes(1)
 })
 it('applyManualOverride 失败 → 返回 null + latest 不变', async => {
 const store = useRoutingStore
 store.upsertTrace(makeTrace, 'conv-1')
 mockPostManualOverride.mockRejectedValue(new Error('network'))
 const result = await store.applyManualOverride('conv-1', 'trace-1', [
 { repository_id: 'repo-a', selected: false },
 ])
 expect(result).toBeNull
 expect(store.latestTraceIdByConversationId.get('conv-1')).toBe('trace-1')
 })
})
