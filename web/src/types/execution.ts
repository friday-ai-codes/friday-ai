// ============================================================================
// Phase: AI 执行透视与成本追踪 — 类型定义
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
 * GET /workflows/workflow-executions/{pk}/cost-breakdown/
 */
export interface CostBreakdown {
 nodes: CostBreakdownNode
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
