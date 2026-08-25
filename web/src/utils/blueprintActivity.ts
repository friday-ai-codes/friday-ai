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
import type { StageState } from '~/utils/blueprintBlocks'
import { BLUEPRINT_STAGES, buildStageTimeline } from '~/utils/blueprintBlocks'

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

// ══════════════════════════════════════════════════════════════════════════
// 阶段全景（每个流程节点的全部过程信息）
// ══════════════════════════════════════════════════════════════════════════

/**
 * `router_version` 的固定路由受控值（后端 `repo_binding_pin.PINNED_ROUTER_VERSION`）。
 *
 * ⭐ 命中它意味着候选来自**项目手动绑定**、自动打分整段没跑 ⇒ `total` 恒 1.0、章程/历史
 * 分量与全部证据计数恒 0。这不是缺陷，但**必须在界面上标注**，否则那张全 0 的证据表
 * 看起来就像数据链路坏了（用户实测点名过这一点）。
 */
const PINNED_ROUTER_VERSION = 'project_binding'

/** 一条 payload 标量字段。`key` 是 payload 原始键名（组件负责翻译或原样 mono 显示）。 */
export interface PanoramaField {
  key: string
  value: string
}

/** payload 里的数组 / 对象键：展开成可读行，而不是只列键名。 */
export interface PanoramaGroup {
  key: string
  /** 数组长度 / 对象键数（`共 N 项` 用）。 */
  count: number
  /** 每项一行的紧凑摘要（已按 `MAX_GROUP_LINES` 截断）。 */
  lines: string[]
  /** `count` 超过 `lines.length`（被截断）时为真。 */
  truncated: boolean
}

/** 全景里的一条事件（标量 + 展开的复合键 + 原始 JSON 兜底）。 */
export interface PanoramaEventRow {
  id: string
  event: string
  ts: string
  fields: PanoramaField[]
  groups: PanoramaGroup[]
  /**
   * 原始 payload 本体，**供 i18n 叙事文案插值**。
   *
   * ⚠️ 必须原样带上：进度文案是 `分仓方案已产出：{item_count} 项实现、{api_count} 条接口契约`
   * 这种带命名占位符的句子，`t(key, payload)` 少了 payload 就渲染成
   * 「分仓方案已产出： 项实现、 条接口契约」——句子还在、数字全没了。
   * ⛔ 不要图省事只传派生出的 `fields`：那是 `{key,value}` 数组，键名对不上占位符。
   */
  payload: Record<string, unknown>
  /** 原始 payload JSON（缩进 2，有界截断）—— 透明度的最后一道兜底。 */
  raw: string
}

/** 阶段全景的一个节点：状态 + 耗时 + 摘要事实 + 全部事件明细。 */
export interface StagePanoramaNode {
  stage: string
  state: StageState
  /** 1-based 序号（界面上的「第几步」）。 */
  index: number
  events: PanoramaEventRow[]
  /** 该阶段最早 / 最晚事件的 `ts`（无事件为 `''`）。 */
  startedTs: string
  latestTs: string
  /** 首末事件间隔毫秒；无法计算（无事件 / 只有一条 / ts 非法）为 `null`。 */
  durationMs: number | null
  /** 摘要事实：`key` 是 `activity.fact.*` 的 i18n 尾段。 */
  facts: PanoramaField[]
  /** 仅 `route` 阶段非空：适配度表（复用既有派生）。 */
  fitness: RouteFitnessRow[]
  /** 仅 `repo_plan` 阶段非空：每仓进度表（复用既有派生）。 */
  repos: RepoPlanProgressRow[]
  /** 仅 `route` 阶段可能为真：固定路由（项目手动绑定），全 0 证据是事实而非缺陷。 */
  pinnedRoute: boolean
}

/**
 * 普通 UI 明细行**不显示**的 payload 键（D-05）。
 *
 * 这三个都是**关联 id / 内部置信度**：`routed_confidence` 是路由器内部标量（用户读了会误当成
 * 结论置信度）、`repository_id` / `task_id` 是排障用的 UUID。它们**只从明细字段行里隐去**，
 * ⛔ 不从 `raw` diagnostics 里删 —— 原始 JSON 折叠层仍原样保留，排障时可查、关联键不丢。
 * 按仓分组（`groupRepoResearchEvents`）也仍从原始 payload 读 `repository_id`，不受此表影响。
 */
