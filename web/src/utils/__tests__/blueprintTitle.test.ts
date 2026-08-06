import { describe, expect, it } from 'vitest'
import { formatBlueprintListTime, formatBlueprintTitle } from '~/utils/blueprintTitle'

describe('formatBlueprintTitle', () => {
  it('与后端模板一致（UTC → 上海墙钟）', () => {
    // 2026-08-06 01:33 UTC → 上海 09:33
    expect(formatBlueprintTitle('高三提分专项', '2026-08-06T01:33:00Z'))
      .toBe('高三提分专项 - 技术方案 - 2026-08-06 09:33')
  })

  it('空项目名回落「未关联项目」', () => {
    expect(formatBlueprintTitle('', '2026-08-06T01:33:00Z'))
      .toBe('未关联项目 - 技术方案 - 2026-08-06 09:33')
    expect(formatBlueprintTitle(null, '2026-08-06T01:33:00Z'))
      .toBe('未关联项目 - 技术方案 - 2026-08-06 09:33')
    expect(formatBlueprintTitle('   ', '2026-08-06T01:33:00Z'))
      .toBe('未关联项目 - 技术方案 - 2026-08-06 09:33')
  })
})

describe('formatBlueprintListTime', () => {
  it('固定 YYYY-MM-DD HH:mm，不含秒', () => {
    const text = formatBlueprintListTime('2026-08-06T01:33:45.123Z')
    expect(text).toBe('2026-08-06 09:33')
    expect(text).not.toMatch(/:\d{2}:\d{2}/)
    expect(text.split(':')).toHaveLength(2)
  })

  it('非法 / 空输入回落空串', () => {
    expect(formatBlueprintListTime(null)).toBe('')
    expect(formatBlueprintListTime(undefined)).toBe('')
    expect(formatBlueprintListTime('not-a-date')).toBe('')
  })
})
