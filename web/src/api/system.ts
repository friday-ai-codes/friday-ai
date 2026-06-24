/**
 * 系统级健康检查 API + 通用设置扩展
 */

import { del, get, patch, post } from './client'

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

// ============================================================================
// 运维大盘数据层（Phase 71–74 运维端点 typed 客户端）
//
// 以下函数均复用 ./client 的 get/post/patch/del（cookie-JWT 自动处理，前端不传 token）。
// 全部 /api/system/* 运维端点后端权限均为 IsSuperUser fail-closed；前端仅在
// requiresAdmin 守卫下渲染。类型严格对齐后端视图/序列化器的路由·参数·响应形状。
//
// 安全契约：本层**不**声明任何明文 api_key/token 字段；下钻 token_fingerprint 仅作
// 哈希展示，依赖后端写入时已 redact_for_ledger 脱敏，前端只读直出、绝不重拼明文。
// ============================================================================

// ----------------------------------------------------------------------------
// 1) 指标快照（QUERY-02）：GET /system/metrics/snapshot/（IsSuperUser）
//    对齐 snapshot_service.collect_snapshot 五源 envelope + 队列计数 + generated_at。
// ----------------------------------------------------------------------------

/** 各源统一 envelope 基类：available + error（失败时 available=false，error 为原因）。 */
export interface SnapshotEnvelope {
  available: boolean
  error: string
}

/** SNAP-01 主机/进程运行时：CPU/内存 + 协程数 + 线程数 + 后台任务计数。 */
export interface HostSnapshot extends SnapshotEnvelope {
  cpu_percent?: number
  mem_total_mb?: number
  mem_used_mb?: number
  mem_percent?: number
  /** 非事件循环上下文取不到时为 null。 */
  asyncio_tasks?: number | null
  threads?: number
  /** 后台任务汇总（durable/subagent/orchestration），结构由 observability 聚合给出。 */
  background_tasks?: Record<string, number>
}

/** SNAP-02 DB 连接：SQLite dev 优雅降级 available=false；Postgres 回连接分布等。 */
export interface DbSnapshot extends SnapshotEnvelope {
  vendor?: string
  connections?: {
    total?: number
    active?: number
    idle?: number
    idle_in_transaction?: number
    waiting?: number
  }
  max_connections?: number | null
  /** psycopg 应用层池 get_stats()（取不到为 null）。 */
  pool?: Record<string, any> | null
  /** PgBouncer SHOW POOLS（opt-in，取不到为 null）。 */
  pgbouncer?: Record<string, any> | null
}

/** 单路 Redis INFO + 命中率（cache/channels/llm 各一路）。 */
export interface RedisClientSnapshot extends SnapshotEnvelope {
  connected_clients?: number
  maxclients?: number | null
  used_memory?: number
  used_memory_human?: string
  keyspace_hits?: number
  keyspace_misses?: number
  hit_rate?: number | null
}

/** SNAP-03 Redis 多路：clients 按路（cache/channels/llm）给出各自 envelope。 */
export interface RedisSnapshot extends SnapshotEnvelope {
  clients?: Record<string, RedisClientSnapshot>
}

/** SNAP-04 Qdrant：可用性 ping + collection 数/占用（带缓存标记）。 */
export interface QdrantSnapshot extends SnapshotEnvelope {
  liveness?: boolean
  cached?: boolean
  collection_count?: number | null
  approx_size?: {
    sampled_collections: number
    points_count_sampled: number
    truncated: boolean
  } | null
}

/** SNAP-05 并发/排队：provider 槽位 / durable / runner / RAG（各块宽松兜底）。 */
export interface ConcurrencySnapshot extends SnapshotEnvelope {
  provider_slots?: any
  durable_queues?: any
  runner?: any
  rag?: any
}

/** 队列四计数（log_sink/metric_sink snapshot_counters：queue_size/enqueued/dropped/failed/sampled_out 等）。 */
export interface QueueCounters {
  request_metric?: Record<string, number>
  system_log?: Record<string, number>
}

