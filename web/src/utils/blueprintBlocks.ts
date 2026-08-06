/**
 * 蓝图 block 走查 / 取文本 / 指纹 / diff 的统一契约（Phase 115-02）。
 *
 * **本模块是前后端坐标系同源的唯一落点。** 各组件一律不得自行取块文本、自行走查段落、
 * 自行判 diff —— 三者只要与后端不一致，症状都是「不报错但结论悄悄错」。
 *
 * 全部调用点（后续五个 plan 直接照这里调）：
 * - `components/blueprint/BlueprintBlock.vue`：`blockText` 取切分坐标系；
 * - `components/blueprint/BlueprintBlockDiff.vue`：`classifyBlockDiff`；
 * - `composables/useBlueprintAnnotations.ts`：`iterBlocks` 建 blockId → sectionKey 索引；
 * - `composables/useBlueprintLive.ts`：`sectionKeyForEvent` / `stageForEvent` 派生段级进度；
 * - `components/knowledge/BlueprintsTabPanel.vue` 与预览弹层：`summaryText`。
 *
 * 后端同源依据（写代码前逐行读过，⛔ 不是凭 UI-SPEC 转述）：
 * - `server/delivery/services/blueprint_anchor.py:34-64` `_block_text`；
 * - `server/services/process_runtime/blueprint_schema.py:911-1060` `_item_key` / `iter_blocks`
 *   （13 处 `collect`）/ `_block_fingerprint` / `diff_blueprint_blocks`；
 * - `server/delivery/services/event_taxonomy.py:185-208` `BLUEPRINT_EVENTS`（21 个常量）。
 */

import type { BlueprintBlock, BlueprintEvent } from '~/types/blueprint'
import { ORCHESTRATION_SETTLED_BLUEPRINT_STATUSES } from '~/config/blueprintStatus'

/** `iterBlocks` 的产出条目：段路径 + 该路径所属的导航段 key + block 本体。 */
export interface IteratedBlock {
  /** 点分 + `[标识]`，如 `implementation_overview.items[impl_01].how`。 */
  sectionPath: string
  /** 该 block 归属的导航段（十段之一），供批注按段汇总与 badge 计数使用。 */
  sectionKey: string
  block: BlueprintBlock
}

/** block 级 diff 的三分类结果（各组 `block_id` 已排序，保证确定性）。 */
export interface BlockDiffResult {
  added: string[]
  removed: string[]
  modified: string[]
  /** 按导航段分组的三分类计数，供「未变化的段整段折叠」使用。 */
  bySection: Record<string, { added: string[], removed: string[], modified: string[] }>
}

/**
 * 取 block 的可比对纯文本 —— **批注 offset 的坐标系**。
 *
 * ⛔ **绝不按 `block.type` 分派，一律按字段优先级判定**（P-13，本相位最难逮的一类错）：
 * schema 对 `text` **没有任何类型约束**（只有一句 description），因此「`type: 'pseudocode'`
 * 且 `text` 非空字符串」这种块完全合法。若按 type 分派，pseudocode 会去取 `code.source`，
 * 而后端取的是 `text` ⇒ 两套坐标系不一致。**后果不是报错**：offset 偏移后**仍落在合法
 * 区间内** ⇒ 不触发越界降级、不报错、`<mark>` 照渲，只是**圈错了字** —— 评审看到一句被
 * 划线的话，而 AI 提问指的其实是另一句。
 *
 * 四分支优先级逐字复刻后端 `_block_text`：
 * 1. `text` 是**非空** string → 直取；
 * 2. `text` 是数组 → 逐项 `String()` 后 `'\n'` 连接（空数组也走这一支，得 `''`）；
 * 3. `code.source` 是**非空** string → 取它；
 * 4. `rows` 是数组 → 逐行扁平（行本身是数组则逐格 `String()`，否则整行 `String()`）后 `'\n'` 连接；
 * 5. 其余 → `''`。
 *
 * @example blockText({ block_id: 'b1', type: 'pseudocode', text: 'hi', code: { source: 'x' } }) // 'hi'
 */
