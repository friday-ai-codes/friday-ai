/**
 * useWorkflowTransform 父子映射单元测试（SLOT-04）。
 *
 * 覆盖：
 * - 带 metadata.parentNodeId 的 store 节点 → vf 节点含 parentNode + extent:'parent'。
 * - 数据契约断言（WARNING 1）：同一附着子节点 node.parentNode===parentId 且
 *   node.data.metadata.parentNodeId===parentId（两者同源不丢，锁死 93-05 读取来源）。
 * - 父先子排序：输出数组中父节点索引恒小于其子节点索引（即便输入中子先于父）。
 * - fromVueFlowNodes 往返保留 metadata.parentNodeId。
 * - 无父子图零回归（节点无 parentNode/extent）。
 * - useAutoLayout 不改动附着子节点坐标（子节点不进 dagre）。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { useAutoLayout } from '../useAutoLayout'
import { fromVueFlowNodes, toVueFlowNodes } from '../useWorkflowTransform'

function makeStoreNode(id: string, overrides: Record<string, any> = {}) {
  return {
    id,
    shortId: id.slice(0, 3),
    nodeType: 'ai_prompt',
    name: id,
    description: '',
    position: { x: 0, y: 0 },
    config: {},
    onError: 'abort' as const,
    retryTimes: 0,
    retryDelay: 5,
    nodeTimeoutSeconds: null,
    fallbackValues: null,
    runCondition: null,
    metadata: {} as Record<string, unknown>,
    ...overrides,
  }
}

describe('toVueFlowNodes - 父子映射 + 数据契约', () => {
  it('带 metadata.parentNodeId 的节点 → parentNode + extent:\'parent\'', () => {
    const nodes = [
      makeStoreNode('parent'),
      makeStoreNode('child', { metadata: { parentNodeId: 'parent' }, position: { x: 20, y: 30 } }),
    ]
    const vf = toVueFlowNodes(nodes)
    const child = vf.find(n => n.id === 'child')!
    expect(child.parentNode).toBe('parent')
    expect(child.extent).toBe('parent')
    // 相对父坐标透传
    expect(child.position).toEqual({ x: 20, y: 30 })
  })

  it('数据契约（WARNING 1）：parentNode 与 data.metadata.parentNodeId 同源并存', () => {
    const nodes = [
      makeStoreNode('p'),
      makeStoreNode('c', { metadata: { parentNodeId: 'p', extra: 1 } }),
    ]
    const vf = toVueFlowNodes(nodes)
    const child = vf.find(n => n.id === 'c')!
    // top-level parentNode
    expect(child.parentNode).toBe('p')
    // data.metadata 同源保留 parentNodeId（93-05 徽标唯一权威来源）
    expect(child.data!.metadata.parentNodeId).toBe('p')
    // 其它 metadata 字段不丢
    expect(child.data!.metadata.extra).toBe(1)
  })

  it('父先子排序：父索引恒小于子索引（即便输入中子先于父）', () => {
    const nodes = [
      makeStoreNode('child', { metadata: { parentNodeId: 'parent' } }),
      makeStoreNode('parent'),
    ]
    const vf = toVueFlowNodes(nodes)
    const pIdx = vf.findIndex(n => n.id === 'parent')
    const cIdx = vf.findIndex(n => n.id === 'child')
    expect(pIdx).toBeLessThan(cIdx)
  })

  it('无父子图零回归：节点不含 parentNode/extent', () => {
    const nodes = [makeStoreNode('a'), makeStoreNode('b')]
    const vf = toVueFlowNodes(nodes)
    for (const n of vf) {
      expect(n.parentNode).toBeUndefined()
      expect(n.extent).toBeUndefined()
    }
    // 顺序保持
    expect(vf.map(n => n.id)).toEqual(['a', 'b'])
  })
})

describe('fromVueFlowNodes - 往返保 parentNodeId', () => {
  it('toVueFlowNodes → fromVueFlowNodes 往返 metadata.parentNodeId 不丢', () => {
    const nodes = [
      makeStoreNode('parent'),
      makeStoreNode('child', { metadata: { parentNodeId: 'parent' } }),
    ]
    const back = fromVueFlowNodes(toVueFlowNodes(nodes))
    const child = back.find(n => n.id === 'child')!
    expect(child.metadata.parentNodeId).toBe('parent')
  })
})

describe('useAutoLayout - 附着子节点不参与 dagre', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('applyAutoLayout 不改动附着子节点坐标（子节点不进 dagre）', () => {
    const store = useWorkflowsStore()
    store.nodes.push(
      makeStoreNode('p1'),
      makeStoreNode('p2'),
      makeStoreNode('c', { metadata: { parentNodeId: 'p1' }, position: { x: 15, y: 25 } }),
    )
    store.edges.push(
      { id: 'e1', source: 'p1', sourcePort: 'default', target: 'p2', targetPort: 'default', condition: null },
    )

    const { applyAutoLayout } = useAutoLayout()
    const ran = applyAutoLayout()

    expect(ran).toBe(true)
    // 子节点相对父坐标在布局前后不变
    const child = store.getNodeById('c')!
    expect(child.position).toEqual({ x: 15, y: 25 })
  })

  it('无父子图零回归：所有节点都参与布局并被重排', () => {
    const store = useWorkflowsStore()
    store.nodes.push(makeStoreNode('a'), makeStoreNode('b'))
    store.edges.push(
      { id: 'e1', source: 'a', sourcePort: 'default', target: 'b', targetPort: 'default', condition: null },
    )
    const { applyAutoLayout } = useAutoLayout()
    expect(applyAutoLayout()).toBe(true)
    // dagre LR：a 在 b 左侧（x 更小）
    const a = store.getNodeById('a')!
    const b = store.getNodeById('b')!
    expect(a.position.x).toBeLessThan(b.position.x)
  })
})
