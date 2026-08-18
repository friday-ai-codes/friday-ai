/**
 * 活动流 / 阶段全景派生的纯函数测试（Phase 119 + 全景化改造）。
 *
 * 除下列八条，另守阶段全景三组：`describeEventPayload` 的标量/复合键分流与半可信容错、
 * `buildStagePanorama` 的八节点恒定与归属、固定路由判定与摘要事实的「缺失不显示成 0」。
 *
 * 守八件事：
 *  1. ⭐ 路由适配度按 `route.scored` + `route.plan_drafted` 合成，按总分降序。
 *  2. ⭐ **重路由只取最新一轮**：多轮 `route.scored` 合并会把已排除的仓和新候选混在一张表里
 *     （用户看到「候选变多了」而事实是「换了一批」）。
 *  3. 缺分数 ⇒ `total` 为 `null`（调用方不显示 0%），且排在有分数的后面。
 *  4. ⭐ 分仓每仓三态：已产出 > 在跑 > 等依赖；`repo_completed` 后不被后续事件拉回进行中。
 *  5. ⭐ waiter 登记 ⇒ `waiting`；被重派（`redispatch_repository_ids` 含它）⇒ 解除等待。
 *  6. 产出计数（实现项 / 接口契约）取自 `repo_completed` payload。
 *  7. ⚠️ 半可信 payload：缺键 / 类型错 / 非数组一律不抛，字段留空。
 *  8. 空事件流 ⇒ 两个函数都返回 `[]`（调用方据此整块不渲染）。
 */

import type { BlueprintEvent } from '~/types/blueprint'
import { describe, expect, it } from 'vitest'
import {
  buildRepoPlanProgress,
  buildRouteFitness,
  buildStagePanorama,
  describeEventPayload,
  humanizeEnumToken,
  humanizePayloadEnums,
  PANORAMA_STAGES,
} from '~/utils/blueprintActivity'

function event(name: string, payload: Record<string, unknown>, ts: string): BlueprintEvent {
  return { id: `${name}-${ts}`, event: name, payload, ts }
}

const T1 = '2026-08-05T01:00:00+00:00'
const T2 = '2026-08-05T02:00:00+00:00'
const T3 = '2026-08-05T03:00:00+00:00'

describe('buildRouteFitness', () => {
  it('⭐ 合成分数与证据，按适配度降序', () => {
    const rows = buildRouteFitness([
      event('blueprint.route.scored', {
        candidates: [
          { repository_id: 'r-low', repository_name: 'low 仓', total: 0.42, charter_match: 0.1, history_match: 0.2, router_base: 0.3, confidence: 'low', role_suggestion: 'indirect' },
          { repository_id: 'r-top', repository_name: 'top 仓', total: 0.7987, charter_match: 0.5, history_match: 0.6, router_base: 0.9, confidence: 'high', role_suggestion: 'direct' },
        ],
      }, T1),
      event('blueprint.route.plan_drafted', {
        repositories: [
          { repository_id: 'r-top', matched_node_path_count: 3, matched_domain_count: 2, violated_boundary_count: 1, citation_ids: ['c1', 'c2'] },
        ],
      }, T2),
    ])

    expect(rows.map(row => row.repositoryId)).toEqual(['r-top', 'r-low'])
    const top = rows[0]
    expect(top.total).toBeCloseTo(0.7987)
    expect(top.roleSuggestion).toBe('direct')
    expect(top.breakdown.map(part => part.key)).toEqual(['charter_match', 'history_match', 'router_base'])
    expect(top.matchedNodePathCount).toBe(3)
    expect(top.citationCount).toBe(2)
    expect(top.violatedBoundaryCount).toBe(1)
    // plan_drafted 没覆盖的仓：证据计数为 0，⛔ 不是 undefined
    expect(rows[1].citationCount).toBe(0)
  })

  it('⭐ 重路由后只取最新一轮 scored（不把两轮候选混在一起）', () => {
    const rows = buildRouteFitness([
      event('blueprint.route.scored', {
        candidates: [{ repository_id: 'excluded', total: 0.9 }],
      }, T1),
      event('blueprint.route.scored', {
        candidates: [{ repository_id: 'fresh', total: 0.5 }],
      }, T3),
    ])

    expect(rows.map(row => row.repositoryId)).toEqual(['fresh'])
  })

  it('缺分数 ⇒ total 为 null 且排在有分数之后', () => {
    const rows = buildRouteFitness([
      event('blueprint.route.scored', {
        candidates: [
          { repository_id: 'no-score', repository_name: 'a' },
          { repository_id: 'scored', repository_name: 'b', total: 0.1 },
        ],
      }, T1),
    ])

    expect(rows.map(row => row.repositoryId)).toEqual(['scored', 'no-score'])
    expect(rows[1].total).toBeNull()
  })

  it('只有 plan_drafted（scored 丢了）也能出表', () => {
    const rows = buildRouteFitness([
      event('blueprint.route.plan_drafted', {
        repositories: [{ repository_id: 'r1', repository_name: 'r1 仓', total: 0.6, role_suggestion: 'direct' }],
      }, T1),
    ])

    expect(rows).toHaveLength(1)
    expect(rows[0].repositoryName).toBe('r1 仓')
    expect(rows[0].roleSuggestion).toBe('direct')
  })

  it('半可信 payload 不抛：candidates 非数组 / 条目非对象 / 分数类型错', () => {
    expect(() =>
      buildRouteFitness([
        event('blueprint.route.scored', { candidates: 'oops' }, T1),
        event('blueprint.route.plan_drafted', { repositories: [null, 42] }, T2),
      ]),
    ).not.toThrow()

    const rows = buildRouteFitness([
      event('blueprint.route.scored', { candidates: [{ repository_id: 'r', total: 'high' }] }, T1),
    ])
    expect(rows[0].total).toBeNull()
  })

  it('空事件流 ⇒ []', () => {
    expect(buildRouteFitness([])).toEqual([])
    expect(buildRouteFitness(undefined)).toEqual([])
  })
})

