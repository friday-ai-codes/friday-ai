/**
 * 人审终审四件的组件测试（Phase 115-04）。
 *
 * 覆盖路径（编号与 115-04-PLAN Task 3 ④逐条对应）：
 *  1. 终审可用性：`pending_review` ⇒ 两按钮**存在且非 disabled**；`ai_reviewing` ⇒
 *     **存在且 disabled**（⛔ 不是不存在）且有 Tooltip 说明。
 *     ——这与 §20 断言 2 的「不存在于 DOM」刻意成对照。
 *  2. 防误触第二层：点「通过」不会立刻 emit，要等全局二次确认返回 true 才 emit。
 *  3. ⭐ §20 断言 3：`threadIds` 三项（其中一项在 `threads` 里查不到）⇒ 条目数 == 3，
 *     查不到那条回落显示 id 前 8 位；点第一项 ⇒ emit `goto-thread` 且载荷是该 id。
 *     **负向对照**：渲染的不是「只有一句说明」（条目数 > 0）。
 *     （变异：只渲染一句「不可确认」⇒ 转红）
 *  4. ⭐ §20 断言 7 三态并列：`null` ⇒ 「暂无数据」且不含 `0`；`0` ⇒ 含 `0` 且不含
 *     「暂无数据」；正值 ⇒ 具体值。**并列存在才逮得住把空值合并成零的写法**。
 *  5. `citation_coverage` 恒百分比；`hasKeyConclusions: false` ⇒ 出现旁注徽标，`true` ⇒ 不出现。
 *  6. 驳回 `comment` 必填：空 ⇒ 提交 disabled；填入 ⇒ emit 载荷含 `comment`；
 *     带 `presetAnchor` 且保留开关为开 ⇒ 载荷含 `anchor`，关掉后不含。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintBlockedDialog from '~/components/blueprint/BlueprintBlockedDialog.vue'
import BlueprintQualityPanel from '~/components/blueprint/BlueprintQualityPanel.vue'
import BlueprintRejectDialog from '~/components/blueprint/BlueprintRejectDialog.vue'
import BlueprintReviewActions from '~/components/blueprint/BlueprintReviewActions.vue'
import { useConfirmDialog } from '~/composables/useConfirmDialog'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          statusUnknown: '未知状态',
          sectionEmpty: '本方案未涉及{name}',
          section: {
            currentStateAnalysis: '现状分析',
            repoAssociations: '仓库关联',
            impactAnalysis: '影响范围',
          },
          status: {
            pending_review: '待人类审查',
            ai_reviewing: 'AI 审查中',
            confirmed: '已确认',
          },
          thread: {
            severityBlocker: '阻塞',
            severityWarning: '警告',
            severityInfo: '提示',
            severityNone: '未分级',
          },
          review: {
            approve: '通过方案',
            reject: '驳回修订',
            disabledReadonly: '当前状态下不可执行该操作',
            disabledReason: '当前状态为「{status}」，需等待进入待人类审查',
            rejectKeepAnchor: '保留此划线',
            reviewRound: '第 {n} 轮审查',
            approveTitle: '确认通过该技术方案？',
            approveBody: '通过后蓝图状态变为「已确认」，你将被记入本方案的评审人名单，且蓝图不可再直接改写。',
            approveConfirm: '确认通过',
            rejectTitle: '驳回该技术方案',
            rejectBody: '驳回后蓝图回到「产出中」，修订轮次将变为 {n}。请写明驳回理由（必填）。',
            rejectReasonPlaceholder: '写明驳回理由（必填）',
            rejectReasonRequired: '驳回理由不可为空',
            rejectConfirm: '确认驳回',
          },
          quality: {
            title: '方案质量',
            citationCoverage: '引用覆盖率',
            aiRejectionRate: 'AI 打回率',
            humanEditVolume: '人工编辑量',
            clarificationRounds: '澄清轮次',
            noData: '暂无数据',
            noKeyConclusions: '无关键结论',
            noKeyConclusionsDetail: '现状分析 / 仓库关联 / 影响范围三处均为空，覆盖率的分母为 0 ⇒ 此处的 100% 不代表证据齐备',
          },
          annotation: { quotedSnapshot: '引用时的原文快照' },
          diff: { baseline: '基线版本' },
          error: { blocked: '还有 {n} 条阻塞级审查发现未处置，处置完成后即可通过' },
        },
      },
    },
  },
})

/** reka-ui 的 Dialog / Tooltip 走 Portal，VTU 里看不到 ⇒ 拍平成裸元素。 */
const OVERLAY_STUBS = {
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
  TooltipProvider: { template: '<div><slot /></div>' },
  Tooltip: { template: '<div><slot /></div>' },
  TooltipTrigger: { template: '<div><slot /></div>' },
  TooltipContent: { template: '<div data-testid="blueprint-review-tooltip"><slot /></div>' },
  Switch: {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<button type="button" data-testid="stub-switch" @click="$emit(\'update:modelValue\', !modelValue)" />',
  },
}

