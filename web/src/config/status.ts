export interface StatusConfig {
  label: string
  icon: string
  variant: 'success' | 'warning' | 'info' | 'destructive' | 'muted' | 'default' | 'secondary' | 'outline'
  animate?: boolean
}

// 执行状态（WorkflowExecution）
export const executionStatusConfig: Record<string, StatusConfig> = {
  pending: { label: '等待中', icon: 'lucide--clock', variant: 'muted' },
  queued: { label: '排队中', icon: 'lucide--list', variant: 'muted' },
  running: { label: '运行中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  paused: { label: '已暂停', icon: 'lucide--pause', variant: 'warning' },
  completed: { label: '已完成', icon: 'lucide--check-circle', variant: 'success' },
  failed: { label: '失败', icon: 'lucide--x-circle', variant: 'destructive' },
  cancelled: { label: '已取消', icon: 'lucide--square', variant: 'muted' },
  timeout: { label: '超时', icon: 'lucide--alarm-clock-off', variant: 'warning' },
  // OBS-03 / Pitfall 7：suspended 是 execution 级挂起态（Phase 18 等待落点），与后端 ExecutionStatus 对齐，补非 fallback badge
  suspended: { label: '挂起中', icon: 'lucide--pause-circle', variant: 'warning' },
  // 注：waiting_approval / waiting_input 仅用于 node 状态渲染（如 NodeOverviewTab），不用于 execution 级筛选/统计
  waiting_approval: { label: '待审批', icon: 'lucide--user-check', variant: 'warning' },
  waiting_input: { label: '待输入', icon: 'lucide--edit', variant: 'info' },
  skipped: { label: '已跳过', icon: 'lucide--skip-forward', variant: 'muted' },
}

// Runner 状态
export const runnerStatusConfig: Record<string, StatusConfig> = {
  online: { label: '在线', icon: 'lucide--wifi', variant: 'success' },
  offline: { label: '离线', icon: 'lucide--wifi-off', variant: 'muted' },
}

// 编码任务状态
export const codingTaskStatusConfig: Record<string, StatusConfig> = {
  pending: { label: '待执行', icon: 'lucide--clock', variant: 'muted' },
  planning: { label: '规划中', icon: 'lucide--brain', variant: 'info', animate: true },
  plan_review: { label: '方案评审', icon: 'lucide--eye', variant: 'warning' },
  executing: { label: '执行中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  code_review: { label: '代码评审', icon: 'lucide--eye', variant: 'warning' },
  merged: { label: '已合并', icon: 'lucide--git-merge', variant: 'success' },
  partial_success: { label: '部分成功', icon: 'lucide--alert-triangle', variant: 'warning' },
  failed: { label: '失败', icon: 'lucide--x-circle', variant: 'destructive' },
}

// 索引状态
export const indexStatusConfig: Record<string, StatusConfig> = {
  pending: { label: '等待中', icon: 'lucide--clock', variant: 'muted' },
  not_indexed: { label: '未索引', icon: 'lucide--clock', variant: 'muted' },
  running: { label: '运行中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  indexing: { label: '索引中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  completed: { label: '已完成', icon: 'lucide--check-circle', variant: 'success' },
  indexed: { label: '已索引', icon: 'lucide--check-circle', variant: 'success' },
  failed: { label: '失败', icon: 'lucide--x-circle', variant: 'destructive' },
  cancelled: { label: '已停止', icon: 'lucide--circle-stop', variant: 'muted' },
}

// 触发日志状态
export const triggerLogStatusConfig: Record<string, StatusConfig> = {
  accepted: { label: '已接受', icon: 'lucide--check', variant: 'success' },
  ignored: { label: '已忽略', icon: 'lucide--minus-circle', variant: 'secondary' },
  error: { label: '错误', icon: 'lucide--alert-circle', variant: 'destructive' },
  duplicate: { label: '重复', icon: 'lucide--copy', variant: 'outline' },
}

// 图谱构建状态
export const graphStatusConfig: Record<string, StatusConfig> = {
  idle: { label: '未构建', icon: 'lucide--circle', variant: 'muted' },
  running: { label: '构建中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  completed: { label: '已构建', icon: 'lucide--check-circle', variant: 'success' },
  failed: { label: '失败', icon: 'lucide--x-circle', variant: 'destructive' },
  cancelled: { label: '已停止', icon: 'lucide--circle-stop', variant: 'muted' },
}

// ：CodingSession 状态徽章 6 态
//
// 与后端 chat.models.CodingSession.Status 同步：draft / confirmed / running /
// awaiting_confirmation / completed / failed。FAN-05 状态行 / TechPlanCard
// 集成（FAN-04）共用。
export const codingSessionStatusConfig: Record<string, StatusConfig> = {
  draft: { label: '草稿', icon: 'lucide--file-text', variant: 'muted' },
  confirmed: { label: '已确认', icon: 'lucide--check', variant: 'info' },
  running: { label: '执行中', icon: 'lucide--loader-2', variant: 'info', animate: true },
  awaiting_confirmation: { label: '等待确认', icon: 'lucide--circle-pause', variant: 'warning' },
  completed: { label: '已完成', icon: 'lucide--check-circle', variant: 'success' },
  failed: { label: '失败', icon: 'lucide--x-circle', variant: 'destructive' },
}

// 根据状态类型获取配置
export function getStatusConfig(
  type: 'execution' | 'runner' | 'codingTask' | 'index' | 'triggerLog' | 'graph' | 'codingSession',
  status: string,
): StatusConfig {
  const configMap = {
    execution: executionStatusConfig,
    runner: runnerStatusConfig,
    codingTask: codingTaskStatusConfig,
    index: indexStatusConfig,
    triggerLog: triggerLogStatusConfig,
    graph: graphStatusConfig,
    codingSession: codingSessionStatusConfig,
  }
  return configMap[type][status] ?? { label: status, icon: 'lucide--help-circle', variant: 'muted' as const }
}
