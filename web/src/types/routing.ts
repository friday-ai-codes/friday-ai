/**
 * ：跨仓路由决策类型契约。
 *
 * 与后端 `RepositoryRelevanceOutput` / `RepositoryRoutingTrace` 一一对应，
 * RoutingDecisionPanel / RelevanceBadge / RepoMultiSelector 共享同一份 store。
 */

export type RoutingLevel = 'high' | 'medium' | 'low'

export type RoutingTriggeredBy = 'chat_tool' | 'deep_analysis_completion' | 'manual_override'

/** 候选归属组（ROUTE-01）：缺失视为 'global'。 */
export type RoutingGroup = 'in_project' | 'global'

/** 信任标记（与 group === 'global' 语义重合，本阶段仅作契约留存）。 */
export type RoutingTrust = 'trusted' | 'needs_confirmation'

/**
 * 降级原因受控闭集（6 值，与后端 classify_degrade_reason 字面对齐）。
 *
 * 闭集本身就是一道信息泄漏防线：赋非受控字符串（异常名 / 截断的上游 body）
 * 时 vue-tsc 编译期即拦（T-107-02）。
 */
export type RoutingDegradeReason
  = 'timeout' | 'upstream_error' | 'provider_missing'
    | 'unparsable' | 'no_node_index' | 'unknown'

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
  /**
   * 归属组（ROUTE-01）；缺失**或空串**视为 'global'（历史 trace 兼容）。
   * 类型带上 `''` 是为了与运行时形状一致 —— 后端 pydantic 字段的默认值就是空串，
   * 写成 `group?: RoutingGroup` 会让 `c.group ?? 'global'` 这类空串失效的兜底
   * 在类型层面看起来是安全的。
   */
  group?: RoutingGroup | ''
  /** 信任标记；缺失不渲染。 */
  trust?: RoutingTrust
  /**
   * 凸组合排序分（旁路字段）：排序取 score_ranked ?? score。
   * 不进任何可见文案——徽标与分数分解合计仍用 score。
   */
  score_ranked?: number | null
  // 后端留痕/排障用的自由文本，**前端不渲染**（T-107-06：跨组说明句一律取前端常量）。
  cross_group_note?: string
}

export interface RoutingDecisionData {
  trace_id: string
  query: string
  candidates: RoutingCandidate[]
  threshold: number
  triggered_by: RoutingTriggeredBy
  /** 路由版本（v2 / v2_stage0_only / v1_fallback / legacy_hybrid）。 */
  router_version?: string
  /** 降级事实，由后端派生；前端绝不自行推断。缺失视为 false。 */
  degraded?: boolean
  degrade_reason?: RoutingDegradeReason
  /** 区顺序权威（ROUTE-01）：长度 2 = 有项目上下文，前端不重排区。 */
  block_order?: RoutingGroup[]
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
  /** 后端 107-08 起回传的四个 trace 级事实（老部署可能缺，故全 optional）。 */
  router_version?: string
  degraded?: boolean
  degrade_reason?: RoutingDegradeReason
  block_order?: RoutingGroup[]
}