function makeThread(overrides: Partial<BlueprintThreadDetail> = {}): BlueprintThreadDetail {
  return {
    thread_id: 't1',
    kind: 'ai_review_finding',
    severity: 'blocker',
    status: 'open',
    blocking: true,
    anchor_status: 'anchored',
    anchor: null,
    return_stage: '',
    created_at: '2026-08-01T00:00:00Z',
    options: [],
    last_reminded_at: null,
    messages: [],
    ...overrides,
  }
}

function mountWith(component: unknown, props: Record<string, unknown>) {
  return mount(component as never, {
    props: props as never,
    global: { plugins: [i18n], stubs: OVERLAY_STUBS },
  })
}

describe('终审操作区：disabled + Tooltip（⛔ 不是不渲染）', () => {
  it('1a. pending_review ⇒ 两按钮存在且非 disabled', () => {
    const wrapper = mountWith(BlueprintReviewActions, { currentStatus: 'pending_review' })
    const approve = wrapper.find('[data-testid="blueprint-review-approve"]')
    const reject = wrapper.find('[data-testid="blueprint-review-reject"]')
    expect(approve.exists()).toBe(true)
    expect(reject.exists()).toBe(true)
    expect(approve.attributes('disabled')).toBeUndefined()
    expect(reject.attributes('disabled')).toBeUndefined()
  })

  it('1b. ai_reviewing ⇒ 两按钮仍存在但 disabled，且 Tooltip 给出状态中文名', () => {
    const wrapper = mountWith(BlueprintReviewActions, { currentStatus: 'ai_reviewing' })
    const approve = wrapper.find('[data-testid="blueprint-review-approve"]')
    expect(approve.exists()).toBe(true)
    expect(approve.attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-testid="blueprint-review-reject"]').attributes('disabled')).toBeDefined()
    const tooltip = wrapper.find('[data-testid="blueprint-review-tooltip"]')
    expect(tooltip.exists()).toBe(true)
    expect(tooltip.text()).toContain('AI 审查中')
  })

  it('1c. confirmed ⇒ 按钮依然存在（⛔ 不是被 v-if 掉）', () => {
    const wrapper = mountWith(BlueprintReviewActions, { currentStatus: 'confirmed' })
    expect(wrapper.find('[data-testid="blueprint-review-approve"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-review-reject"]').exists()).toBe(true)
  })

  it('2a. 点「通过」不会立刻 emit —— 要等二次确认返回 true', async () => {
    const wrapper = mountWith(BlueprintReviewActions, { currentStatus: 'pending_review' })
    const { isOpen, options, handleConfirm } = useConfirmDialog()
    await wrapper.find('[data-testid="blueprint-review-approve"]').trigger('click')
    expect(wrapper.emitted('approve')).toBeUndefined()
    expect(isOpen.value).toBe(true)
    expect(options.value.title).toBe('确认通过该技术方案？')
    handleConfirm()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(wrapper.emitted('approve')).toHaveLength(1)
  })

  it('2b. 点「驳回」直接 emit reject（由父层开受控弹窗，⛔ 不走无输入框的二次确认）', async () => {
    const wrapper = mountWith(BlueprintReviewActions, { currentStatus: 'pending_review' })
    await wrapper.find('[data-testid="blueprint-review-reject"]').trigger('click')
    expect(wrapper.emitted('reject')).toHaveLength(1)
  })
})

