/**
 * ：跨仓路由决策状态管理（pinia setup-style）。
 *
 * RelevanceBadge / RepoMultiSelector / TechPlanCard 共享同一份 store —— 勾选变化
 * → manual_override 写新行 trace → store latestTraceId 更新 → 所有徽章 / 选择器
 * 自动重渲染。
 *
 * `applyManualOverride` 目前**没有生产调用方**：原调用方 `RoutingDecisionPanel`
 * 已随 ROUTE 缺口闭环删除，选仓入口统一收在底部澄清卡。保留该 action 与它的用例
 * 是因为 `POST /override/` 端点仍在线、契约仍需守住；如需再开选仓面，接这里即可。
 */

import type { ManualOverrideRequestCandidate, RoutingDecisionData } from '~/types/routing'
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { postManualOverride } from '~/api/routing'

export const useRoutingStore = defineStore('routing', () => {
  /** trace_id → RoutingDecisionData（单一真源） */
  const tracesByTraceId = ref<Map<string, RoutingDecisionData>>(new Map())

  /** conversation_id → trace_id 列表（最新在前） */
  const tracesByConversationId = ref<Map<string, string[]>>(new Map())

  /** conversation_id → 最新 trace_id（RepoMultiSelector / TechPlanCard 共享） */
  const latestTraceIdByConversationId = ref<Map<string, string>>(new Map())

  /**
   * 写入或更新 trace；自动维护双索引 + latest 指针。
   *
   * 同 trace_id 多次 upsert 不重复（去重保留单条历史）。
   */
  function upsertTrace(trace: RoutingDecisionData, conversationId: string): void {
    tracesByTraceId.value.set(trace.trace_id, trace)
    const list = tracesByConversationId.value.get(conversationId) ?? []
    const next = [trace.trace_id, ...list.filter(id => id !== trace.trace_id)]
    tracesByConversationId.value.set(conversationId, next)
    latestTraceIdByConversationId.value.set(conversationId, trace.trace_id)
  }

  function getTrace(traceId: string): RoutingDecisionData | undefined {
    return tracesByTraceId.value.get(traceId)
  }

  function getLatestTraceId(conversationId: string): string | undefined {
    return latestTraceIdByConversationId.value.get(conversationId)
  }

  /**
   * 取最新 trace 中 selected_by_user_final=true 的 repository_id 列表
   * （RepoMultiSelector / TechPlanCard 默认勾选状态来源）。
   */
  function getLatestSelectedRepoIds(conversationId: string): string[] {
    const traceId = latestTraceIdByConversationId.value.get(conversationId)
    if (!traceId)
      return []
    const trace = tracesByTraceId.value.get(traceId)
    return (
      trace?.candidates
        .filter(c => c.selected_by_user_final)
        .map(c => c.repository_id) ?? []
    )
  }

  /**
   * 用户改勾选 → POST /override/ 写新 trace → store 自动写入并更新 latest 指针。
   *
   * 失败返 null，调用方应回滚 UI 状态 + 提示 toast。
   */
  async function applyManualOverride(
    conversationId: string,
    originalTraceId: string,
    updated: ManualOverrideRequestCandidate[],
  ): Promise<RoutingDecisionData | null> {
    try {
      const response = await postManualOverride(originalTraceId, { candidates: updated })
      const original = tracesByTraceId.value.get(originalTraceId)
      // 四个 trace 级事实「响应优先、original 兜底」：同一次路由的降级与分区
      // 事实不因用户改勾选而改变。不继承的话（本仓此前的行为）用户勾一次
      // 降级横幅与分组分区就凭空消失（107-RESEARCH Pitfall 3）。
      // 用 ?? 而非 ||：响应显式给 degraded=false 时不能被 original 的 true 盖回。
      const newTrace: RoutingDecisionData = {
        trace_id: response.trace_id,
        query: original?.query ?? '',
        candidates: response.candidates,
        threshold: original?.threshold ?? 0.5,
        triggered_by: 'manual_override',
        router_version: response.router_version ?? original?.router_version,
        degraded: response.degraded ?? original?.degraded,
        degrade_reason: response.degrade_reason ?? original?.degrade_reason,
        block_order: response.block_order ?? original?.block_order,
      }
      upsertTrace(newTrace, conversationId)
      return newTrace
    }
    catch (err) {
      console.error('manual override failed', err)
      return null
    }
  }

  return {
    tracesByTraceId,
    tracesByConversationId,
    latestTraceIdByConversationId,
    upsertTrace,
    getTrace,
    getLatestTraceId,
    getLatestSelectedRepoIds,
    applyManualOverride,
  }
})
