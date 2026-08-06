/**
 * 功能点口径工具单测（quick-260806）。
 *
 * 重点守卫 `matchFeaturePointsToRenderedLines` 的顺序贪婪语义：
 * 同名标题按文档顺序各归其行、未匹配点不推进游标、输入为渲染坐标行表。
 */

import { describe, expect, it } from 'vitest'
import {
  cleanFeaturePointTitle,
  intentLabelKeyOf,
  intentVariantOf,
  matchFeaturePointsToRenderedLines,
} from '~/utils/blueprintFeaturePoints'
import { buildMarkdownRender } from '~/utils/blueprintMarkdownLite'

describe('intent 口径', () => {
  it('三档映射 + 未知档回落 outline / null', () => {
    expect(intentVariantOf('greenfield')).toBe('success')
    expect(intentVariantOf('brownfield')).toBe('info')
    expect(intentVariantOf('fix')).toBe('warning')
    expect(intentVariantOf('mystery')).toBe('outline')
    expect(intentLabelKeyOf('greenfield')).toBe('intentGreenfield')
    expect(intentLabelKeyOf('mystery')).toBeNull()
  })

  it('cleanFeaturePointTitle 只剥行首记号', () => {
    expect(cleanFeaturePointTitle('#### 功能点 B: 返回')).toBe('功能点 B: 返回')
    expect(cleanFeaturePointTitle('入口 # 排序')).toBe('入口 # 排序')
  })
})

describe('matchFeaturePointsToRenderedLines', () => {
  /** 用真实渲染模型驱动（与 BlueprintBlock 消费路径同源）。 */
  function matchOn(source: string, points: Array<{ id: string, title?: string, intent?: string }>) {
    const model = buildMarkdownRender(source)
    return matchFeaturePointsToRenderedLines(model.rendered, model.lines, points)
  }

  const SOURCE = [
    '## 模块 3: 学习页',
    '#### 功能点 A: 页面结构',
    '- 验收 1',
    '#### 掌握程度浮层',
    '## 模块 4: 真题检测',
    '#### 掌握程度浮层',
    '- 验收 2',
  ].join('\n')

  it('1. 标题行命中：记号剥除后与标题精确相等才算', () => {
    const result = matchOn(SOURCE, [
      { id: 'fp_1', title: '功能点 A: 页面结构', intent: 'greenfield' },
    ])
    expect(result.size).toBe(1)
    expect([...result.values()][0]).toMatchObject({ pointId: 'fp_1', intent: 'greenfield' })
  })

  it('2. ⭐ 同名标题顺序归位：fp_2/fp_3 各占自己模块下的那一行', () => {
    const result = matchOn(SOURCE, [
      { id: 'fp_1', title: '功能点 A: 页面结构', intent: 'greenfield' },
      { id: 'fp_2', title: '掌握程度浮层', intent: 'greenfield' },
      { id: 'fp_3', title: '掌握程度浮层', intent: 'brownfield' },
    ])
    const ids = [...result.values()].map(tag => tag.pointId)
    expect(ids).toEqual(['fp_1', 'fp_2', 'fp_3'])
    // 行起点单调递增 ⇒ 三个标签落在不同的行上且保持文档顺序
    const starts = [...result.keys()]
    expect(starts).toEqual([...starts].sort((a, b) => a - b))
  })

  it('3. 未匹配点不推进游标：中间缺席不影响后续点归位', () => {
    const result = matchOn(SOURCE, [
      { id: 'fp_1', title: '不存在的标题', intent: 'greenfield' },
      { id: 'fp_2', title: '掌握程度浮层', intent: 'fix' },
    ])
    expect([...result.values()].map(tag => tag.pointId)).toEqual(['fp_2'])
  })

  it('4. 标题带残留行首 # 记号也能命中（cleanFeaturePointTitle 兜底）', () => {
    const result = matchOn(SOURCE, [
      { id: 'fp_1', title: '#### 功能点 A: 页面结构', intent: 'greenfield' },
    ])
    expect(result.size).toBe(1)
  })

  it('5. 空输入恒空 map', () => {
    expect(matchOn(SOURCE, []).size).toBe(0)
    expect(matchFeaturePointsToRenderedLines('', [], [{ id: 'fp_1', title: 'x' }]).size).toBe(0)
  })
})