describe('⭐ §20 断言 3：approve 409 的未决清单逐条可点跳转', () => {
  const threadIds = ['blocker-aaaaaaaa-1', 'blocker-bbbbbbbb-2', 'missing-cccccccc-3']
  const threads = [
    makeThread({ thread_id: threadIds[0], messages: [{ id: 'm1', author_type: 'ai', author_user_id: null, author_display: '', body: '接口缺少鉴权校验', created_at: '2026-08-01T00:00:00Z' }] }),
    makeThread({ thread_id: threadIds[1], severity: 'warning', messages: [] }),
  ]

  it('3a. 条目数 == threadIds.length，查不到线程的那条也渲染（回落 id 前 8 位）', () => {
    const wrapper = mountWith(BlueprintBlockedDialog, { open: true, threadIds, threads })
    const items = wrapper.findAll('[data-testid="blueprint-blocked-item"]')
    expect(items).toHaveLength(3)
    expect(items[2].text()).toContain('missing-')
  })

  it('3b. 点第一项 ⇒ emit goto-thread 一次且载荷是该 id，并关闭弹窗', async () => {
    const wrapper = mountWith(BlueprintBlockedDialog, { open: true, threadIds, threads })
    await wrapper.findAll('[data-testid="blueprint-blocked-item"]')[0].trigger('click')
    expect(wrapper.emitted('goto-thread')).toHaveLength(1)
    expect(wrapper.emitted('goto-thread')?.[0]).toEqual([threadIds[0]])
    expect(wrapper.emitted('update:open')?.[0]).toEqual([false])
  })

  it('3c. 负向对照：渲染的不只是一句说明 —— 摘要文本与 severity 都出现在条目里', () => {
    const wrapper = mountWith(BlueprintBlockedDialog, { open: true, threadIds, threads })
    expect(wrapper.findAll('[data-testid="blueprint-blocked-item"]').length).toBeGreaterThan(0)
    expect(wrapper.text()).toContain('接口缺少鉴权校验')
    expect(wrapper.text()).toContain('阻塞')
    expect(wrapper.text()).toContain('还有 3 条阻塞级审查发现未处置')
  })
})

describe('⭐ §20 断言 7：质量指标三态并列（null / 0 / 正值）', () => {
  const base = { citation_coverage: 0.8, ai_rejection_rate: null, human_edit_volume: null, clarification_rounds: null }

  function metricText(wrapper: ReturnType<typeof mount>, metric: string): string {
    return wrapper.find(`[data-metric="${metric}"]`).text()
  }

  it('7a. ai_rejection_rate: null ⇒ 文本含「暂无数据」且不含 0', () => {
    const wrapper = mountWith(BlueprintQualityPanel, { quality: { ...base, ai_rejection_rate: null } })
    const text = metricText(wrapper as never, 'aiRejectionRate')
    expect(text).toContain('暂无数据')
    expect(text).not.toContain('0')
  })

  it('7b. human_edit_volume: 0 ⇒ 文本含 0 且不含「暂无数据」', () => {
    const wrapper = mountWith(BlueprintQualityPanel, { quality: { ...base, human_edit_volume: 0 } })
    const text = metricText(wrapper as never, 'humanEditVolume')
    expect(text).toContain('0')
    expect(text).not.toContain('暂无数据')
  })

  it('7c. clarification_rounds 正值 ⇒ 显示具体值', () => {
    const wrapper = mountWith(BlueprintQualityPanel, { quality: { ...base, clarification_rounds: 3 } })
    const text = metricText(wrapper as never, 'clarificationRounds')
    expect(text).toContain('3')
    expect(text).not.toContain('暂无数据')
  })

  it('7d. ai_rejection_rate 正值 ⇒ 百分比', () => {
    const wrapper = mountWith(BlueprintQualityPanel, { quality: { ...base, ai_rejection_rate: 0.25 } })
    expect(metricText(wrapper as never, 'aiRejectionRate')).toContain('25.0%')
  })

  it('5a. citation_coverage 恒百分比（分母为 0 时后端返 1.0）', () => {
    const wrapper = mountWith(BlueprintQualityPanel, { quality: { ...base, citation_coverage: 1 } })
    expect(metricText(wrapper as never, 'citationCoverage')).toContain('100.0%')
  })

  it('5b. hasKeyConclusions: false ⇒ 出现旁注徽标；true ⇒ 不出现', () => {
    const warned = mountWith(BlueprintQualityPanel, { quality: { ...base, citation_coverage: 1 }, hasKeyConclusions: false })
    expect(warned.find('[data-testid="blueprint-quality-no-key-conclusions"]').exists()).toBe(true)
    const clean = mountWith(BlueprintQualityPanel, { quality: { ...base, citation_coverage: 1 }, hasKeyConclusions: true })
    expect(clean.find('[data-testid="blueprint-quality-no-key-conclusions"]').exists()).toBe(false)
  })

  /**
   * ⭐ UI-REVIEW L-6：旁注徽标的 `title` 是**解释指标口径**，⛔ 不是复述空态。
   *
   * 原先复用空态串 `sectionEmpty` ⇒ 渲染成「本方案未涉及现状分析 / …」，读起来像在陈述
   * 事实而不是在解释「为什么这里的 100% 不算数」。
   */
  it('5c. ⭐ 旁注徽标的 title 讲清口径（⛔ 不复用空态串）', () => {
    const wrapper = mountWith(BlueprintQualityPanel, { quality: { ...base, citation_coverage: 1 }, hasKeyConclusions: false })
    const title = wrapper.find('[data-testid="blueprint-quality-no-key-conclusions"]').attributes('title') ?? ''
    expect(title).toContain('分母为 0')
    expect(title).not.toContain('本方案未涉及')
  })
})

