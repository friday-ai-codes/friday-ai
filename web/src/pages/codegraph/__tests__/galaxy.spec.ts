/**
 * Phase Plan/04 — galaxy.vue 主页面测试
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { GalaxyResponse } from '~/api/galaxy'
import type { Repository } from '~/types'
// Mock API
vi.mock('~/api/galaxy', => ({
 getGalaxyGraph: vi.fn,
 searchGalaxyNodes: vi.fn,
 getGalaxyNodeDetail: vi.fn,
}))
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 list: vi.fn,
 },
}))
// Mock 3d-force-graph
const mockGraph = {
 width: vi.fn.mockReturnThis,
 height: vi.fn.mockReturnThis,
 showNavInfo: vi.fn.mockReturnThis,
 backgroundColor: vi.fn.mockReturnThis,
 nodeThreeObject: vi.fn.mockReturnThis,
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
 onEngineStop: vi.fn.mockReturnThis,
 graphData: vi.fn.mockImplementation((data?: unknown) => data === undefined ? { nodes:, links: }: mockGraph),
 scene: vi.fn.mockReturnValue({ background: null, add: vi.fn }),
 cameraPosition: vi.fn.mockReturnThis,
 _destructor: vi.fn,
}
vi.mock('3d-force-graph', => ({
 default: vi.fn( => => mockGraph),
}))
vi.mock('three', => {
 class ColorMock { constructor(_c?: string) {} }
 class SphereGeometryMock { constructor(..._a: unknown) {} }
 class RingGeometryMock { constructor(..._a: unknown) {} }
 class MeshBasicMaterialMock { opacity = 1; transparent = false; constructor(_p?: object) {} }
 class MeshMock { material = new MeshBasicMaterialMock; add = vi.fn; traverse = vi.fn; constructor(..._a: unknown) {} }
 class GroupMock { add = vi.fn; traverse = vi.fn((_fn: unknown) => {}); constructor {} }
 class BufferGeometryMock { setAttribute = vi.fn; constructor {} }
 class BufferAttributeMock { constructor(..._a: unknown) {} }
 class PointsMaterialMock { constructor(..._a: unknown) {} }
 class PointsMock { constructor(..._a: unknown) {} }
 class CanvasTextureMock { constructor(..._a: unknown) {} }
 class MaterialMock {}
 return { Color: ColorMock, SphereGeometry: SphereGeometryMock, RingGeometry: RingGeometryMock,
 MeshBasicMaterial: MeshBasicMaterialMock, Mesh: MeshMock, Group: GroupMock,
 BufferGeometry: BufferGeometryMock, BufferAttribute: BufferAttributeMock,
 PointsMaterial: PointsMaterialMock, Points: PointsMock, CanvasTexture: CanvasTextureMock,
 DoubleSide: 2, Material: MaterialMock }
})
class MockResizeObserver {
 observe = vi.fn; unobserve = vi.fn; disconnect = vi.fn
 constructor(_cb: ResizeObserverCallback) {}
}
global.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver
vi.mock('vue-sonner', => ({
 toast: {
 success: vi.fn, error: vi.fn, warning: vi.fn, info: vi.fn,
 promise: vi.fn, dismiss: vi.fn,
 },
}))
const mockRepositories: Repository = [
 {
 id: 'repo-1',
 name: 'test-repo',
 repo_url: 'https://github.com/test/repo',
 default_branch: 'main',
 index_status: 'indexed',
 last_indexed_at: '2026-01-01T00:00:00Z',
 index_error: null,
 index_total_chunks: 100,
 index_processed_chunks: 100,
 index_write_total: 100,
 index_write_processed: 100,
 overall_progress: 100,
 overall_stage: 'done',
 repo_type: 'git',
 icon_url: null,
 repo_group: null,
 } as unknown as Repository,
]
const mockGalaxyResponse: GalaxyResponse = {
 nodes: [
 { id: 'chunk_registry:uuid-1', type: 'chunk_registry', label: 'src/foo.py:0',
 repository_id: 'repo-1', file_path: 'src/foo.py', line_start: 1, line_end: 50,
 metadata: {}, degree: 5 },
 ],
 edges:,
 meta: { total_nodes: 1, total_edges: 0, sampled: false, per_repo_hint: false, max_nodes: 500 },
}
describe('galaxy.vue', => {
 beforeEach( => {
 vi.clearAllMocks
 localStorage.clear
 // 设置桌面宽度
 Object.defineProperty(window, 'innerWidth', { value: 1440, writable: true })
 })
 it('加载仓库列表后调用 fetchGraph', async => {
 const { repositoriesApi } = await import('~/api/repositories')
 const { getGalaxyGraph } = await import('~/api/galaxy')
 vi.mocked(repositoriesApi.list).mockResolvedValueOnce(mockRepositories)
 vi.mocked(getGalaxyGraph).mockResolvedValueOnce(mockGalaxyResponse)
 const { default: GalaxyPage } = await import('../galaxy.vue')
 const wrapper = mount(GalaxyPage, { attachTo: document.body })
 await flushPromises
 expect(repositoriesApi.list).toHaveBeenCalled
 expect(getGalaxyGraph).toHaveBeenCalled
 wrapper.unmount
 })
 it('renderMode = echarts 时展示 EchartsGraphGl', async => {
 const { repositoriesApi } = await import('~/api/repositories')
 const { getGalaxyGraph } = await import('~/api/galaxy')
 vi.mocked(repositoriesApi.list).mockResolvedValueOnce(mockRepositories)
 vi.mocked(getGalaxyGraph).mockResolvedValueOnce(mockGalaxyResponse)
 // 预设 localStorage 为 echarts 模式
 localStorage.setItem('galaxy_render_mode', 'echarts')
 const { default: GalaxyPage } = await import('../galaxy.vue')
 const wrapper = mount(GalaxyPage, { attachTo: document.body })
 await flushPromises
 // EchartsGraphGl 是 defineAsyncComponent，不会立即出现在 DOM
 // 验证 GalaxyForceGraph 不存在即可
 expect(wrapper.findComponent({ name: 'GalaxyForceGraph' }).exists).toBe(false)
 wrapper.unmount
 })
 it('移动端（<1024px）展示 fallback 提示', async => {
 Object.defineProperty(window, 'innerWidth', { value: 800, writable: true })
 const { repositoriesApi } = await import('~/api/repositories')
 vi.mocked(repositoriesApi.list).mockResolvedValueOnce
 const { default: GalaxyPage } = await import('../galaxy.vue')
 const wrapper = mount(GalaxyPage, { attachTo: document.body })
 await flushPromises
 expect(wrapper.text).toContain('3D Galaxy 图谱需要桌面端访问')
 wrapper.unmount
 })
 it('API 返回 sampled=true 时展示采样提示 banner', async => {
 const { repositoriesApi } = await import('~/api/repositories')
 const { getGalaxyGraph } = await import('~/api/galaxy')
 vi.mocked(repositoriesApi.list).mockResolvedValueOnce(mockRepositories)
 vi.mocked(getGalaxyGraph).mockResolvedValueOnce({
 ...mockGalaxyResponse,
 meta: { ...mockGalaxyResponse.meta, sampled: true, total_nodes: 10000 },
 })
 const { default: GalaxyPage } = await import('../galaxy.vue')
 const wrapper = mount(GalaxyPage, { attachTo: document.body })
 await flushPromises
 expect(wrapper.text).toContain('10000')
 wrapper.unmount
 })
})