export const NORMAL_UI_HIDDEN_PAYLOAD_KEYS: ReadonlySet<string> = new Set([
  'routed_confidence',
  'repository_id',
  'task_id',
])

/** 单个复合键最多展开多少行（超出只给计数，防止一个 200 项的数组把 DOM 撑爆）。 */
const MAX_GROUP_LINES = 12
/** 每项摘要最多取几个标量键（取前 N 个，保持行宽可读）。 */
const MAX_ITEM_KEYS = 4
/** 原始 JSON 的字符上界。 */
const MAX_RAW_CHARS = 4000

/** 过程明细标量字段：人话键优先，关联 id 殿后（UUID 仍保留可查）。 */
const PAYLOAD_FIELD_PRIORITY: readonly string[] = [
  'repository_name',
  'research_reason',
  'routed_confidence',
  'fitness_verdict',
  'verdict',
  'attempt',
  'role_suggestion',
  'findings_count',
  'error',
  'error_kind',
  'error_detail',
  'depth',
  'wave',
]

function payloadFieldRank(key: string): number {
  const idx = PAYLOAD_FIELD_PRIORITY.indexOf(key)
  if (idx >= 0)
    return idx
  if (key === 'task_id' || key === 'repository_id' || key.endsWith('_id'))
    return 10_000 + (key === 'repository_id' ? 0 : key === 'task_id' ? 1 : 2)
  return 500
}

/**
 * 把事件 payload 里常见的英文枚举翻成展示值（浅拷贝，不改原对象）。
 * 供标题插值与明细字段共用；未知值原样返回。
 */
export function humanizePayloadEnums(
  payload: Record<string, unknown> | undefined,
): Record<string, unknown> {
  if (!payload)
    return {}
  const out: Record<string, unknown> = { ...payload }
  for (const [key, value] of Object.entries(out)) {
    if (typeof value !== 'string')
      continue
    const mapped = humanizeEnumToken(value)
    if (mapped !== value)
      out[key] = mapped
  }
  return out
}

/** 单枚举 token → 中文（或原样）。与 `knowledge.blueprints.repo.fitness*` / activity 置信度文案对齐。 */
export function humanizeEnumToken(value: string): string {
  switch (value) {
    case 'high':
      return '高'
    case 'medium':
      return '中'
    case 'low':
      return '低'
    case 'suitable':
      return '适配'
    case 'partial':
      return '部分适配'
    case 'unsuitable':
      return '不适配'
    case 'true':
      return '是'
    case 'false':
      return '否'
    case 'retry':
      return '需要重审'
    case 'exhausted':
      return '重试已用尽'
    case 'passed':
      return '审查通过'
    case 'failed':
      return '审查失败'
    case 'direct':
      return '直接改造'
    case 'indirect':
      return '间接关联'
    case 'ready':
      return '已就绪'
    case 'degraded':
      return '产出不完整'
    case 'empty':
      return '无实现项'
    case 'needs_clarification':
      return '需要补充信息'
    case 'pending':
      return '等待中'
    case 'queued':
      return '排队中'
    case 'running':
      return '进行中'
    case 'completed':
    case 'done':
      return '已完成'
    case 'stale':
      return '已失效'
    case 'available':
      return '可用'
    case 'unavailable':
      return '不可用'
    case 'needs_support':
      return '需要协作仓支持'
    case 'warning':
      return '警告'
    case 'error':
      return '错误'
    case 'blocker':
      return '阻断问题'
    case 'info':
      return '提示'
    case 'repo_plan':
      return '各仓方案'
    case 'merge':
      return '方案合并'
    case 'ai_review':
      return 'AI 审查'
    case 'http':
      return 'HTTP 接口'
    case 'rpc':
      return 'RPC 接口'
    case 'event':
      return '事件'
    case 'mq':
      return '消息队列'
    case 'feature':
      return '功能需求'
    case 'bugfix':
      return '缺陷修复'
    case 'refactor':
      return '代码重构'
    default:
      return value
  }
}

