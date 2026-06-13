import type { WorkflowEdge } from '~/types/workflow/store'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * Validation warning for a workflow connection (edge-level, legacy)
 *
 * 保留用于边视觉提示（schema_mismatch）。新链路统一走 {@link ValidationIssue}。
 */
export interface ValidationWarning {
  /** Warning ID (usually edge ID) */
  id: string
  /** The edge with the warning */
  edgeId: string
  /** Warning type */
  type: 'schema_mismatch'
  /** Human-readable message */
  message: string
  /** Source node ID */
  sourceNodeId: string
  /** Target node ID */
  targetNodeId: string
}

/**
 * 后端 `WorkflowGraphValidator` 的单条校验问题（camelCase 形态）。
 *
 * 对应后端 `ValidationIssue`（snake_case），由 {@link useWorkflowValidationStore.addIssues}
 * 在摄入时映射键名。`reason` 直接透传后端枚举值，前端不重命名：
 * `node_not_found` / `field_not_found` / `cycle` / `no_entry` / `orphan_node` /
 * `edge_node_missing` / `invalid_source_handle` / `invalid_target_handle` /
 * `config_schema_invalid` / `unknown_node_type` ...
 */
export interface ValidationIssue {
  /** 前端生成的稳定唯一 ID（edgeId/nodeId/index 组合） */
  id: string
  /** 失败原因分类，透传后端 reason 枚举 */
  reason: string
  /** error 阻断保存 / warning 仅提示 */
  severity: 'error' | 'warning'
  /** 人类可读描述（仅含拓扑/键名/reason，不含 config 取值） */
  message: string
  /** 问题定位（如 "config.user_prompt" / "edges[2].source_handle"） */
  fieldPath?: string
  /** 涉及的节点 ID */
  nodeId?: string
  /** 涉及的边 ID */
  edgeId?: string
}

/** 后端 ValidationIssue 的原始 snake_case 形态（addIssues 入参） */
interface BackendValidationIssue {
  reason?: string
  severity?: string
  message?: string
  field_path?: string
  node_id?: string | null
  edge_id?: string | null
}

/** 后端 `{errors, warnings}` 结构（dry-run 200 / bulk-update 400 body） */
export interface BackendValidationResult {
  errors?: BackendValidationIssue[]
  warnings?: BackendValidationIssue[]
}

/**
 * Centralized validation state management for workflow validation
 *
 * 聚合两类校验数据：
 * - `issues`：后端 `WorkflowGraphValidator` 的结构化结果（severity + reason，node/edge 级），
 *   驱动 IssuesPanel 真实渲染，保存非法图时由 `saveWorkflow` 摄入。
 * - `warnings`：边级 schema_mismatch 视觉提示（legacy，向后兼容）。
 *
 * @example
 * ```ts
 * const validationStore = useWorkflowValidationStore()
 *
 * // 摄入后端校验结果（400 body 或 dry-run 响应）
 * validationStore.addIssues({
 *   errors: [{ reason: 'cycle', severity: 'error', message: '工作流存在环' }],
 *   warnings: [{ reason: 'orphan_node', severity: 'warning', node_id: 'n1', message: '孤立节点' }],
 * })
 *
 * // 面板渲染
 * validationStore.issuesList.forEach(i => render(i))
 * ```
 */
