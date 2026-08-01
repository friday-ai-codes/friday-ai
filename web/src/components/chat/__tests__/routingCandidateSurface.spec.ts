/**
 * ROUTE-01 / ROUTE-02 / ROUTE-07 / RELY-03 的**挂载面**契约测试。
 *
 * 🔴 本文件刻意**不**单独 mount `RoutingCandidateList`。这四条需求此前之所以
 * 在五个相位全绿的情况下仍然对用户不成立，正是因为当时的证据是「组件内有渲染
 * 分支 + 组件单测通过」——而承载它们的组件没有任何挂载点。在叶子组件上取证会
 * 原样重犯那个错误。
 *
 * 所以这里一律从 `ChatMessageBubble`（用户真正看到的那层宿主）出发，走用户
 * 真实的两次点击（展开「分析过程」→ 展开「仓库分级路由」那一步），再断言组
 * 标题 / 跨组说明句 / 分数分解 / 降级解释句可达。任何一环断了（比如把
 * `RoutingCandidateList` 从 `ToolProcessGroup` 里摘掉），这些用例都会红。
 */

import type { ConversationMessage, ToolUsePart } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'

vi.mock('~/composables/useMarkdownRenderer', () => ({
  getMarkdownRenderer: vi.fn(async () => ({
    render: (raw: string) => `<div data-test="md">${raw}</div>`,
  })),
}))

vi.mock('~/components/ui/checkbox', () => ({
  Checkbox: defineComponent({ name: 'Checkbox', setup: () => () => h('input', { type: 'checkbox' }) }),
}))

interface CandidateSeed {
  repository_id: string
  repository_name: string
  score: number
  level: 'high' | 'medium' | 'low'
  evidence?: string
  group?: string
  breakdown?: Record<string, number>
  score_ranked?: number
}

interface ResultSeed {
  candidates: CandidateSeed[]
  block_order?: string[]
  degraded?: boolean
  degrade_reason?: string
}

function relevanceResult(seed: ResultSeed): string {
  return JSON.stringify({
    data: {
      trace_id: 'trace-1',
      threshold: 0.5,
      total_candidates: seed.candidates.length,
      ...seed,
    },
  })
}

function relevanceMessage(seed: ResultSeed): ConversationMessage {
  const part: ToolUsePart = {
    type: 'tool_use',
    id: 'p_relev',
    index: 0,
    tool_call_id: 'call_relev',
    name: 'analyze_repository_relevance',
    input: { query: '给登录页加验证码' },
    status: 'done',
    result: relevanceResult(seed),
  }
  return {
    id: 'msg-relev',
    role: 'assistant',
    content: '已完成仓库路由',
    parts: [part],
    created_at: '2026-08-01T00:00:00Z',
  }
}

/**
 * 走用户真实路径把候选清单点出来：展开过程面板 → 展开「仓库分级路由」这一步。
 * 返回 wrapper 供断言；任一步点不开即抛，等于把「面存在但点不到」也算失败。
 */
async function openRoutingDetail(seed: ResultSeed) {
  const wrapper = mount(ChatMessageBubble, {
    props: { message: relevanceMessage(seed), isStreaming: false },
  })
  await new Promise<void>(r => setTimeout(r, 0))
  await wrapper.vm.$nextTick()

  const head = wrapper.find('.tpg-head')
  expect(head.exists()).toBe(true)
  await head.trigger('click')

  const rowHead = wrapper.find('.tpg-row--tool .tpg-row-head')
  expect(rowHead.exists()).toBe(true)
  await rowHead.trigger('click')

  return wrapper
}

const GROUPED_SEED: ResultSeed = {
  block_order: ['in_project', 'global'],
  candidates: [
    {
      repository_id: 'r-in',
      repository_name: 'onion-web',
      score: 0.91,
      level: 'high',
      evidence: '命中登录模块',
      group: 'in_project',
      breakdown: { text: 0.7, breadth: 0.11, activity: 0.1 },
    },
    {
      repository_id: 'r-out',
      repository_name: 'sso-gateway',
      score: 0.62,
      level: 'medium',
      evidence: '命中验证码签发',
      group: 'global',
      breakdown: { text: 0.5, domain: 0.12 },
    },
  ],
}

