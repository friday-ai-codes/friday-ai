/**
 * ：RoutingDecisionPanel.vue 组件单测。
 *
 * 覆盖：渲染 + 排序 + Badge variant / Tooltip evidence /
 * Checkbox v-model / debounce manual override / 折叠 / emit 事件。
 */

import type { RoutingCandidate, RoutingDecisionData } from '~/types/routing'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import RoutingDecisionPanel from '~/components/chat/RoutingDecisionPanel.vue'
import { useRoutingStore } from '~/stores/routing'

const mockPostManualOverride = vi.fn()
vi.mock('~/api/routing', () => ({
  postManualOverride: (...args: unknown[]) => mockPostManualOverride(...args),
}))

function makeTrace(): RoutingDecisionData {
  return {
    trace_id: 'trace-1',
    query: 'cross-repo',
    threshold: 0.5,
    triggered_by: 'chat_tool',
    candidates: [
      {
        repository_id: 'repo-a',
        repository_name: 'A',
        score: 0.9,
        level: 'high',
        evidence: 'ev-A',
        selected_by_ai: true,
        selected_by_user_final: true,
      },
      {
        repository_id: 'repo-b',
        repository_name: 'B',
        score: 0.55,
        level: 'medium',
        evidence: 'ev-B',
        selected_by_ai: true,
        selected_by_user_final: true,
      },
      {
        repository_id: 'repo-c',
        repository_name: 'C',
        score: 0.2,
        level: 'low',
        evidence: 'ev-C',
        selected_by_ai: false,
        selected_by_user_final: false,
      },
    ],
  }
}

function mountPanel() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useRoutingStore()
  store.upsertTrace(makeTrace(), 'conv-1')
  const wrapper = mount(RoutingDecisionPanel, {
    global: { plugins: [pinia] },
    props: {
      traceId: 'trace-1',
      conversationId: 'conv-1',
      messageId: 'msg-1',
    },
  })
  return { wrapper, store }
}

