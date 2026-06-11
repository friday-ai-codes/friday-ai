/**
 * circles-layout 确定性布局单测
 */
import type { CirclesLayoutNode } from '~/lib/galaxy/circles-layout'
import { describe, expect, it } from 'vitest'
import {
  calculateCirclesLayout,
  CIRCLES_RING_RADII,
  deterministicHash,
} from '~/lib/galaxy/circles-layout'

function makeNode(overrides: Partial<CirclesLayoutNode> = {}): CirclesLayoutNode {
  return {
    id: 'chunk:1',
    type: 'chunk_registry',
    label: 'chunk-1',
    repository_id: 'repo-1',
    file_path: 'src/a.py',
    ...overrides,
  }
}

describe('deterministicHash', () => {
  it('同一输入返回相同值，值域 [0, 1)', () => {
    const a = deterministicHash('hello')
    const b = deterministicHash('hello')
    expect(a).toBe(b)
    expect(a).toBeGreaterThanOrEqual(0)
    expect(a).toBeLessThan(1)
  })

  it('不同输入大概率返回不同值', () => {
    expect(deterministicHash('a')).not.toBe(deterministicHash('b'))
  })
})

describe('calculateCirclesLayout — L1 细粒度', () => {
  const nodes: CirclesLayoutNode[] = [
    makeNode({ id: 'ep:1', type: 'endpoint', file_path: 'server/views.py' }),
    makeNode({ id: 'wrap:1', type: 'api_wrapper', file_path: 'web/api.ts' }),
    makeNode({ id: 'sym:1', type: 'symbol', file_path: 'src/a.py' }),
    makeNode({ id: 'chunk:1', type: 'chunk_registry', file_path: 'src/a.py' }),
    makeNode({ id: 'cs:1', type: 'api_call_site', file_path: 'web/pages/x.vue' }),
  ]

  it('为所有节点生成坐标', () => {
    const positions = calculateCirclesLayout(nodes)
    expect(positions.size).toBe(nodes.length)
  })

  it('确定性：相同输入两次计算结果完全一致', () => {
    const a = calculateCirclesLayout(nodes)
    const b = calculateCirclesLayout([...nodes].reverse())
    for (const [id, pos] of a) {
      expect(b.get(id)).toEqual(pos)
    }
  })

  it('按类型分环：endpoint/api_wrapper 内环，chunk 外环，call_site 最外', () => {
    const positions = calculateCirclesLayout(nodes)
    expect(positions.get('ep:1')!.ring).toBe(0)
    expect(positions.get('wrap:1')!.ring).toBe(0)
    expect(positions.get('sym:1')!.ring).toBe(1)
    expect(positions.get('chunk:1')!.ring).toBe(2)
    expect(positions.get('cs:1')!.ring).toBe(3)
  })

  it('节点半径在所属环半径 ± 抖动范围内', () => {
    const positions = calculateCirclesLayout(nodes)
    for (const pos of positions.values()) {
      const r = Math.hypot(pos.x, pos.y)
      const target = CIRCLES_RING_RADII[pos.ring]
      expect(Math.abs(r - target)).toBeLessThanOrEqual(20)
    }
  })

  it('同文件节点角度相邻（跨环径向对齐）', () => {
    const TWO_PI = Math.PI * 2
    const circularDist = (a: number, b: number) => {
      const d = Math.abs(a - b) % TWO_PI
      return Math.min(d, TWO_PI - d)
    }

    const many: CirclesLayoutNode[] = [
      makeNode({ id: 'chunk:f1-a', file_path: 'src/file1.py' }),
      makeNode({ id: 'chunk:f1-b', file_path: 'src/file1.py' }),
      // file1 的 symbol 应与 file1 的 chunk 角度接近，而不是 file2 区块中部
      makeNode({ id: 'sym:f1', type: 'symbol', file_path: 'src/file1.py' }),
    ]
    for (let i = 0; i < 10; i++)
      many.push(makeNode({ id: `chunk:f2-${i}`, file_path: 'zzz/file2.py' }))

    const positions = calculateCirclesLayout(many)
    const symAngle = positions.get('sym:f1')!.angle
    const sameFileAngle = positions.get('chunk:f1-a')!.angle
    const otherFileMidAngle = positions.get('chunk:f2-5')!.angle

    expect(circularDist(symAngle, sameFileAngle))
      .toBeLessThan(circularDist(symAngle, otherFileMidAngle))
  })

  it('空输入返回空 Map', () => {
    expect(calculateCirclesLayout([]).size).toBe(0)
  })
})

describe('calculateCirclesLayout — L2 仓库总览', () => {
  it('repository 节点均匀分布在单环上', () => {
    const repos: CirclesLayoutNode[] = ['a', 'b', 'c', 'd'].map(id =>
      makeNode({ id: `repo:${id}`, type: 'repository', label: `repo-${id}`, file_path: '' }),
    )
    const positions = calculateCirclesLayout(repos)
    expect(positions.size).toBe(4)

    const radii = [...positions.values()].map(p => Math.hypot(p.x, p.y))
    // 同环：半径一致
    for (const r of radii) {
      expect(Math.abs(r - radii[0])).toBeLessThan(0.001)
    }

    // 角度互不相同
    const angles = new Set([...positions.values()].map(p => p.angle.toFixed(4)))
    expect(angles.size).toBe(4)
  })

  it('单仓库时位于原点', () => {
    const positions = calculateCirclesLayout([
      makeNode({ id: 'repo:only', type: 'repository', label: 'only', file_path: '' }),
    ])
    const pos = positions.get('repo:only')!
    expect(pos.x).toBe(0)
    expect(pos.y).toBe(0)
  })
})
