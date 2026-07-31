/** 对话系统类型定义 */

import type { ConversationStatus } from '~/composables/useConversationFrozen'
import type { ClarificationPayload } from '~/types/clarification'
import type { RoutingDecisionData } from '~/types/routing'

/**
 * 对话状态（与后端 Conversation.Status TextChoices 同步）。
 *
 * 真源在 useConversationFrozen.ts，本文件 re-export 让 chat 类型层保持单一入口。
 * Conversation DTO 引用此类型。
 */
export type { ConversationStatus } from '~/composables/useConversationFrozen'

/** 会话可见性（项目作战室 P2）。 */
export type ConversationVisibility = 'personal' | 'shared'

/** 会话贡献者简要（创建者；前端渲染头像首字母 + 名字）。 */
export interface ConversationContributor {
  id: string
  username: string
  display_name: string
}

/** 对话 */
export interface Conversation {
  id: string
  /** null = 未绑定空间的通用对话 */
  space_id: string | null
  title: string
  model: string
  /** 对话 pin 状态（frozen 判据真源） */
  status: ConversationStatus
  /** 对话级 pin 的 ProviderCredential UUID（null=未 pin） */
  provider_credential_id: string | null
  /** 绑定项目（项目作战室会话；null=通用会话）。 */
  bound_project_id?: string | null
  /** 可见性（personal=仅创建者 / shared=项目共享只读）。 */
  visibility?: ConversationVisibility
  /** 创建者简要（项目作战室 P2，列表/详情 annotate）。 */
  created_by?: ConversationContributor | null
  /** 单会话执行时长（毫秒；所有 OrchestrationRun 运行时长之和，详情返回）。 */
  duration_ms?: number
  /** 是否已归档（归档会话从默认列表隐藏） */
  is_archived?: boolean
  /** 该会话的方案编排是否产出了 SDD spec（列表 annotate，缺省 false） */
  has_sdd_spec?: boolean
  /** 该会话是否产生过技术方案 CodingPlan（列表 annotate，缺省 false） */
  has_coding_plan?: boolean
  /** 该会话是否进行过容器编码 CodingSession（列表 annotate，缺省 false） */
  has_coding_session?: boolean
  created_at: string
  updated_at: string
}

/** 对话消息 */
export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  tool_calls?: ToolCallData[]
  tool_call_id?: string
  metadata?: Record<string, unknown>
  /**
   * Anthropic content blocks 风格的有序 parts 数组
   * （与 `server/chat/parts.py` 的 Pydantic 同源）。后端 BE-04 已暴露 read-only
   * 字段；历史 legacy 消息为空 → 前端 `hydrateLegacyMessage` 合成（D5）。
   */
  parts?: MessagePart[]
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

// ============================================================================
// MessagePart 联合类型 + 新 SSE 事件类型
//
// 与 `server/chat/parts.py` 的 Pydantic discriminated union 字面同源；前端
// `streamingParts` ref + `displayParts` computed 共用，按顺序渲染：
//   text → MarkdownText / tool_use → ToolCallCard / thinking → ThinkingStep
//
// 设计契约见 / / schema versioning。
// ============================================================================

export interface MessagePartBase {
  /** 客户端稳定 :key（uuid 或 server 给） */
  id: string
  /** 0-based 渲染顺序；回放时按 index 排序兜底 */
  index: number
}

export interface TextPart extends MessagePartBase {
  type: 'text'
  text: string
  state: 'streaming' | 'done'
}

export interface ToolUsePart extends MessagePartBase {
  type: 'tool_use'
  tool_call_id: string
  name: string
  input: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  /** 始终 string；与 SSE tool_use_result.result / chat_runner._tool_result_to_content 对齐 */
  result?: string | null
  /** 同 LLM response 内多 tool_call 共享，用于横向 chip 流 */
  batch_id?: string | null
}

export interface ThinkingPart extends MessagePartBase {
  type: 'thinking'
  text: string
  state: 'streaming' | 'done'
}

export interface ImagePart extends MessagePartBase {
  type: 'image'
  mime_type: string
  size_bytes: number
  width?: number | null
  height?: number | null
  detail: 'auto' | 'low' | 'high'
  storage_ref?: string
  source_url?: string
  alt_text?: string
}

export type MessagePart = TextPart | ToolUsePart | ThinkingPart | ImagePart

/** part_started / part_completed 事件中的 part 字段 payload（streaming 期间的 partial shape）。 */
export interface PartStartedPayload {
  id: string
  index: number
  type: 'text' | 'tool_use' | 'thinking'
  text?: string
  state?: 'streaming' | 'done'
  tool_call_id?: string
  name?: string
  input?: Record<string, unknown>
  status?: 'running' | 'done' | 'error'
  result?: string | null
  batch_id?: string | null
}

