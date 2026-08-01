/**
 * Chat API 服务 - LLM 对话能力
 */

import type { CodingSessionResponse, CodingSessionsBatchCreateResponse, Conversation, ConversationDetail, ConversationRuntime, CreateConversationParams, ExportCodingPlanToFeishuRequest, ExportCodingPlanToFeishuResponse, ExportToFeishuRequest, ExportToFeishuResponse, ForkConversationRequest, ImagePart, ProjectPlanToCodingResponse } from '~/types/chat'
import type { ClarificationAnswerRequest, ClarificationAnswerResponse, PlanClarificationAnswerRequest } from '~/types/clarification'
import { del, get, patch, post, upload } from './client'

// ============================================================================
// 类型定义
// ============================================================================

/** 聊天消息 */
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system'
  content: string
}

/** 模型信息 */
export interface Model {
  id: string
  name: string
  created: number | null
}

/** 模型列表响应 */
export interface ModelsResponse {
  models: Model[]
}

/** 配置来源 */
export type ConfigSource = 'system' | 'project'

/** 获取模型列表参数 */
export interface GetModelsParams {
  source?: ConfigSource
  space_id?: number
  api_key?: string
  base_url?: string
}

/** 对话请求 */
export interface ChatCompletionRequest {
  model: string
  messages: ChatMessage[]
  source?: ConfigSource
  space_id?: number
  api_key?: string
  base_url?: string
  max_tokens?: number
}

/** 对话响应 */
export interface ChatCompletionResponse {
  content: string
  model: string
  usage: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  } | null
}

export interface PushPublicKeyResponse {
  public_key: string
  subject: string
}

export interface PushSubscriptionPayload {
  endpoint: string
  keys: {
    p256dh: string
    auth: string
  }
  user_agent?: string
}

export interface ChatImageUploadResponse {
  part: ImagePart
}

// ============================================================================
// 模型排序
// ============================================================================

/**
 * 获取模型的排序优先级
 * 优先级越小越靠前
 */
function getModelPriority(modelId: string): number {
  const id = modelId.toLowerCase()

  // 1. claude-opus-4-5-thinking (最优先)
  if (id.includes('claude') && id.includes('opus') && id.includes('4') && id.includes('5') && id.includes('thinking')) {
    return 10
  }

  // 2. claude-opus* (其他 opus)
  if (id.includes('claude') && id.includes('opus')) {
    return 20
  }

  // 3. claude-sonnet-4-5-thinking
  if (id.includes('claude') && id.includes('sonnet') && id.includes('4') && id.includes('5') && id.includes('thinking')) {
    return 30
  }

  // 4. claude-sonnet* (其他 sonnet)
  if (id.includes('claude') && id.includes('sonnet')) {
    return 40
  }

  // 5. 其他 claude 模型
  if (id.includes('claude')) {
    return 50
  }

  // 6. gemini-claude-opus
  if (id.includes('gemini') && id.includes('claude') && id.includes('opus')) {
    return 60
  }

  // 7. gemini-claude-sonnet
  if (id.includes('gemini') && id.includes('claude') && id.includes('sonnet')) {
    return 70
  }

  // 8. 其他 gemini 模型
  if (id.includes('gemini')) {
    return 80
  }

  // 9. 其他模型（字典序）
  return 100
}

/**
 * 对模型列表进行排序
 */
function sortModels(models: Model[]): Model[] {
  return [...models].sort((a, b) => {
    const priorityA = getModelPriority(a.id)
    const priorityB = getModelPriority(b.id)

    // 优先级不同时，按优先级排序
    if (priorityA !== priorityB) {
      return priorityA - priorityB
    }

    // 优先级相同时，按字典序排序
    return a.id.localeCompare(b.id)
  })
}

// ============================================================================
// API 方法
// ============================================================================

/**
 * 获取可用模型列表（已排序）
 */
export async function getModels(params: GetModelsParams = {}): Promise<ModelsResponse> {
  const queryParams: Record<string, string | number | undefined> = {
    source: params.source,
    space_id: params.space_id,
    api_key: params.api_key,
    base_url: params.base_url,
  }
  const response = await get<ModelsResponse>('/chat/models/', queryParams)

  // 对模型列表进行排序
  return {
    ...response,
    models: sortModels(response.models),
  }
}

/**
 * 发送对话请求
 */
export async function chatCompletion(request: ChatCompletionRequest): Promise<ChatCompletionResponse> {
  return post<ChatCompletionResponse>('/chat/completions/', request)
}

/**
 * 上传 Web Chat 图片并返回可直接放入 input_parts 的 ImagePart。
 */
