/**
 * 版本谱系树派生的纯函数单测（quick-260806 节点重跑 → 版本树切换器）。
 *
 * 守五件事：
 *  1. 同 label 归一组、组内 `version_no` 降序、最新为代表；
 *  2. `"2.1"` 的根是 `"2"`，根 label 本体排组首；
 *  3. 空 label 回落 `v{version_no}` 且各自成组（旧版本之间不捏造血缘）；
 *  4. `hasCurrent` 跟随组内任一 `is_current`；
 *  5. 根按最新活动降序（最近产生版本的谱系排最上）。
 */

import type { BlueprintStageVersionRow } from '~/types/blueprint'
import { describe, expect, it } from 'vitest'
import { buildVersionTree, versionDisplayLabel } from '~/utils/blueprintVersionTree'

function version(overrides: Partial<BlueprintStageVersionRow>): BlueprintStageVersionRow {
  return {
    version_id: `id-${overrides.version_no ?? 0}`,
    version_no: 0,
    version_label: '',
    produced_by_ref: 'ai',
    created_at: '2026-08-01T00:00:00Z',
    is_current: false,
    ...overrides,
  }
}

describe('versionDisplayLabel', () => {
  it('非空 label 取 v{label}，空 label 回落 v{version_no}', () => {
    expect(versionDisplayLabel(version({ version_no: 3, version_label: '2.1' }))).toBe('v2.1')
    expect(versionDisplayLabel(version({ version_no: 3, version_label: '' }))).toBe('v3')
    expect(versionDisplayLabel(version({ version_no: 5, version_label: '  ' }))).toBe('v5')
  })
})

describe('buildVersionTree', () => {
  it('空输入返回空树，不抛错', () => {
    expect(buildVersionTree(undefined)).toEqual([])
    expect(buildVersionTree([])).toEqual([])
  })

  it('⭐ 同 label 归一组：组内 version_no 降序、最新为代表', () => {
    const tree = buildVersionTree([
      version({ version_id: 'a', version_no: 1, version_label: '1' }),
      version({ version_id: 'b', version_no: 3, version_label: '1' }),
      version({ version_id: 'c', version_no: 2, version_label: '1' }),
    ])
    expect(tree).toHaveLength(1)
    const group = tree[0].groups[0]
    expect(group.entries.map(entry => entry.version_no)).toEqual([3, 2, 1])
    expect(group.representative.version_id).toBe('b')
    expect(group.displayLabel).toBe('v1')
  })

  it('⭐ "2.1" 的根是 "2"，根 label 本体排组首、子 label 随后', () => {
    const tree = buildVersionTree([
      version({ version_id: 'a', version_no: 4, version_label: '2' }),
      version({ version_id: 'b', version_no: 5, version_label: '2.1' }),
      version({ version_id: 'c', version_no: 6, version_label: '2.2' }),
    ])
    expect(tree).toHaveLength(1)
    expect(tree[0].rootLabel).toBe('2')
    // 根本体（"2"）恒排组首，其余子 label 按代表版本号降序。
    expect(tree[0].groups.map(group => group.label)).toEqual(['2', '2.2', '2.1'])
  })

  it('⭐ 空 label 各自成组（⛔ 不把旧版本硬并成一组），展示回落 v{version_no}', () => {
    const tree = buildVersionTree([
      version({ version_id: 'a', version_no: 1, version_label: '' }),
      version({ version_id: 'b', version_no: 2, version_label: '' }),
    ])
    const groups = tree.flatMap(root => root.groups)
    expect(groups).toHaveLength(2)
    expect(groups.map(group => group.displayLabel).sort()).toEqual(['v1', 'v2'])
    for (const group of groups)
      expect(group.entries).toHaveLength(1)
  })

  it('⭐ legacy 标记：空 label 根为 true（组件据此不渲染「谱系 X」组头），带 label 根为 false', () => {
    const tree = buildVersionTree([
      version({ version_id: 'a', version_no: 1, version_label: '' }),
      version({ version_id: 'b', version_no: 2, version_label: '2' }),
    ])
    const byRoot = new Map(tree.map(root => [root.rootLabel, root]))
    expect(byRoot.get('v1')?.legacy).toBe(true)
    expect(byRoot.get('2')?.legacy).toBe(false)
  })

  it('hasCurrent 跟随组内任一 is_current', () => {
    const tree = buildVersionTree([
      version({ version_id: 'a', version_no: 1, version_label: '1' }),
      version({ version_id: 'b', version_no: 2, version_label: '1', is_current: true }),
      version({ version_id: 'c', version_no: 3, version_label: '2' }),
    ])
    const byLabel = new Map(tree.flatMap(root => root.groups).map(group => [group.label, group]))
    expect(byLabel.get('1')?.hasCurrent).toBe(true)
    expect(byLabel.get('2')?.hasCurrent).toBe(false)
  })

  it('⭐ 根按最新活动降序：最近产生版本的谱系排最上', () => {
    const tree = buildVersionTree([
      version({ version_id: 'a', version_no: 1, version_label: '1' }),
      version({ version_id: 'b', version_no: 4, version_label: '1.1' }),
      version({ version_id: 'c', version_no: 3, version_label: '2' }),
    ])
    // 谱系 "1" 的最新版本号 4 > 谱系 "2" 的 3 ⇒ "1" 在前。
    expect(tree.map(root => root.rootLabel)).toEqual(['1', '2'])
  })
})
