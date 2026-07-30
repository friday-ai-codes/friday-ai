/**
 * ：useRoutingStore 单元测试。
 *
 * 覆盖：upsertTrace 双索引 / 去重 / 跨 conversation 隔离 /
 * getLatestSelectedRepoIds / applyManualOverride success / failure /
 * override 对降级与分组事实的兜底继承（107-09 Task 1）。
 */

import type { RoutingCandidate, RoutingDecisionData } from '~/types/routing'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import process from 'node:process'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '~/stores/chat'
import { useRoutingStore } from '~/stores/routing'

/**
 * 后端 `RepositoryRelevanceOutput` 的真实 JSON Schema 快照（由
 * `server/tests/agents/test_repository_relevance_tool.py::test_output_schema_snapshot`
 * 守门）。
 *
 * 工具输出 payload **必须**由它构造，不能手写：手写 payload 时，后端输出模型里根本
 * 没有 degraded / degrade_reason / block_order / router_version 这四个键也照样全绿，
 * 而生产里它们恒为 undefined —— 降级横幅与分组分区在对话进行中完全不出现。契约两端
 * 共用同一份 schema 才能让缺口被测试检出。
 */
const SCHEMA_REL_PATH = 'server/tests/agents/fixtures/repository_relevance_output_schema.json'

/** 从 cwd 向上找仓库根（web/ 与 server/ 是兄弟目录），避免依赖 runner 的 cwd。 */
function resolveSchemaPath(): string {
  let dir = process.cwd()
  for (let depth = 0; depth < 6; depth++) {
    const candidate = resolve(dir, SCHEMA_REL_PATH)
    if (existsSync(candidate))
      return candidate
    const parent = dirname(dir)
    if (parent === dir)
      break
    dir = parent
  }
  throw new Error(`未找到后端输出 schema 快照：${SCHEMA_REL_PATH}`)
}

const OUTPUT_SCHEMA = JSON.parse(
  readFileSync(resolveSchemaPath(), 'utf-8'),
) as { properties: Record<string, unknown>, required?: string[] }

/** 按后端输出 schema 的键名构造 tool-output data；schema 里没有的键直接判失败。 */
function toolOutputData(values: Record<string, unknown>): Record<string, unknown> {
  const data: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(values)) {
    expect(
      Object.keys(OUTPUT_SCHEMA.properties),
      `后端 RepositoryRelevanceOutput 缺少字段 ${key} —— 前端解析到的将恒为 undefined`,
    ).toContain(key)
    data[key] = value
  }
  return data
}

const mockPostManualOverride = vi.fn()
vi.mock('~/api/routing', () => ({
  postManualOverride: (...args: unknown[]) => mockPostManualOverride(...args),
}))

function makeTrace(overrides: Partial<RoutingDecisionData> = {}): RoutingDecisionData {
  return {
    trace_id: 'trace-1',
    query: 'q',
    threshold: 0.5,
    triggered_by: 'chat_tool',
    candidates: [
      {
        repository_id: 'repo-a',
        repository_name: 'A',
        score: 0.9,
        level: 'high',
        evidence: 'ev',
        selected_by_ai: true,
        selected_by_user_final: true,
      },
      {
        repository_id: 'repo-b',
        repository_name: 'B',
        score: 0.3,
        level: 'low',
        evidence: 'ev',
        selected_by_ai: false,
        selected_by_user_final: false,
      },
    ],
    ...overrides,
  }
}

