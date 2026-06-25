/**
 * Workflow API - 工作流相关接口
 */

import type {
  ManualTriggerRequest,
  ManualTriggerResponse,
  WorkflowTrigger,
  WorkflowTriggerCreate,
} from '~/types'
import type {
  ActionLogDetail,
  ActionLogSummary,
  CostBreakdown,
} from '~/types/execution'
import { del, get, post, put } from './client'

// ============================================================================
// Trigger Management API
// ============================================================================

/**
 * 获取工作流的触发器列表
 */
export async function listTriggers(workflowId: string): Promise<WorkflowTrigger[]> {
  return get<WorkflowTrigger[]>(`/workflows/${workflowId}/triggers/`)
}

/**
 * 创建触发器
 */
export async function createTrigger(
  workflowId: string,
  data: WorkflowTriggerCreate,
): Promise<WorkflowTrigger> {
  return post<WorkflowTrigger>(`/workflows/${workflowId}/triggers/`, data)
}

/**
 * 更新触发器
 */
export async function updateTrigger(
  workflowId: string,
  triggerId: string,
  data: Partial<WorkflowTriggerCreate>,
): Promise<WorkflowTrigger> {
  return put<WorkflowTrigger>(`/workflows/${workflowId}/triggers/${triggerId}/`, data)
}

/**
 * 删除触发器
 */
export async function deleteTrigger(workflowId: string, triggerId: string): Promise<void> {
  return del(`/workflows/${workflowId}/triggers/${triggerId}/`)
}

// ============================================================================
// Manual Trigger API
// ============================================================================

/**
 * 手动触发工作流
 */
export async function executeWorkflow(
  workflowId: string,
  data: ManualTriggerRequest = {},
  debugMode: boolean = false,
): Promise<ManualTriggerResponse> {
  return post<ManualTriggerResponse>(`/workflows/${workflowId}/execute/`, {
    ...data,
    debug_mode: debugMode,
  })
}

/**
 * 重试失败/取消的执行（用原始触发数据重新执行）
 */
export async function retryExecution(
  executionId: string,
): Promise<{ execution_id: string, status: string, retry_from: string }> {
  return post<{ execution_id: string, status: string, retry_from: string }>(
    `/workflow-executions/${executionId}/retry/`,
  )
}

// ============================================================================
// CodingTask API
// ============================================================================

/**
 * 批准编码任务方案
 */
export async function approveCodingTaskPlan(taskId: string): Promise<{ status: string, message: string }> {
  return post<{ status: string, message: string }>(`/coding-tasks/${taskId}/approve_plan/`)
}

/**
 * 驳回编码任务方案
 */
export async function rejectCodingTaskPlan(
  taskId: string,
  feedback: string,
): Promise<{ status: string, message: string }> {
  return post<{ status: string, message: string }>(`/coding-tasks/${taskId}/reject_plan/`, { feedback })
}

/**
 * 批准编码任务代码
 */
export async function approveCodingTaskCode(taskId: string): Promise<{ status: string, message: string }> {
  return post<{ status: string, message: string }>(`/coding-tasks/${taskId}/approve_code/`)
}

/**
 * 驳回编码任务代码
 */
export async function rejectCodingTaskCode(
  taskId: string,
  feedback: string,
): Promise<{ status: string, message: string }> {
  return post<{ status: string, message: string }>(`/coding-tasks/${taskId}/reject_code/`, { feedback })
}

// ============================================================================
// LLM Models API
// ============================================================================

/**
 * LLM 模型信息
 */
export interface LLMModel {
  id: string
  object?: string
  created?: number
  owned_by?: string
}

/**
 * 查询可用的 LLM 模型列表（自定义 API）
 */
export async function queryLLMModels(
  baseUrl: string,
  apiKey?: string,
): Promise<{ models: LLMModel[], count: number }> {
  return post<{ models: LLMModel[], count: number }>('/workflows/llm/models/', {
    base_url: baseUrl,
    api_key: apiKey || '',
  })
}

/**
 * 查询系统配置的 LLM 模型列表
 */
export async function querySystemLLMModels(): Promise<{ models: LLMModel[], count: number }> {
  return post<{ models: LLMModel[], count: number }>('/workflows/llm/models/', {
    use_system: true,
  })
}

/**
 * 系统 LLM 配置信息
 */
export interface LLMSystemConfig {
  base_url: string
  model: string
  has_api_key: boolean
  source: 'system' | 'project'
}

/**
 * 获取系统 LLM 配置
 */
export async function getLLMSystemConfig(): Promise<LLMSystemConfig> {
  return get<LLMSystemConfig>('/workflows/llm/config/')
}

// ============================================================================
// Node Execution Action API (Manual Intervention)
// ============================================================================

/**
 * 跳过节点等待，继续执行工作流
 */
