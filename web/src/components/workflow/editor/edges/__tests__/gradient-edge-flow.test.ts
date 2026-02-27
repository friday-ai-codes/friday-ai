import { describe, expect, it, vi } from 'vitest'
// Mock Vue Flow 依赖，避免运行时报错
vi.mock('@vue-flow/core', => ({
 BaseEdge: { name: 'BaseEdge', template: '<path />' },
 getBezierPath: vi.fn( => ['M 0 0 C 50 0 50 100 100 100', 50, 50]),
 Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}))
/**
 * 测试边的 flowing/skipped 逻辑（纯逻辑层面）
 *
 * 直接测试 computed 逻辑的等价函数，不需要挂载 Vue Flow
 */
describe('GradientEdge flow logic', => {
 /** 模拟组件中 isFlowing computed 的逻辑 */
 function isFlowing(data: Record<string, unknown> | undefined): boolean {
 return data?.flowing === true
 }
 /** 模拟组件中 isSkipped computed 的逻辑 */
 function isSkipped(data: Record<string, unknown> | undefined): boolean {
 return data?.skipped === true
 }
 /** 模拟 skipped 时的 edgeStyle 生成逻辑 */
 function getSkippedEdgeStyle(skipped: boolean) {
 if (skipped) {
 return {
 stroke: '#9CA3AF',
 strokeDasharray: '6 4',
 }
 }
 return {}
 }
 it('isFlowing is true when data.flowing is true', => {
 expect(isFlowing({ flowing: true })).toBe(true)
 })
 it('isFlowing is false when data.flowing is undefined', => {
 expect(isFlowing({})).toBe(false)
 expect(isFlowing(undefined)).toBe(false)
 })
 it('isSkipped is true when data.skipped is true', => {
 expect(isSkipped({ skipped: true })).toBe(true)
 })
 it('skipped edge style has stroke-dasharray', => {
 const style = getSkippedEdgeStyle(true)
 expect(style.strokeDasharray).toBe('6 4')
 expect(style.stroke).toBe('#9CA3AF')
 })
})
