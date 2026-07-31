/**
 * 编排过程时间线：把「一份运行时快照 + 一条事件流」折叠成用户看得懂的六步（+ 可选第七步）时间线。
 *
 * 本模块是**纯 TS**：不 import vue / pinia / store / api，无响应式、无请求、无 DOM。
 * 这样做有两个理由，都不是风格偏好：
 * 1. 本 phase 用户可见的正确性全部落在这段逻辑里（阶段指针取谁、classify 出不出现、
 *    澄清算不算跳过、调研分母取哪个数、单仓失败算不算整体失败、重复事件会不会让计数翻倍）。
 *    埋在组件里意味着每条规则只能靠挂 DOM 验证，而 DOM 断言天然松。
 * 2. 「观测代码不反噬业务」在结构上成立：整个入口包一层 try/catch，任何解析异常降级为
 *    保守视图，绝不向上抛。
 *
 * 输入的 `payload` 是**半可信结构**：类型上的 `Record<string, unknown>` 不是运行时保证
 * （110-04 交棒结论）。所有读取都是纯字面的，不对 `undefined` 做属性访问链。
 */

import type { OrchestrationRuntime, OrchestrationStageKey } from '~/types/chat'
import type { TimelineStepItem } from '~/types/execution'

// ============================================================================
// 常量
// ============================================================================

/**
 * 编排内部 stage key 的**完整** 7 键有序数组。
 *
 * 🔴 阶段序号一律在这份完整数组上计算，可见性过滤是最后一步。
 * 若先把 classify 删掉再算序号，后续步骤会整体错位一格——症状是「融合已经在跑，
 * 界面上还显示在调研」。
 */
export const STAGE_ORDER: OrchestrationStageKey[] = [
  'decompose',
  'route',
  'recall',
  'classify',
  'clarify',
  'research',
  'merge',
]

/**
 * 用户面标签。前六个取 ROADMAP SC-1 的原文措辞（拆分 / 路由 / 召回 / 澄清 / 并行调研 / 融合），
 * 不另造词；`功能点分类` 是本 phase 新增的第七个词——它是 feature_list 专属扩展点，
 * 六词表本就没覆盖它。
 */
export const STAGE_LABELS: Record<OrchestrationStageKey, string> = {
  decompose: '拆分',
  route: '路由',
  recall: '召回',
  classify: '功能点分类',
  clarify: '澄清',
  research: '并行调研',
  merge: '融合',
}

/**
 * 失败原因闭集（恰 6 键）。
 *
 * 🔴 未命中一律回退 `COPY.unknownReason`，**绝不回显原始取值**：上游是异常分类，
 * 一旦出现非受控值（异常类名、截断的上游 body），回显即泄漏面。
 */
export const FAIL_REASON_LABELS: Record<string, string> = {
  stage_exception: '该阶段执行出错',
  merge_validation_exhausted: '融合校验多次未通过',
  clarification_timeout_no_answer: '澄清超时且无人应答',
  advance_step_limit: '流程推进步数超限',
  unknown_process_type: '流程类型未注册',
  unknown_stage: '阶段未注册',
}

/**
 * 转移事件名 → 该事件把会话推进到的目标 stage。
 *
 * 🔴 表里存在**回退**转移（融合校验不过会退回 clarify 或 research）。因此临时指针必须取
 * 「按 ts 排序后**最后一条**可识别转移事件」的目标，而不是「见过的最大序号」——后者在
 * 回退后会把时间线卡在 merge，而会话实际已经回到 clarify，那正是「时间线撒谎」。
 *
 * `process.session.failed` / `fail` 不在表内：它们不推进 stage，只翻状态。
 */
export const TRANSITION_TO_STAGE: Record<string, OrchestrationStageKey> = {
  decomposed: 'route',
  routed: 'recall',
  recalled: 'classify',
  classified: 'clarify',
  clarified: 'research',
  needs_clarification: 'clarify',
  research_dispatched: 'research',
  research_complete: 'merge',
  merged: 'merge',
  validation_failed_reclarify: 'clarify',
  validation_failed_reresearch: 'research',
  exhausted: 'merge',
}

