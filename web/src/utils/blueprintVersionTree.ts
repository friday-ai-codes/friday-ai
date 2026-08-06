/**
 * 版本谱系树派生（quick-260806 节点重跑 → 版本树切换器）。
 *
 * ⭐ **纯函数、零 Vue 依赖**：与 `blueprintBlocks.buildStageTimeline` 同一范式 —— 分组逻辑
 * 必须能被单测直接喂版本数组，⛔ 不写进组件。
 *
 * 分组规则（与后端 `version_label` 的谱系语义对齐）：
 * - 同一 `version_label` 的多个版本归一组，组内按 `version_no` 降序、**最新一条为代表**；
 * - label `"2.1"` 的父级是 `"2"`（取第一个 `.` 之前的段作根）；
 * - 空 label（旧数据未打标）回落 `v{version_no}` 作展示 label，且**各自成组**（旧版本之间
 *   没有谱系信息，硬并到一组只会捏造不存在的血缘）。
 */

import type { BlueprintStageVersionRow } from '~/types/blueprint'

/** 同一 `version_label` 的版本组（组内按 `version_no` 降序）。 */
export interface VersionTreeGroup {
  /** 原始 label（空串 = 旧数据）。 */
  label: string
  /** 展示 label：非空取 `v{label}`，空 label 回落 `v{version_no}`。 */
  displayLabel: string
  /** 谱系根（`"2.1"` → `"2"`；空 label 组的根是自己的展示 label）。 */
  rootLabel: string
  /** 组代表 = 组内 `version_no` 最大的一条（切换器的默认落点）。 */
  representative: BlueprintStageVersionRow
  /** 组内全部版本，`version_no` 降序。 */
  entries: BlueprintStageVersionRow[]
  /** 组内是否含当前版本。 */
  hasCurrent: boolean
}

/** 谱系根节点：根 label + 其下全部 label 组。 */
export interface VersionTreeRoot {
  rootLabel: string
  /** 根下的组：根 label 本体在前，其余按代表 `version_no` 降序。 */
  groups: VersionTreeGroup[]
  /** 该根下最大的 `version_no`（根间排序用）。 */
  latestVersionNo: number
  /**
   * 旧数据根（组全部无 label）：渲染时**不出「谱系 X」组头**——旧版本之间没有谱系信息，
   * 每版本配一个组头是 100% 重复噪音（「谱系 v10」+「v10」）。
   */
  legacy: boolean
}

/** 版本条目的展示 label（组件与纯函数共用同一口径）。 */
export function versionDisplayLabel(version: Pick<BlueprintStageVersionRow, 'version_label' | 'version_no'>): string {
  const label = String(version.version_label ?? '').trim()
  return label ? `v${label}` : `v${version.version_no}`
}

/** label 的谱系根段（`"2.1"` → `"2"`；无点号即自身）。 */
function rootOf(label: string): string {
  return label.split('.')[0] ?? label
}

/**
 * 把版本清单折成谱系树：根按最新活动降序，组内最新为代表。
 *
 * 任何形状的输入都不抛：空数组返回空树；缺 label 的条目按旧数据处理。
 */
export function buildVersionTree(
  versions: readonly BlueprintStageVersionRow[] | undefined,
): VersionTreeRoot[] {
  const groupsByKey = new Map<string, VersionTreeGroup>()

  for (const version of versions ?? []) {
    const label = String(version.version_label ?? '').trim()
    // 空 label 各自成组：用 version_id 保证互不合并（旧版本之间没有谱系信息）。
    const key = label || `__legacy__${version.version_id}`
    const existing = groupsByKey.get(key)
    if (existing) {
      existing.entries.push(version)
      continue
    }
    groupsByKey.set(key, {
      label,
      displayLabel: versionDisplayLabel(version),
      rootLabel: label ? rootOf(label) : versionDisplayLabel(version),
      representative: version,
      entries: [version],
      hasCurrent: false,
    })
  }

  const groups = [...groupsByKey.values()].map((group) => {
    const entries = [...group.entries].sort((a, b) => b.version_no - a.version_no)
    return {
      ...group,
      entries,
      representative: entries[0],
      hasCurrent: entries.some(entry => entry.is_current),
    }
  })

  const rootsByLabel = new Map<string, VersionTreeRoot>()
  for (const group of groups) {
    const root = rootsByLabel.get(group.rootLabel) ?? {
      rootLabel: group.rootLabel,
      groups: [],
      latestVersionNo: 0,
      legacy: true,
    }
    root.groups.push(group)
    root.latestVersionNo = Math.max(root.latestVersionNo, group.representative.version_no)
    root.legacy = root.legacy && !group.label
    rootsByLabel.set(group.rootLabel, root)
  }

  const roots = [...rootsByLabel.values()]
  for (const root of roots) {
    // 根 label 本体（如 "2"）排最前，其余子 label（"2.1" / "2.2"…）按代表版本号降序。
    root.groups.sort((a, b) => {
      const aIsRoot = a.label === root.rootLabel ? 0 : 1
      const bIsRoot = b.label === root.rootLabel ? 0 : 1
      return aIsRoot - bIsRoot || b.representative.version_no - a.representative.version_no
    })
  }
  // 根间按最新活动降序：最近产生版本的谱系排最上面。
  return roots.sort((a, b) => b.latestVersionNo - a.latestVersionNo)
}
