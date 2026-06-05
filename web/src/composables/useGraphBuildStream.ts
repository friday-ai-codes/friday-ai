/**
 * useGraphBuildStream — 通过 fetch + ReadableStream 消费图谱构建进度 SSE 流
 *
 * 后端端点：GET /api/repositories/{id}/codegraph/stream/
 * Content-Type: text/event-stream
 *
 * 帧形如（-02 后端契约）：
 *   {"type": "progress",
 *    "ts": "...",
 *    "graph": { status, stage, files_processed, files_total, percent,
 *               current_file, started_at, edge_count_so_far,
 *               error_message }}
 *
 *   {"type": "done", "reason": "idle" | "max_ticks" | "repo_deleted"}
 *
 * 与 useIndexProgressStream 平行：1:1 复刻 fetch + ReadableStream + Bearer
 * + AbortController 模式；仅替换端点 URL + 事件 payload 类型。流断开后由
 * 调用方（卡片层）通过 polling GET /api/repositories/<id>/ 兜底
 * （CONTEXT Grey Area 4：不引入 EventSource 重连，独立端点解耦演进）。
 */
import type { GraphPayload } from '~/api/codegraph'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export type GraphBuildStreamEvent
  = | {
    type: 'progress'
    ts: string
    graph: GraphPayload
  }
  | { type: 'done', reason: string }

export interface ConnectGraphStreamOptions {
  /** 收到一帧事件 */
  onEvent: (event: GraphBuildStreamEvent) => void
  /** 流中断 / 网络错误 — 调用方决定是否降级 polling */
  onError?: (err: Error) => void
}

/**
 * 连接图谱构建进度 SSE 流
 *
 * @returns AbortController — 调用方决定何时取消（组件卸载或终态收到后）
 */
export function connectGraphProgressStream(
  repositoryId: string,
  options: ConnectGraphStreamOptions,
): AbortController {
  const controller = new AbortController()
  void runStream(repositoryId, options, controller.signal)
  return controller
}

async function runStream(
  repositoryId: string,
  options: ConnectGraphStreamOptions,
  signal: AbortSignal,
): Promise<void> {
  try {
    const accessToken = localStorage.getItem('access_token') ?? ''
    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
    }
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`
    }
    const response = await fetch(
      `${API_BASE}/repositories/${repositoryId}/codegraph/stream/`,
      {
        method: 'GET',
        headers,
        signal,
      },
    )

    if (!response.ok) {
      throw new Error(`SSE 连接失败 (${response.status})`)
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
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || trimmed.startsWith(':'))
            continue
          if (trimmed.startsWith('data: ')) {
            try {
              const payload = JSON.parse(trimmed.slice(6)) as GraphBuildStreamEvent
              if (!payload.type)
                continue
              options.onEvent(payload)
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
  catch (err) {
    if ((err as Error).name === 'AbortError')
      return
    // 与 useIndexProgressStream 一致：静默失败会让上层卡死，必须在 console 留痕
    console.error('[useGraphBuildStream] 连接失败:', err)
    options.onError?.(err as Error)
  }
}
