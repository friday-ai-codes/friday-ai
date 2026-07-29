/**
 * ：跨仓路由决策类型契约。
 *
 * 与后端 `RepositoryRelevanceOutput` / `RepositoryRoutingTrace` 一一对应，
 * RoutingDecisionPanel / RelevanceBadge / RepoMultiSelector 共享同一份 store。
 */

export type RoutingLevel = 'high' | 'medium' | 'low'

export type RoutingTriggeredBy = 'chat_tool' | 'deep_analysis_completion' | 'manual_override'

export interface RoutingCandidate {
  repository_id: string
  repository_name: string
  score: number
  level: RoutingLevel
  evidence: string
  selected_by_ai: boolean
  selected_by_user_final: boolean
  /**
   * 分数分解（ROUTE-07）：信号名 → 贡献值，Σ值 == score（后端不变量
   * INV-R1/R3 保证）。legacy 路径 / 历史 trace 缺失，前端静默降级。
   */
  breakdown?: Record<string, number>
}

export interface RoutingDecisionData {
  trace_id: string
  query: string
  candidates: RoutingCandidate[]
  threshold: number
  triggered_by: RoutingTriggeredBy
}

export interface ManualOverrideRequestCandidate {
  repository_id: string
  selected: boolean
}

export interface ManualOverrideRequest {
  candidates: ManualOverrideRequestCandidate[]
}

export interface ManualOverrideResponse {
  trace_id: string
  original_trace_id: string
  candidates: RoutingCandidate[]
  triggered_by: 'manual_override'
}
