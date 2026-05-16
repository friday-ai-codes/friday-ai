/**
 * Phase Plan — galaxy.vue 集成测试（node-click + URL 同步 + Drawer 接线）
 *
 * 测试策略：
 * - mock 所有子组件（GalaxyForceGraph / GalaxyCommandPalette / NodeDetailDrawer / ECharts）
 * - mock useGalaxyGraph composable（提供 filteredNodes + 各种 ref/fn）
 * - mock vue-router（createMemoryHistory）
 * - 通过 defineExpose 的 vm 钩子直接调用 handleNodeClick / handleCommandPaletteSelect / handleDrawerClose
 * （script setup 默认不暴露内部 ref/fn；测试钩子 defineExpose 已在 galaxy.vue 中显式开放）
 */
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
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
vi.mock('~/api/repositories', => ({
 repositoriesApi: { list: vi.fn.mockResolvedValue([{ id: 'repo-1' }]) },
}))
vi.mock('~/composables/useToast', => ({
 useToast: vi.fn( => ({ warning: vi.fn, error: vi.fn })),
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
interface GalaxyVm {
 handleNodeClick: (n: GalaxyNode) => void
 handleCommandPaletteSelect: (r: GalaxySearchResult) => void
 handleDrawerClose: (open: boolean) => void
 handleDrawerNodeSelect: (id: string) => void
 drawerOpen: boolean
 selectedNodeId: string | null
}
async function mountGalaxy(initialQuery: Record<string, string> = {}) {
 const router = createRouter({
 history: createMemoryHistory,
 routes: [{ path: '/codegraph/galaxy', component: { template: '<div/>' } }],
 })
 await router.push({ path: '/codegraph/galaxy', query: initialQuery })
 // 重置 filteredNodes（每个测试独立）
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
describe('galaxy.vue — Phase 接线', => {
 beforeEach( => {
 vi.clearAllMocks
 mockFocusNode.mockClear
 Object.defineProperty(window, 'innerWidth', { value: 1440, writable: true, configurable: true })
 })
 afterEach( => {
 document.body.innerHTML = ''
 })
 it('挂载后：GalaxyCommandPalette 与 NodeDetailDrawer 都在 DOM 中', async => {
 const { wrapper } = await mountGalaxy
 expect(wrapper.find('.mock-command-palette').exists).toBe(true)
 expect(wrapper.find('.mock-drawer').exists).toBe(true)
 wrapper.unmount
 })
 it('初始渲染：Drawer 关闭，CommandPalette 关闭', async => {
 const { wrapper } = await mountGalaxy
 const drawer = wrapper.find('.mock-drawer')
 const palette = wrapper.find('.mock-command-palette')
 expect(drawer.attributes('data-open')).toBe('false')
 expect(palette.attributes('data-open')).toBe('false')
 wrapper.unmount
 })
 it('handleNodeClick → drawerOpen=true，selectedNodeId 更新', async => {
 const { wrapper } = await mountGalaxy
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleNodeClick(makeNode({ id: 'symbol:myfn' }))
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('symbol:myfn')
 wrapper.unmount
 })
 it('handleNodeClick 后 URL 包含 ?node=', async => {
 const { wrapper, router } = await mountGalaxy
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleNodeClick(makeNode({ id: 'symbol:url-test' }))
 await flushPromises
 expect(router.currentRoute.value.query.node).toBe('symbol:url-test')
 wrapper.unmount
 })
 it('handleDrawerClose(false) 清除 URL 中 ?node=', async => {
 const { wrapper, router } = await mountGalaxy
 const vm = wrapper.vm as unknown as GalaxyVm
 vm.handleNodeClick(makeNode({ id: 'symbol:clear-test' }))
 await flushPromises
 expect(router.currentRoute.value.query.node).toBe('symbol:clear-test')
 vm.handleDrawerClose(false)
 await flushPromises
 expect(router.currentRoute.value.query.node).toBeUndefined
 wrapper.unmount
 })
 it('handleCommandPaletteSelect 打开 Drawer 并设置 nodeId', async => {
 const { wrapper } = await mountGalaxy
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
 const { wrapper } = await mountGalaxy({ node: 'symbol:initial' })
 const vm = wrapper.vm as unknown as GalaxyVm
 // 模拟 filteredNodes 数据就绪
 mockFilteredNodes.value = [makeNode({ id: 'symbol:initial' })]
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('symbol:initial')
 wrapper.unmount
 })
})