describe('routingDecisionPanel', () => {
  beforeEach(() => {
    mockPostManualOverride.mockReset()
  })

  it('渲染 3 条候选，按 score 倒序展示仓库名', () => {
    const { wrapper } = mountPanel()
    const text = wrapper.text()
    const aIdx = text.indexOf('A')
    const bIdx = text.indexOf('B')
    const cIdx = text.indexOf('C')
    expect(aIdx).toBeGreaterThanOrEqual(0)
    expect(bIdx).toBeGreaterThan(aIdx)
    expect(cIdx).toBeGreaterThan(bIdx)
  })

  it('badge 标签显示百分比 + 中文 level', () => {
    const { wrapper } = mountPanel()
    const html = wrapper.html()
    expect(html).toContain('90% 高')
    expect(html).toContain('55% 中')
    expect(html).toContain('20% 低')
  })

  it('evidence 文本出现在卡片中', () => {
    const { wrapper } = mountPanel()
    const text = wrapper.text()
    expect(text).toContain('ev-A')
    expect(text).toContain('ev-B')
    expect(text).toContain('ev-C')
  })

  it('折叠态切换隐藏候选列表', async () => {
    const { wrapper } = mountPanel()
    // 默认展开
    expect(wrapper.text()).toContain('A')
    // 点击标题按钮折叠
    const titleBtn = wrapper.find('button')
    await titleBtn.trigger('click')
    await nextTick()
    expect(wrapper.text()).not.toContain('ev-A')
  })

  it('checkbox 改动 → debounce 后调 applyManualOverride 一次', async () => {
    vi.useFakeTimers()
    try {
      const { wrapper } = mountPanel()
      mockPostManualOverride.mockResolvedValue({
        trace_id: 'trace-2',
        original_trace_id: 'trace-1',
        triggered_by: 'manual_override',
        candidates: makeTrace().candidates,
      })

      const checkboxes = wrapper.findAllComponents({ name: 'Checkbox' })
      expect(checkboxes.length).toBe(3)
      // 触发三个连续 toggle 模拟连续点击
      await checkboxes[2].vm.$emit('update:modelValue', true)
      await checkboxes[2].vm.$emit('update:modelValue', false)
      await checkboxes[2].vm.$emit('update:modelValue', true)

      // debounce 窗口未到 → 0 次
      expect(mockPostManualOverride).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(350)
      // debounce 之后被批量提交 1 次
      expect(mockPostManualOverride).toHaveBeenCalledTimes(1)
      const [traceId, payload] = mockPostManualOverride.mock.calls[0]
      expect(traceId).toBe('trace-1')
      expect(payload.candidates[0]).toEqual({ repository_id: 'repo-c', selected: true })
    }
    finally {
      vi.useRealTimers()
    }
  })

  it('「基于这些仓库创建编码方案」按钮 emit create-coding-plan-from-trace', async () => {
    const { wrapper } = mountPanel()
    const buttons = wrapper.findAllComponents({ name: 'Button' })
    // 最后两个 Button 是底部操作；按钮顺序：创建方案 / 手动调整
    const createBtn = buttons.find(b => b.text().includes('创建编码方案'))
    expect(createBtn).toBeDefined()
    await createBtn!.trigger('click')
    const emitted = wrapper.emitted('createCodingPlanFromTrace')
    expect(emitted).toBeTruthy()
    expect(emitted?.[0]).toEqual(['trace-1'])
  })

  it('store 无对应 trace 时不渲染（v-if 卡片消失）', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(RoutingDecisionPanel, {
      global: { plugins: [pinia] },
      props: {
        traceId: 'missing-trace',
        conversationId: 'conv-1',
      },
    })
    expect(wrapper.find('[class*="rounded-md"]').exists()).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// 分数分解展开区（ROUTE-07 / 105-06，UI-SPEC Backstop 4）
// ---------------------------------------------------------------------------

function mountPanelWith(candidates: RoutingCandidate[]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useRoutingStore()
  store.upsertTrace({ ...makeTrace(), candidates }, 'conv-1')
  const wrapper = mount(RoutingDecisionPanel, {
    global: { plugins: [pinia] },
    props: {
      traceId: 'trace-1',
      conversationId: 'conv-1',
      messageId: 'msg-1',
    },
  })
  return { wrapper, store }
}

function candidateWithBreakdown(
  breakdown: Record<string, number> | undefined,
  score = 0.92,
): RoutingCandidate {
  return {
    repository_id: 'repo-a',
    repository_name: 'A',
    score,
    level: 'high',
    evidence: 'ev-A',
    selected_by_ai: true,
    selected_by_user_final: true,
    ...(breakdown !== undefined ? { breakdown } : {}),
  }
}

function findBreakdownTrigger(wrapper: ReturnType<typeof mountPanelWith>['wrapper']) {
  return wrapper.findAll('button').find(b => b.text().includes('分数分解'))
}

describe('routingDecisionPanel 分数分解', () => {
  it('有 breakdown：trigger 可见，展开后明细行数==键数、中文标签/未知 key 回退/合计行==score.toFixed(3)', async () => {
    const breakdown = {
      text: 0.5,
      breadth: 0.25,
      activity: 0.15,
      novel_signal: 0.02,
    }
    const { wrapper } = mountPanelWith([candidateWithBreakdown(breakdown, 0.92)])

    const trigger = findBreakdownTrigger(wrapper)
    expect(trigger).toBeDefined()
    // 默认收起：明细不可见
    expect(wrapper.text()).not.toContain('合计')

    await trigger!.trigger('click')
    await nextTick()

    const text = wrapper.text()
    // 信号中文标签正确
    expect(text).toContain('文本相关')
    expect(text).toContain('命中广度')
    expect(text).toContain('活跃度')
    // 未知 key 回退显示原始英文 key
    expect(text).toContain('novel_signal')
    // 贡献值 3 位小数
    expect(text).toContain('0.500')
    expect(text).toContain('0.020')
    // 明细行 + 合计行 == 键数 + 1
    const rows = wrapper.findAll('div.justify-between')
    expect(rows.length).toBe(Object.keys(breakdown).length + 1)
    // 合计行直接显示 candidate.score
    expect(text).toContain('合计')
    expect(rows[rows.length - 1].text()).toContain((0.92).toFixed(3))
  })

  it('无 breakdown（字段缺失与空 dict）：不渲染 trigger，候选行既有元素齐备', () => {
    for (const breakdown of [undefined, {}]) {
      const { wrapper } = mountPanelWith([candidateWithBreakdown(breakdown)])
      expect(findBreakdownTrigger(wrapper)).toBeUndefined()
      // 既有元素齐备：Checkbox / 名称 / Badge / evidence Tooltip
      expect(wrapper.findAllComponents({ name: 'Checkbox' }).length).toBe(1)
      expect(wrapper.text()).toContain('A')
      expect(wrapper.html()).toContain('92% 高')
      expect(wrapper.text()).toContain('ev-A')
    }
  })

  it('Σbreakdown 与 score 偏差 > 1e-6：仍正常渲染合计行，console.warn 被调用', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      const { wrapper } = mountPanelWith([
        candidateWithBreakdown({ text: 0.1 }, 0.9),
      ])
      // 容差校验挂 immediate watch，mount 即触发
      expect(warnSpy).toHaveBeenCalledWith(
        '[RoutingDecisionPanel] breakdown 合计与 score 不一致',
        expect.objectContaining({ repository_id: 'repo-a' }),
      )

      const trigger = findBreakdownTrigger(wrapper)
      expect(trigger).toBeDefined()
      await trigger!.trigger('click')
      await nextTick()
      // 合计行照常渲染（不阻断）
      expect(wrapper.text()).toContain('合计')
      expect(wrapper.text()).toContain((0.9).toFixed(3))
    }
    finally {
      warnSpy.mockRestore()
    }
  })
})

// ---------------------------------------------------------------------------
// Phase 106 新信号标签（ROUTE-04：domain/stack/team 入分后的展示面）
// ---------------------------------------------------------------------------

describe('routingDecisionPanel Phase 106 新信号标签', () => {
  it('domain/stack/team 键渲染对应中文标签，既有三信号标签不受影响', async () => {
    // 值取二进制精确小数，Σbreakdown === score（重归一化后恒等式按构造成立）
    const breakdown = {
      text: 0.5,
      breadth: 0.125,
      domain: 0.125,
      stack: 0.0625,
      team: 0.03125,
      activity: 0.03125,
    }
    const { wrapper } = mountPanelWith([candidateWithBreakdown(breakdown, 0.875)])

    const trigger = findBreakdownTrigger(wrapper)
    expect(trigger).toBeDefined()
    await trigger!.trigger('click')
    await nextTick()

    const text = wrapper.text()
    // 新信号中文标签（键与后端 SIGNAL_DOMAIN/SIGNAL_STACK/SIGNAL_TEAM 字面对齐）
    expect(text).toContain('业务域匹配')
    expect(text).toContain('技术栈匹配')
    expect(text).toContain('团队归属')
    // 既有三信号标签零回归
    expect(text).toContain('文本相关')
    expect(text).toContain('命中广度')
    expect(text).toContain('活跃度')
    // 明细行 + 合计行 == 键数 + 1
    const rows = wrapper.findAll('div.justify-between')
    expect(rows.length).toBe(Object.keys(breakdown).length + 1)
  })

  it('未知 key（future_signal）仍回退英文原名，Σbreakdown==score 时无容差告警', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    try {
      // 0.5 + 0.25 + 0.125 = 0.875（二进制精确，reduce 逐步和无舍入误差）
      const breakdown = {
        text: 0.5,
        domain: 0.25,
        future_signal: 0.125,
      }
      const { wrapper } = mountPanelWith([candidateWithBreakdown(breakdown, 0.875)])

      const trigger = findBreakdownTrigger(wrapper)
      expect(trigger).toBeDefined()
      await trigger!.trigger('click')
      await nextTick()

      // 未知 key 回退英文原名（向前兼容既有行为回归断言）
      expect(wrapper.text()).toContain('future_signal')
      // Σbreakdown === score → 容差校验静默（重归一化兼容断言）
      const mismatchWarns = warnSpy.mock.calls.filter(c =>
        String(c[0]).includes('breakdown 合计与 score 不一致'),
      )
      expect(mismatchWarns.length).toBe(0)
    }
    finally {
      warnSpy.mockRestore()
    }
  })
})