/**
 * 全部用户可见文案。沿用本组件家族硬编码中文常量的惯例（`TOOL_LABELS` /
 * `OrchestratedPlanCard.COPY` 先例），**不接 vue-i18n**。
 */
export const COPY = {
  titleRunning: '正在生成技术方案',
  titleDone: '方案编排已完成',
  titleFailed: '方案编排失败',
  /** 卡头步数计数。🔴 这个串**不得**进 live region（见 `liveRunning` 的注释）。 */
  stepCount: (done: number, total: number) => `${done}/${total} 步`,
  /**
   * live region 三句。
   * 🔴 只反映「活跃阶段 / 会话状态」，**绝不**把调研的 `{done}/{total}` 计数写进来——
   * 五个仓完成会让屏幕阅读器连播五次。
   */
  liveRunning: (label: string) => `当前阶段：${label}`,
  liveDone: '方案编排已完成',
  liveFailed: (label: string, reason: string) => `编排失败：${label} — ${reason}`,
  unknownRepo: '未知仓库',
  unknownReason: '未知原因',
  degradedBadge: '降级',
  interrupted: '进度未知，可能已中断',
  summaryDecompose: (n: number) => `已拆出 ${n} 个需求点`,
  summaryRoute: (n: number) => `命中 ${n} 个候选仓`,
  summaryRecall: (n: number) => `召回 ${n} 条相关知识`,
  summaryClassify: (added: number, modified: number) => `新增 ${added} · 改造 ${modified}`,
  summaryClassifyUnclear: (n: number) => ` · 待确认 ${n}`,
  clarifyWaiting: (round: number) => `等待你回答第 ${round} 轮澄清`,
  clarifyAnswered: (round: number) => `第 ${round} 轮澄清已回答`,
  clarifyTimedOut: (round: number) => `第 ${round} 轮澄清超时，已按假设继续`,
  clarifyDeliveryFailed: '澄清卡送达失败',
  clarifySkipped: '本次无需澄清',
  summaryResearch: (done: number, total: number) => `${done}/${total} 个仓库完成`,
  summaryResearchFailed: (n: number) => ` · ${n} 个失败`,
  mergeRunning: '正在融合各仓方案',
  mergeRound: (n: number) => `第 ${n} 轮融合`,
  mergeDone: '方案已产出',
} as const

// ============================================================================
// 对外契约
// ============================================================================

export interface OrchestrationTimelineEvent {
  event: string
  ts: string
  payload?: Record<string, unknown>
}

export interface OrchestrationTimelineInput {
  snapshot: OrchestrationRuntime | null
  events: OrchestrationTimelineEvent[]
  /** `runtime.active` —— 中断判定用。 */
  runtimeActive: boolean
  /** `repository_id → 仓库名`；解析不出时回退 `COPY.unknownRepo`。 */
  repoNames?: Record<string, string>
}

export interface OrchestrationTimelineView {
  steps: TimelineStepItem[]
  /** 决定卡头标题与是否自动折叠。 */
  phase: 'running' | 'done' | 'failed'
  title: string
  doneCount: number
  totalCount: number
  /** 单一 live region 的内容。 */
  liveMessage: string
}

/**
 * 仓库名解析。**任何情况下不回显裸 UUID**——解析不出就回退常量。
 * 导出供 110-07 的调研日志组复用，避免两处各写一份兜底。
 */
export function resolveRepoName(repoId: string, repoNames?: Record<string, string>): string {
  const name = repoNames?.[repoId]
  return typeof name === 'string' && name.length > 0 ? name : COPY.unknownRepo
}

// ============================================================================
// 防御性读取工具
// ============================================================================

/** payload 可能是 `null` / 字符串 / 数组（110-04 明确：类型不是运行时保证）。 */
function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value))
    return null
  return value as Record<string, unknown>
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asNonEmptyString(value: unknown): string | null {
  return typeof value === 'string' && value.length > 0 ? value : null
}

