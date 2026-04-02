import type { Ref } from 'vue'
import type { useExecutionsStore, WorkflowExecution } from '~/stores/useExecutionsStore'
import { computed, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
export function useDebugMode(
 executionId: Ref<string>,
 store: ReturnType<typeof useExecutionsStore>,
 currentExecution: Ref<WorkflowExecution | null>,
) {
 /** Phase: 断点集合 */
 const breakpoints = ref<Set<string>>(new Set)
 /** 当前调试模式 */
 const debugMode = ref<'step' | 'breakpoint'>('step')
 /** 是否为断点模式（双向绑定用于 Switch） */
 const isBreakpointMode = computed({
 get: => debugMode.value === 'breakpoint',
 set: (val: boolean) => {
 debugMode.value = val ? 'breakpoint': 'step'
 store.sendDebugModeSwitch(debugMode.value)
 },
 })
 /** 切换节点断点 */
 function handleToggleBreakpoint(nodeId: string) {
 if (breakpoints.value.has(nodeId)) {
 breakpoints.value.delete(nodeId)
 store.sendBreakpointAction('remove_breakpoint', nodeId)
 }
 else {
 breakpoints.value.add(nodeId)
 store.sendBreakpointAction('set_breakpoint', nodeId)
 }
 // 触发响应式更新
 breakpoints.value = new Set(breakpoints.value)
 }
 /** 执行切换时重置断点状态 */
 watch( => currentExecution.value?.id, => {
 breakpoints.value = new Set
 debugMode.value = 'step'
 })
 /** 调试放行 */
 function handleDebugRelease(_nodeId: string) {
 store.sendDebugAction('release')
 }
 /** 调试跳过 */
 function handleDebugSkip(_nodeId: string) {
 store.sendDebugAction('skip')
 }
 /** 终止调试（取消执行） */
 async function handleCancelDebug {
 await store.cancelExecution(executionId.value)
 toast.success('调试执行已终止')
 }
 return {
 breakpoints,
 debugMode,
 isBreakpointMode,
 handleToggleBreakpoint,
 handleDebugRelease,
 handleDebugSkip,
 handleCancelDebug,
 }
}
