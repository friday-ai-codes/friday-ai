/**
 * ：chat store 协商卡片状态机测试。
 */
import type { ClarificationPayload } from '~/types/clarification'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getConversationRuntime } from '~/api/chat'
import { useChatStore } from '~/stores/chat'

// 仅替换 getConversationRuntime（runtime 回灌 plan 澄清卡的数据源），其余 API 保持真实。
vi.mock('~/api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('~/api/chat')>()
  return { ...actual, getConversationRuntime: vi.fn() }
})

function makePayload(overrides: Partial<ClarificationPayload> = {}): ClarificationPayload {
  return {
    clarification_id: 'clar-1',
    question: 'A or B?',
    options: [
      { id: 'opt-A', label: 'A' },
      { id: 'opt-B', label: 'B' },
    ],
    allow_freeform: true,
    status: 'pending',
    ...overrides,
  }
}

describe('chat store - clarifications', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('upsertClarification 添加一条记录', () => {
    const store = useChatStore()
    expect(store.pendingClarifications.size).toBe(0)
    store.upsertClarification(makePayload())
    expect(store.pendingClarifications.size).toBe(1)
    expect(store.getClarification('clar-1')?.status).toBe('pending')
  })

  it('upsertClarification 重复 id 覆盖原值', () => {
    const store = useChatStore()
    store.upsertClarification(makePayload({ question: '第一次' }))
    store.upsertClarification(makePayload({ question: '第二次' }))
    expect(store.getClarification('clar-1')?.question).toBe('第二次')
    expect(store.pendingClarifications.size).toBe(1)
  })

  it('markClarificationAnswered 切换 status + 写 answer', () => {
    const store = useChatStore()
    store.upsertClarification(makePayload())
    store.markClarificationAnswered('clar-1', {
      selected_option_id: 'opt-A',
      freeform_text: '',
      answered_at: '2026-05-21T00:00:00Z',
    })
    const result = store.getClarification('clar-1')
    expect(result?.status).toBe('answered')
    expect(result?.answer?.selected_option_id).toBe('opt-A')
  })

  it('markClarificationAnswered 不存在的 id 静默忽略', () => {
    const store = useChatStore()
    expect(() => store.markClarificationAnswered('not-exist', {
      selected_option_id: 'x',
      answered_at: 'now',
    })).not.toThrow()
    expect(store.pendingClarifications.size).toBe(0)
  })

  it('clearAllClarifications 清空 Map', () => {
    const store = useChatStore()
    store.upsertClarification(makePayload({ clarification_id: 'a' }))
    store.upsertClarification(makePayload({ clarification_id: 'b' }))
    expect(store.pendingClarifications.size).toBe(2)
    store.clearAllClarifications()
    expect(store.pendingClarifications.size).toBe(0)
  })

  it('answered 后保留在 Map 中（消息流不删）', () => {
    const store = useChatStore()
    store.upsertClarification(makePayload())
    store.markClarificationAnswered('clar-1', {
      selected_option_id: 'opt-A',
      answered_at: 'now',
    })
    expect(store.pendingClarifications.size).toBe(1)
    expect(store.getClarification('clar-1')?.status).toBe('answered')
  })

  /**
   * 澄清卡内联锚定：upsert 记录「当时最后一条消息」为锚点；答复时固化锚点。
   * ChatMessageArea 据此把卡片内联在消息流触发位置，答复后新消息在卡片下方继续。
   */
  describe('内联锚点（anchor_message_id）', () => {
    function msg(id: string) {
      return { id, role: 'user', content: 'x', created_at: '2026-07-02T00:00:00Z' } as any
    }

    it('upsert 时记录当时最后一条消息为锚点', () => {
      const store = useChatStore()
      store.messages = [msg('m1'), msg('m2')]
      store.upsertClarification(makePayload())
      expect(store.getClarification('clar-1')?.anchor_message_id).toBe('m2')
    })

    it('re-upsert 不重算锚点（回灌/重复事件不漂移）', () => {
      const store = useChatStore()
      store.messages = [msg('m1')]
      store.upsertClarification(makePayload())
      store.messages = [msg('m1'), msg('m2')]
      store.upsertClarification(makePayload({ question: '更新' }))
      expect(store.getClarification('clar-1')?.anchor_message_id).toBe('m1')
    })

    it('markClarificationAnswered 固化锚点为答复时刻的最后一条消息', () => {
      const store = useChatStore()
      store.messages = [msg('m1')]
      store.upsertClarification(makePayload())
      store.messages = [msg('m1'), msg('m2')]
      store.markClarificationAnswered('clar-1', {
        selected_option_id: 'opt-A',
        answered_at: 'now',
      })
      expect(store.getClarification('clar-1')?.anchor_message_id).toBe('m2')
      // 答复后新消息追加不再影响锚点
      store.messages = [msg('m1'), msg('m2'), msg('m3')]
      expect(store.getClarification('clar-1')?.anchor_message_id).toBe('m2')
    })
  })

  /**
   * UAT 2026-05-27 hotfix（284 round 2）：跨 conversation 串单回归。
   *
   * 复现 284-UAT.md round 2 Gap：用户在 conv 78681e45 (entrance) 视图里
   * 看到了 conv 3673d77b (operationResource) 的 ClarificationCard。
   */
  describe('跨 conversation 串单防护（284 round 2 hotfix）', () => {
    it('upsertClarification 显式传 conversationId 写入 payload', () => {
      const store = useChatStore()
      store.upsertClarification(makePayload({ clarification_id: 'c-a' }), 'conv-A')
      const saved = store.getClarification('c-a')
      expect(saved?.conversation_id).toBe('conv-A')
    })

    it('upsertClarification 不传 conversationId 时回退到当前 conv', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-fallback'
      store.upsertClarification(makePayload({ clarification_id: 'c-b' }))
      expect(store.getClarification('c-b')?.conversation_id).toBe('conv-fallback')
    })

    it('payload 已带 conversation_id 时优先用 caller 传入值（caller wins）', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-current'
      store.upsertClarification(
        makePayload({ clarification_id: 'c-c', conversation_id: 'conv-from-payload' }),
        'conv-from-caller',
      )
      expect(store.getClarification('c-c')?.conversation_id).toBe('conv-from-caller')
    })

    it('两个 conv 的 clarification 共存于 Map 时各自带 conv 维度（前端 filter 可分流）', () => {
      const store = useChatStore()
      store.upsertClarification(makePayload({ clarification_id: 'c-A' }), 'conv-A')
      store.upsertClarification(makePayload({ clarification_id: 'c-B' }), 'conv-B')
      expect(store.pendingClarifications.size).toBe(2)
      const onlyA = [...store.pendingClarifications.values()].filter(
        p => p.conversation_id === 'conv-A',
      )
      expect(onlyA.length).toBe(1)
      expect(onlyA[0].clarification_id).toBe('c-A')
    })

    it('legacy payload (无 conversation_id) + 未设 currentConversationId 时 conversation_id 为 undefined（向后兼容）', () => {
      const store = useChatStore()
      // currentConversationId 保持 null（未设）
      store.upsertClarification(makePayload({ clarification_id: 'c-legacy' }))
      const saved = store.getClarification('c-legacy')
      expect(saved?.conversation_id).toBeUndefined()
    })
  })

  /**
   * 284 round 2 Fix C-1：phase_transition(waiting_clarification) event 直接 upsert。
   *
   * 编排层 `_extract_relev_low_confidence_pending` 自动构造的 clarification
   * 不会产生 `tool_use_result(ask_clarification)` 事件（LLM 没主动调工具）—— 前
   * 端必须在 `phase_transition` 事件携带 question/options 时直接 upsert，否则
   * ClarificationCard 永远不渲染、用户答不了 → graph 永久 hang。
   */
  describe('phase_transition event 路径自动 upsert（284 round 2 Fix C-1）', () => {
    it('phase=waiting_clarification + question/options 完整时调 upsertClarification', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-pt-1'

      store._dispatchSSE({
        type: 'phase_transition',
        phase: 'waiting_clarification',
        clarification_id: 'c-from-pt-1',
        question: '请确认要看哪个仓库？',
        options: [
          { id: 'opt-A', label: 'example-app' },
          { id: 'opt-B', label: 'problem-app' },
        ],
        allow_freeform: true,
      })

      const saved = store.getClarification('c-from-pt-1')
      expect(saved).toBeDefined()
      expect(saved?.question).toBe('请确认要看哪个仓库？')
      expect(saved?.options.length).toBe(2)
      expect(saved?.allow_freeform).toBe(true)
      expect(saved?.status).toBe('pending')
      expect(saved?.conversation_id).toBe('conv-pt-1')
    })

    it('phase=waiting_clarification 但 question 缺失 → 不 upsert（防空卡片）', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-pt-2'

      store._dispatchSSE({
        type: 'phase_transition',
        phase: 'waiting_clarification',
        clarification_id: 'c-no-question',
      })

      expect(store.getClarification('c-no-question')).toBeUndefined()
    })

    it('phase 是其他态（如 waiting / executing）→ 不 upsert', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-pt-3'

      store._dispatchSSE({
        type: 'phase_transition',
        phase: 'waiting',
        blocking_task_count: 2,
      })
      store._dispatchSSE({
        type: 'phase_transition',
        phase: 'executing',
      })

      expect(store.pendingClarifications.size).toBe(0)
    })

    it('allow_freeform 缺失时默认 true（兼容老后端 payload）', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-pt-4'

      store._dispatchSSE({
        type: 'phase_transition',
        phase: 'waiting_clarification',
        clarification_id: 'c-no-freeform-flag',
        question: '请选择',
        options: [{ id: 'opt-A', label: 'A' }],
        // allow_freeform 缺失
      })

      expect(store.getClarification('c-no-freeform-flag')?.allow_freeform).toBe(true)
    })

    it('options 缺失或非数组时 fallback 空数组（防类型异常）', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-pt-5'

      store._dispatchSSE({
        type: 'phase_transition',
        phase: 'waiting_clarification',
        clarification_id: 'c-bad-options',
        question: '请选择',
        // options 缺失
      })

      expect(store.getClarification('c-bad-options')?.options).toEqual([])
    })
  })

  /**
   * UNIFY-05 / WARNING 3（94-05）：plan 澄清卡不依赖 marker 字面值。
   *
   * 94-05 后端把 plan 澄清挂起 marker 从 `ask_clarification` 改名为
   * `plan_clarification`（仅前端渲染信号，权威在 delivery.Clarification + PlanSession）。
   * 前端 plan 澄清卡由 91-04 runtime `pending_plan_clarification`（session_id /
   * clarification_id / questions）驱动，**不读任何 marker 字面值** —— marker 改名
   * 对 plan 卡渲染零影响；且 chat 单题路径仍仅认 `ask_clarification`，renamed
   * plan marker 不会被误认成 chat 单题澄清。
   */
  describe('plan 澄清卡 runtime 驱动 + marker 字面非依赖（94-05 UNIFY-05 / WARNING 3）', () => {
    beforeEach(() => {
      vi.mocked(getConversationRuntime).mockReset()
      // chat 单题 ask_clarification 解析在 legacy tool_use_* 路径（'new' 协议下走 part_*）；
      // 显式切 legacy 以单测覆盖 marker 双条件判定（生产灰度同机制，见 useChatPartsProtocol）。
      localStorage.setItem('chat-parts-protocol', 'legacy')
    })

    afterEach(() => {
      localStorage.removeItem('chat-parts-protocol')
    })

    it('① plan 澄清卡由 pending_plan_clarification runtime（session_id/clarification_id）驱动渲染，不读 marker 字面值', async () => {
      const store = useChatStore()
      // runtime 回灌 payload **故意不含任何 marker 字段** —— 若渲染依赖 marker 字面值则此卡渲染不出。
      vi.mocked(getConversationRuntime).mockResolvedValue({
        active: false,
        pending_plan_clarification: {
          clarification_id: 'plan-clar-1',
          round_no: 1,
          questions: [
            {
              question_id: 'q1',
              question: '选哪种鉴权方案？',
              qtype: 'single',
              options: ['JWT', 'Session'],
              recommended: 'JWT',
            },
          ],
        },
      } as any)

      await store.restoreConversationRuntime('conv-plan-1')

      // 标识键取自 clarification_id（runtime 字段），卡渲染成功 → 证明 marker 字面非渲染依赖
      const card = store.getPlanClarification('plan-clar-1')
      expect(card).toBeDefined()
      expect(card?.clarification_id).toBe('plan-clar-1')
      expect(card?.round_no).toBe(1)
      expect(card?.questions.length).toBe(1)
      expect(card?.status).toBe('pending')
      expect(card?.conversation_id).toBe('conv-plan-1')
      // payload 对象上不存在 marker 字段（plan 卡契约本就不含 marker）
      expect((card as unknown as Record<string, unknown>).marker).toBeUndefined()
      // 未误入 chat 单题澄清 Map
      expect(store.getClarification('plan-clar-1')).toBeUndefined()
    })

    it('① 旁证：questions 为空的 runtime 不进 plan 澄清面（旧单题行不误入）', async () => {
      const store = useChatStore()
      vi.mocked(getConversationRuntime).mockResolvedValue({
        active: false,
        pending_plan_clarification: {
          clarification_id: 'plan-clar-empty',
          round_no: 1,
          questions: [],
        },
      } as any)

      await store.restoreConversationRuntime('conv-plan-2')

      expect(store.getPlanClarification('plan-clar-empty')).toBeUndefined()
    })

    it('② chat 单题路径仍仅认 marker===ask_clarification：renamed plan_clarification marker 不被误认单题卡', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-marker-1'

      // 模拟 renamed plan marker 偷渡进 ask_clarification 工具结果：marker=plan_clarification
      store._dispatchSSE({
        type: 'tool_use_start',
        tool_call_id: 'tc-plan-marker',
        tool_name: 'ask_clarification',
        input: {},
      })
      store._dispatchSSE({
        type: 'tool_use_result',
        tool_call_id: 'tc-plan-marker',
        result: JSON.stringify({
          pending: true,
          marker: 'plan_clarification',
          clarification_id: 'leaked-plan-1',
          question: 'q',
          options: [],
          allow_freeform: true,
        }),
      })

      // 双条件 parsed.marker==='ask_clarification' 不命中 → 不弹 chat 单题卡
      expect(store.getClarification('leaked-plan-1')).toBeUndefined()
    })

    it('② 对照零回归：marker===ask_clarification 仍被识别为 chat 单题澄清', () => {
      const store = useChatStore()
      store.currentConversationId = 'conv-marker-2'

      store._dispatchSSE({
        type: 'tool_use_start',
        tool_call_id: 'tc-chat-marker',
        tool_name: 'ask_clarification',
        input: {},
      })
      store._dispatchSSE({
        type: 'tool_use_result',
        tool_call_id: 'tc-chat-marker',
        result: JSON.stringify({
          pending: true,
          marker: 'ask_clarification',
          clarification_id: 'chat-single-1',
          question: '你想动哪个仓库？',
          options: [{ id: 'opt-A', label: 'example-app' }],
          allow_freeform: true,
        }),
      })

      const card = store.getClarification('chat-single-1')
      expect(card).toBeDefined()
      expect(card?.question).toBe('你想动哪个仓库？')
      expect(card?.status).toBe('pending')
    })
  })
})
