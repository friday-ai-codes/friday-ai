/**
 * ChatMessageBubble.vue parts 顺序渲染契约测试。
 *
 * 测试矩阵：
 * 1. renders_parts_in_order
 * 2. text_part_renders_markdown
 * 3. tool_use_part_renders_tool_pill_with_props
 * 4. thinking_part_renders_timeline_step--thinking
 * 5. deep_analysis_tool_use_part_renders_deep_analysis_panel
 * 6. unknown_part_type_renders_fallback_no_crash
 * + 反退化：长 markdown 不被 narration-block 包裹
 */

import type { ConversationMessage } from '~/types/chat'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import ChatMessageBubble from '~/components/chat/ChatMessageBubble.vue'
import OrchestrationStageTimeline from '~/components/chat/OrchestrationStageTimeline.vue'
import { useChatStore } from '~/stores/chat'
import legacyFixtures from './fixtures/legacy-messages.json'

vi.mock('~/composables/useMarkdownRenderer', () => ({
  getMarkdownRenderer: vi.fn(async () => ({
    render: (raw: string) => `<div data-test="md-rendered">${raw}</div>`,
  })),
}))

// stub Checkbox / DocSummaryCard / RoutingDecisionPanel / TechPlanCard 避免重依赖
vi.mock('~/components/ui/checkbox', () => ({
  Checkbox: defineComponent({ name: 'Checkbox', setup: () => () => h('input', { type: 'checkbox' }) }),
}))

vi.mock('~/components/chat/DocSummaryCard.vue', () => ({
  default: defineComponent({ name: 'DocSummaryCard', setup: () => () => h('div', { 'data-test': 'doc-summary' }) }),
}))

vi.mock('~/components/chat/RoutingDecisionPanel.vue', () => ({
  default: defineComponent({
    name: 'RoutingDecisionPanel',
    props: ['traceId', 'conversationId', 'messageId'],
    setup: () => () => h('div', { 'data-test': 'routing-panel' }),
  }),
}))

vi.mock('~/components/chat/TechPlanCard.vue', () => ({
  default: defineComponent({
    name: 'TechPlanCard',
    // 109-06：透出 codingPlanId / techPlan / affectedFiles 供三级优先的传参断言。
    // 109-REVIEW HI-02：加透 provenance —— 卡片内部的判定归 TechPlanCard.spec.ts，
    // 本文件只断言 bubble 到底把什么传下去了（漏传就是 RELY-01 误报的成因）。
    props: ['planId', 'codingPlanId', 'sessionId', 'techPlan', 'affectedFiles', 'provenance', 'status', 'isConfirming', 'branchName'],
    setup: props => () => h('div', {
      'data-test': 'tech-plan-card',
      'data-status': props.status,
      'data-coding-plan-id': props.codingPlanId ?? '',
      'data-tech-plan': props.techPlan ?? '',
      'data-affected-count': String(props.affectedFiles?.length ?? 0),
      'data-provenance': props.provenance ?? '',
      'data-provenance-passed': String(props.provenance !== undefined),
    }),
  }),
}))

// 109-04：stub 编排产出卡片 —— 本文件断言的是「渲染分支是否被走到」，
// 卡片自身的投影交互由 OrchestratedPlanCard.spec.ts 覆盖。
vi.mock('~/components/chat/OrchestratedPlanCard.vue', () => ({
  default: defineComponent({
    name: 'OrchestratedPlanCard',
    props: ['artifactVersionId'],
    setup: props => () => h('div', {
      'data-test': 'orchestrated-plan-card',
      'data-artifact-version-id': props.artifactVersionId,
    }),
  }),
}))

function makeMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: 'msg-test',
    role: 'assistant',
    content: '',
    created_at: '2026-05-21T00:00:00Z',
    ...overrides,
  }
}

async function mountBubble(message: ConversationMessage, props: Record<string, unknown> = {}) {
  const wrapper = mount(ChatMessageBubble, {
    props: { message, isStreaming: false, ...props },
    global: {
      stubs: { Transition: false },
    },
  })
  // 等待 md renderer onMounted resolve
  await new Promise<void>(r => setTimeout(r, 0))
  await new Promise<void>(r => setTimeout(r, 0))
  await wrapper.vm.$nextTick()
  return wrapper
}

