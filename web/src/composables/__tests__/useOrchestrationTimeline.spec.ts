/**
 * buildOrchestrationTimeline 穷举用例。
 *
 * 本模块是纯函数，所以每条用户可见规则都能用一组固定输入直接断言，不必挂 DOM。
 * 四条最容易做反、且做反了不会自己暴露的地方各有一条专门的守卫用例：
 * ① 可见性过滤与序号计算的先后（错位守卫）；② 回退转移下的阶段指针；
 * ③ 计数按自然键去重而非事件条数；④ 调研分母取实际容器数而非路由候选数。
 */
import type { OrchestrationRuntime } from '~/types/chat'
import type { TimelineStepItem } from '~/types/execution'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  buildOrchestrationTimeline,
  COPY,
  FAIL_REASON_LABELS,
  resolveRepoName,
  STAGE_ORDER,
} from '~/composables/useOrchestrationTimeline'

// ---------------------------------------------------------------------------
// fixture helpers
// ---------------------------------------------------------------------------

function ts(n: number): string {
  return `2026-07-31T00:00:${String(n).padStart(2, '0')}Z`
}

function makeSnapshot(overrides: Partial<OrchestrationRuntime> = {}): OrchestrationRuntime {
  return {
    session_id: 'sess-1',
    status: 'running',
    current_stage: 'decompose',
    has_classify: false,
    events: [],
    ...overrides,
  }
}

function makeEvent(event: string, payload: Record<string, unknown> = {}, at = 1) {
  return { event, ts: ts(at), payload }
}

function build(overrides: {
  snapshot?: OrchestrationRuntime | null
  events?: Array<{ event: string, ts: string, payload?: Record<string, unknown> }>
  runtimeActive?: boolean
  repoNames?: Record<string, string>
} = {}) {
  return buildOrchestrationTimeline({
    snapshot: overrides.snapshot ?? null,
    events: overrides.events ?? [],
    runtimeActive: overrides.runtimeActive ?? true,
    repoNames: overrides.repoNames,
  })
}

function step(view: { steps: TimelineStepItem[] }, name: string): TimelineStepItem | undefined {
  return view.steps.find(item => item.name === name)
}

function names(view: { steps: TimelineStepItem[] }): string[] {
  return view.steps.map(item => item.name)
}

/** 一对完整的澄清事件：让「澄清」这一步落在 completed 而不是 skipped。 */
const CLARIFIED_PAIR = [
  makeEvent('clarification.asked', { clarification_id: 'c1' }, 10),
  makeEvent('clarification.answered', { clarification_id: 'c1' }, 11),
]

let warnSpy: ReturnType<typeof vi.spyOn>
let errorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  // 事件截断与快照/事件冲突都是正常场景，不是异常：全程零 warn / 零 error。
  expect(warnSpy).not.toHaveBeenCalled()
  expect(errorSpy).not.toHaveBeenCalled()
  vi.restoreAllMocks()
})

// ---------------------------------------------------------------------------

describe('模块常量', () => {
  it('stage_order 是完整 7 键（可见性过滤不得缩短它）', () => {
    expect(STAGE_ORDER).toEqual(['decompose', 'route', 'recall', 'classify', 'clarify', 'research', 'merge'])
    expect(STAGE_ORDER).toHaveLength(7)
  })

  it('失败原因闭集恰 6 键', () => {
    expect(Object.keys(FAIL_REASON_LABELS).sort()).toEqual([
      'advance_step_limit',
      'clarification_timeout_no_answer',
      'merge_validation_exhausted',
      'stage_exception',
      'unknown_process_type',
      'unknown_stage',
    ])
  })

  it('resolveRepoName 命中映射时取仓库名', () => {
    expect(resolveRepoName('repo-uuid-1', { 'repo-uuid-1': 'friday-web' })).toBe('friday-web')
  })

  it('resolveRepoName 解析不出时回退常量且不回显裸 UUID', () => {
    expect(resolveRepoName('repo-uuid-1', {})).toBe('未知仓库')
    expect(resolveRepoName('repo-uuid-1')).toBe('未知仓库')
    expect(resolveRepoName('repo-uuid-1')).not.toContain('repo-uuid-1')
  })
})