/**
 * 去重用的自然键：优先取 payload 上指定的自然键（`repo_id` / `clarification_id`），
 * 缺失时退回信封 `ts`。
 *
 * 🔴 这是「计数幂等」的落点：同一自然键无论投递几次、ts 是否不同，都只算一次。
 */
function naturalKey(payload: Record<string, unknown> | null, field: string, ts: string): string {
  const value = payload ? asNonEmptyString(payload[field]) : null
  return value ?? ts
}

// ============================================================================
// 事件折叠
// ============================================================================

type ClarifyKind = 'asked' | 'answered' | 'timed_out' | 'delivery_failed'

interface FoldedEvents {
  researchStarted: Set<string>
  researchCompleted: Set<string>
  researchFailed: Set<string>
  clarifyAsked: Set<string>
  clarifyAnswered: Set<string>
  /** `technical_plan.merge.started` 无自然键 ⇒ 按 `ts` 去重（裁定 F-16b）。 */
  mergeStartedKeys: Set<string>
  mergeCompleted: boolean
  lastClarifyKind: ClarifyKind | null
  lastClarifyRound: number | null
  sawClarification: boolean
  sawClassifyEvent: boolean
  routingPayload: Record<string, unknown> | null
  recallPayload: Record<string, unknown> | null
  classifyPayload: Record<string, unknown> | null
  /** 最后一条**可识别**转移事件指向的 stage；不认识的事件名静默忽略。 */
  lastTransitionStage: OrchestrationStageKey | null
  /**
   * 见过会话失败事件。
   *
   * 🔴 这是快照缺席时唯一的失败证据。前半程（拆分→澄清）走 SSE 直播，
   * `pollConversationRuntime` 尚未被调度，桶里的 snapshot 恒为 null——不认这个事件
   * 就会把出错那一步一直画成进行中、标题一直是「正在生成技术方案」，只有刷新页面
   * 才自愈。
   */
  sawSessionFailed: boolean
}

function foldEvents(events: OrchestrationTimelineEvent[]): FoldedEvents {
  const folded: FoldedEvents = {
    researchStarted: new Set(),
    researchCompleted: new Set(),
    researchFailed: new Set(),
    clarifyAsked: new Set(),
    clarifyAnswered: new Set(),
    mergeStartedKeys: new Set(),
    mergeCompleted: false,
    lastClarifyKind: null,
    lastClarifyRound: null,
    sawClarification: false,
    sawClassifyEvent: false,
    routingPayload: null,
    recallPayload: null,
    classifyPayload: null,
    lastTransitionStage: null,
    sawSessionFailed: false,
  }

  const usable = (Array.isArray(events) ? events : [])
    .filter(item => !!item && typeof item === 'object' && typeof item.event === 'string')
    .map(item => ({ event: item.event, ts: typeof item.ts === 'string' ? item.ts : '', payload: asRecord(item.payload) }))

  // Array#sort 稳定：ts 相同的事件保持到达顺序。
  const sorted = [...usable].sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0))

  for (const { event, ts, payload } of sorted) {
    // 转移事件：只认表里的名字，其余静默忽略（不打 warn、不产出任何文案）。
    const target = TRANSITION_TO_STAGE[event]
    if (target)
      folded.lastTransitionStage = target

    if (event.startsWith('clarification.'))
      folded.sawClarification = true

    // 两个名字都认：`process.session.failed` 是分类事件，`fail` 是状态图转移名。
    if (event === 'process.session.failed' || event === 'fail')
      folded.sawSessionFailed = true

    switch (event) {
      case 'repo.routing':
        folded.routingPayload = payload
        break
      case 'knowledge.recalling':
        folded.recallPayload = payload
        break
      case 'technical_plan.feature.classified':
        folded.sawClassifyEvent = true
        folded.classifyPayload = payload
        break
      case 'repo.research.started':
        folded.researchStarted.add(naturalKey(payload, 'repo_id', ts))
        break
      case 'repo.research.completed':
        folded.researchCompleted.add(naturalKey(payload, 'repo_id', ts))
        break
      case 'repo.research.failed':
        folded.researchFailed.add(naturalKey(payload, 'repo_id', ts))
        break
      case 'clarification.asked':
        folded.clarifyAsked.add(naturalKey(payload, 'clarification_id', ts))
        folded.lastClarifyKind = 'asked'
        break
      case 'clarification.answered':
        folded.clarifyAnswered.add(naturalKey(payload, 'clarification_id', ts))
        folded.lastClarifyKind = 'answered'
        break
      case 'clarification.timed_out':
        folded.lastClarifyKind = 'timed_out'
        folded.lastClarifyRound = payload ? asFiniteNumber(payload.round_no) : null
        break
      case 'clarification.delivery_failed':
        folded.lastClarifyKind = 'delivery_failed'
        break
      case 'technical_plan.merge.started':
        folded.mergeStartedKeys.add(ts)
        break
      case 'technical_plan.merge.completed':
        folded.mergeCompleted = true
        break
      default:
        break
    }
  }

  return folded
}

