/**
 * useBlueprintLive 轮询启停时序断言（Phase 115-02，plan-checker BLOCKER-1 的可证伪落点）。
 *
 * 范式抄 `components/repository/__tests__/ReconcilePanel.spec.ts`：
 * `new QueryClient({ defaultOptions: { queries: { retry: false } } })` + `VueQueryPlugin`
 * + `vi.mock('~/api/blueprints')`；composable 挂在一个最小宿主组件里以获得 vue-query 的注入上下文。
 *
 * ⛔ 本 spec **只锁轮询启停这一件事**。业务派生（`sectionProgress`）归
 * `utils/__tests__/blueprintBlocks.test.ts` 的纯函数单测，这里不重复；阶段时间线的末态推断
 * 见 `utils/__tests__/blueprintBlocks.test.ts` 与
 * `components/blueprint/__tests__/stageTimeline.spec.ts`（MN-01 之后本 composable 不再派生它）。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { useBlueprintLive } from '../useBlueprintLive'

vi.mock('~/api/blueprints', () => ({
  default: {
    getBlueprintReviewSnapshot: vi.fn(),
    getBlueprintDocument: vi.fn(),
    getBlueprintEvents: vi.fn(),
  },
}))

const blueprintsApi = (await import('~/api/blueprints')).default

/** 与 `useBlueprintLive` 里的 `LIVE_REFETCH_MS` 同值（刻意手抄，改了那边这里必须跟着改）。 */
const LIVE_INTERVAL_MS = 5_000

const DOC = {
  version_id: 'v1',
  version_no: 1,
  is_current: true,
  produced_by_ref: '',
  created_at: '2026-07-01T00:00:00Z',
  content: {},
  quality: { citation_coverage: 1, ai_rejection_rate: null, human_edit_volume: 0, clarification_rounds: null },
}
const EVENTS = { session_id: 's1', current_stage: 'drafting', events: [] }

function mountHost() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const Host = defineComponent({
    setup() {
      const artifactId = ref('artifact-1')
      const live = useBlueprintLive(artifactId)
      return () => h('div', String(live.currentStatus.value))
    },
  })
  const wrapper = mount(Host, { global: { plugins: [[VueQueryPlugin, { queryClient }]] } })
  return { wrapper, queryClient }
}

/** 推进 fake timers 并把随之产生的 promise 冲干净（轮询是「定时器 → 异步 fetch」两级）。 */
async function advance(ms: number): Promise<void> {
  await vi.advanceTimersByTimeAsync(ms)
  await flushPromises()
}

function docCalls(): number {
  return vi.mocked(blueprintsApi.getBlueprintDocument).mock.calls.length
}

function eventCalls(): number {
  return vi.mocked(blueprintsApi.getBlueprintEvents).mock.calls.length
}

describe('useBlueprintLive —— 轮询启停', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.mocked(blueprintsApi.getBlueprintDocument).mockResolvedValue(DOC as never)
    vi.mocked(blueprintsApi.getBlueprintEvents).mockResolvedValue(EVENTS as never)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('⭐ 非活跃 → 活跃：doc/events 的调用次数从 1 变 2（BLOCKER-1）', async () => {
    // 快照首轮返 pending_review（非活跃），次轮起返 drafting（活跃）。
    vi.mocked(blueprintsApi.getBlueprintReviewSnapshot)
      .mockResolvedValueOnce({ current_status: 'pending_review' } as never)
      .mockResolvedValue({ current_status: 'drafting' } as never)

    const { wrapper, queryClient } = mountHost()
    await flushPromises()

    // 首屏：三个查询各发一次，此刻 isLive === false。
    expect(wrapper.text()).toBe('pending_review')
    expect(docCalls()).toBe(1)
    expect(eventCalls()).toBe(1)

    // pending_review 不在轮询三态里 ⇒ 快照自己也不装定时器。用失效重取模拟「动作后失效」
    // 这条真实路径，让快照转到 drafting。
    await queryClient.invalidateQueries({ queryKey: ['blueprint', 'snapshot'] })
    await flushPromises()
    expect(wrapper.text()).toBe('drafting')

    // ⭐ 断言：isLive 由 false 翻 true 的那一刻，watch 踢了一次 refetch ⇒ 1 → 2。
    //
    // ⚠️ 变异提示（务必保留）：**删掉 `useBlueprintLive.ts` 里的 `watch(isLive, ...)` 这一条，
    //    本用例必须转红**。若删了仍绿，说明断言没测到启动路径，要修用例而不是删断言 ——
    //    doc/events 的响应体里没有状态字段，函数式 refetchInterval 读外部 ref 不是被追踪的
    //    响应式依赖，那条 watch 是它们从「永不装定时器」里被救出来的唯一途径（P-9）。
    expect(docCalls()).toBe(2)
    expect(eventCalls()).toBe(2)

    // 踢动之后链条自持：再过一个 5s 窗口，doc/events 继续增长。
    await advance(LIVE_INTERVAL_MS)
    expect(docCalls()).toBeGreaterThan(2)
    expect(eventCalls()).toBeGreaterThan(2)
  })

  it('活跃 → 终态：doc/events 的调用次数不再增长', async () => {
    vi.mocked(blueprintsApi.getBlueprintReviewSnapshot)
      .mockResolvedValueOnce({ current_status: 'drafting' } as never)
      .mockResolvedValue({ current_status: 'implemented' } as never)

    const { wrapper } = mountHost()
    await flushPromises()
    expect(wrapper.text()).toBe('drafting')

    // 第一个 5s 窗口：快照按自身 data 装了定时器 ⇒ 重取后转 implemented（终态）。
    await advance(LIVE_INTERVAL_MS)
    expect(wrapper.text()).toBe('implemented')

    const docBefore = docCalls()
    const eventsBefore = eventCalls()

    // 再过两个 5s 窗口：终态下三者都应停住。
    await advance(LIVE_INTERVAL_MS * 2)
    expect(docCalls()).toBe(docBefore)
    expect(eventCalls()).toBe(eventsBefore)
  })

  it('一直非活跃则完全不轮询（防止 watch 被写成无条件 refetch）', async () => {
    vi.mocked(blueprintsApi.getBlueprintReviewSnapshot)
      .mockResolvedValue({ current_status: 'pending_review' } as never)

    mountHost()
    await flushPromises()

    await advance(LIVE_INTERVAL_MS * 3)

    expect(blueprintsApi.getBlueprintReviewSnapshot).toHaveBeenCalledTimes(1)
    expect(docCalls()).toBe(1)
    expect(eventCalls()).toBe(1)
  })
})