export async function uploadChatImage(file: File): Promise<ImagePart> {
  const formData = new FormData()
  formData.append('image', file)
  const response = await upload<ChatImageUploadResponse>('/chat/images/', formData)
  return response.part
}

// ============================================================================
// Conversation CRUD API
// ============================================================================

/** 飞书导出可用性探测响应 */
export interface FeishuExportAvailability {
  available: boolean
  reason: string | null
}

/**
 * 探测「导出到飞书」是否可用（空间配置了文件夹 + 凭证）。
 * 前端据此隐藏导出入口，避免点击后才报「未配置」。
 */
export async function getFeishuExportAvailability(
  spaceId?: string | null,
): Promise<FeishuExportAvailability> {
  return get<FeishuExportAvailability>(
    '/chat/feishu-export-availability/',
    spaceId ? { space_id: spaceId } : {},
  )
}

/** 对话列表查询参数 */
export interface ListConversationsParams {
  /** 关键词：匹配标题或消息内容（后端 q）。 */
  q?: string
  /** 最多返回条数（默认后端 50，最大 200）。 */
  limit?: number
  /** 仅返回已归档会话（「查看已归档」入口）。 */
  archived?: boolean
  /** 项目作战室：按绑定项目过滤（项目页大盘会话栏只列本项目会话）。 */
  bound_project?: string
}

/**
 * 获取对话列表
 *
 * 支持服务端关键词搜索（标题 + 消息内容）与 top N 限制；archived 仅取已归档。
 */
export async function listConversations(
  params: ListConversationsParams = {},
): Promise<Conversation[]> {
  const query: Record<string, string | number> = {}
  if (params.q && params.q.trim())
    query.q = params.q.trim()
  if (params.limit != null)
    query.limit = params.limit
  if (params.archived)
    query.archived = 1
  if (params.bound_project)
    query.bound_project = params.bound_project
  return get<Conversation[]>('/chat/conversations/', query)
}

/**
 * 克隆会话为「我的项目个人会话」（项目作战室 P2 clone 贡献）。
 *
 * 共享会话对项目成员只读；成员要发言即 clone 一份归属自己的副本（personal，
 * 继承 bound_project），在副本里自由对话。返回新会话 id。
 */
export async function cloneConversation(id: string): Promise<{ conversation_id: string }> {
  return post<{ conversation_id: string }>(`/chat/conversations/${id}/clone/`, {})
}

/**
 * 创建对话
 */
export async function createConversation(params: CreateConversationParams): Promise<Conversation> {
  return post<Conversation>('/chat/conversations/', params)
}

/**
 * 获取对话详情（含消息列表）
 */
export async function getConversationDetail(id: string): Promise<ConversationDetail> {
  return get<ConversationDetail>(`/chat/conversations/${id}/`)
}

/**
 * 获取对话运行态（用于刷新后恢复执行状态）
 *
 * @param orchestrationSeen 收敛令牌（110-MN-02）：调用方已完整持有的编排会话 id。
 *   命中且该会话已终态时，服务端只回权威字段、不重发早已凝固的事件流与容器日志
 *   （响应里 `orchestration.converged === true`）。**刷新补齐不要带它**——那条路径
 *   本来就是来拿全量的。
 */
export async function getConversationRuntime(
  id: string,
  orchestrationSeen = '',
): Promise<ConversationRuntime> {
  const qs = orchestrationSeen
    ? `?orchestration_seen=${encodeURIComponent(orchestrationSeen)}`
    : ''
  return get<ConversationRuntime>(`/chat/conversations/${id}/runtime/${qs}`)
}

/**
 * 编辑历史 user message 前创建新 conversation 分支。
 */
export async function forkConversationForMessage(
  conversationId: string,
  messageId: string,
  params: ForkConversationRequest,
): Promise<ConversationDetail> {
  return post<ConversationDetail>(
    `/chat/conversations/${conversationId}/messages/${messageId}/fork/`,
    params,
  )
}

/** PATCH 请求体（与后端 ConversationPatchSerializer 对齐） */
export interface PatchConversationParams {
  provider_credential_id?: string | null
  model?: string
  title?: string
  /** 会话内切换空间；null 切回不绑定空间的通用对话 */
  space_id?: string | null
  /** 绑定/解绑项目（项目作战室）。 */
  bound_project_id?: string | null
  /** 可见性互转（个人↔共享，仅创建者；共享需 bound_project）。 */
  visibility?: 'personal' | 'shared'
  /** 归档开关：true 归档（从默认列表隐藏）/ false 取消归档 */
  is_archived?: boolean
}