// ============================================================================
// 各阶段摘要
// ============================================================================

function decomposeSummary(snapshot: OrchestrationRuntime | null): string | undefined {
  const count = asFiniteNumber(snapshot?.segment_count)
  return count === null ? undefined : COPY.summaryDecompose(count)
}

function routeSummary(folded: FoldedEvents): string | undefined {
  const candidates = folded.routingPayload?.candidates
  return Array.isArray(candidates) ? COPY.summaryRoute(candidates.length) : undefined
}

function recallSummary(folded: FoldedEvents): string | undefined {
  const hits = folded.recallPayload ? asFiniteNumber(folded.recallPayload.hits) : null
  return hits === null ? undefined : COPY.summaryRecall(hits)
}

function classifySummary(folded: FoldedEvents): string | undefined {
  const bucket = asRecord(folded.classifyPayload?.summary)
  if (!bucket)
    return undefined
  const added = asFiniteNumber(bucket.new)
  const modified = asFiniteNumber(bucket.modify)
  if (added === null || modified === null)
    return undefined
  const unclear = asFiniteNumber(bucket.unclear) ?? 0
  const base = COPY.summaryClassify(added, modified)
  return unclear > 0 ? base + COPY.summaryClassifyUnclear(unclear) : base
}

function clarifySummary(folded: FoldedEvents, status: TimelineStepItem['status']): string | undefined {
  if (status === 'skipped')
    return COPY.clarifySkipped
  switch (folded.lastClarifyKind) {
    case 'delivery_failed':
      return COPY.clarifyDeliveryFailed
    case 'timed_out':
      return COPY.clarifyTimedOut(folded.lastClarifyRound ?? folded.clarifyAsked.size)
    case 'answered':
      return COPY.clarifyAnswered(folded.clarifyAnswered.size || folded.clarifyAsked.size)
    case 'asked':
      return COPY.clarifyWaiting(folded.clarifyAsked.size)
    default:
      return undefined
  }
}

function researchSummary(folded: FoldedEvents): string | undefined {
  // 🔴 分母取**实际派了容器**的去重 repo 数，不取路由候选数：light path 的仓不起容器，
  // 用候选数当分母会让进度永远到不了满。
  const total = folded.researchStarted.size
  if (total === 0)
    return undefined
  const base = COPY.summaryResearch(folded.researchCompleted.size, total)
  const failed = folded.researchFailed.size
  return failed > 0 ? base + COPY.summaryResearchFailed(failed) : base
}

function mergeSummary(folded: FoldedEvents): string | undefined {
  if (folded.mergeCompleted)
    return COPY.mergeDone
  const rounds = folded.mergeStartedKeys.size
  if (rounds >= 2)
    return COPY.mergeRound(rounds)
  return rounds === 1 ? COPY.mergeRunning : undefined
}