describe('步骤集合与可见性', () => {
  it('空输入 ⇒ 6 步、全 pending、phase 为 running', () => {
    const view = build()
    expect(view.steps).toHaveLength(6)
    expect(names(view)).toEqual(['拆分', '路由', '召回', '澄清', '并行调研', '融合'])
    expect(view.steps.map(s => s.status)).toEqual(['pending', 'pending', 'pending', 'pending', 'pending', 'pending'])
    expect(view.phase).toBe('running')
    expect(view.title).toBe(COPY.titleRunning)
    expect(view.totalCount).toBe(6)
    expect(view.doneCount).toBe(0)
  })

  it('has_classify 为 true ⇒ 7 步且第 4 项是「功能点分类」', () => {
    const view = build({ snapshot: makeSnapshot({ has_classify: true }) })
    expect(view.steps).toHaveLength(7)
    expect(view.steps[3].name).toBe('功能点分类')
    expect(view.totalCount).toBe(7)
  })

  it('has_classify 为 false 且无分类事件 ⇒ 结果里不存在「功能点分类」这一项', () => {
    const view = build({ snapshot: makeSnapshot({ has_classify: false }) })
    expect(names(view)).not.toContain('功能点分类')
    expect(view.steps.filter(s => s.name === '功能点分类')).toHaveLength(0)
    expect(view.steps).toHaveLength(6)
  })

  it('快照缺失但见过 technical_plan.feature.classified ⇒ 7 步（兜底分支）', () => {
    const view = build({
      snapshot: null,
      events: [makeEvent('technical_plan.feature.classified', { summary: { new: 1, modify: 0, unclear: 0 } }, 1)],
    })
    expect(view.steps).toHaveLength(7)
    expect(view.steps[3].name).toBe('功能点分类')
  })

  it('错位守卫：隐藏 classify 时后续步骤的状态不整体错位一格', () => {
    // 序号若先过滤再算，「并行调研」会被算成 completed、「融合」被算成 running。
    const view = build({ snapshot: makeSnapshot({ has_classify: false, current_stage: 'research' }) })
    expect(view.steps).toHaveLength(6)
    expect(step(view, '召回')?.status).toBe('completed')
    expect(step(view, '并行调研')?.status).toBe('running')
    expect(step(view, '融合')?.status).toBe('pending')
  })
})

describe('阶段指针', () => {
  it('快照 current_stage 优先于折叠事件流推出的指针', () => {
    const view = build({
      snapshot: makeSnapshot({ current_stage: 'merge' }),
      events: [makeEvent('routed', {}, 1)],
    })
    expect(step(view, '融合')?.status).toBe('running')
    expect(step(view, '并行调研')?.status).toBe('completed')
  })

  it('无快照时取最后一条可识别转移事件的目标 stage', () => {
    const view = build({ events: [makeEvent('routed', {}, 1), makeEvent('recalled', {}, 2)] })
    expect(step(view, '召回')?.status).toBe('completed')
    expect(step(view, '澄清')?.status).toBe('pending')
  })

  it('无快照 + recalled ⇒ 指针精确落在 classify 这一步上', () => {
    const view = build({
      events: [
        makeEvent('technical_plan.feature.classified', { summary: { new: 1, modify: 1, unclear: 0 } }, 1),
        makeEvent('recalled', {}, 2),
      ],
    })
    expect(step(view, '功能点分类')?.status).toBe('running')
    expect(step(view, '澄清')?.status).toBe('pending')
  })

  it('回退转移：validation_failed_reclarify 之后指针回到 clarify 而不是停在 merge', () => {
    const view = build({
      events: [
        makeEvent('routed', {}, 1),
        makeEvent('recalled', {}, 2),
        makeEvent('classified', {}, 3),
        makeEvent('clarified', {}, 4),
        makeEvent('research_complete', {}, 5),
        makeEvent('validation_failed_reclarify', {}, 6),
      ],
    })
    expect(step(view, '澄清')?.status).toBe('running')
    expect(step(view, '并行调研')?.status).toBe('pending')
    expect(step(view, '融合')?.status).toBe('pending')
  })

  it('乱序投递时按 ts 归并，最后一条仍是 ts 最大的那条', () => {
    const view = build({
      events: [makeEvent('validation_failed_reclarify', {}, 6), makeEvent('research_complete', {}, 5)],
    })
    expect(step(view, '澄清')?.status).toBe('running')
    expect(step(view, '融合')?.status).toBe('pending')
  })

  it('current_stage 为未知 key ⇒ 退回事件指针、不抛、步骤数不变', () => {
    const view = build({
      snapshot: makeSnapshot({ current_stage: 'not_a_stage' }),
      events: [makeEvent('routed', {}, 1)],
    })
    expect(view.steps).toHaveLength(6)
    expect(step(view, '召回')?.status).toBe('running')
    expect(step(view, '路由')?.status).toBe('completed')
  })

  it('快照与事件冲突时不打 warn / error', () => {
    build({
      snapshot: makeSnapshot({ current_stage: 'merge' }),
      events: [makeEvent('routed', {}, 1)],
    })
    expect(warnSpy).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
  })
})