export interface PartCompletedPayload {
  index: number
  id?: string
  type?: 'text' | 'tool_use' | 'thinking'
  state?: 'streaming' | 'done'
  status?: 'running' | 'done' | 'error'
  result?: string | null
  tool_call_id?: string
}

export interface DeepAnalysisLog {
  type: string
  content: string
  ts: number
}

/**
 * 单个深度分析子会话（subagent）的运行态快照。
 *
 * 一次助手回复里可能并行触发多个深度分析，每个子代理拥有自己独立的
 * 工具调用 / 思考日志。前端据此按会话渲染横向 swiper。
 */
export interface DeepAnalysisSession {
  session_id: string
  task_description?: string
  status?: string
  progress_message?: string
  progress_percent?: number | null
  logs: DeepAnalysisLog[]
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
  /** 后端 chat_runner 发的 batch_id；同一 LLM turn 的多个 tool 同值 */
  batch_id?: string
}

export type StreamTimelineItem
  = | StreamTimelineThinkingItem
    | StreamTimelineNarrationItem
    | StreamTimelineToolItem

/**
 * 流式快照——后端 `_StreamingSnapshot` 节流写入 OrchestrationRun.metadata 的镜像。
 *
 * SSE 单向无状态，刷新页面时前端内存里的流式渲染（text / thinking / tools / timeline）
 * 全部丢失。runtime polling 拉到这份快照后 `applyRuntimeSnapshot` 把它还原成
 * streaming state，前端无需重建——结构跟前端 store 的字段一一对应。
 *
 * 仅在 `active=true` 时返回；完成态前端走 `hydrateMessages` 拉 final assistant
 * message，再读 snapshot 会导致 bubble 重影。
 */
export interface ConversationRuntimeStreamingSnapshot {
  pending_text: string
  thinking: string
  tool_calls: Array<{
    id: string
    name: string
    input: Record<string, unknown>
    result?: string | null
    status: 'running' | 'done'
    batch_id?: string | null
  }>
  narrations: string[]
  timeline: StreamTimelineItem[]
}

export interface ConversationRuntime {
  conversation_id: string
  active: boolean
  orchestration_run_id?: string
  phase?: string
  task_progress?: { completed: number, total: number } | null
  mode?: 'chat' | 'deep_analysis' | 'coding' | null
  coding_session?: CodingSessionRuntime | null
  /** ：最近 CodingPlan + 每仓 session 状态 */
  coding_plan?: CodingPlanRuntime | null
  status?: string | null
  session_id?: string
  task_description?: string
  progress_message?: string
  progress_percent?: number | null
  logs?: DeepAnalysisLog[]
  /** 多个深度分析子会话各自独立的日志（按会话渲染 swiper） */
  deep_sessions?: DeepAnalysisSession[]
  deep_analysis_status?: string | null
  deep_analysis_error?: string | null
  streaming_snapshot?: ConversationRuntimeStreamingSnapshot | null
  /** 待回复的澄清（waiting_clarification 时返回，供刷新恢复 ClarificationCard） */
  pending_clarification?: {
    clarification_id: string
    question: string
    options: Array<{ id: string, label: string, hint?: string, implies?: Record<string, unknown> }>
    allow_freeform?: boolean
  } | null
  /**
   * 待回复的 plan 结构化澄清轮（91-04 runtime 新键，供 91-05 渲染多题澄清卡）。
   * 与单题 `pending_clarification` 物理隔离；`questions` 为空/无轮时为 null。
   */
  pending_plan_clarification?: {
    clarification_id: string
    round_no: number
    questions: Array<{
      question_id: string
      question: string
      qtype: 'single' | 'multi'
      options: string[]
      recommended?: string | string[]
      selected?: string | string[]
      freeform_text?: string
    }>
  } | null
}

/** 对话详情（含消息列表） */
export interface ConversationDetail extends Conversation {
  messages: ConversationMessage[]
  /** 已回复的协商卡（刷新回显 ClarificationCard 的已回复态） */
  clarifications?: ClarificationPayload[]
  /** 最新跨仓路由决策 trace（刷新 hydrate routingStore，回显 RelevanceBadge） */
  routing_trace?: RoutingDecisionData | null
}

/** 编辑历史 user message 前创建新分支 conversation 的请求体 */
export interface ForkConversationRequest {
  content: string
}

/** 创建对话参数 */
export interface CreateConversationParams {
  /** null = 创建不绑定空间的通用对话 */
  space_id: string | null
  title?: string
  model?: string
  /** 绑定项目（项目作战室会话；非空则自动加载项目上下文）。 */
  bound_project_id?: string | null
  /** 可见性（personal 默认 / shared 共享，shared 需 bound_project）。 */
  visibility?: ConversationVisibility
}

