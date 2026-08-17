/**
 * 横向节点进度 stepper 的组件测试（quick-260806 节点重跑，接替原 stageTimeline / activityPanel 两份 spec）。
 *
 * 守八件事：
 *  1. ⭐ 八个节点全部出现且顺序 = `BLUEPRINT_STAGES`；`data-state` 与 `buildStageTimeline`
 *     逐节点相同（MN-01 同源纪律的继承：组件不得存在第二份状态推断）。
 *  2. 运行中节点有动效（脉冲/旋转），失败节点有明显标识。
 *  3. 点击节点展开详情：摘要事实、该节点的事件明细、stage_state 分片。
 *  4. 上一步/下一步在节点间切换（单选）。
 *  5. ⭐ 重跑表单只在「有会话 + 该节点在 rerunnable_stages（后端 key）」时渲染；
 *     UI 节点 `confirmation` 提交时映射成后端 `repo_confirmation`。
 *  6. 无会话（`session_id === ''`）⇒ 全部节点无重跑表单（版本谱系照常有效由页面层承担）。
 *  7. 该节点的重跑历史（时间 + 指令）渲染。
 *  8. 等澄清 ⇒ 运行中节点换成醒目问号标识。
 */

import type { BlueprintEvent, BlueprintStagesResponse } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintStageStepper from '~/components/blueprint/BlueprintStageStepper.vue'
import { BLUEPRINT_STAGES, buildStageTimeline } from '~/utils/blueprintBlocks'

const NODE = '[data-testid="blueprint-stepper-node"]'
const DETAIL = '[data-testid="blueprint-stepper-detail"]'
const RERUN_FORM = '[data-testid="blueprint-stepper-rerun-form"]'
const RERUN_INPUT = '[data-testid="blueprint-stepper-rerun-input"]'
const RERUN_SUBMIT = '[data-testid="blueprint-stepper-rerun-submit"]'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          stepper: {
            title: '编排进度',
            runLabel: '轮次 {label}',
            nodeAria: '查看「{label}」节点详情',
            duration: '耗时 {d}',
            stateTitle: '节点状态数据',
            eventsEmpty: '该节点暂无事件',
            prev: '上一步',
            next: '下一步',
          },
          rerun: {
            title: '带指令重跑',
            placeholder: '补充一段话，让 AI 带着它重跑这个环节…',
            submit: '重跑该环节',
            historyTitle: '重跑历史',
          },
          activity: {
            step: '第 {n} 步',
            eventCount: '{n} 条事件',
            eventsTitle: '过程明细',
            groupCount: '共 {n} 项',
            groupTruncated: '余下项已折叠',
            rawToggle: '原始数据',
            yes: '是',
            no: '否',
            pinnedRoute: '固定路由：候选仓来自项目手动绑定',
            confidenceHigh: '高',
            confidenceMedium: '中',
            confidenceLow: '低',
            fact: { candidateCount: '候选仓', researchProgress: '调研进度' },
            payload: {
              candidate_count: '候选数',
              repository_name: '仓库',
              research_reason: '调研理由',
              routed_confidence: '路由置信度',
              fitness_verdict: '适配结论',
              attempt: '尝试次数',
              repository_id: '仓库 id',
              task_id: '任务 id',
            },
          },
          progress: {
            repoResearchStarted: '正在调研 {repository_name}…',
            repoResearchStartedGeneric: '正在调研相关仓库…',
            repoResearchCompleted: '{repository_name} 调研完成（适配：{fitness_verdict}）',
            repoResearchCompletedGeneric: '仓库调研完成',
            repoResearchFailed: '{repository_name} 调研未成功（第 {attempt} 次）',
            repoResearchFailedGeneric: '仓库调研未成功',
          },
          repo: {
            fitnessSuitable: '适配',
            fitnessPartial: '部分适配',
            fitnessUnsuitable: '不适配',
          },
          stage: {
            summaryCurrent: '当前阶段：{label}',
            summaryDone: '编排已完成',
            summaryFailed: '{label}未成功',
            spec_gate: '需求规格门',
            route: '仓库路由',
            repo_research: '仓库调研',
            confirmation: '仓库集确认门',
            repo_plan: '各仓方案',
            merge: '方案合并',
            ai_review: 'AI 审查',
            pending_review: '待人类审查',
            stateIdle: '未开始',
            stateRunning: '进行中',
            stateDone: '已完成',
            stateFailed: '未成功',
          },
        },
      },
    },
  },
})

