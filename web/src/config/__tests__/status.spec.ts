/**
 * status.spec.ts — OBS-03 ExecutionStatus 全覆盖 RED 测试
 *
 * 断言每个后端 ExecutionStatus 值在前端 `getStatusConfig('execution', ...)`
 * 都有非 fallback 的 badge 配置。当前 `executionStatusConfig` 缺 `suspended`
 * （Pitfall 7：前端枚举与后端 SSOT 漂移），故 suspended 相关用例为 RED，
 * 由 Wave 1（21-07）实现转 GREEN。
 */
import { describe, expect, it } from 'vitest'
import { getStatusConfig } from '../status'

// 后端 ExecutionStatus 全集（SSOT 镜像）
// 来源：server/workflows/models/execution.py L17-27
// pending / running / paused / suspended / completed / failed / cancelled / timeout
const EXECUTION_STATUSES = [
  'pending',
  'running',
  'paused',
  'suspended',
  'completed',
  'failed',
  'cancelled',
  'timeout',
] as const

const FALLBACK_ICON = 'lucide--help-circle'

describe('getStatusConfig(\'execution\', ...) — OBS-03 状态枚举全覆盖', () => {
  it('test_every_execution_status_has_non_fallback_badge', () => {
    // 遍历后端 ExecutionStatus 全集，断言每个状态都有专属 badge（非 fallback）
    for (const status of EXECUTION_STATUSES) {
      const config = getStatusConfig('execution', status)
      // fallback 的 label 等于原始 status 字符串、icon 为 help-circle
      expect(config.label, `状态 ${status} 缺少中文 label（命中 fallback）`).not.toBe(status)
      expect(config.icon, `状态 ${status} 命中 fallback icon`).not.toBe(FALLBACK_ICON)
    }
  })

  it('test_suspended_badge_present', () => {
    // 专项：suspended 当前缺失（RED），实现后应有中文 label
    const config = getStatusConfig('execution', 'suspended')
    expect(config.label).toBe('挂起中')
    expect(config.icon).not.toBe(FALLBACK_ICON)
  })

  it('test_unknown_status_falls_back', () => {
    // 保护既有 fallback 行为（GREEN）：未知状态走兜底
    const config = getStatusConfig('execution', 'bogus')
    expect(config.label).toBe('bogus')
    expect(config.icon).toBe(FALLBACK_ICON)
  })
})
