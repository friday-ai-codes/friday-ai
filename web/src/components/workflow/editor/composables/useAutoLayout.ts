import { useDagreLayout } from '~/composables/useDagreLayout'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'
import { toVueFlowEdges, toVueFlowNodes } from './useWorkflowTransform'

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
      toVueFlowEdges(store.edges),
      { rankdir: 'LR', ranksep: 80, nodesep: 40 },
    )

    // 逐节点写回（仅 markDirty 不入历史），最后手动入历史一次 → 单步可撤销
    for (const node of laidOut)
      store.updateNodePosition(node.id, node.position)
    store.saveToHistory()

    return true
  }

  return { applyAutoLayout }
}
