/**
 * 线程侧栏 / 线程卡 / 作答框 / finding 处置 / 选区浮层的组件测试（Phase 115-04）。
 *
 * 覆盖路径（编号与 115-04-PLAN Task 3 ③逐条对应）：
 *  1. ⭐ §20 断言 1 —— kind 四类参数化：`ai_review_finding` 的卡里
 *     `blueprint-thread-composer` **不存在于 DOM**、`blueprint-finding-actions` 存在；
 *     其余三类反向为真。（变异：把 finding 也渲成可回复 ⇒ 1a 转红）
 *  2. ⭐ §20 断言 2（三条并列）—— `readonly: true` 时 (a) 作答框不存在于 DOM（⛔ 不是
 *     disabled）、(b) 选区浮层的「发起评论」不存在、(c) **finding 处置仍然存在**。
 *     （变异一：改成 disabled ⇒ 2a 转红；变异二：把 finding 处置也关掉 ⇒ 2c 转红）
 *  3. ⭐ §20 断言 5（kind 分组口径）—— `orphanedThreads` 不被二次过滤：失锚线程按各自
 *     kind 落组，全侧栏卡片总数 == 传入总数。（变异：加 `.filter(t => t.anchor?.block_id)` ⇒ 转红）
 *  4. ⭐ §20 断言 11（kind 分组口径）—— 同 id 线程只在其 kind 组出现一次，全量卡片数 ==
 *     线程总数（去重口径由 `sidebarKindGroups` 承载）；空 kind 组整块（含标题行）不渲染。
 *  5. 组内排序：open → answered → closed；同 status 内 `blocker` 在 `warning` 之前、
 *     同 severity 按 `created_at` 升序。
 *  6. `options` 候选：两个合法条目 ⇒ 渲染两个可点选项且点选填入输入框；非法形状 ⇒ 不渲染且不抛。
 *  7. `author_display` 为空串的消息正常渲染不抛。
 *  8. 失锚线程仍可处置：失锚的 `human_comment` 在 `readonly: false` 时仍渲染作答框。
 *  9. finding 处置：理由空 ⇒ 提交 disabled；填入 ⇒ emit `resolve` / `dismiss` 且载荷带理由。
 *
 * 测试范式照 `components/prompts/__tests__/PromptVersionDiff.test.ts`（覆盖路径编号清单 +
 * 工厂 + 正负成对 + `data-*` 定位）与 `pages/knowledge/__tests__/entity-detail.spec.ts`
 * （手写最小 i18n 键树，⛔ 不 import `zh-CN.json`）。
 * reka-ui 的 `Dialog` / `Popover` 走 Portal，VTU 里看不到 ⇒ 与 115-03 同款做法：stub 成裸 div。
 */

import type { BlueprintThreadDetail } from '~/types/blueprint'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import { resolveBlueprintAnchorDomId } from '~/components/blueprint/anchorTargets'
import { FOCUS_RING_CLASS } from '~/components/blueprint/annotationTokens'
import BlueprintFindingActions from '~/components/blueprint/BlueprintFindingActions.vue'
import BlueprintSelectionPopover from '~/components/blueprint/BlueprintSelectionPopover.vue'
import BlueprintThreadCard from '~/components/blueprint/BlueprintThreadCard.vue'
import BlueprintThreadSidebar from '~/components/blueprint/BlueprintThreadSidebar.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          thread: {
            kindAiClarification: 'AI 提问',
            kindAiReviewFinding: 'AI 审查',
            kindHumanComment: '人工评论',
            kindRepoConfirmation: '确认门',
            severityBlocker: '阻塞',
            severityWarning: '警告',
            severityInfo: '提示',
            severityNone: '未分级',
            composerPlaceholder: '写下你的回复…',
            composerSubmit: '提交回复',
            composerEmpty: '回复内容不可为空',
            optionsHint: '可直接选用下列候选答案，选中后仍可改写',
            wizardProgress: '第 {i} / {n} 题',
            wizardOther: '其他',
            wizardOtherPlaceholder: '写下你的自定义回答…',
            wizardNext: '下一题',
            wizardPrev: '上一题',
            wizardSubmitAll: '提交全部回答',
            recommended: '推荐',
            wizardHasRecommended: '含推荐答案',
            relatedFeaturePoints: '相关功能点（点击查看）',
            reminded: '上次提醒：{time}',
            authorAi: 'AI',
            gotoGate: '前往确认门',
            anchorLocation: '定位：{location}',
            gotoAnchorLocation: '定位到{location}',
            draftTitle: '针对选中片段发起评论',
            draftSubmit: '提交评论',
            groupOpen: '未决',
            groupAnswered: '已回答',
            groupClosed: '已关闭',
            rule: {
              acceptance_uncovered: '验收标准未覆盖',
              gate_lock_violation_role: '偏离锁定·角色',
            },
          },
          finding: {
            resolve: '已修复',
            dismiss: '误报忽略',
            reasonLabel: '处置说明',
            reasonPlaceholder: '写明处置理由（必填）',
            reasonRequired: '处置理由不可为空',
            resolveTitle: '标记该审查发现为已修复',
            dismissTitle: '标记该审查发现为误报忽略',
            confirm: '确认处置',
          },
          repo: {
            rationale: '选仓理由',
          },
          activity: {
            repoTag: '仓库：{name}',
            repoUnknown: '未知仓库',
          },
          annotation: {
            degraded: '无法精确定位到原文片段，已标注整块',
            orphaned: '原文已变更，无法定位',
            quotedSnapshot: '引用时的原文快照',
            sidebarToggleAria: '查看批注，共 {n} 条',
            sidebarTitle: '批注',
            showClosed: '显示已关闭批注',
            showClosedHint: '已关闭的批注以灰色点线标注',
            emptyTitle: '暂无批注',
            emptyBody: 'AI 的划线提问与你的评论都会出现在这里；选中正文任意片段即可发起评论',
            selection: { comment: '发起评论', copy: '复制原文' },
          },
        },
      },
    },
  },
})

