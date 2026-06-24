/**
 * 系统级健康检查 API + 通用设置扩展
 */

import { get } from './client'

export type ServiceHealthStatus = 'healthy' | 'unhealthy' | 'not_configured'
/**
 * 整体状态只区分正常 / 异常：未配置视为正常。
 */
export type OverallHealthStatus = 'healthy' | 'unhealthy'

export interface ServiceHealth {
  name: 'database' | 'redis' | 'feishu' | 'qdrant' | string
  label: string
  status: ServiceHealthStatus
  message?: string
  latency_ms?: number
}

export interface SystemHealth {
  overall: OverallHealthStatus
  checked_at: string
  services: ServiceHealth[]
}

export async function getSystemHealth(): Promise<SystemHealth> {
  return get<SystemHealth>('/system/health/')
}

// ============================================================================
// 通用设置：系统信息 / 备份 / 恢复
// ============================================================================

/** 系统信息响应。 */
export interface SystemInfoResponse {
  version: { current: string }
  changelog_url: string
  environment: Record<string, string>
  image: {
    task_runner_image: string
  }
  database: {
    engine: string
    path: string
    size: string
  }
  python_version: string
  django_version: string
}

export async function getSystemInfo(): Promise<SystemInfoResponse> {
  return get<SystemInfoResponse>('/settings/info/')
}

/**
 * 下载数据库备份（返回 Blob + 服务端给出的文件名）。
 * 文件扩展名随数据库引擎不同（sqlite=.db / postgres=.dump / mysql=.sql），
 * 故文件名优先取响应的 Content-Disposition。
 */
export async function downloadSystemBackup(): Promise<{ blob: Blob, filename: string }> {
  const resp = await fetch('/api/settings/backup/', {
    method: 'GET',
    headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
    },
  })
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: '备份下载失败' }))
    throw new Error(err.detail ?? '备份下载失败')
  }
  const disposition = resp.headers.get('Content-Disposition') ?? ''
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i)
  const filename = match?.[1]
    ? decodeURIComponent(match[1])
    : `friday_backup_${new Date().toISOString().slice(0, 10)}`
  return { blob: await resp.blob(), filename }
}

/** 上传备份文件恢复数据库。restored_tables 仅 SQLite 引擎返回。 */
export async function restoreSystemBackup(file: File): Promise<{ detail: string, restored_tables?: number }> {
  const formData = new FormData()
  formData.append('file', file)
  const resp = await fetch('/api/settings/backup/', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${localStorage.getItem('access_token') ?? ''}`,
    },
    body: formData,
  })
  const data = await resp.json()
  if (!resp.ok) {
    throw new Error(data.detail ?? '恢复失败')
  }
  return data
}

// ============================================================================
// 超管可观测总览（OBS-01）：任务队列全景 + 系统/Runner 负载
// GET /api/system/observability/（IsSuperUser）
// ============================================================================

/** durable 队列（procrastinate_jobs）按 queue×status 的一行计数。 */
export interface QueueStatusRow {
  queue: string
  status: string
  count: number
}

/** SubAgent 会话按 task_type×status 的一行计数。 */
export interface SubagentStatusRow {
  task_type: string
  status: string
  count: number
}

/** 活跃（pending/running）SubAgent 会话条目。 */
export interface SubagentActiveItem {
  session_id: string
  task_type: string
  status: string
  repository_id: string
  runner_id: string
  updated_at: string
}

/** Runner 最近一次心跳上报的负载（与主机等价）。 */
export interface RunnerLoad {
  cpu_percent?: number
  mem_percent?: number
  mem_total_mb?: number
  mem_used_mb?: number
  disk_percent?: number
  disk_total_gb?: number
  disk_used_gb?: number
}

export interface RunnerObservability {
  id: string
  name: string
  status: string
  current_tasks: number
  concurrent: number
  version: string
  last_heartbeat: string | null
  load: RunnerLoad
}

/** server 进程运行时快照：协程数 + 线程数。 */
export interface RuntimeStats {
  asyncio_tasks: number | null
  threads: number
}

/** 后台（异步）任务数量汇总。 */
export interface BackgroundTaskSummary {
  durable_active: number
  durable_total: number
  subagent_active: number
  orchestration_active: number
  total_active: number
}

/** 告警事件（AlertRuleExecution）。 */
export interface AlertEvent {
  id: string
  rule_name: string
  condition_type: string
  status: string
  triggered_event: string
  error_message: string
  triggered_at: string
}

export interface ObservabilityResponse {
  generated_at: string
  durable_queues: {
    by_queue_status: QueueStatusRow[]
    totals: Record<string, number>
  }
  subagent: {
    by_type_status: SubagentStatusRow[]
    active: SubagentActiveItem[]
  }
  repositories: {
    total: number
    index_status: Record<string, number>
    graph_status: Record<string, number>
    ai_summary_status: Record<string, number>
  }
  orchestration: Record<string, number>
  runners: RunnerObservability[]
  runtime: RuntimeStats
  background_tasks: BackgroundTaskSummary
  alerts: {
    recent: AlertEvent[]
    counts: Record<string, number>
  }
}

export async function getObservability(): Promise<ObservabilityResponse> {
  return get<ObservabilityResponse>('/system/observability/')
}

// ============================================================================
// 运维监控「系统日志」：内存环形缓冲最近日志
// GET /api/system/logs/（IsSuperUser）
// ============================================================================

export interface SystemLogEntry {
  ts: string | null
  level: string
  logger: string
  message: string
  source: string
}

export async function getSystemLogs(params: { limit?: number, level?: string } = {}): Promise<{ logs: SystemLogEntry[] }> {
  return get<{ logs: SystemLogEntry[] }>('/system/logs/', params)
}

// ============================================================================
// 任务中心：排队中/进行中的后台任务列表（索引 / AI 描述 / durable 队列）
// GET /api/system/tasks/（IsAuthenticated）
// ============================================================================

export interface IndexingTaskItem {
  repository_id: string
  name: string
  stage: string
  current_file: string
  files_processed: number
  files_total: number
}

export interface SummaryTaskItem {
  repository_id: string
  name: string
  status: string
}

export interface ActiveTasksResponse {
  indexing: { count: number, items: IndexingTaskItem[] }
  summary: { count: number, items: SummaryTaskItem[] }
  queue: {
    by_queue_status: QueueStatusRow[]
    totals: Record<string, number>
  }
}

export async function getActiveTasks(): Promise<ActiveTasksResponse> {
  return get<ActiveTasksResponse>('/system/tasks/')
}