describe('摘要 · 拆分', () => {
  it('segment_count 为 3 ⇒ 已拆出 3 个需求点', () => {
    const view = build({ snapshot: makeSnapshot({ segment_count: 3 }) })
    expect(step(view, '拆分')?.summary).toBe('已拆出 3 个需求点')
  })

  it('segment_count 为 null ⇒ 该步无摘要（不产出「暂无」占位）', () => {
    const view = build({ snapshot: makeSnapshot({ segment_count: null }) })
    expect(step(view, '拆分')?.summary).toBeUndefined()
  })
})

describe('摘要 · 路由', () => {
  it('candidates 长度 2 ⇒ 命中 2 个候选仓', () => {
    const view = build({ events: [makeEvent('repo.routing', { candidates: [{}, {}] }, 1)] })
    expect(step(view, '路由')?.summary).toBe('命中 2 个候选仓')
  })

  it('candidates 传字符串 ⇒ 该摘要为空且其余步骤照常', () => {
    const view = build({
      snapshot: makeSnapshot({ segment_count: 4 }),
      events: [makeEvent('repo.routing', { candidates: 'oops' }, 1)],
    })
    expect(step(view, '路由')?.summary).toBeUndefined()
    expect(step(view, '拆分')?.summary).toBe('已拆出 4 个需求点')
    expect(view.steps).toHaveLength(6)
  })
})

describe('摘要 · 召回', () => {
  it('hits 为 7 ⇒ 召回 7 条相关知识', () => {
    const view = build({ events: [makeEvent('knowledge.recalling', { hits: 7 }, 1)] })
    expect(step(view, '召回')?.summary).toBe('召回 7 条相关知识')
  })

  it('hits 为字符串 ⇒ 无摘要', () => {
    const view = build({ events: [makeEvent('knowledge.recalling', { hits: '7' }, 1)] })
    expect(step(view, '召回')?.summary).toBeUndefined()
  })
})

describe('摘要 · 功能点分类', () => {
  it('unclear 为 0 ⇒ 只有新增与改造，不含「待确认」', () => {
    const view = build({
      events: [makeEvent('technical_plan.feature.classified', { summary: { new: 1, modify: 2, unclear: 0 } }, 1)],
    })
    expect(step(view, '功能点分类')?.summary).toBe('新增 1 · 改造 2')
    expect(step(view, '功能点分类')?.summary).not.toContain('待确认')
  })

  it('unclear 大于 0 ⇒ 追加待确认', () => {
    const view = build({
      events: [makeEvent('technical_plan.feature.classified', { summary: { new: 1, modify: 2, unclear: 3 } }, 1)],
    })
    expect(step(view, '功能点分类')?.summary).toBe('新增 1 · 改造 2 · 待确认 3')
  })

  it('summary 不是 dict ⇒ 无摘要', () => {
    const view = build({
      snapshot: makeSnapshot({ has_classify: true }),
      events: [makeEvent('technical_plan.feature.classified', { summary: '新增两个' }, 1)],
    })
    expect(step(view, '功能点分类')?.summary).toBeUndefined()
  })
})