let seq = 0

function event(name: string, payload: Record<string, unknown> = {}, ts = '2026-08-05T01:00:00+00:00'): BlueprintEvent {
  seq += 1
  return { id: `e-${seq}`, event: name, payload, ts }
}

function makeStages(overrides: Partial<BlueprintStagesResponse> = {}): BlueprintStagesResponse {
  return {
    session_id: 's-1',
    current_stage: 'route',
    session_status: 'running',
    run_label: '1',
    stage_rerun: null,
    stage_rerun_history: [],
    rerunnable_stages: ['ai_review', 'decompose', 'merge', 'repo_confirmation', 'repo_plan', 'repo_research', 'route', 'spec_gate'],
    stages: [
      { key: 'route', state: { routing: { candidate_count: 2, candidates: [{ repository_id: 'r1' }] } } },
      { key: 'repo_confirmation', state: {} },
    ],
    versions: [],
    ...overrides,
  }
}

function mountStepper(options: {
  events?: BlueprintEvent[]
  currentStage?: string
  currentStatus?: string
  stages?: BlueprintStagesResponse | null
  submitting?: boolean
} = {}) {
  return mount(BlueprintStageStepper, {
    props: {
      events: options.events ?? [],
      currentStage: options.currentStage ?? '',
      currentStatus: options.currentStatus ?? '',
      stages: options.stages === undefined ? makeStages() : options.stages,
      submitting: options.submitting ?? false,
    },
    global: { plugins: [i18n] },
  })
}

/** 从渲染结果读每个节点的 `data-state`（判据落在 DOM 上，⛔ 不读组件内部状态）。 */
function renderedStates(wrapper: ReturnType<typeof mountStepper>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const li of wrapper.findAll(NODE)) {
    const stage = li.attributes('data-stage')
    if (stage)
      result[stage] = li.attributes('data-state') ?? ''
  }
  return result
}

/** 完整事件流（八节点里七个有事件；与旧 stageTimeline spec 同款素材）。 */
function fullEventStream(): BlueprintEvent[] {
  return [
    event('blueprint.spec_gate.scored', {}, '2026-08-01T00:00:01Z'),
    event('blueprint.spec_gate.locked', {}, '2026-08-01T00:00:02Z'),
    event('blueprint.route.scored', {}, '2026-08-01T00:00:03Z'),
    event('blueprint.repo_research.started', {}, '2026-08-01T00:00:04Z'),
    event('blueprint.repo_research.completed', {}, '2026-08-01T00:00:05Z'),
    event('blueprint.confirmation.opened', {}, '2026-08-01T00:00:06Z'),
    event('blueprint.confirmation.locked', {}, '2026-08-01T00:00:07Z'),
    event('blueprint.context.entry_appended', {}, '2026-08-01T00:00:08Z'),
    event('blueprint.context.waiter_registered', {}, '2026-08-01T00:00:09Z'),
    event('blueprint.context.waiter_satisfied', {}, '2026-08-01T00:00:10Z'),
    event('blueprint.review.started', {}, '2026-08-01T00:00:11Z'),
    event('blueprint.review.completed', {}, '2026-08-01T00:00:12Z'),
  ]
}

