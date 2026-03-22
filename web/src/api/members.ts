/**
 * Project Members API 服务
 * 封装项目成员管理相关的 API 调用
 */
import type { ProjectMembership } from '~/types'
import { del, get, patch, post } from './client'
/**
 * 获取项目成员列表
 */
export async function listProjectMembers(projectId: string): Promise<ProjectMembership> {
 return get<ProjectMembership>(`/projects/${projectId}/members/`)
}
/**
 * 添加项目成员
 */
export async function addProjectMember(
 projectId: string,
 data: { user_id: string, role: 'admin' | 'member' | 'viewer' },
): Promise<ProjectMembership> {
 return post<ProjectMembership>(`/projects/${projectId}/members/`, data)
}
/**
 * 更新项目成员角色
 */
export async function updateProjectMember(
 projectId: string,
 userId: string,
 data: { role: 'admin' | 'member' | 'viewer' },
): Promise<ProjectMembership> {
 return patch<ProjectMembership>(`/projects/${projectId}/members/${userId}/`, data)
}
/**
 * 移除项目成员
 */
export async function removeProjectMember(projectId: string, userId: string): Promise<void> {
 return del(`/projects/${projectId}/members/${userId}/`)
}
export default {
 listProjectMembers,
 addProjectMember,
 updateProjectMember,
 removeProjectMember,
}
