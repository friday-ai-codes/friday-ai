/**
 * Workflow API - 工作流相关接口
 */
import type {
 CodingTask,
 ExecutionContext,
 ManualTriggerRequest,
 ManualTriggerResponse,
 WorkflowTrigger,
 WorkflowTriggerCreate,
} from '~/types'
import { del, get, patch, post, put } from './client'
// ============================================================================
// Node Schema API
// ============================================================================
/**
 * 节点 Schema 定义
 */
export interface NodeSchema {
 node_type: string
 display_name: string
 description: string
 category: string
 icon: string
 config_schema: Record<string, any>
 inputs: Array<{ name: string, label: string, port_type: string }>
 outputs: Array<{ name: string, label: string, port_type: string }>
}
/**
 * 获取所有节点 Schema
 */
export async function getNodeSchemas(category?: string): Promise<NodeSchema> {
 const params = category ? { category }: undefined
 return get<NodeSchema>('/workflows/nodes/schemas/', params)
}
// ============================================================================
// Trigger Management API
// ============================================================================
/**
 * 获取工作流的触发器列表
 */
export async function listTriggers(workflowId: string): Promise<WorkflowTrigger> {
 return get<WorkflowTrigger>(`/workflows/workflows/${workflowId}/triggers/`)
}
/**
 * 创建触发器
 */
export async function createTrigger(
 workflowId: string,
 data: WorkflowTriggerCreate,
): Promise<WorkflowTrigger> {
 return post<WorkflowTrigger>(`/workflows/workflows/${workflowId}/triggers/`, data)
}
/**
 * 更新触发器
 */
export async function updateTrigger(
 workflowId: string,
 triggerId: string,
 data: Partial<WorkflowTriggerCreate>,
): Promise<WorkflowTrigger> {
 return put<WorkflowTrigger>(`/workflows/workflows/${workflowId}/triggers/${triggerId}/`, data)
}
/**
 * 删除触发器
 */
export async function deleteTrigger(workflowId: string, triggerId: string): Promise<void> {
 return del(`/workflows/workflows/${workflowId}/triggers/${triggerId}/`)
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
): Promise<ManualTriggerResponse> {
 return post<ManualTriggerResponse>(`/workflows/workflows/${workflowId}/execute/`, data)
}
// ============================================================================
// Execution Context API
// ============================================================================
/**
 * 获取执行上下文快照
 */
export async function getExecutionContext(executionId: string): Promise<ExecutionContext> {
 return get<ExecutionContext>(`/workflows/workflow-executions/${executionId}/context/`)
}
// ============================================================================
// CodingTask API
// ============================================================================
/**
 * 获取执行的编码任务列表
 */
export async function listCodingTasks(executionId: string): Promise<CodingTask> {
 return get<CodingTask>(`/workflows/workflow-executions/${executionId}/coding-tasks/`)
}
/**
 * 获取编码任务详情
 */
export async function getCodingTask(taskId: string): Promise<CodingTask> {
 return get<CodingTask>(`/workflows/coding-tasks/${taskId}/`)
}
/**
 * 更新编码任务
 */
export async function updateCodingTask(
 taskId: string,
 data: Partial<CodingTask>,
): Promise<CodingTask> {
 return patch<CodingTask>(`/workflows/coding-tasks/${taskId}/`, data)
}
/**
 * 批准编码任务方案
 */
export async function approveCodingTaskPlan(taskId: string): Promise<{ status: string, message: string }> {
 return post<{ status: string, message: string }>(`/workflows/coding-tasks/${taskId}/approve_plan/`)
}
/**
 * 驳回编码任务方案
 */
export async function rejectCodingTaskPlan(
 taskId: string,
 feedback: string,
): Promise<{ status: string, message: string }> {
 return post<{ status: string, message: string }>(`/workflows/coding-tasks/${taskId}/reject_plan/`, { feedback })
}
/**
 * 批准编码任务代码
 */
export async function approveCodingTaskCode(taskId: string): Promise<{ status: string, message: string }> {
 return post<{ status: string, message: string }>(`/workflows/coding-tasks/${taskId}/approve_code/`)
}
/**
 * 驳回编码任务代码
 */
export async function rejectCodingTaskCode(
 taskId: string,
 feedback: string,
): Promise<{ status: string, message: string }> {
 return post<{ status: string, message: string }>(`/workflows/coding-tasks/${taskId}/reject_code/`, { feedback })
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
): Promise<{ models: LLMModel, count: number }> {
 return post<{ models: LLMModel, count: number }>('/workflows/llm/models/', {
 base_url: baseUrl,
 api_key: apiKey || '',
 })
}
/**
 * 查询系统配置的 LLM 模型列表
 */
export async function querySystemLLMModels: Promise<{ models: LLMModel, count: number }> {
 return post<{ models: LLMModel, count: number }>('/workflows/llm/models/', {
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
export async function getLLMSystemConfig: Promise<LLMSystemConfig> {
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
 `/workflows/workflow-executions/${executionId}/nodes/${nodeId}/skip-wait/`,
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
 `/workflows/workflow-executions/${executionId}/nodes/${nodeId}/trigger-resume/`,
 )
}
export default {
 // Node Schema
 getNodeSchemas,
 // Triggers
 listTriggers,
 createTrigger,
 updateTrigger,
 deleteTrigger,
 // Execution
 executeWorkflow,
 getExecutionContext,
 // CodingTask
 listCodingTasks,
 getCodingTask,
 updateCodingTask,
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
}
