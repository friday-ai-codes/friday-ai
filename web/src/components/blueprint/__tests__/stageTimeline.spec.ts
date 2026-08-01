/**
 * 八节点阶段时间线的末态推断（Phase 115-06；MJ-02 / MN-01 回归）。
 *
 * ## 这个 spec 存在的理由
 *
 * 末态原本**只按事件名后缀**推断（`.completed` / `.locked` / `.failed`）。把
 * `EVENT_STAGE_MAP` 按 stage 摊开会发现 `route` / `repo_plan` / `merge` 三个阶段的**全部
 * 出边**都不以那三个后缀结尾（`route.scored` / `reroute.triggered` /
 * `context.entry_appended` / `context.waiter_registered` / `context.waiter_satisfied`）
 * ⇒ 只要它们发过任何一条事件，状态就永久钉在 `running`：一份**早已 confirmed**、编排结束
 * 的蓝图，时间线上仍有三个阶段挂着 `animate-spin` 与「进行中」徽标。
 *
 * 这是典型的静默假通过 —— 不报错、不空白、看着还很「活」，只是永远不对。所以下面每条
 * 「全绿」断言都配了一条**非恒真对照**：没跑完的阶段必须仍然 `running`，否则「把所有阶段
 * 一律判 done」这种同样能让主断言变绿的错误实现就无法被拦住。
 *
 * 覆盖路径：
 *  1. ⭐ 完整事件流 + `confirmed` ⇒ 八个节点里 `running` 数量为 **0**、`animate-spin` 为 **0**。
 *  2. 非恒真对照：`repo_research.started` 之后没有 `.completed` ⇒ 该 stage 仍 `running`。
 *  3. ⭐ 会话 stage 名与时间线节点名**不同名**（`repo_confirmation` ↔ `confirmation`）：
 *     位序推断必须走别名表，否则 gate 阶段的 `route` 仍会转圈。
 *  4. 终态状态在 `current_stage` 缺失时独立生效（事件端点返空会话时 `current_stage` 是 `''`）。
 *  5. ⭐ MN-01：组件与纯函数**同源** —— 组件渲染出的 `data-state` 与 `buildStageTimeline`
 *     的返回逐节点相同（两份派生逻辑并存时，只修其中一份会让这条转红）。
 */

import type { BlueprintEvent } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintStageTimeline from '~/components/blueprint/BlueprintStageTimeline.vue'
import { BLUEPRINT_STAGES, buildStageTimeline } from '~/utils/blueprintBlocks'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          stage: {
            title: '编排进展',
            empty: '暂无阶段事件',
            spec_gate: '需求规格闸',
            route: '仓库路由',
            repo_research: '仓库调研',
            confirmation: '仓库集确认',
            repo_plan: '分仓方案',
            merge: '方案融合',
            ai_review: 'AI 审查',
            pending_review: '待人类审查',
            stateIdle: '未开始',
            stateRunning: '进行中',
            stateDone: '完成',
            stateFailed: '失败',
          },
        },
      },
    },
  },
})

const PASSTHROUGH = { template: '<div><slot /></div>' }

const STUBS = {
  Collapsible: { name: 'Collapsible', props: ['disabled'], template: '<div><slot /></div>' },
  CollapsibleTrigger: { name: 'CollapsibleTrigger', props: ['disabled'], template: '<button type="button"><slot /></button>' },
  CollapsibleContent: PASSTHROUGH,
  Badge: { name: 'Badge', props: ['variant'], template: '<span><slot /></span>' },
}

let seq = 0

function makeEvent(name: string, ts: string): BlueprintEvent {
  seq += 1
  return { id: `e-${seq}`, event: name, ts, payload: {} } as BlueprintEvent
}

/** 「每个能发终态事件的阶段都发了」的完整事件流（八节点里七个有事件）。 */
function fullEventStream(): BlueprintEvent[] {
  return [
    makeEvent('blueprint.spec_gate.scored', '2026-08-01T00:00:01Z'),
    makeEvent('blueprint.spec_gate.locked', '2026-08-01T00:00:02Z'),
    makeEvent('blueprint.route.scored', '2026-08-01T00:00:03Z'),
    makeEvent('blueprint.repo_research.started', '2026-08-01T00:00:04Z'),
    makeEvent('blueprint.repo_research.completed', '2026-08-01T00:00:05Z'),
    makeEvent('blueprint.confirmation.opened', '2026-08-01T00:00:06Z'),
    makeEvent('blueprint.confirmation.locked', '2026-08-01T00:00:07Z'),
    makeEvent('blueprint.context.entry_appended', '2026-08-01T00:00:08Z'),
    makeEvent('blueprint.context.waiter_registered', '2026-08-01T00:00:09Z'),
    makeEvent('blueprint.context.waiter_satisfied', '2026-08-01T00:00:10Z'),
    makeEvent('blueprint.review.started', '2026-08-01T00:00:11Z'),
    makeEvent('blueprint.review.completed', '2026-08-01T00:00:12Z'),
  ]
}

