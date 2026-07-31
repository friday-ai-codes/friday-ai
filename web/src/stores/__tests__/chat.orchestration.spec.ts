import type { SSEEvent } from '~/types/chat'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getConversationDetail, getConversationRuntime } from '~/api/chat'
import { useChatStore } from '~/stores/chat'

/**
 * Phase 110-04：编排进度双链合流的 store 层。
 *
 * 核心不变量（110-UI-SPEC §E.1 / §E.4）：SSE `process_event` 与 2s 运行时快照
 * 写**同一份** store 状态；两条链必然重复投递，合并必须幂等；编排终态那一拍
 * `runtime.active` 恰好变 false，终态仍必须到达 store。
 */

vi.mock('~/api/chat', async () => {
  const actual = await vi.importActual<typeof import('~/api/chat')>('~/api/chat')
  return {
    ...actual,
    getConversationRuntime: vi.fn(),
    getConversationDetail: vi.fn(),
  }
})

const SESSION_A = 'conv-session-A'
const SESSION_B = 'conv-session-B'

/** 两条链共有的三条事件（`event` / `ts` / 自然键逐字相同 ⇒ 必须被认成同一条）。 */
const SHARED_EVENTS = [
  { event: 'repo.research.started', ts: '2026-07-31T10:00:01+00:00', payload: { repo_id: 'repo-1' } },
  { event: 'repo.research.started', ts: '2026-07-31T10:00:02+00:00', payload: { repo_id: 'repo-2' } },
  { event: 'repo.research.completed', ts: '2026-07-31T10:00:03+00:00', payload: { repo_id: 'repo-1' } },
]

/** 只在快照侧出现的两条补齐事件。 */
const EXTRA_EVENTS = [
  { event: 'repo.research.completed', ts: '2026-07-31T10:00:04+00:00', payload: { repo_id: 'repo-2' } },
  { event: 'technical_plan.merge.started', ts: '2026-07-31T10:00:05+00:00', payload: {} },
]

function processEvent(
  overrides: Partial<{ event: string, session_id: string, ts: string, payload: unknown }> = {},
): SSEEvent {
  return {
    type: 'process_event',
    event: 'repo.research.started',
    session_id: SESSION_A,
    ts: '2026-07-31T10:00:01+00:00',
    payload: {},
    ...overrides,
  } as unknown as SSEEvent
}

function orchestrationSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    session_id: SESSION_A,
    status: 'running',
    current_stage: 'research',
    has_classify: false,
    segment_count: 3,
    failure: null,
    events: [],
    events_truncated: false,
    ...overrides,
  }
}

function runtimeWith(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: 'conv-1',
    active: true,
    ...overrides,
  } as any
}

