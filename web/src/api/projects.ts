/**
 * Projects API 服务
 * 封装所有项目相关的 API 调用
 */
import type {
 GitCredential,
 Project,
 ProjectCreate,
 ProjectUpdate,
} from '~/types'
import { del, get, patch, post, upload } from './client'
/**
 * 获取项目列表
 */
export async function listProjects: Promise<Project> {
 return get<Project>('/projects/')
}
/**
 * 创建项目
 */
export async function createProject(data: ProjectCreate): Promise<Project> {
 return post<Project>('/projects/', data)
}
/**
 * 获取项目详情
 */
export async function getProject(projectId: string): Promise<Project> {
 return get<Project>(`/projects/${projectId}`)
}
/**
 * 更新项目
 */
export async function updateProject(projectId: string, data: ProjectUpdate): Promise<Project> {
 return patch<Project>(`/projects/${projectId}`, data)
}
/**
 * 删除项目
 */
export async function deleteProject(projectId: string): Promise<void> {
 return del(`/projects/${projectId}`)
}
// ============================================================================
// 凭证管理
// ============================================================================
/**
 * 获取项目凭证
 */
export async function getCredential(projectId: string): Promise<GitCredential> {
 return get<GitCredential>(`/projects/${projectId}/credential`)
}
/**
 * 上传 SSH 密钥
 */
export async function uploadSshKey(
 projectId: string,
 file: File,
 gitUserName: string = 'Friday AI Agent',
 gitUserEmail: string = 'ai-agent@friday.dev',
): Promise<GitCredential> {
 const formData = new FormData
 formData.append('file', file)
 formData.append('git_user_name', gitUserName)
 formData.append('git_user_email', gitUserEmail)
 return upload<GitCredential>(`/projects/${projectId}/credential/ssh-key`, formData)
}
/**
 * 设置 Access Token
 */
export async function setAccessToken(
 projectId: string,
 token: string,
 gitUserName: string = 'Friday AI Agent',
 gitUserEmail: string = 'ai-agent@friday.dev',
): Promise<GitCredential> {
 const formData = new FormData
 formData.append('token', token)
 formData.append('git_user_name', gitUserName)
 formData.append('git_user_email', gitUserEmail)
 return upload<GitCredential>(`/projects/${projectId}/credential/access-token`, formData)
}
/**
 * 删除凭证
 */
export async function deleteCredential(projectId: string): Promise<void> {
 return del(`/projects/${projectId}/credential`)
}
export default {
 list: listProjects,
 create: createProject,
 get: getProject,
 update: updateProject,
 delete: deleteProject,
 getCredential,
 uploadSshKey,
 setAccessToken,
 deleteCredential,
}
