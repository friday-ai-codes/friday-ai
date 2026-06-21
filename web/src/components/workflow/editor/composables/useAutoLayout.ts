import type { Edge } from '@vue-flow/core'
import { useDagreLayout } from '~/composables/useDagreLayout'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { toVueFlowEdges, toVueFlowNodes } from './useWorkflowTransform'

/** 兜底/默认分支 handle 名，排序时殿后（参考 dify sortIfElseOutEdges 思路） */
const FALLBACK_HANDLES = new Set(['else', 'false', 'default'])

/**
 * 稳定排序分支出边：同一源节点的多条出边按 sourceHandle 名排序，
 * 把 else/false/default 之类兜底分支排到最后，使 dagre 分层时分支上下顺序稳定。
 * 仅影响布局输入顺序，不改 store 边。
 */
function sortBranchEdges(edges: Edge[]): Edge[] {
  const sourceFirstIndex = new Map<string, number>()
  edges.forEach((e, i) => {
    if (!sourceFirstIndex.has(e.source))
      sourceFirstIndex.set(e.source, i)
  })

  return edges
    .map((e, i) => ({ e, i }))
    .sort((a, b) => {
      const sa = sourceFirstIndex.get(a.e.source) ?? 0
      const sb = sourceFirstIndex.get(b.e.source) ?? 0
      if (sa !== sb)
        return sa - sb
      const ha = a.e.sourceHandle ?? 'default'
      const hb = b.e.sourceHandle ?? 'default'
      const fa = FALLBACK_HANDLES.has(ha) ? 1 : 0
      const fb = FALLBACK_HANDLES.has(hb) ? 1 : 0
      if (fa !== fb)
        return fa - fb
      if (ha !== hb)
        return ha.localeCompare(hb)
      return a.i - b.i
    })
    .map(x => x.e)
}

/**
 * 一键自动布局 composable（横向 LR）。
 *
 * 复用既有 dagre（rankdir 'LR'）计算横向 L→R 坐标，写回 store 后手动入历史一次，
 * 使整次布局成为单步可撤销。fitView 不在此（无 VueFlow 上下文），由 WorkflowCanvas
 * 调用方在布局后触发。
 */
export function useAutoLayout() {
  const store = useWorkflowsStore()
  const { applyLayout } = useDagreLayout()

  /**
   * 计算并写回横向 LR 布局坐标。
   * @returns 是否有节点参与布局（空图返回 false，调用方据此决定是否 fitView）。
   */
  function applyAutoLayout(): boolean {
    if (store.nodes.length === 0)
      return false

    const laidOut = applyLayout(
      toVueFlowNodes(store.nodes),
      sortBranchEdges(toVueFlowEdges(store.edges)),
      // 横向层间距 / 同层间距：对齐 dify（层间 ~100、同层 ~80）撑开连线，避免节点贴太近
      { rankdir: 'LR', ranksep: 140, nodesep: 70 },
    )

    // 逐节点写回（仅 markDirty 不入历史），最后手动入历史一次 → 单步可撤销
    for (const node of laidOut)
      store.updateNodePosition(node.id, node.position)
    store.saveToHistory()

    return true
  }

  return { applyAutoLayout }
}
