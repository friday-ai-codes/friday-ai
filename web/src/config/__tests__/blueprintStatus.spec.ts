/**
 * blueprintStatus.ts 配置守护测试（Phase 115-02，形状照 `config/__tests__/status.spec.ts`）。
 *
 * 锁四件事：
 * 1. 12 态配置逐条与 UI-SPEC §13.9 一致（labelKey / 裸图标名 / variant / animate）；
 * 2. ⭐ `''`（v0 旧数据）命中 **legacy 档而非 unknown 兜底** —— 正反两条并列，任一档被写错
 *    都会转红；
 * 3. `isBlueprintEditable` 白名单成员逐字对齐后端 `EDITABLE_BLUEPRINT_STATUSES`；
 * 4. ⭐ 12 个 `labelKey` **全部能在 `zh-CN.json` 里查到** —— 这条把 i18n 子树与本配置的
 *    一一对应关系锁死（少写一个键、或改名后忘了同步，都会转红）。
 */
import { describe, expect, it } from 'vitest'
import zhCN from '~/locales/zh-CN.json'
import {
  BLUEPRINT_STATUS_CONFIG,
  EDITABLE_BLUEPRINT_STATUSES,
  getBlueprintStatusConfig,
  isBlueprintEditable,
  LIVE_BLUEPRINT_STATUSES,
  PRODUCED_BY_PREFIXES,
  producedByReason,
} from '../blueprintStatus'

const FALLBACK_ICON = 'lucide--help-circle'
const UNKNOWN_LABEL_KEY = 'knowledge.blueprints.statusUnknown'

/** UI-SPEC §13.9 的 12 行逐字镜像（`labelKey` 尾段 / 裸图标名 / variant / animate）。 */
const EXPECTED: Array<[string, string, string, string, boolean]> = [
  ['researching', 'researching', 'lucide--scan-eye', 'info', true],
  ['drafting', 'drafting', 'lucide--pen-line', 'info', true],
  ['ai_reviewing', 'ai_reviewing', 'lucide--shield-check', 'info', true],
  ['needs_clarification', 'needs_clarification', 'lucide--help-circle', 'warning', false],
  ['pending_review', 'pending_review', 'lucide--user-check', 'warning', false],
  ['confirmed', 'confirmed', 'lucide--check-circle', 'success', false],
  ['implementing', 'implementing', 'lucide--hammer', 'info', true],
  ['implemented', 'implemented', 'lucide--check-check', 'success', false],
  ['archived', 'archived', 'lucide--archive', 'muted', false],
  ['failed', 'failed', 'lucide--x-circle', 'destructive', false],
  ['superseded', 'superseded', 'lucide--file-x', 'muted', false],
  ['', 'legacy', 'lucide--file-text', 'outline', false],
]

/** 按点分路径取 i18n 值（缺键返回 undefined）。 */
function lookup(messages: unknown, key: string): unknown {
  return key.split('.').reduce<any>((node, part) => (node == null ? undefined : node[part]), messages)
}