describe('摘要 · 澄清', () => {
  const waitingSnapshot = makeSnapshot({ status: 'waiting_clarification', current_stage: 'clarify' })

  it('asked 之后为等待中', () => {
    const view = build({
      snapshot: waitingSnapshot,
      events: [makeEvent('clarification.asked', { clarification_id: 'c1' }, 1)],
    })
    expect(step(view, '澄清')?.summary).toBe('等待你回答第 1 轮澄清')
    expect(step(view, '澄清')?.status).toBe('running')
  })

  it('answered 之后为已回答', () => {
    const view = build({
      snapshot: waitingSnapshot,
      events: [
        makeEvent('clarification.asked', { clarification_id: 'c1' }, 1),
        makeEvent('clarification.answered', { clarification_id: 'c1' }, 2),
      ],
    })
    expect(step(view, '澄清')?.summary).toBe('第 1 轮澄清已回答')
  })

  it('timed_out 取 payload 的 round_no', () => {
    const view = build({
      snapshot: waitingSnapshot,
      events: [
        makeEvent('clarification.asked', { clarification_id: 'c1' }, 1),
        makeEvent('clarification.timed_out', { clarification_id: 'c1', round_no: 2 }, 2),
      ],
    })
    expect(step(view, '澄清')?.summary).toBe('第 2 轮澄清超时，已按假设继续')
  })

  it('delivery_failed ⇒ 澄清卡送达失败', () => {
    const view = build({
      snapshot: waitingSnapshot,
      events: [makeEvent('clarification.delivery_failed', { clarification_id: 'c1' }, 1)],
    })
    expect(step(view, '澄清')?.summary).toBe('澄清卡送达失败')
  })

  it('已推进过澄清但全程无 clarification.* 事件 ⇒ skipped + 本次无需澄清', () => {
    const view = build({ snapshot: makeSnapshot({ current_stage: 'research' }) })
    expect(step(view, '澄清')?.status).toBe('skipped')
    expect(step(view, '澄清')?.summary).toBe('本次无需澄清')
  })

  it('出现过 clarification.asked 时即便已推进也不判 skipped', () => {
    const view = build({
      snapshot: makeSnapshot({ current_stage: 'research' }),
      events: CLARIFIED_PAIR,
    })
    expect(step(view, '澄清')?.status).toBe('completed')
  })
})

describe('摘要 · 并行调研', () => {
  /** 路由候选 5 个、实际派出 3 个容器：分母取错会立刻显形。 */
  const RESEARCH_EVENTS = [
    makeEvent('repo.routing', { candidates: [{}, {}, {}, {}, {}] }, 1),
    makeEvent('repo.research.started', { repo_id: 'r1' }, 2),
    makeEvent('repo.research.started', { repo_id: 'r2' }, 3),
    makeEvent('repo.research.started', { repo_id: 'r3' }, 4),
    makeEvent('repo.research.completed', { repo_id: 'r1' }, 5),
    makeEvent('repo.research.completed', { repo_id: 'r2' }, 6),
  ]

  it('分母取实际派了容器的去重 repo 数，不取路由候选数', () => {
    const view = build({
      snapshot: makeSnapshot({ current_stage: 'research' }),
      events: RESEARCH_EVENTS,
    })
    expect(step(view, '并行调研')?.summary).toBe('2/3 个仓库完成')
  })

  it('单仓失败只进失败计数，该步 status 仍是 running 而不是 failed', () => {
    const view = build({
      snapshot: makeSnapshot({ current_stage: 'research' }),
      events: [...RESEARCH_EVENTS, makeEvent('repo.research.failed', { repo_id: 'r3' }, 7)],
    })
    expect(step(view, '并行调研')?.summary).toBe('2/3 个仓库完成 · 1 个失败')
    expect(step(view, '并行调研')?.status).toBe('running')
    expect(view.phase).toBe('running')
  })

  it('一个容器都没派出时该步无摘要', () => {
    const view = build({ snapshot: makeSnapshot({ current_stage: 'research' }) })
    expect(step(view, '并行调研')?.summary).toBeUndefined()
  })
})

describe('摘要 · 融合', () => {
  it('merge.started 一次 ⇒ 正在融合各仓方案', () => {
    const view = build({ events: [makeEvent('technical_plan.merge.started', { partials: 2 }, 1)] })
    expect(step(view, '融合')?.summary).toBe('正在融合各仓方案')
  })

  it('merge.started 两次（不同 ts）⇒ 第 2 轮融合', () => {
    const view = build({
      events: [
        makeEvent('technical_plan.merge.started', { partials: 2 }, 1),
        makeEvent('technical_plan.merge.started', { partials: 2 }, 2),
      ],
    })
    expect(step(view, '融合')?.summary).toBe('第 2 轮融合')
  })

  it('见过 merge.completed ⇒ 方案已产出', () => {
    const view = build({
      events: [
        makeEvent('technical_plan.merge.started', { partials: 2 }, 1),
        makeEvent('technical_plan.merge.completed', { artifact_version_id: 'v1' }, 2),
      ],
    })
    expect(step(view, '融合')?.summary).toBe('方案已产出')
  })
})