/** 数值格式化：整数原样，小数保留 3 位（打分类字段全是 0–1 小数）。 */
function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(3)
}

/** 标量 → 字符串；非标量返回 `null`（调用方据此判定走 group 分支）。 */
function formatScalar(value: unknown): string | null {
  if (typeof value === 'string')
    return value
  if (typeof value === 'number')
    return Number.isFinite(value) ? formatNumber(value) : null
  if (typeof value === 'boolean')
    return value ? 'true' : 'false'
  return null
}

/** 一个数组项 / 对象 → 紧凑单行摘要（`k=v · k=v`）。非对象直接取标量。 */
function summarizeItem(item: unknown): string {
  const scalar = formatScalar(item)
  if (scalar !== null)
    return scalar
  if (Array.isArray(item))
    return `[${item.length}]`
  if (!item || typeof item !== 'object')
    return ''
  const parts: string[] = []
  for (const [key, value] of Object.entries(item as Record<string, unknown>)) {
    if (parts.length >= MAX_ITEM_KEYS)
      break
    const text = formatScalar(value)
    if (text === null || text === '')
      continue
    parts.push(`${key}=${text}`)
  }
  return parts.join(' · ')
}

/**
 * 把任意 payload 拆成「标量字段 + 展开的复合键 + 原始 JSON」。
 *
 * ⭐ 与已下线的 `BlueprintStageTimeline` 老口径的关键差别：**复合键要展开**。老时间线只列
 * 对象/数组的键名（`candidates repositories`），用户看得见「有这个键」却看不见里面是什么 ——
 * 而候选仓清单、每仓证据、接口契约恰恰都在那些键里，这正是「过程分析没东西」的由来。
 *
 * ⚠️ `payload` 的键 schema 层零保证（P-8）：逐值 `typeof` 收窄，任何形状都不抛错。
 * ⛔ 不做 `*_id` 过滤：全景的诉求就是公开透明，id 是排障的关联键；它们只在明细的
 * 折叠层里出现，不进摘要行。人话键排前、`*_id` 殿后。
 */
export function describeEventPayload(payload: Record<string, unknown> | undefined): {
  fields: PanoramaField[]
  groups: PanoramaGroup[]
  raw: string
} {
  const source = payload ?? {}
  const fields: PanoramaField[] = []
  const groups: PanoramaGroup[] = []

  for (const [key, value] of Object.entries(source)) {
    if (value === null || value === undefined)
      continue
    const scalar = formatScalar(value)
    if (scalar !== null) {
      // ⛔ 关联 id / 内部置信度不进普通字段行（D-05）；raw JSON 兜底仍带（见下方 stringify）。
      if (scalar !== '' && !NORMAL_UI_HIDDEN_PAYLOAD_KEYS.has(key))
        fields.push({ key, value: scalar })
      continue
    }
    let count: number
    let rawLines: string[]
    if (Array.isArray(value)) {
      count = value.length
      rawLines = value.slice(0, MAX_GROUP_LINES).map(item => summarizeItem(item))
    }
    else {
      const entries = Object.entries(value as Record<string, unknown>)
      count = entries.length
      rawLines = entries.slice(0, MAX_GROUP_LINES).map(([itemKey, itemValue]) => {
        const scalar = formatScalar(itemValue)
        return `${itemKey}=${scalar ?? summarizeItem(itemValue)}`
      })
    }
    if (count === 0)
      continue
    const lines = rawLines.filter(line => line !== '' && !line.endsWith('='))
    groups.push({ key, count, lines, truncated: count > MAX_GROUP_LINES })
  }

  fields.sort((a, b) => payloadFieldRank(a.key) - payloadFieldRank(b.key))

  let raw = ''
  try {
    raw = JSON.stringify(source, null, 2)
  }
  catch {
    // 循环引用等极端情况：原始视图降级为空，⛔ 绝不让一条脏 payload 炸掉整块面板
    raw = ''
  }
  if (raw.length > MAX_RAW_CHARS)
    raw = `${raw.slice(0, MAX_RAW_CHARS)}\n…`

  return { fields, groups, raw }
}