describe('buildRepoPlanProgress', () => {
  it('⭐ 三态排序：已产出 > 在跑 > 等依赖', () => {
    const rows = buildRepoPlanProgress([
      event('blueprint.repo_plan.repo_started', { repository_id: 'r-run', repository_name: 'run 仓', wave: 1 }, T1),
      event('blueprint.repo_plan.repo_started', { repository_id: 'r-done', repository_name: 'done 仓', wave: 1 }, T1),
      event('blueprint.repo_plan.repo_completed', { repository_id: 'r-done', item_count: 7, api_count: 2 }, T2),
      event('blueprint.repo_plan.repo_started', { repository_id: 'r-wait', repository_name: 'wait 仓', wave: 2 }, T1),
      event('blueprint.context.waiter_registered', { from_repository_id: 'r-wait', to_key: 'contract:x' }, T2),
    ])

    expect(rows.map(row => row.state)).toEqual(['done', 'running', 'waiting'])
    const done = rows[0]
    expect(done.itemCount).toBe(7)
    expect(done.apiCount).toBe(2)
    expect(done.wave).toBe(1)
  })

  it('⭐ 已产出的仓不被后续事件拉回进行中', () => {
    const rows = buildRepoPlanProgress([
      event('blueprint.repo_plan.repo_started', { repository_id: 'r', wave: 1 }, T1),
      event('blueprint.repo_plan.repo_completed', { repository_id: 'r', item_count: 1, api_count: 0 }, T2),
      event('blueprint.repo_plan.repo_started', { repository_id: 'r', wave: 2 }, T3),
    ])

    expect(rows[0].state).toBe('done')
  })

  it('⭐ 被重派的仓解除等待', () => {
    const rows = buildRepoPlanProgress([
      event('blueprint.repo_plan.repo_started', { repository_id: 'r', wave: 1 }, T1),
      event('blueprint.context.waiter_registered', { from_repository_id: 'r', to_key: 'contract:x' }, T2),
      event('blueprint.context.waiter_satisfied', { redispatch_repository_ids: ['r'], satisfied_count: 1 }, T3),
    ])

    expect(rows[0].state).toBe('running')
  })

  it('无 repository_id 的事件被忽略，不产生空行', () => {
    const rows = buildRepoPlanProgress([
      event('blueprint.repo_plan.wave_advanced', { wave: 1, total_waves: 2, repository_count: 3 }, T1),
      event('blueprint.repo_plan.repo_started', { repository_name: '没有 id' }, T2),
    ])

    expect(rows).toEqual([])
  })

  it('空事件流 ⇒ []', () => {
    expect(buildRepoPlanProgress([])).toEqual([])
    expect(buildRepoPlanProgress(undefined)).toEqual([])
  })
})

