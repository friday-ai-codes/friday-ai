import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import type { GraphNode, ViewportTransform } from '@vue-flow/core'
// ---------------------------------------------------------------------------
// A. Mock @vue-flow/core
// ---------------------------------------------------------------------------
const mockNodes = ref<GraphNode>
const mockViewport = ref<ViewportTransform>({ x: 0, y: 0, zoom: 1 })
vi.mock('@vue-flow/core', => ({
 useVueFlow: => ({
 getNodes: mockNodes,
 viewport: mockViewport,
 }),
}))
// ---------------------------------------------------------------------------
// B. Mock document.querySelector（happy-dom 对 .vue-flow__transformationpane 支持有限）
// ---------------------------------------------------------------------------
vi.spyOn(document, 'querySelector').mockImplementation((selector: string) => {
 if (selector === '.vue-flow__transformationpane') {
 return {
 parentElement: {
 clientWidth: 1000,
 clientHeight: 800,
 },
 } as unknown as Element
 }
 return null
})
// ---------------------------------------------------------------------------
// C. 被测模块（mock 之后导入）
// ---------------------------------------------------------------------------
import { useAlignmentGuides } from '../useAlignmentGuides'
// ---------------------------------------------------------------------------
// D. Fixture 工厂
// ---------------------------------------------------------------------------
function makeGraphNode(overrides: Partial<GraphNode> = {}): GraphNode {
 const pos = overrides.position ?? { x: 100, y: 100 }
 return {
 id: overrides.id ?? 'node-1',
 position: pos,
 computedPosition: overrides.computedPosition ?? { x: pos.x, y: pos.y, z: 0 },
 dimensions: overrides.dimensions ?? { width: 200, height: 80 },
 handleBounds: { source:, target: },
 isParent: false,
 selected: false,
 resizing: false,
 dragging: false,
 data: {},
 events: {},
 type: 'default',
 ...overrides,
 } as GraphNode
}
// ---------------------------------------------------------------------------
// E. 测试套件
// ---------------------------------------------------------------------------
describe('checkAlignment', => {
 beforeEach( => {
 mockNodes.value =
 mockViewport.value = { x: 0, y: 0, zoom: 1 }
 })
 it('无其他节点时返回原位置，guides 为空', => {
 mockNodes.value = [makeGraphNode({ id: 'dragged' })]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 50, y: 50 })
 expect(result.x).toBe(50)
 expect(result.y).toBe(50)
 expect(result.guides).toHaveLength(0)
 })
 it('centerX 对齐时吸附到目标中心，返回 vertical center guide', => {
 // target 在 (100,100) → centerX = 200
 // dragged 在 (100,100) → centerX = 200，差值 0 < SNAP_THRESHOLD(5)
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 } }),
 makeGraphNode({ id: 'target', position: { x: 100, y: 300 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 expect(result.x).toBe(100) // 200 - 200/2 = 100
 expect(result.guides).toContainEqual({
 orientation: 'vertical',
 position: 200,
 type: 'center',
 })
 })
 it('left 边对齐时吸附到目标左边，返回 vertical edge guide', => {
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 } }),
 makeGraphNode({ id: 'target', position: { x: 100, y: 300 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 // left 差值 = |100 - 100| = 0 < 5，但 centerX 先匹配且 !hasSnapX，所以 centerX 优先
 // 这里需要让 dragged 的 centerX 不接近 target centerX
 // dragged at (0,100): centerX=100, target centerX=200 → diff=100 > 5
 // left diff = |0 - 100| = 100 > 5，也不匹配
 // 调整 target 到 (0,300): centerX=100, target centerX=100 → diff=0 < 5，又匹配 centerX
 // 换个思路：让 target 宽度不同，使 left 对齐但 centerX 不对齐
 // target at (100,300), width=200 → centerX=200
 // dragged at (100,100), width=200 → centerX=200
 // 这总是同时满足。改用 dragged width=100:
 // dragged at (100,100), width=100 → centerX=150, left=100
 // target at (100,300), width=200 → centerX=200, left=100
 // centerX diff = 50 > 5, left diff = 0 < 5 → left 对齐
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 }, dimensions: { width: 100, height: 80 } }),
 makeGraphNode({ id: 'target', position: { x: 100, y: 300 } }),
 ]
 const result2 = useAlignmentGuides.checkAlignment('dragged', { x: 100, y: 100 })
 expect(result2.x).toBe(100)
 expect(result2.guides).toContainEqual({
 orientation: 'vertical',
 position: 100,
 type: 'edge',
 })
 })
 it('right 边对齐时吸附到目标右边，返回 vertical edge guide', => {
 // target at (0,300), width=200 → right=200
 // dragged at (0,100), width=200 → right=200, centerX=100, target centerX=100 → centerX 也匹配
 // 需要 centerX 不匹配：dragged width=100
 // dragged at (100,100), width=100 → right=200, centerX=150
 // target at (0,300), width=200 → right=200, centerX=100
 // centerX diff=50>5, right diff=0<5 → right 对齐
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 }, dimensions: { width: 100, height: 80 } }),
 makeGraphNode({ id: 'target', position: { x: 0, y: 300 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 expect(result.x).toBe(100) // targetRight(200) - draggedWidth(100) = 100
 expect(result.guides).toContainEqual({
 orientation: 'vertical',
 position: 200,
 type: 'edge',
 })
 })
 it('centerY 对齐时吸附到目标垂直中心，返回 horizontal center guide', => {
 // target at (300,100) → centerY = 100 + 80/2 = 140
 // dragged at (100,100) → centerY = 140，差值 0 < 5
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 } }),
 makeGraphNode({ id: 'target', position: { x: 300, y: 100 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 expect(result.y).toBe(100) // 140 - 80/2 = 100
 expect(result.guides).toContainEqual({
 orientation: 'horizontal',
 position: 140,
 type: 'center',
 })
 })
 it('top 边对齐时吸附到目标顶边，返回 horizontal edge guide', => {
 // 需要 centerY 不匹配：dragged height=40
 // target at (300,100) → top=100, centerY=140
 // dragged at (100,100), height=40 → top=100, centerY=120
 // centerY diff=20>5, top diff=0<5 → top 对齐
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 }, dimensions: { width: 200, height: 40 } }),
 makeGraphNode({ id: 'target', position: { x: 300, y: 100 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 expect(result.y).toBe(100)
 expect(result.guides).toContainEqual({
 orientation: 'horizontal',
 position: 100,
 type: 'edge',
 })
 })
 it('bottom 边对齐时吸附到目标底边，返回 horizontal edge guide', => {
 // target at (300,0), height=80 → bottom=80, centerY=40
 // dragged at (100,0), height=40 → bottom=40, centerY=20
 // centerY diff=20>5, bottom diff=|40-80|=40>5 → 不匹配
 // 调整：target at (300,20), height=80 → bottom=100, centerY=60
 // dragged at (100,20), height=40 → bottom=60, centerY=40
 // centerY diff=20>5, bottom diff=|60-100|=40>5
 // 需要 bottom 差值 < 5：dragged bottom ≈ target bottom
 // target at (300,0), height=80 → bottom=80
 // dragged at (100,40), height=40 → bottom=80, centerY=60, target centerY=40
 // centerY diff=20>5, bottom diff=0<5 → bottom 对齐
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 40 }, dimensions: { width: 200, height: 40 } }),
 makeGraphNode({ id: 'target', position: { x: 300, y: 0 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 40 })
 expect(result.y).toBe(40) // targetBottom(80) - draggedHeight(40) = 40
 expect(result.guides).toContainEqual({
 orientation: 'horizontal',
 position: 80,
 type: 'edge',
 })
 })
 it('同时满足 X 和 Y 对齐时返回 snappedX 和 snappedY', => {
 // target at (100,100) → centerX=200, centerY=140
 // dragged at (100,100) → centerX=200, centerY=140，两者都满足
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 } }),
 makeGraphNode({ id: 'target', position: { x: 100, y: 100 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 expect(result.x).toBe(100)
 expect(result.y).toBe(100)
 expect(result.guides).toEqual(
 expect.arrayContaining([
 expect.objectContaining({ orientation: 'vertical', type: 'center' }),
 expect.objectContaining({ orientation: 'horizontal', type: 'center' }),
 ]),
 )
 })
 it('被拖拽节点不在 allNodes 中时返回原位置', => {
 mockNodes.value = [
 makeGraphNode({ id: 'other', position: { x: 100, y: 100 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('missing', { x: 50, y: 50 })
 expect(result.x).toBe(50)
 expect(result.y).toBe(50)
 expect(result.guides).toHaveLength(0)
 })
 it('节点在视口外时不参与对齐', => {
 // viewport zoom=1, x=0,y=0, canvas=1000x800
 // visibleLeft=0, visibleTop=0, visibleRight=1000, visibleBottom=800
 // target 在 (2000,2000) 完全在视口外
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 } }),
 makeGraphNode({ id: 'target', position: { x: 2000, y: 2000 } }),
 ]
 const { checkAlignment } = useAlignmentGuides
 const result = checkAlignment('dragged', { x: 100, y: 100 })
 // 无对齐发生，返回原位置
 expect(result.x).toBe(100)
 expect(result.y).toBe(100)
 expect(result.guides).toHaveLength(0)
 })
})
describe('clearGuides', => {
 beforeEach( => {
 mockNodes.value =
 mockViewport.value = { x: 0, y: 0, zoom: 1 }
 })
 it('清空 alignmentGuides', => {
 mockNodes.value = [
 makeGraphNode({ id: 'dragged', position: { x: 100, y: 100 } }),
 makeGraphNode({ id: 'target', position: { x: 100, y: 300 } }),
 ]
 const { alignmentGuides, checkAlignment, clearGuides } = useAlignmentGuides
 checkAlignment('dragged', { x: 100, y: 100 })
 expect(alignmentGuides.value.length).toBeGreaterThan(0)
 clearGuides
 expect(alignmentGuides.value).toHaveLength(0)
 })
})
