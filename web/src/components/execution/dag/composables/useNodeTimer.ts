/**
 * useNodeTimer — 批量管理运行中节点的 elapsed 时间
 *
 * 使用单个 useIntervalFn 避免多个 setInterval 导致性能问题。
 * 仅在有 running 节点时启动 interval，无 running 节点时自动暂停。
 */
import { useIntervalFn } from '@vueuse/core'
import { ref, watch, type Ref } from 'vue'
import type { NodeExecution } from '~/stores/useExecutionsStore'
/**
 * 返回 elapsedMap: key 是 node ID（NodeExecution.node），value 是 elapsed 秒数。
 */
export function useNodeTimer(nodeExecutions: Ref<NodeExecution>) {
 const elapsedMap = ref<Record<string, number>>({})
 const { pause, resume } = useIntervalFn( => {
 const now = Date.now
 const running = nodeExecutions.value.filter(
 ne => ne.status === 'running' && ne.started_at,
 )
 const newMap: Record<string, number> = {}
 for (const ne of running) {
 newMap[ne.node] = (now - new Date(ne.started_at!).getTime) / 1000
 }
 elapsedMap.value = newMap
 }, 1000, { immediate: false })
 // 仅在有运行中节点时启动计时
 watch(
 => nodeExecutions.value.some(ne => ne.status === 'running'),
 (hasRunning) => {
 if (hasRunning) {
 resume
 }
 else {
 pause
 elapsedMap.value = {}
 }
 },
 { immediate: true },
 )
 return { elapsedMap }
}
