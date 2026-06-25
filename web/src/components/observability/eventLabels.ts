/**
 * 系统日志「事件 → 中文说明」映射（UI 展示用，纯前端字典）。
 *
 * 背景：structlog 事件名为 snake_case 英文（如 `metrics_query_served`），落库后
 * `message` 列默认与 `event` 同值，导致日志中心「消息」列全是英文事件名，运维同学
 * 难以一眼看懂。本字典把已知事件（与 `.planning/observability/LOGGING-SPEC.md §10`
 * 事件目录对齐）翻译成简洁中文，供 SystemLogTable「消息」列优先展示。
 *
 * 约定：
 * - 仅做展示层翻译，不改变落库的原始 `event` / `message`（筛选、检索仍用英文事件名）。
 * - 未收录的事件回退到原始 `message`，绝不抛异常或显示空白。
 * - 新增埋点事件时，按需在此补充中文说明即可（非强制，缺省回退原文）。
 */

/** 事件名 → 中文说明（与 LOGGING-SPEC §10 事件目录对齐）。 */
export const EVENT_LABELS: Record<string, string> = {
  // §10.1 用户上下文 / 中间件 / 运行时配置
  log_runtime_config_apply_failed: '运行时日志配置应用失败',
  system_setting_cache_invalidate_failed: '系统设置缓存失效失败',
  qdrant_client_reset_due_to_setting_change: 'Qdrant 凭证变更触发客户端重建',
  qdrant_client_reset_failed: 'Qdrant 客户端重建失败',
  sqlite_pragma_setup_failed: 'SQLite PRAGMA 设置失败',

  // §10.2 系统日志落库 / 队列 / 保留
  system_log_flush_failed: '系统日志批量落库失败',
  system_logs_purged: '系统日志按保留策略清理',
  system_logs_purge_failed: '系统日志清理失败',
  webhook_events_purged: 'Webhook 留痕按保留策略清理',
  webhook_events_purge_failed: 'Webhook 留痕清理失败',

  // §10.3 Webhook 原始留痕
  webhook_received: '收到入站 Webhook',
  inbound_webhook_recorded: 'Webhook 原始 payload 已脱敏入库',
  inbound_webhook_record_failed: 'Webhook 留痕入库失败',
  inbound_webhook_bg_schedule_failed: 'Webhook 留痕后台调度失败',
  webhook_events_queried: '查询 Webhook 留痕列表',

  // §10.4 运维观测 API / 下钻
  observability_served: '访问运维可观测性端点',
  call_drilldown_viewed: '查看单次调用下钻详情',
  conversation_drilldown_viewed: '查看会话调用链下钻',
  system_logs_queried: '查询系统日志列表',
  system_logs_cleared: '按条件清理系统日志',

  // §10.5 后台任务
  background_runner_started: '后台 runner 协程启动',
  job_start: '调度作业开始',
  job_complete: '调度作业完成',

  // §10.7 LLM 并发 / 限流 / 留痕
  llm_slot_acquired: '获取 LLM 并发槽位',
  llm_slot_busy_timeout: 'LLM 槽位等待超时限流',
  llm_slot_redis_unavailable_fallback_inprocess: 'Redis 不可用，降级进程内信号量',
  ledger_event_write_failed: '调用锚点留痕写入失败',
  ledger_tool_call_write_failed: '工具调用留痕写入失败',
  ledger_retrieval_trace_write_failed: '召回证据留痕写入失败',
  ledger_model_usage_write_failed: '模型用量留痕写入失败',
  ledger_llm_usage_write_failed: 'LLM 用量回写失败',

  // §10.8 快照 / 趋势 / 查询 / 采样 / 保留
  metrics_snapshot_served: '查询实时指标快照',
  metrics_query_served: '查询指标趋势/分位',
  snapshot_host_failed: '主机指标快照采集失败',
  snapshot_db_failed: '数据库指标快照采集失败',
  snapshot_redis_failed: 'Redis 指标快照采集失败',
  snapshot_qdrant_failed: 'Qdrant 指标快照采集失败',
  snapshot_concurrency_failed: '并发指标快照采集失败',
  gauge_sampled: '周期 gauge 采样写入',
  gauge_sample_failed: 'gauge 采样失败',
  gauge_samples_purged: 'gauge 采样行按保留策略清理',
  request_metrics_purged: '请求指标行清理',
  model_usage_records_purged: '模型用量行清理',

  // §10.9 告警评估与通知
  alert_rules_listed: '查询告警规则列表',
  alert_rule_created: '创建告警规则',
  alert_rule_updated: '更新告警规则',
  alert_rule_deleted: '删除告警规则',
  alert_events_queried: '查询告警事件',
  alert_eval_cycle: '完成一次告警评估周期',
  alert_eval_failed: '告警评估周期失败',
  alert_rule_eval_failed: '单条告警规则评估失败',
  alert_metric_unsupported: '告警规则引用了不支持的指标',
  alert_metric_resolve_failed: '告警指标取值解析失败',
  alert_firing: '告警触发',
  alert_resolved: '告警恢复',
  alert_notify_dispatch_failed: '告警通知分发失败',
  alert_notified: '告警通知送达',
  alert_notify_failed: '单渠道告警通知失败',
  alert_notify_persist_failed: '告警通知结果回写失败',
  alert_email_failed: '邮件告警发送失败',
  alert_feishu_failed: '飞书告警发送失败',
  alert_webhook_failed: '自定义 Webhook 告警发送失败',
  alert_events_purged: '告警事件按保留策略清理',
  alert_events_purge_failed: '告警事件清理失败',
}

/** message 前缀 → 中文说明（用于 Django 等动态消息事件，按前缀匹配）。 */
const MESSAGE_PREFIX_LABELS: Array<[string, string]> = [
  ['Not Found:', '接口未找到（404）'],
  ['Forbidden:', '访问被拒绝（403）'],
  ['Unauthorized:', '未授权（401）'],
  ['Bad Request:', '请求参数错误（400）'],
  ['Internal Server Error:', '服务器内部错误（500）'],
]

/**
 * 取一条日志的中文展示文案：
 * 1. 命中事件字典 → 返回中文说明；
 * 2. 否则按 message 前缀匹配（Django 动态消息）→ 中文前缀 + 原始路径/详情；
 * 3. 都未命中 → 回退原始 message（再退到事件名）。
 */
export function eventMessageLabel(event: string, message: string): string {
  const mapped = EVENT_LABELS[event]
  if (mapped)
    return mapped

  const msg = (message || '').trim()
  for (const [prefix, label] of MESSAGE_PREFIX_LABELS) {
    if (msg.startsWith(prefix))
      return `${label} ${msg.slice(prefix.length).trim()}`.trim()
  }

  return msg || event || ''
}
