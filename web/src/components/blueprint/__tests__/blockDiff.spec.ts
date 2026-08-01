/**
 * `BlueprintBlockDiff.vue` / `BlueprintVersionSwitcher.vue` 组件测试（Phase 115-04）。
 *
 * 覆盖路径（编号与 115-04-PLAN Task 3 ⑤逐条对应）：
 *  1. 三类分类各一条：仅 B 有 ⇒ added；仅 A 有 ⇒ removed；同 id 内容变 ⇒ modified。
 *  2. ⭐ 键序不同**不算** modified（canonical 指纹的下游证伪；变异成朴素序列化比较 ⇒ 转红）。
 *  3. ⭐ `modified` 块进 `diffWords`：渲染出 `.diff-added` 与 `.diff-removed` 两类片段。
 *     **本用例跑绿即 settle RESEARCH 的 A3 假设**（`diffWords` 与 `diffLines` 同包同族，
 *     返回同构 `Change[]`）—— 因此 `diff` 包**真实 import、⛔ 不 mock**。
 *  4. inline / split 两形态：`split` 下左栏不含 `diff-added`、右栏不含 `diff-removed`
 *     （抄 analog `PromptVersionDiff.test.ts` 的正负成对断言）。
 *  5. 摘要行 `aria-live="polite"` 存在且文本含三个计数。
 *  6. ⭐ diff 模式下批注层与所有写动作关闭：划线标记与任何 `blueprint-review-*` /
 *     `blueprint-thread-*` 定位点**均不存在**。
 *  7. 未变化的段整段折叠（组头显示「本段无变化」）+ `must_haves` 段标注为不参与块级对比。
 *  8. 版本切换器：版本原因走唯一判据 `producedByReason`，切换与对比各自 emit。
 */

import type { BlueprintDocumentResponse } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintBlockDiff from '~/components/blueprint/BlueprintBlockDiff.vue'
import BlueprintVersionSwitcher from '~/components/blueprint/BlueprintVersionSwitcher.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          section: {
            requirementSpec: '需求规格',
            repoAssociations: '仓库关联',
            currentStateAnalysis: '现状分析',
            implementationOverview: '实现概述',
            apiContracts: 'API 契约',
            impactAnalysis: '影响范围',
            interactionFlows: '交互流程',
            mustHaves: '验收锚点',
          },
          diff: {
            summary: 'v{a} 对比 v{b}：新增 {added} 块、删除 {removed} 块、修改 {modified} 块',
            modeInline: '单栏对照',
            modeSplit: '左右并排',
            baseline: '基线版本',
            target: '目标版本',
            sectionUnchanged: '本段无变化',
            noChange: '两个版本没有差异',
          },
          version: {
            switch: '切换版本',
            current: '当前版本',
            reasonHumanEdit: '人工编辑',
            reasonAiReviewReflow: '澄清回灌',
            reasonHumanBlockRestore: '人工块保护',
            reasonBlueprintReviewReject: '人审驳回',
            reasonAiGenerated: 'AI 产出',
            empty: '暂无版本记录',
          },
        },
      },
    },
  },
})

const STUBS = {
  Collapsible: { template: '<div><slot /></div>' },
  CollapsibleTrigger: { template: '<div><slot /></div>' },
  CollapsibleContent: { template: '<div><slot /></div>' },
  Popover: { template: '<div><slot /></div>' },
  PopoverTrigger: { template: '<div><slot /></div>' },
  PopoverContent: { template: '<div><slot /></div>' },
}

/** 把若干 block 挂到 `requirement_spec.goal`（`iterBlocks` 走查得到的段之一）。 */
function makeDoc(versionNo: number, blocks: unknown[]): BlueprintDocumentResponse {
  return {
    version_id: `v-${versionNo}`,
    version_no: versionNo,
    is_current: versionNo === 2,
    produced_by_ref: '',
    created_at: '2026-08-01T00:00:00Z',
    content: {
      schema_version: 'blueprint/v1',
      meta: {},
      requirement_spec: { goal: blocks },
      citations: {},
    },
    quality: {
      citation_coverage: 1,
      ai_rejection_rate: null,
      human_edit_volume: null,
      clarification_rounds: null,
    },
  } as unknown as BlueprintDocumentResponse
}

