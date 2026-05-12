/**
 * Phase Plan — useConversationFrozen composable（ 三态判定）
 *
 * status 真源：对话 status 字段（Conversation.status TextChoices）
 * - draft → 可自由修改 Provider
 * - running/paused/interrupted → active 态，前端需弹 PinConfirmDialog 才允许切换
 * - completed/stopped/error → frozen 态，下拉置灰 + tooltip 说明
 *
 * 此 composable 仅输出 isFrozen 布尔 + reason 字符串；弹窗 / 置灰交互由调用组件处理。
 * waitingForInput 为 SSE 驱动的动态判定（ChatInterruptView WAITING 态）——同样置灰。
 *
 * 使用场景：
 * const { status, waitingForInput } = useConversation
 * const frozen = useConversationFrozen(status, waitingForInput)
 * // frozen.value.isFrozen → boolean
 * // frozen.value.reason → string（frozen 时用于 Tooltip）
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
/** frozen 真源：completed / stopped / error 三态 pin 不可改。 */
const FROZEN_STATUSES = new Set<ConversationStatus>([
 'completed',
 'stopped',
 'error',
])
/** work item §Copywriting Contract — 各 frozen 态 tooltip 硬锁文案。 */
const STATUS_REASON_MAP: Record<ConversationStatus, string> = {
 draft: '',
 running: '',
 paused: '',
 interrupted: '',
 completed: '该对话已完成，Provider 不可修改',
 stopped: '该对话已停止，Provider 不可修改',
 error: '该对话异常中断，Provider 不可修改',
}
/**
 * 返回响应式 { isFrozen, reason }，随 status / waitingForInput 变化自动更新。
 *
 * @param status - 对话 status 响应式引用（必填；真源 Conversation.status）
 * @param waitingForInput - SSE 驱动的 WAITING 状态（可选；ChatInterruptView 场景）
 */
export function useConversationFrozen(
 status: Ref<ConversationStatus>,
 waitingForInput?: Ref<boolean>,
): ComputedRef<FrozenState> {
 return computed( => {
 // 1. status 冻结优先（completed/stopped/error）
 if (FROZEN_STATUSES.has(status.value)) {
 return {
 isFrozen: true,
 reason: STATUS_REASON_MAP[status.value],
 }
 }
 // 2. WAITING 态冻结（前端 SSE 驱动）
 if (waitingForInput?.value) {
 return {
 isFrozen: true,
 reason: '该对话等待输入中，Provider 不可修改',
 }
 }
 return { isFrozen: false, reason: '' }
 })
}
