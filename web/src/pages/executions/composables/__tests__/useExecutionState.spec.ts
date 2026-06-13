/**
 * useExecutionState.spec.ts — OBS-02 WS 断线降级轮询 RED 测试
 *
 * 契约（D-05）：当执行处于活跃态且 WS 连接 CLOSED（wsDisconnected=true）时，
 * 应启动 REST 轮询（usePolling.start），且轮询回调以 store.fetchExecution
 * 全量覆盖为服务端权威值（Pitfall 6：勿与 WS 本地 ++ 并存）；WS 恢复或执行终态后
 * 应停止轮询（usePolling.stop）。
 *
 * 当前 useExecutionState 未集成 usePolling，故启停/回调断言为 RED，
 * 由 Wave 1（21-05）实现转绿。
 */
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

// hoisted：usePolling 间谍与回调捕获、store 持有器
const mocks = vi.hoisted(() => ({
  pollStart: vi.fn(),
  pollStop: vi.fn(),
  pollRefresh: vi.fn(),
  capturedCallback: { fn: null as null | (() => any) },
  storeHolder: { current: null as any },
}))

vi.mock('~/composables/usePolling', () => ({
  usePolling: (cb: () => any) => {
    mocks.capturedCallback.fn = cb
    return {
      start: mocks.pollStart,
      stop: mocks.pollStop,
      refresh: mocks.pollRefresh,
      isPolling: ref(false),
      isActive: ref(false),
      error: ref(null),
    }
  },
}))

vi.mock('~/stores/useExecutionsStore', () => ({
  useExecutionsStore: () => mocks.storeHolder.current,
}))

// storeToRefs：我们的 fake store 已直接暴露 ref，identity 返回即可
vi.mock('pinia', async (importOriginal) => {
  const actual = await importOriginal<typeof import('pinia')>()
  return {
    ...actual,
    storeToRefs: (s: any) => s,
  }
})

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: 'exec-1' } }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

vi.mock('~/api/workflow', () => ({
  getCostBreakdown: vi.fn().mockResolvedValue(null),
  checkWorkflowChanged: vi.fn().mockResolvedValue({ changed: false }),
}))

const { useExecutionState } = await import('../useExecutionState')

function makeFakeStore() {
  return {
    currentExecution: ref<any>(null),
    timelineData: ref(null),
    loading: ref(false),
    error: ref(null),
    wsStatus: ref<'OPEN' | 'CONNECTING' | 'CLOSED' | 'CLOSING'>('OPEN'),
    fetchExecution: vi.fn().mockResolvedValue(undefined),
    connectWebSocket: vi.fn(),
    disconnectWebSocket: vi.fn(),
    fetchTimeline: vi.fn(),
  }
}

/** 挂载宿主组件以驱动 composable 的生命周期与 watch */
function mountHost() {
  let api: ReturnType<typeof useExecutionState> | null = null
  const Host = defineComponent({
    setup() {
      api = useExecutionState()
      return () => h('div')
    },
  })
  const wrapper = mount(Host)
  return { wrapper, getApi: () => api! }
}

describe('useExecutionState — OBS-02 WS 断线降级轮询', () => {
  let store: ReturnType<typeof makeFakeStore>

  beforeEach(() => {
    vi.clearAllMocks()
    mocks.capturedCallback.fn = null
    store = makeFakeStore()
    mocks.storeHolder.current = store
  })

  it('test_ws_closed_starts_polling', async () => {
    mountHost()
    await nextTick()

    // 驱动 wsDisconnected = true：执行活跃 + WS CLOSED
    store.currentExecution.value = { id: 'exec-1', status: 'running' }
    store.wsStatus.value = 'CLOSED'
    await nextTick()

    expect(mocks.pollStart).toHaveBeenCalled()
  })

  it('test_ws_reconnect_stops_polling', async () => {
    mountHost()
    await nextTick()

    // 先断线
    store.currentExecution.value = { id: 'exec-1', status: 'running' }
    store.wsStatus.value = 'CLOSED'
    await nextTick()

    // 再恢复（wsStatus 非 CLOSED）→ 应停止轮询
    store.wsStatus.value = 'OPEN'
    await nextTick()

    expect(mocks.pollStop).toHaveBeenCalled()
  })

  it('test_polling_uses_fetch_execution', () => {
    mountHost()

    // usePolling 的回调应被注册，且调用它会触发 store.fetchExecution（服务端权威值，D-05）
    expect(mocks.capturedCallback.fn).toBeTypeOf('function')
    mocks.capturedCallback.fn!()
    expect(store.fetchExecution).toHaveBeenCalled()
  })
})