/** 该阶段下某事件名出现的次数。 */
function countOf(events: readonly BlueprintEvent[], name: string): number {
  return events.filter(event => event.event === name).length
}

/** 某事件名下出现过的唯一 `repository_id` 集合（重试 / 重派只计一次）。 */
function repositoryIdsForEvent(events: readonly BlueprintEvent[], name: string): Set<string> {
  const ids = new Set<string>()
  for (const event of events) {
    if (event.event !== name)
      continue
    const repositoryId = asText((event.payload ?? {}).repository_id)
    if (repositoryId)
      ids.add(repositoryId)
  }
  return ids
}

/** 多个集合的并集大小；事件窗口裁掉早期 started 时，completed/failed 仍进入分母。 */
function unionSize(...sets: ReadonlySet<string>[]): number {
  return new Set(sets.flatMap(set => [...set])).size
}

/** 取最新一条指定事件的某个 payload 标量（缺失返回 `''`）。 */
function latestField(events: readonly BlueprintEvent[], name: string, key: string): string {
  const event = latestOf(events, name)
  if (!event)
    return ''
  return formatScalar((event.payload ?? {})[key]) ?? ''
}

/**
 * 取最新一条指定事件的标量，按候选键顺序回退（兼容历史 emit 与 taxonomy 键名漂移）。
 *
 * 例：确认门一度 emit `repo_count`，taxonomy / 摘要事实读的是 `repository_count`。
 */
function latestFieldAny(
  events: readonly BlueprintEvent[],
  name: string,
  keys: readonly string[],
): string {
  const event = latestOf(events, name)
  if (!event)
    return ''
  const payload = event.payload ?? {}
  for (const key of keys) {
    const value = formatScalar(payload[key])
    if (value)
      return value
  }
  return ''
}

/** 往 facts 里推一条（值为空串一律跳过 ⇒ ⛔ 不把缺失显示成 0）。 */
function pushFact(facts: PanoramaField[], key: string, value: string): void {
  if (value !== '')
    facts.push({ key, value })
}

/**
 * 各阶段的摘要事实。
 *
 * ⭐ 只取**已在后端 emit 点核对过**的 payload 键（见 `event_taxonomy` 各常量上方的
 * payload 契约注释）。⛔ 不猜键名：猜错的症状是这一行永远不出现，比没有更难排查。
 */
