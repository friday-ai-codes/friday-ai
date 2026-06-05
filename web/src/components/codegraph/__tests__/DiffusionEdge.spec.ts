/**
 * — DiffusionEdge 单测
 * 验证：EdgeLabelRenderer 内 TooltipContent 显示 edge_type chip（颜色 + 文字） /
 *      weight 2 位小数 / reason 文本及空 fallback / unknown edgeType 兜底色。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DiffusionEdge from '../DiffusionEdge.vue'

vi.mock('@vue-flow/core', () => ({
  BaseEdge: { template: '<path class="base-edge-stub" />' },
  EdgeLabelRenderer: { template: '<div class="edge-label-stub"><slot /></div>' },
  getSmoothStepPath: () => ['M0 0', 50, 50],
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}))

vi.mock('~/components/ui/tooltip', () => ({
  Tooltip: { template: '<div><slot /></div>' },
  TooltipTrigger: { template: '<div><slot /></div>' },
  TooltipContent: { template: '<div class="tooltip-content-stub"><slot /></div>' },
  TooltipProvider: { template: '<div><slot /></div>' },
}))

function makeProps(dataOverrides: Record<string, unknown> = {}) {
  return {
    id: 'edge-1',
    sourceX: 0,
    sourceY: 0,
    targetX: 100,
    targetY: 100,
    sourcePosition: 'bottom' as never,
    targetPosition: 'top' as never,
    data: {
      edgeType: 'CALL',
      weight: 0.5,
      reason: 'caller of foo via direct call',
      hop: 1 as 1 | 2,
      ...dataOverrides,
    },
  }
}

describe('diffusionEdge', () => {
  it('a: edgeType=CALL → chip 文案 "CALL" + style 含 #3b82f6', () => {
    const wrapper = mount(DiffusionEdge, { props: makeProps() })
    const html = wrapper.html()
    expect(html).toContain('CALL')
    expect(html).toMatch(/#3b82f6/i)
  })

  it('b: edgeType=SEMANTIC → chip 文案 "SEMANTIC" + style 含 #ec4899', () => {
    const wrapper = mount(DiffusionEdge, {
      props: makeProps({ edgeType: 'SEMANTIC' }),
    })
    const html = wrapper.html()
    expect(html).toContain('SEMANTIC')
    expect(html).toMatch(/#ec4899/i)
  })

  it('c: weight=0.456789 → 文案 "weight 0.46"（toFixed(2)）', () => {
    const wrapper = mount(DiffusionEdge, {
      props: makeProps({ weight: 0.456789 }),
    })
    expect(wrapper.text()).toContain('weight 0.46')
  })

  it('d: reason 非空 → 渲染 reason 文案', () => {
    const wrapper = mount(DiffusionEdge, {
      props: makeProps({ reason: 'caller of foo via direct call' }),
    })
    expect(wrapper.text()).toContain('caller of foo via direct call')
  })

  it('e: reason="" → 降级为 "（无说明）" fallback', () => {
    const wrapper = mount(DiffusionEdge, {
      props: makeProps({ reason: '' }),
    })
    expect(wrapper.text()).toContain('（无说明）')
  })

  it('f: unknown edgeType → chip 仍展示原字面值（不掩盖问题），且 style 用兜底色 #6b7280', () => {
    const wrapper = mount(DiffusionEdge, {
      props: makeProps({ edgeType: 'UNKNOWN_TYPE' }),
    })
    const html = wrapper.html()
    expect(html).toContain('UNKNOWN_TYPE')
    expect(html).toMatch(/#6b7280/i)
  })

  it('g: 不写 title 属性（per UI-SPEC §10 硬约束 15）', () => {
    const wrapper = mount(DiffusionEdge, { props: makeProps() })
    expect(wrapper.html()).not.toMatch(/\stitle=/)
  })
})
