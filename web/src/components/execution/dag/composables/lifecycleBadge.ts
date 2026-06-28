/**
 * 节点生命周期相位徽章视觉映射（Chassis v2 · P5）。
 *
 * 与后端 `server/workflows/lifecycle_projection.py` 的相位词表一一对应：
 * `idle | running | waiting_clarification | revising | produced | waiting_approval | done | failed`。
 *
 * 语义色（P5 约定）：running 蓝 / waiting(澄清·审批) 琥珀 / revising 紫 / produced·done 绿 / failed 红。
 * 执行画布（ExecutionNode）与编辑画布运行态（BaseWorkflowNode）共用此映射，保证一致观感；
 * WS 缺 `lifecycle` 字段（静态加载/旧执行）时用 `deriveLifecycleFromStatus` 从节点 status 兜底。
 */

export type LifecyclePhase
  = | 'idle'
    | 'running'
    | 'waiting_clarification'
    | 'revising'
    | 'produced'
    | 'waiting_approval'
    | 'done'
    | 'failed'

export interface LifecycleBadgeVisual {
  /** 基础中文标签（不含轮次） */
  label: string
  /** 徽章容器 class（背景 + 文字 + 边框，半透明语义色） */
  badgeClass: string
  /** 指示点 class（实心语义色，运行/等待态带脉冲） */
  dotClass: string
}

/** 相位 → 视觉。未知相位回退到 idle。 */
export const LIFECYCLE_VISUALS: Record<LifecyclePhase, LifecycleBadgeVisual> = {
  idle: {
    label: '待运行',
    badgeClass: 'bg-muted/60 text-muted-foreground border-border/50',
    dotClass: 'bg-muted-foreground/50',
  },
  running: {
    label: '运行中',
    badgeClass: 'bg-primary/10 text-primary border-primary/30',
    dotClass: 'bg-primary animate-pulse',
  },
  waiting_clarification: {
    label: '等澄清',
    badgeClass: 'bg-amber-400/10 text-amber-600 border-amber-400/40',
    dotClass: 'bg-amber-400 animate-pulse',
  },
  revising: {
    label: '修订中',
    badgeClass: 'bg-purple-400/10 text-purple-600 border-purple-400/40',
    dotClass: 'bg-purple-400 animate-pulse',
  },
  produced: {
    label: '已产出',
    badgeClass: 'bg-green-400/10 text-green-600 border-green-400/40',
    dotClass: 'bg-green-400',
  },
  waiting_approval: {
    label: '待审批',
    badgeClass: 'bg-amber-400/10 text-amber-600 border-amber-400/40',
    dotClass: 'bg-amber-400 animate-pulse',
  },
  done: {
    label: '已完成',
    badgeClass: 'bg-green-400/10 text-green-600 border-green-400/40',
    dotClass: 'bg-green-400',
  },
  failed: {
    label: '失败',
    badgeClass: 'bg-red-400/10 text-red-600 border-red-400/40',
    dotClass: 'bg-red-400',
  },
}

/** 类型守卫 + 归一：非法相位回退 idle。 */
export function normalizeLifecyclePhase(phase: string | null | undefined): LifecyclePhase {
  if (phase && phase in LIFECYCLE_VISUALS)
    return phase as LifecyclePhase
  return 'idle'
}

/**
 * 从 NodeExecution.status 兜底推导相位（WS 未推送 `lifecycle` 时用）。
 * 与后端纯节点态映射（无 session）保持一致语义。
 */
export function deriveLifecycleFromStatus(status: string | null | undefined): LifecyclePhase {
  switch (status) {
    case 'running':
    case 'waiting_event':
      return 'running'
    case 'waiting_approval':
      return 'waiting_approval'
    case 'waiting_input':
      return 'waiting_clarification'
    case 'completed':
      return 'done'
    case 'failed':
    case 'timeout':
      return 'failed'
    default:
      // pending / queued / skipped / cancelled / 未知
      return 'idle'
  }
}

/**
 * 徽章展示文案：澄清/修订态附带「· 第 N/M 轮」，其余仅相位标签。
 */
export function lifecycleBadgeText(
  phase: LifecyclePhase,
  round?: number | null,
  maxRounds?: number | null,
): string {
  const base = LIFECYCLE_VISUALS[phase].label
  if ((phase === 'revising' || phase === 'waiting_clarification') && round) {
    const max = maxRounds ?? 6
    return `${base} · 第 ${round}/${max} 轮`
  }
  return base
}