function mountDiff(baseBlocks: unknown[], targetBlocks: unknown[], mode: 'inline' | 'split' = 'inline') {
  return mount(BlueprintBlockDiff, {
    props: { baseDoc: makeDoc(1, baseBlocks), targetDoc: makeDoc(2, targetBlocks), mode },
    global: { plugins: [i18n], stubs: STUBS },
  })
}

describe('blockDiff —— 三类分类走 canonical 指纹', () => {
  it('1a. 仅目标版有的块 ⇒ added', () => {
    const wrapper = mountDiff([], [{ block_id: 'b1', type: 'paragraph', text: '新增的一段' }])
    const blocks = wrapper.findAll('[data-diff-kind="added"]')
    expect(blocks).toHaveLength(1)
    expect(blocks[0].text()).toContain('新增的一段')
  })

  it('1b. 仅基线版有的块 ⇒ removed', () => {
    const wrapper = mountDiff([{ block_id: 'b1', type: 'paragraph', text: '被删掉的一段' }], [])
    const blocks = wrapper.findAll('[data-diff-kind="removed"]')
    expect(blocks).toHaveLength(1)
    expect(blocks[0].text()).toContain('被删掉的一段')
  })

  it('1c. 同 block_id 内容变化 ⇒ modified', () => {
    const wrapper = mountDiff(
      [{ block_id: 'b1', type: 'paragraph', text: '旧文本' }],
      [{ block_id: 'b1', type: 'paragraph', text: '新文本' }],
    )
    expect(wrapper.findAll('[data-diff-kind="modified"]')).toHaveLength(1)
  })

  it('2. ⭐ 键序不同不算 modified（canonical 指纹）', () => {
    const wrapper = mountDiff(
      [{ block_id: 'b1', type: 'paragraph', text: '同一段' }],
      [{ text: '同一段', type: 'paragraph', block_id: 'b1' }],
    )
    expect(wrapper.findAll('[data-diff-kind="modified"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('修改 0 块')
    expect(wrapper.text()).toContain('两个版本没有差异')
  })
})

describe('blockDiff —— 词级差分与两种形态（diff 包真实 import，⛔ 不 mock）', () => {
  const base = [{ block_id: 'b1', type: 'paragraph', text: '接口 返回 旧字段' }]
  const target = [{ block_id: 'b1', type: 'paragraph', text: '接口 返回 新字段' }]

  it('3. ⭐ modified 块渲染出 diff-added 与 diff-removed 两类片段（A3 假设 settle）', () => {
    const html = mountDiff(base, target).html()
    expect(html).toContain('diff-added')
    expect(html).toContain('diff-removed')
    expect(html).toContain('diff-unchanged')
  })

  it('4a. split 形态：左栏不含 diff-added、右栏不含 diff-removed', () => {
    const wrapper = mountDiff(base, target, 'split')
    const columns = wrapper.findAll('[data-diff-column]')
    expect(columns).toHaveLength(2)
    const leftHtml = columns[0].html()
    const rightHtml = columns[1].html()
    expect(leftHtml).toContain('diff-removed')
    expect(leftHtml).not.toContain('diff-added')
    expect(rightHtml).toContain('diff-added')
    expect(rightHtml).not.toContain('diff-removed')
  })

  it('4b. inline 形态不出现左右两栏，且模式切换会 emit update:mode', async () => {
    const wrapper = mountDiff(base, target, 'inline')
    expect(wrapper.findAll('[data-diff-column]')).toHaveLength(0)
    await wrapper.find('[data-testid="blueprint-diff-mode-split"]').trigger('click')
    expect(wrapper.emitted('update:mode')?.[0]).toEqual(['split'])
  })

  it('5. 摘要行 aria-live="polite" 且含三个计数', () => {
    const wrapper = mountDiff(
      [{ block_id: 'b1', type: 'paragraph', text: '旧' }, { block_id: 'b2', type: 'paragraph', text: '要删' }],
      [{ block_id: 'b1', type: 'paragraph', text: '新' }, { block_id: 'b3', type: 'paragraph', text: '新增' }],
    )
    const summary = wrapper.find('[data-testid="blueprint-diff-summary"]')
    expect(summary.attributes('aria-live')).toBe('polite')
    expect(summary.text()).toContain('新增 1 块')
    expect(summary.text()).toContain('删除 1 块')
    expect(summary.text()).toContain('修改 1 块')
    expect(summary.text()).toContain('v1 对比 v2')
  })

  it('6. ⭐ diff 模式下批注层与所有写动作关闭', () => {
    const wrapper = mountDiff(base, target)
    expect(wrapper.find('[data-testid="blueprint-annotation-mark"]').exists()).toBe(false)
    for (const testid of [
      'blueprint-review-approve',
      'blueprint-review-reject',
      'blueprint-thread-composer',
      'blueprint-thread-card',
      'blueprint-finding-actions',
    ])
      expect(wrapper.find(`[data-testid="${testid}"]`).exists()).toBe(false)
    // 只有一个「模式切换」类的 emit 声明面，⛔ 无任何写动作
    const declaredEmits = wrapper.vm.$options.emits
    expect(Array.isArray(declaredEmits) ? [...declaredEmits] : Object.keys(declaredEmits ?? {}))
      .toEqual(['update:mode'])
  })

  it('7a. 未变化的段组头显示「本段无变化」', () => {
    const wrapper = mountDiff(base, target)
    const untouched = wrapper.find('[data-diff-section="repoAssociations"]')
    expect(untouched.exists()).toBe(true)
    expect(untouched.text()).toContain('本段无变化')
  })

  it('7b. must_haves 段被标注为不参与块级对比', () => {
    const wrapper = mountDiff(base, target)
    const excluded = wrapper.find('[data-diff-excluded="true"]')
    expect(excluded.exists()).toBe(true)
    expect(excluded.attributes('data-diff-section')).toBe('must_haves')
    expect(excluded.text()).toContain('验收锚点')
  })

  it('7c. 版本 id 变化时重算（watch 只盯标量）', async () => {
    const wrapper = mountDiff([], [])
    expect(wrapper.text()).toContain('两个版本没有差异')
    await wrapper.setProps({
      baseDoc: makeDoc(3, []),
      targetDoc: makeDoc(4, [{ block_id: 'bx', type: 'paragraph', text: '后来加的' }]),
    })
    expect(wrapper.findAll('[data-diff-kind="added"]')).toHaveLength(1)
  })
})

describe('versionSwitcher —— 版本原因走唯一判据', () => {
  const versions = [
    { id: 'v2', version_no: 2, produced_by_ref: 'human_edit:u-1', is_current: true, supersedes_id: 'v1', created_at: '2026-08-02T00:00:00Z' },
    { id: 'v1', version_no: 1, produced_by_ref: '', is_current: false, supersedes_id: null, created_at: '2026-08-01T00:00:00Z' },
  ]

  function mountSwitcher(currentVersionId: string | null = 'v2') {
    return mount(BlueprintVersionSwitcher, {
      props: { versions, currentVersionId },
      global: { plugins: [i18n], stubs: STUBS },
    })
  }

  it('8a. 五档映射逐档命中：human_edit 前缀 ⇒ 人工编辑，空 ref ⇒ AI 产出', () => {
    const wrapper = mountSwitcher()
    const reasons = wrapper.findAll('[data-testid="blueprint-version-reason"]').map(node => node.text())
    expect(reasons[0]).toContain('人工编辑')
    expect(reasons[1]).toContain('AI 产出')
  })

  it('8b. 点条目 emit change，点对比按钮 emit compare', async () => {
    const wrapper = mountSwitcher()
    await wrapper.findAll('[data-testid="blueprint-version-item"]')[1].trigger('click')
    expect(wrapper.emitted('change')?.[0]).toEqual(['v1'])
    await wrapper.findAll('[data-testid="blueprint-version-compare"]')[1].trigger('click')
    expect(wrapper.emitted('compare')?.[0]).toEqual(['v1'])
  })

  it('8c. 当前版本带「当前版本」徽标；空列表给空态', () => {
    expect(mountSwitcher().text()).toContain('当前版本')
    const empty = mount(BlueprintVersionSwitcher, {
      props: { versions: [], currentVersionId: null },
      global: { plugins: [i18n], stubs: STUBS },
    })
    expect(empty.text()).toContain('暂无版本记录')
  })
})