function stageSummary(
  stage: OrchestrationStageKey,
  status: TimelineStepItem['status'],
  snapshot: OrchestrationRuntime | null,
  folded: FoldedEvents,
): string | undefined {
  switch (stage) {
    case 'decompose':
      return decomposeSummary(snapshot)
    case 'route':
      return routeSummary(folded)
    case 'recall':
      return recallSummary(folded)
    case 'classify':
      return classifySummary(folded)
    case 'clarify':
      return clarifySummary(folded, status)
    case 'research':
      return researchSummary(folded)
    case 'merge':
      return mergeSummary(folded)
    default:
      return undefined
  }
}

// ============================================================================
// 主函数
// ============================================================================

function conservativeView(): OrchestrationTimelineView {
  const steps: TimelineStepItem[] = STAGE_ORDER
    .filter(stage => stage !== 'classify')
    .map(stage => ({ id: stage, name: STAGE_LABELS[stage], status: 'pending' as const }))
  return {
    steps,
    phase: 'running',
    title: COPY.titleRunning,
    doneCount: 0,
    totalCount: steps.length,
    liveMessage: COPY.liveRunning(STAGE_LABELS[STAGE_ORDER[0]]),
  }
}

export function buildOrchestrationTimeline(input: OrchestrationTimelineInput): OrchestrationTimelineView {
  try {
    return buildInner(input)
  }
  catch {
    // 观测代码不反噬业务：任何解析异常降级为保守视图，不抛、不 warn。
    return conservativeView()
  }
}

