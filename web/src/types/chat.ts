/** 对话系统类型定义 */
import type { ConversationStatus } from '~/composables/useConversationFrozen'
/**
 * 对话状态（与后端 Conversation.Status TextChoices 同步）。
 *
 * 真源在 useConversationFrozen.ts，本文件 re-export 让 chat 类型层保持单一入口。
 * UAT 第 3 项 hotfix：Conversation DTO 引用此类型。
 */
export type { ConversationStatus } from '~/composables/useConversationFrozen'
/** 对话 */
export interface Conversation {
 id: string
 project_id: string
 title: string
 model: string
 /** UAT 第 3 项 hotfix：对话 pin 状态（frozen 判据真源） */
 status: ConversationStatus
 /** UAT 第 3 项 hotfix：对话级 pin 的 ProviderCredential UUID（null=未 pin） */
 provider_credential_id: string | null
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
export interface StreamTimelineThinkingItem {
 id: string
 kind: 'thinking'
 text: string
}
export interface StreamTimelineNarrationItem {
 id: string
 kind: 'narration'
 text: string
}
export interface StreamTimelineToolItem {
 id: string
 kind: 'tool'
 name: string
 input: Record<string, unknown>
 result?: string
 status: 'running' | 'done'
}
export type StreamTimelineItem
 = | StreamTimelineThinkingItem
 | StreamTimelineNarrationItem
 | StreamTimelineToolItem
export interface ConversationRuntime {
 conversation_id: string
 active: boolean
 orchestration_run_id?: string
 phase?: string
 task_progress?: { completed: number, total: number } | null
 mode?: 'chat' | 'deep_analysis' | 'coding' | null
 coding_session?: CodingSessionRuntime | null
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
 type: 'text_delta' | 'tool_use_start' | 'tool_use_result' | 'message_complete' | 'title_generated' | 'error' | 'thinking' | 'budget_warning' | 'deep_analysis_progress' | 'phase_transition' | 'task_progress' | 'doc_summary' | 'doc_error' | 'coding_progress' | 'coding_complete' | 'coding_failed' | 'awaiting_commit_confirm' | 'awaiting_pr_review' | 'conflict_check'
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
 // doc_summary
 doc_title?: string
 word_count?: number
 preview?: string
 truncated?: boolean
 truncated_length?: number
 // doc_error
 error_type?: 'permission_denied' | 'not_found' | 'not_configured' | 'unknown'
 // coding_progress (Phase)
 coding_session_id?: string
 steps?: Array<{ name: string, status: 'pending' | 'running' | 'done' }>
 modified_files_count?: number
 // coding_complete (Phase)
 pr_url?: string
 branch_name?: string
 // coding_failed — 复用 message 字段
 // awaiting_commit_confirm (Phase)
 suggested_commit_message?: string
 confirmation_step?: string
 // awaiting_pr_review (Phase)
 suggested_pr_title?: string
 suggested_pr_description?: string
 target_branch?: string
 branch_url?: string
 // conflict_check (Phase)
 has_conflicts?: boolean
 conflicting_files?: string
 behind_by?: number
 suggestion?: string
 // coding_progress enhanced (Phase/210)
 modified_files?: Array<{ path: string, change_type: string }>
 recent_tool_calls?: Array<{ tool: string, summary: string }>
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
// ============================================================================
// 导出到飞书文档 (Phase)
// ============================================================================
/** 导出到飞书文档请求 */
export interface ExportToFeishuRequest {
 message_ids: string
 title: string
 folder_token?: string
}
/** 导出到飞书文档成功响应 */
export interface ExportToFeishuResponse {
 document_id: string
 url: string
 title: string
 exported_at?: string
}
/** 导出到飞书文档错误响应 */
export interface ExportToFeishuError {
 error: string
 error_type: 'permission_denied' | 'not_configured' | 'api_error'
}
// ============================================================================
// 编码会话 (Phase)
// ============================================================================
/** CodingSession API 响应 */
export interface CodingSessionResponse {
 id: string
 status: 'draft' | 'confirmed' | 'running' | 'completed' | 'failed'
 tech_plan: string
 affected_files: Array<{ path: string, change_type: string }>
 revision_count: number
 repository_id: string
 branch_name: string
 pr_url: string
 error_message: string
 confirmation_step: string
 suggested_commit_message: string
 suggested_pr_title: string
 suggested_pr_description: string
 target_branch: string
 branch_url: string
 conflict_check_result: {
 has_conflicts?: boolean
 conflicting_files?: string
 behind_by?: number
 suggestion?: string
 } | null
 diff_summary: {
 files?: Array<{ path: string, additions: number, deletions: number, change_type: string }>
 total_additions?: number
 total_deletions?: number
 truncated?: boolean
 } | null
 created_at: string
 updated_at: string
}
/** ConversationRuntime 中的 CodingSession 快照 */
export interface CodingSessionRuntime {
 id: string
 status: string
 tech_plan?: string
 affected_files?: Array<{ path: string, change_type: string }>
 branch_name?: string
 pr_url?: string
 error_message?: string
 confirmation_step?: string
 suggested_commit_message?: string
 suggested_pr_title?: string
 suggested_pr_description?: string
 target_branch?: string
 branch_url?: string
 conflict_check_result?: Record<string, unknown> | null
 diff_summary?: Record<string, unknown> | null
}
/** Store 中的编码进度数据 */
export interface CodingProgressData {
 sessionId: string
 steps: Array<{ name: string, status: 'pending' | 'running' | 'done' }>
 modifiedFilesCount: number
 modifiedFiles?: Array<{ path: string, change_type: string }>
 recentToolCalls?: Array<{ tool: string, summary: string }>
}
/** Store 中的编码结果数据 */
export interface CodingResultData {
 sessionId: string
 prUrl: string
 branchName: string
 modifiedFilesCount: number
 branchUrl: string
}
/** Store 中的编码错误数据 */
export interface CodingErrorData {
 sessionId: string
 errorMessage: string
}
