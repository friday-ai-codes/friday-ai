import type { WorkflowNodeStore } from '~/types/workflow/store'
import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { SIGNAL_META } from '../../slotTaxonomy'
import { deriveSignalEdges, SIGNAL_EDGE_TYPE, useSignalLayer } from '../useSignalLayer'

/**
 * P6 信号层派生逻辑单测：以 reaction 配置（附着子 metadata.subscribeSignals）为准，
 * 纯派生「宿主 → 通知/文档」虚线信号订阅边。锁死：正确数量/颜色/虚线/方向、能力过滤、
 * 默认回退、开关关闭无边。
 */

function makeNode(overrides: Partial<WorkflowNodeStore> & { id: string }): WorkflowNodeStore {
  return {
    id: overrides.id,
    shortId: overrides.shortId ?? overrides.id,
    nodeType: overrides.nodeType ?? 'x',
    name: overrides.name ?? 'N',
    description: '',
    position: overrides.position ?? { x: 0, y: 0 },
    config: {},
    onError: 'abort',
    retryTimes: 0,
    retryDelay: 5,
    nodeTimeoutSeconds: null,
    fallbackValues: null,
    runCondition: null,
    metadata: overrides.metadata ?? {},
  }
}

/** 一个宿主 + 一个通知子（订阅 完成/失败）+ 一个文档子（订阅 产出）。 */
function fixtureNodes(): WorkflowNodeStore[] {
  return [
    makeNode({ id: 'host', nodeType: 'ai_plan_research' }),
    makeNode({
      id: 'notify',
      nodeType: 'notify_feishu',
      metadata: { parentNodeId: 'host', subscribeSignals: ['node.completed', 'node.failed'] },
    }),
    makeNode({
      id: 'doc',
      nodeType: 'feishu_doc_create',
      metadata: { parentNodeId: 'host', subscribeSignals: ['artifact.produced'] },
    }),
  ]
}

describe('deriveSignalEdges', () => {
  it('按 subscribeSignals 每信号派生一条边：数量正确 + 信号语义色 + 虚线 + 宿主→插件方向', () => {
    const edges = deriveSignalEdges(fixtureNodes())
    // notify 2 条（完成/失败）+ doc 1 条（产出）= 3
    expect(edges).toHaveLength(3)

    for (const e of edges) {
      expect(e.type).toBe(SIGNAL_EDGE_TYPE)
      expect(e.source).toBe('host')
      expect(e.data?.kind).toBe('signal_subscription')
      // 虚线：strokeDasharray 必有
      expect((e.style as Record<string, unknown>).strokeDasharray).toBeTruthy()
      // 派生叠加层不可选/不可删
      expect(e.selectable).toBe(false)
      expect(e.deletable).toBe(false)
    }

    const completed = edges.find(e => e.target === 'notify' && e.data?.signal === 'node.completed')
    const failed = edges.find(e => e.target === 'notify' && e.data?.signal === 'node.failed')
    const produced = edges.find(e => e.target === 'doc' && e.data?.signal === 'artifact.produced')
    expect(completed?.data?.color).toBe(SIGNAL_META['node.completed'].color)
    expect(failed?.data?.color).toBe(SIGNAL_META['node.failed'].color)
    expect(produced?.data?.color).toBe(SIGNAL_META['artifact.produced'].color)
    // style.stroke 与 data.color 同口径
    expect((completed?.style as Record<string, unknown>).stroke).toBe(SIGNAL_META['node.completed'].color)
  })

  it('唯一 id（宿主::插件::信号）便于幂等渲染', () => {
    const edges = deriveSignalEdges(fixtureNodes())
    const ids = edges.map(e => e.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toContain('signal::host::notify::node.completed')
  })

  it('clarification 能力不订阅生命周期信号 → 不派生边', () => {
    const nodes = [
      makeNode({ id: 'host', nodeType: 'ai_plan_research' }),
      makeNode({
        id: 'clar',
        nodeType: 'clarification_card',
        metadata: { parentNodeId: 'host', subscribeSignals: ['node.completed'] },
      }),
    ]
    expect(deriveSignalEdges(nodes)).toHaveLength(0)
  })

  it('非附着节点（无 parentNodeId）→ 不派生边', () => {
    const nodes = [
      makeNode({ id: 'host', nodeType: 'ai_plan_research' }),
      makeNode({ id: 'standalone', nodeType: 'notify_feishu' }),
    ]
    expect(deriveSignalEdges(nodes)).toHaveLength(0)
  })

  it('附着子未显式订阅 → 归一为默认「完成」信号（绿）一条边', () => {
    const nodes = [
      makeNode({ id: 'host', nodeType: 'ai_coding' }),
      makeNode({ id: 'notify', nodeType: 'notify_feishu', metadata: { parentNodeId: 'host' } }),
    ]
    const edges = deriveSignalEdges(nodes)
    expect(edges).toHaveLength(1)
    expect(edges[0].data?.signal).toBe('node.completed')
    expect(edges[0].data?.color).toBe(SIGNAL_META['node.completed'].color)
  })

  it('非法订阅值被过滤（归一回退默认），不产出非法信号边', () => {
    const nodes = [
      makeNode({ id: 'host', nodeType: 'ai_coding' }),
      makeNode({
        id: 'notify',
        nodeType: 'notify_feishu',
        metadata: { parentNodeId: 'host', subscribeSignals: ['bogus', 'nope'] },
      }),
    ]
    const edges = deriveSignalEdges(nodes)
    expect(edges).toHaveLength(1)
    expect(edges[0].data?.signal).toBe('node.completed')
  })
})

describe('useSignalLayer 开关', () => {
  it('关闭 → 无信号边 + 无目标节点；开启 → 派生', () => {
    const nodes = ref(fixtureNodes())
    const enabled = ref(false)
    const { signalEdges, signalTargetIds } = useSignalLayer(nodes, enabled)

    expect(signalEdges.value).toHaveLength(0)
    expect(signalTargetIds.value.size).toBe(0)

    enabled.value = true
    expect(signalEdges.value).toHaveLength(3)
    // 目标插件去重集（notify + doc）
    expect(signalTargetIds.value).toEqual(new Set(['notify', 'doc']))
  })

  it('支持 getter 形式的 nodes（响应式重算）', () => {
    const base = fixtureNodes()
    const { signalEdges } = useSignalLayer(() => base, () => true)
    expect(signalEdges.value).toHaveLength(3)
  })
})
