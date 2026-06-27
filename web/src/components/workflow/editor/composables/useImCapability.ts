/**
 * 图级 IM（飞书群聊）能力判定（SLOT-04 / CONTEXT 决策 D）。
 *
 * 职责：
 * - 判定当前工作流图是否具备 IM 能力——图中存在「创建群聊 / 创建工作项群聊」
 *   节点即视为有 `chat_id` 源（`hasImCapability`）。
 * - `isImGated(nodeType)`：依赖 `chat_id` 的发群/通知节点在缺源时应被门控降级。
 *
 * 边界：纯派生（仅读 `useWorkflowsStore().nodes`），无副作用/日志；
 * 视觉门控（opacity + 锁徽标 + tooltip）由消费方 `BaseWorkflowNode` 负责。
 *
 * 合规：门控仅为前端引导（缺 chat_id 源时提示如何补全），后端节点执行期仍校验
 * `chat_id` 必填，视觉绕过不影响后端权威（threat T-93-05-BYPASS: accept）。
 */
import type { ComputedRef } from 'vue'
import { computed } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

/** 提供 `chat_id` 源的节点类型（图中存在任一即具备 IM 能力）。 */
export const IM_SOURCE_TYPES = new Set(['create_group_chat', 'create_work_item_chat'])

/** 依赖 `chat_id` 的发群/通知节点类型（缺源时按 CONTEXT D 降级门控）。 */
export const IM_DEPENDENT_TYPES = new Set(['notify_feishu', 'notify_feishu_im'])

/**
 * 图级 IM 能力判定 holder。
 *
 * - `hasImCapability`：图中存在任一 `IM_SOURCE_TYPES` 节点 → true。
 * - `isImGated(nodeType)`：该节点依赖 chat_id 且当前图无 IM 源 → true（应门控）。
 *   非 IM 依赖节点恒 false。
 */
export function useImCapability(): {
  hasImCapability: ComputedRef<boolean>
  isImGated: (nodeType: string) => boolean
} {
  const store = useWorkflowsStore()

  const hasImCapability = computed(() =>
    store.nodes.some(n => IM_SOURCE_TYPES.has(n.nodeType)),
  )

  function isImGated(nodeType: string): boolean {
    return IM_DEPENDENT_TYPES.has(nodeType) && !hasImCapability.value
  }

  return { hasImCapability, isImGated }
}
