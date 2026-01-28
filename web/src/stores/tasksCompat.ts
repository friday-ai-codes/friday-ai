import type { TaskStatus } from '~/utils/taskStatusMapper'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { get, post } from '~/api/client'
export interface TaskCompat {
 id: string
 project_id: string
 work_item_id: string
 title: string
 description: string
 status: TaskStatus
 branch_name?: string
 commit_sha?: string
 pr_url?: string
 plan_output?: string
 error_message?: string
 created_at: string
 updated_at?: string
 // Workflow-specific fields
 _workflow_execution_id?: string
 _workflow_id?: string
 _is_workflow?: boolean
}
export const useTasksCompatStore = defineStore('tasksCompat', => {
 const tasks = ref<TaskCompat>
 const currentTask = ref<TaskCompat | null>(null)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // Computed
 const pendingTasks = computed( =>
 tasks.value.filter(t => t.status === 'pending'),
 )
 const activeTasks = computed( =>
 tasks.value.filter(t =>
 ['planning', 'plan_review', 'executing', 'code_review'].includes(t.status),
 ),
 )
 const completedTasks = computed( =>
 tasks.value.filter(t => t.status === 'merged'),
 )
 const failedTasks = computed( =>
 tasks.value.filter(t => t.status === 'failed'),
 )
 const runningTasks = computed( =>
 tasks.value.filter(t => ['planning', 'executing'].includes(t.status)),
 )
 const reviewTasks = computed( =>
 tasks.value.filter(t => ['plan_review', 'code_review'].includes(t.status)),
 )
 const taskCount = computed( => tasks.value.length)
 // Stats for dashboard display
 const stats = computed( => ({
 total: tasks.value.length,
 pending: pendingTasks.value.length,
 running: runningTasks.value.length,
 review: reviewTasks.value.length,
 completed: completedTasks.value.length,
 failed: failedTasks.value.length,
 }))
 /**
 * Fetch tasks list with optional filters.
 * Uses the compatibility API which merges Workflow and legacy Task data.
 */
 async function fetchTasks(filters?: { project_id?: string, status?: string, limit?: number }) {
 loading.value = true
 error.value = null
 try {
 tasks.value = await get<TaskCompat>('/tasks/', filters)
 }
 catch (e: any) {
 error.value = e.message || 'Failed to fetch tasks'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * Fetch a single task by ID.
 */
 async function fetchTask(id: string) {
 loading.value = true
 error.value = null
 try {
 const data = await get<TaskCompat>(`/tasks/${id}/`)
 currentTask.value = data
 return data
 }
 catch (e: any) {
 error.value = e.message || 'Failed to fetch task'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * Approve the current pending node in a task.
 * Only works for workflow-based tasks.
 */
 async function approveTask(taskId: string, comment?: string) {
 // Use the compat API approve endpoint
 try {
 await post(`/tasks/${taskId}/approve/`, { comment })
 // Refresh the task data
 await fetchTask(taskId)
 }
 catch (e: any) {
 error.value = e.message || 'Failed to approve task'
 throw e
 }
 }
 /**
 * Reject the current pending node in a task.
 * Only works for workflow-based tasks.
 */
 async function rejectTask(taskId: string, comment?: string) {
 try {
 await post(`/tasks/${taskId}/reject/`, { comment })
 await fetchTask(taskId)
 }
 catch (e: any) {
 error.value = e.message || 'Failed to reject task'
 throw e
 }
 }
 /**
 * Check if a task is workflow-based (vs legacy Task).
 */
 function isWorkflowTask(task: TaskCompat): boolean {
 return !!task._is_workflow || !!task._workflow_execution_id
 }
 /**
 * Get the workflow ID for navigation.
 */
 function getWorkflowId(task: TaskCompat): string | null {
 return task._workflow_id || null
 }
 /**
 * Clear current task.
 */
 function clearCurrentTask {
 currentTask.value = null
 }
 /**
 * Reset store state.
 */
 function reset {
 tasks.value =
 currentTask.value = null
 loading.value = false
 error.value = null
 }
 return {
 // State
 tasks,
 currentTask,
 loading,
 error,
 // Computed
 pendingTasks,
 activeTasks,
 completedTasks,
 failedTasks,
 runningTasks,
 reviewTasks,
 taskCount,
 stats,
 // Actions
 fetchTasks,
 fetchTask,
 approveTask,
 rejectTask,
 isWorkflowTask,
 getWorkflowId,
 clearCurrentTask,
 reset,
 }
})