describe('describeEventPayload', () => {
  it('⭐ 标量与复合键分流：数组/对象被展开成可读行，⛔ 不只留键名', () => {
    const { fields, groups } = describeEventPayload({
      candidate_count: 2,
      router_version: 'repo_router_v2',
      auto_selected: true,
      weights_used: { charter: 0.4, history: 0.3 },
      candidates: [
        { repository_id: 'r1', repository_name: '数学仓', total: 0.8 },
        { repository_id: 'r2', repository_name: '语文仓', total: 0.42 },
      ],
    })

    expect(fields).toEqual([
      { key: 'candidate_count', value: '2' },
      { key: 'router_version', value: 'repo_router_v2' },
      { key: 'auto_selected', value: 'true' },
    ])

    const byKey = new Map(groups.map(group => [group.key, group]))
    expect(byKey.get('weights_used')?.lines).toEqual(['charter=0.400', 'history=0.300'])
    const candidates = byKey.get('candidates')
    expect(candidates?.count).toBe(2)
    expect(candidates?.lines[0]).toBe('repository_id=r1 · repository_name=数学仓 · total=0.800')
  })

  it('小数保留 3 位、整数原样（打分类字段全是 0–1 小数）', () => {
    const { fields } = describeEventPayload({ total: 1, score: 0.7987 })
    expect(fields).toEqual([
      { key: 'total', value: '1' },
      { key: 'score', value: '0.799' },
    ])
  })

  it('⚠️ 半可信 payload：null/空数组/空对象一律不产生行，且不抛', () => {
    const { fields, groups } = describeEventPayload({
      ok: 1,
      nothing: null,
      missing: undefined,
      emptyList: [],
      emptyObject: {},
      blank: '',
    })

    expect(fields).toEqual([{ key: 'ok', value: '1' }])
    expect(groups).toEqual([])
    expect(() => describeEventPayload(undefined)).not.toThrow()
  })

  it('超长数组只展开前若干项并标记截断', () => {
    const { groups } = describeEventPayload({
      items: Array.from({ length: 30 }, (_, index) => ({ id: `it_${index}` })),
    })

    expect(groups[0].count).toBe(30)
    expect(groups[0].lines).toHaveLength(12)
    expect(groups[0].truncated).toBe(true)
  })

  it('原始 JSON 可序列化输出（透明度兜底）', () => {
    expect(describeEventPayload({ item_count: 7 }).raw).toContain('"item_count": 7')
  })

  it('⭐ 人话键优先；关联 id / 内部置信度隐去（D-05）；缺键不渲染 undefined', () => {
    const { fields, raw } = describeEventPayload({
      task_id: 't-1',
      repository_id: 'r-1',
      repository_name: 'gaosan-web',
      research_reason: '主落点仓',
      routed_confidence: 'high',
      fitness_verdict: 'suitable',
      attempt: 2,
      blank: '',
      missing: undefined,
    })
    // ⛔ routed_confidence / repository_id / task_id 不进普通字段行
    expect(fields.map(f => f.key)).toEqual([
      'repository_name',
      'research_reason',
      'fitness_verdict',
      'attempt',
    ])
    expect(fields.every(f => f.value !== 'undefined')).toBe(true)
    // 但原始 JSON 折叠层仍原样保留（排障可查、关联键不丢）
    expect(raw).toContain('"routed_confidence"')
    expect(raw).toContain('"repository_id"')
    expect(raw).toContain('"task_id"')
  })
})

describe('humanizeEnumToken / humanizePayloadEnums', () => {
  it('置信度与适配结论翻中文；未知值原样', () => {
    expect(humanizeEnumToken('high')).toBe('高')
    expect(humanizeEnumToken('suitable')).toBe('适配')
    expect(humanizeEnumToken('custom')).toBe('custom')
    expect(humanizePayloadEnums({
      fitness_verdict: 'partial',
      routed_confidence: 'low',
      repository_name: 'A',
    })).toEqual({
      fitness_verdict: '部分适配',
      routed_confidence: '低',
      repository_name: 'A',
    })
  })
})

