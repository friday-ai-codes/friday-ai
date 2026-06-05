/**
 * ：RoutingDecisionPanel.vue 组件单测。
 *
 * 覆盖：渲染 + 排序 + Badge variant / Tooltip evidence /
 * Checkbox v-model / debounce manual override / 折叠 / emit 事件。
 */

import type { RoutingDecisionData } from '~/types/routing'
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
