// 全局类型定义
/**
 * 任务状态枚举
 */
export type TaskStatus =
 | 'pending'
 | 'planning'
 | 'in_progress'
 | 'reviewing'
 | 'completed'
 | 'failed'
/**
 * 任务接口
 */
export interface Task {
 id: string
 title: string
 description?: string
 status: TaskStatus
 createdAt: string
 updatedAt: string
}
/**
 * 项目接口
 */
export interface Project {
 id: string
 name: string
 repository: string
 branch: string
 createdAt: string
}
/**
 * API 响应接口
 */
export interface ApiResponse<T> {
 data: T
 message?: string
 error?: string
}