describe('blueprintStageStepper —— 节点排与状态同源（MN-01 继承）', () => {
  it('⭐ 八个节点全部出现，顺序 = BLUEPRINT_STAGES', () => {
    const wrapper = mountStepper()
    const nodes = wrapper.findAll(NODE)
    expect(nodes).toHaveLength(BLUEPRINT_STAGES.length)
    expect(nodes.map(node => node.attributes('data-stage'))).toEqual([...BLUEPRINT_STAGES])
  })

  it('⭐ data-state 与 buildStageTimeline 的返回逐节点相同（多组入参）', () => {
    const events = fullEventStream()
    const cases: ReadonlyArray<[string, string]> = [
      ['ai_review', 'confirmed'],
      ['repo_confirmation', 'drafting'],
      ['', 'pending_review'],
      ['repo_research', 'researching'],
    ]
    for (const [currentStage, currentStatus] of cases) {
      const rendered = renderedStates(mountStepper({ events, currentStage, currentStatus }))
      const derived = Object.fromEntries(
        buildStageTimeline(events, currentStage, currentStatus).map(node => [node.stage, node.state]),
      )
      expect({ currentStage, currentStatus, states: rendered })
        .toEqual({ currentStage, currentStatus, states: derived })
    }
  })

  it('运行中节点有动效（脉冲 + 旋转），完成后动效清零', () => {
    const running = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
    })
    expect(running.findAll('.animate-ping').length).toBeGreaterThan(0)
    expect(running.findAll('.animate-spin').length).toBeGreaterThan(0)

    const settled = mountStepper({
      events: fullEventStream(),
      currentStage: 'ai_review',
      currentStatus: 'confirmed',
    })
    expect(settled.findAll('.animate-ping')).toHaveLength(0)
    expect(settled.findAll('.animate-spin')).toHaveLength(0)
  })

  it('失败节点带 failed 态标识（x 图标 + destructive 语义）', () => {
    const wrapper = mountStepper({
      events: [
        event('blueprint.repo_research.started'),
        event('blueprint.repo_research.failed', {}, '2026-08-05T02:00:00+00:00'),
      ],
      currentStage: 'repo_research',
      currentStatus: 'failed',
    })
    const node = wrapper.find(`${NODE}[data-stage="repo_research"]`)
    expect(node.attributes('data-state')).toBe('failed')
    expect(node.find('.icon-\\[lucide--x\\]').exists()).toBe(true)
  })

  it('⭐ 等澄清 ⇒ 运行中节点换成醒目问号标识（⛔ 不再转圈装忙）', () => {
    const wrapper = mountStepper({
      events: [event('blueprint.spec_gate.clarification_asked', { question_count: 2 })],
      currentStage: 'spec_gate',
      currentStatus: 'needs_clarification',
    })
    const node = wrapper.find(`${NODE}[data-stage="spec_gate"]`)
    expect(node.attributes('data-state')).toBe('running')
    expect(node.find('.icon-\\[lucide--help-circle\\]').exists()).toBe(true)
    expect(node.find('.animate-spin').exists()).toBe(false)
  })
})

describe('blueprintStageStepper —— 详情区（单选展开）', () => {
  it('⭐ 默认自动落在进行中节点上；点击别的节点切过去、再点收起', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored', { candidate_count: 2 })],
      currentStage: 'route',
      currentStatus: 'drafting',
    })
    // 自动落点 = 运行中的 route
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('route')

    await wrapper.find(`${NODE}[data-stage="merge"] button`).trigger('click')
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('merge')

    // 再点同一节点 ⇒ 收起（单选可清空）
    await wrapper.find(`${NODE}[data-stage="merge"] button`).trigger('click')
    expect(wrapper.find(DETAIL).exists()).toBe(false)
  })

  it('详情含摘要事实与该节点的事件明细（复用 buildStagePanorama 的产出）', async () => {
    const wrapper = mountStepper({
      events: [
        event('blueprint.route.scored', {
          candidate_count: 2,
          candidates: [
            { repository_id: 'r1', repository_name: '数学仓', total: 0.8 },
            { repository_id: 'r2', repository_name: '语文仓', total: 0.4 },
          ],
        }),
      ],
      currentStage: 'route',
      currentStatus: 'drafting',
    })
    const detail = wrapper.find(DETAIL)
    // 摘要事实
    const fact = detail.find('[data-fact="candidateCount"]')
    expect(fact.exists()).toBe(true)
    expect(fact.text()).toContain('候选仓')
    expect(fact.text()).toContain('2')
    // 事件明细：复合键展开成可读行，⛔ 不只列键名
    const group = detail.find('[data-testid="blueprint-stepper-event-group"][data-group="candidates"]')
    expect(group.exists()).toBe(true)
    expect(group.text()).toContain('repository_name=数学仓')
  })

  it('⭐ stage_state 分片渲染成可读键值 + 折叠 JSON（⛔ 不整页倾倒）', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored', { candidate_count: 2 })],
      currentStage: 'route',
      currentStatus: 'drafting',
      stages: makeStages({
        stages: [
          { key: 'route', state: { intent: 'feature', routing: { candidate_count: 2 } } },
        ],
      }),
    })
    const state = wrapper.find('[data-testid="blueprint-stepper-state"]')
    expect(state.exists()).toBe(true)
    // 标量字段直接可读
    expect(state.text()).toContain('intent')
    expect(state.text()).toContain('feature')
    // 复合键折成行 + 计数
    expect(state.find('[data-group="routing"]').exists()).toBe(true)
    // 原始 JSON 默认收起、点击展开
    expect(wrapper.find('[data-testid="blueprint-stepper-state-raw"]').exists()).toBe(false)
    await wrapper.find('[data-testid="blueprint-stepper-state-raw-toggle"]').trigger('click')
    expect(wrapper.find('[data-testid="blueprint-stepper-state-raw"]').text()).toContain('candidate_count')
  })

  it('分片为空（{}）⇒ 状态数据区整块不渲染', () => {
    const wrapper = mountStepper({
      events: [event('blueprint.confirmation.opened')],
      currentStage: 'repo_confirmation',
      currentStatus: 'drafting',
      stages: makeStages({ stages: [{ key: 'repo_confirmation', state: {} }] }),
    })
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('confirmation')
    expect(wrapper.find('[data-testid="blueprint-stepper-state"]').exists()).toBe(false)
  })

  it('上一步/下一步在节点间切换，边界处按钮禁用', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
    })
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('route')
    // route 是第一个节点 ⇒ 上一步禁用
    expect(wrapper.find('[data-testid="blueprint-stepper-prev"]').attributes('disabled')).toBeDefined()

    await wrapper.find('[data-testid="blueprint-stepper-next"]').trigger('click')
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('repo_research')

    await wrapper.find('[data-testid="blueprint-stepper-prev"]').trigger('click')
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('route')
  })
})