function mountTimeline(options: {
  events: BlueprintEvent[]
  currentStage?: string
  currentStatus?: string
}) {
  return mount(BlueprintStageTimeline, {
    props: {
      events: options.events,
      currentStage: options.currentStage ?? '',
      currentStatus: options.currentStatus ?? '',
    },
    global: { plugins: [i18n], stubs: STUBS },
  })
}

/** 从渲染结果读每个节点的 `data-state`（判据落在 DOM 上，⛔ 不读组件内部状态）。 */
function renderedStates(wrapper: ReturnType<typeof mountTimeline>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const li of wrapper.findAll('li[data-stage]')) {
    const stage = li.attributes('data-stage')
    if (stage)
      result[stage] = li.attributes('data-state') ?? ''
  }
  return result
}

describe('⭐ mJ-02：三个无终态出边的阶段必须能到达「完成」', () => {
  it('1. 完整事件流 + confirmed ⇒ running 数量为 0，且零个 animate-spin', () => {
    const wrapper = mountTimeline({
      events: fullEventStream(),
      // ⚠️ `__done__` 只是转移表的 sentinel，`current_stage` 落的是**发出该出边的那个 stage**。
      currentStage: 'ai_review',
      currentStatus: 'confirmed',
    })
    const states = renderedStates(wrapper)
    expect(Object.keys(states)).toHaveLength(BLUEPRINT_STAGES.length)
    expect(Object.entries(states).filter(([, state]) => state === 'running')).toEqual([])
    expect(wrapper.findAll('.animate-spin')).toHaveLength(0)
    // 逐节点钉死，防止「全判 idle」这种同样能让上面两条变绿的实现
    expect(states).toEqual({
      spec_gate: 'done',
      route: 'done',
      repo_research: 'done',
      confirmation: 'done',
      repo_plan: 'done',
      merge: 'done',
      ai_review: 'done',
      pending_review: 'idle',
    })
  })

  it('2. 非恒真对照：started 之后没有 completed ⇒ 该 stage 仍 running', () => {
    const wrapper = mountTimeline({
      events: [
        makeEvent('blueprint.spec_gate.locked', '2026-08-01T00:00:01Z'),
        makeEvent('blueprint.route.scored', '2026-08-01T00:00:02Z'),
        makeEvent('blueprint.repo_research.started', '2026-08-01T00:00:03Z'),
      ],
      currentStage: 'repo_research',
      currentStatus: 'researching',
    })
    const states = renderedStates(wrapper)
    expect(states.repo_research).toBe('running')
    // 走过的阶段仍要收成 done（否则「一律 running」也能让本条变绿）
    expect(states.route).toBe('done')
    expect(states.spec_gate).toBe('done')
    expect(wrapper.findAll('.animate-spin')).toHaveLength(1)
  })

  it('3. 会话 stage 名与节点名不同名（repo_confirmation ↔ confirmation）仍能定位位序', () => {
    const states = renderedStates(mountTimeline({
      events: [
        makeEvent('blueprint.route.scored', '2026-08-01T00:00:01Z'),
        makeEvent('blueprint.confirmation.opened', '2026-08-01T00:00:02Z'),
      ],
      currentStage: 'repo_confirmation',
      currentStatus: 'drafting',
    }))
    expect(states.route).toBe('done')
    // 当前所在阶段本身不能被位序规则误收（对照）
    expect(states.confirmation).toBe('running')
  })

  it('4. current_stage 缺失时，终态状态独立把发过事件的阶段收成 done', () => {
    const states = renderedStates(mountTimeline({
      events: fullEventStream(),
      currentStage: '',
      currentStatus: 'implemented',
    }))
    expect(Object.values(states).filter(state => state === 'running')).toEqual([])
    expect(states.merge).toBe('done')
    expect(states.pending_review).toBe('idle')
  })

  it('5. failed 后缀优先于位序规则（走过的失败阶段不得被收成 done）', () => {
    const states = renderedStates(mountTimeline({
      events: [
        makeEvent('blueprint.repo_research.started', '2026-08-01T00:00:01Z'),
        makeEvent('blueprint.repo_research.failed', '2026-08-01T00:00:02Z'),
      ],
      currentStage: 'ai_review',
      currentStatus: 'confirmed',
    }))
    expect(states.repo_research).toBe('failed')
  })
})

describe('⭐ MN-01：组件与纯函数同源（⛔ 不得存在第二份派生逻辑）', () => {
  it('6. 组件渲染出的 data-state 与 buildStageTimeline 的返回逐节点相同', () => {
    const events = fullEventStream()
    const cases: ReadonlyArray<[string, string]> = [
      ['ai_review', 'confirmed'],
      ['repo_confirmation', 'drafting'],
      ['', 'pending_review'],
      ['repo_research', 'researching'],
    ]
    for (const [currentStage, currentStatus] of cases) {
      const rendered = renderedStates(mountTimeline({ events, currentStage, currentStatus }))
      const derived = Object.fromEntries(
        buildStageTimeline(events, currentStage, currentStatus).map(node => [node.stage, node.state]),
      )
      expect({ currentStage, currentStatus, states: rendered })
        .toEqual({ currentStage, currentStatus, states: derived })
    }
  })
})
