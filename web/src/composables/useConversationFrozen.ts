/**
 * — useConversationFrozen composable
 *
 * 产品决策（2026-07）：**任何状态都不冻结 Provider / 模型**。
 * 用户可在任意时刻把当前会话切换到任意模型；已在进行中的那一轮沿用发送时锁定的
 * 模型（``build_sdk_config`` 在发送时已构建 config），切换从下一轮生效。
 *
 * 因此本 composable 恒定返回 ``{ isFrozen: false, reason: '' }``，保留其签名/类型仅为
 * 兼容既有调用点（ChatInput 用其派生下拉可用态、并复用 ConversationStatus 类型）。
 * 历史上它会在 completed/stopped/error/等待输入 时置灰下拉——该 pin 语义已废弃。
 */

import type { ComputedRef, Ref } from 'vue'
import { computed } from 'vue'

export type ConversationStatus
  = | 'draft'
    | 'running'
    | 'paused'
    | 'interrupted'
    | 'completed'
    | 'stopped'
    | 'error'

export interface FrozenState {
  isFrozen: boolean
  reason: string
}

/**
 * 返回响应式 { isFrozen, reason }。恒为不冻结（产品决策：随时可切换模型）。
 *
 * @param _status - 对话 status（保留入参兼容；不再用于冻结判定）
 * @param _waitingForInput - SSE WAITING 状态（保留入参兼容；不再用于冻结判定）
 */
export function useConversationFrozen(
  _status: Ref<ConversationStatus>,
  _waitingForInput?: Ref<boolean>,
): ComputedRef<FrozenState> {
  return computed<FrozenState>(() => ({ isFrozen: false, reason: '' }))
}