/** 指标快照聚合响应：五源 envelope + 队列计数 + 生成时间。 */
export interface MetricsSnapshot {
  host: HostSnapshot
  db: DbSnapshot
  redis: RedisSnapshot
  qdrant: QdrantSnapshot
  concurrency: ConcurrencySnapshot
  counters: QueueCounters
  generated_at: string
}

/** 一次性聚合 SNAP-01~05 当前值。 */
export async function getMetricsSnapshot(): Promise<MetricsSnapshot> {
  return get<MetricsSnapshot>('/system/metrics/snapshot/')
}

// ----------------------------------------------------------------------------
// 2) 时序查询（QUERY-01 / SLA-01 / RATE-03）：GET /system/metrics/query/（IsSuperUser）
//    对齐 metrics_query.query_timeseries 受控 metric/dimension/agg 与两种 series 形状。
// ----------------------------------------------------------------------------

/** 受控 metric：计数/分位/求和型 + gauge:<受控前缀名>。 */
export type MetricName = 'qps' | 'tps' | 'sla' | 'error' | 'duration' | 'ttft' | `gauge:${string}`
/** 受控聚合方式（分位 + avg/max）。 */
export type MetricAgg = 'p95' | 'p90' | 'p50' | 'avg' | 'max'
/** 受控分组维度（仅白名单列可进 GROUP BY）。 */
export type MetricDimension = 'source' | 'provider' | 'call_source' | 'error_class' | 'route' | 'model'

/** 计数/分位/求和/gauge 型时间桶点：{bucket, dim, value}。 */
export interface MetricPoint {
  bucket: string
  dim: string
  value: number
}

/** SLA 型时间桶点：可用率派生（business 不计入分母）。 */
export interface SlaPoint {
  bucket: string
  dim: string
  /** (eligible - failures) / eligible；eligible=0 时为 null。 */
  availability: number | null
  eligible: number
  failures: number
  business_rejected: number
}

/** 时序查询统一响应包络；series 形状随 metric 而异（默认 MetricPoint，sla 为 SlaPoint）。 */
export interface MetricsQueryResult<T = MetricPoint> {
  metric: string
  agg: string
  step_seconds: number
  start: string
  end: string
  vendor: string
  /** SQLite 分位降级时为 true。 */
  degraded: boolean
  /** 降级说明（如 'sqlite_percentile_approx'）。 */
  note: string
  series: T[]
}

/** 时序查询入参；client 自动 drop undefined。dimension 传 '' 表示全量桶。 */
export interface MetricsQueryParams {
  metric: MetricName
  start?: string
  end?: string
  /** 时间桶步长，如 '30s'/'1m'/'5m'/'1h'/'1d'（默认 60s）。 */
  step?: string
  dimension?: MetricDimension | ''
  agg?: MetricAgg
}

/** 计数/分位/求和/gauge 型查询（series 为 MetricPoint[]）。 */
export async function queryMetrics(params: MetricsQueryParams): Promise<MetricsQueryResult<MetricPoint>> {
  return get<MetricsQueryResult<MetricPoint>>('/system/metrics/query/', { ...params })
}

/** SLA 可用率查询（metric 固定 'sla'，series 为 SlaPoint[]）。 */
export async function querySla(
  params: Omit<MetricsQueryParams, 'metric' | 'agg'>,
): Promise<MetricsQueryResult<SlaPoint>> {
  return get<MetricsQueryResult<SlaPoint>>('/system/metrics/query/', { ...params, metric: 'sla' })
}

// ----------------------------------------------------------------------------
// 3) 告警规则 CRUD（ALERT-01）：/system/alerts/rules/(+<rule_id>/)（IsSuperUser）
//    对齐 alert_serializers.SystemAlertRule(Write)Serializer 字段与受控枚举。
// ----------------------------------------------------------------------------

/** 告警规则比较运算符。 */
export type AlertOp = 'gt' | 'gte' | 'lt' | 'lte'
/** 告警严重级别。 */
export type AlertSeverity = 'P0' | 'P1' | 'P2'
/** 通知通道受控子集。 */
export type AlertChannel = 'email' | 'feishu' | 'webhook'
/**
 * 受控告警 metric（与 74-02 评估器 metric 解析表对齐；后端 ChoiceField 白名单校验）。
 * 注意：与时序查询 MetricName 不同——告警 metric 含 cpu/memory/db_connections 等快照派生项。
 */