describe('chatMessageBubble parts rendering ', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('1. renders parts in order (text → process-group → text)', async () => {
    const msg = makeMessage({
      content: '基于结果：found',
      parts: [
        { type: 'text', id: 'p1', index: 0, text: '先思考一下，', state: 'done' },
        {
          type: 'tool_use',
          id: 'p2',
          index: 1,
          tool_call_id: 'call_1',
          name: 'search_repository_code',
          input: { query: 'foo' },
          status: 'done',
          result: 'ok',
        },
        { type: 'text', id: 'p3', index: 2, text: '基于结果：found', state: 'done' },
      ],
    })
    const wrapper = await mountBubble(msg)
    const flow = wrapper.find('.timeline-flow')
    expect(flow.exists()).toBe(true)
    // 工具调用收拢进「分析过程」折叠面板（默认收起）
    expect(wrapper.find('.tpg').exists()).toBe(true)
    const html = flow.html()
    const textIdx1 = html.indexOf('先思考一下')
    // 收起态头部预览展示 toolAction（含「检索」）—— 用此作为过程面板锚点
    const procIdx = html.indexOf('检索')
    const textIdx2 = html.indexOf('基于结果')
    expect(textIdx1).toBeGreaterThan(-1)
    expect(procIdx).toBeGreaterThan(-1)
    expect(textIdx2).toBeGreaterThan(-1)
    expect(textIdx1).toBeLessThan(procIdx)
    expect(procIdx).toBeLessThan(textIdx2)
  })

  it('2. text part renders markdown (via stub renderer)', async () => {
    const msg = makeMessage({
      content: '# Title',
      parts: [{ type: 'text', id: 'p1', index: 0, text: '# Title', state: 'done' }],
    })
    const wrapper = await mountBubble(msg)
    const prose = wrapper.findAll('.ai-prose')
    expect(prose.length).toBeGreaterThanOrEqual(1)
    expect(prose[0].html()).toContain('md-rendered')
    expect(prose[0].html()).toContain('# Title')
  })

  it('3. tool_use part renders process-group row with proper label + status', async () => {
    const msg = makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'search_repository_code',
          input: { query: 'foo' },
          status: 'done',
          result: 'ok',
        },
      ],
    })
    const wrapper = await mountBubble(msg)
    // 收起态：折叠面板存在，状态为已完成
    expect(wrapper.find('.tpg').exists()).toBe(true)
    expect(wrapper.find('.tpg-dot--done').exists()).toBe(true)
    // 展开容器 → 步骤行显示中文标签
    await wrapper.find('.tpg-head').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.tpg-row-label').text()).toBe('RAG 代码检索')
  })

  it('4. thinking part renders timeline-step--thinking', async () => {
    const msg = makeMessage({
      parts: [
        { type: 'thinking', id: 'p1', index: 0, text: '用户想要分析跨仓代码', state: 'done' },
        { type: 'text', id: 'p2', index: 1, text: '正在分析', state: 'done' },
      ],
    })
    const wrapper = await mountBubble(msg)
    expect(wrapper.find('.timeline-step--thinking').exists()).toBe(true)
    expect(wrapper.html()).toContain('用户想要分析跨仓代码')
  })

  it('5. deep_analysis tool_use 渲染深度分析卡片（按会话日志）', async () => {
    const msg = makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'deep_analysis',
          input: { task_description: 'analyze' },
          status: 'done',
          result: 'long result',
        },
      ],
      metadata: {
        deep_analysis_logs: [
          { type: 'text', content: '[思考] 开始分析', ts: 1715000000000 },
          { type: 'result', content: 'cost=$0.001', ts: 1715000010000 },
        ],
      },
    })
    const wrapper = await mountBubble(msg)
    // 单个深度分析 → 直接渲染一张 DeepAnalysisCard（不进 swiper）
    expect(wrapper.find('.da-card').exists()).toBe(true)
    expect(wrapper.find('.dag').exists()).toBe(false)
    expect(wrapper.html()).toContain('开始分析')
  })

  it('5b. 多个 deep_analysis → 横向 swiper（DeepAnalysisGroup），各会话日志独立', async () => {
    const msg = makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'deep_analysis',
          input: { task_description: '分析 A' },
          status: 'done',
          result: '{"data":{"session_id":"deep-aaa111"}}',
        },
        {
          type: 'tool_use',
          id: 'p2',
          index: 1,
          tool_call_id: 'c2',
          name: 'deep_analysis',
          input: { task_description: '分析 B' },
          status: 'done',
          result: '{"data":{"session_id":"deep-bbb222"}}',
        },
      ],
      metadata: {
        deep_analysis_sessions: [
          { session_id: 'deep-aaa111', task_description: '分析 A', logs: [{ type: 'tool_call', content: 'Read({"file_path":"a.py"})', ts: 1 }] },
          { session_id: 'deep-bbb222', task_description: '分析 B', logs: [{ type: 'result', content: 'cost=$0.02', ts: 2 }] },
        ],
      },
    })
    const wrapper = await mountBubble(msg)
    expect(wrapper.find('.dag').exists()).toBe(true)
    expect(wrapper.findAll('.dag-tab').length).toBe(2)
    expect(wrapper.html()).toContain('2 个子任务')
  })

  it('5c. list_space_repositories 工具显示中文名（不漏英文）', async () => {
    const msg = makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'mcp__chat-tools__list_space_repositories',
          input: {},
          status: 'done',
          result: 'ok',
        },
      ],
    })
    const wrapper = await mountBubble(msg)
    await wrapper.find('.tpg-head').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.tpg-row-label').text()).toBe('仓库列表')
    expect(wrapper.html()).not.toContain('list_space_repositories')
  })

  it('5d. analyze_repository_relevance 显示中文名 + 查询副标题', async () => {
    const msg = makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'mcp__chat-tools__analyze_repository_relevance',
          input: { query: 'entrance', top_k: 10 },
          status: 'done',
          result: 'ok',
        },
      ],
    })
    const wrapper = await mountBubble(msg)
    // 收起态头部预览即包含查询关键字 entrance
    expect(wrapper.html()).toContain('entrance')
    await wrapper.find('.tpg-head').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.tpg-row-label').text()).toBe('仓库分级路由')
    expect(wrapper.html()).not.toContain('analyze_repository_relevance')
  })

  it('5e. 搜索/相关性分析显示仓库名称而非裸 UUID（诉求 2/3）', async () => {
    const relevanceResult = JSON.stringify({
      data: {
        candidates: [
          { repository_id: 'repo-uuid-1', repository_name: 'example-app', score: 0.82, level: 'high', evidence: '命中 2 个文件' },
          { repository_id: 'repo-uuid-2', repository_name: 'question-bank', score: 0.55, level: 'medium', evidence: '语义相关' },
        ],
      },
    })
    const msg = makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'mcp__chat-tools__analyze_repository_relevance',
          input: { query: 'entrance' },
          status: 'done',
          result: relevanceResult,
        },
        {
          type: 'tool_use',
          id: 'p2',
          index: 1,
          tool_call_id: 'c2',
          name: 'search_repository_code',
          input: { query: 'entrance', repository_id: 'repo-uuid-1' },
          status: 'done',
          result: 'ok',
        },
      ],
    })
    const wrapper = await mountBubble(msg)
    await wrapper.find('.tpg-head').trigger('click')
    await wrapper.vm.$nextTick()
    const rows = wrapper.findAll('.tpg-row')
    expect(rows.length).toBe(2)
    // 相关性分析行：摘要里出现关联到的仓库名称
    expect(rows[0].text()).toContain('example-app')
    // 搜索行：把 repository_id 映射成仓库名称
    expect(rows[1].text()).toContain('example-app')
    // 展开相关性行 → 候选仓库名称 + 等级
    await rows[0].find('.tpg-row-head').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.html()).toContain('question-bank')
    expect(wrapper.html()).not.toContain('repo-uuid-1')
  })

  it('5f. 渲染「引用仓库」编号图例，点击触发过程面板展开（结论↔证据闭环）', async () => {
    const relevanceResult = JSON.stringify({
      data: {
        candidates: [
          { repository_id: 'repo-uuid-1', repository_name: 'example-app', score: 0.82, level: 'high', evidence: 'e1' },
          { repository_id: 'repo-uuid-2', repository_name: 'question-bank', score: 0.55, level: 'medium', evidence: 'e2' },
        ],
      },
    })
    const msg = makeMessage({
      content: '基于检索结果给出结论',
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'mcp__chat-tools__analyze_repository_relevance',
          input: { query: 'entrance' },
          status: 'done',
          result: relevanceResult,
        },
        { type: 'text', id: 'p2', index: 1, text: '基于检索结果给出结论', state: 'done' },
      ],
    })
    const wrapper = await mountBubble(msg)
    const legend = wrapper.find('.repo-legend')
    expect(legend.exists()).toBe(true)
    const items = wrapper.findAll('.repo-legend-item')
    expect(items.length).toBe(2)
    expect(items[0].text()).toContain('example-app')
    expect(items[0].text()).toContain('1')
    // 点击图例项 → 过程面板被展开（验证联动不抛错且容器存在）
    await items[1].trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-process-group]').exists()).toBe(true)
  })

  it('6. unknown part type 渲染 fallback 不 crash（forward-compat）', async () => {
    const msg = makeMessage({
      parts: [
        // @ts-expect-error 故意构造未知 type 模拟 v27 新增 part type 旧客户端遇到
        { type: 'image', id: 'p1', index: 0, src: 'data:image/png;base64,xxx' },
        { type: 'text', id: 'p2', index: 1, text: '正常文本', state: 'done' },
      ],
    })
    const wrapper = await mountBubble(msg)
    expect(wrapper.find('.unknown-part').exists()).toBe(true)
    expect(wrapper.text()).toContain('[未知 part: image]')
    expect(wrapper.text()).toContain('正常文本')
  })

  it('7. F5 反退化 —— 长 markdown 答复直接渲染为顶层 ai-prose，不被 narration-block 包裹', async () => {
    // F5 fixture：deep_analysis 长 markdown + 单 tool_call
    const f5 = legacyFixtures.F5 as unknown as ConversationMessage
    const wrapper = await mountBubble(f5)
    const html = wrapper.html()

    // 关键不变量 1：narration-block / narration-toggle / narration-count
    // CSS class 必须不存在于渲染输出（ 要求删除）
    expect(html).not.toContain('class="narration-block"')
    expect(html).not.toContain('narration-toggle')
    expect(html).not.toContain('narration-count')
    expect(html).not.toContain('timeline-step--narration')

    // 关键不变量 2：长 markdown 标题 / 代码块 / 表格关键标记直接出现在 ai-prose 中
    const prose = wrapper.findAll('.ai-prose')
    const proseTexts = prose.map(p => p.html()).join('\n')
    expect(proseTexts).toContain('# entrance 字段处理逻辑分析')
    expect(proseTexts).toContain('apps/study/views.py')
    expect(proseTexts).toContain('| 字段 | 含义 | 默认值 |')

    // 关键不变量 3：narration 字符串以独立 ai-prose text part 呈现
    // （顶层 markdown 块，不嵌套在「分析」折叠容器内）
    expect(proseTexts).toContain('让我深入分析两个仓库中 entrance 字段的处理逻辑...')

    // 关键不变量 4：deep_analysis tool_use part 仍能渲染深度分析卡片
    expect(wrapper.find('.da-card').exists()).toBe(true)
  })
})

