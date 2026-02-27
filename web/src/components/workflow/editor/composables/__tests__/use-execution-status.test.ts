import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { mapBackendStatus } from '../useExecutionStatus'
// Mock @vue-flow/core
const mockUpdateNodeData = vi.fn
const mockGetEdges = ref<any>
const mockGetNodes = ref<any>
vi.mock('@vue-flow/core', => ({
 useVueFlow: => ({
 updateNodeData: mockUpdateNodeData,
 getEdges: mockGetEdges,
 getNodes: mockGetNodes,
 }),
}))
// Mock useExecutionsStore
const mockCurrentExecution = ref<any>(null)
const mockWsStatus = ref('CLOSED')
vi.mock('~/stores/useExecutionsStore', => ({
 useExecutionsStore: => ({
 currentExecution: mockCurrentExecution,
 wsStatus: mockWsStatus,
 }),
}))
// Mock pinia storeToRefs to pass through refs as-is
vi.mock('pinia', => ({
 storeToRefs: (store: any) => store,
}))
describe('mapBackendStatus', => {
 it('maps "running" to "running"', => {
 expect(mapBackendStatus('running')).toBe('running')
 })
 it('maps "completed" to "success"', => {
 expect(mapBackendStatus('completed')).toBe('success')
 })
 it('maps "failed" to "failed"', => {
 expect(mapBackendStatus('failed')).toBe('failed')
 })
 it('maps "skipped" to "skipped"', => {
 expect(mapBackendStatus('skipped')).toBe('skipped')
 })
 it('maps unknown status to "idle"', => {
 expect(mapBackendStatus('pending')).toBe('idle')
 expect(mapBackendStatus('queued')).toBe('idle')
 expect(mapBackendStatus('cancelled')).toBe('idle')
 })
 it('maps empty string to "idle"', => {
 expect(mapBackendStatus('')).toBe('idle')
 })
})
describe('useExecutionStatus edge updates', => {
 beforeEach( => {
 mockUpdateNodeData.mockClear
 mockGetEdges.value =
 mockGetNodes.value =
 mockCurrentExecution.value = null
 mockWsStatus.value = 'CLOSED'
 })
 it('sets incoming edges to flowing when node is running', async => {
 // 准备边数据：edge-1 指向 node-B
 mockGetEdges.value = [
 { id: 'edge-1', source: 'node-A', target: 'node-B', data: {} },
 { id: 'edge-2', source: 'node-B', target: 'node-C', data: {} },
 ]
 // 动态导入以触发 watch 注册
 const { useExecutionStatus } = await import('../useExecutionStatus')
 useExecutionStatus
 // 模拟 WS 推送：node-B 开始运行
 mockCurrentExecution.value = {
 id: 'exec-1',
 node_executions: [
 { node: 'node-B', status: 'running' },
 ],
 }
 // 等待 watch 触发
 await new Promise(r => setTimeout(r, 10))
 // 验证 node-B 的入边（edge-1）被设为 flowing
 expect(mockGetEdges.value[0].data.flowing).toBe(true)
 // node-B 的出边（edge-2）flowing 为 false（被 resetAllStatuses 初始化）
 expect(mockGetEdges.value[1].data.flowing).toBe(false)
 })
 it('stops flowing on incoming edges when node completes', async => {
 mockGetEdges.value = [
 { id: 'edge-1', source: 'node-A', target: 'node-B', data: { flowing: true } },
 ]
 const { useExecutionStatus } = await import('../useExecutionStatus')
 useExecutionStatus
 mockCurrentExecution.value = {
 id: 'exec-2',
 node_executions: [
 { node: 'node-B', status: 'completed' },
 ],
 }
 await new Promise(r => setTimeout(r, 10))
 expect(mockGetEdges.value[0].data.flowing).toBe(false)
 })
 it('marks incoming edges as skipped when node is skipped', async => {
 mockGetEdges.value = [
 { id: 'edge-1', source: 'node-A', target: 'node-B', data: {} },
 ]
 const { useExecutionStatus } = await import('../useExecutionStatus')
 useExecutionStatus
 mockCurrentExecution.value = {
 id: 'exec-3',
 node_executions: [
 { node: 'node-B', status: 'skipped' },
 ],
 }
 await new Promise(r => setTimeout(r, 10))
 expect(mockGetEdges.value[0].data.skipped).toBe(true)
 expect(mockGetEdges.value[0].data.flowing).toBe(false)
 })
})
