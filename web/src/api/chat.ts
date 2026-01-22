/**
 * Chat API 服务 - LLM 对话能力
 */
import { get, post } from './client'
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
 project_id?: number
 api_key?: string
 base_url?: string
}
/** 对话请求 */
export interface ChatCompletionRequest {
 model: string
 messages: ChatMessage
 source?: ConfigSource
 project_id?: number
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
 project_id: params.project_id,
 api_key: params.api_key,
 base_url: params.base_url,
 }
 const response = await get<ModelsResponse>('/chat/models', queryParams)
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
 return post<ChatCompletionResponse>('/chat/completions', request)
}
/**
 * 快速测试 - 使用系统配置发送测试消息
 */
export async function testSystemConfig(
 model: string,
 message: string = '你基于什么模型？',
 apiKey?: string,
 baseUrl?: string,
): Promise<ChatCompletionResponse> {
 return chatCompletion({
 model,
 messages: [{ role: 'user', content: message }],
 source: 'system',
 api_key: apiKey,
 base_url: baseUrl,
 })
}
/**
 * 快速测试 - 使用项目配置发送测试消息
 */
export async function testProjectConfig(
 projectId: number,
 model: string,
 message: string = '你基于什么模型？',
 apiKey?: string,
 baseUrl?: string,
): Promise<ChatCompletionResponse> {
 return chatCompletion({
 model,
 messages: [{ role: 'user', content: message }],
 source: 'project',
 project_id: projectId,
 api_key: apiKey,
 base_url: baseUrl,
 })
}
// 默认导出
export default {
 getModels,
 chatCompletion,
 testSystemConfig,
 testProjectConfig,
}