describe('buildStagePanorama', () => {
  it('⭐ 恒返八个节点，顺序与阶段时间线同源', () => {
    const nodes = buildStagePanorama([], '', '')
    expect(nodes.map(node => node.stage)).toEqual([...PANORAMA_STAGES])
    expect(nodes.map(node => node.index)).toEqual([1, 2, 3, 4, 5, 6, 7, 8])
    expect(nodes.every(node => node.events.length === 0)).toBe(true)
  })

  it('事件归到所属阶段，路由适配度与分仓进度各归其位', () => {
    const nodes = buildStagePanorama([
      event('blueprint.route.scored', {
        candidate_count: 1,
        candidates: [{ repository_id: 'r1', repository_name: '数学仓', total: 0.8 }],
      }, T1),
      event('blueprint.repo_plan.repo_started', { repository_id: 'r1', repository_name: '数学仓', wave: 1 }, T2),
      event('blueprint.repo_plan.repo_completed', { repository_id: 'r1', item_count: 5, api_count: 3 }, T3),
    ], '', '')

    const byStage = new Map(nodes.map(node => [node.stage, node]))
    expect(byStage.get('route')?.events.map(row => row.event)).toEqual(['blueprint.route.scored'])
    expect(byStage.get('route')?.fitness).toHaveLength(1)
    // ⭐ 适配度只挂路由阶段、分仓进度只挂分仓阶段 —— ⛔ 不在每张卡上重复渲染同一张表
    expect(byStage.get('route')?.repos).toEqual([])
    expect(byStage.get('repo_plan')?.repos).toHaveLength(1)
    expect(byStage.get('repo_plan')?.fitness).toEqual([])
    expect(byStage.get('repo_plan')?.repos[0].itemCount).toBe(5)
  })

  it('⭐ 固定路由：两条事件任一带 project_binding 即判定，且只标在路由阶段', () => {
    const nodes = buildStagePanorama([
      event('blueprint.route.plan_drafted', { router_version: 'project_binding', repositories: [] }, T1),
      event('blueprint.repo_plan.repo_started', { repository_id: 'r1', wave: 1 }, T2),
    ], '', '')

    const byStage = new Map(nodes.map(node => [node.stage, node]))
    expect(byStage.get('route')?.pinnedRoute).toBe(true)
    expect(byStage.get('repo_plan')?.pinnedRoute).toBe(false)
  })

  it('自动路由 ⇒ pinnedRoute 为 false', () => {
    const nodes = buildStagePanorama([
      event('blueprint.route.scored', { router_version: 'repo_router_v2', candidates: [] }, T1),
    ], '', '')

    expect(nodes.find(node => node.stage === 'route')?.pinnedRoute).toBe(false)
  })

  it('耗时取该阶段首末事件间隔；单条事件无耗时', () => {
    const single = buildStagePanorama([
      event('blueprint.review.started', { round: 1 }, T1),
    ], '', '')
    expect(single.find(node => node.stage === 'ai_review')?.durationMs).toBe(null)

    const spanned = buildStagePanorama([
      event('blueprint.review.started', { round: 1 }, T1),
      event('blueprint.review.completed', { round: 1, review_status: 'passed' }, T2),
    ], '', '')
    // T1 → T2 恰好一小时
    expect(spanned.find(node => node.stage === 'ai_review')?.durationMs).toBe(3_600_000)
  })

  it('摘要事实只出非空项（⛔ 缺失不显示成 0）', () => {
    const nodes = buildStagePanorama([
      event('blueprint.repo_plan.repo_started', { repository_id: 'r1', wave: 1 }, T1),
      event('blueprint.repo_plan.repo_completed', { repository_id: 'r1', item_count: 2, api_count: 1 }, T2),
    ], '', '')

    const facts = nodes.find(node => node.stage === 'repo_plan')?.facts ?? []
    expect(facts).toContainEqual({ key: 'repoPlanProgress', value: '1/1' })
    // 没发过 wave_advanced ⇒ 不出波次行
    expect(facts.some(fact => fact.key === 'waveProgress')).toBe(false)
  })

  it('调研阶段摘要给「完成/派发」进度与失败数', () => {
    const nodes = buildStagePanorama([
      event('blueprint.repo_research.started', { repository_id: 'a' }, T1),
      event('blueprint.repo_research.started', { repository_id: 'b' }, T1),
      event('blueprint.repo_research.completed', { repository_id: 'a' }, T2),
      event('blueprint.repo_research.failed', { repository_id: 'b', error_kind: 'timeout' }, T2),
    ], '', '')

    const node = nodes.find(item => item.stage === 'repo_research')
    expect(node?.facts).toContainEqual({ key: 'researchProgress', value: '1/2' })
    expect(node?.facts).toContainEqual({ key: 'researchFailed', value: '1' })
  })
})