function factsForStage(stage: string, events: readonly BlueprintEvent[]): PanoramaField[] {
  const facts: PanoramaField[] = []

  if (stage === 'route') {
    pushFact(facts, 'scopeRepositoryCount', latestField(events, 'blueprint.route.recalled', 'scope_repository_count'))
    pushFact(facts, 'candidateCount', latestField(events, 'blueprint.route.scored', 'candidate_count'))
    pushFact(facts, 'intent', latestField(events, 'blueprint.route.scored', 'intent'))
    pushFact(facts, 'charterSupplementCount', latestField(events, 'blueprint.route.scored', 'charter_supplement_count'))
    pushFact(facts, 'boundaryHitCount', latestField(events, 'blueprint.route.scored', 'unjustified_boundary_hit_count'))
    pushFact(facts, 'rerouteRound', latestField(events, 'blueprint.reroute.triggered', 'round'))
    pushFact(facts, 'retrievalHitCount', latestField(events, 'blueprint.retrieval.completed', 'hit_count'))
  }
  else if (stage === 'repo_research') {
    const started = repositoryIdsForEvent(events, 'blueprint.repo_research.started')
    const done = repositoryIdsForEvent(events, 'blueprint.repo_research.completed')
    const failed = repositoryIdsForEvent(events, 'blueprint.repo_research.failed')
    const total = unionSize(started, done, failed)
    const terminalFailed = [...failed].filter(repositoryId => !done.has(repositoryId)).length
    if (total > 0)
      pushFact(facts, 'researchProgress', `${done.size}/${total}`)
    if (terminalFailed > 0)
      pushFact(facts, 'researchFailed', String(terminalFailed))
  }
  else if (stage === 'confirmation') {
    pushFact(
      facts,
      'gateRepositoryCount',
      latestFieldAny(events, 'blueprint.confirmation.opened', ['repository_count', 'repo_count']),
    )
    pushFact(facts, 'actionCount', String(countOf(events, 'blueprint.confirmation.action') || ''))
    pushFact(
      facts,
      'lockedRepositoryCount',
      latestFieldAny(events, 'blueprint.confirmation.locked', [
        'locked_repository_count',
        'locked_repo_count',
      ]),
    )
    pushFact(facts, 'decidedBy', latestField(events, 'blueprint.confirmation.locked', 'decided_by'))
  }
  else if (stage === 'spec_gate') {
    pushFact(facts, 'weightedTotal', latestField(events, 'blueprint.spec_gate.scored', 'weighted_total'))
    pushFact(facts, 'threshold', latestField(events, 'blueprint.spec_gate.scored', 'threshold'))
    pushFact(facts, 'questionCount', latestField(events, 'blueprint.spec_gate.clarification_asked', 'question_count'))
    pushFact(facts, 'resolvedThreadCount', latestField(events, 'blueprint.spec_gate.locked', 'resolved_thread_count'))
    pushFact(facts, 'decisionLogCount', latestField(events, 'blueprint.spec_gate.locked', 'decision_log_count'))
  }
  else if (stage === 'repo_plan') {
    const started = repositoryIdsForEvent(events, 'blueprint.repo_plan.repo_started')
    const done = repositoryIdsForEvent(events, 'blueprint.repo_plan.repo_completed')
    const failed = repositoryIdsForEvent(events, 'blueprint.repo_plan.repo_failed')
    const total = unionSize(started, done, failed)
    const terminalFailed = [...failed].filter(repositoryId => !done.has(repositoryId)).length
    if (total > 0)
      pushFact(facts, 'repoPlanProgress', `${done.size}/${total}`)
    if (terminalFailed > 0)
      pushFact(facts, 'repoPlanFailed', String(terminalFailed))
    const wave = latestField(events, 'blueprint.repo_plan.wave_advanced', 'wave')
    const totalWaves = latestField(events, 'blueprint.repo_plan.wave_advanced', 'total_waves')
    if (wave !== '' && totalWaves !== '')
      pushFact(facts, 'waveProgress', `${wave}/${totalWaves}`)
    pushFact(facts, 'contextEntryCount', String(countOf(events, 'blueprint.context.entry_appended') || ''))
  }
  else if (stage === 'merge') {
    pushFact(facts, 'waiterRegistered', String(countOf(events, 'blueprint.context.waiter_registered') || ''))
    pushFact(facts, 'waiterSatisfied', String(countOf(events, 'blueprint.context.waiter_satisfied') || ''))
  }
  else if (stage === 'ai_review') {
    pushFact(facts, 'reviewRound', latestField(events, 'blueprint.review.completed', 'round'))
    pushFact(facts, 'reviewStatus', latestField(events, 'blueprint.review.completed', 'review_status'))
    pushFact(facts, 'reviewFailed', String(countOf(events, 'blueprint.review.failed') || ''))
  }

  return facts
}

/**
 * 两个 ISO8601 之间的毫秒差；任一非法、倒序或零跨度返回 `null`。
 *
 * ⭐ 零跨度也返 `null`：单条事件的阶段「无法测量耗时」≠「耗时 0ms」，后者会被读成
 * 「这一步瞬间就完了」。⛔ 不返 0。
 */
function durationBetween(from: string, to: string): number | null {
  const start = new Date(from).getTime()
  const end = new Date(to).getTime()
  if (Number.isNaN(start) || Number.isNaN(end) || end <= start)
    return null
  return end - start
}

