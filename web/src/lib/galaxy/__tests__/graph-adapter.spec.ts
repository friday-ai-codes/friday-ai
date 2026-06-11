/**
 * graph-adapter 单测：GalaxyNode/Edge → graphology 转换与视觉编码
 */
import type { GalaxyEdge, GalaxyNode } from '~/api/galaxy'
import { describe, expect, it } from 'vitest'
import {
  brightenColor,
  buildGalaxyGraph,
  dimColor,
  EDGE_COLORS,
  NODE_COLORS,
  nodeSize,
} from '~/lib/galaxy/graph-adapter'

function makeNode(overrides: Partial<GalaxyNode> = {}): GalaxyNode {
  return {
    id: 'chunk:1',
    type: 'chunk_registry',
    label: 'src/a.py:0',
    repository_id: 'repo-1',
    file_path: 'src/a.py',
    line_start: 1,
    line_end: 50,
    metadata: {},
    degree: 4,
    ...overrides,
  }
}

function makeEdge(overrides: Partial<GalaxyEdge> = {}): GalaxyEdge {
  return {
    id: 'edge-1',
    source: 'chunk:1',
    target: 'chunk:2',
    edge_type: 'CALL',
    weight: 0.5,
    repository_id: 'repo-1',
    target_repository_id: null,
    metadata: {},
    ...overrides,
  }
}

describe('buildGalaxyGraph', () => {
  it('节点带坐标与视觉属性', () => {
    const graph = buildGalaxyGraph(
      [makeNode(), makeNode({ id: 'chunk:2', type: 'symbol', label: 'fn' })],
      [makeEdge()],
    )

    expect(graph.order).toBe(2)
    expect(graph.size).toBe(1)

    const attrs = graph.getNodeAttributes('chunk:1')
    expect(typeof attrs.x).toBe('number')
    expect(typeof attrs.y).toBe('number')
    expect(attrs.color).toBe(NODE_COLORS.chunk_registry)
    expect(attrs.label).toBe('src/a.py:0')
    expect(attrs.nodeType).toBe('chunk_registry')
    expect(attrs.filePath).toBe('src/a.py')
    expect(attrs.degree).toBe(4)
  })

  it('忽略端点缺失的边与自环', () => {
    const graph = buildGalaxyGraph(
      [makeNode()],
      [
        makeEdge({ id: 'dangling', target: 'chunk:missing' }),
        makeEdge({ id: 'self-loop', source: 'chunk:1', target: 'chunk:1' }),
      ],
    )
    expect(graph.size).toBe(0)
  })

  it('长程关系边（API_CALLS/SEMANTIC）使用 curved 类型', () => {
    const graph = buildGalaxyGraph(
      [makeNode(), makeNode({ id: 'chunk:2' })],
      [
        makeEdge({ id: 'e-api', edge_type: 'API_CALLS' }),
        makeEdge({ id: 'e-call', edge_type: 'CALL' }),
      ],
    )
    expect(graph.getEdgeAttribute('e-api', 'type')).toBe('curved')
    expect(graph.getEdgeAttribute('e-api', 'color')).toBe(EDGE_COLORS.API_CALLS)
    expect(graph.getEdgeAttribute('e-call', 'type')).toBeUndefined()
  })
})

describe('视觉编码工具', () => {
  it('nodeSize — degree 越大尺寸越大且有上限', () => {
    const small = nodeSize('chunk_registry', 0)
    const mid = nodeSize('chunk_registry', 16)
    const huge = nodeSize('chunk_registry', 100000)
    expect(mid).toBeGreaterThan(small)
    expect(huge - small).toBeLessThanOrEqual(6)
  })

  it('dimColor — 向背景混合后返回合法 hex', () => {
    const dimmed = dimColor('#60a5fa', 0.2)
    expect(dimmed).toMatch(/^#[0-9a-f]{6}$/i)
    expect(dimmed).not.toBe('#60a5fa')
  })

  it('brightenColor — 提亮后返回合法 hex', () => {
    const brightened = brightenColor('#60a5fa', 1.5)
    expect(brightened).toMatch(/^#[0-9a-f]{6}$/i)
  })

  it('dimColor(x, 1) 还原原色', () => {
    expect(dimColor('#60a5fa', 1)).toBe('#60a5fa')
  })
})
