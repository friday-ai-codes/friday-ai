/**
 * — useDagreLayout 单测
 * 验证：TB 方向 dagre 布局正确计算节点 position
 */
import type { Edge, Node } from '@vue-flow/core'
import { describe, expect, it } from 'vitest'
import { useDagreLayout } from '../useDagreLayout'

const { applyLayout } = useDagreLayout()

describe('useDagreLayout', () => {
  it('a: 3 节点线性链布局后所有 position 均为有效数字', () => {
    const nodes: Node[] = [
      { id: 'A', position: { x: 0, y: 0 }, data: {} },
      { id: 'B', position: { x: 0, y: 0 }, data: {} },
      { id: 'C', position: { x: 0, y: 0 }, data: {} },
    ]
    const edges: Edge[] = [
      { id: 'e1', source: 'A', target: 'B' },
      { id: 'e2', source: 'B', target: 'C' },
    ]
    const result = applyLayout(nodes, edges)
    expect(result).toHaveLength(3)
    for (const n of result) {
      expect(typeof n.position.x).toBe('number')
      expect(typeof n.position.y).toBe('number')
      expect(Number.isFinite(n.position.x)).toBe(true)
      expect(Number.isFinite(n.position.y)).toBe(true)
    }
  })

  it('b: TB 方向布局下 A→B→C 节点 y 坐标递增', () => {
    const nodes: Node[] = [
      { id: 'A', position: { x: 0, y: 0 }, data: {} },
      { id: 'B', position: { x: 0, y: 0 }, data: {} },
      { id: 'C', position: { x: 0, y: 0 }, data: {} },
    ]
    const edges: Edge[] = [
      { id: 'e1', source: 'A', target: 'B' },
      { id: 'e2', source: 'B', target: 'C' },
    ]
    const result = applyLayout(nodes, edges)
    const nodeA = result.find(n => n.id === 'A')!
    const nodeB = result.find(n => n.id === 'B')!
    const nodeC = result.find(n => n.id === 'C')!
    expect(nodeB.position.y).toBeGreaterThan(nodeA.position.y)
    expect(nodeC.position.y).toBeGreaterThan(nodeB.position.y)
  })

  it('c: 单节点也能正常布局', () => {
    const nodes: Node[] = [{ id: 'solo', position: { x: 0, y: 0 }, data: {} }]
    const edges: Edge[] = []
    const result = applyLayout(nodes, edges)
    expect(result).toHaveLength(1)
    expect(Number.isFinite(result[0].position.x)).toBe(true)
  })
})
