import { describe, expect, it } from 'vitest'
import { getWorkflowEdgeRoute } from '../workflow/editor/utils/edgeRouting'
describe('workflow edge routing', => {
 it('横向跨度较大时应优先走侧向 bezier', => {
 const route = getWorkflowEdgeRoute({
 sourceX: 120,
 sourceY: 180,
 targetX: 420,
 targetY: 240,
 })
 expect(route.strategy).toBe('horizontal-bezier')
 expect(route.path).toContain('C')
 })
 it('目标在源节点上方时应走回流 bezier', => {
 const route = getWorkflowEdgeRoute({
 sourceX: 360,
 sourceY: 360,
 targetX: 300,
 targetY: 220,
 })
 expect(route.strategy).toBe('return-bezier')
 expect(route.path).toContain('C')
 })
 it('常规自上而下流转应保持圆角折线', => {
 const route = getWorkflowEdgeRoute({
 sourceX: 220,
 sourceY: 160,
 targetX: 250,
 targetY: 360,
 })
 expect(route.strategy).toBe('smooth-step')
 expect(route.path).toContain('L')
 })
})