describe('chat store 编排进度（process_event + 运行时快照双链合流）', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>
  let errorSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.mocked(getConversationRuntime).mockReset()
    vi.mocked(getConversationDetail).mockReset()
    window.localStorage.clear()
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    // 观测代码不刷噪音：全部用例中 console.warn / console.error 零调用。
    expect(warnSpy).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
    errorSpy.mockRestore()
    vi.useRealTimers()
  })

  // ======================================================================
  // 双链合流（核心不变量）
  // ======================================================================

  it('先 SSE 后快照：同一条事件必须被认成同一条（5 条，不是 8 条）', () => {
    const store = useChatStore()
    for (const e of SHARED_EVENTS)
      store._dispatchSSE(processEvent(e))

    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ events: [...SHARED_EVENTS, ...EXTRA_EVENTS] }),
    }))

    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(5)
  })

  it('快照先 / SSE 后：反方向同样去重（5 条，不是 8 条）', () => {
    const store = useChatStore()
    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ events: SHARED_EVENTS }),
    }))

    for (const e of [...SHARED_EVENTS, ...EXTRA_EVENTS])
      store._dispatchSSE(processEvent(e))

    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(5)
  })

  it('同 event 同自然键但 ts 不同 ⇒ 两条都保留（去重键退化为「只按 event + 自然键」时必红）', () => {
    const store = useChatStore()
    store._dispatchSSE(processEvent({
      event: 'clarification.asked',
      ts: '2026-07-31T10:00:01+00:00',
      payload: { clarification_id: 'clar-1' },
    }))
    store._dispatchSSE(processEvent({
      event: 'clarification.asked',
      ts: '2026-07-31T10:05:00+00:00',
      payload: { clarification_id: 'clar-1' },
    }))

    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(2)
  })

  it('合流后的事件流按 ts 升序（快照乱序到达也归并到正确位置）', () => {
    const store = useChatStore()
    store._dispatchSSE(processEvent(EXTRA_EVENTS[1]))
    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ events: SHARED_EVENTS }),
    }))

    const tsList = store.orchestrationSessions[SESSION_A].events.map(e => e.ts)
    expect(tsList).toEqual([...tsList].sort())
    expect(tsList[tsList.length - 1]).toBe(EXTRA_EVENTS[1].ts)
  })

  it('快照的权威字段整体替换，current_stage 跟随最后一次快照（store 不做阶段裁决）', () => {
    const store = useChatStore()
    for (const e of SHARED_EVENTS)
      store._dispatchSSE(processEvent(e))

    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ current_stage: 'merge' }),
    }))
    expect(store.orchestrationSessions[SESSION_A].snapshot?.current_stage).toBe('merge')

    // 更旧的一份快照到达 ⇒ 字段仍跟随最后一次（「取更靠后阶段」的裁决归 110-05）
    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ current_stage: 'research' }),
    }))
    expect(store.orchestrationSessions[SESSION_A].snapshot?.current_stage).toBe('research')
    // 事件不被快照整体替换掉
    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(3)
  })

  it('events_truncated 随快照写入桶', () => {
    const store = useChatStore()
    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ events_truncated: true }),
    }))

    expect(store.orchestrationSessions[SESSION_A].eventsTruncated).toBe(true)
  })

  // ======================================================================
  // 终态可达（F-9 的回归锁）
  // ======================================================================

  it('active: false 时编排终态 done 仍到达 store —— 非活跃分支也必须写编排快照', async () => {
    vi.useFakeTimers()
    const store = useChatStore()
    store.currentConversationId = 'conv-1'

    // 第一拍：active=true，起 2s 轮询
    vi.mocked(getConversationRuntime).mockResolvedValueOnce(runtimeWith({
      orchestration: orchestrationSnapshot({ status: 'running', current_stage: 'merge' }),
    }))
    await store.restoreConversationRuntime('conv-1')

    // 终态那一拍：active 变 false，编排 done
    vi.mocked(getConversationRuntime).mockResolvedValue(runtimeWith({
      active: false,
      orchestration: orchestrationSnapshot({ status: 'done', current_stage: 'merge' }),
    }))
    vi.mocked(getConversationDetail).mockResolvedValue({ messages: [] } as any)

    await vi.advanceTimersByTimeAsync(2000)

    expect(store.orchestrationSessions[SESSION_A].snapshot?.status).toBe('done')
  })

  it('active: false 时 failed + failure（stage / reason_code）完整到达 store', async () => {
    vi.useFakeTimers()
    const store = useChatStore()
    store.currentConversationId = 'conv-1'

    vi.mocked(getConversationRuntime).mockResolvedValueOnce(runtimeWith({
      orchestration: orchestrationSnapshot({ status: 'running' }),
    }))
    await store.restoreConversationRuntime('conv-1')

    vi.mocked(getConversationRuntime).mockResolvedValue(runtimeWith({
      active: false,
      orchestration: orchestrationSnapshot({
        status: 'failed',
        current_stage: 'merge',
        failure: { stage: 'merge', reason_code: 'merge_validation_exhausted' },
      }),
    }))
    vi.mocked(getConversationDetail).mockResolvedValue({ messages: [] } as any)

    await vi.advanceTimersByTimeAsync(2000)

    const snap = store.orchestrationSessions[SESSION_A].snapshot
    expect(snap?.status).toBe('failed')
    expect(snap?.failure).toEqual({ stage: 'merge', reason_code: 'merge_validation_exhausted' })
  })

  it('active: true 分支同样到达（两条分支各覆盖一次）', async () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    vi.mocked(getConversationRuntime).mockResolvedValue(runtimeWith({
      active: true,
      orchestration: orchestrationSnapshot({ status: 'running', current_stage: 'clarify' }),
    }))

    await store.restoreConversationRuntime('conv-1')

    expect(store.orchestrationSessions[SESSION_A].snapshot?.current_stage).toBe('clarify')
  })

  it('applyOrchestrationRuntime 不把 isStreaming 置 true（防止被并回 applyRuntimeSnapshot）', () => {
    const store = useChatStore()
    expect(store.isStreaming).toBe(false)

    store.applyOrchestrationRuntime(runtimeWith({
      active: false,
      orchestration: orchestrationSnapshot({ status: 'done' }),
    }))

    expect(store.orchestrationSessions[SESSION_A].snapshot?.status).toBe('done')
    expect(store.isStreaming).not.toBe(true)
  })

  // ======================================================================
  // 终态收敛协议（110-MN-02）
  // ======================================================================

  /** 已经拿到过一份「终态 + 全量」的快照，并且有调研日志在手。 */
  function seedTerminalSnapshot(
    store: ReturnType<typeof useChatStore>,
    orchOverrides: Record<string, unknown> = {},
  ) {
    store.applyOrchestrationRuntime(runtimeWith({
      active: false,
      orchestration: orchestrationSnapshot({
        status: 'done',
        current_stage: 'merge',
        events: SHARED_EVENTS,
        ...orchOverrides,
      }),
      plan_research_sessions: [
        { session_id: 'sub-1', plan_session_id: SESSION_A, repository_id: 'repo-1', logs: [] },
      ],
    }))
  }

  it('converged 响应不把 eventsTruncated 冲回 false（空 events 是「没有变化」而不是「没有了」）', () => {
    // 事件**列表**本身有合并语义天然兜着（merge(existing, []) 恒等），所以只断言
    // events.length 的用例挡不住任何实现——真正被收敛守卫保护的是随空 events 一起
    // 回来的 events_truncated=false。
    const store = useChatStore()
    seedTerminalSnapshot(store, { events_truncated: true })
    expect(store.orchestrationSessions[SESSION_A].eventsTruncated).toBe(true)

    store.applyOrchestrationRuntime(runtimeWith({
      active: true,
      orchestration: orchestrationSnapshot({
        status: 'done',
        current_stage: 'merge',
        events: [],
        events_truncated: false,
        converged: true,
      }),
    }))

    expect(store.orchestrationSessions[SESSION_A].eventsTruncated).toBe(true)
    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(3)
  })

  it('converged 响应不清空已有调研日志', () => {
    // 与上一条分开：两份内容各走一条保留路径，合成一条时第一个断言会遮住另一条。
    const store = useChatStore()
    seedTerminalSnapshot(store)

    store.applyOrchestrationRuntime(runtimeWith({
      active: true,
      orchestration: orchestrationSnapshot({ status: 'done', converged: true }),
      // 后端在收敛响应里就是这么回的
      plan_research_sessions: [],
    }))

    expect(store.planResearchSessions.map(s => s.session_id)).toEqual(['sub-1'])
  })

  it('非 converged 响应仍按全量语义整体替换调研日志（收敛保护不得泄漏成永不更新）', () => {
    const store = useChatStore()
    seedTerminalSnapshot(store)

    store.applyOrchestrationRuntime(runtimeWith({
      active: true,
      orchestration: orchestrationSnapshot({ status: 'running' }),
      plan_research_sessions: [],
    }))

    expect(store.planResearchSessions).toEqual([])
  })

  it('轮询在编排终态后带上收敛令牌，刷新补齐则永远不带', async () => {
    vi.useFakeTimers()
    const store = useChatStore()
    store.currentConversationId = 'conv-1'

    vi.mocked(getConversationRuntime).mockResolvedValue(runtimeWith({
      active: true,
      orchestration: orchestrationSnapshot({ status: 'done', current_stage: 'merge' }),
    }))
    vi.mocked(getConversationDetail).mockResolvedValue({ messages: [] } as any)

    await store.restoreConversationRuntime('conv-1')
    // 🔴 刷新补齐这条路径是来拿全量的，带令牌会让它永远补不齐
    expect(vi.mocked(getConversationRuntime).mock.calls[0][1] ?? '').toBe('')

    await vi.advanceTimersByTimeAsync(2000)

    const pollArgs = vi.mocked(getConversationRuntime).mock.calls.at(-1)
    expect(pollArgs?.[1]).toBe(SESSION_A)
  })

  it('编排仍在途时轮询不带令牌（事件流还在增长，短路会把时间线钉死）', async () => {
    vi.useFakeTimers()
    const store = useChatStore()
    store.currentConversationId = 'conv-1'

    vi.mocked(getConversationRuntime).mockResolvedValue(runtimeWith({
      active: true,
      orchestration: orchestrationSnapshot({ status: 'running', current_stage: 'research' }),
    }))

    await store.restoreConversationRuntime('conv-1')
    await vi.advanceTimersByTimeAsync(2000)

    const pollArgs = vi.mocked(getConversationRuntime).mock.calls.at(-1)
    expect(pollArgs?.[1] ?? '').toBe('')
  })

  // ======================================================================
  // 分桶隔离
  // ======================================================================

  it('两个 session 的事件各自入桶互不相含，activeOrchestrationSessionId 为最后一次到达的那个', () => {
    const store = useChatStore()
    store._dispatchSSE(processEvent({ session_id: SESSION_A, event: 'decomposed' }))
    store._dispatchSSE(processEvent({ session_id: SESSION_B, event: 'routed' }))

    const a = store.orchestrationSessions[SESSION_A]
    const b = store.orchestrationSessions[SESSION_B]
    expect(a.events.map(e => e.event)).toEqual(['decomposed'])
    expect(b.events.map(e => e.event)).toEqual(['routed'])
    expect(store.activeOrchestrationSessionId).toBe(SESSION_B)
  })

  it('快照写 session A 时不清空 session B 的桶（历史编排的时间线不被新编排覆盖）', () => {
    const store = useChatStore()
    store._dispatchSSE(processEvent({ session_id: SESSION_B, event: 'merged' }))

    store.applyOrchestrationRuntime(runtimeWith({
      orchestration: orchestrationSnapshot({ session_id: SESSION_A, events: SHARED_EVENTS }),
    }))

    expect(store.orchestrationSessions[SESSION_B].events).toHaveLength(1)
    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(3)
  })

  // ======================================================================
  // 清理点
  // ======================================================================

  it('流结束（resetStreamingState）后桶仍在 —— 编排完成后时间线不应消失', async () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    for (const e of SHARED_EVENTS)
      store._dispatchSSE(processEvent(e))

    // 非活跃 runtime 的 restore 路径内部会调 resetStreamingState
    vi.mocked(getConversationRuntime).mockResolvedValue(runtimeWith({ active: false }))
    await store.restoreConversationRuntime('conv-1')

    expect(store.isStreaming).toBe(false)
    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(3)
  })

  it('切换会话后桶被清空（编排原材料按会话维度隔离，不跨会话串渲染）', async () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    store._dispatchSSE(processEvent())
    store.applyOrchestrationRuntime(runtimeWith({
      plan_research_sessions: [
        { session_id: 's1', plan_session_id: SESSION_A, repository_id: 'repo-1', logs: [] },
      ],
    }))
    expect(Object.keys(store.orchestrationSessions)).toHaveLength(1)

    vi.mocked(getConversationDetail).mockResolvedValue({
      id: 'conv-2',
      messages: [],
    } as any)
    // 新会话没有编排 ⇒ 清理后的空状态不会被 restore 又填回来
    vi.mocked(getConversationRuntime).mockResolvedValue({
      conversation_id: 'conv-2',
      active: false,
    } as any)

    await store.selectConversation('conv-2')

    expect(Object.keys(store.orchestrationSessions)).toHaveLength(0)
    expect(store.activeOrchestrationSessionId).toBeNull()
    expect(store.planResearchSessions).toEqual([])
  })

  it('新建会话时编排状态整体复位，orchestrationRuntimeActive 回到初值 true', async () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-1'
    store._dispatchSSE(processEvent())
    store.applyOrchestrationRuntime(runtimeWith({ active: false }))
    expect(store.orchestrationRuntimeActive).toBe(false)

    await store.createNewConversation()

    expect(Object.keys(store.orchestrationSessions)).toHaveLength(0)
    expect(store.activeOrchestrationSessionId).toBeNull()
    expect(store.planResearchSessions).toEqual([])
    expect(store.orchestrationRuntimeActive).toBe(true)
  })

  // ======================================================================
  // 守卫与兜底
  // ======================================================================

  it('后台会话流的 process_event 不写当前 UI 的桶（前台守卫生效）', () => {
    const store = useChatStore()
    store.currentConversationId = 'conv-B'

    store._dispatchSSE(processEvent(), 'conv-A')

    expect(Object.keys(store.orchestrationSessions)).toHaveLength(0)
  })

  it('中断态的 process_event 不入桶（中断守卫生效，真实进度由快照补齐）', () => {
    const store = useChatStore()
    store.streamingStatus = 'interrupted'

    store._dispatchSSE(processEvent())

    expect(Object.keys(store.orchestrationSessions)).toHaveLength(0)
  })

  it('未知事件名（后端新增而前端未同步）正常入桶，不被白名单过滤掉', () => {
    const store = useChatStore()

    store._dispatchSSE(processEvent({ event: 'brand.new.event' }))

    expect(store.orchestrationSessions[SESSION_A].events.map(e => e.event))
      .toContain('brand.new.event')
  })

  it('process_event 缺 session_id / 缺 event 名时不入桶、不抛', () => {
    const store = useChatStore()

    expect(() => store._dispatchSSE(processEvent({ session_id: undefined as any }))).not.toThrow()
    expect(() => store._dispatchSSE(processEvent({ event: undefined as any }))).not.toThrow()

    expect(Object.keys(store.orchestrationSessions)).toHaveLength(0)
  })

  it('payload 为 null / 字符串 / 数组时不抛，事件仍原样入桶', () => {
    const store = useChatStore()

    for (const [i, payload] of [null, 'not-an-object', ['a', 'b'], undefined].entries()) {
      expect(() => store._dispatchSSE(processEvent({
        event: `weird.payload.${i}`,
        ts: `2026-07-31T11:00:0${i}+00:00`,
        payload,
      }))).not.toThrow()
    }

    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(4)
  })

  it('老后端 runtime（无 orchestration / plan_research_sessions 两键）不抛，桶保持不变', () => {
    const store = useChatStore()
    store._dispatchSSE(processEvent())

    expect(() => store.applyOrchestrationRuntime(runtimeWith())).not.toThrow()

    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(1)
    expect(store.planResearchSessions).toEqual([])
  })

  it('orchestration 为 null 时不清空已有的桶（「没有新信息」不等于「之前的信息作废」）', () => {
    const store = useChatStore()
    for (const e of SHARED_EVENTS)
      store._dispatchSSE(processEvent(e))

    store.applyOrchestrationRuntime(runtimeWith({ orchestration: null }))

    expect(store.orchestrationSessions[SESSION_A].events).toHaveLength(3)
  })

  // ======================================================================
  // plan_research_sessions（全量替换语义）
  // ======================================================================

  it('plan_research_sessions 按快照全量替换，顺序保持，缺键回落空数组', () => {
    const store = useChatStore()
    const two = [
      { session_id: 's1', plan_session_id: SESSION_A, repository_id: 'repo-1', repository_name: 'alpha', status: 'RUNNING', logs: [] },
      { session_id: 's2', plan_session_id: SESSION_A, repository_id: 'repo-2', repository_name: 'beta', status: 'COMPLETED', logs: [] },
    ]

    store.applyOrchestrationRuntime(runtimeWith({ plan_research_sessions: two }))
    expect(store.planResearchSessions.map(s => s.session_id)).toEqual(['s1', 's2'])
    // 110-07 要按 plan_session_id 过滤到具体气泡，这个字段不能在整形时被丢掉
    expect(store.planResearchSessions[0].plan_session_id).toBe(SESSION_A)

    store.applyOrchestrationRuntime(runtimeWith({ plan_research_sessions: [two[1]] }))
    expect(store.planResearchSessions.map(s => s.session_id)).toEqual(['s2'])

    store.applyOrchestrationRuntime(runtimeWith())
    expect(store.planResearchSessions).toEqual([])
  })

  // ======================================================================
  // orchestrationRuntimeActive（中断判定的输入）
  // ======================================================================

  it('orchestrationRuntimeActive 初值为 true（一次快照都没到达时不判中断）', () => {
    const store = useChatStore()
    expect(store.orchestrationRuntimeActive).toBe(true)
  })

  it('orchestrationRuntimeActive 跟随快照的 active：false 后为 false，true 后回到 true', () => {
    const store = useChatStore()

    store.applyOrchestrationRuntime(runtimeWith({ active: false }))
    expect(store.orchestrationRuntimeActive).toBe(false)

    store.applyOrchestrationRuntime(runtimeWith({ active: true }))
    expect(store.orchestrationRuntimeActive).toBe(true)
  })
})
