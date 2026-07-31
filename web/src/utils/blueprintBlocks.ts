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

import type { BlueprintBlock } from '~/types/blueprint'

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
}

/** 阶段时间线的节点顺序（八节点）。 */
export const BLUEPRINT_STAGES: readonly string[] = [
  'spec_gate',
  'route',
  'repo_research',
  'confirmation',
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

/** 事件名 → 阶段；未映射（如 `blueprint.status.transitioned`）返回 `''`。 */
export function stageForEvent(eventName: string): string {
  return EVENT_STAGE_MAP[eventName] ?? ''
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
