/**
 * `files_touched[].action` 展示口径单测（quick-260806：动作徽标中文化）。
 *
 * 守三件事：
 *  1. 正典三档 + 同义 token（edit/delete/add/update…）归一到同一标签键与色档；
 *  2. 未知 token 标签键返回 null（消费方原样透出，⛔ 不猜）、variant 退 outline；
 *  3. 大小写与首尾空白不敏感。
 */

import { describe, expect, it } from 'vitest'
import { fileActionLabelKeyOf, fileActionVariantOf } from '~/utils/blueprintImplItems'

describe('fileActionLabelKeyOf / fileActionVariantOf', () => {
  it.each([
    ['create', 'changeTypeCreate', 'success'],
    ['add', 'changeTypeCreate', 'success'],
    ['new', 'changeTypeCreate', 'success'],
    ['modify', 'changeTypeModify', 'info'],
    ['edit', 'changeTypeModify', 'info'],
    ['update', 'changeTypeModify', 'info'],
    ['change', 'changeTypeModify', 'info'],
    ['remove', 'changeTypeRemove', 'destructive'],
    ['delete', 'changeTypeRemove', 'destructive'],
  ])('⭐ %s → 标签键 %s / 色档 %s', (action, labelKey, variant) => {
    expect(fileActionLabelKeyOf(action)).toBe(labelKey)
    expect(fileActionVariantOf(action)).toBe(variant)
  })

  it('大小写与首尾空白不敏感', () => {
    expect(fileActionLabelKeyOf(' Edit ')).toBe('changeTypeModify')
    expect(fileActionVariantOf('CREATE')).toBe('success')
  })

  it('未知 token：标签键 null（原样透出）、variant 退 outline', () => {
    expect(fileActionLabelKeyOf('refactor')).toBeNull()
    expect(fileActionVariantOf('refactor')).toBe('outline')
    expect(fileActionLabelKeyOf(undefined)).toBeNull()
    expect(fileActionVariantOf(undefined)).toBe('outline')
    expect(fileActionLabelKeyOf('')).toBeNull()
  })
})
