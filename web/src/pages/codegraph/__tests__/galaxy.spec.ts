/**
 * galaxy.vue 集成测试
 *
 * 覆盖两套视图模式：
 * - overview (默认 URL 无 repo_ids)：L2 仓库节点图，点击仓库节点下钻
 * - detail (URL ?repo_ids=...)：L1 细粒度图，节点点击打开 Drawer
 *
 * 测试策略：
 * - mock 所有子组件 (GalaxyForceGraph / CommandPalette / NodeDetailDrawer / Echarts / Breadcrumb / SpaceFilter)
 * - mock useGalaxyGraph composable
 * - mock getGalaxyRepoGraph API
 * - mock useSpacesStore
 * - 通过 defineExpose 的 vm 钩子直接调用 handler
 */
import type { GalaxyNode, GalaxyRepoNode, GalaxySearchResult } from '~/api/galaxy'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import { ref } from 'vue'
// ============================================================================
// Mocks
// ============================================================================
const mockFilteredNodes = ref<GalaxyNode>
vi.mock('~/composables/useGalaxyGraph', => ({
 useGalaxyGraph: vi.fn( => ({
 meta: ref(null),
 loading: ref(false),
 error: ref(null),
 renderMode: ref('force3d'),
 maxNodes: ref(500),
 fps: ref(60),
 lowFpsDetected: ref(false),
 activeNodeTypes: ref(new Set),
 activeEdgeTypes: ref(new Set),
 filteredNodes: mockFilteredNodes,
 filteredEdges: ref,
 fetchGraph: vi.fn,
 setRenderMode: vi.fn,
 onFpsUpdate: vi.fn,
 toggleNodeType: vi.fn,
 toggleEdgeType: vi.fn,
 setAllNodeTypes: vi.fn,
 setAllEdgeTypes: vi.fn,
 })),
}))
const mockGetGalaxyRepoGraph = vi.fn.mockResolvedValue({
 nodes:,
 edges:,
 meta: { total_nodes: 0, total_edges: 0, sampled: false, by_node_type: {}, per_repo_hint: false },
})
vi.mock('~/api/galaxy', async (importOriginal) => {
 const actual = await importOriginal<typeof import('~/api/galaxy')>
 return {
 ...actual,
 getGalaxyRepoGraph: mockGetGalaxyRepoGraph,
 }
})
vi.mock('~/composables/useToast', => ({
 useToast: vi.fn( => ({ warning: vi.fn, error: vi.fn, success: vi.fn })),
}))
vi.mock('~/stores/spaces', => ({
 useSpacesStore: vi.fn( => ({
 spaces:,
 loading: false,
 fetchSpaces: vi.fn.mockResolvedValue(undefined),
 })),
}))
const mockFocusNode = vi.fn
vi.mock('~/components/galaxy/GalaxyForceGraph.vue', => ({
 default: {
 name: 'GalaxyForceGraph',
 props: ['nodes', 'edges', 'loading'],
 emits: ['node-click', 'fps-update'],
 template: '<div class="mock-force-graph" />',
 setup(_: unknown, { expose }: { expose: (obj: Record<string, unknown>) => void }) {
 expose({ focusNode: mockFocusNode })
 return {}
 },
 },
}))
vi.mock('~/components/galaxy/GalaxyControls.vue', => ({
 default: { name: 'GalaxyControls', template: '<div class="mock-controls" />' },
}))
vi.mock('~/components/galaxy/GalaxyLegend.vue', => ({
 default: { name: 'GalaxyLegend', template: '<div class="mock-legend" />' },
}))
vi.mock('~/components/galaxy/EchartsGraphGl.vue', => ({
 default: { name: 'EchartsGraphGl', template: '<div class="mock-echarts" />' },
}))
vi.mock('~/components/galaxy/GalaxyCommandPalette.vue', => ({
 default: {
 name: 'GalaxyCommandPalette',
 props: ['modelValue', 'nodes'],
 emits: ['update:modelValue', 'node-select'],
 template: '<div class="mock-command-palette":data-open="String(modelValue)" />',
 },
}))
vi.mock('~/components/galaxy/NodeDetailDrawer.vue', => ({
 default: {
 name: 'NodeDetailDrawer',
 props: ['nodeId', 'modelValue'],
 emits: ['update:modelValue', 'node-select'],
 template: '<div class="mock-drawer":data-open="String(modelValue)":data-node-id="nodeId ?? \'\'" />',
 },
}))
vi.mock('~/components/galaxy/GalaxyBreadcrumb.vue', => ({
 default: {
 name: 'GalaxyBreadcrumb',
 props: ['mode', 'spaceId', 'repoLabel'],
 emits: ['update:spaceId', 'back'],
 template: '<div class="mock-breadcrumb":data-mode="mode" />',
 },
}))
vi.mock('~/components/galaxy/SpaceFilter.vue', => ({
 default: {
 name: 'SpaceFilter',
 props: ['modelValue'],
 emits: ['update:modelValue'],
 template: '<div class="mock-space-filter" />',
 },
}))
// ============================================================================
// 工具函数
// ============================================================================
function makeNode(overrides: Partial<GalaxyNode> = {}): GalaxyNode {
 return {
 id: 'symbol:test',
 type: 'symbol',
 label: 'TestFunc',
 file_path: 'src/test.ts',
 repository_id: 'repo-1',
 line_start: 1,
 line_end: 5,
 metadata: {},
 degree: 3,
 ...overrides,
 }
}
function makeRepoNode(id: string): GalaxyRepoNode {
 return {
 id: `repo:${id}`,
 type: 'repository',
 label: `repo-${id}`,
 file_path: '',
 repository_id: id,
 line_start: 0,
 line_end: 0,
 metadata: { git_platform: 'github', space_ids:, endpoint_count: 0, callsite_count: 0 },
 degree: 0,
 }
}
interface GalaxyVm {
 handleDetailNodeClick: (n: GalaxyNode) => void
 handleOverviewNodeClick: (n: GalaxyNode) => void
 handleCommandPaletteSelect: (r: GalaxySearchResult) => void
 handleDrawerClose: (open: boolean) => void
 handleDrawerNodeSelect: (id: string) => void
 handleBackToOverview: => void
 drawerOpen: boolean
 selectedNodeId: string | null
 viewMode: 'overview' | 'detail'
}
async function mountGalaxy(initialQuery: Record<string, string> = {}) {
 const router = createRouter({
 history: createMemoryHistory,
 routes: [{ path: '/codegraph/galaxy', component: { template: '<div/>' } }],
 })
 await router.push({ path: '/codegraph/galaxy', query: initialQuery })
 mockFilteredNodes.value =
 const GalaxyPage = await import('~/pages/codegraph/galaxy.vue')
 const wrapper = mount(GalaxyPage.default, {
 global: { plugins: [router] },
 attachTo: document.body,
 })
 await flushPromises
 await flushPromises
 return { wrapper, router }
}
// ============================================================================
// Tests
// ============================================================================
describe('galaxy.vue — viewMode 路由', => {
 beforeEach( => {
 vi.clearAllMocks
 mockFocusNode.mockClear
 Object.defineProperty(window, 'innerWidth', { value: 1440, writable: true, configurable: true })
 })
 afterEach( => {
 document.body.innerHTML = ''
 })
 it('无 repo_ids → viewMode=overview，加载仓库总览', async => {
 const { wrapper } = await mountGalaxy
 const vm = wrapper.vm as unknown as GalaxyVm
 expect(vm.viewMode).toBe('overview')
 expect(mockGetGalaxyRepoGraph).toHaveBeenCalled
 // overview 模式不渲染 Drawer 与 CommandPalette
 expect(wrapper.find('.mock-drawer').exists).toBe(false)
 expect(wrapper.find('.mock-command-palette').exists).toBe(false)
 wrapper.unmount
 })
 it('?repo_ids=X → viewMode=detail，渲染 Drawer/CommandPalette', async => {
 const { wrapper } = await mountGalaxy({ repo_ids: 'repo-1' })
 const vm = wrapper.vm as unknown as GalaxyVm
 expect(vm.viewMode).toBe('detail')
 expect(wrapper.find('.mock-drawer').exists).toBe(true)
 expect(wrapper.find('.mock-command-palette').exists).toBe(true)
 wrapper.unmount
 })
 it('handleOverviewNodeClick(repository node) → router.push 带 repo_ids', async => {
 const { wrapper, router } = await mountGalaxy
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleOverviewNodeClick(makeRepoNode('abc-123'))
 await flushPromises
 expect(router.currentRoute.value.query.repo_ids).toBe('abc-123')
 wrapper.unmount
 })
 it('handleBackToOverview → 清除 repo_ids，回到 overview', async => {
 const { wrapper, router } = await mountGalaxy({ repo_ids: 'repo-1' })
 const vm = wrapper.vm as unknown as GalaxyVm
 expect(vm.viewMode).toBe('detail')
 vm.handleBackToOverview
 await flushPromises
 expect(router.currentRoute.value.query.repo_ids).toBeUndefined
 expect(vm.viewMode).toBe('overview')
 wrapper.unmount
 })
})
describe('galaxy.vue — detail 模式 Drawer 接线', => {
 beforeEach( => {
 vi.clearAllMocks
 mockFocusNode.mockClear
 Object.defineProperty(window, 'innerWidth', { value: 1440, writable: true, configurable: true })
 })
 afterEach( => {
 document.body.innerHTML = ''
 })
 it('初始渲染：Drawer 关闭，CommandPalette 关闭', async => {
 const { wrapper } = await mountGalaxy({ repo_ids: 'repo-1' })
 expect(wrapper.find('.mock-drawer').attributes('data-open')).toBe('false')
 expect(wrapper.find('.mock-command-palette').attributes('data-open')).toBe('false')
 wrapper.unmount
 })
 it('handleDetailNodeClick → drawerOpen=true，selectedNodeId 更新', async => {
 const { wrapper } = await mountGalaxy({ repo_ids: 'repo-1' })
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleDetailNodeClick(makeNode({ id: 'symbol:myfn' }))
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('symbol:myfn')
 wrapper.unmount
 })
 it('handleDetailNodeClick 后 URL 包含 ?node=', async => {
 const { wrapper, router } = await mountGalaxy({ repo_ids: 'repo-1' })
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleDetailNodeClick(makeNode({ id: 'symbol:url-test' }))
 await flushPromises
 expect(router.currentRoute.value.query.node).toBe('symbol:url-test')
 wrapper.unmount
 })
 it('handleDrawerClose(false) 清除 URL 中 ?node=', async => {
 const { wrapper, router } = await mountGalaxy({ repo_ids: 'repo-1' })
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleDetailNodeClick(makeNode({ id: 'symbol:clear-test' }))
 await flushPromises
 expect(router.currentRoute.value.query.node).toBe('symbol:clear-test')
 vm.handleDrawerClose(false)
 await flushPromises
 expect(router.currentRoute.value.query.node).toBeUndefined
 wrapper.unmount
 })
 it('handleCommandPaletteSelect 打开 Drawer 并设置 nodeId', async => {
 const { wrapper } = await mountGalaxy({ repo_ids: 'repo-1' })
 const vm = wrapper.vm as unknown as GalaxyVm
 const result: GalaxySearchResult = {
 id: 'endpoint:api',
 type: 'endpoint',
 label: 'POST /api/users',
 file_path: 'server/views.py',
 repository_id: 'repo-1',
 degree: 10,
 }
 vm.handleCommandPaletteSelect(result)
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('endpoint:api')
 wrapper.unmount
 })
 it('初始 URL ?node=symbol:initial → filteredNodes 就绪时自动打开 Drawer', async => {
 const { wrapper } = await mountGalaxy({ repo_ids: 'repo-1', node: 'symbol:initial' })
 const vm = wrapper.vm as unknown as GalaxyVm
 mockFilteredNodes.value = [makeNode({ id: 'symbol:initial' })]
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('symbol:initial')
 wrapper.unmount
 })
})