export function blockText(block: unknown): string {
  if (block === null || typeof block !== 'object')
    return ''
  const raw = block as Record<string, unknown>

  const value = raw.text
  if (typeof value === 'string' && value)
    return value
  if (Array.isArray(value))
    return value.map(item => String(item)).join('\n')

  const code = raw.code
  if (code !== null && typeof code === 'object') {
    const source = (code as Record<string, unknown>).source
    if (typeof source === 'string' && source)
      return source
  }

  const rows = raw.rows
  if (Array.isArray(rows)) {
    const cells: string[] = []
    for (const row of rows) {
      if (Array.isArray(row))
        cells.push(...row.map(cell => String(cell)))
      else
        cells.push(String(row))
    }
    return cells.join('\n')
  }

  return ''
}

/**
 * 列表项的 `section_path` 索引：优先取标识字段值，缺失（`null` / `undefined` / `''`）回退
 * **位置下标字符串化**。逐字复刻后端 `_item_key`。
 */
export function itemKey(item: Record<string, unknown>, field: string, index: number): string {
  const value = item[field]
  if (value === null || value === undefined || value === '')
    return String(index)
  return String(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function asRecords(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

/**
 * 走查全部已知 Block[] 落位，返回 `(sectionPath, sectionKey, block)` 列表。
 *
 * **13 处 `collect` 与后端 `iter_blocks` 逐段对齐**（走查顺序、`section_path` 拼法、`_item_key`
 * 回退规则全部同款）。只收带**非空 `block_id`** 的 dict，逐字段防御，恒不抛。
 *
 * ⛔ `must_haves` / `decision_log` / `deferred_ideas` / `execution_plan` **不在走查里**（P-14）：
 * 后端 `iter_blocks` 对它们零 `collect` ⇒ 后端不会往那里挂线程。前端多走查它们只会凭空造出
 * 后端永远认不出的锚点。
 */
export function iterBlocks(content: unknown): IteratedBlock[] {
  const results: IteratedBlock[] = []
  if (!isRecord(content))
    return results

  const collect = (sectionKey: string, sectionPath: string, blocks: unknown): void => {
    if (!Array.isArray(blocks))
      return
    for (const block of blocks) {
      if (isRecord(block) && block.block_id)
        results.push({ sectionPath, sectionKey, block: block as unknown as BlueprintBlock })
    }
  }

  // 1) meta.summary（不占导航段，归到需求规格段的首屏摘要）
  const meta = content.meta
  if (isRecord(meta))
    collect('meta', 'meta.summary', meta.summary)

  // 2-4) requirement_spec
  const spec = content.requirement_spec
  if (isRecord(spec)) {
    collect('requirement_spec', 'requirement_spec.goal', spec.goal)
    collect('requirement_spec', 'requirement_spec.background', spec.background)
    asRecords(spec.feature_points).forEach((fp, idx) => {
      const key = itemKey(fp, 'id', idx)
      collect('requirement_spec', `requirement_spec.feature_points[${key}].description`, fp.description)
    })
  }

  // 5-9) repo_associations
  asRecords(content.repo_associations).forEach((assoc, idx) => {
    const base = `repo_associations[${itemKey(assoc, 'repository_id', idx)}]`
    const rationale = assoc.rationale
    if (isRecord(rationale))
      collect('repo_associations', `${base}.rationale.text`, rationale.text)
    collect('repo_associations', `${base}.responsibility`, assoc.responsibility)
    const fitness = assoc.fitness
    if (isRecord(fitness))
      collect('repo_associations', `${base}.fitness.reasons`, fitness.reasons)
    collect('repo_associations', `${base}.planned_change_summary`, assoc.planned_change_summary)
    collect('repo_associations', `${base}.support_needed`, assoc.support_needed)
  })

  // 10-11) current_state_analysis
  asRecords(content.current_state_analysis).forEach((analysis, idx) => {
    const base = `current_state_analysis[${itemKey(analysis, 'repository_id', idx)}]`
    collect('current_state_analysis', `${base}.summary`, analysis.summary)
    asRecords(analysis.findings).forEach((finding, fIdx) => {
      const key = itemKey(finding, 'id', fIdx)
      collect('current_state_analysis', `${base}.findings[${key}].text`, finding.text)
    })
  })

  // 12-16) implementation_overview
  const overview = content.implementation_overview
  if (isRecord(overview)) {
    collect(
      'implementation_overview',
      'implementation_overview.requirement_narrative',
      overview.requirement_narrative,
    )
    asRecords(overview.modules).forEach((module, idx) => {
      const key = itemKey(module, 'id', idx)
      collect('implementation_overview', `implementation_overview.modules[${key}].narrative`, module.narrative)
    })
    asRecords(overview.items).forEach((item, idx) => {
      const base = `implementation_overview.items[${itemKey(item, 'id', idx)}]`
      collect('implementation_overview', `${base}.how`, item.how)
      collect('implementation_overview', `${base}.existing_integration`, item.existing_integration)
      collect('implementation_overview', `${base}.test_strategy`, item.test_strategy)
    })
  }

  // 17-18) api_contracts
  asRecords(content.api_contracts).forEach((contract, idx) => {
    const base = `api_contracts[${itemKey(contract, 'id', idx)}]`
    collect('api_contracts', `${base}.description`, contract.description)
    const dataSource = contract.data_source
    if (isRecord(dataSource))
      collect('api_contracts', `${base}.data_source.notes`, dataSource.notes)
  })

  // 19-22) impact_analysis
  const impact = content.impact_analysis
  if (isRecord(impact)) {
    collect('impact_analysis', 'impact_analysis.business_impact', impact.business_impact)
    asRecords(impact.affected_features).forEach((feature, idx) => {
      const key = itemKey(feature, 'feature', idx)
      collect('impact_analysis', `impact_analysis.affected_features[${key}].description`, feature.description)
    })
    collect('impact_analysis', 'impact_analysis.compat_risks', impact.compat_risks)
    collect('impact_analysis', 'impact_analysis.rollback_plan', impact.rollback_plan)
  }

  // 23) interaction_flows
  asRecords(content.interaction_flows).forEach((flow, idx) => {
    const flowKey = itemKey(flow, 'id', idx)
    asRecords(flow.steps).forEach((step, sIdx) => {
      const stepKey = itemKey(step, 'seq', sIdx)
      collect('interaction_flows', `interaction_flows[${flowKey}].steps[${stepKey}].note`, step.note)
    })
  })

  return results
}

/** 递归按键排序，让 `JSON.stringify` 的输出与 Python 的 `sort_keys=True` 一致。 */
function canonicalize(value: unknown): unknown {
  if (Array.isArray(value))
    return value.map(canonicalize)
  if (isRecord(value)) {
    const sorted: Record<string, unknown> = {}
    for (const key of Object.keys(value).sort())
      sorted[key] = canonicalize(value[key])
    return sorted
  }
  return value
}

/**
 * block 的 canonical 指纹（与后端 `_block_fingerprint` 同源判据）。
 *
 * ⭐ **必须先递归排序键再序列化**：后端是 `json.dumps(block, sort_keys=True, ensure_ascii=False)`，
 * 而 JS 的 `JSON.stringify` **按属性插入顺序输出、不保证键序**。不做 canonical 化的话，
 * 「内容一字未改、只是键序不同」的块会被判成 `modified` ⇒ diff 面被噪声淹没，评审在一片
 * 假变更里找真变更。
 *
 * @example canonicalBlockFingerprint({ b: 1, a: 2 }) === canonicalBlockFingerprint({ a: 2, b: 1 })
 */
export function canonicalBlockFingerprint(block: unknown): string {
  return JSON.stringify(canonicalize(block))
}

/**
 * 两版本正文的 block 级 diff（按 `block_id` 对齐，三分类 + 按段分组）。
 *
 * 判据与后端 `diff_blueprint_blocks` 同款：仅 B 有 → `added`；仅 A 有 → `removed`；
 * 两者都有且 **canonical 指纹**不等 → `modified`。
 */
export function classifyBlockDiff(contentA: unknown, contentB: unknown): BlockDiffResult {
  const indexOf = (content: unknown): Map<string, IteratedBlock> => {
    const map = new Map<string, IteratedBlock>()
    for (const entry of iterBlocks(content))
      map.set(String(entry.block.block_id), entry)
    return map
  }
  const oldMap = indexOf(contentA)
  const newMap = indexOf(contentB)

  const added: string[] = []
  const removed: string[] = []
  const modified: string[] = []
  const bySection: BlockDiffResult['bySection'] = {}

  const bucket = (sectionKey: string) => {
    bySection[sectionKey] ??= { added: [], removed: [], modified: [] }
    return bySection[sectionKey]
  }

  for (const [blockId, entry] of newMap) {
    if (!oldMap.has(blockId)) {
      added.push(blockId)
      bucket(entry.sectionKey).added.push(blockId)
      continue
    }
    const before = canonicalBlockFingerprint(oldMap.get(blockId)!.block)
    if (before !== canonicalBlockFingerprint(entry.block)) {
      modified.push(blockId)
      bucket(entry.sectionKey).modified.push(blockId)
    }
  }
  for (const [blockId, entry] of oldMap) {
    if (!newMap.has(blockId)) {
      removed.push(blockId)
      bucket(entry.sectionKey).removed.push(blockId)
    }
  }

  const sortAll = (group: { added: string[], removed: string[], modified: string[] }) => {
    group.added.sort()
    group.removed.sort()
    group.modified.sort()
  }
  added.sort()
  removed.sort()
  modified.sort()
  Object.values(bySection).forEach(sortAll)

  return { added, removed, modified, bySection }
}

/**
 * 21 个 `BLUEPRINT_EVENTS` → 导航段 key 的映射（UI-SPEC §8.1 逐行）。
 *
 * 值为**数组**而非单值：`repo_research.*` 映射两段（一次容器调研同时产出 `fitness` 与
 * `findings`，两段在同一时刻都还空着；只映射一段会让另一段显示无信息的通用「调研中…」），
 * `spec_gate.locked` 同理映射两段。
 *
 * 空数组 = 该事件**不驱动任何段级进度**（确认门是面板不是正文段；AI 审查是跨段动作，映射
 * 到某一段等于谎报范围）—— 这五个事件只喂阶段时间线。
 */
const EVENT_SECTION_MAP: Record<string, string[]> = {
  'blueprint.status.transitioned': [],
  'blueprint.stage.started': [],
  'blueprint.stage.completed': [],
  'blueprint.stage.failed': [],
  'blueprint.spec_gate.scored': ['requirement_spec'],
  'blueprint.spec_gate.clarification_asked': ['requirement_spec'],
  'blueprint.spec_gate.locked': ['requirement_spec', 'decision_log'],
  'blueprint.route.scored': ['repo_associations'],
  'blueprint.repo_research.started': ['repo_associations', 'current_state_analysis'],
  'blueprint.repo_research.completed': ['repo_associations', 'current_state_analysis'],
  'blueprint.repo_research.failed': ['repo_associations', 'current_state_analysis'],
  'blueprint.reroute.triggered': ['repo_associations'],
  'blueprint.confirmation.opened': [],
  'blueprint.confirmation.action': [],
  'blueprint.confirmation.locked': [],
  'blueprint.context.entry_appended': ['implementation_overview'],
  'blueprint.context.waiter_registered': ['api_contracts'],
  'blueprint.context.waiter_satisfied': ['api_contracts'],
  'blueprint.review.started': [],
  'blueprint.review.completed': [],
  'blueprint.review.failed': [],
  // 118 活动流（LIVE-02/03）
  'blueprint.route.recalled': ['repo_associations'],
  'blueprint.route.plan_drafted': ['repo_associations'],
  // 检索命中是跨段的过程证据，映射到某一段等于谎报范围 ⇒ 只喂时间线与活动流
  'blueprint.retrieval.completed': [],
  'blueprint.repo_plan.repo_started': ['implementation_overview'],
  'blueprint.repo_plan.repo_completed': ['implementation_overview'],
  'blueprint.repo_plan.repo_failed': ['implementation_overview'],
  'blueprint.repo_plan.wave_advanced': ['implementation_overview'],
}

/** 事件名 → i18n 进度文案 key 尾段（`knowledge.blueprints.progress.<尾段>`）。 */
const EVENT_PROGRESS_KEY: Record<string, string> = {
  'blueprint.status.transitioned': 'statusTransitioned',
  'blueprint.stage.started': 'stageStarted',
  'blueprint.stage.completed': 'stageCompleted',
  'blueprint.stage.failed': 'stageFailed',
  'blueprint.spec_gate.scored': 'specGateScored',
  'blueprint.spec_gate.clarification_asked': 'specGateClarificationAsked',
  'blueprint.spec_gate.locked': 'specGateLocked',
  'blueprint.route.scored': 'routeScored',
  'blueprint.repo_research.started': 'repoResearchStarted',
  'blueprint.repo_research.completed': 'repoResearchCompleted',
  'blueprint.repo_research.failed': 'repoResearchFailed',
  'blueprint.reroute.triggered': 'rerouteTriggered',
  'blueprint.confirmation.opened': 'confirmationOpened',
  'blueprint.confirmation.action': 'confirmationAction',
  'blueprint.confirmation.locked': 'confirmationLocked',
  'blueprint.context.entry_appended': 'contextEntryAppended',
  'blueprint.context.waiter_registered': 'contextWaiterRegistered',
  'blueprint.context.waiter_satisfied': 'contextWaiterSatisfied',
  'blueprint.review.started': 'reviewStarted',
  'blueprint.review.completed': 'reviewCompleted',
  'blueprint.review.failed': 'reviewFailed',
  // 118 活动流：⭐ 这六条**刻意不配 `<key>Generic` 兜底文案** —— `eventLabel` 一旦发现
  // Generic 存在就优先用它（见 BlueprintStageStepper.eventLabel），叙事插值会被无参兜底
  // 顶掉。活动流的价值全在那几个数字上，兜底等于把它抹平成一句废话。
  'blueprint.route.recalled': 'routeRecalled',
  'blueprint.route.plan_drafted': 'routePlanDrafted',
  'blueprint.retrieval.completed': 'retrievalCompleted',
  'blueprint.repo_plan.repo_started': 'repoPlanRepoStarted',
  'blueprint.repo_plan.repo_completed': 'repoPlanRepoCompleted',
  'blueprint.repo_plan.repo_failed': 'repoPlanRepoFailed',
  'blueprint.repo_plan.wave_advanced': 'repoPlanWaveAdvanced',
}

/** 事件名 → 阶段（供阶段时间线聚合成八个节点）。 */
const EVENT_STAGE_MAP: Record<string, string> = {
  'blueprint.spec_gate.scored': 'spec_gate',
  'blueprint.spec_gate.clarification_asked': 'spec_gate',
  'blueprint.spec_gate.locked': 'spec_gate',
  'blueprint.route.scored': 'route',
  'blueprint.reroute.triggered': 'route',
  'blueprint.repo_research.started': 'repo_research',
  'blueprint.repo_research.completed': 'repo_research',
  'blueprint.repo_research.failed': 'repo_research',
  'blueprint.confirmation.opened': 'confirmation',
  'blueprint.confirmation.action': 'confirmation',
  'blueprint.confirmation.locked': 'confirmation',
  'blueprint.context.entry_appended': 'repo_plan',
  'blueprint.context.waiter_registered': 'merge',
  'blueprint.context.waiter_satisfied': 'merge',
  'blueprint.review.started': 'ai_review',
  'blueprint.review.completed': 'ai_review',
  'blueprint.review.failed': 'ai_review',
  // 118 活动流。⭐ `repo_plan.repo_completed` / `repo_started` 的后缀是 `_completed` /
  // `_started` 而**不是** `.completed` / `.started` ⇒ `buildStageTimeline` 的后缀判据
  // 不会把「一个仓产出完了」误判成「分仓阶段跑完了」。⛔ 重命名这两个事件前先看那条判据
  // （`test_blueprint_event_taxonomy_112` 与 blueprintBlocks 的用例各有一条守它）。
  'blueprint.route.recalled': 'route',
  'blueprint.route.plan_drafted': 'route',
  'blueprint.retrieval.completed': 'route',
  'blueprint.repo_plan.repo_started': 'repo_plan',
  'blueprint.repo_plan.repo_completed': 'repo_plan',
  'blueprint.repo_plan.repo_failed': 'repo_plan',
  'blueprint.repo_plan.wave_advanced': 'repo_plan',
}

/**
 * 阶段时间线的节点顺序（八节点）。
 *
 * ⭐ 与后端 `builtin_processes._TECHNICAL_BLUEPRINT_STAGES` 的转移图同序（116 重排）：
 * 拆解后先路由调研，规格门（澄清）在仓库集确认门**之后**、分仓方案之前。
 */
export const BLUEPRINT_STAGES: readonly string[] = [
  'route',
  'repo_research',
  'confirmation',
  'spec_gate',
  'repo_plan',
  'merge',
  'ai_review',
  'pending_review',
]

/** 21 个蓝图事件常量名（与后端 `BLUEPRINT_EVENTS` frozenset 逐字同集）。 */
export const BLUEPRINT_EVENT_NAMES: readonly string[] = Object.keys(EVENT_SECTION_MAP)

/**
 * 事件名 → 它驱动的导航段 key 列表；未映射 / 未知事件返回 `[]`。
 *
 * 返回的是**副本**，调用方改它不会污染映射表。
 */
export function sectionKeyForEvent(eventName: string): string[] {
  return [...(EVENT_SECTION_MAP[eventName] ?? [])]
}

/** 事件名 → 段级进度文案的 i18n key；未知事件返回 `''`（调用方回落状态级文案）。 */
export function progressKeyForEvent(eventName: string): string {
  const suffix = EVENT_PROGRESS_KEY[eventName]
  return suffix ? `knowledge.blueprints.progress.${suffix}` : ''
}

/**
 * 带插值的进度文案所需的 payload 键（缺任一即回落无参兜底）。
 *
 * ⚠️ **新增带 `{占位符}` 的进度文案必须在这里登记**（P-8：payload 的键 schema 层零保证）。
 * 漏登记的后果不是报错而是**静默出残句**：`t()` 把缺失的具名参数渲染成空串，于是
 * 「分仓方案已产出：{item_count} 项实现」上屏成「分仓方案已产出： 项实现」——句子还在、
 * 数字没了，看起来像埋点丢数据，实际是文案选错了分支。
 */
const PROGRESS_PARAMS: Record<string, readonly string[]> = {
  specGateClarificationAsked: ['question_count'],
  specGateLocked: ['decision_log_count'],
  routeScored: ['candidate_count'],
  repoResearchStarted: ['repository_name'],
  repoResearchCompleted: ['repository_name', 'fitness_verdict'],
  repoResearchFailed: ['repository_name', 'attempt'],
  rerouteTriggered: ['round'],
  contextEntryAppended: ['seq'],
  contextWaiterRegistered: ['to_key'],
  contextWaiterSatisfied: ['satisfied_count'],
  // 118 活动流：这六条此前漏登记 —— 它们的文案全都带插值。
  // ⚠️ 要列**文案里出现的每一个**占位符，不是只列「最重要那个」：漏列的那个照样渲染成空。
  routeRecalled: [
    'candidate_count',
    'router_candidate_count',
    'charter_supplement_count',
    'scope_repository_count',
  ],
  routePlanDrafted: ['repository_count'],
  retrievalCompleted: ['hit_count', 'top_score', 'matched_repository_count'],
  // quick-260806：started 事件改由派发漏斗发射，payload 带 repository_name、不再带 wave
  // （波次叙事归 wave_advanced）；failed 是同批新增的三元补齐事件。
  repoPlanRepoStarted: ['repository_name'],
  repoPlanRepoCompleted: ['item_count', 'api_count'],
  repoPlanRepoFailed: ['error'],
  repoPlanWaveAdvanced: ['wave', 'total_waves', 'repository_count'],
}

/**
 * 同一事件按 payload 判别式分文案：`<key>_<判别值>` 配了就优先用它。
 *
 * 为什么需要：`context.waiter_satisfied` 一个事件名承载**两种相反的事实** ——
 * `reason="key_available"` 是「契约上总线，等待正常解除」，`reason="expired"` 是
 * 「等超时了，强行放行」。两者都说成「跨仓接口已对齐」是实质误导：后者接口根本没等到。
 */
const PROGRESS_VARIANT_BY: Record<string, string> = {
  contextWaiterSatisfied: 'reason',
}

/**
 * 事件 + payload → 实际该用的进度文案 key（含判别式分支与无参兜底）。
 *
 * ⭐ **进度文案取键的唯一入口**：活动流全景、段级进度头、时间线都必须走它。各处自行
 * `te(generic) ? generic : key` 地判过一遍，就会出现「同一条事件在两个面板上文案不一样」
 * 这种没人能解释的差异。
 *
 * Returns:
 *   `{key, fallbackKey}`；`key` 是首选（可能是判别式变体或无参兜底），`fallbackKey`
 *   恒为无参兜底。未映射事件两者皆 `''`。
 */
export function resolveProgressKeys(
  eventName: string,
  payload: Record<string, unknown> | undefined,
): { key: string, fallbackKey: string } {
  const base = progressKeyForEvent(eventName)
  if (!base)
    return { key: '', fallbackKey: '' }
  const suffix = base.split('.').pop() ?? ''
  const generic = `${base}Generic`

  const discriminator = PROGRESS_VARIANT_BY[suffix]
  const variantValue = discriminator ? payload?.[discriminator] : undefined
  const variant = typeof variantValue === 'string' && variantValue ? `${base}_${variantValue}` : ''

  const required = PROGRESS_PARAMS[suffix]
  const complete
    = !required
      || required.every((name) => {
        const value = payload?.[name]
        return value !== undefined && value !== null && value !== ''
      })

  // 变体优先（它自带完整语义），其次按插值完整性在具体文案 / 无参兜底之间选。
  if (variant)
    return { key: variant, fallbackKey: generic }
  return { key: complete ? base : generic, fallbackKey: generic }
}

/** 事件名 → 阶段；未映射（如 `blueprint.status.transitioned`）返回 `''`。 */
export function stageForEvent(eventName: string): string {
  return EVENT_STAGE_MAP[eventName] ?? ''
}

/**
 * 会话 stage 名 → 时间线节点名的别名表。
 *
 * ⚠️ **两侧不是同一套命名**（后端 stage graph 见 `builtin_processes.py:850-960`）：会话侧是
 * `intake / decompose / spec_gate / route / repo_research / reroute / repo_confirmation /
 * repo_plan / merge / ai_review`，时间线侧把 `reroute` 并进 `route`、把 `repo_confirmation`
 * 叫 `confirmation`，并多一个后端根本没有的 `pending_review`。⛔ 不要「统一命名」——两侧
 * 各有各的既有消费方；漏了这张表的症状是 `indexOf` 返 `-1`、位序推断整条静默失效。
 */
const SESSION_STAGE_ALIASES: Record<string, string> = {
  repo_confirmation: 'confirmation',
  reroute: 'route',
}

/** 排在 `spec_gate` 之前的准备 stage：它们意味着一个时间线节点都还没走完。 */
const PRE_TIMELINE_SESSION_STAGES: ReadonlySet<string> = new Set(['intake', 'decompose'])

/** 会话 `current_stage` 在八节点里的位序；未知 / 尚未进入时间线返回 `-1`。 */
export function timelineIndexOfSessionStage(sessionStage: string): number {
  const raw = String(sessionStage ?? '')
  if (!raw || PRE_TIMELINE_SESSION_STAGES.has(raw))
    return -1
  return BLUEPRINT_STAGES.indexOf(SESSION_STAGE_ALIASES[raw] ?? raw)
}

/** 阶段节点的四态。 */
export type StageState = 'idle' | 'running' | 'done' | 'failed'

/** 阶段时间线的一个节点。 */
export interface StageTimelineNode {
  stage: string
  state: StageState
  events: BlueprintEvent[]
  /** 该 stage 下最新一条事件的 `ts`（无事件为 `''`）。 */
  latestTs: string
}

/**
 * 按 stage 聚合事件并推断八个节点的末态 —— **全相位唯一的一份实现**。
 *
 * ⭐ **末态不能只看事件名后缀**：把 `EVENT_STAGE_MAP` 按 stage 摊开会发现 `route` /
 * `repo_plan` / `merge` 三个阶段的**全部出边**都不以 `.completed` / `.locked` / `.failed`
 * 结尾（`route.scored` / `reroute.triggered` / `context.entry_appended` /
 * `context.waiter_registered` / `context.waiter_satisfied`）⇒ 只按后缀判，它们发过任何一条
 * 事件就永久钉在 `running`：一份早已 confirmed 的蓝图，时间线上仍有三个阶段转圈。
 *
 * 通用的 `blueprint.stage.started/.completed/.failed` 三个常量**全仓零 emit 点**
 * （`event_taxonomy.py:133` 自述「本相位仅定义常量」），所以补不出后端信号，只能用手上已有的
 * 两个：**会话位序**（走过 `current_stage` 的阶段必然已经走完）与**编排终态**
 * （`confirmed` / `implementing` / `implemented` / `archived` ⇒ 发过事件的阶段一律收成完成）。
 *
 * ⚠️ `.failed` 后缀**优先于**这两条推断：失败的阶段不得被位序收成「完成」。
 *
 * @param events 阶段事件（乱序无妨，函数内按 `ts` 排）。
 * @param currentStage `blueprint/events/` 的 `current_stage`（会话侧命名，走别名表换算）。
 * @param currentStatus 人审快照的 `current_status`（⛔ 前端不自行推断状态）。
 */
export function buildStageTimeline(
  events: readonly BlueprintEvent[] | undefined,
  currentStage: string,
  currentStatus: string,
): StageTimelineNode[] {
  const buckets = new Map<string, BlueprintEvent[]>()
  for (const event of events ?? []) {
    const stage = stageForEvent(event.event)
    if (!stage)
      continue
    const list = buckets.get(stage) ?? []
    list.push(event)
    buckets.set(stage, list)
  }

  const currentIndex = timelineIndexOfSessionStage(currentStage)
  const status = String(currentStatus ?? '')
  const settled = ORCHESTRATION_SETTLED_BLUEPRINT_STATUSES.has(status)
  // ⭐ `pending_review` 同样收敛前序阶段：它只能由 ai_review 的两条 __done__ 出边到达，
  // 走到这一步时前面的机器阶段必然都已跑完。不加这一条的症状（实测）：作答后的续驱被
  // 进程重启 / 请求取消打断，会话事件流永远停在 `spec_gate.clarification_asked`，而蓝图
  // 已由后续链路推到 `pending_review` ⇒ 「需求规格门」在一份等人终审的蓝图上永远转圈，
  // 文案还挂着「等待作答」——而那条澄清早已被回答并 resolved。
  // ⛔ 不把它并进 ORCHESTRATION_SETTLED 集合：该集合另有消费方（空节点不点亮），而
  // `pending_review` 下「待人类审查」节点本身仍需点亮为进行中。
  const collapseRunning = settled || status === 'pending_review'
  const currentNode = currentIndex >= 0 ? BLUEPRINT_STAGES[currentIndex] : ''

  return BLUEPRINT_STAGES.map((stage, index) => {
    const list = [...(buckets.get(stage) ?? [])].sort((a, b) =>
      String(a.ts).localeCompare(String(b.ts)))
    const latest = list.at(-1)
    let state: StageState = 'idle'
    if (latest) {
      if (latest.event.endsWith('.failed'))
        state = 'failed'
      else if (latest.event.endsWith('.completed') || latest.event.endsWith('.locked'))
        state = 'done'
      else
        state = 'running'
      // ⭐ `repo_research.started/.completed/.failed` 是**每仓**事件（四仓并行调研会各发
      // 一对），后缀判据在「第一个仓完成、其余仓还在跑」时会把整个调研阶段误判成 done
      // （用户实测点名：2/4 完成时时间线已显示「已完成」）。改用计数判据：started 数 >
      // 终态（completed+failed）数 ⇒ 仍在调研中。`repo_plan` 的每仓事件后缀是 `_completed`
      // 天然绕开后缀判据，无需同款处理（见 EVENT_STAGE_MAP 的注释）。
      // （本分支内 state 恒非 idle —— latest 存在时上面三支必落其一，无需再判。）
      if (stage === 'repo_research') {
        const startedCount = list.filter(e => e.event === 'blueprint.repo_research.started').length
        const terminalCount = list.filter(
          e => e.event === 'blueprint.repo_research.completed' || e.event === 'blueprint.repo_research.failed',
        ).length
        if (startedCount > 0 && terminalCount < startedCount)
          state = 'running'
      }
      if (state === 'running' && (collapseRunning || (currentIndex >= 0 && index < currentIndex)))
        state = 'done'
    }
    else if (!settled && (stage === currentNode || (stage === 'pending_review' && status === 'pending_review'))) {
      // 无事件的当前阶段仍要点亮；编排已确定走完时不再点亮任何空节点。
      state = 'running'
    }
    return { stage, state, events: list, latestTs: latest?.ts ?? '' }
  })
}

/**
 * `meta.summary` 首块的纯文本截断（列表卡与预览弹层共用同一口径）。
 *
 * 取第一个**非空**块的文本；超长按 `maxLen` 截断并补省略号。
 */
export function summaryText(blocks: unknown, maxLen = 200): string {
  if (!Array.isArray(blocks))
    return ''
  for (const block of blocks) {
    const text = blockText(block).trim()
    if (text)
      return text.length > maxLen ? `${text.slice(0, maxLen)}…` : text
  }
  return ''
}
