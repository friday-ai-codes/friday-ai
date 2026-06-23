/**
 * useIndexProgressStream — 通过 fetch + ReadableStream 消费索引进度 SSE 流
 *
 * 后端端点：GET /api/repositories/{id}/index/stream/
 * Content-Type: text/event-stream
 *
 * 帧体形如：
 *   {"type": "progress",
 *    "ts": "...",
 *    "repository": { index_status, overall_progress, overall_stage,
 *                    index_total_chunks, ... },
 *    "running_history": null | { id, status, from_sha, to_sha,
 *                                files_added, files_modified, files_deleted,
 *                                changed_files, summary_text,
 * // per-run delta + 行级 diff
 *                                symbols_added, imports_added, calls_added,
 *                                endpoints_added, chunk_edges_added,
 *                                lines_added, lines_deleted, ... }}
 *
 *   {"type": "done", "reason": "idle" | "max_ticks" | "repo_deleted"}
 *
 * 用 fetch + ReadableStream（与 useSSEStream 一致的模式）以便携带
 * Cookie 鉴权，并且后端可以是 GET 端点直接复用浏览器 fetch 缓存策略。
 */
import type { IndexHistoryItem } from '~/api/repositories'

const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface IndexStreamRepositoryPayload {
  index_status: string
  last_indexed_at: string | null
  index_error: string | null
  index_total_chunks: number
  index_processed_chunks: number
  index_write_total: number
  index_write_processed: number
  overall_progress: number
  overall_stage: string
  // OBS-05: 文件级实时进度
  current_indexing_file?: string
  indexed_files_processed?: number
  indexed_files_total?: number
  // PROG-02: AI 描述生成状态（not_started/pending/running/completed/failed）
  ai_summary_status?: string
  ai_summary_error?: string
}

/** 图谱构建进度（SSE 帧顶层 graph 段，与 repository 平级，PROG-01 独立轨）。 */
export interface IndexStreamGraphPayload {
  status: string
  stage: string
  files_processed: number
  files_total: number
  percent: number
  current_file: string
  started_at: string | null
  edge_count_so_far: number
  error_message: string
}

export type IndexStreamEvent
  = | {
    type: 'progress'
    ts: string
    repository: IndexStreamRepositoryPayload
    // ：per-run delta（symbols_added / imports_added /
    // calls_added / endpoints_added / chunk_edges_added）与行级 diff
    // （lines_added / lines_deleted，number | null）经 running_history
    // （后端 IndexHistorySerializer）天然携带 —— 这是 SSE delta 的**主路径**：
    // RUNNING 行经 IndexHistoryList 的 liveRunningHistory merge 实时显示 delta，
    // 无需扩展 SSE 后端的 graph 段。running_history 直接复用 IndexHistoryItem，
    // 故 295-01 在 IndexHistoryItem 上新增的 delta 字段在此天然继承，
    // 消除「后端发了 delta 字段、前端类型没有」的 drift。
    running_history: IndexHistoryItem | null
    // PROG-01：图谱构建独立轨（后端 SSE 帧顶层 graph 段，与 repository 平级）
    graph?: IndexStreamGraphPayload | null
  }
  | { type: 'done', reason: string }

export interface ConnectIndexStreamOptions {
  /** 收到一帧事件 */
  onEvent: (event: IndexStreamEvent) => void
  /** 流中断 / 网络错误 — 调用方决定是否重连 */
  onError?: (err: Error) => void
}

/**
 * 连接索引进度 SSE 流
 *
 * @returns AbortController — 调用方决定何时取消（通常组件卸载或 list 中无 RUNNING 项时）
 */
export function connectIndexProgressStream(
  repositoryId: string,
  options: ConnectIndexStreamOptions,
): AbortController {
  const controller = new AbortController()
  void runStream(repositoryId, options, controller.signal)
  return controller
}

async function runStream(
  repositoryId: string,
  options: ConnectIndexStreamOptions,
  signal: AbortSignal,
): Promise<void> {
  try {
    // 项目走 JWT (Bearer)：必须把 access_token 显式放进 Authorization header；
    // SSE 端点同其它 DRF View 一样用 IsAuthenticated 校验 — 没 token 直接 401，
    // 静默失败会让前端 progress 永远收不到事件，进度条卡在初始值。
    const accessToken = localStorage.getItem('access_token') ?? ''
    const headers: Record<string, string> = {
      Accept: 'text/event-stream',
    }
    if (accessToken) {
      headers.Authorization = `Bearer ${accessToken}`
    }
    const response = await fetch(
      `${API_BASE}/repositories/${repositoryId}/index/stream/`,
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
              const payload = JSON.parse(trimmed.slice(6)) as IndexStreamEvent
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
    // 静默失败是上游 bug 的根源：之前 SSE 拿了 406 没有日志、UI 又有 polling 兜底，
    // 用户看到的就是「卡在克隆中」。打 console 让浏览器 devtools 至少能看到。
    console.error('[useIndexProgressStream] 连接失败:', err)
    options.onError?.(err as Error)
  }
}