describe('计数幂等', () => {
  const base = makeSnapshot({ current_stage: 'research' })
  const started = [
    makeEvent('repo.research.started', { repo_id: 'r1' }, 1),
    makeEvent('repo.research.started', { repo_id: 'r2' }, 2),
  ]

  it('同一条 completed 投递两次（同 repo_id 同 ts）⇒ 完成数仍为 1', () => {
    const view = build({
      snapshot: base,
      events: [
        ...started,
        makeEvent('repo.research.completed', { repo_id: 'r1' }, 5),
        makeEvent('repo.research.completed', { repo_id: 'r1' }, 5),
      ],
    })
    expect(step(view, '并行调研')?.summary).toBe('1/2 个仓库完成')
  })

  it('同一 repo_id 不同 ts 的两条 completed ⇒ 完成数仍为 1（按自然键去重，不是按 ts）', () => {
    const view = build({
      snapshot: base,
      events: [
        ...started,
        makeEvent('repo.research.completed', { repo_id: 'r1' }, 5),
        makeEvent('repo.research.completed', { repo_id: 'r1' }, 6),
      ],
    })
    expect(step(view, '并行调研')?.summary).toBe('1/2 个仓库完成')
  })

  it('同一 clarification_id 的两条 asked ⇒ 澄清轮次仍为 1', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'waiting_clarification', current_stage: 'clarify' }),
      events: [
        makeEvent('clarification.asked', { clarification_id: 'c1' }, 1),
        makeEvent('clarification.asked', { clarification_id: 'c1' }, 2),
      ],
    })
    expect(step(view, '澄清')?.summary).toBe('等待你回答第 1 轮澄清')
  })

  it('merge.started 同 ts 两条 ⇒ 轮次 1', () => {
    const view = build({
      events: [
        makeEvent('technical_plan.merge.started', { partials: 2 }, 3),
        makeEvent('technical_plan.merge.started', { partials: 2 }, 3),
      ],
    })
    expect(step(view, '融合')?.summary).toBe('正在融合各仓方案')
  })
})

