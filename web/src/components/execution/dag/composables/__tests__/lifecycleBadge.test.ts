/**
 * 生命周期徽章视觉映射单测（Chassis v2 · P5）。
 *
 * 覆盖：相位 → 视觉一一映射、非法相位归一回退、status → 相位兜底推导、
 * 澄清/修订态「· 第 N/M 轮」文案。
 */

import { describe, expect, it } from 'vitest'
import {
  deriveLifecycleFromStatus,
  LIFECYCLE_VISUALS,
  type LifecyclePhase,
  lifecycleBadgeText,
  normalizeLifecyclePhase,
} from '../lifecycleBadge'

describe('lifecycleBadge - 视觉映射', () => {
  it('所有相位都有 label/badgeClass/dotClass', () => {
    const phases: LifecyclePhase[] = [
      'idle', 'running', 'waiting_clarification', 'revising',
      'produced', 'waiting_approval', 'done', 'failed',
    ]
    for (const p of phases) {
      const v = LIFECYCLE_VISUALS[p]
      expect(v.label).toBeTruthy()
      expect(v.badgeClass).toBeTruthy()
      expect(v.dotClass).toBeTruthy()
    }
  })

  it('语义色：running 蓝(primary) / waiting 琥珀 / revising 紫 / done·produced 绿 / failed 红', () => {
    expect(LIFECYCLE_VISUALS.running.dotClass).toContain('primary')
    expect(LIFECYCLE_VISUALS.waiting_clarification.dotClass).toContain('amber')
    expect(LIFECYCLE_VISUALS.waiting_approval.dotClass).toContain('amber')
    expect(LIFECYCLE_VISUALS.revising.dotClass).toContain('purple')
    expect(LIFECYCLE_VISUALS.done.dotClass).toContain('green')
    expect(LIFECYCLE_VISUALS.produced.dotClass).toContain('green')
    expect(LIFECYCLE_VISUALS.failed.dotClass).toContain('red')
  })
})

describe('lifecycleBadge - normalizeLifecyclePhase', () => {
  it('合法相位原样返回', () => {
    expect(normalizeLifecyclePhase('revising')).toBe('revising')
  })
  it('非法/空相位回退 idle', () => {
    expect(normalizeLifecyclePhase('bogus')).toBe('idle')
    expect(normalizeLifecyclePhase(null)).toBe('idle')
    expect(normalizeLifecyclePhase(undefined)).toBe('idle')
  })
})

describe('lifecycleBadge - deriveLifecycleFromStatus 兜底', () => {
  it.each([
    ['running', 'running'],
    ['waiting_event', 'running'],
    ['waiting_approval', 'waiting_approval'],
    ['waiting_input', 'waiting_clarification'],
    ['completed', 'done'],
    ['failed', 'failed'],
    ['timeout', 'failed'],
    ['pending', 'idle'],
    ['queued', 'idle'],
    ['skipped', 'idle'],
    [undefined, 'idle'],
  ] as const)('status=%s → %s', (status, expected) => {
    expect(deriveLifecycleFromStatus(status)).toBe(expected)
  })
})

describe('lifecycleBadge - lifecycleBadgeText 轮次文案', () => {
  it('修订态附带「· 第 N/M 轮」', () => {
    expect(lifecycleBadgeText('revising', 2, 6)).toBe('修订中 · 第 2/6 轮')
  })
  it('等澄清态附带轮次', () => {
    expect(lifecycleBadgeText('waiting_clarification', 1, 6)).toBe('等澄清 · 第 1/6 轮')
  })
  it('maxRounds 缺省回退 6', () => {
    expect(lifecycleBadgeText('revising', 3, null)).toBe('修订中 · 第 3/6 轮')
  })
  it('无轮次仅展示相位标签', () => {
    expect(lifecycleBadgeText('running')).toBe('运行中')
    expect(lifecycleBadgeText('produced')).toBe('已产出')
    expect(lifecycleBadgeText('revising', null)).toBe('修订中')
  })
})
