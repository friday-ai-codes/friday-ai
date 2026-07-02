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
  /** 推荐选项（至多一个）：UI 展示 Friday 品牌标识 +「（推荐）」并默认选中。 */
  recommended?: boolean
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
   * 触发本次协商的消息 id（后端 ConversationIntentTrace 记录的是 user message id，
   * SSE 路径可能是 assistant message id）—— ChatMessageArea 按此把已答卡片内联锚定
   * 在消息流中触发位置，而不是堆在最底部。
   */
  triggering_message_id?: string
  /**
   * 兜底锚点：upsert 时记录「当时最后一条已落库消息」的 id。triggering_message_id
   * 缺失/未命中时按此锚定，保证答复后新消息在卡片下方继续、卡片不跳到最底部。
   */
  anchor_message_id?: string
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

// ============================================================================
// Plan 结构化澄清（多题 + 多选）—— 与上方 chat 单题澄清并存，物理隔离不串。
//
// 对齐 Phase 90 结构化模型 + 91-04 runtime `pending_plan_clarification` /
// 专路由 `POST /chat/conversations/{id}/plan-clarification/answer/`。
// runtime questions[] 字段：question_id/question/qtype/options/recommended/
// selected/freeform_text。
// ============================================================================

/** plan 澄清单题类型：single=单选 / multi=多选。 */
export type PlanClarificationQType = 'single' | 'multi'

export interface PlanClarificationQuestion {
  question_id: string
  question: string
  qtype: PlanClarificationQType
  options: string[]
  /** 推荐项（⭐ 默认选中）：single 取一个、multi 可多个。runtime 可能给 str 或 str[]。 */
  recommended?: string | string[]
  /** 后端已回填的选择（已答轮回显）。 */
  selected?: string | string[]
  freeform_text?: string
}

export interface PlanClarificationPayload {
  clarification_id: string
  round_no: number
  questions: PlanClarificationQuestion[]
  /**
   * 卡片归属的 conversation id——store 写入时绑定（mirror ClarificationPayload
   * 的防污染范式），`ChatMessageArea` 按当前会话过滤防跨会话串渲染。
   */
  conversation_id?: string
  status?: ClarificationStatus
  /** 兜底锚点（同 ClarificationPayload.anchor_message_id）：内联锚定用。 */
  anchor_message_id?: string
}

/** 单题答复项：single→selected 为 str；multi→selected 为 string[]。 */
export interface PlanClarificationAnswerItem {
  question_id: string
  selected: string | string[]
  freeform_text?: string
}

export interface PlanClarificationAnswerRequest {
  answers: PlanClarificationAnswerItem[]
}