describe('useRoutingStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockPostManualOverride.mockReset()
  })

  it('upsertTrace 写入双索引 + latest 指针', () => {
    const store = useRoutingStore()
    store.upsertTrace(makeTrace(), 'conv-1')
    expect(store.tracesByTraceId.get('trace-1')).toBeTruthy()
    expect(store.tracesByConversationId.get('conv-1')).toEqual(['trace-1'])
    expect(store.latestTraceIdByConversationId.get('conv-1')).toBe('trace-1')
  })

  it('同 trace_id upsert 第二次不重复（list 长度仍 1）', () => {
    const store = useRoutingStore()
    store.upsertTrace(makeTrace(), 'conv-1')
    store.upsertTrace(makeTrace(), 'conv-1')
    expect(store.tracesByConversationId.get('conv-1')).toEqual(['trace-1'])
  })

  it('不同 conversation_id 各自维护独立 list', () => {
    const store = useRoutingStore()
    store.upsertTrace(makeTrace({ trace_id: 't-a' }), 'conv-1')
    store.upsertTrace(makeTrace({ trace_id: 't-b' }), 'conv-2')
    expect(store.tracesByConversationId.get('conv-1')).toEqual(['t-a'])
    expect(store.tracesByConversationId.get('conv-2')).toEqual(['t-b'])
  })

  it('getLatestSelectedRepoIds 取最新 trace 中 selected_by_user_final=true 的 IDs', () => {
    const store = useRoutingStore()
    store.upsertTrace(makeTrace(), 'conv-1')
    expect(store.getLatestSelectedRepoIds('conv-1')).toEqual(['repo-a'])
  })

  it('applyManualOverride 成功 → 新 trace 写入 + latest 更新', async () => {
    const store = useRoutingStore()
    store.upsertTrace(makeTrace(), 'conv-1')
    mockPostManualOverride.mockResolvedValue({
      trace_id: 'trace-2',
      original_trace_id: 'trace-1',
      triggered_by: 'manual_override',
      candidates: [
        {
          repository_id: 'repo-a',
          repository_name: 'A',
          score: 0.9,
          level: 'high',
          evidence: 'ev',
          selected_by_ai: true,
          selected_by_user_final: false,
        },
        {
          repository_id: 'repo-b',
          repository_name: 'B',
          score: 0.3,
          level: 'low',
          evidence: 'ev',
          selected_by_ai: false,
          selected_by_user_final: true,
        },
      ],
    })

    const result = await store.applyManualOverride('conv-1', 'trace-1', [
      { repository_id: 'repo-a', selected: false },
      { repository_id: 'repo-b', selected: true },
    ])
    expect(result?.trace_id).toBe('trace-2')
    expect(store.latestTraceIdByConversationId.get('conv-1')).toBe('trace-2')
    expect(store.getLatestSelectedRepoIds('conv-1')).toEqual(['repo-b'])
    expect(mockPostManualOverride).toHaveBeenCalledTimes(1)
  })

  it('applyManualOverride 失败 → 返回 null + latest 不变', async () => {
    const store = useRoutingStore()
    store.upsertTrace(makeTrace(), 'conv-1')
    mockPostManualOverride.mockRejectedValue(new Error('network'))

    const result = await store.applyManualOverride('conv-1', 'trace-1', [
      { repository_id: 'repo-a', selected: false },
    ])
    expect(result).toBeNull()
    expect(store.latestTraceIdByConversationId.get('conv-1')).toBe('trace-1')
  })
})

// ---------------------------------------------------------------------------
// 107-09 Task 1：override 不丢降级与分组事实（107-RESEARCH Pitfall 3 前端半边）
//
// 后端（107-08）已让 override 响应回传 router_version / degraded /
// degrade_reason / block_order 四键；前端若不做「响应优先 + original 兜底」，
// 用户改一次勾选后降级横幅与分组分区就凭空消失。
// ---------------------------------------------------------------------------

/** 带分组/降级事实的候选（override 响应也必须原样带回这三个呈现字段）。 */
function groupedCandidates(): RoutingCandidate[] {
  return [
    {
      repository_id: 'repo-a',
      repository_name: 'A',
      score: 0.9,
      level: 'high',
      evidence: 'ev',
      selected_by_ai: true,
      selected_by_user_final: false,
      group: 'in_project',
      trust: 'trusted',
      score_ranked: 0.95,
    },
    {
      repository_id: 'repo-b',
      repository_name: 'B',
      score: 0.3,
      level: 'low',
      evidence: 'ev',
      selected_by_ai: false,
      selected_by_user_final: true,
      group: 'global',
      trust: 'needs_confirmation',
      score_ranked: 0.28,
    },
  ]
}

