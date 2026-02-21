/**
 * Runners Store
 * 管理 Runner 列表和 Runner 相关操作
 */
import type { RegistrationToken, RegistrationTokenCreate, RegistrationTokenCreateResponse, Runner } from '~/types'
import { runnersApi } from '~/api'
export const useRunnersStore = defineStore('runners', => {
 // ============================================================================
 // State
 // ============================================================================
 const runners = ref<Runner>
 const tokens = ref<RegistrationToken>
 const currentRunner = ref<Runner | null>(null)
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
 async function fetchRunner(runnerId: string) {
 loading.value = true
 error.value = null
 try {
 currentRunner.value = await runnersApi.getRunner(runnerId)
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取 Runner 详情失败'
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
 async function fetchTokens {
 tokens.value = await runnersApi.listTokens
 }
 async function addToken(data: RegistrationTokenCreate): Promise<RegistrationTokenCreateResponse> {
 const result = await runnersApi.createToken(data)
 await fetchTokens
 return result
 }
 async function removeToken(tokenId: string) {
 await runnersApi.deleteToken(tokenId)
 tokens.value = tokens.value.filter(t => t.id !== tokenId)
 }
 /**
 * WS 事件：patch runner 状态字段
 */
 function patchRunner(runnerId: string, data: Record<string, unknown>) {
 const idx = runners.value.findIndex(r => r.id === runnerId)
 if (idx !== -1) Object.assign(runners.value[idx], data)
 if (currentRunner.value?.id === runnerId) Object.assign(currentRunner.value, data)
 }
 /**
 * WS 事件：patch runner 的任务状态
 */
 function patchRunnerTask(runnerId: string, data: Record<string, unknown>) {
 const taskStatus = data.status as string
 const taskId = data.task_id as string
 // 更新列表页 runner 的 current_tasks
 const idx = runners.value.findIndex(r => r.id === runnerId)
 if (taskStatus === 'running' && idx !== -1) {
 runners.value[idx].current_tasks += 1
 }
 else if ((taskStatus === 'completed' || taskStatus === 'failed') && idx !== -1) {
 runners.value[idx].current_tasks = Math.max(0, runners.value[idx].current_tasks - 1)
 }
 // 更新详情页 currentRunner 的 current_task_list
 if (currentRunner.value?.id !== runnerId) return
 if (taskStatus === 'completed' || taskStatus === 'failed') {
 currentRunner.value.current_task_list = currentRunner.value.current_task_list.filter(t => t.id !== taskId)
 currentRunner.value.current_tasks = Math.max(0, currentRunner.value.current_tasks - 1)
 }
 else if (taskStatus === 'running') {
 currentRunner.value.current_tasks += 1
 const task = currentRunner.value.current_task_list.find(t => t.id === taskId)
 if (task) task.status = 'running'
 }
 }
 return {
 // State
 runners,
 tokens,
 currentRunner,
 loading,
 error,
 // Getters
 onlineRunners,
 offlineRunners,
 runnerCount,
 // Actions
 fetchRunners,
 fetchRunner,
 removeRunner,
 fetchTokens,
 addToken,
 removeToken,
 patchRunner,
 patchRunnerTask,
 }
})