export type AlertMetric
  = | 'qps'
    | 'error_rate'
    | 'ttft'
    | 'cpu'
    | 'memory'
    | 'db_connections'
    | 'redis_clients'
    | 'qdrant'
    | 'queue_depth'

/** 告警规则（读形状，含时间戳）。 */
export interface AlertRule {
  id: number
  name: string
  metric: AlertMetric
  op: AlertOp
  value: number
  window: number
  dimension: Record<string, string>
  severity: AlertSeverity
  enabled: boolean
  channels: AlertChannel[]
  cooldown: number
  title_template: string
  created_at: string
  updated_at: string
}

/** 告警规则写入体（create 用全量；patch 用 Partial）。 */
export type AlertRuleWrite = Omit<AlertRule, 'id' | 'created_at' | 'updated_at'>

/** 规则列表（可选 enabled 过滤）。 */
export async function listAlertRules(
  params?: { enabled?: boolean },
): Promise<{ items: AlertRule[], total: number }> {
  return get<{ items: AlertRule[], total: number }>('/system/alerts/rules/', params)
}

/** 创建规则。 */
export async function createAlertRule(body: AlertRuleWrite): Promise<AlertRule> {
  return post<AlertRule>('/system/alerts/rules/', body)
}

/** 单条规则详情。 */
export async function getAlertRule(id: number): Promise<AlertRule> {
  return get<AlertRule>(`/system/alerts/rules/${id}/`)
}

/** 部分更新规则。 */
export async function updateAlertRule(id: number, body: Partial<AlertRuleWrite>): Promise<AlertRule> {
  return patch<AlertRule>(`/system/alerts/rules/${id}/`, body)
}

/** 删除规则（204 No Content）。 */
export async function deleteAlertRule(id: number): Promise<void> {
  return del(`/system/alerts/rules/${id}/`)
}

// ----------------------------------------------------------------------------
// 4) 告警事件（ALERT-02）：GET /system/alerts/events/（IsSuperUser）
//    对齐 alert_serializers.AlertEventSerializer 全字段（列对齐 REFERENCE-UI §1.4）。
//    新名 AlertEventRow，避免与既有 OBS-01 AlertEvent interface 撞名。
// ----------------------------------------------------------------------------

/** 告警事件行（已脱敏只读直出）。 */
export interface AlertEventRow {
  id: number
  rule: number | null
  severity: AlertSeverity
  title_zh: string
  rule_info: Record<string, any>
  target: Record<string, any>
  target_key: string
  status: 'firing' | 'resolved'
  started_at: string
  ended_at: string | null
  duration_s: number | null
  current_value: number | null
  last_seen_at: string | null
  email_sent: string
  notified_channels: string[]
  created_at: string
}

/** 告警事件查询入参（全部可选，组合 AND；started_at 时间段 + 分页倒序）。 */
export interface AlertEventQuery {
  severity?: string
  status?: string
  rule_id?: number
  start?: string
  end?: string
  limit?: number
  offset?: number
}

/** 告警事件查询。 */
export async function listAlertEvents(
  params?: AlertEventQuery,
): Promise<{ items: AlertEventRow[], total: number }> {
  return get<{ items: AlertEventRow[], total: number }>('/system/alerts/events/', params ? { ...params } : undefined)
}

// ----------------------------------------------------------------------------
// 5) 系统日志（LOG-01/03/08）：/system/logs/(+/clear/)（IsSuperUser）
//    对齐 serializers.SystemLogEntrySerializer + log_views 查询/清理契约。
//    新名 SystemLogRow，避免与既有内存版 SystemLogEntry interface 撞名。
// ----------------------------------------------------------------------------

/** 持久化系统日志行（SystemLogEntry，payload/correlation 写入前已脱敏）。 */
export interface SystemLogRow {
  id: number
  ts: string | null
  level: string
  component: string
  category: string
  event: string
  message: string
  user_id: string
  source: string
  trace_id: string
  request_id: string
  payload: Record<string, any>
  correlation: Record<string, any>
}

