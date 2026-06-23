/**
 * useSSEStream — 通过 fetch POST 消费 SSE 流
 *
 * 后端 ChatStreamView 是 POST 端点，EventSource 仅支持 GET，
 * 因此使用 fetch + ReadableStream + TextDecoder 手动解析 SSE。
 * 认证通过 HTTP-only Cookie 自动处理。
 */
import type { MessagePart, SSEEvent } from '~/types/chat'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

// 仅保留为最后一次 run_id 的弱引用（向后兼容旧导入 / 测试 mock）。
// ：不再用作并发流的运行标识 —— 多个会话流并发时会互相覆盖，
// 真正的「本流 run_id」改由 connectSSE 的 options.onRunId 回调按流透出，
// 调用方（sendMessage）以闭包内局部 ref 持有，互不污染。
let lastRunId: string | null = null

/**
 * 获取最后一次 SSE 流的 run_id。
 *
 * @deprecated 并发流下该值会被后启动的流覆盖。新代码应使用
 * `connectSSE(..., { onRunId })` 按流接收 run_id，避免跨流污染。
 */
export function getCurrentRunId(): string | null {
  return lastRunId
}

/**
 * 连接 SSE 流并消费事件
 *
 * `options.onRunId`：本流首次见到 `run_id` 时回调一次，调用方据此持有
 * **本流独立** 的 run_id（用于断线恢复比对），不与其他并发流共享。
 */
export async function connectSSE(
  conversationId: string,
  content: string,
  role: string,
  onEvent: (event: SSEEvent) => void,
  signal: AbortSignal,
  options?: { forceDeepAnalysis?: boolean, feishuDocId?: string, branch?: string, inputParts?: MessagePart[], onRunId?: (runId: string) => void },
): Promise<void> {
  // 本流独立的 run_id（闭包局部，绝不跨并发流共享）
  let streamRunId: string | null = null

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
            // run_id 追踪：按流记录本流 run_id（局部），首见时回调透出给调用方；
            // 同时更新 lastRunId 仅为兼容旧 getCurrentRunId（不用于并发判定）。
            if (data.run_id && data.run_id !== streamRunId) {
              streamRunId = data.run_id
              lastRunId = data.run_id
              options?.onRunId?.(data.run_id)
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
