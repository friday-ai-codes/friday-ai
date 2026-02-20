/**
 * Runners Store
 * 管理 Runner 列表和 Runner 相关操作
 */
import type { Runner } from '~/types'
import { runnersApi } from '~/api'
export const useRunnersStore = defineStore('runners', => {
 // ============================================================================
 // State
 // ============================================================================
 const runners = ref<Runner>
 const loading = ref(false)
 const error = ref<string | null>(null)
 // ============================================================================
 // Getters
 // ============================================================================
 const onlineRunners = computed( => runners.value.filter(r => r.status === 'online'))
 const offlineRunners = computed( => runners.value.filter(r => r.status === 'offline'))
 const runnerCount = computed( => runners.value.length)
 // ============================================================================
 // Actions
 // ============================================================================
 /**
 * 获取 Runner 列表
 */
 async function fetchRunners {
 loading.value = true
 error.value = null
 try {
 runners.value = await runnersApi.list
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取 Runner 列表失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 删除 Runner
 */
 async function removeRunner(runnerId: string) {
 loading.value = true
 error.value = null
 try {
 await runnersApi.delete(runnerId)
 runners.value = runners.value.filter(r => r.id !== runnerId)
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '删除 Runner 失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 return {
 // State
 runners,
 loading,
 error,
 // Getters
 onlineRunners,
 offlineRunners,
 runnerCount,
 // Actions
 fetchRunners,
 removeRunner,
 }
})