describe('驳回弹窗：comment 必填 + 可选携带划线', () => {
  const presetAnchor = { blockId: 'b1', startOffset: 0, endOffset: 4, quotedText: '这一段' }

  it('6a. comment 为空 ⇒ 提交按钮 disabled 且有内联提示', () => {
    const wrapper = mountWith(BlueprintRejectDialog, { open: true, revisionRound: 1 })
    expect(wrapper.find('[data-testid="blueprint-reject-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('驳回理由不可为空')
  })

  it('6b. 纯空格也不可提交', async () => {
    const wrapper = mountWith(BlueprintRejectDialog, { open: true, revisionRound: 1 })
    await wrapper.find('[data-testid="blueprint-reject-comment"]').setValue('    ')
    expect(wrapper.find('[data-testid="blueprint-reject-submit"]').attributes('disabled')).toBeDefined()
  })

  it('6c. 填入理由 ⇒ emit submit 且载荷含 comment；底部提示显示 revisionRound + 1', async () => {
    const wrapper = mountWith(BlueprintRejectDialog, { open: true, revisionRound: 2 })
    expect(wrapper.text()).toContain('修订轮次将变为 3')
    await wrapper.find('[data-testid="blueprint-reject-comment"]').setValue('  方案缺少回滚设计  ')
    await wrapper.find('[data-testid="blueprint-reject-submit"]').trigger('click')
    expect(wrapper.emitted('submit')?.[0]).toEqual([{ comment: '方案缺少回滚设计' }])
  })

  it('6d. presetAnchor 存在且保留开关为开 ⇒ 载荷含 anchor', async () => {
    const wrapper = mountWith(BlueprintRejectDialog, { open: true, revisionRound: 0, presetAnchor })
    await wrapper.find('[data-testid="blueprint-reject-comment"]').setValue('这段有问题')
    await wrapper.find('[data-testid="blueprint-reject-submit"]').trigger('click')
    expect(wrapper.emitted('submit')?.[0]?.[0]).toEqual({
      comment: '这段有问题',
      anchor: { block_id: 'b1', start_offset: 0, end_offset: 4, quoted_text: '这一段' },
    })
  })

  it('6e. 关掉保留开关 ⇒ 载荷不含 anchor', async () => {
    const wrapper = mountWith(BlueprintRejectDialog, { open: true, revisionRound: 0, presetAnchor })
    await wrapper.find('[data-testid="blueprint-reject-keep-anchor"]').trigger('click')
    await wrapper.find('[data-testid="blueprint-reject-comment"]').setValue('这段有问题')
    await wrapper.find('[data-testid="blueprint-reject-submit"]').trigger('click')
    expect(wrapper.emitted('submit')?.[0]).toEqual([{ comment: '这段有问题' }])
  })
})
