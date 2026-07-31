// ============================================================================
// : AI 执行透视与成本追踪 — 类型定义
// ============================================================================

/**
 * ActionLog 摘要（ReAct 步骤列表项）
 * GET /workflows/node-executions/{pk}/react-steps/
 */
export interface ActionLogSummary {
  id: number
  action_type: 'tool_call' | 'llm_request' | 'llm_response' | 'state_change' | 'decision'
  sequence: number
  duration_ms: number | null
  timestamp: string
  payload_summary: string
}

/**
 * ActionLog 详情（展开后的完整 payload）
 * GET /workflows/action-logs/{pk}/
 */
export interface ActionLogDetail {
  id: number
  session: number
  action_type: string
  sequence: number
  duration_ms: number | null
  timestamp: string
  payload: Record<string, unknown>
  created_at: string
}

// ============================================================================
// 成本拆分类型
// ============================================================================

/**
 * 单个模型的 Token + 成本统计
 */
export interface CostBreakdownNodeModel {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
  total_cost_usd: string
}

/**
 * 节点级成本拆分
 */
export interface CostBreakdownNode {
  node_id: string
  node_name: string
  node_type: string
  models: Record<string, CostBreakdownNodeModel>
}

/**
 * 执行级成本汇总
 */
export interface CostBreakdownSummary {
  total_input_tokens: number
  total_output_tokens: number
  total_cache_read_tokens: number
  total_cache_write_tokens: number
  total_tokens: number
  total_cost_usd: string
  model_distribution: Record<string, string>
}

/**
 * 成本拆分完整响应
 * GET /workflow-executions/{pk}/cost-breakdown/
 */
export interface CostBreakdown {
  nodes: CostBreakdownNode[]
  summary: CostBreakdownSummary
}

// ============================================================================
// DAG 节点成本注入类型
// ============================================================================

/**
 * 节点级成本（注入到 ExecutionNodeData.cost）
 */
export interface NodeCost {
  totalCostUsd: string
  totalTokens: number
  models: Record<string, CostBreakdownNodeModel>
}

// ============================================================================
// 子步骤类型（: 前端集成）
// ============================================================================

/**
 * 子步骤进度摘要（折叠状态显示 "2/5 steps"）
 */
export interface SubStepProgress {
  completed: number
  total: number
}

/**
 * 节点执行子步骤
 * GET /node-executions/{id}/sub-steps/
 * WebSocket sub_step.update 事件数据
 */
export interface SubStep {
  id: string
  name: string
  step_type: string
  step_order: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  input_data: Record<string, any>
  output_data: Record<string, any>
  started_at: string | null
  completed_at: string | null
}

/**
 * 通用竖向时间线 item 契约（SubStepTimeline 的入参单元）。
 *
 * 与 `SubStep` 解耦：`SubStep` 带 step_type / step_order / input_data / started_at 等
 * 工作流执行域字段，编排阶段侧根本没有这些东西。`SubStep` 结构上满足本接口
 * （status 的 4 值是本接口 6 值的子集），因此 ExecutionNode 的调用点零改动。
 */
export interface TimelineStepItem {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped' | 'unknown'
  /** 该步的一句话摘要；缺省不渲染摘要行（不是渲染一句「暂无」）。 */
  summary?: string
  /** 行尾角标；缺省不渲染。纯 variant，禁止 :class 追加颜色。 */
  badge?: { text: string, variant: 'warning' | 'info' | 'muted' }
  /**
   * running 态是否脉冲。缺省 true = 今日行为逐字不变。
   * 传 false 时**只去掉 animate-pulse，色值不变** —— 用于「合法等待用户」「会话已终态」
   * 这类「确实不在动」的进行中步骤：动画讲的是「它正在推进」，不在推进却还在闪是撒谎。
   */
  pulse?: boolean
  /** 既有：failed 时的错误摘要来源，保留以兼容 ExecutionNode。 */
  output_data?: Record<string, any>
}

// ============================================================================
// : 结构化执行日志类型
// ============================================================================

/**
 * 结构化执行日志条目
 */
export interface ExecutionLogEntry {
  timestamp: string
  level: 'INFO' | 'WARN' | 'ERROR'
  message: string
  context?: Record<string, any> | null
}
