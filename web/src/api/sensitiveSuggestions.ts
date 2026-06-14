/**
 * 敏感文件 AI 识别建议 API（Phase 24 sensitive-ai-detect，EXCL-03）。
 *
 * 安全边界（DOMAIN §9.1 / §9，D-03/D-04）：
 * - 建议为只读视图，状态仅经专用 accept/dismiss action 变更（后端不允许直接 PATCH）。
 * - `accept` 仅幂等创建 `RepoExclusionRule(source=ai_suggested)`，**绝不**静默删除
 *   已索引/派生数据——删除仍由 Phase 23 reconcile/cleanup 由用户显式发起。
 * - `reason` 已脱敏：只含命中类型与行号，**绝不**回显密钥本体（T-24-11）。
 */

import { get, post } from './client'

/** 建议严重程度：真实密钥 > 疑似敏感 > 建议复核（列表按此优先级排序）。 */
export type SensitiveSeverity = 'real_secret' | 'likely_sensitive' | 'config_review'
/** 检出来源：启发式 / 内容扫描 / LLM。 */
export type SensitiveDetector = 'heuristic' | 'content' | 'llm'
/** 建议状态：待处理 / 已接受 / 已忽略。 */
export type SensitiveStatus = 'pending' | 'accepted' | 'dismissed'

/** 单条敏感文件建议（与后端 SensitiveFileSuggestionSerializer 对齐，全字段只读）。 */
export interface SensitiveSuggestion {
  id: string
  path: string
  severity: SensitiveSeverity
  detector: SensitiveDetector
  /** 已脱敏的命中说明（仅命中类型 + 行号，不含密钥本体）。 */
  reason: string
  status: SensitiveStatus
  detected_at: string
  updated_at: string
}

export interface SensitiveSuggestionListResponse {
  suggestions: SensitiveSuggestion[]
}

/** accept 返回所建排除规则；dismiss 仅返回更新后的建议。 */
export interface SensitiveActionResponse {
  suggestion: SensitiveSuggestion
  rule?: {
    id: string
    pattern: string
    rule_type: string
    source: string
  }
  /** accept 时为 true：仅作前端引导提示，accept 本身**不**自动清理。 */
  cleanup_available?: boolean
}

export const sensitiveSuggestionsApi = {
  /** 列出某仓库 AI 敏感文件建议（默认仅 pending；severity 优先排序，后端已排序）。 */
  list: async (
    repoId: string,
    status?: SensitiveStatus | 'all',
  ): Promise<SensitiveSuggestionListResponse> => {
    const query = status ? `?status=${status}` : ''
    return get<SensitiveSuggestionListResponse>(
      `/repositories/${repoId}/sensitive-suggestions/${query}`,
    )
  },

  /** 接受建议：幂等建 ai_suggested 排除规则（绝不删数据，需在清理面板显式清理）。 */
  accept: async (repoId: string, id: string): Promise<SensitiveActionResponse> => {
    return post<SensitiveActionResponse>(
      `/repositories/${repoId}/sensitive-suggestions/${id}/action/`,
      { action: 'accept' },
    )
  },

  /** 忽略建议：仅置 dismissed，不建规则、不删数据。 */
  dismiss: async (repoId: string, id: string): Promise<SensitiveActionResponse> => {
    return post<SensitiveActionResponse>(
      `/repositories/${repoId}/sensitive-suggestions/${id}/action/`,
      { action: 'dismiss' },
    )
  },
}
