/**
 * useSSEStream — 通过 fetch POST 消费 SSE 流
 *
 * 后端 ChatStreamView 是 POST 端点，EventSource 仅支持 GET，
 * 因此使用 fetch + ReadableStream + TextDecoder 手动解析 SSE。
 */
import type { SSEEvent } from '~/types/chat'
import { getAccessToken } from '~/api/client'
const API_BASE = import.meta.env.VITE_API_BASE || '/api'
/**
 * 连接 SSE 流并消费事件
 *
 * @param conversationId 对话 ID
 * @param content 用户消息内容
 * @param role 用户角色
 * @param onEvent 事件回调
 * @param signal AbortSignal 用于取消连接
 */
export async function connectSSE(
 conversationId: string,
 content: string,
 role: string,
 onEvent: (event: SSEEvent) => void,
 signal: AbortSignal,
): Promise<void> {
 const token = getAccessToken
 const headers: Record<string, string> = {
 'Content-Type': 'application/json',
 }
 if (token) {
 headers.Authorization = `Bearer ${token}`
 }
 const response = await fetch(
 `${API_BASE}/chat/conversations/${conversationId}/stream/`,
 {
 method: 'POST',
 headers,
 body: JSON.stringify({ content, role }),
 signal,
 },
 )
 if (!response.ok) {
 const errorText = await response.text.catch( => '请求失败')
 throw new Error(`SSE 连接失败 (${response.status}): ${errorText}`)
 }
 if (!response.body) {
 throw new Error('响应体为空')
 }
 const reader = response.body.getReader
 const decoder = new TextDecoder
 let buffer = ''
 try {
 while (true) {
 const { done, value } = await reader.read
 if (done) break
 buffer += decoder.decode(value, { stream: true })
 const lines = buffer.split('\n')
 // 保留最后一个可能不完整的行
 buffer = lines.pop || ''
 for (const line of lines) {
 const trimmed = line.trim
 // 跳过空行和注释行（keepalive）
 if (!trimmed || trimmed.startsWith(':')) continue
 // 解析 SSE data 行
 if (trimmed.startsWith('data: ')) {
 try {
 const data: SSEEvent = JSON.parse(trimmed.slice(6))
 onEvent(data)
 }
 catch {
 // 忽略无法解析的行
 }
 }
 }
 }
 }
 finally {
 reader.releaseLock
 }
}
