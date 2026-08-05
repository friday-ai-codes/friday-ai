/**
 * 蓝图实时进展 —— **全相位唯一的轮询消费点**（Phase 115-02，UI-SPEC §8.3）。
 *
 * 只在 `researching` / `drafting` / `ai_reviewing` 三态开启 5s 轮询；进入人审态
 * （`pending_review`）与任一终态自动停。
 *
 * **同步点 2 之后**若 v0.19.0 的推送契约就位，**只改这一个文件**（把 `refetchInterval` 换成
 * 订阅）。这是本相位对并行纪律最实际的交代 ⇒ `refetchInterval` 字面量**不得**出现在任何
 * 组件里（`src/__tests__/blueprint-source-guard.spec.ts` 的源码扫描锁死单文件）。
 *
 * ⛔ 不接页面可见性判断：TanStack Query 内建 `refetchIntervalInBackground: false`（默认即
 * false），页面失焦时自动停，仓内 10 处轮询先例都没自己写一遍。
 * ⛔ 不用 `composables/` 下那个手动 start/stop 的 `useIntervalFn` 轮询工具：它与 TanStack
 * Query 无关，两套定时器并存必然打架。对齐它的只是**间隔量级**（日志级 2s，蓝图阶段级取 5s）。
 *
 * ## ⭐ 为什么三个查询的 `refetchInterval` 写法不一样（不能统一，这是本文件最要紧的一段）
 *
 * 函数式 `refetchInterval` **只在本查询自己的 state 更新、或 options 触发 `setOptions` 时
 * 重算**；函数体里读一个外部 ref **不是被追踪的响应式依赖**（vue-query 的 `cloneDeepUnref`
 * 不下探函数体）。
 *
 * - **snapshot 查询**的响应体自带 `current_status` ⇒ 直接读**它自己的** `query.state.data`，
 *   与仓内全部可用先例同款（`DocsSection.vue:73` / `ReconcilePanel.vue:59` /
 *   `FeatureBoard.vue:50,58` / `ProjectHealthCard.vue:79` / `BatchIngestPanel.vue:32`）。
 *   它的间隔自带自持链条：每次 fetch 结束都会重算。
 * - **doc / events 查询**的响应体里**没有状态字段**，只能读外部的 `isLive` ⇒ 必须**另配一条
 *   `watch(isLive, ...)` 的 `refetch()` 踢动作为启动保证**。
 *
 * 不配那条 `watch` 会怎样：打开一个 `drafting` 蓝图时三个查询近乎同时发出，doc/events **先**
 * 落地而共享的 `currentStatus` 此刻还是 `''` ⇒ 算出 `false`、**永不装定时器、也永不再重算**。
 * 症状是**首屏有内容、无报错、快照徽标还在跳，而章节进度冻结在打开那一刻** —— 正是 P-9 那种
 * 静默假通过。有了 `watch` 的首次 `refetch()` 踢动，此后每次 fetch 结束都会重算间隔，链条自持。
 * ⛔ **不得删掉该 `watch`**（`composables/__tests__/useBlueprintLive.spec.ts` 有对应的
 * 「doc/events 调用次数 1 → 2」时序断言，删了它必须转红）。
 *
 * ⚠️ 参考实证：仓内**唯一**在函数体里读外部 ref 的先例是 `pages/admin/observability/index.vue:83`，
 * 但那一页真正驱动刷新的是**页面自建的 `setInterval` + `invalidateQueries`**（`:47-76`）——
 * 恰好反证「只读外部 ref 不足以自启动」。本文件用 `watch` + `refetch()` 承担同一职责，
 * ⛔ 不复制它的 `setInterval` 方案（会绕开 TanStack Query 的窗口失焦策略）。
 */

import type { Ref } from 'vue'
import type { BlueprintEvent } from '~/types/blueprint'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import blueprintsApi from '~/api/blueprints'
import { LIVE_BLUEPRINT_STATUSES } from '~/config/blueprintStatus'
import { progressKeyForEvent, sectionKeyForEvent } from '~/utils/blueprintBlocks'

/** 轮询间隔（毫秒）。阶段级进展取 5s；日志级的 2s 太密，会把只读评审面变成压测。 */
const LIVE_REFETCH_MS = 5_000