describe('blueprintStageStepper —— 带指令重跑', () => {
  it('⭐ 提交时 UI 节点 key 映射成后端 stage key（confirmation → repo_confirmation）', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.confirmation.opened')],
      currentStage: 'repo_confirmation',
      currentStatus: 'drafting',
    })
    expect(wrapper.find(DETAIL).attributes('data-stage')).toBe('confirmation')
    await wrapper.find(RERUN_INPUT).setValue('  这次把边缘仓也考虑进去  ')
    await wrapper.find(RERUN_SUBMIT).trigger('click')
    expect(wrapper.emitted('rerun')).toEqual([
      [{ stage: 'repo_confirmation', instruction: '这次把边缘仓也考虑进去' }],
    ])
  })

  it('⭐ 无会话（session_id 为空）⇒ 重跑表单不渲染', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
      stages: makeStages({ session_id: '' }),
    })
    expect(wrapper.find(DETAIL).exists()).toBe(true)
    expect(wrapper.find(RERUN_FORM).exists()).toBe(false)
  })

  it('节点不在 rerunnable_stages ⇒ 不渲染表单；pending_review 虚拟节点恒无表单', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
      stages: makeStages({ rerunnable_stages: ['spec_gate'] }),
    })
    // route 不在集合内
    expect(wrapper.find(RERUN_FORM).exists()).toBe(false)

    const full = mountStepper({
      events: fullEventStream(),
      currentStage: '',
      currentStatus: 'pending_review',
    })
    // pending_review 是进行中节点 ⇒ 自动落点已在它身上，无需点击
    expect(full.find(DETAIL).attributes('data-stage')).toBe('pending_review')
    expect(full.find(RERUN_FORM).exists()).toBe(false)
  })

  it('submitting 时按钮禁用（防重复提交）', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
      submitting: true,
    })
    expect(wrapper.find(RERUN_SUBMIT).attributes('disabled')).toBeDefined()
    await wrapper.find(RERUN_SUBMIT).trigger('click')
    expect(wrapper.emitted('rerun')).toBeUndefined()
  })

  it('⭐ 该节点的重跑历史渲染（时间 + 指令；当前标记并入且不重复）', async () => {
    const marker = {
      stage: 'route',
      instruction: '这次优先央端仓',
      run_label: '1.2',
      requested_by: 'u-1',
      requested_at: '2026-08-06T10:00:00+00:00',
    }
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
      stages: makeStages({
        stage_rerun: marker,
        stage_rerun_history: [
          marker,
          { stage: 'route', instruction: '先看章程', run_label: '1.1', requested_by: 'u-1', requested_at: '2026-08-06T09:00:00+00:00' },
          { stage: 'spec_gate', instruction: '别的节点的记录', run_label: '1.3', requested_by: 'u-1', requested_at: '2026-08-06T11:00:00+00:00' },
        ],
      }),
    })
    const history = wrapper.find('[data-testid="blueprint-stepper-history"]')
    expect(history.exists()).toBe(true)
    const items = history.findAll('[data-testid="blueprint-stepper-history-item"]')
    // route 的两条（marker 与 history 里同一条不重复），spec_gate 的不掺进来
    expect(items).toHaveLength(2)
    expect(history.text()).toContain('这次优先央端仓')
    expect(history.text()).toContain('先看章程')
    expect(history.text()).not.toContain('别的节点的记录')
  })

  it('stages 供数缺席（查询失败降级 null）⇒ 节点排照常、无重跑面', () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
      stages: null,
    })
    expect(wrapper.findAll(NODE)).toHaveLength(BLUEPRINT_STAGES.length)
    expect(wrapper.find(RERUN_FORM).exists()).toBe(false)
  })
})