/** reka-ui 的浮层走 Portal，VTU 找不到 ⇒ 拍平成裸 div。 */
const OVERLAY_STUBS = {
  RouterLink: {
    props: ['to'],
    template: '<a :href="to"><slot /></a>',
  },
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
  Popover: { template: '<div><slot /></div>' },
  PopoverAnchor: { template: '<div><slot /></div>' },
  PopoverContent: { template: '<div><slot /></div>' },
  Collapsible: { template: '<div><slot /></div>' },
  CollapsibleTrigger: { template: '<div><slot /></div>' },
  CollapsibleContent: { template: '<div><slot /></div>' },
  Switch: { template: '<button type="button" />' },
}

function makeThread(overrides: Partial<BlueprintThreadDetail> = {}): BlueprintThreadDetail {
  return {
    thread_id: 't1',
    kind: 'human_comment',
    severity: '',
    status: 'open',
    blocking: false,
    anchor_status: 'anchored',
    anchor: { block_id: 'b1', start_offset: 0, end_offset: 3, quoted_text: '原文' },
    return_stage: '',
    created_at: '2026-08-01T00:00:00Z',
    options: [],
    last_reminded_at: null,
    messages: [],
    ...overrides,
  }
}

function mountCard(props: Record<string, unknown>) {
  return mount(BlueprintThreadCard, {
    props: props as never,
    global: { plugins: [i18n], stubs: OVERLAY_STUBS },
  })
}

function mountSidebar(props: Record<string, unknown> = {}) {
  return mount(BlueprintThreadSidebar, {
    props: props as never,
    global: { plugins: [i18n], stubs: OVERLAY_STUBS },
  })
}

describe('线程 section_path 的段级定位', () => {
  it('finding 缺 block_id 时点击仓库位置入口 emit repo-<rid>', async () => {
    const rid = 'cee27ee1-cc73-4937-9a9e-730edd6c93b2'
    const wrapper = mountCard({
      thread: makeThread({
        kind: 'ai_review_finding',
        anchor: {
          block_id: '',
          quoted_text: '',
          section_path: `repo_associations[${rid}].rationale`,
        },
      }),
      repoNames: { [rid]: 'friday-ai' },
    })

    const location = wrapper.find('[data-testid="blueprint-thread-anchor-location"]')
    expect(location.text()).toContain('friday-ai · 选仓理由')
    await location.trigger('click')
    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual([`repo-${rid}`])
  })

  it.each([
    [{ block_id: '', section_path: 'repo_associations[repo-1].rationale' }, 'repo-repo-1'],
    [{ block_id: '', section_path: 'implementation_overview.items[impl-1].how' }, 'impl-impl-1'],
    [{ block_id: '', section_path: 'api_contracts[api-1].request' }, 'api-api-1'],
    [{ block_id: '', section_path: 'current_state_analysis.findings' }, 'current_state_analysis'],
    [{ block_id: '', section_path: '' }, ''],
    [{ block_id: '', section_path: 42 }, ''],
    [{ block_id: '', section_path: '[]' }, ''],
  ])('section_path 防御解析：%j ⇒ %s', (anchor, expected) => {
    expect(() => resolveBlueprintAnchorDomId(anchor as never)).not.toThrow()
    expect(resolveBlueprintAnchorDomId(anchor as never)).toBe(expected)
  })

  it('block_id 非空时优先保持 blk-<block_id> 行为', () => {
    expect(resolveBlueprintAnchorDomId({
      block_id: 'block-7',
      section_path: 'repo_associations[repo-1].rationale',
    })).toBe('blk-block-7')
  })
})