/**
 * 部分更新对话（pin Provider 凭证 / 切模型 / 改标题）
 *
 * 原 注释承诺的
 * 「/08 接 store action」从未交付 → 此次补齐。后端 endpoint 已在
 * 完成（ConversationDetailView.patch）。
 *
 * 失败语义：
 *   - 400 + {code: "conversation_frozen"} → frozen 态拒绝改 provider_credential_id / model
 *   - 400 + {code/detail: ...} → FK 校验失败（凭证不存在 / 已禁用）
 *   - 客户端错误由 client.ts 抛 ApiError；调用方应 try/catch 并降级
 */
export async function patchConversation(
  id: string,
  params: PatchConversationParams,
): Promise<Conversation> {
  return patch<Conversation>(`/chat/conversations/${id}/`, params)
}

/**
 * 删除对话
 */
export async function deleteConversation(id: string): Promise<void> {
  return del(`/chat/conversations/${id}/`)
}

/**
 * 中断对话（通知后端停止 AI 回复生成）
 */
export async function interruptConversation(id: string): Promise<void> {
  await post(`/chat/conversations/${id}/interrupt/`)
}

/**
 * 获取 Web Push VAPID 公钥
 */
export async function getPushPublicKey(): Promise<PushPublicKeyResponse> {
  return get<PushPublicKeyResponse>('/chat/push/public-key/')
}

/**
 * 保存当前浏览器的 Push 订阅
 */
export async function savePushSubscription(payload: PushSubscriptionPayload): Promise<void> {
  await post('/chat/push/subscriptions/', payload)
}

/**
 * 取消当前浏览器的 Push 订阅
 */
export async function removePushSubscription(endpoint: string): Promise<void> {
  await post('/chat/push/subscriptions/unsubscribe/', { endpoint })
}

// ============================================================================
// 导出到飞书文档
// ============================================================================

/**
 * 导出对话消息到飞书文档
 */
export async function exportToFeishu(
  conversationId: string,
  data: ExportToFeishuRequest,
): Promise<ExportToFeishuResponse> {
  return post<ExportToFeishuResponse>(
    `/chat/conversations/${conversationId}/export-to-feishu/`,
    data,
  )
}

/**
 * ：导出 CodingPlan 到飞书文档。
 *
 * 与 conversation 路径独立的 endpoint，数据源换成 CodingPlan + 多仓 sessions
 * （由后端 `coding_plan_exporter` 拼接成单篇 markdown）。
 */
export async function exportCodingPlanToFeishu(
  codingPlanId: string,
  data: ExportCodingPlanToFeishuRequest,
): Promise<ExportCodingPlanToFeishuResponse> {
  return post<ExportCodingPlanToFeishuResponse>(
    `/chat/coding-plans/${codingPlanId}/export-to-feishu/`,
    data,
  )
}

// ============================================================================
// 编码会话
// ============================================================================

/**
 * 确认编码方案 — 触发 Runner 编码执行
 */
export async function confirmCodingSession(sessionId: string): Promise<CodingSessionResponse> {
  return post<CodingSessionResponse>(`/chat/coding-sessions/${sessionId}/confirm/`)
}

/**
 * 确认编码方案（附带可选的分支名覆盖）— 扩展
 */
export async function confirmCodingSessionWithBranch(
  sessionId: string,
  branchName?: string,
  targetBranch?: string,
): Promise<CodingSessionResponse> {
  const body: Record<string, string> = {}
  if (branchName)
    body.branch_name = branchName
  if (targetBranch)
    body.target_branch = targetBranch
  return post<CodingSessionResponse>(`/chat/coding-sessions/${sessionId}/confirm/`, body)
}

/**
 * 确认 Commit Message
 */
export async function confirmCommit(
  sessionId: string,
  commitMessage: string,
): Promise<CodingSessionResponse> {
  return post<CodingSessionResponse>(
    `/chat/coding-sessions/${sessionId}/commit-confirm/`,
    { commit_message: commitMessage },
  )
}

/**
 * 确认/跳过 PR
 */
export async function confirmPR(
  sessionId: string,
  data: { title: string, description: string, target_branch: string } | { skip: true },
): Promise<CodingSessionResponse> {
  return post<CodingSessionResponse>(
    `/chat/coding-sessions/${sessionId}/pr-confirm/`,
    data,
  )
}

/**
 * 获取 Diff 摘要
 */
export async function getDiffSummary(sessionId: string) {
  return get<{
    files?: Array<{ path: string, additions: number, deletions: number, change_type: string }>
    total_additions?: number
    total_deletions?: number
    truncated?: boolean
  }>(`/chat/coding-sessions/${sessionId}/diff-summary/`)
}

/**
 * ：在已存在的 CodingPlan 上批量创建 N 个 CodingSession（DRAFT 态）。
 * POST /api/chat/coding-plans/{plan_id}/sessions/
 */
