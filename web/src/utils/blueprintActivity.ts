/**
 * 活动流派生：把事件流折成「路由适配度」与「分仓每仓进度」两张可读视图（Phase 119，LIVE-02/03）。
 *
 * ⭐ **纯函数、零 Vue 依赖**：与 `blueprintBlocks` 的 `buildStageTimeline` 同一范式 ——
 * 派生逻辑必须能被单测直接喂事件数组，⛔ 不写进组件（那份逻辑一旦进组件就只能靠挂载测，
 * 而挂载测对「事件乱序 / 缺键 / 半可信 payload」这些真实情况覆盖不动）。
 *
 * ⚠️ **payload 的键 schema 层零保证**（P-8，与时间线同一前提）：逐键 `??` 与类型收窄，
 * 任何缺键都只让对应字段留空，⛔ 绝不抛错、⛔ 绝不因为一条脏事件让整张面板消失。
 */

import type { BlueprintEvent } from '~/types/blueprint'

/** 路由阶段：单个候选仓的适配度与证据（来自 `route.scored` + `route.plan_drafted`）。 */
export interface RouteFitnessRow {
  repositoryId: string
  repositoryName: string
  /** 加权总分（0–1）；缺失为 `null` ⇒ 调用方不显示百分比而不是显示 0%。 */
  total: number | null
  /** 三分量（章程 / 历史落点 / 路由器基分）；缺失键不出现。 */
  breakdown: Array<{ key: string, value: number }>
  roleSuggestion: string
  confidence: string
  /** 证据计数：命中的能力树节点 / 章程域 / 触碰的边界 / 引用条数。 */
  matchedNodePathCount: number
  matchedDomainCount: number
  violatedBoundaryCount: number
  citationCount: number
}

/** 分仓阶段：单个仓的执行位置与产出（来自 `repo_plan.*` + `context.*`）。 */
export interface RepoPlanProgressRow {
  repositoryId: string
  repositoryName: string
  /** `running` = 已派发未产出；`done` = 分仓方案已落库；`waiting` = 在等别的仓的契约。 */
  state: 'running' | 'done' | 'waiting'
  wave: number | null
  itemCount: number | null
  apiCount: number | null
  /** 该仓最近一条相关事件的 `ts`（排序与「多久没动静」用）。 */
  latestTs: string
}

