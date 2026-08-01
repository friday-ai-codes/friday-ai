/**
 * blueprintArtifact.ts 配置守护（同步点 2 收尾 · 三处触点共用的判别与中文文案）。
 *
 * 锁四件事：
 * 1. ⭐ **漂移守卫**：`BLUEPRINT_STATUS_TEXT` 与 `zh-CN.json` 的
 *    `knowledge.blueprints.status.*` **逐键逐字相等**，兜底文案与 `statusUnknown` 相等。
 *    两份定义只能靠这一条不漂移（i18n 面与内联中文面的消费者不同，⛔ 不合并）。
 * 2. 键集与 `BLUEPRINT_STATUS_CONFIG` **完全一致**（12 档：11 个状态机取值 + `''`）。
 * 3. ⭐ `''` 命中「旧版方案」而**不是**未知兜底；未知取值命中兜底 —— **正反并列**，
 *    只断言一侧会漏掉「全都走兜底」的假通过。
 * 4. `isBlueprintSchemaVersion` 是**允许清单**：只有 `'blueprint/v1'` 为真，
 *    `'blueprint/v2'` / `''` / `undefined` / `null` / 对象一律为假。
 */
import { describe, expect, it } from 'vitest'
import zhCN from '~/locales/zh-CN.json'
import {
  BLUEPRINT_ATTENTION_STATUSES,
  BLUEPRINT_SCHEMA_VERSION,
  BLUEPRINT_STATUS_TEXT,
  BLUEPRINT_STATUS_UNKNOWN_TEXT,
  blueprintStatusText,
  blueprintViewerPath,
  isBlueprintSchemaVersion,
} from '../blueprintArtifact'
import { BLUEPRINT_STATUS_CONFIG } from '../blueprintStatus'

/** `''` 在 i18n 子树下的键名是 `legacy`（配置里是空串键）。 */
const I18N_KEY_OF: Record<string, string> = { '': 'legacy' }

describe('bLUEPRINT_STATUS_TEXT —— 与 i18n 子树的漂移守卫', () => {
  it('键集与 BLUEPRINT_STATUS_CONFIG 完全一致（12 档）', () => {
    expect(Object.keys(BLUEPRINT_STATUS_TEXT).sort()).toEqual(
      Object.keys(BLUEPRINT_STATUS_CONFIG).sort(),
    )
    expect(Object.keys(BLUEPRINT_STATUS_TEXT)).toHaveLength(12)
  })

  it.each(Object.keys(BLUEPRINT_STATUS_TEXT))(
    'status %j 的中文与 zh-CN.json 逐字相等',
    (status) => {
      const leaf = I18N_KEY_OF[status] ?? status
      expect(BLUEPRINT_STATUS_TEXT[status]).toBe(
        (zhCN as any).knowledge.blueprints.status[leaf],
      )
    },
  )

  it('兜底文案与 statusUnknown 逐字相等', () => {
    expect(BLUEPRINT_STATUS_UNKNOWN_TEXT).toBe((zhCN as any).knowledge.blueprints.statusUnknown)
  })
})

describe('blueprintStatusText —— 空串与未知的正反并列', () => {
  it('\'\' 命中「旧版方案」而不是未知兜底', () => {
    expect(blueprintStatusText('')).toBe('旧版方案')
    expect(blueprintStatusText('')).not.toBe(BLUEPRINT_STATUS_UNKNOWN_TEXT)
  })

  it('表外取值命中未知兜底', () => {
    expect(blueprintStatusText('brand_new_status')).toBe(BLUEPRINT_STATUS_UNKNOWN_TEXT)
  })

  it('两个「等人处置」状态在集合内，其余不在', () => {
    expect([...BLUEPRINT_ATTENTION_STATUSES].sort()).toEqual([
      'needs_clarification',
      'pending_review',
    ])
    expect(BLUEPRINT_ATTENTION_STATUSES.has('confirmed')).toBe(false)
  })
})

describe('isBlueprintSchemaVersion —— 允许清单', () => {
  it('只有 blueprint/v1 为真', () => {
    expect(BLUEPRINT_SCHEMA_VERSION).toBe('blueprint/v1')
    expect(isBlueprintSchemaVersion('blueprint/v1')).toBe(true)
  })

  it.each([['blueprint/v2'], [''], [undefined], [null], [{}], [1]])(
    '%j 一律为假（未知 schema 走 v0 旧链渲染）',
    (value) => {
      expect(isBlueprintSchemaVersion(value)).toBe(false)
    },
  )
})

describe('blueprintViewerPath', () => {
  it('拼出 115-06 的查看器路由', () => {
    expect(blueprintViewerPath('art-1')).toBe('/knowledge/blueprints/art-1')
  })
})