/**
 * 109-04：编排产出「进入编码」入口的渲染分支（SPINE-01）。
 *
 * 两个编排工具走同一判定、同一张卡片；三条渲染条件必须同时成立。
 */
describe('chatMessageBubble 编排产出卡片渲染分支', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const DONE_RESULT = {
    session_id: 'sess-1',
    artifact_version_id: 'av-uuid-1',
    status: 'done',
    message: '跨仓方案编排已完成，已产出技术方案产物（ArtifactVersion）。',
  }

  function orchestrationMessage(
    name: string,
    result: unknown,
    status: 'running' | 'done' = 'done',
  ): ConversationMessage {
    return makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name,
          input: { requirement: '打通编排产出到编码执行' },
          status,
          result: result as string | undefined,
        },
      ],
    })
  }

  it.each([
    'start_plan_research',
    'start_feature_solution',
    'mcp__chat-tools__start_plan_research',
    'mcp__chat-tools__start_feature_solution',
  ])('%s 终态渲染 OrchestratedPlanCard，并把 artifact_version_id 交给卡片', async (name) => {
    const wrapper = await mountBubble(
      orchestrationMessage(name, JSON.stringify(DONE_RESULT)),
    )
    const card = wrapper.find('[data-test="orchestrated-plan-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-artifact-version-id')).toBe('av-uuid-1')
  })

  it.each(['start_plan_research', 'start_feature_solution'])(
    // 🔴 静默失守点：若把该工具从 UNGROUPABLE_TOOLS 中移除，它会被 isProcessTool
    // 归入「分析过程」折叠面板（.tpg）。那条路径不渲染专属卡片 —— 不报错、不崩、
    // 只是「进入编码」入口彻底不见。本断言就是这个失守点的护栏：
    // .tpg 出现 / 卡片消失都说明集合被漏改。
    '%s 在 UNGROUPABLE_TOOLS 内：走单例 tool 分支而非「分析过程」折叠面板',
    async (name) => {
      const wrapper = await mountBubble(
        orchestrationMessage(name, JSON.stringify(DONE_RESULT)),
      )
      expect(wrapper.find('.tool-inline').exists()).toBe(true)
      expect(wrapper.find('.tpg').exists()).toBe(false)
      expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(true)
    },
  )

  it('异步路径：同一消息两条同名编排工具时，卡片挂在带 artifact_version_id 的那条上', async () => {
    // 跨仓调研的常态路径：waiting → executing 二次运行 SDK，于是同一条消息里
    // 累积两条 start_plan_research —— 第一条 result 是 __blocking_task__（无
    // artifact_version_id），第二条才是终态。若解析改回「在 toolCalls 里 find
    // 第一条」，取到的恒是阻塞态 ⇒ 卡片一张都不渲染，SPINE-01 的「进入编码」
    // 入口在正常路径上彻底消失（不报错、不崩，只是没有入口）。
    const wrapper = await mountBubble(makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'start_plan_research',
          input: { requirement: '打通编排产出到编码执行' },
          status: 'done',
          result: JSON.stringify({
            __blocking_task__: true,
            task_type: 'plan_research',
            task_id: 'sess-1',
            session_id: 'sess-1',
          }),
        },
        {
          type: 'tool_use',
          id: 'p2',
          index: 1,
          tool_call_id: 'c2',
          name: 'start_plan_research',
          input: { session_id: 'sess-1' },
          status: 'done',
          result: JSON.stringify(DONE_RESULT),
        },
      ],
    }))

    const cards = wrapper.findAll('[data-test="orchestrated-plan-card"]')
    // 恰好一张：阻塞态那条不渲染，终态那条渲染
    expect(cards).toHaveLength(1)
    expect(cards[0].attributes('data-artifact-version-id')).toBe('av-uuid-1')
  })

  it('result 为 dict 形态（历史 chat_runner 路径）同样解析出 artifact_version_id', async () => {
    const wrapper = await mountBubble(
      orchestrationMessage('start_plan_research', DONE_RESULT),
    )
    const card = wrapper.find('[data-test="orchestrated-plan-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-artifact-version-id')).toBe('av-uuid-1')
  })

  it('item.status !== done → 不渲染卡片', async () => {
    const wrapper = await mountBubble(
      orchestrationMessage('start_plan_research', JSON.stringify(DONE_RESULT), 'running'),
    )
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(false)
  })

  it('result 内 status !== done → 不渲染卡片', async () => {
    const wrapper = await mountBubble(
      orchestrationMessage(
        'start_plan_research',
        JSON.stringify({ ...DONE_RESULT, status: 'waiting_event' }),
      ),
    )
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(false)
  })

  it.each([
    ['artifact_version_id 为 null', { ...DONE_RESULT, artifact_version_id: null }],
    ['artifact_version_id 缺失', { session_id: 'sess-1', status: 'done' }],
    ['artifact_version_id 为空串', { ...DONE_RESULT, artifact_version_id: '' }],
  ])('%s → 不渲染卡片、不抛错', async (_label, result) => {
    const wrapper = await mountBubble(
      orchestrationMessage('start_plan_research', JSON.stringify(result)),
    )
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(false)
    expect(wrapper.find('.tool-inline').exists()).toBe(true)
  })

  it('编排在途（__blocking_task__ 形态，无 artifact_version_id）→ 零卡片、零进度 UI、不抛错', async () => {
    const blocking = JSON.stringify({
      __blocking_task__: true,
      task_type: 'plan_research',
      task_id: 'sess-1',
      session_id: 'sess-1',
      params: { session_id: 'sess-1' },
      placeholder: '已发起跨仓方案编排调研（session=sess-1，状态=waiting_event）；深入调研容器运行中。',
    })
    const wrapper = await mountBubble(orchestrationMessage('start_plan_research', blocking))
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(false)
    // 在途摘要取前端常量，后端 placeholder 原文不上屏
    expect(wrapper.text()).toContain('方案编排调研进行中')
    expect(wrapper.html()).not.toContain('容器运行中')
  })

  it('result 解析失败（非 JSON）→ 不渲染卡片、不抛错', async () => {
    const wrapper = await mountBubble(
      orchestrationMessage('start_plan_research', 'not-a-json'),
    )
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(false)
    expect(wrapper.find('.tool-inline').exists()).toBe(true)
  })

  it('展开详情不把编排工具的原始 input/output 经 StructuredJsonView 上屏', async () => {
    const wrapper = await mountBubble(
      orchestrationMessage('start_plan_research', JSON.stringify(DONE_RESULT)),
    )
    await wrapper.find('.tool-pill').trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.tool-detail').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('ArtifactVersion')
  })
})

