/**
 * 仓库对账 / 清理 API（Phase 23 purge-reconcile，EXCL-04 / EXCL-06）。
 *
 * 安全边界（DOMAIN §9.1）：
 * - 普通清理仅清除 Friday 派生的索引/检索面，使被排除文件对 Friday 不可见；
 * - 敏感清理额外尽力清理操作记录面（归档 diff / 任务结果 / 执行轨迹 / 消息正文），
 *   但 **不承诺** 从本地 git object / Git 历史 / 备份中物理消失（§9.1，靠工具层 denylist 兜底）。
 *
 * 清理后台异步执行：`cleanup` 立即返回 `run_id`，前端经 `getCleanupStatus` 拉取
 * `CleanupRun` 真实结果（含敏感清理「哪些面未清(unscrubbed) + caveat」，W1/W2），
 * 并重查 `getReconcile` 观察差异归零。对账匹配器构造失败时 `degraded=true`，
 * 前端须显式「对账不可信」而非假装已一致（W3）。
 */

import { get, post } from './client'

/** 清理模式：普通（仅派生索引面）/ 敏感（额外清操作记录面，23-03）。 */
export type CleanupMode = 'normal' | 'sensitive'

/**
 * 对账结果（与后端 `ReconcileReportSerializer` / `services.purge_reconcile.ReconcileReport` 对齐）。
 *
 * `degraded=true` 表示排除规则匹配器构造失败，对账不可信——此时 `match_count` 恒为 0，
 * 前端 **不得** 据此渲染「已一致」空态，必须显式警示（W3）。
 */
export interface ReconcileReport {
  /** 已索引文件总数（FileIndex ∪ ChunkRegistry 去重）。 */
  indexed_count: number
  /** 现行排除规则模式列表（仅供展示）。 */
  excluded_paths: string[]
  /** 「已索引但现命中排除」的差异文件数；degraded 时为 0。 */
  match_count: number
  /** 后端建议的清理模式。 */
  suggested_mode: CleanupMode
  /** 匹配器构造失败 → 对账不可信（W3）。 */
  degraded: boolean
  /** degraded 时的失败原因；正常时为空串。 */
  error: string
}

/** POST `/reconcile/` 派发清理的即时响应（202）。 */
export interface CleanupDispatch {
  mode: CleanupMode
  /** 即时命中数（派发前 compute_reconciliation 取；degraded 时为 0）。 */
  match_count: number
  dispatched: boolean
  /** 本次清理运行记录 id，供状态端点拉取真实结果。 */
  run_id: string
}

/**
 * 敏感清理结果（落 `CleanupRun.sensitive`，由 23-03 `purge_sensitive_planes` 原样透传）。
 *
 * `unscrubbed` 为应用层不强保证 / 无精确 file 关联的面（prompt snapshot / 备份 / git object），
 * 须如实回显；`caveat` 如实声明 git/备份不承诺物理消失（§9.1）。
 */
export interface CleanupSensitiveResult {
  /** 各面计数：`{ plane: { scrubbed, deleted } }`。 */
  scrubbed?: Record<string, { scrubbed: number, deleted: number }>
  /** 未能清除的面（best-effort 范围之外）。 */
  unscrubbed?: string[]
  /** 诚实边界声明。 */
  caveat?: string
  /** 逐面隔离的失败标记。 */
  errors?: string[]
}

/**
 * 最近一次清理运行记录（与 `CleanupRunSerializer` 对齐）。
 *
 * `status='none'` 为状态端点在无任何运行记录时返回的哨兵值。
 */
export interface CleanupRun {
  status: 'none' | 'running' | 'completed' | 'failed'
  id?: string
  mode?: CleanupMode
  match_count?: number
  failures?: string[]
  /** 敏感模式结果 dict；普通模式为 null。 */
  sensitive?: CleanupSensitiveResult | null
  started_at?: string
  completed_at?: string | null
  error?: string
}

export const reconcileApi = {
  /** 取对账差异（含 degraded/error，W3）。 */
  getReconcile: async (repoId: string): Promise<ReconcileReport> => {
    return get<ReconcileReport>(`/repositories/${repoId}/reconcile/`)
  },

  /** 派发后台清理（202 + run_id），普通或敏感模式。 */
  cleanup: async (repoId: string, mode: CleanupMode): Promise<CleanupDispatch> => {
    return post<CleanupDispatch>(`/repositories/${repoId}/reconcile/`, { mode })
  },

  /** 拉取最近一次清理运行状态/结果（含敏感未清面 + caveat，W1/W2）。 */
  getCleanupStatus: async (repoId: string): Promise<CleanupRun> => {
    return get<CleanupRun>(`/repositories/${repoId}/reconcile/status/`)
  },
}
