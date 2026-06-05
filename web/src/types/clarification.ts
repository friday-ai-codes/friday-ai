/**
 * ：ClarificationCard 数据契约。
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
  options: ClarificationOption[]
  allow_freeform: boolean
  status: ClarificationStatus
  answer?: ClarificationAnswer
  /**
   * 触发本次协商的 assistant message id —— 前端按此排序把 ClarificationCard
   * 紧跟在触发它的 assistant 消息之后渲染。
   */
  triggering_message_id?: string
  /**
   * UAT 2026-05-27 hotfix（284 round 2）：协商卡片归属的 conversation id。
   *
   * 仅在 store 内由 `upsertClarification` 写入（SSE 处理时取当前 chat 上下文）。
   * `undefined` 兼容旧路径 — `ChatMessageArea` 过滤时遇到 undefined 一律渲染
   * （等同于未携带 conv 维度的 legacy payload）。
   *
   * 根因：在不带此字段前，`pendingClarifications` 是按 clarification_id 唯一的
   * 全局 Map，切换 conversation 时残留 + 其他 conv 的 SSE tool_use_result 异步
   * 流入都会污染当前 conv 视图，导致跨会话串单（见 284-UAT.md round 2 Gap）。
   */
  conversation_id?: string
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
