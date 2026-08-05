/**
 * 活动流派生的纯函数测试（Phase 119，LIVE-02/03）。
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
import { buildRepoPlanProgress, buildRouteFitness } from '~/utils/blueprintActivity'

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