describe('失败', () => {
  it('融合失败 ⇒ 该步 failed + 闭集文案，其前各步逐个 completed', () => {
    const view = build({
      snapshot: makeSnapshot({
        status: 'failed',
        current_stage: 'merge',
        failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
      }),
      events: CLARIFIED_PAIR,
    })
    expect(step(view, '融合')?.status).toBe('failed')
    expect(step(view, '融合')?.summary).toBe('融合校验多次未通过')
    expect(view.phase).toBe('failed')
    expect(view.title).toBe(COPY.titleFailed)
    // merge 是最后一步：它之后没有任何步骤
    expect(view.steps[view.steps.length - 1].name).toBe('融合')
    expect(view.steps.slice(0, -1).map(s => s.status)).toEqual([
      'completed',
      'completed',
      'completed',
      'completed',
      'completed',
    ])
  })

  // ── 缺维补齐：快照有无 × 会话状态 ──────────────────────────────────────
  // GAP-1 就是靠这一维缺失在全绿套件下存活的：前半程（拆分→澄清）走 SSE 直播，
  // pollConversationRuntime 尚未被调度 ⇒ snapshot 恒为 null，此时若只看快照
  // status，时间线会一直显示「正在生成技术方案」并把出错那步画成进行中。
  it('无快照 + process.session.failed ⇒ 判失败，指针那步标红而不是画成进行中', () => {
    const view = build({
      snapshot: null,
      // decomposed 把指针推到 route，随后会话失败 ⇒ 失败落在「路由」
      events: [makeEvent('decomposed', {}, 1), makeEvent('process.session.failed', {}, 2)],
    })
    expect(view.phase).toBe('failed')
    expect(view.title).toBe(COPY.titleFailed)
    expect(step(view, '路由')?.status).toBe('failed')
    // payload 恒为空 dict ⇒ 拿不到 reason_code，如实显示未知原因
    expect(step(view, '路由')?.summary).toBe(COPY.unknownReason)
    expect(step(view, '拆分')?.status).toBe('completed')
    // 失败步之后逐个 pending（不是「不等于 failed」）
    expect(step(view, '召回')?.status).toBe('pending')
    expect(step(view, '澄清')?.status).toBe('pending')
    expect(step(view, '并行调研')?.status).toBe('pending')
    expect(step(view, '融合')?.status).toBe('pending')
  })

  it('无快照 + 状态图转移名 fail ⇒ 同样判失败（两个名字都认）', () => {
    const view = build({
      snapshot: null,
      events: [makeEvent('routed', {}, 1), makeEvent('fail', {}, 2)],
    })
    expect(view.phase).toBe('failed')
    expect(step(view, '召回')?.status).toBe('failed')
  })

  it('快照在场时以快照为准：status=running 不被残留的失败事件翻转', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'running', current_stage: 'research' }),
      events: [makeEvent('process.session.failed', {}, 1)],
      runtimeActive: true,
    })
    expect(view.phase).not.toBe('failed')
    expect(view.steps.every(s => s.status !== 'failed')).toBe(true)
  })

  it('无快照 + 无失败事件 ⇒ 不得凭空判失败', () => {
    const view = build({ snapshot: null, events: [makeEvent('decomposed', {}, 1)] })
    expect(view.phase).not.toBe('failed')
    expect(view.steps.every(s => s.status !== 'failed')).toBe(true)
  })

  // 与 GAP-1 同根因：脉冲原先也只看快照 status，导致真直播的前半程不脉冲、
  // 2s 轮询的后半程反而脉冲，把「哪一半更实时」表达反了。
  it('无快照 + runtime 活跃 + 有转移事件 ⇒ 前半程直播时该步脉冲', () => {
    const view = build({
      snapshot: null,
      events: [makeEvent('decomposed', {}, 1)],
      runtimeActive: true,
    })
    // decomposed 把指针推到 route ⇒「路由」是 running 那一步
    expect(step(view, '路由')?.status).toBe('running')
    expect(step(view, '路由')?.pulse).toBe(true)
  })

  it('无快照 + 已失败 ⇒ 无任何步骤脉冲', () => {
    const view = build({
      snapshot: null,
      events: [makeEvent('decomposed', {}, 1), makeEvent('process.session.failed', {}, 2)],
      runtimeActive: true,
    })
    expect(view.steps.every(s => s.pulse !== true)).toBe(true)
  })

  it('无快照 + runtime 不活跃 ⇒ 无任何步骤脉冲', () => {
    const view = build({
      snapshot: null,
      events: [makeEvent('decomposed', {}, 1)],
      runtimeActive: false,
    })
    expect(view.steps.every(s => s.pulse !== true)).toBe(true)
  })

  it('路由失败 ⇒ 其后各步逐个等于 pending（不是「不等于 failed」）', () => {
    const view = build({
      snapshot: makeSnapshot({
        status: 'failed',
        current_stage: 'route',
        failure: { stage: 'route', reason_code: 'stage_exception' },
      }),
    })
    expect(step(view, '路由')?.status).toBe('failed')
    expect(step(view, '拆分')?.status).toBe('completed')
    expect(step(view, '召回')?.status).toBe('pending')
    expect(step(view, '澄清')?.status).toBe('pending')
    expect(step(view, '并行调研')?.status).toBe('pending')
    expect(step(view, '融合')?.status).toBe('pending')
  })

  it.each([
    ['stage_exception', '该阶段执行出错'],
    ['merge_validation_exhausted', '融合校验多次未通过'],
    ['clarification_timeout_no_answer', '澄清超时且无人应答'],
    ['advance_step_limit', '流程推进步数超限'],
    ['unknown_process_type', '流程类型未注册'],
    ['unknown_stage', '阶段未注册'],
  ])('reason_code %s ⇒ 文案 %s', (code, label) => {
    const view = build({
      snapshot: makeSnapshot({
        status: 'failed',
        current_stage: 'recall',
        failure: { stage: 'recall', reason_code: code },
      }),
    })
    expect(step(view, '召回')?.summary).toBe(label)
  })

  it('未命中的 reason_code ⇒ 未知原因，且结果序列化后不含原始取值', () => {
    const view = build({
      snapshot: makeSnapshot({
        status: 'failed',
        current_stage: 'recall',
        failure: { stage: 'recall', reason_code: 'weird_unmapped' },
      }),
    })
    expect(step(view, '召回')?.summary).toBe('未知原因')
    expect(JSON.stringify(view)).not.toContain('weird_unmapped')
    expect(view.liveMessage).not.toContain('weird_unmapped')
  })

  it('failure 缺失但 status 为 failed ⇒ 退回 current_stage 命中，文案为未知原因', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'failed', current_stage: 'recall' }),
    })
    expect(step(view, '召回')?.status).toBe('failed')
    expect(step(view, '召回')?.summary).toBe('未知原因')
    expect(view.phase).toBe('failed')
  })

  it('failure.stage 为未知 key ⇒ 不产生红步、不崩、步骤数不变', () => {
    const view = build({
      snapshot: makeSnapshot({
        status: 'failed',
        current_stage: 'not_a_stage',
        failure: { stage: 'not_a_stage', reason_code: 'stage_exception' },
      }),
    })
    expect(view.steps).toHaveLength(6)
    expect(view.steps.filter(s => s.status === 'failed')).toHaveLength(0)
    expect(view.phase).toBe('failed')
  })
})