/** 某个导航段的进度文案信息（i18n key + 该事件的 payload，插值键缺失时回落无参兜底）。 */
export interface SectionProgress {
  /** `knowledge.blueprints.progress.<尾段>`。 */
  key: string
  /** 同一 key 的无参兜底（`<key>Generic`）；文案本身无插值时与 `key` 相同。 */
  fallbackKey: string
  payload: Record<string, unknown>
  ts: string
}

/** 带插值的进度文案所需的键（缺任一即回落无参兜底，P-8：payload 的键 schema 层零保证）。 */
const PROGRESS_PARAMS: Record<string, string[]> = {
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
}

function resolveProgressKeys(eventName: string, payload: Record<string, unknown>): {
  key: string
  fallbackKey: string
} {
  const key = progressKeyForEvent(eventName)
  if (!key)
    return { key: '', fallbackKey: '' }
  const suffix = key.split('.').pop() ?? ''
  const required = PROGRESS_PARAMS[suffix]
  if (!required)
    return { key, fallbackKey: key }
  const generic = `${key}Generic`
  const complete = required.every(
    name => payload?.[name] !== undefined && payload?.[name] !== null && payload?.[name] !== '',
  )
  return { key: complete ? key : generic, fallbackKey: generic }
}

/**
 * 蓝图查看器的三个实时查询 + 两项派生。
 *
 * ⛔ **阶段时间线不在这里派生**：它是 `~/utils/blueprintBlocks` 的纯函数
 * `buildStageTimeline(events, currentStage, currentStatus)`，由
 * `components/blueprint/BlueprintStageTimeline.vue` 直接调用。这里曾有过一份零消费方的副本，
 * 它让「修一处、单测绿、界面纹丝不动」成为可能（MN-01），已删除，⛔ 不要加回来。
 *
 * @param artifactId 蓝图 artifact id（响应式）。
 * @param versionId 可选的历史版本 id；变化会带出新的 `['blueprint','doc',...]` 缓存条目。
 */
