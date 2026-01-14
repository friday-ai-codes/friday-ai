/**
 * Tasks Store
 * 管理任务列表和任务相关操作
 */
import { tasksApi } from '~/api'
import type {
 ContainerStatusResponse,
 Task,
 TaskCreate,
 TaskFilters,
 TaskStatus,
 TaskUpdate,
} from '~/types'
export const useTasksStore = defineStore('tasks', => {
 // ============================================================================
 // State
 // ============================================================================
 const tasks = ref<Task>
 const currentTask = ref<Task | null>(null)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // 过滤条件
 const filters = ref<TaskFilters>({
 limit: 50,
 offset: 0,
 })
 // 日志相关
 const currentLogs = ref<string>('')
 const containerStatus = ref<ContainerStatusResponse | null>(null)
 // ============================================================================
 // Getters
 // ============================================================================
 const taskById = computed( => {
 return (id: string) => tasks.value.find((t) => t.id === id)
 })
 const taskCount = computed( => tasks.value.length)
 const tasksByStatus = computed( => {
 return (status: TaskStatus) => tasks.value.filter((t) => t.status === status)
 })
 const pendingTasks = computed( => tasksByStatus.value('pending'))
 const runningTasks = computed( => [
 ...tasksByStatus.value('planning'),
 ...tasksByStatus.value('executing'),
 ])
 const reviewTasks = computed( => [
 ...tasksByStatus.value('plan_review'),
 ...tasksByStatus.value('code_review'),
 ])
 const completedTasks = computed( => tasksByStatus.value('merged'))
 const failedTasks = computed( => tasksByStatus.value('failed'))
 // 统计数据
 const stats = computed( => ({
 total: tasks.value.length,
 pending: pendingTasks.value.length,
 running: runningTasks.value.length,
 review: reviewTasks.value.length,
 completed: completedTasks.value.length,
 failed: failedTasks.value.length,
 }))
 // ============================================================================
 // Actions
 // ============================================================================
 /**
 * 获取任务列表
 */
 async function fetchTasks(newFilters?: TaskFilters) {
 if (newFilters) {
 filters.value = { ...filters.value, ...newFilters }
 }
 loading.value = true
 error.value = null
 try {
 tasks.value = await tasksApi.list(filters.value)
 } catch (e) {
 error.value = e instanceof Error ? e.message: '获取任务列表失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 获取单个任务详情
 */
 async function fetchTask(taskId: string) {
 loading.value = true
 error.value = null
 try {
 currentTask.value = await tasksApi.get(taskId)
 return currentTask.value
 } catch (e) {
 error.value = e instanceof Error ? e.message: '获取任务详情失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 创建任务
 */
 async function createTask(data: TaskCreate) {
 loading.value = true
 error.value = null
 try {
 const newTask = await tasksApi.create(data)
 tasks.value.unshift(newTask)
 return newTask
 } catch (e) {
 error.value = e instanceof Error ? e.message: '创建任务失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 更新任务
 */
 async function updateTask(taskId: string, data: TaskUpdate) {
 loading.value = true
 error.value = null
 try {
 const updatedTask = await tasksApi.update(taskId, data)
 updateTaskInList(updatedTask)
 return updatedTask
 } catch (e) {
 error.value = e instanceof Error ? e.message: '更新任务失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 删除任务
 */
 async function deleteTask(taskId: string) {
 loading.value = true
 error.value = null
 try {
 await tasksApi.delete(taskId)
 tasks.value = tasks.value.filter((t) => t.id !== taskId)
 if (currentTask.value?.id === taskId) {
 currentTask.value = null
 }
 } catch (e) {
 error.value = e instanceof Error ? e.message: '删除任务失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 任务状态转换
 */
 async function transitionTask(taskId: string, newStatus: TaskStatus) {
 loading.value = true
 error.value = null
 try {
 const updatedTask = await tasksApi.transition(taskId, newStatus)
 updateTaskInList(updatedTask)
 return updatedTask
 } catch (e) {
 error.value = e instanceof Error ? e.message: '状态转换失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 执行任务
 */
 async function executeTask(taskId: string, mode: 'plan' | 'execute') {
 loading.value = true
 error.value = null
 try {
 const response = await tasksApi.execute(taskId, { mode })
 // 刷新任务状态
 await fetchTask(taskId)
 return response
 } catch (e) {
 error.value = e instanceof Error ? e.message: '执行任务失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 停止任务
 */
 async function stopTask(taskId: string, force: boolean = false) {
 loading.value = true
 error.value = null
 try {
 const response = await tasksApi.stop(taskId, force)
 // 刷新任务状态
 await fetchTask(taskId)
 return response
 } catch (e) {
 error.value = e instanceof Error ? e.message: '停止任务失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 获取任务日志
 */
 async function fetchLogs(taskId: string, tail: number = 100) {
 try {
 const response = await tasksApi.getLogs(taskId, tail)
 currentLogs.value = response.logs
 return response.logs
 } catch (e) {
 // 如果没有日志，不报错
 currentLogs.value = ''
 return ''
 }
 }
 /**
 * 获取容器状态
 */
 async function fetchContainerStatus(taskId: string) {
 try {
 containerStatus.value = await tasksApi.getContainerStatus(taskId)
 return containerStatus.value
 } catch (e) {
 containerStatus.value = null
 return null
 }
 }
 /**
 * 更新列表中的任务
 */
 function updateTaskInList(updatedTask: Task) {
 const index = tasks.value.findIndex((t) => t.id === updatedTask.id)
 if (index !== -1) {
 tasks.value[index] = updatedTask
 }
 if (currentTask.value?.id === updatedTask.id) {
 currentTask.value = updatedTask
 }
 }
 /**
 * 设置过滤条件
 */
 function setFilters(newFilters: Partial<TaskFilters>) {
 filters.value = { ...filters.value, ...newFilters }
 }
 /**
 * 清空过滤条件
 */
 function clearFilters {
 filters.value = { limit: 50, offset: 0 }
 }
 /**
 * 清空当前任务
 */
 function clearCurrent {
 currentTask.value = null
 currentLogs.value = ''
 containerStatus.value = null
 }
 return {
 // State
 tasks,
 currentTask,
 loading,
 error,
 filters,
 currentLogs,
 containerStatus,
 // Getters
 taskById,
 taskCount,
 tasksByStatus,
 pendingTasks,
 runningTasks,
 reviewTasks,
 completedTasks,
 failedTasks,
 stats,
 // Actions
 fetchTasks,
 fetchTask,
 createTask,
 updateTask,
 deleteTask,
 transitionTask,
 executeTask,
 stopTask,
 fetchLogs,
 fetchContainerStatus,
 setFilters,
 clearFilters,
 clearCurrent,
 }
})