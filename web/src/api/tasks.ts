/**
 * Tasks API 服务
 * 封装所有任务相关的 API 调用
 */
import type {
 ContainerStatusResponse,
 Task,
 TaskCreate,
 TaskExecuteRequest,
 TaskExecuteResponse,
 TaskFilters,
 TaskLogsResponse,
 TaskStatus,
 TaskUpdate,
} from '~/types'
import { del, get, patch, post } from './client'
/**
 * 获取任务列表
 */
export async function listTasks(filters?: TaskFilters): Promise<Task> {
 return get<Task>('/tasks/', {
 project_id: filters?.project_id,
 status: filters?.status,
 limit: filters?.limit,
 offset: filters?.offset,
 })
}
/**
 * 创建任务
 */
export async function createTask(data: TaskCreate): Promise<Task> {
 return post<Task>('/tasks/', data)
}
/**
 * 获取任务详情
 */
export async function getTask(taskId: string): Promise<Task> {
 return get<Task>(`/tasks/${taskId}`)
}
/**
 * 通过工作项 ID 获取任务
 */
export async function getTaskByWorkItem(workItemId: string): Promise<Task> {
 return get<Task>(`/tasks/work-item/${workItemId}`)
}
/**
 * 更新任务
 */
export async function updateTask(taskId: string, data: TaskUpdate): Promise<Task> {
 return patch<Task>(`/tasks/${taskId}`, data)
}
/**
 * 删除任务
 */
export async function deleteTask(taskId: string): Promise<void> {
 return del(`/tasks/${taskId}`)
}
/**
 * 任务状态转换
 */
export async function transitionTask(taskId: string, newStatus: TaskStatus): Promise<Task> {
 return post<Task>(`/tasks/${taskId}/transition/${newStatus}`)
}
/**
 * 执行任务
 */
export async function executeTask(
 taskId: string,
 request: TaskExecuteRequest,
): Promise<TaskExecuteResponse> {
 return post<TaskExecuteResponse>(`/tasks/${taskId}/execute`, request)
}
/**
 * 停止任务
 */
export async function stopTask(
 taskId: string,
 force: boolean = false,
): Promise<{ status: string, message: string }> {
 return post<{ status: string, message: string }>(`/tasks/${taskId}/stop`, undefined, {
 params: { force: force ? 'true': undefined },
 })
}
/**
 * 获取任务日志
 */
export async function getTaskLogs(taskId: string, tail: number = 100): Promise<TaskLogsResponse> {
 return get<TaskLogsResponse>(`/tasks/${taskId}/logs`, { tail })
}
/**
 * 获取容器状态
 */
export async function getContainerStatus(taskId: string): Promise<ContainerStatusResponse> {
 return get<ContainerStatusResponse>(`/tasks/${taskId}/container-status`)
}
export default {
 list: listTasks,
 create: createTask,
 get: getTask,
 getByWorkItem: getTaskByWorkItem,
 update: updateTask,
 delete: deleteTask,
 transition: transitionTask,
 execute: executeTask,
 stop: stopTask,
 getLogs: getTaskLogs,
 getContainerStatus,
}