describe('中断态', () => {
  it('不活跃 + running ⇒ 当前步 unknown，后续步保持 pending', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'running', current_stage: 'research' }),
      runtimeActive: false,
    })
    expect(step(view, '并行调研')?.status).toBe('unknown')
    expect(step(view, '并行调研')?.summary).toBe('进度未知，可能已中断')
    expect(step(view, '融合')?.status).toBe('pending')
    expect(step(view, '召回')?.status).toBe('completed')
  })

  it('不活跃 + waiting_event ⇒ 同样判中断', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'waiting_event', current_stage: 'merge' }),
      runtimeActive: false,
    })
    expect(step(view, '融合')?.status).toBe('unknown')
  })

  it('不活跃 + waiting_clarification ⇒ 不算中断，澄清步仍是 running 且不脉冲', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'waiting_clarification', current_stage: 'clarify' }),
      events: [makeEvent('clarification.asked', { clarification_id: 'c1' }, 1)],
      runtimeActive: false,
    })
    expect(step(view, '澄清')?.status).toBe('running')
    expect(step(view, '澄清')?.pulse).toBe(false)
    expect(step(view, '澄清')?.summary).toBe('等待你回答第 1 轮澄清')
  })

  it('活跃 + running ⇒ 当前步 running 且脉冲开启', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'running', current_stage: 'route' }),
      runtimeActive: true,
    })
    expect(step(view, '路由')?.status).toBe('running')
    expect(step(view, '路由')?.pulse).toBe(true)
  })
})

describe('降级角标', () => {
  it('degraded 为 true ⇒ 路由步带 warning 角标', () => {
    const view = build({ events: [makeEvent('repo.routing', { candidates: [{}], degraded: true }, 1)] })
    expect(step(view, '路由')?.badge).toEqual({ text: '降级', variant: 'warning' })
  })

  it('degraded 缺失（slim path）⇒ 无角标', () => {
    const view = build({ events: [makeEvent('repo.routing', { candidates: [{}] }, 1)] })
    expect(step(view, '路由')?.badge).toBeUndefined()
  })

  it('degraded 为 false ⇒ 无角标', () => {
    const view = build({ events: [makeEvent('repo.routing', { candidates: [{}], degraded: false }, 1)] })
    expect(step(view, '路由')?.badge).toBeUndefined()
  })

  it('degraded 为字符串 true ⇒ 无角标（严格比较，不做宽松真值判断）', () => {
    const view = build({ events: [makeEvent('repo.routing', { candidates: [{}], degraded: 'true' }, 1)] })
    expect(step(view, '路由')?.badge).toBeUndefined()
  })

  it('只有其他步骤不带角标，降级只标位置不做解释', () => {
    const view = build({ events: [makeEvent('repo.routing', { candidates: [{}], degraded: true }, 1)] })
    expect(view.steps.filter(s => s.badge !== undefined)).toHaveLength(1)
    const serialized = JSON.stringify(view)
    expect(serialized).not.toContain('未经 LLM 推理')
    expect(serialized).not.toContain('置信度')
  })
})