// ---------------------------------------------------------------------------
// Phase 107-09 Task 2：分区呈现 / Top-3 与 pin-in / 跨组标注 / 迟滞置顶提示
// （ROUTE-01 / ROUTE-02，UI-SPEC §交互契约 A/B）
// ---------------------------------------------------------------------------

const IN_PROJECT_LABEL = '本项目关联仓'
const GLOBAL_LABEL = '全局候选'
const CROSS_GROUP_SENTENCE = '未关联当前平台，可能涉及跨组协作'
const PROMOTION_SENTENCE = '更匹配的仓不在本项目关联范围内'

function cand(id: string, extra: Partial<RoutingCandidate> = {}): RoutingCandidate {
  return {
    repository_id: id,
    repository_name: id,
    score: 0.5,
    level: 'medium',
    evidence: `ev-${id}`,
    selected_by_ai: false,
    selected_by_user_final: false,
    ...extra,
  }
}

function mountTrace(overrides: Partial<RoutingDecisionData>) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useRoutingStore()
  store.upsertTrace({ ...makeTrace(), ...overrides }, 'conv-1')
  const wrapper = mount(RoutingDecisionPanel, {
    global: { plugins: [pinia] },
    props: {
      traceId: overrides.trace_id ?? 'trace-1',
      conversationId: 'conv-1',
      messageId: 'msg-1',
    },
  })
  return { wrapper, store }
}

