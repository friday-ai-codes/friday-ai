import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SUBSCRIBE_SIGNAL,
  getEmptySlotHint,
  getSubscribableSignals,
  normalizeSubscribeSignals,
  SIG_ARTIFACT_PRODUCED,
  SIG_NODE_COMPLETED,
  SIG_NODE_FAILED,
  supportsSignalSubscription,
  toggleSubscribeSignal,
} from '../slotTaxonomy'

/**
 * SLOT P4 信号反应器：slotTaxonomy 的「可订阅信号集合」+ 归一化/切换/默认 纯函数单测。
 * 这些纯函数是「附着插件存 metadata.subscribeSignals」+「后端 config_sync 转 reaction」
 * 的前端事实源，须锁死语义（过滤非法、空回退默认、至少订阅一个、稳定排序）。
 */

describe('getSubscribableSignals / supportsSignalSubscription', () => {
  it('notification/document 可订阅 成功/失败/产出；clarification 不可订阅', () => {
    expect(getSubscribableSignals('notification')).toContain(SIG_NODE_COMPLETED)
    expect(getSubscribableSignals('notification')).toContain(SIG_NODE_FAILED)
    expect(getSubscribableSignals('notification')).toContain(SIG_ARTIFACT_PRODUCED)
    expect(getSubscribableSignals('document').length).toBeGreaterThan(0)
    expect(getSubscribableSignals('clarification')).toEqual([])

    expect(supportsSignalSubscription('notification')).toBe(true)
    expect(supportsSignalSubscription('document')).toBe(true)
    expect(supportsSignalSubscription('clarification')).toBe(false)
  })
})

describe('normalizeSubscribeSignals', () => {
  it('过滤非该能力可订阅的非法值并去重', () => {
    const out = normalizeSubscribeSignals('notification', [
      'node.completed',
      'bogus',
      'node.completed',
      'node.failed',
    ])
    expect(out).toEqual([SIG_NODE_COMPLETED, SIG_NODE_FAILED])
  })

  it('空数组 / undefined / 全非法 → 回退默认完成信号', () => {
    expect(normalizeSubscribeSignals('notification', [])).toEqual([DEFAULT_SUBSCRIBE_SIGNAL])
    expect(normalizeSubscribeSignals('notification', undefined)).toEqual([DEFAULT_SUBSCRIBE_SIGNAL])
    expect(normalizeSubscribeSignals('notification', ['nope', 'bad'])).toEqual([DEFAULT_SUBSCRIBE_SIGNAL])
    expect(DEFAULT_SUBSCRIBE_SIGNAL).toBe(SIG_NODE_COMPLETED)
  })

  it('clarification 不支持订阅 → 恒空（即便传入合法信号）', () => {
    expect(normalizeSubscribeSignals('clarification', ['node.completed'])).toEqual([])
  })

  it('按 CAPABILITY_SIGNALS 顺序稳定排序（与输入顺序无关）', () => {
    const out = normalizeSubscribeSignals('notification', ['node.failed', 'node.completed'])
    const order = getSubscribableSignals('notification')
    expect(out).toEqual(order.filter(s => out.includes(s)))
  })
})

describe('toggleSubscribeSignal', () => {
  it('新增未选信号', () => {
    const out = toggleSubscribeSignal('notification', ['node.completed'], SIG_NODE_FAILED)
    expect(out).toContain(SIG_NODE_COMPLETED)
    expect(out).toContain(SIG_NODE_FAILED)
  })

  it('取消已选信号', () => {
    const out = toggleSubscribeSignal('notification', ['node.completed', 'node.failed'], SIG_NODE_FAILED)
    expect(out).toEqual([SIG_NODE_COMPLETED])
  })

  it('不允许取消最后一个信号（至少订阅一个）', () => {
    const out = toggleSubscribeSignal('notification', ['node.completed'], SIG_NODE_COMPLETED)
    expect(out).toEqual([SIG_NODE_COMPLETED])
  })

  it('忽略非该能力可订阅的信号', () => {
    // document 切换一个其本身支持的信号正常；切换不存在的信号则返回归一化原集合
    const out = toggleSubscribeSignal('notification', ['node.completed'], 'bogus' as any)
    expect(out).toEqual([SIG_NODE_COMPLETED])
  })

  it('从默认（未设）开始切换：先归一为默认完成，再叠加', () => {
    const out = toggleSubscribeSignal('notification', undefined, SIG_NODE_FAILED)
    expect(out).toContain(SIG_NODE_COMPLETED)
    expect(out).toContain(SIG_NODE_FAILED)
  })
})

describe('getEmptySlotHint', () => {
  it('支持订阅的能力追加「（默认订阅完成）」注脚', () => {
    expect(getEmptySlotHint('notification')).toContain('（默认订阅完成）')
    expect(getEmptySlotHint('document')).toContain('（默认订阅完成）')
  })

  it('不支持订阅的能力不追加注脚', () => {
    expect(getEmptySlotHint('clarification')).not.toContain('（默认订阅完成）')
  })
})
