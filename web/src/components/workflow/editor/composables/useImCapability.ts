/**
 * 图级 IM（飞书群聊）能力判定（SLOT-04 / CONTEXT 决策 D）。
 *
 * 职责：
 * - 判定当前工作流图是否具备 IM 能力——图中存在「创建群聊 / 创建工作项群聊」
 *   节点即视为有 `chat_id` 源（`hasImCapability`）。
 * - `isImGated(nodeType, config?)`：仅真正依赖群 `chat_id` 的发群节点在缺源时门控降级。
 *
 * 门控边界（WR-01 收敛误门控）：
 * - `notify_feishu` 走**飞书机器人 Webhook**（required: webhook_url/content），与 chat_id
 *   无关，**不纳入门控**。
 * - `notify_feishu_im` 的 `receive_id_type` 可为 `chat_id | open_id | user_id`：
 *   仅当配置为发群（`chat_id` 模式）**且**节点自身未配置 `receive_id`（无字面/变量化
 *   chat_id 来源）**且**图中无 IM 源节点时才门控；发个人或已填 receive_id 不误报。
 *
 * 边界：纯派生（仅读 `useWorkflowsStore().nodes`），无副作用/日志；
 * 视觉门控（opacity + 锁徽标 + tooltip）由消费方 `BaseWorkflowNode` 负责。
 *
 * 合规：门控仅为前端引导（缺 chat_id 源时提示如何补全），后端节点执行期仍校验
 * 必填项，视觉绕过不影响后端权威（threat T-93-05-BYPASS: accept）。
 */
import type { ComputedRef } from 'vue'
import { computed } from 'vue'
import { useWorkflowsStore } from '~/stores/useWorkflowsStore'

/** 提供 `chat_id` 源的节点类型（图中存在任一即具备 IM 能力）。 */
export const IM_SOURCE_TYPES = new Set(['create_group_chat', 'create_work_item_chat'])

/**
 * 真正依赖群 `chat_id` 的发群节点类型（缺源时按 CONTEXT D 降级门控）。
 * `notify_feishu`（webhook 型）不在其列——它与 chat_id 无关（WR-01）。
 */
export const IM_DEPENDENT_TYPES = new Set(['notify_feishu_im'])

/**
 * 图级 IM 能力判定 holder。
 *
 * - `hasImCapability`：图中存在任一 `IM_SOURCE_TYPES` 节点 → true。
 * - `isImGated(nodeType, config?)`：该节点真正依赖群 chat_id 且当前图无 chat_id 来源
 *   （图无 IM 源 + 节点自身未配置 receive_id）→ true（应门控）。非 IM 依赖节点、
 *   发个人（open_id/user_id）或已配置 receive_id 的节点恒 false。
 */
export function useImCapability(): {
  hasImCapability: ComputedRef<boolean>
  isImGated: (nodeType: string, config?: Record<string, unknown>) => boolean
} {
  const store = useWorkflowsStore()

  const hasImCapability = computed(() =>
    store.nodes.some(n => IM_SOURCE_TYPES.has(n.nodeType)),
  )

  function isImGated(nodeType: string, config?: Record<string, unknown>): boolean {
    if (!IM_DEPENDENT_TYPES.has(nodeType) || hasImCapability.value)
      return false
    // notify_feishu_im：仅"发群 chat_id 模式"才可能依赖群 chat_id 源。
    // receive_id_type 默认 chat_id；显式发个人（open_id/user_id）不门控。
    const receiveIdType = (config?.receive_id_type as string | undefined) ?? 'chat_id'
    if (receiveIdType !== 'chat_id')
      return false
    // 节点自身已配置 receive_id（字面群 ID 或模板变量，如来自 fetch_group_chat）→
    // 已有 chat_id 来源，不误报。
    const receiveId = typeof config?.receive_id === 'string' ? config.receive_id.trim() : ''
    return !receiveId
  }

  return { hasImCapability, isImGated }
}
