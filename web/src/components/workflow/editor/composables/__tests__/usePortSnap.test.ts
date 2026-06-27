/**
 * usePortSnap 端口吸附几何单测（SLOT-03）。
 *
 * 覆盖：
 * - 兼容候选在阈值内 → 返回最近 handle 端点；多个命中取最近。
 * - 不兼容候选即便在阈值内 → 跳过（compatible=false 不吸附）。
 * - zoom 换算：zoom=0.5 屏幕 28px 对应 flow 56px（边界命中/不命中）。
 * - 无候选 / 全超距 / 非法 zoom 防御。
 * - 守护：PORT_SNAP_THRESHOLD=28 独立常量；useAlignmentGuides 的 SNAP_THRESHOLD 仍=5（未被本 plan 改动）。
 */
import type { SnapCandidate } from '../usePortSnap'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { findSnapTarget, PORT_SNAP_THRESHOLD } from '../usePortSnap'

describe('端口吸附阈值 PORT_SNAP_THRESHOLD 独立常量', () => {
  it('端口吸附阈值 = 28px（屏幕像素）', () => {
    expect(PORT_SNAP_THRESHOLD).toBe(28)
  })

  it('useAlignmentGuides 的 SNAP_THRESHOLD 仍 = 5（节点对齐零回归，未被本 plan 改动）', () => {
    // vitest cwd = web/；从源根定位 useAlignmentGuides.ts（import.meta.url 在该 env 下非 file:// scheme）。
    const src = readFileSync(
      resolve(process.cwd(), 'src/components/workflow/editor/composables/useAlignmentGuides.ts'),
      'utf-8',
    )
    expect(src).toContain('const SNAP_THRESHOLD = 5')
  })
})

describe('findSnapTarget 命中/跳过/最近', () => {
  it('兼容候选在阈值内 → 返回其中心端点（zoom=1）', () => {
    const candidates: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 10, y: 0, compatible: true },
    ]
    const hit = findSnapTarget({ x: 0, y: 0 }, candidates, 1)
    expect(hit).toEqual({ nodeId: 'n1', handleId: 'in', x: 10, y: 0 })
  })

  it('多个兼容命中 → 取欧氏距离最近者', () => {
    const candidates: SnapCandidate[] = [
      { nodeId: 'far', handleId: 'a', x: 20, y: 0, compatible: true },
      { nodeId: 'near', handleId: 'b', x: 5, y: 0, compatible: true },
    ]
    const hit = findSnapTarget({ x: 0, y: 0 }, candidates, 1)
    expect(hit?.nodeId).toBe('near')
  })

  it('不兼容候选即便在阈值内 → 跳过（不吸附）', () => {
    const candidates: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 2, y: 0, compatible: false },
    ]
    expect(findSnapTarget({ x: 0, y: 0 }, candidates, 1)).toBeNull()
  })

  it('兼容候选超出阈值 → 不命中（28px 边界外）', () => {
    const candidates: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 29, y: 0, compatible: true },
    ]
    expect(findSnapTarget({ x: 0, y: 0 }, candidates, 1)).toBeNull()
  })

  it('恰在阈值上（dist===28, zoom=1）→ 命中（含边界）', () => {
    const candidates: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 28, y: 0, compatible: true },
    ]
    expect(findSnapTarget({ x: 0, y: 0 }, candidates, 1)?.nodeId).toBe('n1')
  })

  it('空候选 → null', () => {
    expect(findSnapTarget({ x: 0, y: 0 }, [], 1)).toBeNull()
  })
})

describe('zoom 换算（屏幕阈值恒定，flow 距离随缩放变化）', () => {
  it('zoom=0.5：屏幕 28px 对应 flow 56px → 50px 命中、57px 不命中', () => {
    const within: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 50, y: 0, compatible: true },
    ]
    const beyond: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 57, y: 0, compatible: true },
    ]
    expect(findSnapTarget({ x: 0, y: 0 }, within, 0.5)?.nodeId).toBe('n1')
    expect(findSnapTarget({ x: 0, y: 0 }, beyond, 0.5)).toBeNull()
  })

  it('zoom=2：屏幕 28px 对应 flow 14px → 13px 命中、15px 不命中', () => {
    const within: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 13, y: 0, compatible: true },
    ]
    const beyond: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 15, y: 0, compatible: true },
    ]
    expect(findSnapTarget({ x: 0, y: 0 }, within, 2)?.nodeId).toBe('n1')
    expect(findSnapTarget({ x: 0, y: 0 }, beyond, 2)).toBeNull()
  })

  it('非法 zoom（0 / 负 / NaN）→ 回退按屏幕阈值（zoom=1 口径）不除零', () => {
    const candidates: SnapCandidate[] = [
      { nodeId: 'n1', handleId: 'in', x: 20, y: 0, compatible: true },
    ]
    expect(findSnapTarget({ x: 0, y: 0 }, candidates, 0)?.nodeId).toBe('n1')
    expect(findSnapTarget({ x: 0, y: 0 }, candidates, -1)?.nodeId).toBe('n1')
    expect(findSnapTarget({ x: 0, y: 0 }, candidates, Number.NaN)?.nodeId).toBe('n1')
  })
})
