/**
 * useExecutionsStore P5 生命周期投影消费单测。
 *
 * 覆盖 handleWebSocketMessage 对 WS 新增 lifecycle/round/max_rounds 字段的消费：
 * 写入对应 NodeExecution、缺 round 时清空、缺 lifecycle 时不覆盖既有值。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useExecutionsStore } from '~/stores/useExecutionsStore'

function makeExecution() {
  return {
    id: 'exec-1',
    node_executions: [
      { id: 'ne-1', node: 'node-1', status: 'running' },
    ],
  } as any
}

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('useExecutionsStore - handleWebSocketMessage 生命周期投影', () => {
  it('消费 lifecycle/round/max_rounds 写入对应 NodeExecution', () => {
    const store = useExecutionsStore()
    store.currentExecution = makeExecution()

    store.handleWebSocketMessage({
      event: 'node_started',
      execution_id: 'exec-1',
      node_id: 'node-1',
      node_status: 'waiting_input',
      lifecycle: 'waiting_clarification',
      round: 2,
      max_rounds: 6,
    })

    const ne = store.currentExecution!.node_executions[0]
    expect(ne.status).toBe('waiting_input')
    expect(ne.lifecycle).toBe('waiting_clarification')
    expect(ne.round).toBe(2)
    expect(ne.max_rounds).toBe(6)
  })

  it('lifecycle 在场但 round 缺省 → round 清空（相位回到无轮次态）', () => {
    const store = useExecutionsStore()
    store.currentExecution = makeExecution()
    store.currentExecution!.node_executions[0].round = 3

    store.handleWebSocketMessage({
      event: 'node_completed',
      execution_id: 'exec-1',
      node_id: 'node-1',
      node_status: 'completed',
      lifecycle: 'produced',
    })

    const ne = store.currentExecution!.node_executions[0]
    expect(ne.lifecycle).toBe('produced')
    expect(ne.round).toBeNull()
  })

  it('缺 lifecycle 字段不覆盖既有生命周期值', () => {
    const store = useExecutionsStore()
    store.currentExecution = makeExecution()
    store.currentExecution!.node_executions[0].lifecycle = 'revising'
    store.currentExecution!.node_executions[0].round = 1

    store.handleWebSocketMessage({
      event: 'node_started',
      execution_id: 'exec-1',
      node_id: 'node-1',
      node_status: 'running',
    })

    const ne = store.currentExecution!.node_executions[0]
    expect(ne.status).toBe('running')
    expect(ne.lifecycle).toBe('revising')
    expect(ne.round).toBe(1)
  })
})