function degradedTrace(): RoutingDecisionData {
  return makeTrace({
    router_version: 'v2_stage0_only',
    degraded: true,
    degrade_reason: 'timeout',
    block_order: ['in_project', 'global'],
    candidates: groupedCandidates(),
  })
}

describe('useRoutingStore override 继承降级与分组事实', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockPostManualOverride.mockReset()
  })

  it('响应缺四键 → 从 original 兜底继承（降级横幅与分区不消失）', async () => {
    const store = useRoutingStore()
    store.upsertTrace(degradedTrace(), 'conv-1')
    mockPostManualOverride.mockResolvedValue({
      trace_id: 'trace-2',
      original_trace_id: 'trace-1',
      triggered_by: 'manual_override',
      candidates: groupedCandidates(),
    })

    const result = await store.applyManualOverride('conv-1', 'trace-1', [
      { repository_id: 'repo-a', selected: false },
    ])
    expect(result?.router_version).toBe('v2_stage0_only')
    expect(result?.degraded).toBe(true)
    expect(result?.degrade_reason).toBe('timeout')
    expect(result?.block_order).toEqual(['in_project', 'global'])
    // store 里的新 trace 同样带着这四键（面板读的是 store）
    expect(store.getTrace('trace-2')?.degraded).toBe(true)
  })

  it('响应带四键 → 响应值优先（degraded=false 不被 original 的 true 覆盖）', async () => {
    const store = useRoutingStore()
    store.upsertTrace(degradedTrace(), 'conv-1')
    mockPostManualOverride.mockResolvedValue({
      trace_id: 'trace-2',
      original_trace_id: 'trace-1',
      triggered_by: 'manual_override',
      candidates: groupedCandidates(),
      router_version: 'v2',
      degraded: false,
      degrade_reason: 'unknown',
      block_order: ['global', 'in_project'],
    })

    const result = await store.applyManualOverride('conv-1', 'trace-1', [
      { repository_id: 'repo-a', selected: false },
    ])
    expect(result?.router_version).toBe('v2')
    expect(result?.degraded).toBe(false)
    expect(result?.degrade_reason).toBe('unknown')
    expect(result?.block_order).toEqual(['global', 'in_project'])
  })

  it('override 后候选保留 group / trust / score_ranked', async () => {
    const store = useRoutingStore()
    store.upsertTrace(degradedTrace(), 'conv-1')
    mockPostManualOverride.mockResolvedValue({
      trace_id: 'trace-2',
      original_trace_id: 'trace-1',
      triggered_by: 'manual_override',
      candidates: groupedCandidates(),
    })

    const result = await store.applyManualOverride('conv-1', 'trace-1', [
      { repository_id: 'repo-a', selected: false },
    ])
    expect(result?.candidates.map(c => c.group)).toEqual(['in_project', 'global'])
    expect(result?.candidates.map(c => c.trust)).toEqual(['trusted', 'needs_confirmation'])
    expect(result?.candidates.map(c => c.score_ranked)).toEqual([0.95, 0.28])
  })

  it('original 不在 store 且响应也没给 → 四键为 undefined，不抛', async () => {
    const store = useRoutingStore()
    mockPostManualOverride.mockResolvedValue({
      trace_id: 'trace-2',
      original_trace_id: 'trace-missing',
      triggered_by: 'manual_override',
      candidates: groupedCandidates(),
    })

    const result = await store.applyManualOverride('conv-1', 'trace-missing', [
      { repository_id: 'repo-a', selected: false },
    ])
    expect(result?.trace_id).toBe('trace-2')
    expect(result?.router_version).toBeUndefined()
    expect(result?.degraded).toBeUndefined()
    expect(result?.degrade_reason).toBeUndefined()
    expect(result?.block_order).toBeUndefined()
  })

  it('upsertTrace 整对象透传（detail hydrate 契约：不得改成字段白名单）', () => {
    const store = useRoutingStore()
    const trace = degradedTrace()
    store.upsertTrace(trace, 'conv-1')
    // 后端 detail payload 已出 9 键；store 必须原样保留，否则 hydrate 后
    // 刷新一次降级横幅与分组分区就没了
    expect(store.getTrace('trace-1')).toEqual(trace)
  })
})

