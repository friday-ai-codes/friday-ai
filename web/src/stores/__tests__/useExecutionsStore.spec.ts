/**
 * useExecutionsStore.spec.ts — OBS-01 node_failed 写 error 字段 + OBS-03 stats 语义 RED 测试
 *
 * - OBS-01：node_failed WS 消息应把 error_message/error_code 写入对应 NodeExecution
 *   （当前实现仅 failed_nodes++，故 RED；由 21-06 实现转绿）。
 * - OBS-01 防御：缺 error 字段的 node_failed 消息不得破坏 store 状态（防御读 != null）。
 * - OBS-03：stats 应区分 execution 级挂起（suspended）与 node 级 waiting_approval
 *   （当前 stats 把 execution.status==='waiting_approval' 当真且无 suspended 统计，故 RED）。
 *
 * WS 入口：store 未导出 handleWebSocketMessage（内部函数），通过 mock @vueuse/core
 * 的 useWebSocket 返回受控 `data` ref，写入 JSON 触发 store 内部 watch → handler。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'

// 受控 WS data ref：store 内部 watch(wsData) 监听它，写入即触发消息处理
const wsData = ref<string | null>(null)

vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  return {
    ...actual,
    useWebSocket: () => ({
      data: wsData,
      close: vi.fn(),
      open: vi.fn(),
      status: ref<'OPEN' | 'CONNECTING' | 'CLOSED' | 'CLOSING'>('CLOSED'),
      send: vi.fn(),
    }),
  }
})

vi.mock('~/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const { useExecutionsStore } = await import('../useExecutionsStore')

type Store = ReturnType<typeof useExecutionsStore>

function makeExecution(overrides: Record<string, any> = {}) {
  return {
    id: 'exec-1',
    workflow: 'wf-1',
    workflow_name: 'wf',
    task: null,
    status: 'running',
    trigger_type: 'manual',
    triggered_by: null,
    triggered_by_name: null,
    trigger_data: {},
    trigger_log_id: null,
    resumed_from: null,
    workflow_definition: null,
    context: {},
    input_data: {},
    output_data: {},
    error_message: '',
    error_node_id: null,
    total_nodes: 1,
    completed_nodes: 0,
    failed_nodes: 0,
    skipped_nodes: 0,
    node_executions: [
      {
        id: 'ne1',
        node: 'n1',
        node_name: 'N1',
        node_type: 'test',
        status: 'running',
        input_data: {},
        output_data: {},
        error_message: '',
        error_traceback: '',
        attempt: 1,
        approval_data: {},
        container_id: '',
        container_logs: '',
        duration: null,
        created_at: '2026-06-13T00:00:00Z',
        started_at: null,
        completed_at: null,
        sub_step_progress: null,
        logs: null,
        error_code: null,
      },
    ],
    duration: null,
    progress: 0,
    created_at: '2026-06-13T00:00:00Z',
    started_at: null,
    completed_at: null,
    timeout_at: null,
    ...overrides,
  } as any
}

/** 通过受控 wsData 注入一条 WS 消息并等待 store watch 处理 */
async function sendWsMessage(payload: Record<string, any>) {
  wsData.value = JSON.stringify(payload)
  await nextTick()
}

describe('useExecutionsStore — OBS-01 node_failed', () => {
  let store: Store

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    wsData.value = null
    store = useExecutionsStore()
    store.currentExecution = makeExecution()
  })

  it('test_node_failed_writes_error_message', async () => {
    // OBS-01：node_failed 应把 error_message/error_code 写入对应 NodeExecution
    await sendWsMessage({
      event: 'node_failed',
      node_id: 'n1',
      error_message: '变量解析失败',
      error_code: 'VAR_RESOLUTION_FAILED',
    })

    expect(store.currentExecution!.failed_nodes).toBe(1)
    expect(store.currentExecution!.node_executions[0].error_message).toBe('变量解析失败')
    expect(store.currentExecution!.node_executions[0].error_code).toBe('VAR_RESOLUTION_FAILED')
  })

  it('test_node_failed_without_error_fields_is_safe', async () => {
    // OBS-01 防御：缺 error 字段不得抛错，且不得把已有 error_message 覆盖为 undefined
    store.currentExecution!.node_executions[0].error_message = '原始错误'

    await sendWsMessage({ event: 'node_failed', node_id: 'n1' })

    expect(store.currentExecution!.failed_nodes).toBe(1)
    // 防御读：未传 error_message 时保持原值（!= null 保护，Pitfall 5）
    expect(store.currentExecution!.node_executions[0].error_message).toBe('原始错误')
  })
})

describe('useExecutionsStore — OBS-03 stats 语义', () => {
  let store: Store

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    store = useExecutionsStore()
  })

  it('test_stats_execution_waiting_uses_suspended', () => {
    // execution A：execution 级挂起（suspended）
    // execution B：running，但 node 级含 waiting_approval（不应被算作 execution 级挂起）
    store.executions = [
      makeExecution({ id: 'a', status: 'suspended', node_executions: [] }),
      makeExecution({
        id: 'b',
        status: 'running',
        node_executions: [
          { id: 'neb', node: 'nb', status: 'waiting_approval', error_message: '', error_code: null },
        ],
      }),
    ]

    // OBS-03：stats 应以 execution 级 suspended 统计"挂起"，仅 A 命中
    expect((store.stats as any).suspended).toBe(1)
  })
})