/**
 * 有效活跃耗时：相邻事件间隔 ≤ `pauseThresholdMs` 才计入，更大间隔视为暂停
 * （等人澄清 / 跨夜挂起 / 会话失败后人工恢复）。
 *
 * ⭐ 首末墙钟差会把「等了 1 天」算进阶段耗时（实测把各仓方案显示成 1621m）。
 * 活跃耗时只累加连续工作片段，暂停不计入。
 */
export const STAGE_ACTIVE_PAUSE_THRESHOLD_MS = 30 * 60 * 1000

export function activeDurationMs(
  timestamps: readonly string[],
  pauseThresholdMs: number = STAGE_ACTIVE_PAUSE_THRESHOLD_MS,
): number | null {
  const times = timestamps
    .map(value => new Date(value).getTime())
    .filter(value => !Number.isNaN(value))
    .sort((a, b) => a - b)
  if (times.length < 2)
    return null
  let active = 0
  for (let index = 1; index < times.length; index += 1) {
    const gap = times[index]! - times[index - 1]!
    if (gap > 0 && gap <= pauseThresholdMs)
      active += gap
  }
  return active > 0 ? active : null
}

/**
 * 阶段全景：八个流程节点各自的状态、耗时、摘要事实与**全部**事件明细。
 *
 * ⭐ **状态推断与事件归属全部委托 `buildStageTimeline`**：那是全相位唯一的一份实现
 * （位序收敛 / 终态折叠 / 每仓事件计数判据都在里面）。⛔ 本函数不另写一份判据 ——
 * 那份副本一旦存在就会漂移，症状是「时间线说已完成、全景说还在跑」。
 *
 * @param events 阶段事件（乱序无妨）。
 * @param currentStage `blueprint/events/` 的 `current_stage`。
 * @param currentStatus 人审快照的 `current_status`。
 */
export function buildStagePanorama(
  events: readonly BlueprintEvent[] | undefined,
  currentStage: string,
  currentStatus: string,
): StagePanoramaNode[] {
  const list = events ?? []
  const fitness = buildRouteFitness(list)
  const repos = buildRepoPlanProgress(list)
  const pinnedRoute = [
    latestField(list, 'blueprint.route.plan_drafted', 'router_version'),
    latestField(list, 'blueprint.route.scored', 'router_version'),
  ].includes(PINNED_ROUTER_VERSION)

  return buildStageTimeline(list, currentStage, currentStatus).map((node, index) => {
    const startedTs = String(node.events[0]?.ts ?? '')
    const latestTs = String(node.latestTs ?? '')
    const eventTimestamps = node.events.map(event => String(event.ts ?? '')).filter(Boolean)
    const activeMs = activeDurationMs(eventTimestamps)
    const wallMs = startedTs && latestTs ? durationBetween(startedTs, latestTs) : null
    return {
      stage: node.stage,
      state: node.state,
      index: index + 1,
      startedTs,
      latestTs,
      // 活跃片段优先；若整段只有超阈值间隔（跨夜/等人），宁可不出耗时也不要用墙钟灌进「1621m」。
      durationMs: activeMs
        ?? (wallMs !== null && wallMs <= STAGE_ACTIVE_PAUSE_THRESHOLD_MS ? wallMs : null),
      facts: factsForStage(node.stage, node.events),
      fitness: node.stage === 'route' ? fitness : [],
      repos: node.stage === 'repo_plan' ? repos : [],
      pinnedRoute: node.stage === 'route' && pinnedRoute,
      events: node.events.map((event) => {
        const { fields, groups, raw } = describeEventPayload(event.payload)
        return {
          id: event.id,
          event: event.event,
          ts: String(event.ts ?? ''),
          payload: event.payload ?? {},
          fields,
          groups,
          raw,
        }
      }),
    }
  })
}

/** 全景节点顺序（= 时间线八节点，供测试与调用方对齐）。 */
export const PANORAMA_STAGES = BLUEPRINT_STAGES

// ══════════════════════════════════════════════════════════════════════════
// repo_research 按仓分组（Task 3，D-06）
// ══════════════════════════════════════════════════════════════════════════