export const useWorkflowValidationStore = defineStore('workflowValidation', () => {
  // ==========================================================================
  // 结构化校验问题（后端 WorkflowGraphValidator 结果，驱动 IssuesPanel）
  // ==========================================================================
  const issues = ref<ValidationIssue[]>([])

  const issuesList = computed((): ValidationIssue[] => issues.value)

  const errorCount = computed((): number =>
    issues.value.filter(i => i.severity === 'error').length,
  )

  const warningCount = computed((): number =>
    issues.value.filter(i => i.severity === 'warning').length,
  )

  const hasIssues = computed((): boolean => issues.value.length > 0)

  const hasErrors = computed((): boolean => errorCount.value > 0)

  /**
   * 查找某条边相关的结构化问题（edge 级视觉定位）
   * @param edgeId - 边 ID
   */
  function getIssuesForEdge(edgeId: string): ValidationIssue[] {
    return issues.value.filter(i => i.edgeId === edgeId)
  }

  /** 把单条后端 snake_case 问题映射为前端 ValidationIssue */
  function mapBackendIssue(
    raw: BackendValidationIssue,
    severity: 'error' | 'warning',
    index: number,
  ): ValidationIssue {
    const nodeId = raw.node_id ?? undefined
    const edgeId = raw.edge_id ?? undefined
    const fieldPath = raw.field_path || undefined
    const reason = raw.reason ?? 'unknown'
    // 稳定唯一 ID：优先 edge/node + field_path/reason，再以 index 兜底去重
    const scope = edgeId ?? nodeId ?? 'graph'
    const id = `${severity}:${scope}:${fieldPath ?? reason}:${index}`

    return {
      id,
      reason,
      severity: (raw.severity as 'error' | 'warning') ?? severity,
      message: raw.message ?? '',
      fieldPath,
      nodeId,
      edgeId,
    }
  }

  /**
   * 批量摄入后端 `{errors, warnings}`（追加语义；清空请用 clearAllIssues）
   * @param payload - 后端校验结果（dry-run 响应或 bulk-update 400 body）
   */
  function addIssues(payload: BackendValidationResult): void {
    const mapped: ValidationIssue[] = []
    const errors = payload.errors ?? []
    const warnings = payload.warnings ?? []

    errors.forEach((raw, idx) => {
      mapped.push(mapBackendIssue(raw, 'error', idx))
    })
    warnings.forEach((raw, idx) => {
      mapped.push(mapBackendIssue(raw, 'warning', errors.length + idx))
    })

    if (mapped.length > 0) {
      issues.value = [...issues.value, ...mapped]
    }
  }

  /** 清空所有结构化校验问题 */
  function clearAllIssues(): void {
    issues.value = []
  }

  // ==========================================================================
  // 边级 schema_mismatch 视觉提示（legacy，向后兼容）
  // ==========================================================================
  const warnings = ref<Map<string, ValidationWarning>>(new Map())

  const warningsList = computed((): ValidationWarning[] => {
    return Array.from(warnings.value.values())
  })

  /**
   * Get warning for a specific edge
   * @param edgeId - The edge ID to look up
   * @returns The warning if exists, undefined otherwise
   */
  function getWarningForEdge(edgeId: string): ValidationWarning | undefined {
    return warnings.value.get(edgeId)
  }

  /**
   * Add or update an edge warning
   * @param warning - The warning to add
   */
  function addWarning(warning: ValidationWarning): void {
    warnings.value.set(warning.edgeId, warning)
  }

  /**
   * Remove a warning by edge ID
   * @param edgeId - The edge ID to remove warning for
   */
  function removeWarning(edgeId: string): void {
    warnings.value.delete(edgeId)
  }

  /**
   * Clear all edge warnings
   */
  function clearAllWarnings(): void {
    warnings.value.clear()
  }

  /**
   * Sync warnings with current edges
   * Removes orphaned warnings for edges that no longer exist
   * @param edges - Current edges in the workflow
   */
  function syncWithEdges(edges: WorkflowEdge[]): void {
    const edgeIds = new Set(edges.map(e => e.id))

    for (const edgeId of warnings.value.keys()) {
      if (!edgeIds.has(edgeId)) {
        warnings.value.delete(edgeId)
      }
    }
  }

  return {
    // Structured issues (backend validator)
    issues,
    issuesList,
    errorCount,
    warningCount,
    hasIssues,
    hasErrors,
    getIssuesForEdge,
    addIssues,
    clearAllIssues,
    // Legacy edge warnings
    warnings,
    warningsList,
    getWarningForEdge,
    addWarning,
    removeWarning,
    clearAllWarnings,
    syncWithEdges,
  }
})
