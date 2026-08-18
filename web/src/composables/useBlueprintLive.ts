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
import type {
  BlueprintEvent,
  BlueprintProgressLog,
  BlueprintResearchProgressRepo,
} from '~/types/blueprint'
import { useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import blueprintsApi from '~/api/blueprints'
import { LIVE_BLUEPRINT_STATUSES } from '~/config/blueprintStatus'
import { resolveProgressKeys, sectionKeyForEvent } from '~/utils/blueprintBlocks'

/** 轮询间隔（毫秒）。阶段级进展取 5s；日志级的 2s 太密，会把只读评审面变成压测。 */
const LIVE_REFETCH_MS = 5_000

/** 直播进度：调研态标识（唯一开启轻量 progress 轮询的状态）。 */
const RESEARCHING_STATUS = 'researching'
/** 每仓客户端累积保留的最近日志条数（尾窗；超出丢最旧，防止长会话把内存撑爆）。 */
const PROGRESS_LOG_KEEP = 40
/** 单次 progress 拉取每仓条数（后端仍 clamp；与端点默认一致）。 */
const PROGRESS_FETCH_LIMIT = 20

/** 某个导航段的进度文案信息（i18n key + 该事件的 payload，插值键缺失时回落无参兜底）。 */
export interface SectionProgress {
  /** `knowledge.blueprints.progress.<尾段>`。 */
  key: string
  /** 同一 key 的无参兜底（`<key>Generic`）；文案本身无插值时与 `key` 相同。 */
  fallbackKey: string
  payload: Record<string, unknown>
  ts: string
}

// 取键逻辑（插值完整性 + 判别式变体）已收敛到 `blueprintBlocks.resolveProgressKeys` ——
// 活动流全景要用同一份，两处各判一遍必然漂移成「同一事件文案不一致」。

/**
 * 蓝图查看器的三个实时查询 + 两项派生。
 *
 * ⛔ **阶段时间线不在这里派生**：它是 `~/utils/blueprintBlocks` 的纯函数
 * `buildStageTimeline(events, currentStage, currentStatus)`，由
 * `components/blueprint/BlueprintStageStepper.vue`（经 `buildStagePanorama`）间接调用。
 * 这里曾有过一份零消费方的副本，
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
  watch(artifactId, () => {
    resetEventLog()
    resetProgress()
  })

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

  /**
   * 节点快照（quick-260806 节点重跑）：stage_state 分片 + 重跑标记/历史 + 版本谱系。
   *
   * enabled / refetch 策略与 events 完全同款：响应体没有蓝图状态字段 ⇒ 只能读外部
   * `isLive`，启动保证同样落在下面那条 `watch(isLive)` 的 refetch 踢动上。
   */
  const stagesQuery = useQuery({
    queryKey: computed(() => ['blueprint', 'stages', artifactId.value]),
    queryFn: () => blueprintsApi.getBlueprintStages(artifactId.value),
    enabled: computed(() => Boolean(artifactId.value)),
    staleTime: 0,
    refetchInterval: () => (isLive.value ? LIVE_REFETCH_MS : false),
  })

  /**
   * ⭐ 调研直播进度累积器（Task 3，D-07）：**唯一**接入 5s 轮询的调研读面。
   *
   * 拉的是**轻量 cursor/tail** `research-progress`（每仓 ≤ {@link PROGRESS_FETCH_LIMIT} 条最近可观测
   * 日志）——⛔ 不是全量 `research-detail`（默认 400 条/仓，那是抽屉按需拉的复盘面）。用 `after_log_id`
   * 全局游标做增量，客户端按仓累积最近 {@link PROGRESS_LOG_KEEP} 条尾窗。
   *
   * 状态标量（`task_status`/`run_status`/`latest_observable`）每次覆盖为最新；日志按 `id` 去重后追加。
   */
  const progressByRepo = ref<Map<string, BlueprintResearchProgressRepo>>(new Map())
  const progressRepoOrder = ref<string[]>([])
  /** 全局 cursor = 已见过的最大 log id；0 表示下一次取尾窗。 */
  const progressCursor = ref(0)

  function resetProgress(): void {
    progressByRepo.value = new Map()
    progressRepoOrder.value = []
    progressCursor.value = 0
  }

  function mergeProgress(repos: BlueprintResearchProgressRepo[]): void {
    if (repos.length === 0)
      return
    const next = new Map(progressByRepo.value)
    const order = progressRepoOrder.value.slice()
    let maxCursor = progressCursor.value
    for (const repo of repos) {
      const key = repo.repository_id || repo.repository_name
      if (!key)
        continue
      const existing = next.get(key)
      if (!existing)
        order.push(key)
      // 按 id 去重后追加，保留尾窗（⛔ 不无界增长）
      const seen = new Set<number>((existing?.recent_logs ?? []).map(log => log.id))
      const mergedLogs: BlueprintProgressLog[] = (existing?.recent_logs ?? []).slice()
      for (const log of repo.recent_logs ?? []) {
        if (seen.has(log.id))
          continue
        seen.add(log.id)
        mergedLogs.push(log)
        if (log.id > maxCursor)
          maxCursor = log.id
      }
      mergedLogs.sort((a, b) => a.id - b.id)
      const trimmed = mergedLogs.slice(-PROGRESS_LOG_KEEP)
      if (repo.log_cursor > maxCursor)
        maxCursor = repo.log_cursor
      next.set(key, {
        repository_id: repo.repository_id,
        repository_name: repo.repository_name || existing?.repository_name || '',
        task_status: repo.task_status || existing?.task_status || '',
        run_status: repo.run_status || existing?.run_status || '',
        latest_observable: repo.latest_observable || existing?.latest_observable || '',
        log_cursor: Math.max(repo.log_cursor, existing?.log_cursor ?? 0),
        recent_logs: trimmed,
      })
    }
    progressByRepo.value = next
    progressRepoOrder.value = order
    progressCursor.value = maxCursor
  }

  /** 仅在蓝图处于 `researching` 时轮询（进 draft/评审即停）。 */
  const isResearching = computed(() => currentStatus.value === RESEARCHING_STATUS)

  const progressQuery = useQuery({
    queryKey: computed(() => ['blueprint', 'research-progress', artifactId.value]),
    queryFn: async () => {
      const response = await blueprintsApi.getBlueprintResearchProgress(artifactId.value, {
        after_log_id: progressCursor.value || undefined,
        limit: PROGRESS_FETCH_LIMIT,
      })
      mergeProgress(response.repositories ?? [])
      return response
    },
    enabled: computed(() => Boolean(artifactId.value) && isResearching.value),
    staleTime: 0,
    // ⛔ 唯一另一处 refetchInterval —— 与文件头纪律一致：轮询只在本文件。响应体带不出蓝图状态，
    // 读外部 `isResearching`；启动保证同样落在下面 watch(isLive) 的 refetch 踢动上。
    refetchInterval: () => (isResearching.value ? LIVE_REFETCH_MS : false),
  })

  // ⭐ 启动保证：非活跃 → 活跃的那一刻踢一次 refetch，让 doc/events/stages 的间隔函数重算
  // 并装上定时器。⛔ 不得删除（见文件头的「为什么写法不一样」）。
  watch(isLive, (on) => {
    if (on) {
      docQuery.refetch()
      eventsQuery.refetch()
      stagesQuery.refetch()
      // researching 态才有意义；非 researching 时 enabled=false，refetch 是安全 no-op。
      if (isResearching.value)
        progressQuery.refetch()
    }
  })

  /** 完整事件流（累积器）。⛔ 不读 `eventsQuery.data.events` —— 增量后那只是最后一批。 */
  const events = computed<BlueprintEvent[]>(() => eventLog.value)

  /**
   * 调研直播进度（按仓，累积尾窗）。供 `BlueprintStageStepper` 的 repo_research 分组卡片显示
   * 「在途可观测行」；非 researching 态为空数组。⛔ 消费方不得据此再发请求（唯一读面在本文件）。
   */
  const researchProgress = computed<BlueprintResearchProgressRepo[]>(
    () => progressRepoOrder.value.flatMap((key) => {
      const repo = progressByRepo.value.get(key)
      return repo ? [repo] : []
    }),
  )

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

  /** 手动重取全部实时查询（动作端点 2xx 后由调用方触发，与 `invalidateQueries` 二选一）。 */
  function refetchAll(): void {
    snapshotQuery.refetch()
    docQuery.refetch()
    stagesQuery.refetch()
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
    stagesQuery,
    progressQuery,
    events,
    researchProgress,
    sectionProgress,
    statusProgressKey,
    refetchAll,
  }
}