export async function skipNodeWait(
  executionId: string,
  nodeId: string,
): Promise<{ status: string, message: string }> {
  return post<{ status: string, message: string }>(
    `/workflow-executions/${executionId}/nodes/${nodeId}/skip-wait/`,
  )
}

/**
 * 手动触发节点唤醒，继续执行工作流
 */
export async function triggerNodeResume(
  executionId: string,
  nodeId: string,
): Promise<{ status: string, message: string }> {
  return post<{ status: string, message: string }>(
    `/workflow-executions/${executionId}/nodes/${nodeId}/trigger-resume/`,
  )
}

// ============================================================================
// InteractionLog API (Node Debug)
// ============================================================================

export interface InteractionLog {
  id: number
  session_id: string
  question_id: string
  question_text: string
  question_context: string
  code_snippet: string
  options: string[]
  answer_text: string
  answer_source: string
  asked_at: string
  answered_at: string | null
}

/**
 * 获取节点执行关联的交互记录
 */
export async function getNodeInteractions(nodeExecutionId: string): Promise<InteractionLog[]> {
  return get<InteractionLog[]>(`/containers/node-executions/${nodeExecutionId}/interactions/`)
}

/**
 * 提交交互回答
 */
export async function answerInteraction(
  interactionId: number,
  answer: string,
  answerSource: 'button' | 'text' = 'text',
): Promise<InteractionLog> {
  return post<InteractionLog>(`/containers/interactions/${interactionId}/answer/`, {
    answer,
    answer_source: answerSource,
  })
}

/**
 * 回答 AgentSession 的提问（AIAgentBaseNode 场景）
 */
export async function answerAgentSession(
  sessionId: string,
  answer: string,
): Promise<{ status: string, session_id: string }> {
  return post<{ status: string, session_id: string }>(`/containers/agent-sessions/${sessionId}/answer/`, {
    answer,
  })
}

// ============================================================================
// AI 执行透视 API
// ============================================================================

/**
 * 获取节点的 ReAct 步骤列表（ActionLog 摘要）
 */
export async function getReactSteps(nodeExecutionId: string): Promise<ActionLogSummary[]> {
  return get<ActionLogSummary[]>(`/node-executions/${nodeExecutionId}/react-steps/`)
}

/**
 * 获取 ActionLog 详情（含完整 payload）
 */
export async function getActionLogDetail(actionLogId: number): Promise<ActionLogDetail> {
  return get<ActionLogDetail>(`/action-logs/${actionLogId}/`)
}

/**
 * 获取执行的成本拆分数据
 */
export async function getCostBreakdown(executionId: string): Promise<CostBreakdown> {
  return get<CostBreakdown>(`/workflow-executions/${executionId}/cost-breakdown/`)
}

/**
 * 从失败节点继续执行（创建新的部分重执行实例）
 */
export async function resumeFromFailed(
  executionId: string,
  nodeId: string,
): Promise<{ execution_id: string, status: string, resumed_from: string }> {
  return post<{ execution_id: string, status: string, resumed_from: string }>(
    `/workflow-executions/${executionId}/resume-from-failed/`,
    { node_id: nodeId },
  )
}

/**
 * 检查执行的工作流定义是否在执行后发生变更
 */
export async function checkWorkflowChanged(
  executionId: string,
): Promise<{ changed: boolean }> {
  return get<{ changed: boolean }>(
    `/workflow-executions/${executionId}/check-definition-changed/`,
  )
}

/**
 * 预览从失败节点恢复的影响范围
 */
export interface ResumePreviewNode {
  id: string
  name: string
  status: string
}

export interface ResumePreviewResult {
  skip_nodes: ResumePreviewNode[]
  rerun_nodes: ResumePreviewNode[]
  total_skip: number
  total_rerun: number
}

export async function resumePreview(
  executionId: string,
  nodeId: string,
): Promise<ResumePreviewResult> {
  return get<ResumePreviewResult>(
    `/workflow-executions/${executionId}/resume-preview/?node_id=${nodeId}`,
  )
}

export default {
  // Triggers
  listTriggers,
  createTrigger,
  updateTrigger,
  deleteTrigger,
  // Execution
  executeWorkflow,
  retryExecution,
  // CodingTask
  approveCodingTaskPlan,
  rejectCodingTaskPlan,
  approveCodingTaskCode,
  rejectCodingTaskCode,
  // LLM Models
  queryLLMModels,
  getLLMSystemConfig,
  // Node Execution Actions
  skipNodeWait,
  triggerNodeResume,
  // Interactions
  getNodeInteractions,
  answerInteraction,
  answerAgentSession,
  // AI 执行透视
  getReactSteps,
  getActionLogDetail,
  getCostBreakdown,
  // : 从失败节点继续
  resumeFromFailed,
  checkWorkflowChanged,
  // : 恢复预览
  resumePreview,
}
