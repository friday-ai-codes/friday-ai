/**
 * Task status mapper utilities.
 *
 * Maps WorkflowExecution states to legacy Task statuses for UI compatibility.
 */
export interface WorkflowExecution {
 id: string
 status: 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'
 node_executions: NodeExecution
 context: Record<string, unknown>
 input_data: Record<string, unknown>
 workflow: {
 id: string
 name: string
 project_id: string
 }
}
export interface NodeExecution {
 id: string
 node: {
 id: string
 node_type: string
 name: string
 }
 status: string
 output_data: Record<string, unknown>
}
export type TaskStatus
 = | 'pending'
 | 'planning'
 | 'plan_review'
 | 'executing'
 | 'code_review'
 | 'merged'
 | 'failed'
/**
 * Map WorkflowExecution status to legacy Task status for UI display.
 */
export function mapWorkflowToTaskStatus(execution: WorkflowExecution): TaskStatus {
 if (execution.status === 'pending')
 return 'pending'
 if (execution.status === 'completed')
 return 'merged'
 if (execution.status === 'failed' || execution.status === 'cancelled')
 return 'failed'
 // For running status, determine based on current active node
 const activeNode = execution.node_executions.find(
 n => n.status === 'running' || n.status === 'waiting_approval',
 )
 if (!activeNode)
 return 'pending'
 const nodeType = activeNode.node.node_type
 switch (nodeType) {
 case 'generate_plan':
 return 'planning'
 case 'human_approval': {
 // Check if this is plan approval or code approval
 const codeNode = execution.node_executions.find(
 n => n.node.node_type === 'code_implement' && n.status === 'completed',
 )
 return codeNode ? 'code_review': 'plan_review'
 }
 case 'code_implement':
 return 'executing'
 case 'create_pr':
 return 'executing'
 default:
 return 'pending'
 }
}
/**
 * Status display configuration for UI components.
 */
export const STATUS_CONFIG: Record<
 TaskStatus,
 { label: string, color: string, bgColor: string, icon: string }
> = {
 pending: {
 label: '待处理',
 color: 'text-gray-600',
 bgColor: 'bg-gray-100',
 icon: 'lucide:clock',
 },
 planning: {
 label: '规划中',
 color: 'text-indigo-600',
 bgColor: 'bg-indigo-100',
 icon: 'lucide:brain',
 },
 plan_review: {
 label: '方案评审',
 color: 'text-orange-600',
 bgColor: 'bg-orange-100',
 icon: 'lucide:eye',
 },
 executing: {
 label: '执行中',
 color: 'text-blue-600',
 bgColor: 'bg-blue-100',
 icon: 'lucide:code',
 },
 code_review: {
 label: '代码评审',
 color: 'text-orange-600',
 bgColor: 'bg-orange-100',
 icon: 'lucide:git-pull-request',
 },
 merged: {
 label: '已完成',
 color: 'text-green-600',
 bgColor: 'bg-green-100',
 icon: 'lucide:check-circle',
 },
 failed: {
 label: '失败',
 color: 'text-red-600',
 bgColor: 'bg-red-100',
 icon: 'lucide:x-circle',
 },
}
/**
 * Get status configuration for a given status.
 */
export function getStatusConfig(status: TaskStatus) {
 return STATUS_CONFIG[status] || STATUS_CONFIG.pending
}