/**
 * 109-06：codingPlanData 的 tool input 取值降级为**历史消息兜底**（SPINE-02 连带）。
 *
 * SPINE-02 已把 tech_plan / affected_files 从 create/update_coding_plan 的 schema
 * 里删掉，新消息的 input 无此两键。本组用例锁两件事：
 *   1. 新消息形态下卡片仍渲染、codingPlanId 仍正确传下（正文为空不致崩）；
 *   2. 历史消息形态下 input 里的正文仍能经 props 传下（这一级不可删）。
 */
describe('chatMessageBubble — 109-06 coding plan 正文数据源', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function codingPlanMessage(
    input: Record<string, unknown>,
    result: unknown,
  ): ConversationMessage {
    return makeMessage({
      parts: [
        {
          type: 'tool_use',
          id: 'p1',
          index: 0,
          tool_call_id: 'c1',
          name: 'create_coding_plan',
          input,
          status: 'done',
          result: result as string | undefined,
        },
      ],
    })
  }

  const PLAN_RESULT = {
    coding_plan_id: 'plan-uuid-1',
    status: 'plan_only',
  }

  it('新消息形态（input 不含 tech_plan / affected_files）→ 卡片仍渲染且 codingPlanId 正确传下', async () => {
    const wrapper = await mountBubble(
      codingPlanMessage(
        { space_id: 's1', conversation_id: 'c1', artifact_version_id: 'av-1' },
        JSON.stringify(PLAN_RESULT),
      ),
    )
    const card = wrapper.find('[data-test="tech-plan-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-coding-plan-id')).toBe('plan-uuid-1')
    // 正文为空是预期（新消息的正文由 runtime / 投影响应承载），卡片不因此崩
    expect(card.attributes('data-tech-plan')).toBe('')
    expect(card.attributes('data-affected-count')).toBe('0')
  })

  it('历史消息形态（input 含 tech_plan / affected_files）→ 正文与影响文件经 props 传下', async () => {
    const wrapper = await mountBubble(
      codingPlanMessage(
        {
          tech_plan: '# 历史方案正文',
          affected_files: [{ file_path: 'legacy.py', change_type: 'modify' }],
        },
        JSON.stringify(PLAN_RESULT),
      ),
    )
    const card = wrapper.find('[data-test="tech-plan-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-tech-plan')).toBe('# 历史方案正文')
    expect(card.attributes('data-affected-count')).toBe('1')
  })

  /**
   * 🔴 109-REVIEW HI-02：正文与来源标志改由 **tool result** 承载。
   *
   * 修复前这两者对「非最新那一份 plan」的卡片同时取不到 —— input 里没有（SPINE-02
   * 收窄），runtime 只指向「对话内最近一条 CodingPlan」。用户滚回去看第一份方案，
   * 正文没了，还多了一条「本方案未经代码调研」——而它明明是编排产出的。这是最普通
   * 的两方案会话，不是边缘场景。
   */
  const PLAN_RESULT_WITH_BODY = {
    coding_plan_id: 'plan-uuid-1',
    status: 'plan_only',
    tech_plan: '# 编排产出的方案正文',
    affected_files: [
      { file_path: 'server/a.py', change_type: 'add' },
      { file_path: 'server/b.py', change_type: 'modify' },
    ],
    provenance: 'orchestrated',
  }

  it('工具结果携带正文 / 影响文件 / provenance → 三者都经 props 传下（不依赖 runtime）', async () => {
    const wrapper = await mountBubble(
      codingPlanMessage(
        { space_id: 's1', conversation_id: 'c1', artifact_version_id: 'av-1' },
        JSON.stringify(PLAN_RESULT_WITH_BODY),
      ),
    )
    const card = wrapper.find('[data-test="tech-plan-card"]')
    expect(card.attributes('data-tech-plan')).toBe('# 编排产出的方案正文')
    expect(card.attributes('data-affected-count')).toBe('2')
    // 漏传 provenance 会让编排产出落进保守分支、被误挂草稿横幅（RELY-01 误报）
    expect(card.attributes('data-provenance')).toBe('orchestrated')
  })

  it('工具结果为 dict（非 JSON string）时同样解析出正文与 provenance', async () => {
    const wrapper = await mountBubble(
      codingPlanMessage({ artifact_version_id: 'av-1' }, PLAN_RESULT_WITH_BODY),
    )
    const card = wrapper.find('[data-test="tech-plan-card"]')
    expect(card.attributes('data-tech-plan')).toBe('# 编排产出的方案正文')
    expect(card.attributes('data-provenance')).toBe('orchestrated')
  })

  it('结果里缺 provenance → 原样传 undefined，不在此处补默认值（保守分支归卡片判定）', async () => {
    const wrapper = await mountBubble(
      codingPlanMessage({ artifact_version_id: 'av-1' }, JSON.stringify(PLAN_RESULT)),
    )
    const card = wrapper.find('[data-test="tech-plan-card"]')
    expect(card.attributes('data-provenance-passed')).toBe('false')
  })

  it('工具结果有正文时优先于 tool input（新旧两种来源并存的历史消息）', async () => {
    const wrapper = await mountBubble(
      codingPlanMessage(
        { tech_plan: '# 旧 input 正文' },
        JSON.stringify(PLAN_RESULT_WITH_BODY),
      ),
    )
    expect(
      wrapper.find('[data-test="tech-plan-card"]').attributes('data-tech-plan'),
    ).toBe('# 编排产出的方案正文')
  })
})

