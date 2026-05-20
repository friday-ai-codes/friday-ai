/**
 * Phase：ClarificationCard 数据契约。
 *
 * 与后端 `agents/tools/clarification.py` 工具产出 + `chat/serializers.py`
 * `ClarificationAnswerSerializer` 完全对齐。
 */
export interface ClarificationOption {
 id: string
 label: string
 hint?: string
 /**
 * 用户选中后能 inferred 的结构化状态（如 selected_repository_ids /
 * task_category）；客户端透传不解析，由后端 endpoint 在 resume graph 时
 * merge 到 result_metadata.inferred_intent。
 */
 implies?: Record<string, unknown>
}
export type ClarificationStatus = 'pending' | 'answered'
export interface ClarificationAnswer {
 selected_option_id?: string
 freeform_text?: string
 answered_at: string
}
export interface ClarificationPayload {
 clarification_id: string
 question: string
 options: ClarificationOption
 allow_freeform: boolean
 status: ClarificationStatus
 answer?: ClarificationAnswer
 /**
 * 触发本次协商的 assistant message id —— 前端按此排序把 ClarificationCard
 * 紧跟在触发它的 assistant 消息之后渲染。
 */
 triggering_message_id?: string
}
export interface ClarificationAnswerRequest {
 selected_option_id?: string
 freeform_text?: string
}
export interface ClarificationAnswerResponse {
 clarification_id: string
 selected_option_id: string
 freeform_text: string
 answered_at: string
 inferred_state: Record<string, unknown>
}