/** 默认折叠场景：本项目在前 + 首位高置信（UI-SPEC 默认折叠判定两条同时成立）。 */
function collapsedGlobalTrace(): Partial<RoutingDecisionData> {
  return {
    block_order: ['in_project', 'global'],
    candidates: [
      cand('ip-a', { group: 'in_project', score: 0.9, level: 'high' }),
      cand('gl-a', { group: 'global', score: 0.6 }),
    ],
  }
}

function findButtonWith(
  wrapper: ReturnType<typeof mountTrace>['wrapper'],
  text: string,
) {
  return wrapper.findAll('button').find(b => b.text().includes(text))
}

function crossGroupBadges(wrapper: ReturnType<typeof mountTrace>['wrapper']) {
  return wrapper
    .findAllComponents({ name: 'Badge' })
    .filter(b => b.text().includes('跨组'))
}

describe('routingDecisionPanel 分组分区（ROUTE-01）', () => {
  it('区顺序严格等于后端 block_order（global 置顶时全局组标题先出现）', () => {
    const { wrapper } = mountTrace({
      block_order: ['global', 'in_project'],
      candidates: [
        cand('ip-a', { group: 'in_project', score: 0.9, level: 'high' }),
        cand('gl-a', { group: 'global', score: 0.4 }),
      ],
    })
    const text = wrapper.text()
    expect(text.indexOf(GLOBAL_LABEL)).toBeGreaterThanOrEqual(0)
    expect(text.indexOf(IN_PROJECT_LABEL)).toBeGreaterThan(text.indexOf(GLOBAL_LABEL))
  })

  it('区内按 score_ranked 降序（与 score 顺序相反时以 score_ranked 为准）', () => {
    const { wrapper } = mountTrace({
      block_order: ['in_project', 'global'],
      candidates: [
        cand('ip-low-rank', { group: 'in_project', score: 0.9, score_ranked: 0.1 }),
        cand('ip-high-rank', { group: 'in_project', score: 0.2, score_ranked: 0.99 }),
      ],
    })
    const text = wrapper.text()
    expect(text.indexOf('ip-high-rank')).toBeGreaterThanOrEqual(0)
    expect(text.indexOf('ip-high-rank')).toBeLessThan(text.indexOf('ip-low-rank'))
  })

  it('score_ranked 为 null / 缺失 → 回退 score 参与排序（混合不抛）', () => {
    const { wrapper } = mountTrace({
      block_order: ['in_project', 'global'],
      candidates: [
        cand('ip-mid', { group: 'in_project', score: 0.5, score_ranked: null }),
        cand('ip-top', { group: 'in_project', score: 0.8 }),
        cand('ip-bottom', { group: 'in_project', score: 0.1, score_ranked: 0.05 }),
      ],
    })
    const text = wrapper.text()
    expect(text.indexOf('ip-top')).toBeLessThan(text.indexOf('ip-mid'))
    expect(text.indexOf('ip-mid')).toBeLessThan(text.indexOf('ip-bottom'))
  })

  it('本项目在前且首位高置信 → 全局组默认折叠（标题在、候选不可见）', () => {
    const { wrapper } = mountTrace(collapsedGlobalTrace())
    expect(wrapper.text()).toContain(GLOBAL_LABEL)
    expect(wrapper.text()).not.toContain('gl-a')
  })

  it('本项目首位非高置信 → 全局组默认展开', () => {
    const { wrapper } = mountTrace({
      block_order: ['in_project', 'global'],
      candidates: [
        cand('ip-a', { group: 'in_project', score: 0.6, level: 'medium' }),
        cand('gl-a', { group: 'global', score: 0.5 }),
      ],
    })
    expect(wrapper.text()).toContain('gl-a')
  })

  it('用户手动展开后本地态优先；trace 变化后重算默认态', async () => {
    const { wrapper, store } = mountTrace(collapsedGlobalTrace())
    expect(wrapper.text()).not.toContain('gl-a')

    const trigger = findButtonWith(wrapper, GLOBAL_LABEL)
    expect(trigger).toBeDefined()
    await trigger!.trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('gl-a')

    // override 写新 trace → effectiveTraceId 变化 → 折叠态回到默认（折叠）
    store.upsertTrace(
      { ...makeTrace(), ...collapsedGlobalTrace(), trace_id: 'trace-2' },
      'conv-1',
    )
    await nextTick()
    expect(wrapper.text()).not.toContain('gl-a')
  })

  it('Top-3 截断 + 已选候选 pin-in；溢出 trigger 文案与组标题总数', async () => {
    const { wrapper } = mountTrace({
      block_order: ['in_project', 'global'],
      candidates: [
        cand('ip-1', { group: 'in_project', score: 0.9 }),
        cand('ip-2', { group: 'in_project', score: 0.8 }),
        cand('ip-3', { group: 'in_project', score: 0.7 }),
        cand('ip-4', { group: 'in_project', score: 0.6 }),
        cand('ip-5', { group: 'in_project', score: 0.5, selected_by_user_final: true }),
      ],
    })
    const text = wrapper.text()
    // 组标题计数为该组总数（不是可见数）
    expect(text).toContain(IN_PROJECT_LABEL)
    expect(text).toContain('（5）')
    for (const id of ['ip-1', 'ip-2', 'ip-3', 'ip-5'])
      expect(text).toContain(id)
    expect(text).not.toContain('ip-4')

    const trigger = findButtonWith(wrapper, '显示其余')
    expect(trigger?.text()).toContain('显示其余 1 个候选')
    await trigger!.trigger('click')
    await nextTick()
    expect(wrapper.text()).toContain('ip-4')
    expect(findButtonWith(wrapper, '收起其余候选')).toBeDefined()
  })

  it('空组不渲染（block_order 长度 2 但全局组 0 条）', () => {
    const { wrapper } = mountTrace({
      block_order: ['in_project', 'global'],
      candidates: [cand('ip-a', { group: 'in_project', score: 0.9, level: 'high' })],
    })
    const text = wrapper.text()
    expect(text).toContain(IN_PROJECT_LABEL)
    expect(text).not.toContain(GLOBAL_LABEL)
    expect(text).not.toContain(CROSS_GROUP_SENTENCE)
  })

  it('block_order 缺失但存在 in_project 候选 → 按 [in_project, global] 启用分组', () => {
    const { wrapper } = mountTrace({
      candidates: [
        cand('ip-a', { group: 'in_project', score: 0.9, level: 'medium' }),
        cand('gl-a', { group: 'global', score: 0.5 }),
      ],
    })
    const text = wrapper.text()
    expect(text.indexOf(IN_PROJECT_LABEL)).toBeGreaterThanOrEqual(0)
    expect(text.indexOf(GLOBAL_LABEL)).toBeGreaterThan(text.indexOf(IN_PROJECT_LABEL))
  })

  it('block_order 长度 1（无项目上下文）→ 平铺、无组标题与跨组标注', () => {
    const { wrapper } = mountTrace({
      block_order: ['global'],
      candidates: [
        cand('gl-a', { group: 'global', score: 0.9, level: 'high' }),
        cand('gl-b', { group: 'global', score: 0.4 }),
      ],
    })
    const text = wrapper.text()
    expect(text).toContain('gl-a')
    expect(text).not.toContain(GLOBAL_LABEL)
    expect(text).not.toContain(CROSS_GROUP_SENTENCE)
    expect(crossGroupBadges(wrapper).length).toBe(0)
  })

  it('历史 trace（无 block_order / group / score_ranked）→ 单个平铺 ul、零新增标注', () => {
    const { wrapper } = mountPanel()
    const text = wrapper.text()
    expect(text).not.toContain(IN_PROJECT_LABEL)
    expect(text).not.toContain(GLOBAL_LABEL)
    expect(text).not.toContain(CROSS_GROUP_SENTENCE)
    expect(text).not.toContain(PROMOTION_SENTENCE)
    expect(crossGroupBadges(wrapper).length).toBe(0)
    expect(wrapper.findAll('ul').length).toBe(1)
  })
})