const ROUTE_BREAKDOWN_KEYS = ['charter_match', 'history_match', 'router_base'] as const

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asCount(value: unknown): number {
  const parsed = asNumber(value)
  return parsed === null ? 0 : parsed
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function latestOf(events: readonly BlueprintEvent[], eventName: string): BlueprintEvent | undefined {
  let latest: BlueprintEvent | undefined
  for (const event of events) {
    if (event.event !== eventName)
      continue
    if (!latest || String(event.ts).localeCompare(String(latest.ts)) > 0)
      latest = event
  }
  return latest
}

/**
 * 路由适配度表：以**最新一条** `route.scored` 为骨架，用最新 `route.plan_drafted` 补角色与证据。
 *
 * ⭐ 取最新而非合并全部：重路由（`reroute`）会让同一会话出现多轮 `route.scored`，把它们
 * 合起来等于把已被排除的仓和新候选混在一张表里 —— 用户看到的是「候选变多了」而事实是
 * 「换了一批」。按 `ts` 取最新一轮是唯一正确口径。
 */
export function buildRouteFitness(events: readonly BlueprintEvent[] | undefined): RouteFitnessRow[] {
  const list = events ?? []
  const scored = latestOf(list, 'blueprint.route.scored')
  const drafted = latestOf(list, 'blueprint.route.plan_drafted')
  if (!scored && !drafted)
    return []

  const draftedById = new Map<string, Record<string, unknown>>()
  const draftedRows = (drafted?.payload?.repositories ?? []) as unknown
  if (Array.isArray(draftedRows)) {
    for (const row of draftedRows) {
      if (row && typeof row === 'object')
        draftedById.set(asText((row as Record<string, unknown>).repository_id), row as Record<string, unknown>)
    }
  }

  const scoredRows = scored?.payload?.candidates as unknown
  const fromScored = Array.isArray(scoredRows)
    ? scoredRows.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object')
    : []
  // ⭐ 骨架优先取 scored（它有三分量），**空则回落 plan_drafted** —— 打分事件可能丢
  // （emit 是 best-effort）或候选为空，此时仍应把初步方案渲染出来，⛔ 不整块消失。
  const source: Array<Record<string, unknown>> = fromScored.length > 0
    ? fromScored
    : [...draftedById.values()]

  const rows: RouteFitnessRow[] = source.map((row) => {
    const repositoryId = asText(row.repository_id)
    const extra = draftedById.get(repositoryId) ?? {}
    const citationIds = extra.citation_ids
    return {
      repositoryId,
      // 仓名两处都可能有（118 起 scored 也带），谁非空用谁
      repositoryName: asText(row.repository_name) || asText(extra.repository_name),
      total: asNumber(row.total) ?? asNumber(extra.total),
      breakdown: ROUTE_BREAKDOWN_KEYS.flatMap((key) => {
        const value = asNumber(row[key])
        return value === null ? [] : [{ key, value }]
      }),
      roleSuggestion: asText(row.role_suggestion) || asText(extra.role_suggestion),
      confidence: asText(row.confidence) || asText(extra.confidence),
      matchedNodePathCount: asCount(extra.matched_node_path_count),
      matchedDomainCount: asCount(extra.matched_domain_count),
      violatedBoundaryCount: asCount(extra.violated_boundary_count),
      citationCount: Array.isArray(citationIds) ? citationIds.length : 0,
    }
  })

  // 适配度降序（无分数的排最后），同分按仓名稳定排序
  return rows.sort((a, b) => {
    const left = a.total ?? -1
    const right = b.total ?? -1
    return right - left || a.repositoryName.localeCompare(b.repositoryName)
  })
}

/**
 * 分仓每仓进度表：按仓聚合 `repo_plan.repo_started` / `repo_completed` 与 waiter 事件。
 *
 * 状态判据（按优先级）：
 * 1. 出现过 `repo_completed` ⇒ `done`（产出已落库，后续事件不该把它拉回进行中）。
 * 2. 该仓在 `context.waiter_registered` 里且未 `satisfied` ⇒ `waiting`（在等别人的契约）。
 * 3. 否则 `running`（已派发、未产出）。
 *
 * ⚠️ waiter 的命中事件 `context.waiter_satisfied` 的 payload 带的是
 * `redispatch_repository_ids`（被重派的仓），不是登记时那个 key ⇒ 只能按「该仓是否出现在
 * 某条 satisfied 的重派清单里」解除等待。取不到就保守留在 `waiting`：显示「在等依赖」
 * 比显示「正在跑」更接近真相（它确实没在跑）。
 */
export function buildRepoPlanProgress(
  events: readonly BlueprintEvent[] | undefined,
): RepoPlanProgressRow[] {
  const rows = new Map<string, RepoPlanProgressRow>()
  const waiting = new Set<string>()
  const redispatched = new Set<string>()

  const sorted = [...(events ?? [])].sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
  for (const event of sorted) {
    const payload = event.payload ?? {}
    const repositoryId = asText(payload.repository_id) || asText(payload.from_repository_id)

    if (event.event === 'blueprint.context.waiter_registered' && repositoryId)
      waiting.add(repositoryId)

    if (event.event === 'blueprint.context.waiter_satisfied') {
      const ids = payload.redispatch_repository_ids
      if (Array.isArray(ids)) {
        for (const id of ids)
          redispatched.add(asText(id))
      }
      continue
    }

    if (!repositoryId)
      continue
    if (
      event.event !== 'blueprint.repo_plan.repo_started'
      && event.event !== 'blueprint.repo_plan.repo_completed'
      && event.event !== 'blueprint.context.waiter_registered'
    ) {
      continue
    }

    const existing = rows.get(repositoryId)
    const next: RepoPlanProgressRow = existing ?? {
      repositoryId,
      repositoryName: '',
      state: 'running',
      wave: null,
      itemCount: null,
      apiCount: null,
      latestTs: '',
    }
    next.repositoryName = asText(payload.repository_name) || next.repositoryName
    next.wave = asNumber(payload.wave) ?? next.wave
    next.latestTs = String(event.ts ?? '') || next.latestTs
    if (event.event === 'blueprint.repo_plan.repo_completed') {
      next.state = 'done'
      next.itemCount = asNumber(payload.item_count) ?? next.itemCount
      next.apiCount = asNumber(payload.api_count) ?? next.apiCount
    }
    rows.set(repositoryId, next)
  }

  for (const row of rows.values()) {
    if (row.state === 'done')
      continue
    if (waiting.has(row.repositoryId) && !redispatched.has(row.repositoryId))
      row.state = 'waiting'
  }

  // 已产出的排前面（它们是可读的结论），其余按最近活动倒序
  const order: Record<RepoPlanProgressRow['state'], number> = { done: 0, running: 1, waiting: 2 }
  return [...rows.values()].sort(
    (a, b) => order[a.state] - order[b.state] || String(b.latestTs).localeCompare(String(a.latestTs)),
  )
}
