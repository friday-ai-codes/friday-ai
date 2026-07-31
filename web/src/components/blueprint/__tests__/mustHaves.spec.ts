/**
 * 验收锚点段的组件测试（Phase 115-05，⭐ UI-SPEC §20 断言 9）。
 *
 * 覆盖路径（编号与 115-05-PLAN Task 3 ④逐条对应）：
 *  1. ⭐ 断言 9 上半 —— 三子块都非空 ⇒ `blueprint-must-haves` 存在，且 truths / artifacts /
 *     key_links 三块各自渲染出与数组等长的条目。
 *     **变异一**：漏渲 `must_haves`（组件返回空）⇒ 本条转红。
 *  2. ⭐ 断言 9 下半 —— 该段内 `blueprint-annotation-mark` 计数 == 0（本段不接批注层）。
 *     **变异二**：给它接上批注层（渲染划线标记）⇒ 本条转红。
 *  3. ⭐ 不复用 `BlueprintBlockList`（它的契约前提是块有 `block_id`，而本段零 `block_id`）。
 *  4. 三块全空 / 整键缺失（v0 旧数据）⇒ 组件不渲染任何内容卡。
 *  5. 部分子块为空（只有 truths）⇒ truths 渲染、artifacts 与 key_links 不渲染（正反并列）。
 *  6. 缺键条目（`artifacts: [{}]` / `key_links: [{}]`）⇒ 渲染「—」且不抛、文本不含 undefined。
 *
 * 测试范式照 `components/prompts/__tests__/PromptVersionDiff.test.ts`（覆盖路径清单 + 工厂 +
 * 正负成对 + `data-*` 定位）与 `pages/knowledge/__tests__/entity-detail.spec.ts`
 * （手写最小 i18n 键树，⛔ 不 import `zh-CN.json`）。
 */

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import MustHavesSection from '~/components/blueprint/sections/MustHavesSection.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          mustHaves: {
            truths: '可观察行为断言',
            artifacts: '必须存在的产物',
            keyLinks: '关键链接',
            colPath: '路径',
            colProvides: '提供能力',
            colFrom: '来源',
            colTo: '去向',
            colVia: '通过',
            empty: '本方案未登记验收锚点',
          },
        },
      },
    },
  },
})

function mountSection(mustHaves: unknown) {
  return mount(MustHavesSection, {
    props: { mustHaves: mustHaves as never },
    global: { plugins: [i18n] },
  })
}

const FULL_MUST_HAVES = {
  truths: ['登录后能看到方案列表', '驳回后蓝图回到产出中'],
  artifacts: [
    { path: 'web/src/components/blueprint/sections/MustHavesSection.vue', provides: '验收锚点三子块' },
    { path: 'web/src/components/blueprint/RepoAssociationCard.vue', provides: '仓库关联卡' },
  ],
  key_links: [
    { from: 'RepoAssociationsSection.vue', to: 'BlueprintBlockList.vue', via: 'blockCtx 原样透传' },
  ],
}

describe('mustHavesSection —— §20 断言 9', () => {
  it('1. ⭐ 三子块都非空 ⇒ 段被渲染，且三块条目数与数组等长', () => {
    const wrapper = mountSection(FULL_MUST_HAVES)

    expect(wrapper.find('[data-testid="blueprint-must-haves"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="blueprint-must-haves-truths"] li')).toHaveLength(
      FULL_MUST_HAVES.truths.length,
    )
    expect(wrapper.findAll('[data-testid="blueprint-must-haves-artifact-row"]')).toHaveLength(
      FULL_MUST_HAVES.artifacts.length,
    )
    expect(wrapper.findAll('[data-testid="blueprint-must-haves-key-link-row"]')).toHaveLength(
      FULL_MUST_HAVES.key_links.length,
    )
  })

  it('2. ⭐ 段内划线标记计数 == 0（本段不接批注层）', () => {
    const wrapper = mountSection(FULL_MUST_HAVES)

    expect(wrapper.findAll('[data-testid="blueprint-annotation-mark"]')).toHaveLength(0)
    expect(wrapper.html()).not.toContain('blueprint-annotation-mark')
  })

  it('3. ⭐ 不复用 BlueprintBlockList（本段零 block_id）', () => {
    const wrapper = mountSection(FULL_MUST_HAVES)

    expect(wrapper.findComponent({ name: 'BlueprintBlockList' }).exists()).toBe(false)
    expect(wrapper.html()).not.toContain('blueprint-block-list')
  })

  it('4a. 三块全空 ⇒ 不渲染任何内容卡', () => {
    const wrapper = mountSection({ truths: [], artifacts: [], key_links: [] })

    expect(wrapper.find('[data-testid="blueprint-must-haves"]').exists()).toBe(false)
  })

  it('4b. 整键缺失（v0 旧数据）⇒ 不渲染任何内容卡且不抛', () => {
    expect(() => mountSection(null)).not.toThrow()
    expect(mountSection(null).find('[data-testid="blueprint-must-haves"]').exists()).toBe(false)
    expect(mountSection({}).find('[data-testid="blueprint-must-haves"]').exists()).toBe(false)
  })

  it('5. 部分子块为空 ⇒ 该子块不渲染、其余照渲（正反并列）', () => {
    const wrapper = mountSection({ truths: ['只有断言'], artifacts: [], key_links: [] })

    expect(wrapper.find('[data-testid="blueprint-must-haves"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-must-haves-truths"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-must-haves-artifacts"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-must-haves-key-links"]').exists()).toBe(false)
  })

  it('6. 缺键条目 ⇒ 渲染「—」、不抛、文本不含 undefined', () => {
    const wrapper = mountSection({ truths: [], artifacts: [{}], key_links: [{}] })

    const text = wrapper.text()
    expect(text).toContain('—')
    expect(text).not.toContain('undefined')
    expect(wrapper.findAll('[data-testid="blueprint-must-haves-artifact-row"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="blueprint-must-haves-key-link-row"]')).toHaveLength(1)
  })

  it('7. 非字符串 truths 条目被剔除而不是渲染成 undefined', () => {
    const wrapper = mountSection({ truths: ['真断言', null, 42], artifacts: [], key_links: [] })

    expect(wrapper.findAll('[data-testid="blueprint-must-haves-truths"] li')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('undefined')
  })
})