/** 单个仓库的调研分组（started/completed/failed 折叠成一张卡片）。 */
export interface RepoResearchGroup {
  repositoryId: string
  repositoryName: string
  /** `done` = 出现过 completed；`failed` = 最后一次终态是 failed；否则 `running`（已派发未产出）。 */
  state: 'running' | 'done' | 'failed'
  /** started 事件里的 `research_reason`（取最新一条）；缺失为空串。 */
  reason: string
  /** started 次数（含重试）；0 表示只见到 completed/failed 而没抓到 started。 */
  attempts: number
  /** 该仓最近一条事件的 `ts`（排序与「多久没动静」用）。 */
  latestTs: string
  /** 归属本仓的全部过程事件（升序），供组内展开明细。 */
  events: PanoramaEventRow[]
}

/** repo_research 事件名（与后端 `event_taxonomy` 对齐）。 */
const REPO_RESEARCH_STARTED = 'blueprint.repo_research.started'
const REPO_RESEARCH_COMPLETED = 'blueprint.repo_research.completed'
const REPO_RESEARCH_FAILED = 'blueprint.repo_research.failed'

/**
 * 把 `repo_research` 节点的扁平事件流折成**按仓卡片**（D-06）。
 *
 * ⭐ 分组键取 `repository_id`（缺则 `repository_name`）：一个仓可能 started→failed→started→completed
 * 多轮重试，串行列表读起来是「同一个仓来回跳」，折成一张卡才看得清「这个仓最终成了没」。
 *
 * 状态判据：出现过 `completed` ⇒ `done`；否则看**最后一条终态**是 failed 还是（无终态）——
 * failed 且其后无 completed ⇒ `failed`；只 started 未见终态 ⇒ `running`。
 *
 * ⚠️ 入参是**已 describe 过的** `PanoramaEventRow[]`（`payload` 原样带在行上，见其 doc）——
 * 分组只读 `payload.repository_id/name/research_reason`，⛔ 不重算 fields（那是渲染层的事）。
 */
export function groupRepoResearchEvents(
  events: readonly PanoramaEventRow[] | undefined,
): RepoResearchGroup[] {
  const groups = new Map<string, RepoResearchGroup>()
  const order: string[] = []

  const sorted = [...(events ?? [])].sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
  for (const row of sorted) {
    if (
      row.event !== REPO_RESEARCH_STARTED
      && row.event !== REPO_RESEARCH_COMPLETED
      && row.event !== REPO_RESEARCH_FAILED
    ) {
      continue
    }
    const payload = row.payload ?? {}
    const repositoryId = asText(payload.repository_id)
    const repositoryName = asText(payload.repository_name)
    const key = repositoryId || repositoryName
    if (!key)
      continue

    let group = groups.get(key)
    if (!group) {
      group = {
        repositoryId,
        repositoryName: repositoryName || repositoryId,
        state: 'running',
        reason: '',
        attempts: 0,
        latestTs: '',
        events: [],
      }
      groups.set(key, group)
      order.push(key)
    }
    if (repositoryName)
      group.repositoryName = repositoryName
    group.events.push(row)
    group.latestTs = String(row.ts ?? '') || group.latestTs

    if (row.event === REPO_RESEARCH_STARTED) {
      group.attempts += 1
      const reason = asText(payload.research_reason)
      if (reason)
        group.reason = reason
      // started 不覆盖已到达的终态（重试的 started 出现在 completed/failed 之后时保留结论）
      if (group.state === 'running')
        group.state = 'running'
    }
    else if (row.event === REPO_RESEARCH_COMPLETED) {
      group.state = 'done'
    }
    else if (row.event === REPO_RESEARCH_FAILED) {
      // 已 done 的不因后来的 failed 回退（completed 是产出已落库的强信号）
      if (group.state !== 'done')
        group.state = 'failed'
    }
  }

  // 未产出的排前面（在途/失败的更需要关注），其余按最近活动倒序
  const rank: Record<RepoResearchGroup['state'], number> = { failed: 0, running: 1, done: 2 }
  return order
    .map(key => groups.get(key)!)
    .sort((a, b) => rank[a.state] - rank[b.state] || String(b.latestTs).localeCompare(String(a.latestTs)))
}