describe('线程正文的仓库标签', () => {
  it('仓库 UUID 转成可读且可跳转的仓库标签，不在正文裸露 UUID', () => {
    const repositoryId = '47991a7f-c8e4-4da6-b42c-2ce81d8b137f'
    const wrapper = mountCard({
      thread: makeThread({
        messages: [{
          id: 'm-repo',
          author_type: 'ai',
          author_user_id: null,
          author_display: '',
          body: `仓库 ${repositoryId} 的分仓方案未能产出`,
          created_at: '2026-08-01T00:00:00Z',
        }],
      }),
      repoNames: { [repositoryId]: 'backend/study-course' },
    })

    const link = wrapper.find('[data-testid="blueprint-thread-repo-link"]')
    expect(link.text()).toBe('仓库：backend/study-course')
    expect(link.attributes('href')).toBe(`/repositories/${repositoryId}`)
    expect(wrapper.text()).not.toContain(repositoryId)
  })
})

describe('⭐ §20 断言 1：线程动作按 kind 硬分流（渲染层）', () => {
  it('1a. ai_review_finding ⇒ 作答框不存在于 DOM，只有处置按钮', () => {
    const wrapper = mountCard({ thread: makeThread({ kind: 'ai_review_finding', severity: 'blocker' }), readonly: false })
    expect(wrapper.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-finding-actions"]').exists()).toBe(true)
  })

  it.each([
    ['ai_clarification'],
    ['human_comment'],
    ['repo_confirmation'],
  ])('1b. %s ⇒ 反向为真：有作答框、无处置按钮', (kind) => {
    const wrapper = mountCard({ thread: makeThread({ kind: kind as never }), readonly: false })
    expect(wrapper.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-finding-actions"]').exists()).toBe(false)
  })

  it('1c. finding 卡里连作答框的输入元素都不存在（⛔ 不是隐藏）', () => {
    const wrapper = mountCard({ thread: makeThread({ kind: 'ai_review_finding' }), readonly: false })
    expect(wrapper.find('[data-testid="blueprint-thread-composer-input"]').exists()).toBe(false)
  })
})

describe('⭐ §20 断言 2：readonly 是「不存在于 DOM」而 finding 处置不受其约束', () => {
  it('2a. readonly: true ⇒ 作答框不存在于 DOM（⛔ 不是 disabled）', () => {
    const wrapper = mountCard({ thread: makeThread({ kind: 'ai_clarification' }), readonly: true })
    expect(wrapper.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(false)
    // 负向对照：也不是「渲染了但 disabled」
    expect(wrapper.html()).not.toContain('blueprint-thread-composer')
  })

  it('2b. canComment: false ⇒ 选区浮层的「发起评论」不存在，「复制原文」仍在', () => {
    const wrapper = mount(BlueprintSelectionPopover, {
      props: { rect: null, canComment: false },
      global: { plugins: [i18n], stubs: OVERLAY_STUBS },
    })
    expect(wrapper.find('[data-testid="blueprint-selection-comment"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-selection-copy"]').exists()).toBe(true)
  })

  it('2c. ⭐ readonly: true 时 finding 处置按钮仍然存在（§7.9 末条，超界死锁的唯一出口）', () => {
    const wrapper = mountCard({ thread: makeThread({ kind: 'ai_review_finding', severity: 'blocker' }), readonly: true })
    expect(wrapper.find('[data-testid="blueprint-finding-actions"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-finding-resolve"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-finding-dismiss"]').exists()).toBe(true)
  })

  it('2d. readonly: false ⇒ 前两条反向为真', () => {
    const card = mountCard({ thread: makeThread({ kind: 'ai_clarification' }), readonly: false })
    expect(card.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(true)
    const popover = mount(BlueprintSelectionPopover, {
      props: { rect: null, canComment: true },
      global: { plugins: [i18n], stubs: OVERLAY_STUBS },
    })
    expect(popover.find('[data-testid="blueprint-selection-comment"]').exists()).toBe(true)
  })
})

describe('⭐ §20 断言 5 / 11（kind 分组口径）：失锚线程按 kind 落组且只出现一次', () => {
  it('5. orphanedThreads 不二次过滤：失锚线程按各自 kind 落组，卡片总数 == 传入总数', () => {
    const orphanedThreads = [
      makeThread({ thread_id: 'o1', kind: 'human_comment', anchor: null, anchor_status: 'orphaned', status: 'open' }),
      makeThread({ thread_id: 'o2', kind: 'ai_clarification', anchor: { block_id: 'b9', start_offset: 0, end_offset: 2 }, anchor_status: 'orphaned', status: 'answered' }),
    ]
    const wrapper = mountSidebar({ threads: [], orphanedThreads })
    const humanGroup = wrapper.find('[data-testid="blueprint-thread-group-human_comment"]')
    expect(humanGroup.exists()).toBe(true)
    expect(humanGroup.findAll('[data-thread-id="o1"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="blueprint-thread-card"]')).toHaveLength(orphanedThreads.length)
  })

  it('11. 同 id 的 open 且 orphaned 线程：只在其 kind 组出现一次，全量卡片数 == 线程总数', () => {
    const orphan = makeThread({ thread_id: 'dup', anchor_status: 'orphaned', status: 'open' })
    const normal = makeThread({ thread_id: 'plain', status: 'open' })
    const wrapper = mountSidebar({
      threads: [orphan, normal],
      orphanedThreads: [orphan],
      showClosed: true,
    })
    // 全量卡片数 == 线程总数（2），⛔ 不是 3（去重口径由 sidebarKindGroups 承载）
    expect(wrapper.findAll('[data-testid="blueprint-thread-card"]')).toHaveLength(2)
    const kindGroup = wrapper.find('[data-testid="blueprint-thread-group-human_comment"]')
    expect(kindGroup.findAll('[data-thread-id="dup"]')).toHaveLength(1)
    expect(kindGroup.findAll('[data-thread-id="plain"]')).toHaveLength(1)
  })

  it('11b. 无任何线程的 kind 组整块（含标题行）不渲染', () => {
    const wrapper = mountSidebar({
      threads: [makeThread({ kind: 'ai_clarification' })],
      orphanedThreads: [],
    })
    expect(wrapper.find('[data-testid="blueprint-thread-group-ai_clarification"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-thread-group-ai_review_finding"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-thread-group-human_comment"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-thread-group-repo_confirmation"]').exists()).toBe(false)
    // 标题行随空组一并不存在：全侧栏只剩非空那一组的触发器
    expect(wrapper.findAll('[data-testid="blueprint-thread-group-trigger"]')).toHaveLength(1)
  })
})

describe('侧栏分组与排序（kind 分组口径）', () => {
  it('5b. 组内排序：open(blocker) → open(warning) → answered → closed', () => {
    const threads = [
      makeThread({ thread_id: 'cl', status: 'resolved', created_at: '2026-08-01T00:00:00Z' }),
      makeThread({ thread_id: 'an', status: 'answered', created_at: '2026-08-01T00:00:00Z' }),
      makeThread({ thread_id: 'w1', status: 'open', severity: 'warning', created_at: '2026-08-01T00:00:00Z' }),
      makeThread({ thread_id: 'b2', status: 'open', severity: 'blocker', created_at: '2026-08-02T00:00:00Z' }),
      makeThread({ thread_id: 'b1', status: 'open', severity: 'blocker', created_at: '2026-08-01T00:00:00Z' }),
    ]
    const wrapper = mountSidebar({ threads, orphanedThreads: [], showClosed: true })
    const ids = wrapper.find('[data-testid="blueprint-thread-group-human_comment"]')
      .findAll('[data-testid="blueprint-thread-card"]')
      .map(card => card.attributes('data-thread-id'))
    expect(ids).toEqual(['b1', 'b2', 'w1', 'an', 'cl'])
  })

  it('5c. showClosed 关闭时 closed 线程不出现在其 kind 组（组因此为空则整块不渲染），打开后出现', () => {
    const closed = makeThread({ thread_id: 'c1', status: 'resolved' })
    const hidden = mountSidebar({ threads: [closed], orphanedThreads: [], showClosed: false })
    expect(hidden.find('[data-testid="blueprint-thread-group-human_comment"]').exists()).toBe(false)
    const shown = mountSidebar({ threads: [closed], orphanedThreads: [], showClosed: true })
    const group = shown.find('[data-testid="blueprint-thread-group-human_comment"]')
    expect(group.exists()).toBe(true)
    expect(group.findAll('[data-thread-id="c1"]')).toHaveLength(1)
  })

  it('5d. 四组皆空 ⇒ 渲染空态', () => {
    const wrapper = mountSidebar({ threads: [], orphanedThreads: [] })
    expect(wrapper.text()).toContain('暂无批注')
  })

  it('5e. 分组顺序固定：AI 提问 → AI 审查 → 人工评论 → 确认门', () => {
    const threads = [
      makeThread({ thread_id: 'k3', kind: 'human_comment' }),
      makeThread({ thread_id: 'k4', kind: 'repo_confirmation' }),
      makeThread({ thread_id: 'k1', kind: 'ai_clarification' }),
      makeThread({ thread_id: 'k2', kind: 'ai_review_finding' }),
    ]
    const wrapper = mountSidebar({ threads, orphanedThreads: [] })
    const order = wrapper.findAll('[data-group-key]').map(group => group.attributes('data-group-key'))
    expect(order).toEqual(['ai_clarification', 'ai_review_finding', 'human_comment', 'repo_confirmation'])
  })
})

describe('作答框：options 候选与必填校验', () => {
  it('6a. 两个合法 options ⇒ 渲染两个可点选项，点选填入输入框', async () => {
    const wrapper = mountCard({
      thread: makeThread({
        kind: 'ai_clarification',
        options: [{ label: '方案 A', value: 'A' }, { label: '方案 B', value: 'B' }],
      }),
      readonly: false,
    })
    const options = wrapper.findAll('[data-testid="blueprint-thread-option"]')
    expect(options).toHaveLength(2)
    await options[1].trigger('click')
    const input = wrapper.find('[data-testid="blueprint-thread-composer-input"]')
    expect((input.element as HTMLTextAreaElement).value).toBe('B')
  })

  it('6b. options 是非法形状（空对象）⇒ 不渲染选项组且不抛', () => {
    const wrapper = mountCard({
      thread: makeThread({ kind: 'ai_clarification', options: [{} as never] }),
      readonly: false,
    })
    expect(wrapper.findAll('[data-testid="blueprint-thread-option"]')).toHaveLength(0)
    expect(wrapper.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(true)
  })

  it('6d. 结构化 questions ⇒ 渲染逐步向导而非旧 composer', () => {
    const wrapper = mountCard({
      thread: makeThread({
        kind: 'ai_clarification',
        options: [
          {
            text: '弱网重连后倒计时如何恢复？',
            options: ['从中断处续计', '整轮重置'],
            recommended: '从中断处续计',
            related_feature_points: ['fp_27'],
          },
          {
            text: '本期是否包含激励发放？',
            options: ['包含', '不包含'],
          },
        ],
        messages: [
          {
            id: 'm1',
            author_type: 'ai',
            author_user_id: null,
            author_display: '',
            body: '1. 弱网…\n2. 激励…',
            created_at: '2026-08-01T00:00:00Z',
          },
        ],
      }),
      readonly: false,
      featurePointTitles: { fp_27: '倒计时中断恢复' },
    })
    expect(wrapper.find('[data-testid="blueprint-clarification-wizard"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-clarification-progress"]').text()).toContain('1')
    expect(wrapper.find('[data-testid="blueprint-clarification-question"]').text()).toContain('弱网重连')
    // 首条 AI 编号题面被隐藏
    expect(wrapper.findAll('[data-testid="blueprint-thread-message"]')).toHaveLength(0)
    expect(wrapper.find('[data-testid="blueprint-clarification-fp-chip"]').text()).toContain('倒计时中断恢复')
  })

  it('6e. 向导：选选项 → 下一题 → 选其他填写 → 整包提交', async () => {
    const wrapper = mountCard({
      thread: makeThread({
        kind: 'ai_clarification',
        options: [
          { text: '问题一', options: ['A', 'B'], recommended: 'A' },
          { text: '问题二', options: ['X', 'Y'] },
        ],
      }),
      readonly: false,
    })
    const opts = wrapper.findAll('[data-testid="blueprint-clarification-option"]')
    await opts[0].trigger('click')
    await wrapper.find('[data-testid="blueprint-clarification-next"]').trigger('click')
    expect(wrapper.find('[data-testid="blueprint-clarification-question"]').text()).toBe('问题二')
    await wrapper.find('[data-testid="blueprint-clarification-other"]').trigger('click')
    await wrapper.find('[data-testid="blueprint-clarification-other-input"]').setValue('自定义答案')
    await wrapper.find('[data-testid="blueprint-clarification-next"]').trigger('click')
    expect(wrapper.emitted('answer')?.[0]).toEqual([
      't1',
      '1. 问题一\n→ A\n\n2. 问题二\n→ 自定义答案',
    ])
  })

  it('6f. 功能点 chip 点击 emit goto-anchor', async () => {
    const wrapper = mountCard({
      thread: makeThread({
        kind: 'ai_clarification',
        options: [
          { text: '关于恢复', options: ['续计'], related_feature_points: ['fp_28'] },
        ],
      }),
      readonly: false,
      featurePointTitles: { fp_28: '弱网续计' },
    })
    await wrapper.find('[data-testid="blueprint-clarification-fp-chip"]').trigger('click')
    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual(['fp-fp_28'])
  })

  it('6c. 空 / 纯空格不可提交，填入后 emit answer 且载荷已 trim', async () => {
    const wrapper = mountCard({ thread: makeThread({ kind: 'human_comment' }), readonly: false })
    const submit = wrapper.find('[data-testid="blueprint-thread-composer-submit"]')
    expect(submit.attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="blueprint-thread-composer-input"]').setValue('  已确认  ')
    await submit.trigger('click')
    expect(wrapper.emitted('answer')?.[0]).toEqual(['t1', '已确认'])
  })

  it('7. author_display 为空串的消息正常渲染不抛', () => {
    const wrapper = mountCard({
      thread: makeThread({
        messages: [
          { id: 'm1', author_type: 'ai', author_user_id: null, author_display: '', body: '来自 AI', created_at: '2026-08-01T00:00:00Z' },
          { id: 'm2', author_type: 'human', author_user_id: null, author_display: '', body: '作者已删', created_at: '2026-08-01T01:00:00Z' },
        ],
      }),
      readonly: false,
    })
    expect(wrapper.findAll('[data-testid="blueprint-thread-message"]')).toHaveLength(2)
    expect(wrapper.text()).toContain('来自 AI')
  })

  it('8. 失锚的 human_comment 在 readonly: false 时仍可回复（失锚不 disable 动作）', () => {
    const wrapper = mountCard({
      thread: makeThread({ kind: 'human_comment', anchor_status: 'orphaned' }),
      readonly: false,
    })
    expect(wrapper.find('[data-testid="blueprint-thread-orphaned"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-thread-composer"]').exists()).toBe(true)
  })
})

describe('⭐ AI 审查 finding 的 rule_id 前缀汉化（quick-260806-vqh）', () => {
  function findingThread(bodies: string[]): BlueprintThreadDetail {
    return makeThread({
      kind: 'ai_review_finding',
      severity: 'warning',
      messages: bodies.map((body, index) => ({
        id: `m${index}`,
        author_type: 'ai' as const,
        author_user_id: null,
        author_display: '',
        body,
        created_at: '2026-08-01T00:00:00Z',
      })),
    })
  }

  it('10a. 已知 rule_id ⇒ 中文标签徽标，可读正文里不再有裸 id', () => {
    const wrapper = mountCard({
      thread: findingThread(['[acceptance_uncovered] 当前节点轻高亮引导未见独立测试策略']),
      readonly: false,
    })
    const rule = wrapper.find('[data-testid="blueprint-thread-message-rule"]')
    expect(rule.exists()).toBe(true)
    expect(rule.text()).toBe('验收标准未覆盖')
    // 原始 id 只留在 title 里供排障，⛔ 不出现在可读文本
    expect(rule.attributes('title')).toBe('acceptance_uncovered')
    expect(wrapper.text()).not.toContain('acceptance_uncovered')
    expect(wrapper.text()).toContain('当前节点轻高亮引导未见独立测试策略')
  })

  it('10b. 未知 rule_id ⇒ 回落原始 id（⛔ 不吞掉分类）', () => {
    const wrapper = mountCard({
      thread: findingThread(['[brand_new_rule] 后端新增了一条规则']),
      readonly: false,
    })
    expect(wrapper.find('[data-testid="blueprint-thread-message-rule"]').text()).toBe(
      'brand_new_rule',
    )
  })

  it('10c. ⭐ 无前缀消息不渲染徽标，中文前缀原样保留', () => {
    const wrapper = mountCard({
      thread: findingThread([
        '第 2 轮仍存在：功能点C无独立测试策略',
        '[已修复] 人审复核：该缺口已补齐',
      ]),
      readonly: false,
    })
    expect(wrapper.findAll('[data-testid="blueprint-thread-message-rule"]')).toHaveLength(0)
    expect(wrapper.text()).toContain('第 2 轮仍存在：功能点C无独立测试策略')
    expect(wrapper.text()).toContain('[已修复] 人审复核：该缺口已补齐')
  })
})

describe('finding 处置：理由必填且分别打到 resolve / dismiss', () => {
  it('9a. 理由为空 ⇒ 确认按钮 disabled', async () => {
    const wrapper = mount(BlueprintFindingActions, {
      props: { threadId: 'f1' },
      global: { plugins: [i18n], stubs: OVERLAY_STUBS },
    })
    await wrapper.find('[data-testid="blueprint-finding-resolve"]').trigger('click')
    expect(wrapper.find('[data-testid="blueprint-finding-reason-submit"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('处置理由不可为空')
  })

  it('9b. 「已修复」填入理由 ⇒ emit resolve(threadId, reason)', async () => {
    const wrapper = mount(BlueprintFindingActions, {
      props: { threadId: 'f1' },
      global: { plugins: [i18n], stubs: OVERLAY_STUBS },
    })
    await wrapper.find('[data-testid="blueprint-finding-resolve"]').trigger('click')
    await wrapper.find('[data-testid="blueprint-finding-reason-input"]').setValue(' 已按建议改写 ')
    await wrapper.find('[data-testid="blueprint-finding-reason-submit"]').trigger('click')
    expect(wrapper.emitted('resolve')?.[0]).toEqual(['f1', '已按建议改写'])
    expect(wrapper.emitted('dismiss')).toBeUndefined()
  })

  it('9c. 「误报忽略」填入理由 ⇒ emit dismiss(threadId, reason)', async () => {
    const wrapper = mount(BlueprintFindingActions, {
      props: { threadId: 'f2' },
      global: { plugins: [i18n], stubs: OVERLAY_STUBS },
    })
    await wrapper.find('[data-testid="blueprint-finding-dismiss"]').trigger('click')
    await wrapper.find('[data-testid="blueprint-finding-reason-input"]').setValue('该发现不适用')
    await wrapper.find('[data-testid="blueprint-finding-reason-submit"]').trigger('click')
    expect(wrapper.emitted('dismiss')?.[0]).toEqual(['f2', '该发现不适用'])
    expect(wrapper.emitted('resolve')).toBeUndefined()
  })

  it('9d. ⛔ 组件不自行拼装后端的结论文本：emit 载荷就是用户原话', async () => {
    const wrapper = mount(BlueprintFindingActions, {
      props: { threadId: 'f3' },
      global: { plugins: [i18n], stubs: OVERLAY_STUBS },
    })
    await wrapper.find('[data-testid="blueprint-finding-resolve"]').trigger('click')
    await wrapper.find('[data-testid="blueprint-finding-reason-input"]').setValue('原话')
    await wrapper.find('[data-testid="blueprint-finding-reason-submit"]').trigger('click')
    expect(wrapper.emitted('resolve')?.[0]?.[1]).toBe('原话')
  })
})

/**
 * ⭐ UI-REVIEW M-2 回归：线程卡选中区是 §18.3 点名的四个新增焦点目标之一。
 *
 * 侧栏的 `↑`/`↓` 焦点移动正是围绕这颗按钮设计的，焦点指示必须是契约那道不透明
 * `--color-primary-600`（3.74:1），⛔ 不是浏览器默认环、⛔ 不是既有那个 1.59:1 的半透明值。
 *
 * ⚠️ happy-dom 无布局引擎 ⇒ ⛔ 不断言渲染几何，只断言类名。
 */
describe('线程卡选中区的契约焦点环（M-2）', () => {
  const FOCUS_OUTLINE = 'focus-visible:[outline:2px_solid_var(--color-primary-600)]'

  it('10a. ⭐ 选中区按钮带 §18.3 的焦点环，且默认环仍被压掉', () => {
    const wrapper = mountCard({ thread: makeThread({ kind: 'ai_clarification' }) })
    const select = wrapper.find('[data-testid="blueprint-thread-card-select"]')
    expect(select.exists()).toBe(true)
    expect(select.attributes('class')).toContain(FOCUS_OUTLINE)
    expect(select.attributes('class')).toContain('focus-visible:[outline-offset:2px]')
    expect(select.attributes('class')).toContain('outline-none')
  })

  it('10b. ⭐ 焦点环与选中态互不吃掉：active 时两者都在', () => {
    const wrapper = mountCard({ thread: makeThread(), active: true })
    expect(wrapper.find('[data-testid="blueprint-thread-card"]').attributes('class')).toContain('ring-2')
    expect(wrapper.find('[data-testid="blueprint-thread-card-select"]').attributes('class')).toContain(FOCUS_OUTLINE)
  })

  it('10c. ⭐ 三处共用同一份令牌（⛔ 不各写一串会漂移的字面量）', () => {
    // 单一实现落在 annotationTokens；这里断言三个消费方拿到的是同一个常量对象。
    expect(FOCUS_RING_CLASS).toContain(FOCUS_OUTLINE)
    for (const path of [
      'src/components/blueprint/BlueprintCitationChip.vue',
      'src/components/blueprint/BlueprintSelectionPopover.vue',
      'src/components/blueprint/BlueprintThreadCard.vue',
    ]) {
      const source = readFileSync(resolve(process.cwd(), path), 'utf8')
      expect(source).toContain('FOCUS_RING_CLASS')
      // ⛔ 组件内不得再出现焦点环的颜色字面量。
      expect(source).not.toContain('focus-visible:[outline:2px_solid')
    }
  })
})

/**
 * ⭐ 「显示已关闭批注」开关去重回归：顶栏（BlueprintViewerHeader）已有同名开关，
 * 侧栏内不得再渲染第二个 —— 两处并存就是用户实测点名的「怎么有两个」。
 * 空态里的一键「显示」按钮不受此约束（上下文动作，非常驻开关）。
 */
describe('侧栏不重复渲染「显示已关闭批注」开关', () => {
  it('11a. ⭐ 侧栏内不存在 blueprint-show-closed 开关（唯一开关在顶栏）', () => {
    const wrapper = mountSidebar({ threads: [makeThread()] })
    expect(wrapper.find('[data-testid="blueprint-show-closed"]').exists()).toBe(false)
  })
})

/**
 * ⭐ UI-REVIEW L-4：landmark 名必须是**名词短语**。
 *
 * `role="complementary"` 的 `aria-label` 原本用了按钮的 `sidebarToggleAria`
 * （「查看批注，共 N 条」）—— 那是**动作描述**兼计数。读屏按 landmark 列表导航时念的就是
 * 这个名字，塞进动作与数字只会让每次导航都被读一长串；计数已由各分组 Badge 提供。
 */
describe('侧栏 landmark 的可访问名（L-4）', () => {
  it('12a. ⭐ aria-label 是名词短语「批注」，⛔ 不含动作描述与计数', () => {
    const wrapper = mountSidebar({ threads: [makeThread(), makeThread({ thread_id: 't-2' })] })
    const label = wrapper.find('[data-testid="blueprint-thread-sidebar"]').attributes('aria-label')
    expect(label).toBe('批注')
    expect(label).not.toContain('查看')
    expect(label).not.toContain('2')
  })

  it('12b. 计数为 0 时同名（landmark 名不随内容漂移）', () => {
    const wrapper = mountSidebar({ threads: [] })
    expect(wrapper.find('[data-testid="blueprint-thread-sidebar"]').attributes('aria-label')).toBe('批注')
  })
})

/**
 * ⭐ UI-REVIEW L-8：分组折叠触发器是 §2 的 44px 例外逐字点名的目标
 * （「线程侧栏的折叠箭头」）——窄屏抽屉里它是实际触控目标。
 *
 * ⚠️ happy-dom 无布局引擎 ⇒ ⛔ 不量高度，只断言 `min-h-11` 类在。
 */
describe('分组折叠触发器的 44px 触控目标（L-8）', () => {
  it('13a. ⭐ 每个分组的折叠触发器都带 min-h-11', () => {
    const wrapper = mountSidebar({ threads: [makeThread()], showClosed: true })
    const triggers = wrapper.findAll('[data-testid="blueprint-thread-group-trigger"]')
    expect(triggers.length).toBeGreaterThan(0)
    for (const trigger of triggers)
      expect(trigger.attributes('class')).toContain('min-h-11')
  })
})
