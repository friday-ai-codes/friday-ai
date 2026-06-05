/**
 * useSSEStream — 通过 fetch POST 消费 SSE 流
 *
 * 后端 ChatStreamView 是 POST 端点，EventSource 仅支持 GET，
 * 因此使用 fetch + ReadableStream + TextDecoder 手动解析 SSE。
 * 认证通过 HTTP-only Cookie 自动处理。
 */
import type { MessagePart, SSEEvent } from '~/types/chat'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

let currentRunId: string | null = null

/**
 * 获取当前 SSE 流的 run_id，用于断线恢复时比对
 */
export function getCurrentRunId(): string | null {
  return currentRunId
}

/**
 * 连接 SSE 流并消费事件
 */
export async function connectSSE(
  conversationId: string,
  content: string,
  role: string,
  onEvent: (event: SSEEvent) => void,
  signal: AbortSignal,
  options?: { forceDeepAnalysis?: boolean, feishuDocId?: string, branch?: string, inputParts?: MessagePart[] },
): Promise<void> {
  currentRunId = null

  const body: Record<string, unknown> = { content, role }
  if (options?.forceDeepAnalysis)
    body.force_deep_analysis = true
  if (options?.feishuDocId)
    body.feishu_doc_id = options.feishuDocId
  if (options?.branch)
    body.branch = options.branch
  if (options?.inputParts && options.inputParts.length > 0)
    body.input_parts = options.inputParts

  const response = await fetch(
    `${API_BASE}/chat/conversations/${conversationId}/stream/`,
    {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal,
    },
  )

  if (!response.ok) {
    const errorText = await response.text().catch(() => '请求失败')
    throw new Error(`SSE 连接失败 (${response.status}): ${errorText}`)
  }

  if (!response.body) {
    throw new Error('响应体为空')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done)
        break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || trimmed.startsWith(':'))
          continue
        if (trimmed.startsWith('data: ')) {
          try {
            const data: SSEEvent = JSON.parse(trimmed.slice(6))
            if (!data.type) {
              console.warn('[SSE] 收到缺少 type 字段的事件，已跳过:', data)
              continue
            }
            // run_id 追踪：检测新的运行实例，防止跨 run 状态污染
            if (data.run_id && data.run_id !== currentRunId) {
              currentRunId = data.run_id
            }
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
    reader.releaseLock()
  }
}