describe('blueprintStageStepper —— 仓库调研过程明细可读性（quick-260817-xb9）', () => {
  async function openResearchDetail(wrapper: ReturnType<typeof mountStepper>) {
    const detail = wrapper.find(DETAIL)
    // 已自动落在调研节点时再点会收起；仅在未展开或展开了别的节点时点击
    if (detail.exists() && detail.attributes('data-stage') === 'repo_research')
      return
    await wrapper.find(`${NODE}[data-stage="repo_research"] button`).trigger('click')
  }

  it('有 repository_name 时标题含仓名；字段标签非英文键；枚举中文', async () => {
    const wrapper = mountStepper({
      events: [
        event('blueprint.repo_research.started', {
          repository_name: 'gaosan-web',
          research_reason: '主落点仓',
          routed_confidence: 'high',
          repository_id: '11111111-1111-1111-1111-111111111111',
          task_id: '22222222-2222-2222-2222-222222222222',
        }),
        event('blueprint.repo_research.completed', {
          repository_name: 'gaosan-web',
          fitness_verdict: 'suitable',
          repository_id: '11111111-1111-1111-1111-111111111111',
        }),
      ],
      currentStage: 'repo_research',
      currentStatus: 'researching',
    })
    await openResearchDetail(wrapper)
    const detail = wrapper.find(DETAIL)
    expect(detail.exists()).toBe(true)
    expect(detail.text()).toContain('正在调研 gaosan-web')
    expect(detail.text()).toContain('调研理由')
    expect(detail.text()).toContain('路由置信度')
    expect(detail.text()).toContain('高')
    expect(detail.text()).toContain('适配')
    expect(detail.text()).not.toContain('routed_confidence')
    expect(detail.text()).not.toContain('research_reason')
  })

  it('缺 repository_name 的存量事件回落 Generic，不白屏', async () => {
    const wrapper = mountStepper({
      events: [
        event('blueprint.repo_research.started', { repository_id: 'r-old' }),
        event('blueprint.repo_research.failed', { error_kind: 'container_failed' }),
      ],
      currentStage: 'repo_research',
      currentStatus: 'researching',
    })
    await openResearchDetail(wrapper)
    const text = wrapper.find(DETAIL).text()
    expect(text).toContain('正在调研相关仓库')
    expect(text).toContain('仓库调研未成功')
    expect(text).not.toContain('undefined')
  })
})

describe('blueprintStageStepper —— 整篇重新生成（decompose 重跑 = major 版本）', () => {
  const TOGGLE = '[data-testid="blueprint-stepper-full-rerun-toggle"]'
  const FORM = '[data-testid="blueprint-stepper-full-rerun-form"]'
  const INPUT = '[data-testid="blueprint-stepper-full-rerun-input"]'
  const SUBMIT = '[data-testid="blueprint-stepper-full-rerun-submit"]'

  it('⭐ 头部入口展开表单，提交 emit stage=decompose（时间线八节点无 decompose 入口，唯此一处）', async () => {
    const wrapper = mountStepper({
      events: [event('blueprint.route.scored')],
      currentStage: 'route',
      currentStatus: 'drafting',
    })
    expect(wrapper.find(FORM).exists()).toBe(false)
    await wrapper.find(TOGGLE).trigger('click')
    await wrapper.find(INPUT).setValue('  需求改了：只做移动端  ')
    await wrapper.find(SUBMIT).trigger('click')
    expect(wrapper.emitted('rerun')).toEqual([
      [{ stage: 'decompose', instruction: '需求改了：只做移动端' }],
    ])
  })

  it('无会话 / decompose 不在 rerunnable_stages ⇒ 入口不渲染', () => {
    const noSession = mountStepper({ stages: makeStages({ session_id: '' }) })
    expect(noSession.find(TOGGLE).exists()).toBe(false)

    const notRerunnable = mountStepper({ stages: makeStages({ rerunnable_stages: ['route'] }) })
    expect(notRerunnable.find(TOGGLE).exists()).toBe(false)
  })
})
