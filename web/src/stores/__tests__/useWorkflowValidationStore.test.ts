/**
 * useWorkflowValidationStore 单元测试（VAL-03）。
 *
 * 覆盖：addIssues 批量摄入后端 {errors,warnings}（severity + reason，node/edge 级）、
 * snake_case → camelCase 映射、errorCount/warningCount/hasErrors/hasIssues 计数、
 * clearAllIssues 清空、以及与既有 edge 级 warning API 的向后兼容。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkflowValidationStore } from '~/stores/useWorkflowValidationStore'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useWorkflowValidationStore - addIssues', () => {
  it('摄入混合 errors + warnings，计数正确', () => {
    const store = useWorkflowValidationStore()

    store.addIssues({
      errors: [
        { reason: 'cycle', severity: 'error', message: '工作流存在环' },
      ],
      warnings: [
        { reason: 'orphan_node', severity: 'warning', node_id: 'n1', message: '孤立节点' },
      ],
    })

    expect(store.issuesList.length).toBe(2)
    expect(store.errorCount).toBe(1)
    expect(store.warningCount).toBe(1)
    expect(store.hasErrors).toBe(true)
    expect(store.hasIssues).toBe(true)
  })

  it('snake_case 字段映射为 camelCase（node_id/edge_id/field_path）', () => {
    const store = useWorkflowValidationStore()

    store.addIssues({
      errors: [
        {
          reason: 'config_schema_invalid',
          severity: 'error',
          node_id: 'node-uuid-1',
          field_path: 'config.user_prompt',
          message: '配置不合法',
        },
      ],
    })

    const issue = store.issuesList[0]
    expect(issue.nodeId).toBe('node-uuid-1')
    expect(issue.fieldPath).toBe('config.user_prompt')
    expect(issue.reason).toBe('config_schema_invalid')
    expect(issue.severity).toBe('error')
    // 不应残留 snake_case 键
    expect((issue as Record<string, unknown>).node_id).toBeUndefined()
    expect((issue as Record<string, unknown>).field_path).toBeUndefined()
  })

  it('edge 级问题映射 edge_id 并可被 getIssuesForEdge 查找', () => {
    const store = useWorkflowValidationStore()

    store.addIssues({
      errors: [
        {
          reason: 'invalid_source_handle',
          severity: 'error',
          edge_id: 'edge-1',
          field_path: 'edges[0].source_handle',
          message: '源 handle 非法',
        },
      ],
    })

    const issue = store.issuesList[0]
    expect(issue.edgeId).toBe('edge-1')
    expect(store.getIssuesForEdge('edge-1').length).toBe(1)
    expect(store.getIssuesForEdge('not-exist').length).toBe(0)
  })

  it('每个 issue 生成唯一 id', () => {
    const store = useWorkflowValidationStore()

    store.addIssues({
      errors: [
        { reason: 'cycle', severity: 'error', message: 'a' },
        { reason: 'no_entry', severity: 'error', message: 'b' },
      ],
    })

    const ids = store.issuesList.map(i => i.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('缺省 errors/warnings 字段不报错', () => {
    const store = useWorkflowValidationStore()

    store.addIssues({ errors: [{ reason: 'cycle', severity: 'error', message: 'a' }] })
    expect(store.issuesList.length).toBe(1)

    store.addIssues({ warnings: [{ reason: 'orphan_node', severity: 'warning', message: 'b' }] })
    // addIssues 为追加语义（覆盖语义由 clearAllIssues 控制）
    expect(store.issuesList.length).toBe(2)

    store.addIssues({})
    expect(store.issuesList.length).toBe(2)
  })

  it('clearAllIssues 清空所有问题', () => {
    const store = useWorkflowValidationStore()

    store.addIssues({
      errors: [{ reason: 'cycle', severity: 'error', message: 'a' }],
      warnings: [{ reason: 'orphan_node', severity: 'warning', message: 'b' }],
    })
    expect(store.hasIssues).toBe(true)

    store.clearAllIssues()
    expect(store.issuesList.length).toBe(0)
    expect(store.hasIssues).toBe(false)
    expect(store.hasErrors).toBe(false)
    expect(store.errorCount).toBe(0)
    expect(store.warningCount).toBe(0)
  })
})

describe('useWorkflowValidationStore - 向后兼容 edge warning API', () => {
  it('addWarning / getWarningForEdge / clearAllWarnings 仍可用', () => {
    const store = useWorkflowValidationStore()

    store.addWarning({
      id: 'edge-1',
      edgeId: 'edge-1',
      type: 'schema_mismatch',
      message: '类型不匹配',
      sourceNodeId: 'node-1',
      targetNodeId: 'node-2',
    })

    expect(store.getWarningForEdge('edge-1')?.message).toBe('类型不匹配')
    expect(store.warningsList.length).toBe(1)

    store.clearAllWarnings()
    expect(store.getWarningForEdge('edge-1')).toBeUndefined()
  })
})
