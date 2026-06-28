/**
 * useWorkflowTransform 附着子节点（拼积木插槽）单元测试（SLOT-04）。
 *
 * 新模型（拖拽落槽）：附着子节点（插件，带 metadata.parentNodeId）**不作为独立画布节点渲染**，
 * 它嵌入宿主卡的能力槽内（in-card chip）；其相连的内部边也不在画布渲染。子节点/内部边仍留在
 * store（SSOT，供后端执行 + 卡内渲染）。
 *
 * 覆盖：
 * - toVueFlowNodes 过滤附着子节点（画布只渲染宿主与普通节点）。
 * - toVueFlowEdges 过滤「内部边」（任一端为附着子节点）。
 * - 普通节点 data.metadata 透传；无父子图零回归。
 * - fromVueFlowNodes 普通节点往返不丢字段。
 * - useAutoLayout 不改动附着子节点坐标（子节点不进 dagre）。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { useAutoLayout } from '../useAutoLayout'
import { fromVueFlowNodes, toVueFlowEdges, toVueFlowNodes } from '../useWorkflowTransform'

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

describe('toVueFlowNodes - 附着子节点过滤（拼积木插槽）', () => {
  it('附着子节点不渲染为画布节点（嵌入宿主卡内）', () => {
    const nodes = [
      makeStoreNode('parent'),
      makeStoreNode('child', { metadata: { parentNodeId: 'parent' }, position: { x: 20, y: 30 } }),
    ]
    const vf = toVueFlowNodes(nodes)
    expect(vf.find(n => n.id === 'child')).toBeUndefined()
    expect(vf.find(n => n.id === 'parent')).toBeDefined()
    expect(vf).toHaveLength(1)
  })

  it('普通节点 data.metadata 透传 + 无父子图零回归', () => {
    const nodes = [makeStoreNode('a', { metadata: { extra: 1 } }), makeStoreNode('b')]
    const vf = toVueFlowNodes(nodes)
    expect(vf.map(n => n.id)).toEqual(['a', 'b'])
    expect(vf.find(n => n.id === 'a')!.data!.metadata.extra).toBe(1)
    for (const n of vf) {
      expect(n.parentNode).toBeUndefined()
      expect(n.extent).toBeUndefined()
    }
  })
})

describe('toVueFlowEdges - 内部边过滤', () => {
  it('任一端为附着子节点的边不渲染；普通边保留', () => {
    const nodes = [
      makeStoreNode('host'),
      makeStoreNode('plugin', { metadata: { parentNodeId: 'host' } }),
      makeStoreNode('other'),
    ]
    const edges = [
      { id: 'internal1', source: 'host', sourcePort: 'clarify', target: 'plugin', targetPort: 'clarification_request', condition: null },
      { id: 'internal2', source: 'plugin', sourcePort: 'clarification_answer', target: 'host', targetPort: 'resume', condition: null },
      { id: 'normal', source: 'host', sourcePort: 'default', target: 'other', targetPort: 'default', condition: null },
    ]
    const vf = toVueFlowEdges(edges, nodes)
    expect(vf.map(e => e.id)).toEqual(['normal'])
  })
})

describe('fromVueFlowNodes - 普通节点往返', () => {
  it('toVueFlowNodes → fromVueFlowNodes 普通节点字段不丢', () => {
    const nodes = [makeStoreNode('a'), makeStoreNode('b')]
    const back = fromVueFlowNodes(toVueFlowNodes(nodes))
    expect(back.map(n => n.id)).toEqual(['a', 'b'])
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