describe('路由候选面（挂载于 ChatMessageBubble → ToolProcessGroup）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    window.localStorage.clear()
  })

  it('候选清单确实挂在气泡里（不是一个没有挂载点的组件）', async () => {
    const wrapper = await openRoutingDetail(GROUPED_SEED)
    expect(wrapper.find('[data-test="routing-candidate-list"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="routing-candidate"]')).toHaveLength(2)
  })

  it('「ROUTE-01」两组分别带组标题与组内计数，顺序取自后端 block_order', async () => {
    const wrapper = await openRoutingDetail(GROUPED_SEED)

    const headings = wrapper.findAll('[data-test="routing-group-heading"]')
    expect(headings).toHaveLength(2)
    expect(headings[0].text()).toContain('本项目关联仓')
    expect(headings[0].text()).toContain('（1）')
    expect(headings[1].text()).toContain('全局候选')
    expect(headings[1].text()).toContain('（1）')

    // 区顺序权威在后端：block_order 反过来，渲染顺序也必须跟着反过来
    const reversed = await openRoutingDetail({
      ...GROUPED_SEED,
      block_order: ['global', 'in_project'],
    })
    const reversedHeadings = reversed.findAll('[data-test="routing-group-heading"]')
    expect(reversedHeadings[0].text()).toContain('全局候选')
    expect(reversedHeadings[1].text()).toContain('本项目关联仓')
  })

  it('「ROUTE-01」block_order 缺失（历史结果）平铺，不出现组标题与跨组标注', async () => {
    const wrapper = await openRoutingDetail({ candidates: GROUPED_SEED.candidates })
    expect(wrapper.find('[data-test="routing-candidate-list"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-test="routing-candidate"]')).toHaveLength(2)
    expect(wrapper.find('[data-test="routing-group-heading"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="routing-cross-group-note"]').exists()).toBe(false)
  })

  it('「ROUTE-02」跨组候选带「未关联当前平台」说明句与候选级徽标', async () => {
    const wrapper = await openRoutingDetail(GROUPED_SEED)

    const note = wrapper.find('[data-test="routing-cross-group-note"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toBe('未关联当前平台，可能涉及跨组协作')

    // 只有全局组那一条挂徽标，本项目组那条不挂
    const badges = wrapper.findAll('[data-test="routing-cross-group-badge"]')
    expect(badges).toHaveLength(1)
    expect(badges[0].attributes('aria-label')).toBe('未关联当前平台，可能涉及跨组协作')
  })

  it('「ROUTE-02」全局组被置顶时给出因果句；本项目组为空时换成陈述句', async () => {
    const promoted = await openRoutingDetail({
      ...GROUPED_SEED,
      block_order: ['global', 'in_project'],
    })
    expect(promoted.find('[data-test="routing-promotion-notice"]').text())
      .toBe('更匹配的仓不在本项目关联范围内')

    const emptyInProject = await openRoutingDetail({
      block_order: ['global', 'in_project'],
      candidates: [GROUPED_SEED.candidates[1]],
    })
    expect(emptyInProject.find('[data-test="routing-promotion-notice"]').text())
      .toBe('本项目关联范围内没有匹配的仓库')
  })

  it('「ROUTE-07」分数分解默认收起，点开后逐信号可读且合计等于分数', async () => {
    const wrapper = await openRoutingDetail(GROUPED_SEED)

    const toggles = wrapper.findAll('[data-test="routing-breakdown-toggle"]')
    expect(toggles).toHaveLength(2)
    expect(wrapper.find('[data-test="routing-breakdown"]').exists()).toBe(false)
    expect(toggles[0].attributes('aria-expanded')).toBe('false')

    await toggles[0].trigger('click')

    const panel = wrapper.find('[data-test="routing-breakdown"]')
    expect(panel.exists()).toBe(true)
    expect(toggles[0].attributes('aria-expanded')).toBe('true')
    // 英文 key 翻成中文信号名，而不是把 `text` / `breadth` 直接摊给用户
    expect(panel.text()).toContain('文本相关')
    expect(panel.text()).toContain('0.700')
    expect(panel.text()).toContain('命中广度')
    expect(panel.text()).toContain('活跃度')
    expect(panel.text()).toContain('合计')
    expect(panel.text()).toContain('0.910')
  })

  it('「ROUTE-07」breakdown 缺失（legacy 结果）不出现展开入口，其余照常', async () => {
    const wrapper = await openRoutingDetail({
      block_order: ['in_project', 'global'],
      candidates: [{ ...GROUPED_SEED.candidates[0], breakdown: undefined }],
    })
    expect(wrapper.find('[data-test="routing-candidate"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="routing-breakdown-toggle"]').exists()).toBe(false)
  })

  it('「RELY-03」降级时横幅带解释句与受控闭集原因，且置信度徽标灰化', async () => {
    const wrapper = await openRoutingDetail({
      ...GROUPED_SEED,
      degraded: true,
      degrade_reason: 'timeout',
    })

    const banner = wrapper.find('[data-test="routing-degraded-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('本次未经 LLM 推理，置信度仅供参考')
    expect(banner.text()).toContain('降级原因：上游超时')
    expect(banner.attributes('role')).toBe('alert')

    // 灰化：颜色不再宣称「高置信可信」，但 level 文案本身不变
    const levelBadge = wrapper.find('[data-test="routing-level-badge"]')
    expect(levelBadge.text()).toContain('高')
    expect(levelBadge.classes().join(' ')).toContain('bg-gray-500/10')
  })

  it('「RELY-03」闭集外的降级原因回退「未知原因」，绝不回显原始值', async () => {
    const wrapper = await openRoutingDetail({
      ...GROUPED_SEED,
      degraded: true,
      degrade_reason: 'ConnectionResetError: upstream said <secret-token>',
    })
    const banner = wrapper.find('[data-test="routing-degraded-banner"]')
    expect(banner.text()).toContain('降级原因：未知原因')
    expect(banner.text()).not.toContain('secret-token')
    expect(banner.text()).not.toContain('ConnectionResetError')
  })

  it('「RELY-03」未降级时不出现横幅，徽标保持置信度配色', async () => {
    const wrapper = await openRoutingDetail(GROUPED_SEED)
    expect(wrapper.find('[data-test="routing-degraded-banner"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="routing-level-badge"]').classes().join(' '))
      .toContain('bg-emerald-500/10')
  })

  it('只读面：候选行不带任何选择或提交控件（不重新引入与澄清卡的重复）', async () => {
    const wrapper = await openRoutingDetail(GROUPED_SEED)
    const list = wrapper.find('[data-test="routing-candidate-list"]')
    expect(list.findAll('input[type="checkbox"]')).toHaveLength(0)
    // 唯一允许的 button 是「分数分解」披露开关
    const buttons = list.findAll('button')
    expect(buttons.every(b => b.attributes('data-test') === 'routing-breakdown-toggle')).toBe(true)
  })
})