describe('bLUEPRINT_STATUS_CONFIG —— 12 态逐条', () => {
  it('恰好 12 档（11 个状态机取值 + \'\'）', () => {
    expect(Object.keys(BLUEPRINT_STATUS_CONFIG)).toHaveLength(12)
  })

  it.each(EXPECTED)(
    'status %j → labelKey status.%s / icon %s / variant %s',
    (status, labelSuffix, icon, variant, animate) => {
      const config = getBlueprintStatusConfig(status)
      expect(config.labelKey).toBe(`knowledge.blueprints.status.${labelSuffix}`)
      // 裸图标名：⛔ 不带 `icon-[...]` 包装（拼接发生在组件内）。
      expect(config.icon).toBe(icon)
      expect(config.icon).not.toMatch(/^icon-\[/)
      expect(config.variant).toBe(variant)
      expect(Boolean(config.animate)).toBe(animate)
    },
  )

  it('配置里不存中文 label，只存 i18n key', () => {
    for (const config of Object.values(BLUEPRINT_STATUS_CONFIG)) {
      expect(config).not.toHaveProperty('label')
      expect(config.labelKey.startsWith('knowledge.blueprints.status.')).toBe(true)
    }
  })
})

describe('getBlueprintStatusConfig 兜底 —— \'\' 与未知态必须分开', () => {
  it('\'\' 命中 legacy 档（v0 旧数据是合法输入，⛔ 不走 unknown）', () => {
    const config = getBlueprintStatusConfig('')
    expect(config.labelKey).toBe('knowledge.blueprints.status.legacy')
    expect(config.icon).toBe('lucide--file-text')
    expect(config.icon).not.toBe(FALLBACK_ICON)
    expect(config.variant).toBe('outline')
  })

  it('未登记的取值命中 unknown 兜底（与上一条并列，结论必须不同）', () => {
    const config = getBlueprintStatusConfig('__unknown__')
    expect(config.labelKey).toBe(UNKNOWN_LABEL_KEY)
    expect(config.icon).toBe(FALLBACK_ICON)
    expect(config.variant).toBe('muted')
    // 变异提示：若 `''` 被写成真值判定（如 `CONFIG[status] || FALLBACK`），上一条即转红。
    expect(config.labelKey).not.toBe(getBlueprintStatusConfig('').labelKey)
  })
})

describe('isBlueprintEditable —— 白名单内外各三条', () => {
  it('白名单恰好六值且与后端逐字一致', () => {
    expect([...EDITABLE_BLUEPRINT_STATUSES].sort()).toEqual(
      ['', 'ai_reviewing', 'drafting', 'needs_clarification', 'pending_review', 'researching'],
    )
  })

  it.each(['', 'drafting', 'pending_review'])('可编辑：%j', (status) => {
    expect(isBlueprintEditable(status)).toBe(true)
  })

  it.each(['confirmed', 'implementing', 'archived'])('不可编辑：%s', (status) => {
    expect(isBlueprintEditable(status)).toBe(false)
  })
})

describe('lIVE_BLUEPRINT_STATUSES —— 轮询三态', () => {
  it('恰好三态，且 pending_review 与终态不在内', () => {
    // 116 续驱队列化：needs_clarification 也轮询——作答后状态推进发生在 worker，
    // 页面靠轮询看到下一个状态。
    expect([...LIVE_BLUEPRINT_STATUSES].sort()).toEqual(['ai_reviewing', 'drafting', 'needs_clarification', 'researching'])
    for (const status of ['pending_review', 'confirmed', 'implemented', 'archived', 'failed', 'superseded', ''])
      expect(LIVE_BLUEPRINT_STATUSES.has(status)).toBe(false)
  })
})

describe('producedByReason —— 四前缀 + AI 产出兜底共五档', () => {
  it('登记了四个前缀', () => {
    expect(PRODUCED_BY_PREFIXES.map(([prefix]) => prefix)).toEqual([
      'human_edit:',
      'ai_review_reflow:',
      'human_block_restore:',
      'blueprint_review_reject:',
    ])
  })

  it.each([
    ['human_edit:u-1', 'reasonHumanEdit', 'lucide--user-pen', 'secondary'],
    ['ai_review_reflow:thread-1', 'reasonAiReviewReflow', 'lucide--refresh-cw', 'info'],
    ['human_block_restore:b-1', 'reasonHumanBlockRestore', 'lucide--shield', 'warning'],
    ['blueprint_review_reject:r-1', 'reasonBlueprintReviewReject', 'lucide--undo-2', 'destructive'],
    ['stage:merge', 'reasonAiGenerated', 'lucide--sparkles', 'muted'],
  ])('produced_by_ref %j → %s', (ref, labelSuffix, icon, variant) => {
    const config = producedByReason(ref)
    expect(config.labelKey).toBe(`knowledge.blueprints.version.${labelSuffix}`)
    expect(config.icon).toBe(icon)
    expect(config.variant).toBe(variant)
  })

  it('空串与非字符串一律走 AI 产出兜底', () => {
    expect(producedByReason('').labelKey).toBe('knowledge.blueprints.version.reasonAiGenerated')
    expect(producedByReason(undefined as unknown as string).labelKey).toBe(
      'knowledge.blueprints.version.reasonAiGenerated',
    )
  })
})

describe('i18n key 对齐 —— 配置里的每个 labelKey 都能在 zh-CN.json 里查到', () => {
  it('12 个状态 labelKey 全部可解析', () => {
    for (const [status, config] of Object.entries(BLUEPRINT_STATUS_CONFIG)) {
      const value = lookup(zhCN, config.labelKey)
      expect(typeof value, `状态 ${JSON.stringify(status)} 的 ${config.labelKey} 在 zh-CN.json 里查不到`).toBe('string')
      expect(value).not.toBe('')
    }
  })

  it('unknown 兜底与五档版本原因的 labelKey 同样可解析', () => {
    expect(typeof lookup(zhCN, UNKNOWN_LABEL_KEY)).toBe('string')
    for (const ref of ['human_edit:x', 'ai_review_reflow:x', 'human_block_restore:x', 'blueprint_review_reject:x', ''])
      expect(typeof lookup(zhCN, producedByReason(ref).labelKey)).toBe('string')
  })

  it('status 子树恰好 12 键，与配置一一对应', () => {
    const subtree = lookup(zhCN, 'knowledge.blueprints.status') as Record<string, string>
    expect(Object.keys(subtree)).toHaveLength(12)
    const expected = new Set(
      Object.values(BLUEPRINT_STATUS_CONFIG).map(c => c.labelKey.split('.').pop()),
    )
    expect(new Set(Object.keys(subtree))).toEqual(expected)
  })
})