describe('终态与计数', () => {
  it('status 为 done ⇒ 全部可见步 completed、标题与计数到顶', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'done', current_stage: 'merge' }),
      events: CLARIFIED_PAIR,
    })
    expect(view.steps.map(s => s.status)).toEqual([
      'completed',
      'completed',
      'completed',
      'completed',
      'completed',
      'completed',
    ])
    expect(view.phase).toBe('done')
    expect(view.title).toBe('方案编排已完成')
    expect(view.doneCount).toBe(view.totalCount)
    expect(view.doneCount).toBe(6)
  })

  it('skipped 也计入 doneCount', () => {
    const view = build({ snapshot: makeSnapshot({ status: 'done', current_stage: 'merge' }) })
    expect(step(view, '澄清')?.status).toBe('skipped')
    expect(view.doneCount).toBe(6)
  })
})

describe('live region', () => {
  it('在途时播报当前阶段标签且不含调研计数', () => {
    const view = build({
      snapshot: makeSnapshot({ status: 'running', current_stage: 'research' }),
      events: [
        makeEvent('repo.research.started', { repo_id: 'r1' }, 1),
        makeEvent('repo.research.started', { repo_id: 'r2' }, 2),
        makeEvent('repo.research.completed', { repo_id: 'r1' }, 3),
      ],
    })
    expect(view.liveMessage).toBe('当前阶段：并行调研')
    expect(view.liveMessage).not.toContain('/')
  })

  it('完成时播报固定一句且不含计数', () => {
    const view = build({ snapshot: makeSnapshot({ status: 'done', current_stage: 'merge' }) })
    expect(view.liveMessage).toBe('方案编排已完成')
    expect(view.liveMessage).not.toContain('/')
  })

  it('失败时播报阶段标签与闭集原因', () => {
    const view = build({
      snapshot: makeSnapshot({
        status: 'failed',
        current_stage: 'merge',
        failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
      }),
    })
    expect(view.liveMessage).toBe('编排失败：融合 — 融合校验多次未通过')
  })
})

describe('兜底', () => {
  it('未知事件名混在事件流里 ⇒ 结果与不含它时逐字段相同', () => {
    const events = [makeEvent('routed', {}, 1), makeEvent('repo.routing', { candidates: [{}, {}] }, 2)]
    const withUnknown = build({
      snapshot: makeSnapshot({ current_stage: 'recall' }),
      events: [...events, makeEvent('brand.new.event', { whatever: 1 }, 3)],
    })
    const without = build({ snapshot: makeSnapshot({ current_stage: 'recall' }), events })
    expect(withUnknown).toEqual(without)
  })

  it('payload 为 null / 字符串 / 数组 ⇒ 不抛，其余摘要照常', () => {
    const view = build({
      snapshot: makeSnapshot({ segment_count: 2 }),
      events: [
        makeEvent('repo.routing', { candidates: [{}, {}] }, 1),
        { event: 'knowledge.recalling', ts: ts(2), payload: null as any },
        { event: 'technical_plan.feature.classified', ts: ts(3), payload: 'oops' as any },
        { event: 'repo.research.started', ts: ts(4), payload: [] as any },
      ],
    })
    expect(step(view, '路由')?.summary).toBe('命中 2 个候选仓')
    expect(step(view, '拆分')?.summary).toBe('已拆出 2 个需求点')
    expect(step(view, '召回')?.summary).toBeUndefined()
  })

  it('事件项本身是 null / 缺 event 字段 ⇒ 静默跳过', () => {
    const view = build({
      events: [null as any, { ts: ts(1) } as any, makeEvent('routed', {}, 2)],
    })
    expect(view.steps).toHaveLength(6)
    expect(step(view, '召回')?.status).toBe('running')
    expect(step(view, '路由')?.status).toBe('completed')
  })

  it('events 传非数组 ⇒ 降级为保守视图而不是抛错', () => {
    const view = buildOrchestrationTimeline({
      snapshot: null,
      events: 'nope' as any,
      runtimeActive: true,
    })
    expect(view.steps).toHaveLength(6)
    expect(view.phase).toBe('running')
  })

  it('repo_id 缺失的调研事件退回 ts 计数，不因 undefined 属性访问而抛', () => {
    const view = build({
      snapshot: makeSnapshot({ current_stage: 'research' }),
      events: [
        makeEvent('repo.research.started', {}, 1),
        makeEvent('repo.research.started', {}, 2),
      ],
    })
    expect(step(view, '并行调研')?.summary).toBe('0/2 个仓库完成')
  })
})
