/**
 * 仓库排除规则 API（Phase 22 fail-closed，EXCL-01）。
 *
 * 安全边界（DOMAIN §9.1）：被排除文件仅对 Friday 的索引/检索/agent/容器不可见，
 * **不承诺** 从 git 历史物理删除。
 */

import { del, get, post } from './client'

export type ExclusionRuleType = 'dir' | 'glob' | 'regex'

/** per-repo 排除规则（与后端 RepoExclusionRuleSerializer 对齐）。 */
export interface ExclusionRule {
  id: string
  pattern: string
  rule_type: ExclusionRuleType
  enabled: boolean
  source: string
  created_at: string
}

/** 只读全局默认（builtin ∪ 全局设置）；enabled=false 表示已被 per-repo override 关闭。 */
export interface GlobalDefaultRule {
  pattern: string
  rule_type: ExclusionRuleType
  source: 'global'
  enabled: boolean
  /** 关闭该全局默认的 override 行 id（用于再次启用 = 删除该行）；启用态为 null。 */
  override_id: string | null
}

export interface ExclusionListResponse {
  global_defaults: GlobalDefaultRule[]
  rules: ExclusionRule[]
}

export interface CreateExclusionPayload {
  pattern: string
  rule_type: ExclusionRuleType
  enabled?: boolean
  source?: string
}

export const exclusionsApi = {
  /** 列出仓库有效排除规则（全局默认 + per-repo）。 */
  list: async (repoId: string): Promise<ExclusionListResponse> => {
    return get<ExclusionListResponse>(`/repositories/${repoId}/exclusions/`)
  },

  /** 新增 per-repo 规则（或 source=global+enabled=false 的关闭 override）。 */
  create: async (repoId: string, payload: CreateExclusionPayload): Promise<ExclusionRule> => {
    return post<ExclusionRule>(`/repositories/${repoId}/exclusions/`, payload)
  },

  /** 删除 per-repo 规则（删除关闭 override 行 = 再次启用该全局默认）。 */
  remove: async (repoId: string, ruleId: string): Promise<void> => {
    await del(`/repositories/${repoId}/exclusions/${ruleId}/`)
  },
}
