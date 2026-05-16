/**
 * Phase Plan — GalaxyForceGraph.vue 组件测试
 * 使用 mock 替换 3d-force-graph 和 THREE，绕过 WebGL 环境限制
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GalaxyEdge, GalaxyNode } from '~/api/galaxy'
// Mock 3d-force-graph
const mockGraph = {
 width: vi.fn.mockReturnThis,
 height: vi.fn.mockReturnThis,
 showNavInfo: vi.fn.mockReturnThis,
 backgroundColor: vi.fn.mockReturnThis,
 nodeThreeObject: vi.fn.mockImplementation((fn?: unknown) => {
 if (fn === undefined)
 return vi.fn
 return mockGraph
 }),
 nodeThreeObjectExtend: vi.fn.mockReturnThis,
 nodeLabel: vi.fn.mockReturnThis,
 linkColor: vi.fn.mockReturnThis,
 linkWidth: vi.fn.mockReturnThis,
 linkOpacity: vi.fn.mockReturnThis,
 linkParticles: vi.fn.mockReturnThis,
 linkParticleSpeed: vi.fn.mockReturnThis,
 linkParticleColor: vi.fn.mockReturnThis,
 onNodeHover: vi.fn.mockReturnThis,
 onNodeClick: vi.fn.mockReturnThis,
 d3Force: vi.fn.mockReturnThis,
 cooldownTicks: vi.fn.mockReturnThis,
 onEngineStop: vi.fn.mockImplementation((cb: => void) => {
 // 立即调用回调（模拟引擎停止）
 setTimeout(cb, 0)
 return mockGraph
 }),
 graphData: vi.fn.mockImplementation((data?: unknown) => {
 if (data === undefined) {
 // getter 模式：返回当前图数据
 return { nodes:, links: }
 }
 return mockGraph // setter 模式：链式
 }),
 scene: vi.fn.mockReturnValue({
 background: null,
 add: vi.fn,
 }),
 camera: vi.fn.mockReturnValue({}),
 renderer: vi.fn.mockReturnValue({}),
 controls: vi.fn.mockReturnValue({}),
 cameraPosition: vi.fn.mockReturnThis,
 _destructor: vi.fn,
}
vi.mock('3d-force-graph', => ({
 default: vi.fn( => => mockGraph),
}))
// Mock THREE.js（使用 class 语法确保 new 操作符正确工作）
vi.mock('three', => {
 class ColorMock {
 r = 0; g = 0; b = 0; isColor = true
 constructor(_color?: string) {}
 }
 class SphereGeometryMock { constructor(..._args: unknown) {} }
 class RingGeometryMock { constructor(..._args: unknown) {} }
 class MeshBasicMaterialMock {
 opacity = 1; transparent = false
 constructor(_params?: object) {}
 }
 class MeshMock {
 material = new MeshBasicMaterialMock
 add = vi.fn
 traverse = vi.fn
 constructor(..._args: unknown) {}
 }
 class GroupMock {
 add = vi.fn
 traverse = vi.fn((fn: (child: object) => void) => { fn(new MeshMock) })
 constructor {}
 }
 class BufferGeometryMock {
 setAttribute = vi.fn
 constructor {}
 }
 class BufferAttributeMock { constructor(..._args: unknown) {} }
 class PointsMaterialMock { constructor(..._args: unknown) {} }
 class PointsMock { constructor(..._args: unknown) {} }
 class CanvasTextureMock { constructor(..._args: unknown) {} }
 class MaterialMock {}
 return {
 Color: ColorMock,
 SphereGeometry: SphereGeometryMock,
 RingGeometry: RingGeometryMock,
 MeshBasicMaterial: MeshBasicMaterialMock,
 Mesh: MeshMock,
 Group: GroupMock,
 BufferGeometry: BufferGeometryMock,
 BufferAttribute: BufferAttributeMock,
 PointsMaterial: PointsMaterialMock,
 Points: PointsMock,
 CanvasTexture: CanvasTextureMock,
 DoubleSide: 2,
 Material: MaterialMock,
 }
})
// Mock ResizeObserver（需要 class 形式的构造函数）
class MockResizeObserver {
 observe = vi.fn
 unobserve = vi.fn
 disconnect = vi.fn
 constructor(_callback: ResizeObserverCallback) {}
}
global.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver
const mockNodes: GalaxyNode = [
 {
 id: 'chunk_registry:uuid-1',
 type: 'chunk_registry',
 label: 'src/foo.py:0',
 repository_id: 'repo-1',
 file_path: 'src/foo.py',
 line_start: 1,
 line_end: 50,
 metadata: {},
 degree: 5,
 },
 {
 id: 'endpoint:uuid-2',
 type: 'endpoint',
 label: 'GET /api/users/',
 repository_id: 'repo-1',
 file_path: 'src/views.py',
 line_start: 10,
 line_end: 30,
 metadata: {},
 degree: 8,
 },
]
const mockEdges: GalaxyEdge = [
 {
 id: 'edge-1',
 source: 'chunk_registry:uuid-1',
 target: 'endpoint:uuid-2',
 edge_type: 'API_CALLS',
 weight: 0.9,
 repository_id: 'repo-1',
 target_repository_id: 'repo-2',
 metadata: {},
 },
]
describe('GalaxyForceGraph.vue', => {
 beforeEach( => {
 vi.clearAllMocks
 vi.useFakeTimers
 })
 it('挂载时初始化 3d-force-graph 实例', async => {
 const ForceGraph3D = (await import('3d-force-graph')).default
 const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')
 const wrapper = mount(GalaxyForceGraph, {
 props: {
 nodes: mockNodes,
 edges: mockEdges,
 },
 attachTo: document.body,
 })
 await flushPromises
 expect(ForceGraph3D).toHaveBeenCalled
 wrapper.unmount
 })
 it('props.nodes 变化时更新 graphData', async => {
 const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')
 const wrapper = mount(GalaxyForceGraph, {
 props: { nodes: mockNodes, edges: mockEdges },
 attachTo: document.body,
 })
 await flushPromises
 const initialCallCount = mockGraph.graphData.mock.calls.length
 // 更新 props
 await wrapper.setProps({ nodes: [...mockNodes, { ...mockNodes[0], id: 'new-node' }] })
 await flushPromises
 expect(mockGraph.graphData.mock.calls.length).toBeGreaterThan(initialCallCount)
 wrapper.unmount
 })
 it('onUnmounted 时调用 graph._destructor', async => {
 const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')
 const wrapper = mount(GalaxyForceGraph, {
 props: { nodes: mockNodes, edges: mockEdges },
 attachTo: document.body,
 })
 await flushPromises
 wrapper.unmount
 expect(mockGraph._destructor).toHaveBeenCalled
 })
 it('emit node-click 正确触发', async => {
 const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')
 const wrapper = mount(GalaxyForceGraph, {
 props: { nodes: mockNodes, edges: mockEdges },
 attachTo: document.body,
 })
 await flushPromises
 // 获取 onNodeClick 回调并调用
 const clickCallback = mockGraph.onNodeClick.mock.calls[0]?.[0]
 if (clickCallback) {
 clickCallback({ id: 'chunk_registry:uuid-1', type: 'chunk_registry' })
 }
 const emitted = wrapper.emitted('node-click')
 expect(emitted).toBeTruthy
 if (emitted) {
 expect((emitted[0] as GalaxyNode)[0].id).toBe('chunk_registry:uuid-1')
 }
 wrapper.unmount
 })
 it('emit node-hover 防抖后正确触发', async => {
 const { default: GalaxyForceGraph } = await import('../GalaxyForceGraph.vue')
 const wrapper = mount(GalaxyForceGraph, {
 props: { nodes: mockNodes, edges: mockEdges },
 attachTo: document.body,
 })
 await flushPromises
 const hoverCallback = mockGraph.onNodeHover.mock.calls[0]?.[0]
 if (hoverCallback) {
 hoverCallback({ id: 'endpoint:uuid-2', type: 'endpoint' }, null)
 }
 // 防抖前不应 emit
 expect(wrapper.emitted('node-hover')).toBeFalsy
 // 推进 100ms 防抖时间
 vi.advanceTimersByTime(150)
 expect(wrapper.emitted('node-hover')).toBeTruthy
 wrapper.unmount
 })
})
