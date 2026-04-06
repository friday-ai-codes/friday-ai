/** 对话系统类型定义 */
/** 对话 */
export interface Conversation {
 id: string
 project_id: string
 title: string
 model: string
 created_at: string
 updated_at: string
}
/** 对话消息 */
export interface ConversationMessage {
 id: string
 role: 'user' | 'assistant' | 'system' | 'tool'
 content: string
 tool_calls?: ToolCallData
 tool_call_id?: string
 metadata?: Record<string, unknown>
 created_at: string
}
/** 工具调用数据 */
export interface ToolCallData {
 id: string
 name: string
 input: Record<string, unknown>
 result?: string
 status?: 'running' | 'done'
}
export interface DeepAnalysisLog {
 type: string
 content: string
 ts: number
}
export interface ConversationRuntime {
 conversation_id: string
 active: boolean
 orchestration_run_id?: string
 phase?: string
 task_progress?: { completed: number, total: number } | null
 mode?: 'chat' | 'deep_analysis' | null
 status?: string | null
 session_id?: string
 task_description?: string
 progress_message?: string
 progress_percent?: number | null
 logs?: DeepAnalysisLog
}
/** 对话详情（含消息列表） */
export interface ConversationDetail extends Conversation {
 messages: ConversationMessage
}
/** 创建对话参数 */
export interface CreateConversationParams {
 project_id: string
 title?: string
 model?: string
}
/**
 * SSE 事件
 *
 * type 联合类型与后端 server/agents/core/events.py 的 ALL_EVENT_TYPES 一一对应。
 * 新增事件类型时，两端必须同步更新，并在 test_sse_event_contract.py 中添加验证。
 */
export interface SSEEvent {
 type: 'text_delta' | 'tool_use_start' | 'tool_use_result' | 'message_complete' | 'title_generated' | 'error' | 'thinking' | 'budget_warning' | 'deep_analysis_progress' | 'phase_transition' | 'task_progress'
 message_id?: string
 run_id?: string
 // text_delta
 text?: string
 // tool_use_start
 tool_name?: string
 tool_call_id?: string
 input?: Record<string, unknown>
 // tool_use_result
 result?: string
 // thinking
 thinking?: string
 // message_complete
 final_answer?: string
 cost_usd?: number
 usage?: {
 prompt_tokens?: number
 completion_tokens?: number
 total_tokens?: number
 input_tokens?: number
 output_tokens?: number
 }
 model?: string
 status?: 'completed' | 'interrupted' | 'budget_exceeded'
 // title_generated
 title?: string
 // error
 message?: string
 // budget_warning
 budget_usage_percent?: number
 // deep_analysis_progress
 session_id?: string
 log_type?: string
 content?: string
 // phase_transition
 phase?: string
 blocking_task_count?: number
 // task_progress
 completed_count?: number
 total_count?: number
}
/** 用户角色 */
export type ChatRole = 'developer' | 'pm' | 'designer' | 'qa' | 'general'
/** 角色选项 */
export const ROLE_OPTIONS: Array<{ value: ChatRole, label: string }> = [
 { value: 'developer', label: '开发者' },
 { value: 'pm', label: '产品经理' },
 { value: 'designer', label: '设计师' },
 { value: 'qa', label: '测试工程师' },
 { value: 'general', label: '通用' },
]