/** 系统日志查询/清理共用筛选条件（全部可选，组合 AND）。 */
export interface SystemLogQuery {
  component?: string
  level?: string
  user_id?: string
  source?: string
  start?: string
  end?: string
  keyword?: string
  limit?: number
  offset?: number
}

/** 系统日志查询结果：items + total + 队列四计数。 */
export interface SystemLogResult {
  items: SystemLogRow[]
  total: number
  counters: Record<string, number>
}

/** 系统日志查询（时间倒序 + 组合筛选 + 全文，顶部带队列计数）。 */
export async function querySystemLogs(params?: SystemLogQuery): Promise<SystemLogResult> {
  return get<SystemLogResult>('/system/logs/', params ? { ...params } : undefined)
}

/**
 * 按条件批量清理日志（防误清：无任何筛选条件时须显式 confirm_all=true）。
 * 返回 { deleted: <删除行数> }。
 */
export async function clearSystemLogs(
  body: SystemLogQuery & { confirm_all?: boolean },
): Promise<{ deleted: number }> {
  return post<{ deleted: number }>('/system/logs/clear/', body)
}

// ----------------------------------------------------------------------------
// 6) 入站 webhook 原始留痕（LOG-07）：/system/webhooks/(+<event_id>/)（IsSuperUser）
//    对齐 serializers.InboundWebhookEventSerializer；headers/raw_body 写入前已脱敏。
// ----------------------------------------------------------------------------

/** 入站 webhook 原始留痕行（已脱敏只读直出）。 */
export interface WebhookEventRow {
  id: number
  received_at: string
  kind: string
  source_ip: string
  headers: Record<string, any>
  raw_body: any
  user_id: string
  verified: boolean
  correlation: Record<string, any>
  created_at: string
}

/** webhook 留痕列表（倒序 + kind/user_id/verified/时间段筛选 + 分页）。 */
export async function listWebhookEvents(
  params?: { kind?: string, user_id?: string, verified?: boolean, start?: string, end?: string, limit?: number, offset?: number },
): Promise<{ items: WebhookEventRow[], total: number }> {
  return get<{ items: WebhookEventRow[], total: number }>('/system/webhooks/', params)
}

/** 单条 webhook 原始详情（已脱敏，原始可回放）。 */
export async function getWebhookEvent(id: number): Promise<WebhookEventRow> {
  return get<WebhookEventRow>(`/system/webhooks/${id}/`)
}

// ----------------------------------------------------------------------------
// 7) 调用下钻（LOG-04）：/system/calls/drilldown/ + /system/conversations/<uuid>/drilldown/
//    （IsSuperUser）对齐 drilldown_views；token_fingerprint 仅哈希展示，绝不回 token。
// ----------------------------------------------------------------------------

/** MCP 调用下钻：run 归因 + 触发用户（只回 id/用户名/fingerprint）+ 各类明细行。 */
export interface CallDrilldown {
  run: Record<string, any>
  user: { id: string | null, username: string, fingerprint: string }
  tool_calls: any[]
  retrieval: any[]
  model_usages: any[]
  events: any[]
}

/** 按 request_id 或 run_id 下钻一次 MCP 调用（二者至少其一）。 */
export async function getCallDrilldown(
  params: { request_id?: string, run_id?: string },
): Promise<CallDrilldown> {
  return get<CallDrilldown>('/system/calls/drilldown/', params)
}

/** AI 对话会话原始下钻：会话 + 创建者 + 消息 + 关联日志/run（只回关联键，不复制正文）。 */
export interface ConversationDrilldown {
  conversation: Record<string, any>
  created_by: { id: string, username: string } | null
  messages: any[]
  related_logs: any[]
  related_runs: any[]
}

/** 按 conversation_id（uuid）下钻 AI 对话会话原始。 */
export async function getConversationDrilldown(conversationId: string): Promise<ConversationDrilldown> {
  return get<ConversationDrilldown>(`/system/conversations/${conversationId}/drilldown/`)
}