export function useBlueprintLive(artifactId: Ref<string>, versionId?: Ref<string | undefined>) {
  const snapshotQuery = useQuery({
    queryKey: computed(() => ['blueprint', 'snapshot', artifactId.value]),
    queryFn: () => blueprintsApi.getBlueprintReviewSnapshot(artifactId.value),
    enabled: computed(() => Boolean(artifactId.value)),
    staleTime: 0,
    // ⭐ 读**自己的** data：响应体自带 current_status，链条自持（仓内全部可用先例同款）。
    refetchInterval: query =>
      LIVE_BLUEPRINT_STATUSES.has(String(query.state.data?.current_status ?? ''))
        ? LIVE_REFETCH_MS
        : false,
  })

  /** 状态一律以快照响应体的 `current_status` 为准，⛔ 前端不自行乐观推断下一状态。 */
  const currentStatus = computed(() => String(snapshotQuery.data.value?.current_status ?? ''))
  const isLive = computed(() => LIVE_BLUEPRINT_STATUSES.has(currentStatus.value))

  const docQuery = useQuery({
    queryKey: computed(() => [
      'blueprint',
      'doc',
      artifactId.value,
      versionId?.value ?? 'current',
    ]),
    queryFn: () =>
      blueprintsApi.getBlueprintDocument(artifactId.value, { version_id: versionId?.value }),
    enabled: computed(() => Boolean(artifactId.value)),
    staleTime: 30_000,
    // ⚠️ 响应体没有状态字段 ⇒ 只能读外部 isLive；**启动保证在下面那条 watch 里**。
    refetchInterval: () => (isLive.value ? LIVE_REFETCH_MS : false),
  })

  /**
   * ⭐ 事件累积器（Phase 118，LIVE-04）：轮询改**增量**后单次响应只含新增事件，
   * 因此完整事件流必须在客户端累积，⛔ 不能再直接读 `eventsQuery.data.events`。
   *
   * 去重键是 `(event, ts)` —— 与 chat 侧 `process_event` 合流用的同一口径。`since_ts`
   * 是严格大于，正常路径不会重复；但**手动 `refetchAll()` 会重新全量拉**（它把游标清空，
   * 否则动作端点 2xx 后拉不到早于游标的补洞事件），那一次必然与已累积的重叠。
   */
  const eventLog = ref<BlueprintEvent[]>([])
  const seenKeys = ref<Set<string>>(new Set())
  /** 增量游标 = 已累积事件里最大的 `ts`；为空表示下一次全量拉。 */
  const cursorTs = ref('')

  function resetEventLog(): void {
    eventLog.value = []
    seenKeys.value = new Set()
    cursorTs.value = ''
  }

  function mergeEvents(incoming: BlueprintEvent[]): void {
    if (incoming.length === 0)
      return
    const merged = eventLog.value.slice()
    for (const event of incoming) {
      const key = `${event.event}|${event.ts}`
      if (seenKeys.value.has(key))
        continue
      seenKeys.value.add(key)
      merged.push(event)
      if (String(event.ts) > cursorTs.value)
        cursorTs.value = String(event.ts)
    }
    // 按 ts 升序（后端已升序，但增量批次之间仍要保序；ISO8601 可字典序比较）
    merged.sort((a, b) => String(a.ts).localeCompare(String(b.ts)))
    eventLog.value = merged
  }

  // 切换 artifact 必须清空累积器：不清会把上一份蓝图的事件混进这一份的时间线。
  watch(artifactId, resetEventLog)

  const eventsQuery = useQuery({
    queryKey: computed(() => ['blueprint', 'events', artifactId.value]),
    queryFn: async () => {
      const response = await blueprintsApi.getBlueprintEvents(artifactId.value, {
        since_ts: cursorTs.value || undefined,
      })
      mergeEvents(response.events ?? [])
      return response
    },
    enabled: computed(() => Boolean(artifactId.value)),
    staleTime: 0,
    refetchInterval: () => (isLive.value ? LIVE_REFETCH_MS : false),
  })

  // ⭐ 启动保证：非活跃 → 活跃的那一刻踢一次 refetch，让 doc/events 的间隔函数重算并装上
  // 定时器。⛔ 不得删除（见文件头的「为什么写法不一样」）。
  watch(isLive, (on) => {
    if (on) {
      docQuery.refetch()
      eventsQuery.refetch()
    }
  })

  /** 完整事件流（累积器）。⛔ 不读 `eventsQuery.data.events` —— 增量后那只是最后一批。 */
  const events = computed<BlueprintEvent[]>(() => eventLog.value)

  /**
   * 段级进度：`Record<sectionKey, SectionProgress>`，**一段取其命中事件中 `ts` 最大的一条**。
   *
   * 未被任何事件覆盖的段（`impact_analysis` / `interaction_flows` / `must_haves` /
   * `associations`）不出现在此表里 ⇒ 调用方回落状态级文案
   * （`progress.fallbackResearching` / `fallbackDrafting` / `fallbackAiReviewing`）。
   */
  const sectionProgress = computed<Record<string, SectionProgress>>(() => {
    const result: Record<string, SectionProgress> = {}
    for (const event of events.value) {
      const sections = sectionKeyForEvent(event.event)
      if (sections.length === 0)
        continue
      const payload = event.payload ?? {}
      const { key, fallbackKey } = resolveProgressKeys(event.event, payload)
      if (!key)
        continue
      for (const sectionKey of sections) {
        const existing = result[sectionKey]
        if (existing && String(existing.ts).localeCompare(String(event.ts)) >= 0)
          continue
        result[sectionKey] = { key, fallbackKey, payload, ts: event.ts }
      }
    }
    return result
  })

  /** 状态级回落文案 key（生成中三态之一；非生成态返回 `''`）。 */
  const statusProgressKey = computed(() => {
    switch (currentStatus.value) {
      case 'researching':
        return 'knowledge.blueprints.progress.fallbackResearching'
      case 'drafting':
        return 'knowledge.blueprints.progress.fallbackDrafting'
      case 'ai_reviewing':
        return 'knowledge.blueprints.progress.fallbackAiReviewing'
      default:
        return ''
    }
  })

  /** 手动重取三者（动作端点 2xx 后由调用方触发，与 `invalidateQueries` 二选一）。 */
  function refetchAll(): void {
    snapshotQuery.refetch()
    docQuery.refetch()
    // ⭐ 清游标再拉：动作端点 2xx 后可能有**早于游标**的事件（并发 emit / ts 由 emit 端
    // 传入 ⇒ 不保证单调）。增量拉会永久漏掉它们，而手动重取本就是「把一切拉齐」的语义。
    cursorTs.value = ''
    eventsQuery.refetch()
  }

  return {
    isLive,
    currentStatus,
    doc: docQuery,
    snapshot: snapshotQuery,
    eventsQuery,
    events,
    sectionProgress,
    statusProgressKey,
    refetchAll,
  }
}
