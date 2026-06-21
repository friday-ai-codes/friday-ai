import { describe, expect, it } from 'vitest'
import { getWorkflowEdgeRoute } from '../workflow/editor/utils/edgeRouting'

/**
 * 对标 dify：连线只有一种 bezier（source=Right→target=Left，curvature 0.16）。
 * 不再按节点相对位置切换 smooth-step / 折返 bezier，故所有方向都产出同一种 bezier 路径。
 */
describe('workflow edge routing', () => {
  it('横向跨度较大时产出 bezier 曲线', () => {
    const route = getWorkflowEdgeRoute({
      sourceX: 120,
      sourceY: 180,
      targetX: 420,
      targetY: 240,
    })

    expect(route.path).toContain('C')
  })

  it('目标在源节点上方时仍是同一种 bezier（不再回流分支）', () => {
    const route = getWorkflowEdgeRoute({
      sourceX: 360,
      sourceY: 360,
      targetX: 300,
      targetY: 220,
    })

    expect(route.path).toContain('C')
  })

  it('常规自上而下流转也产出 bezier（不再走圆角折线）', () => {
    const route = getWorkflowEdgeRoute({
      sourceX: 220,
      sourceY: 160,
      targetX: 250,
      targetY: 360,
    })

    expect(route.path).toContain('C')
    expect(route.labelX).toBeTypeOf('number')
    expect(route.labelY).toBeTypeOf('number')
  })
})
