/**
 * ClarificationCard 守护测试（91-05 CLARIFY-04：plan 多题多选澄清 + 单题零回归）。
 *
 * 覆盖：
 * - plan 多题轮渲染（single/multi）+ ⭐推荐默认选中（single 取一项 / multi 取全部推荐）
 * - single 单选互斥 / multi 多选 Set 语义（累加/取消）
 * - 提交聚合 answers:[{question_id, selected: single=str|multi=string[], freeform_text}]
 *   打 postPlanClarificationAnswer + 成功切「已回复」(markPlanClarificationAnswered)
 * - i18n 真实 zh-CN.json 守护关键文案（推荐 / 提交答复 /（可多选）不被改空）
 * - 既有 chat 单题澄清路径零回归（postClarificationAnswer 仍被调）
 */
import type { ClarificationPayload, PlanClarificationPayload } from '~/types/clarification'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

const postPlanClarificationAnswerMock = vi.fn()
const postClarificationAnswerMock = vi.fn()
vi.mock('~/api/chat', () => ({
  postPlanClarificationAnswer: (...a: unknown[]) => postPlanClarificationAnswerMock(...a),
  postClarificationAnswer: (...a: unknown[]) => postClarificationAnswerMock(...a),
}))

const markPlanClarificationAnsweredMock = vi.fn()
const markClarificationAnsweredMock = vi.fn()
const skipClarificationMock = vi.fn()
vi.mock('~/stores/chat', () => ({
  useChatStore: () => ({
    currentConversationId: 'conv-1',
    markPlanClarificationAnswered: markPlanClarificationAnsweredMock,
    markClarificationAnswered: markClarificationAnsweredMock,
    skipClarification: skipClarificationMock,
  }),
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const ClarificationCard = (await import('../ClarificationCard.vue')).default

function planPayload(overrides: Partial<PlanClarificationPayload> = {}): PlanClarificationPayload {
  return {
    clarification_id: 'pc-1',
    round_no: 1,
    conversation_id: 'conv-1',
    status: 'pending',
    questions: [
      {
        question_id: 'q1',
        question: '选择目标分支策略',
        qtype: 'single',
        options: ['main', 'develop', 'release'],
        recommended: 'develop',
      },
      {
        question_id: 'q2',
        question: '需要覆盖的测试类型',
        qtype: 'multi',
        options: ['unit', 'integration', 'e2e'],
        recommended: ['unit', 'integration'],
      },
    ],
    ...overrides,
  }
}

function mountPlan(payload: PlanClarificationPayload) {
  return mount(ClarificationCard, {
    props: { payload },
    global: { plugins: [i18n] },
  })
}

function optionBtn(wrapper: any, qid: string, value: string) {
  return wrapper.find(`[data-question-id="${qid}"] [data-option][data-value="${value}"]`)
}

beforeEach(() => {
  vi.clearAllMocks()
  postPlanClarificationAnswerMock.mockResolvedValue({ status: 'accepted' })
  postClarificationAnswerMock.mockResolvedValue({
    selected_option_id: 'a',
    freeform_text: '',
    answered_at: '2026-06-27T00:00:00Z',
  })
})

describe('clarificationCard - plan 多题多选', () => {
  it('渲染多题并按推荐默认选中（single 一项 / multi 全部推荐）', () => {
    const wrapper = mountPlan(planPayload())
    // 两题都渲染
    expect(wrapper.find('[data-question-id="q1"]').exists()).toBe(true)
    expect(wrapper.find('[data-question-id="q2"]').exists()).toBe(true)
    // q1 single 默认选中 develop
    expect(optionBtn(wrapper, 'q1', 'develop').attributes('aria-checked')).toBe('true')
    expect(optionBtn(wrapper, 'q1', 'main').attributes('aria-checked')).toBe('false')
    // q2 multi 默认选中 unit + integration（非 e2e）
    expect(optionBtn(wrapper, 'q2', 'unit').attributes('aria-checked')).toBe('true')
    expect(optionBtn(wrapper, 'q2', 'integration').attributes('aria-checked')).toBe('true')
    expect(optionBtn(wrapper, 'q2', 'e2e').attributes('aria-checked')).toBe('false')
  })

  it('single 单选互斥：点其他项只保留一个', async () => {
    const wrapper = mountPlan(planPayload())
    await optionBtn(wrapper, 'q1', 'main').trigger('click')
    expect(optionBtn(wrapper, 'q1', 'main').attributes('aria-checked')).toBe('true')
    expect(optionBtn(wrapper, 'q1', 'develop').attributes('aria-checked')).toBe('false')
    expect(optionBtn(wrapper, 'q1', 'release').attributes('aria-checked')).toBe('false')
  })

  it('multi 多选 Set 语义：累加与取消', async () => {
    const wrapper = mountPlan(planPayload())
    // 取消 unit
    await optionBtn(wrapper, 'q2', 'unit').trigger('click')
    expect(optionBtn(wrapper, 'q2', 'unit').attributes('aria-checked')).toBe('false')
    // 加 e2e
    await optionBtn(wrapper, 'q2', 'e2e').trigger('click')
    expect(optionBtn(wrapper, 'q2', 'e2e').attributes('aria-checked')).toBe('true')
    // integration 仍在
    expect(optionBtn(wrapper, 'q2', 'integration').attributes('aria-checked')).toBe('true')
  })

  it('提交聚合 answers[] 命中专路由：single=str / multi=string[]，并切已回复', async () => {
    const wrapper = mountPlan(planPayload())
    await wrapper.find('[data-testid="plan-clarification-submit"]').trigger('click')
    await flushPromises()

    expect(postPlanClarificationAnswerMock).toHaveBeenCalledTimes(1)
    const [convId, body] = postPlanClarificationAnswerMock.mock.calls[0]
    expect(convId).toBe('conv-1')
    const answers = body.answers
    const a1 = answers.find((a: any) => a.question_id === 'q1')
    const a2 = answers.find((a: any) => a.question_id === 'q2')
    expect(a1.selected).toBe('develop')
    expect(Array.isArray(a2.selected)).toBe(true)
    expect([...a2.selected].sort()).toEqual(['integration', 'unit'])

    expect(markPlanClarificationAnsweredMock).toHaveBeenCalledWith('pc-1')
  })

  it('i18n 真实文案守护：推荐 /（可多选）/ 提交答复 不被改空', () => {
    const wrapper = mountPlan(planPayload())
    const text = wrapper.text()
    expect(text).toContain('推荐')
    expect(text).toContain('提交答复')
    // q2 为多选题，应出现多选提示
    expect(text).toContain('可多选')
  })
})

describe('clarificationCard - 既有 chat 单题零回归', () => {
  function singlePayload(): ClarificationPayload {
    return {
      clarification_id: 'c-1',
      question: '你想做什么？',
      options: [
        { id: 'a', label: '选项A' },
        { id: 'b', label: '选项B' },
      ],
      allow_freeform: true,
      status: 'pending',
      conversation_id: 'conv-1',
    }
  }

  it('渲染单题并提交走 postClarificationAnswer（不串 plan 路径）', async () => {
    const wrapper = mount(ClarificationCard, {
      props: { payload: singlePayload() },
      global: { plugins: [i18n] },
    })
    // 单题问题渲染
    expect(wrapper.text()).toContain('你想做什么？')
    // 无 plan 多题容器
    expect(wrapper.find('[data-question-id]').exists()).toBe(false)
    // 选一个选项再提交
    const optBtns = wrapper.findAll('[role="radio"]')
    await optBtns[0].trigger('click')
    await wrapper.findAll('button').filter(b => b.text().includes('提交答复'))[0].trigger('click')
    await flushPromises()
    expect(postClarificationAnswerMock).toHaveBeenCalledTimes(1)
    expect(postPlanClarificationAnswerMock).not.toHaveBeenCalled()
  })
})