export async function createSessionsForPlan(
  planId: string,
  payload: {
    repository_ids: string[]
    branch_template?: string
    target_branch?: string
    /**
     * 109-08（RELY-01）：草稿方案送编码的用户显式确认。
     *
     * 🔴 该值代表一次**用户签名**，只能由用户在确认弹层里勾选后产生。调用方不传
     * 时**不得注入 false** —— 「不发字段」让后端日志里「带了 ack」等价于「用户
     * 确实确认过」；本层也绝不给它设默认值、不缓存、不记忆。
     */
    acknowledge_unresearched?: boolean
  },
): Promise<CodingSessionsBatchCreateResponse> {
  return post<CodingSessionsBatchCreateResponse>(
    `/chat/coding-plans/${planId}/sessions/`,
    payload,
  )
}

/**
 * 109-04：把编排产出的方案版本惰性投影为 chat CodingPlan。
 * POST /api/chat/coding-plans/from-artifact-version/
 *
 * 幂等：同一 ArtifactVersion 重复投影只产一行，响应 `created=false` 表示命中既有投影。
 * 前端只传 `artifact_version_id`，归属判定与字段组装全在服务端（109-03 owner gate）。
 */
export async function projectArtifactVersionToCodingPlan(
  artifactVersionId: string,
): Promise<ProjectPlanToCodingResponse> {
  return post<ProjectPlanToCodingResponse>(
    '/chat/coding-plans/from-artifact-version/',
    { artifact_version_id: artifactVersionId },
  )
}

/**
 * ：提交协商答复。
 * POST /api/chat/clarifications/{clarification_id}/answer/
 *
 * 后端 endpoint 完成 trace + Message 双写 + 后台 graph.ainvoke(Command(resume=...))，
 * 前端只需等 SSE 后续事件渲染 graph 输出。
 */
export async function postClarificationAnswer(
  clarificationId: string,
  payload: ClarificationAnswerRequest,
): Promise<ClarificationAnswerResponse> {
  return post<ClarificationAnswerResponse>(
    `/chat/clarifications/${clarificationId}/answer/`,
    payload,
  )
}

/**
 * ：提交 plan 结构化澄清答复（多题 + 多选）。
 * POST /api/chat/conversations/{conversation_id}/plan-clarification/answer/
 *
 * 对接 91-04 会话端专属路由（与 chat 单题 `postClarificationAnswer` 物理隔离）：
 * owner gate + question_id 归属校验后经同源 helper 写 delivery + 续推 PlanSession。
 * 前端只组装 UI 选择 `answers:[{question_id,selected,freeform_text}]`，越界/越权
 * 由服务端把关；提交后等 runtime polling 拿续推产出。
 */
export async function postPlanClarificationAnswer(
  conversationId: string,
  payload: PlanClarificationAnswerRequest,
): Promise<{ status?: string }> {
  return post<{ status?: string }>(
    `/chat/conversations/${conversationId}/plan-clarification/answer/`,
    payload,
  )
}

/** 跳过澄清的响应（按 conversation 维度，不依赖 clarification_id）。 */
export interface ClarificationSkipResponse {
  status: 'skipped' | 'no_pending'
  clarification_id?: string | null
  answered_at?: string
}

/**
 * 跳过当前等待中的澄清提问。
 * POST /api/chat/conversations/{conversation_id}/clarification/skip/
 *
 * 兜底场景：澄清卡片未能渲染导致 run 卡在 waiting_clarification。后端按
 * conversation 定位等待中的 run，注入「跳过」指令后台 resume graph，让 LLM
 * 基于现有信息直接作答。前端等 runtime polling 拿后续输出。
 */
export async function skipClarification(
  conversationId: string,
): Promise<ClarificationSkipResponse> {
  return post<ClarificationSkipResponse>(
    `/chat/conversations/${conversationId}/clarification/skip/`,
    {},
  )
}

// ============================================================================
// 默认导出
// ============================================================================

export default {
  getModels,
  chatCompletion,
  uploadChatImage,
  listConversations,
  createConversation,
  cloneConversation,
  getConversationDetail,
  getConversationRuntime,
  patchConversation,
  deleteConversation,
  interruptConversation,
  getPushPublicKey,
  savePushSubscription,
  removePushSubscription,
  exportToFeishu,
  exportCodingPlanToFeishu,
  confirmCodingSession,
  confirmCodingSessionWithBranch,
  createSessionsForPlan,
  projectArtifactVersionToCodingPlan,
  confirmCommit,
  confirmPR,
  getDiffSummary,
  postClarificationAnswer,
  postPlanClarificationAnswer,
  skipClarification,
}
