/**
 * `[rule_id]` 前缀解析用例（quick-260806-vqh）。
 *
 * 守四件事：
 * 1. 有前缀 ⇒ 拆出 `ruleId` 且正文不带方括号那段；
 * 2. ⭐ 中文前缀（`[已修复]`）**不被误剥** —— 字符集与后端 `_RULE_ID_TAG` 同款是前提；
 * 3. 无前缀 / 空值 ⇒ 原样返回，`ruleId` 空串；
 * 4. ⭐ 已知规则集合与后端 `blueprint_review.py` 的 22 条对齐，未知 id 判 `false`
 *    （调用方据此回落原始 id，⛔ 不吞）；
 * 5. ⭐ **漂移守卫**：每个 rule_id 在 `zh-CN.json` 里都查得到标签 —— 少一条就会让那类
 *    finding 在页面上退回英文 id，而这正是本次要消灭的东西（范式照
 *    `config/__tests__/blueprintStatus.spec.ts`）。
 */

import { describe, expect, it } from 'vitest'
import zhCN from '~/locales/zh-CN.json'
import {
  FINDING_RULE_IDS,
  isKnownFindingRule,
  parseFindingBody,
} from '../blueprintFindingRules'

describe('parseFindingBody', () => {
  it('拆出 rule_id 并剥掉前缀与其后空白', () => {
    const parsed = parseFindingBody('[acceptance_uncovered] 当前节点轻高亮引导未见独立测试策略')
    expect(parsed.ruleId).toBe('acceptance_uncovered')
    expect(parsed.text).toBe('当前节点轻高亮引导未见独立测试策略')
  })

  it('下划线与数字都在字符集内', () => {
    expect(parseFindingBody('[gate_lock_violation_role] 角色偏离').ruleId).toBe(
      'gate_lock_violation_role',
    )
    expect(parseFindingBody('[rule2] x').ruleId).toBe('rule2')
  })

  it('⭐ 中文前缀不被误剥（后端处置留痕本就是人话）', () => {
    const body = '[已修复] 人审复核：该缺口已在后续融合轮次补齐'
    const parsed = parseFindingBody(body)
    expect(parsed.ruleId).toBe('')
    expect(parsed.text).toBe(body)
  })

  it('无前缀 / 非首位方括号 ⇒ 原样返回', () => {
    const followUp = '第 2 轮仍存在：功能点C无独立测试策略'
    expect(parseFindingBody(followUp)).toEqual({ ruleId: '', text: followUp })

    const midway = '正文里提到 [acceptance_uncovered] 不算前缀'
    expect(parseFindingBody(midway).ruleId).toBe('')
  })

  it('空值与非字符串恒不抛', () => {
    expect(parseFindingBody('')).toEqual({ ruleId: '', text: '' })
    expect(parseFindingBody(undefined)).toEqual({ ruleId: '', text: '' })
    expect(parseFindingBody(null)).toEqual({ ruleId: '', text: '' })
  })
})

describe('isKnownFindingRule', () => {
  it('⭐ 与后端 blueprint_review.py 的 22 条 rule_id 对齐', () => {
    expect(FINDING_RULE_IDS).toHaveLength(22)
    expect(new Set(FINDING_RULE_IDS).size).toBe(22)
    for (const ruleId of FINDING_RULE_IDS)
      expect(isKnownFindingRule(ruleId)).toBe(true)
  })

  it('未知 id 与空串判 false（调用方回落原始 id）', () => {
    expect(isKnownFindingRule('brand_new_rule')).toBe(false)
    expect(isKnownFindingRule('')).toBe(false)
  })
})

describe('i18n 漂移守卫 —— 每个 rule_id 都有中文标签', () => {
  const labels = (zhCN as any).knowledge.blueprints.thread.rule as Record<string, string>

  it.each(FINDING_RULE_IDS)('%s 在 zh-CN.json 里查得到', (ruleId) => {
    expect(typeof labels[ruleId], `${ruleId} 缺中文标签，会在页面上退回英文 id`).toBe('string')
    expect(labels[ruleId].length).toBeGreaterThan(0)
  })

  it('⛔ 语言文件里没有多余标签（后端删规则时前端要跟着删）', () => {
    expect(Object.keys(labels).sort()).toEqual([...FINDING_RULE_IDS].sort())
  })
})