/**
 * 110-07：编排在途 UI（阶段时间线 + 调研容器日志组）在气泡上的挂载契约。
 *
 * 本组不 stub 两个新组件——「时间线绑到哪个会话」「日志组挂在哪条气泡上」这两件事
 * 只有在真实组件树上才读得出来。
 */
describe('chatMessageBubble — 110-07 编排进度挂载', () => {
  const TIMELINE = '[data-test="orchestration-stage-timeline"]'
  const LOG_GROUP = '[data-test="plan-research-log-group"]'

  let store: ReturnType<typeof useChatStore>

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useChatStore()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  /** 让某个会话在 store 里「至少有一条已知事实」，时间线的组件侧门才会放行。 */
  function seedBucket(sessionId: string, overrides: Record<string, unknown> = {}) {
    store.orchestrationSessions[sessionId] = {
      sessionId,
      snapshot: {
        session_id: sessionId,
        status: 'running',
        current_stage: 'research',
        has_classify: false,
        segment_count: 3,
        failure: null,
        events: [],
        events_truncated: false,
        ...overrides,
      },
      events: [],
      eventsTruncated: false,
    }
  }

  function seedResearchSessions(planSessionId: string, repos: Array<[string, string]>) {
    store.planResearchSessions = repos.map(([id, name], i) => ({
      session_id: `sub-${planSessionId}-${i}`,
      plan_session_id: planSessionId,
      repository_id: id,
      repository_name: name,
      status: 'RUNNING',
      logs: [{ type: 'text', content: `${name} 调研中`, ts: i + 1 }],
    }))
  }

  const BLOCKING = (sessionId: string) => JSON.stringify({
    __blocking_task__: true,
    task_type: 'plan_research',
    task_id: sessionId,
    session_id: sessionId,
  })

  const TERMINAL = (sessionId: string, artifactVersionId = 'av-uuid-1') => JSON.stringify({
    session_id: sessionId,
    artifact_version_id: artifactVersionId,
    status: 'done',
  })

  function toolPart(id: string, index: number, result: unknown, status: 'running' | 'done' = 'done') {
    return {
      type: 'tool_use' as const,
      id,
      index,
      tool_call_id: `c${index}`,
      name: 'start_plan_research',
      input: { requirement: '打通编排产出到编码执行' },
      status,
      result: result as string | undefined,
    }
  }

  function orchestrationMsg(parts: ReturnType<typeof toolPart>[], id = 'msg-test') {
    return makeMessage({ id, parts })
  }

  // ---- 挂载与单次渲染 -----------------------------------------------------

  it('在途编排 tool item + store 有桶 ⇒ 渲染时间线，且不渲染编排产出卡片', async () => {
    seedBucket('S1')
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, BLOCKING('S1'))]))
    expect(wrapper.find(TIMELINE).exists()).toBe(true)
    // 在途无 artifact_version_id ⇒ 裁决 D-4「在途完全不呈现」
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(false)
  })

  it('同一消息两条同名编排 tool call ⇒ 时间线恰渲染一次，且挂在末条上', async () => {
    seedBucket('S1')
    const wrapper = await mountBubble(orchestrationMsg([
      toolPart('p1', 0, BLOCKING('S1')),
      toolPart('p2', 1, TERMINAL('S1')),
    ]))
    // 🔴 去掉 item.id === lastOrchestrationToolItemId 这个条件，这里会变成 2
    expect(wrapper.findAll(TIMELINE)).toHaveLength(1)

    const bubbles = wrapper.findAll('.tool-inline')
    expect(bubbles).toHaveLength(2)
    expect(bubbles[0].find(TIMELINE).exists()).toBe(false)
    expect(bubbles[1].find(TIMELINE).exists()).toBe(true)
  })

  it('per-item 解析回归锁：末条编排 item 在途时，产出卡片仍挂在前面那条终态上', async () => {
    // 🔴 这条锁的是 plan Task 2 的 🔴 边界：`lastOrchestrationToolItemId` 只准用于
    // 去重渲染位置，**不准**顺手接进 `OrchestratedPlanCard` 的渲染条件。
    // 若接了进去，卡片会因为「它不是末条」而消失——和 109 修掉的 `.find` 缺口
    // 是同一种后果（不报错、不崩，只是「进入编码」入口没了）。
    seedBucket('S1')
    const wrapper = await mountBubble(orchestrationMsg([
      toolPart('p1', 0, TERMINAL('S1')),
      toolPart('p2', 1, BLOCKING('S1')),
    ]))
    const cards = wrapper.findAll('[data-test="orchestrated-plan-card"]')
    expect(cards).toHaveLength(1)
    expect(cards[0].attributes('data-artifact-version-id')).toBe('av-uuid-1')
    // 时间线仍只挂在末条上
    expect(wrapper.findAll(TIMELINE)).toHaveLength(1)
  })

  // ---- 会话绑定（§A.7）----------------------------------------------------

  it('result 里的 session_id 优先于 store 的 activeOrchestrationSessionId', async () => {
    seedBucket('S1')
    seedBucket('S2')
    store.activeOrchestrationSessionId = 'S2'
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, BLOCKING('S1'))]))
    // 两个桶都在 ⇒ 绑错会话时时间线照样渲染，只有 prop 断言分得出对错
    expect(wrapper.findComponent(OrchestrationStageTimeline).props('sessionId')).toBe('S1')
  })

  it('result 取不到 session_id（在途早期）⇒ 回退 store 的活跃会话', async () => {
    seedBucket('S2')
    store.activeOrchestrationSessionId = 'S2'
    const wrapper = await mountBubble(
      orchestrationMsg([toolPart('p1', 0, undefined, 'running')]),
    )
    expect(wrapper.findComponent(OrchestrationStageTimeline).props('sessionId')).toBe('S2')
  })

  it('两级来源都取不到会话 ⇒ 时间线不渲染、不抛错', async () => {
    seedBucket('S2')
    store.activeOrchestrationSessionId = null
    const wrapper = await mountBubble(
      orchestrationMsg([toolPart('p1', 0, JSON.stringify({ status: 'waiting_event' }), 'running')]),
    )
    expect(wrapper.find(TIMELINE).exists()).toBe(false)
    expect(wrapper.find('.tool-inline').exists()).toBe(true)
    expect(console.warn).not.toHaveBeenCalled()
    expect(console.error).not.toHaveBeenCalled()
  })

  // ---- 110-HI-01：失败后重跑，失败那条气泡不得改播新一轮 --------------------
  //
  // 上面三条绑定用例只覆盖「在途、根本没有 result」这一种取不到会话的形态——那正是
  // 兜底**应该**生效的一种。真正会出事的是「**终态**、result 可解析但缺 session_id」，
  // 也就是失败路径 `{"error":…,"is_error":true}` 的形状。下面三条把它锁住。

  /** 编排失败的 tool result 出网形状（`chat_runner._normalize_tool_result` 固化）。 */
  const FAILED = (sessionId?: string) => JSON.stringify({
    error: '上游 500：<html>boom</html>',
    is_error: true,
    ...(sessionId ? { session_id: sessionId } : {}),
  })

  /** 第一轮失败（S1） + 第二轮在途（S2，store 的活跃会话指向它）。 */
  function seedFailedThenRerun() {
    seedBucket('S1', {
      status: 'failed',
      current_stage: 'merge',
      failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
    })
    seedBucket('S2', { status: 'running', current_stage: 'route' })
    store.activeOrchestrationSessionId = 'S2'
  }

  it('失败终态 result 带 session_id ⇒ 绑回它自己那一轮（S1），不跟随 store 的活跃会话', async () => {
    seedFailedThenRerun()
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, FAILED('S1'))]))

    expect(wrapper.findComponent(OrchestrationStageTimeline).props('sessionId')).toBe('S1')
  })

  it('失败气泡显示「方案编排失败」，且全文不含新一轮的「正在生成技术方案」', async () => {
    // 🔴 与上一条分开写、且**两个方向都断言**：只断言标题为「失败」的话，
    // 「绑到 S2」的实现在这条上同样会红，但看不出它把别人的进度挂了上来；
    // 只断言不含在途文案的话，「整块不渲染」的实现会假通过。
    seedFailedThenRerun()
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, FAILED('S1'))]))

    expect(wrapper.text()).toContain('方案编排失败')
    expect(wrapper.text()).not.toContain('正在生成技术方案')
  })

  it('终态 result 可解析但缺 session_id（老后端形状）⇒ 整块不渲染，绝不回退到 store 的活跃会话', async () => {
    // 兜底只服务「在途还没有 result」。这条形状有 result、只是绑不到会话 ⇒ §A.5 条件 2
    // 不成立，整块不渲染；回退到 S2 会让失败气泡播新一轮的实时进度。
    seedFailedThenRerun()
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, FAILED())]))

    expect(wrapper.find(TIMELINE).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('正在生成技术方案')
    expect(wrapper.find('.tool-inline').exists()).toBe(true)
  })

  // ---- 调研日志组 ---------------------------------------------------------

  it('调研容器归属本气泡的会话 ⇒ 渲染日志组，且位置早于编排产出卡片', async () => {
    seedBucket('S1')
    seedResearchSessions('S1', [['repo-1', 'example-app'], ['repo-2', 'question-bank']])
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, TERMINAL('S1'))]))

    expect(wrapper.find(LOG_GROUP).exists()).toBe(true)
    expect(wrapper.text()).toContain('方案调研 · 2 个仓库')
    expect(wrapper.text()).toContain('example-app')

    const html = wrapper.html()
    const groupIdx = html.indexOf('plan-research-log-group')
    const cardIdx = html.indexOf('orchestrated-plan-card')
    expect(groupIdx).toBeGreaterThan(-1)
    expect(cardIdx).toBeGreaterThan(-1)
    expect(groupIdx).toBeLessThan(cardIdx)
  })

  it('store 里没有调研容器 ⇒ 日志组不渲染', async () => {
    seedBucket('S1')
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, TERMINAL('S1'))]))
    expect(wrapper.find(LOG_GROUP).exists()).toBe(false)
  })

  it('planResearchSessions 是会话级扁平数组、被快照整体替换 —— 没有 plan_session_id 过滤就会把第二轮的日志挂到第一条编排消息上', async () => {
    // 🔴 本组最重要的一条（F-21）。真实形态由两条事实叠加而成：
    //   ① 后端只装本对话**最近一次** ConvergenceSession 的容器；
    //   ② 前端每份 runtime 快照**整体替换** planResearchSessions。
    // ⇒ 一段对话跑两轮编排时，数组里装的全是第二轮（S2）的容器。
    seedBucket('S1')
    seedBucket('S2')
    store.activeOrchestrationSessionId = 'S2'
    seedResearchSessions('S2', [['repo-9', 'second-round-repo']])

    const firstRound = await mountBubble(
      orchestrationMsg([toolPart('p1', 0, TERMINAL('S1'))], 'msg-round-1'),
    )
    const secondRound = await mountBubble(
      orchestrationMsg([toolPart('p1', 0, TERMINAL('S2'))], 'msg-round-2'),
    )

    // 第二轮那条：日志组在
    expect(secondRound.findAll(LOG_GROUP)).toHaveLength(1)
    expect(secondRound.text()).toContain('second-round-repo')

    // 🔴 第一轮那条：日志组**不在**。两侧断言缺一不可 ——
    // 只断言上面那条的话，「完全不过滤」的实现同样为真。
    expect(firstRound.findAll(LOG_GROUP)).toHaveLength(0)
    expect(firstRound.text()).not.toContain('方案调研')
    expect(firstRound.text()).not.toContain('second-round-repo')
  })

  it('过滤后为空 ⇒ 整组不渲染，不出现一个空的组标题', async () => {
    seedBucket('S1')
    seedResearchSessions('S-other', [['repo-1', 'example-app']])
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, TERMINAL('S1'))]))
    expect(wrapper.find(LOG_GROUP).exists()).toBe(false)
    expect(wrapper.text()).not.toContain('方案调研')
    expect(wrapper.text()).not.toContain('0 个仓库')
  })

  // ---- 历史与边界（零回归）-----------------------------------------------

  it('非编排工具的单例 tool item ⇒ 两块都不渲染', async () => {
    seedBucket('S1')
    store.activeOrchestrationSessionId = 'S1'
    seedResearchSessions('S1', [['repo-1', 'example-app']])
    const wrapper = await mountBubble(makeMessage({
      parts: [{
        type: 'tool_use',
        id: 'p1',
        index: 0,
        tool_call_id: 'c1',
        name: 'create_coding_plan',
        input: { artifact_version_id: 'av-1' },
        status: 'done',
        result: JSON.stringify({ coding_plan_id: 'plan-1', status: 'plan_only' }),
      }],
    }))
    expect(wrapper.find('.tool-inline').exists()).toBe(true)
    expect(wrapper.find(TIMELINE).exists()).toBe(false)
    expect(wrapper.find(LOG_GROUP).exists()).toBe(false)
  })

  it('老会话 / 老后端（store 无桶、无调研容器）⇒ 两块都不渲染且零 console 输出', async () => {
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, TERMINAL('S1'))]))
    expect(wrapper.find(TIMELINE).exists()).toBe(false)
    expect(wrapper.find(LOG_GROUP).exists()).toBe(false)
    // 其余渲染与今日一致：pill 与产出卡片照常
    expect(wrapper.find('.tool-pill').exists()).toBe(true)
    expect(wrapper.find('[data-test="orchestrated-plan-card"]').exists()).toBe(true)
    expect(console.warn).not.toHaveBeenCalled()
    expect(console.error).not.toHaveBeenCalled()
  })

  it('107 边界：编排气泡上不出现路由决策面板与降级解释句', async () => {
    seedBucket('S1')
    seedResearchSessions('S1', [['repo-1', 'example-app']])
    const wrapper = await mountBubble(orchestrationMsg([toolPart('p1', 0, BLOCKING('S1'))]))
    expect(wrapper.find('[data-test="routing-panel"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('未经 LLM 推理')
    expect(wrapper.text()).not.toContain('置信度')
  })
})