/**
 * SSE 事件
 *
 * type 联合类型与后端 server/agents/core/events.py 的 ALL_EVENT_TYPES 一一对应。
 * 新增事件类型时，两端必须同步更新，并在 test_sse_event_contract.py 中添加验证。
 */
export interface SSEEvent {
  type: 'text_delta' | 'tool_use_start' | 'tool_use_result' | 'message_complete' | 'title_generated' | 'error' | 'thinking' | 'budget_warning' | 'deep_analysis_progress' | 'phase_transition' | 'task_progress' | 'doc_summary' | 'doc_error' | 'coding_progress' | 'coding_complete' | 'coding_failed' | 'awaiting_commit_confirm' | 'awaiting_pr_review' | 'conflict_check' | 'part_started' | 'part_delta' | 'part_completed'
  message_id?: string
  run_id?: string
  // part_* 事件 payload（双轨期与旧事件共存）
  /** part_started / part_completed 携带的 part 内容；part_delta 不带（用 delta_type + text） */
  part?: PartStartedPayload | PartCompletedPayload
  /** part_*：所属 part 的 0-based index */
  index?: number
  /** part_delta：增量类型，目前仅 'text_append' */
  delta_type?: 'text_append'
  // text_delta / part_delta 共用 text 字段
  /** message_complete：新版冗余整份 parts snapshot */
  parts?: MessagePart[]
  // text_delta
  text?: string
  // tool_use_start
  tool_name?: string
  tool_call_id?: string
  input?: Record<string, unknown>
  /**
   * 同一个 LLM response 内的多个 tool_call 共享 batch_id（后端 chat_runner
   * 在 tool_calls 循环开始时生成 UUID），用于前端将"语义同批"的工具调用
   * 渲染为横向 chip 流。单工具调用时为空字符串 / undefined，前端退化到
   * 旧的"连续同名"分组规则。
   */
  batch_id?: string
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
  /**
   * 284 round 2 Fix C-1：waiting_clarification 阶段直接在 phase_transition 事件
   *  携带 ClarificationCard 完整 payload，避免依赖 tool_use_result 兜底（编排层
   *  自动构造的 clarification 不会触发 tool_use_result）。详见
   *  server/orchestration/graph.py:742 + stores/chat.ts phase_transition handler。
   */
  clarification_id?: string
  question?: string
  options?: Array<{ id: string, label: string, hint?: string, implies?: Record<string, unknown> }>
  allow_freeform?: boolean
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
  // coding_progress
  coding_session_id?: string
  steps?: Array<{ name: string, status: 'pending' | 'running' | 'done' }>
  modified_files_count?: number
  // coding_complete
  pr_url?: string
  branch_name?: string
  // coding_failed — 复用 message 字段
  // awaiting_commit_confirm
  suggested_commit_message?: string
  confirmation_step?: string
  // awaiting_pr_review
  suggested_pr_title?: string
  suggested_pr_description?: string
  target_branch?: string
  branch_url?: string
  // conflict_check
  has_conflicts?: boolean
  conflicting_files?: string[]
  behind_by?: number
  suggestion?: string
  // coding_progress enhanced (/210)
  // ：支持 file_path / path 两种 schema 兼容期共存
  modified_files?: Array<{ file_path?: string, path?: string, change_type: string }>
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
// 导出到飞书文档
// ============================================================================

/** 导出到飞书文档请求 */
export interface ExportToFeishuRequest {
  message_ids: string[]
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
// ：CodingPlan 导出到飞书文档
// ============================================================================

/** 导出 CodingPlan 到飞书文档请求 */
export interface ExportCodingPlanToFeishuRequest {
  folder_token?: string
  title?: string
}

/** 导出 CodingPlan 到飞书文档成功响应 */
export interface ExportCodingPlanToFeishuResponse {
  doc_token: string
  doc_url: string
  title: string
  exported_at?: string
}

// ============================================================================
// 编码会话
// ============================================================================

/** CodingSession API 响应 */
export interface CodingSessionResponse {
  id: string
  /** ：关联的 CodingPlan UUID（null 表示历史数据未迁移） */
  coding_plan_id?: string | null
  status: 'draft' | 'confirmed' | 'running' | 'completed' | 'failed'
  tech_plan: string
  affected_files: Array<{ file_path: string, change_type: string, path?: string }>
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
    conflicting_files?: string[]
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

/** ：CodingPlan API 响应（独立领域模型） */
export interface CodingPlanResponse {
  id: string
  conversation_id: string
  title: string
  tech_plan: string
  affected_files: Array<{ file_path: string, change_type: string }>
  feishu_doc_token: string
  feishu_doc_url: string
  created_at: string
  updated_at: string
}

/** ConversationRuntime 中的 CodingSession 快照 */
export interface CodingSessionRuntime {
  id: string
  status: string
  tech_plan?: string
  affected_files?: Array<{ file_path: string, change_type: string, path?: string }>
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
  /**
   * polling 路径携带的编码中间产出：runner 通过 progress callback
   * 写入 SubAgentSession.last_output['coding_progress']，conversation_service
   * 序列化时透传到 runtime.coding_session.coding_progress。前端 store 在
   * applyRuntimeSnapshot 里把它转成 CodingProgressData 喂 CodingProgressCard。
   * runtime restore：补 v18.1 切 polling 时遗漏的前端接线。
   */
  coding_progress?: {
    modified_files: Array<{ file_path?: string, path?: string, change_type: string }>
    recent_tool_calls: Array<{ tool: string, summary: string }>
    updated_at: string
  } | null
}

/** Store 中的编码进度数据 */
export interface CodingProgressData {
  sessionId: string
  steps: Array<{ name: string, status: 'pending' | 'running' | 'done' }>
  modifiedFilesCount: number
  modifiedFiles?: Array<{ file_path?: string, path?: string, change_type: string }>
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

// ============================================================================
// / / / ：多仓 fan-out 类型
// ============================================================================

/** RepoMultiSelector 可选项（FAN-03） */
export interface RepoSelectableItem {
  id: string
  name: string
  description?: string
  /** 推荐预填用 —— 0..1，越高越推荐 */
  relevance_score?: number
}

/** FAN-02 批量创建 endpoint 响应（镜像后端 schema） */
export interface CodingSessionsBatchCreateResponse {
  created: Array<{
    session_id: string
    repository_id: string
    branch_name: string
  }>
  failed: Array<{
    repository_id: string
    error: string
  }>
}

/** ：CodingSession 6 态枚举（与后端 CodingSession.Status 同步） */
export type CodingSessionStatus
  = | 'draft'
    | 'confirmed'
    | 'running'
    | 'awaiting_confirmation'
    | 'completed'
    | 'failed'

/**
 * ：单条 CodingSession 实时状态（镜像后端
 * ConversationRuntimeCodingPlanSessionSerializer）
 */
export interface CodingPlanSessionRuntime {
  session_id: string
  repository_id: string
  repository_name: string
  branch_name: string
  status: CodingSessionStatus
  pr_url: string
  commit_sha: string
  error_message: string
}

/**
 * 编码方案来源标志（RELY-01）。与后端 CodingPlanProvenance TextChoices 字面对齐。
 */
export type CodingPlanProvenance = 'orchestrated' | 'draft'

/**
 * ：对话内最近 CodingPlan + 每仓 session 状态。
 *
 * 扩展：可选 `feishu_doc_token` / `feishu_doc_url`，
 * 来自 backend runtime serializer 或本地 store patch（导出成功后立即可见）。
 *
 * 与后端 `ConversationRuntimeCodingPlanSerializer` 手工对齐（无代码生成），
 * 漏一侧 TS 不会报错，改动任一侧都要同步这里。
 */
export interface CodingPlanRuntime {
  plan_id: string
  title: string
  sessions: CodingPlanSessionRuntime[]
  feishu_doc_token?: string
  feishu_doc_url?: string
  // ---- [新增 109] ----
  /**
   * 来源标志；缺失 / 未知取值 → 保守视为未经调研。
   *
   * 类型故意保留 `| string`：后端未来新增取值时前端不该编译失败，而应走保守
   * 分支（未知取值视为未经调研）。这让「未知取值按保守处理」成为类型层默认，
   * 而不是依赖每个消费点自觉。
   */
  provenance?: CodingPlanProvenance | string | null
  /** 方案正文。SPINE-02 后前端取正文的权威来源（tool input 仅作历史兜底）。 */
  tech_plan?: string
  affected_files?: Array<{ file_path?: string, path?: string, change_type: string }>
  recommended_repository_ids?: string[]
  /** 投影来源留痕；前端**不渲染**，仅用于排障与测试断言。 */
  source_artifact_version_id?: string | null
}

/** 投影端点响应（惰性投影：点「进入编码」时触发）。 */
export interface ProjectPlanToCodingResponse {
  coding_plan_id: string
  /** false = 幂等命中既有投影（同一 ArtifactVersion 重复点击）。 */
  created: boolean
  title: string
  tech_plan: string
  affected_files: Array<{ file_path: string, change_type: string }>
  recommended_repository_ids: string[]
  /**
   * 推荐仓库的 `{id, name}`（按 plan 所属 space 过滤）。
   *
   * 🔴 不能只靠 `recommended_repository_ids`：`RepoMultiSelector` 要用名字渲染每一
   * 行，只给 id 会让交棒后的选仓面变成「未找到匹配的仓库」——用户既看不到 AI 推荐
   * 了哪几个仓，也无法勾选或取消。id 与本列表可能不等长（跨 space 的 id 只在前者）。
   */
  recommended_repositories: RepoSelectableItem[]
  provenance: CodingPlanProvenance
}
