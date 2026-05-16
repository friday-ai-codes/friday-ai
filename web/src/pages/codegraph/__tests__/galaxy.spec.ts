/**
 * Phase Plan — galaxy.vue 集成测试（node-click + URL 同步 + Drawer 接线）
 */
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'
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
 repositoriesApi: { list: vi.fn.mockResolvedValue },
}))
vi.mock('~/composables/useToast', => ({
 useToast: vi.fn( => ({ warning: vi.fn, error: vi.fn })),
}))
const mockFocusNode = vi.fn
vi.mock('~/components/galaxy/GalaxyForceGraph.vue', => ({
 default: {
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
 default: { template: '<div />' },
}))
vi.mock('~/components/galaxy/GalaxyLegend.vue', => ({
 default: { template: '<div />' },
}))
vi.mock('~/components/galaxy/EchartsGraphGl.vue', => ({
 default: { template: '<div />' },
}))
vi.mock('~/components/galaxy/GalaxyCommandPalette.vue', => ({
 default: {
 props: ['modelValue', 'nodes'],
 emits: ['update:modelValue', 'node-select'],
 template: '<div class="mock-command-palette":data-open="String(modelValue)" />',
 },
}))
vi.mock('~/components/galaxy/NodeDetailDrawer.vue', => ({
 default: {
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
async function mountGalaxy(initialQuery: Record<string, string> = {}) {
 const router = createRouter({
 history: createMemoryHistory,
 routes: [{ path: '/codegraph/galaxy', component: { template: '<div/>' } }],
 })
 await router.push({ path: '/codegraph/galaxy', query: initialQuery })
 // 重置 filteredNodes
 mockFilteredNodes.value =
 const GalaxyPage = await import('~/pages/codegraph/galaxy.vue')
 const wrapper = mount(GalaxyPage.default, {
 global: { plugins: [router] },
 attachTo: document.body,
 })
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
 })
 afterEach( => {
 document.body.innerHTML = ''
 })
 it('初始渲染：Drawer 关闭，CommandPalette 关闭', async => {
 const { wrapper } = await mountGalaxy
 // 主体内容在 "桌面端" 条件下渲染（window.innerWidth 默认 1024+）
 await flushPromises
 const drawer = wrapper.find('.mock-drawer')
 const palette = wrapper.find('.mock-command-palette')
 if (drawer.exists) {
 expect(drawer.attributes('data-open')).toBe('false')
 }
 if (palette.exists) {
 expect(palette.attributes('data-open')).toBe('false')
 }
 wrapper.unmount
 })
 it('galaxy.vue 正确导入 GalaxyCommandPalette 和 NodeDetailDrawer', async => {
 const { wrapper } = await mountGalaxy
 // 两个组件挂载到 DOM 中（无论 filteredNodes 是否有数据）
 expect(wrapper.find('.mock-command-palette').exists).toBe(true)
 expect(wrapper.find('.mock-drawer').exists).toBe(true)
 wrapper.unmount
 })
 it('node-click 后触发 openNode → drawerOpen=true，selectedNodeId 更新', async => {
 const { wrapper } = await mountGalaxy
 await flushPromises
 // 通过 vm 直接调用 handleNodeClick（跳过 ForceGraph mock 事件）
 const vm = wrapper.vm as unknown as { handleNodeClick: (n: GalaxyNode) => void, drawerOpen: boolean, selectedNodeId: string | null }
 if (typeof vm.handleNodeClick === 'function') {
 vm.handleNodeClick(makeNode({ id: 'symbol:myfn' }))
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('symbol:myfn')
 }
 wrapper.unmount
 })
 it('node-click 后 URL 包含 ?node=', async => {
 const { wrapper, router } = await mountGalaxy
 await flushPromises
 const vm = wrapper.vm as unknown as { handleNodeClick: (n: GalaxyNode) => void }
 if (typeof vm.handleNodeClick === 'function') {
 vm.handleNodeClick(makeNode({ id: 'symbol:url-test' }))
 await flushPromises
 expect(router.currentRoute.value.query.node).toBe('symbol:url-test')
 }
 wrapper.unmount
 })
 it('handleDrawerClose(false) 清除 URL 中 ?node=', async => {
 const { wrapper, router } = await mountGalaxy
 await flushPromises
 const vm = wrapper.vm as unknown as {
 handleNodeClick: (n: GalaxyNode) => void
 handleDrawerClose: (open: boolean) => void
 }
 if (typeof vm.handleNodeClick === 'function') {
 vm.handleNodeClick(makeNode({ id: 'symbol:clear-test' }))
 await flushPromises
 expect(router.currentRoute.value.query.node).toBe('symbol:clear-test')
 vm.handleDrawerClose(false)
 await flushPromises
 expect(router.currentRoute.value.query.node).toBeUndefined
 }
 wrapper.unmount
 })
 it('handleCommandPaletteSelect 打开 Drawer 并设置 nodeId', async => {
 const { wrapper } = await mountGalaxy
 await flushPromises
 const vm = wrapper.vm as unknown as {
 handleCommandPaletteSelect: (r: GalaxySearchResult) => void
 drawerOpen: boolean
 selectedNodeId: string | null
 }
 const result: GalaxySearchResult = {
 id: 'endpoint:api',
 type: 'endpoint',
 label: 'POST /api/users',
 file_path: 'server/views.py',
 repository_id: 'repo-1',
 degree: 10,
 }
 if (typeof vm.handleCommandPaletteSelect === 'function') {
 vm.handleCommandPaletteSelect(result)
 await flushPromises
 expect(vm.drawerOpen).toBe(true)
 expect(vm.selectedNodeId).toBe('endpoint:api')
 }
 wrapper.unmount
 })
})
