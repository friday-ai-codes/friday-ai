/**
 * 轮询组合式函数
 * 用于实现任务日志等需要定期刷新的场景
 */
import { useIntervalFn } from '@vueuse/core'
export interface UsePollingOptions {
 /** 轮询间隔（毫秒），默认 2000 */
 interval?: number
 /** 是否立即执行一次，默认 true */
 immediate?: boolean
}
export function usePolling(
 callback: => Promise<void> | void,
 options: UsePollingOptions = {},
) {
 const { interval = 2000, immediate = true } = options
 const isPolling = ref(false)
 const error = ref<Error | null>(null)
 const wrappedCallback = async => {
 if (!isPolling.value) return
 try {
 await callback
 error.value = null
 } catch (e) {
 error.value = e instanceof Error ? e: new Error('Polling error')
 }
 }
 const { pause, resume, isActive } = useIntervalFn(wrappedCallback, interval, {
 immediate: false,
 })
 /**
 * 开始轮询
 */
 async function start {
 isPolling.value = true
 if (immediate) {
 await wrappedCallback
 }
 resume
 }
 /**
 * 停止轮询
 */
 function stop {
 isPolling.value = false
 pause
 }
 /**
 * 手动刷新一次
 */
 async function refresh {
 await callback
 }
 // 组件卸载时自动停止
 onUnmounted( => {
 stop
 })
 return {
 isPolling: readonly(isPolling),
 isActive,
 error: readonly(error),
 start,
 stop,
 refresh,
 }
}