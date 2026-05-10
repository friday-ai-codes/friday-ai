/**
 * Chat API 服务 - LLM 对话能力
 */
import type { CodingSessionResponse, Conversation, ConversationDetail, ConversationRuntime, CreateConversationParams, ExportToFeishuRequest, ExportToFeishuResponse } from '~/types/chat'
import { del, get, patch, post } from './client'
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
 models: Model
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
 messages: ChatMessage
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
// ============================================================================
// 模型排序
// ============================================================================
/**
 * 获取模型的排序优先级
 * 优先级越小越靠前
 */
function getModelPriority(modelId: string): number {
 const id = modelId.toLowerCase
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
function sortModels(models: Model): Model {
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
// ============================================================================
// Conversation CRUD API (Phase)
// ============================================================================
/**
 * 获取对话列表
 */
export async function listConversations: Promise<Conversation> {
 return get<Conversation>('/chat/conversations/')
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
 */
export async function getConversationRuntime(id: string): Promise<ConversationRuntime> {
 return get<ConversationRuntime>(`/chat/conversations/${id}/runtime/`)
}
/** PATCH 请求体（与后端 ConversationPatchSerializer 对齐） */
export interface PatchConversationParams {
 provider_credential_id?: string | null
 model?: string
 title?: string
}
/**
 * 部分更新对话（pin Provider 凭证 / 切模型 / 改标题）
 *
 * UAT 第 3 项 hotfix：原 Phase Plan 注释承诺的
 * 「Plan/08 接 store action」从未交付 → 此次补齐。后端 endpoint 已在 Phase
 * 完成（ConversationDetailView.patch）。
 *
 * 失败语义：
 * - 400 + {code: "conversation_frozen"} → frozen 态拒绝改 provider_credential_id / model
 * - 400 + {code/detail: ...} → FK 校验失败（凭证不存在 / 已禁用）
 * - 客户端错误由 client.ts 抛 ApiError；调用方应 try/catch 并降级
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
export async function getPushPublicKey: Promise<PushPublicKeyResponse> {
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
// 导出到飞书文档 (Phase)
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
// ============================================================================
// 编码会话 (Phase)
// ============================================================================
/**
 * 确认编码方案 — 触发 Runner 编码执行
 */
export async function confirmCodingSession(sessionId: string): Promise<CodingSessionResponse> {
 return post<CodingSessionResponse>(`/chat/coding-sessions/${sessionId}/confirm/`)
}
/**
 * 获取编码会话详情
 */
export async function getCodingSession(sessionId: string): Promise<CodingSessionResponse> {
 return get<CodingSessionResponse>(`/chat/coding-sessions/${sessionId}/`)
}
/**
 * 确认编码方案（附带可选的分支名覆盖）— Phase 扩展
 */
export async function confirmCodingSessionWithBranch(
 sessionId: string,
 branchName?: string,
): Promise<CodingSessionResponse> {
 const body = branchName ? { branch_name: branchName }: {}
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
 * 获取 Commit 确认数据（GET）
 */
export async function getCommitConfirmData(sessionId: string) {
 return get<{
 suggested_commit_message: string
 affected_files: Array<{ path: string, change_type: string }>
 }>(`/chat/coding-sessions/${sessionId}/commit-confirm/`)
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
 * 获取 PR 确认数据（GET）
 */
export async function getPRConfirmData(sessionId: string) {
 return get<{
 suggested_pr_title: string
 suggested_pr_description: string
 target_branch: string
 branch_url: string
 }>(`/chat/coding-sessions/${sessionId}/pr-confirm/`)
}
/**
 * 获取冲突检查结果
 */
export async function getConflictCheck(sessionId: string) {
 return get<{
 has_conflicts?: boolean
 conflicting_files?: string
 behind_by?: number
 suggestion?: string
 }>(`/chat/coding-sessions/${sessionId}/conflict-check/`)
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
// ============================================================================
// 默认导出
// ============================================================================
export default {
 getModels,
 chatCompletion,
 listConversations,
 createConversation,
 getConversationDetail,
 getConversationRuntime,
 patchConversation,
 deleteConversation,
 interruptConversation,
 getPushPublicKey,
 savePushSubscription,
 removePushSubscription,
 exportToFeishu,
 confirmCodingSession,
 getCodingSession,
 confirmCodingSessionWithBranch,
 confirmCommit,
 getCommitConfirmData,
 confirmPR,
 getPRConfirmData,
 getConflictCheck,
 getDiffSummary,
}