describe('routingDecisionPanel 跨组标注与置顶提示（ROUTE-02）', () => {
  it('跨组两层：组级说明句常驻 + 每个全局候选带跨组 Badge（本项目候选无）', () => {
    const { wrapper } = mountTrace({
      block_order: ['global', 'in_project'],
      candidates: [
        cand('gl-a', { group: 'global', score: 0.9, level: 'high' }),
        cand('gl-b', { group: 'global', score: 0.8 }),
        cand('ip-a', { group: 'in_project', score: 0.7 }),
      ],
    })
    expect(wrapper.text()).toContain(CROSS_GROUP_SENTENCE)
    const badges = crossGroupBadges(wrapper)
    expect(badges.length).toBe(2)
    expect(badges[0].attributes('aria-label')).toBe(CROSS_GROUP_SENTENCE)
  })

  it('缺 group 的候选视为 global（分组启用时也带跨组 Badge）', () => {
    const { wrapper } = mountTrace({
      block_order: ['in_project', 'global'],
      candidates: [
        cand('ip-a', { group: 'in_project', score: 0.6, level: 'medium' }),
        cand('unknown-group', { score: 0.5 }),
      ],
    })
    expect(wrapper.text()).toContain(GLOBAL_LABEL)
    expect(crossGroupBadges(wrapper).length).toBe(1)
  })

  it('block_order[0]===global → 出现 role=status 置顶提示；in_project 在前则无', () => {
    const promoted = mountTrace({
      block_order: ['global', 'in_project'],
      candidates: [
        cand('gl-a', { group: 'global', score: 0.9, level: 'high' }),
        cand('ip-a', { group: 'in_project', score: 0.7 }),
      ],
    })
    expect(promoted.wrapper.text()).toContain(PROMOTION_SENTENCE)
    expect(promoted.wrapper.find('[role="status"]').exists()).toBe(true)

    const normal = mountTrace(collapsedGlobalTrace())
    expect(normal.wrapper.text()).not.toContain(PROMOTION_SENTENCE)
    expect(normal.wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