function buildInner(input: OrchestrationTimelineInput): OrchestrationTimelineView {
  const snapshot = input?.snapshot ?? null
  const folded = foldEvents(input?.events ?? [])

  const status = typeof snapshot?.status === 'string' ? snapshot.status : null
  /**
   * 🔴 快照缺席时用失败事件兜底。
   *
   * 快照在场时**仍以快照为准**（与阶段指针同一条权威顺序），事件不得翻转它；
   * 只有 `status === null`（前半程 SSE 直播期间，轮询未起）才认事件。不加这一支，
   * 前半程失败会让时间线一直显示「正在生成技术方案」并把出错那步画成进行中。
   */
  const isFailed = status === 'failed' || (status === null && folded.sawSessionFailed)
  const isDone = status === 'done'

  // ---- 阶段指针（权威顺序：快照 → 最后一条可识别转移事件 → 无证据） ----
  // 冲突时以快照为准，且不打 warn、不报错：事件截断与时序是正常场景，不是异常。
  const rawStage = asNonEmptyString(snapshot?.current_stage) ?? ''
  const snapshotStage = (STAGE_ORDER as string[]).includes(rawStage)
    ? (rawStage as OrchestrationStageKey)
    : null
  const pointerStage = snapshotStage ?? folded.lastTransitionStage
  // 一条证据都没有时不点亮任何步骤（全 pending），而不是假装「拆分正在跑」。
  const pointerIndex = pointerStage ? STAGE_ORDER.indexOf(pointerStage) : -1

  // ---- 失败落点 ----
  // 事件兜底路径下 snapshot 为 null ⇒ 前两个来源都空，退到指针 stage：
  // `process.session.failed` 的 payload 恒为空 dict，拿不到落点，最后一条转移事件
  // 指向的 stage 就是当时正在跑的那一步。退不出来时不标红任何一步，不猜。
  const failureStage = isFailed
    ? (asNonEmptyString(snapshot?.failure?.stage) ?? (rawStage || pointerStage || ''))
    : ''
  const failIndex = failureStage ? (STAGE_ORDER as string[]).indexOf(failureStage) : -1
  const failReason = isFailed
    ? (FAIL_REASON_LABELS[String(snapshot?.failure?.reason_code ?? '')] ?? COPY.unknownReason)
    : null

  /** 已推进到哪一格：失败时以失败步为界，否则以指针为界。 */
  const progressIndex = isFailed && failIndex >= 0 ? failIndex : pointerIndex

  // ---- 中断判定 ----
  // `waiting_clarification` + 不活跃**不算**中断：那是合法的等待用户。
  const interrupted = input?.runtimeActive === false && (status === 'running' || status === 'waiting_event')

  // ---- 脉冲：只有「确实在动」时才脉冲 ----
  //
  // 🔴 与失败态同一个坑：只看快照 status 会让**真直播的前半程不脉冲、2s 轮询的
  // 后半程反而脉冲**——恰好把「哪一半更实时」表达反了。前半程 snapshot 恒为 null，
  // 此时只要 runtime 活跃、有事件在来、且未进终态，就是确实在动。
  const liveWithoutSnapshot = status === null
    && input?.runtimeActive === true
    && folded.lastTransitionStage !== null
    && !isFailed
  const shouldPulse = (
    input?.runtimeActive === true
    && (status === 'running' || status === 'waiting_clarification' || status === 'waiting_event')
  ) || liveWithoutSnapshot

  const showClassify = snapshot?.has_classify === true || folded.sawClassifyEvent
  const clarifyIndex = STAGE_ORDER.indexOf('clarify')
  const routingDegraded = folded.routingPayload?.degraded === true

  // ---- 逐步状态：🔴 序号在完整 7 键上算，可见性过滤放到最后 ----
  const allSteps: TimelineStepItem[] = STAGE_ORDER.map((stage, index) => {
    let stepStatus: TimelineStepItem['status']
    if (isFailed && failIndex >= 0 && index === failIndex)
      stepStatus = 'failed'
    else if (interrupted && index === pointerIndex)
      stepStatus = 'unknown'
    else if (stage === 'clarify' && progressIndex > clarifyIndex && !folded.sawClarification)
      stepStatus = 'skipped'
    else if (isDone)
      stepStatus = 'completed'
    else if (index < progressIndex)
      stepStatus = 'completed'
    else if (index === progressIndex && !isFailed)
      stepStatus = 'running'
    else
      stepStatus = 'pending'

    const step: TimelineStepItem = { id: stage, name: STAGE_LABELS[stage], status: stepStatus }

    if (stepStatus === 'failed') {
      step.summary = failReason ?? COPY.unknownReason
    }
    else if (stepStatus === 'unknown') {
      step.summary = COPY.interrupted
    }
    else {
      const summary = stageSummary(stage, stepStatus, snapshot, folded)
      if (summary !== undefined)
        step.summary = summary
    }

    if (stepStatus === 'running')
      step.pulse = shouldPulse

    // §D.2 本 phase 唯一渲染的降级信号：只标位置、不做解释。
    // 🔴 严格 `=== true`，绝不按 router_version 或候选内容自行推断；缺失视为 false。
    if (stage === 'route' && routingDegraded)
      step.badge = { text: COPY.degradedBadge, variant: 'warning' }

    return step
  })

  // ---- 可见性过滤（最后一步）：非 feature_list 流程时整条移除，而不是标灰 / 标 skipped ----
  const steps = showClassify ? allSteps : allSteps.filter(step => step.id !== 'classify')

  const phase: OrchestrationTimelineView['phase'] = isFailed ? 'failed' : isDone ? 'done' : 'running'
  const title = phase === 'failed' ? COPY.titleFailed : phase === 'done' ? COPY.titleDone : COPY.titleRunning
  const doneCount = steps.filter(step => step.status === 'completed' || step.status === 'skipped').length

  const pointerLabel = STAGE_LABELS[STAGE_ORDER[pointerIndex >= 0 ? pointerIndex : 0]]
  const failLabel = failIndex >= 0 ? STAGE_LABELS[STAGE_ORDER[failIndex]] : pointerLabel
  // 🔴 一条证据都没有时（pointerIndex === -1）不播报阶段：此时六步全 pending，
  // 播「当前阶段：拆分」会说出一个界面上明明是 pending 的阶段，是读屏侧的撒谎。
  const liveMessage = phase === 'failed'
    ? COPY.liveFailed(failLabel, failReason ?? COPY.unknownReason)
    : phase === 'done'
      ? COPY.liveDone
      : pointerIndex >= 0
        ? COPY.liveRunning(pointerLabel)
        : ''

  return { steps, phase, title, doneCount, totalCount: steps.length, liveMessage }
}