// ---------------------------------------------------------------------------
// 107-09 Task 1：chat.ts 两处手工构造 trace 的四键透传
// ---------------------------------------------------------------------------

describe('chat store 构造 routing trace 时透传降级与分组事实', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockPostManualOverride.mockReset()
    window.localStorage.clear()
  })

  it('后端输出契约含四个结果级字段（缺一即实时链路恒 undefined）', () => {
    expect(Object.keys(OUTPUT_SCHEMA.properties)).toEqual(
      expect.arrayContaining([
        'router_version',
        'degraded',
        'degrade_reason',
        'block_order',
      ]),
    )
  })

  it('chat_tool：工具 data 含四键 → 构造的 trace 携带四键', () => {
    const chatStore = useChatStore()
    const routingStore = useRoutingStore()
    chatStore.currentConversationId = 'conv-1'

    chatStore._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: {
        id: 'p_routing',
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_relev',
        name: 'analyze_repository_relevance',
        input: { query: 'foo' },
        status: 'running',
      },
    })
    chatStore._dispatchSSE({
      type: 'part_completed',
      index: 0,
      part: {
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_relev',
        status: 'done',
        result: JSON.stringify({
          output: {
            data: toolOutputData({
              trace_id: 'trace-tool',
              candidates: groupedCandidates(),
              threshold: 0.5,
              total_candidates: 2,
              router_version: 'v1_fallback',
              degraded: true,
              degrade_reason: 'upstream_error',
              block_order: ['global', 'in_project'],
            }),
          },
        }),
      },
    })

    const trace = routingStore.getTrace('trace-tool')
    expect(trace?.router_version).toBe('v1_fallback')
    expect(trace?.degraded).toBe(true)
    expect(trace?.degrade_reason).toBe('upstream_error')
    expect(trace?.block_order).toEqual(['global', 'in_project'])
    expect(trace?.candidates[0]?.group).toBe('in_project')
  })

  it('deep_analysis：无结果级四键 → 四键为 undefined（不填假值）', () => {
    const chatStore = useChatStore()
    const routingStore = useRoutingStore()
    chatStore.currentConversationId = 'conv-1'

    const traceId = '11111111-2222-3333-4444-555555555555'
    chatStore._dispatchSSE({
      type: 'part_started',
      index: 0,
      part: {
        id: 'p_deep',
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_deep',
        name: 'deep_analysis',
        input: {},
        status: 'running',
      },
    })
    chatStore._dispatchSSE({
      type: 'part_completed',
      index: 0,
      part: {
        index: 0,
        type: 'tool_use',
        tool_call_id: 'call_deep',
        status: 'done',
        result: `分析完成\n[cross_repo_relevance:${traceId}]\n${JSON.stringify(groupedCandidates())}`,
      },
    })

    const trace = routingStore.getTrace(traceId)
    expect(trace).toBeTruthy()
    expect(trace?.degraded).toBeUndefined()
    expect(trace?.degrade_reason).toBeUndefined()
    expect(trace?.router_version).toBeUndefined()
    expect(trace?.block_order).toBeUndefined()
    // 候选级呈现字段仍原样透传
    expect(trace?.candidates[1]?.group).toBe('global')
  })
})
