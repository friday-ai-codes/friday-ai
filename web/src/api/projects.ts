/**
 * Projects API 服务
 * 封装所有项目相关的 API 调用
 */
import type {
 FeishuConfig,
 FeishuConfigCreate,
 FeishuConfigTest,
 FeishuConfigTestResult,
 Project,
 ProjectCreate,
 ProjectUpdate,
 WebhookTokenRead,
 WebhookTokenUpdate,
} from '~/types'
import { del, get, patch, post, put } from './client'
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
// 仓库关联管理
// ============================================================================
/**
 * 关联仓库
 */
export async function addRepository(projectId: string, repositoryId: string): Promise<void> {
 return post(`/projects/${projectId}/repositories/${repositoryId}`)
}
/**
 * 解除关联仓库
 */
export async function removeRepository(projectId: string, repositoryId: string): Promise<void> {
 return del(`/projects/${projectId}/repositories/${repositoryId}`)
}
// ============================================================================
// 飞书配置管理
// ============================================================================
/**
 * 获取项目的飞书配置
 */
export async function getFeishuConfig(projectId: string): Promise<FeishuConfig> {
 return get<FeishuConfig>(`/feishu/projects/${projectId}/config`)
}
/**
 * 设置项目的飞书配置
 */
export async function setFeishuConfig(
 projectId: string,
 config: FeishuConfigCreate,
): Promise<FeishuConfig> {
 return put<FeishuConfig>(`/feishu/projects/${projectId}/config`, config)
}
/**
 * 删除项目的飞书配置
 */
export async function deleteFeishuConfig(projectId: string): Promise<void> {
 return del(`/feishu/projects/${projectId}/config`)
}
/**
 * 测试项目的飞书配置
 * @param projectId 项目 ID
 * @param testConfig 可选的临时配置，不传则使用已保存的配置
 */
export async function testFeishuConfig(
 projectId: string,
 testConfig?: FeishuConfigTest,
): Promise<FeishuConfigTestResult> {
 return post<FeishuConfigTestResult>(`/feishu/projects/${projectId}/config/test`, testConfig || {})
}
// ============================================================================
// Webhook Token 管理
// ============================================================================
/**
 * 刷新项目的 Webhook Token（生成新的随机 Token）
 */
export async function refreshWebhookToken(projectId: string): Promise<WebhookTokenRead> {
 return post<WebhookTokenRead>(`/feishu/projects/${projectId}/refresh-token`)
}
/**
 * 更新项目的 Webhook Token（自定义 Token，最大 32 字符）
 */
export async function updateWebhookToken(
 projectId: string,
 data: WebhookTokenUpdate,
): Promise<WebhookTokenRead> {
 return put<WebhookTokenRead>(`/feishu/projects/${projectId}/token`, data)
}
export default {
 list: listProjects,
 create: createProject,
 get: getProject,
 update: updateProject,
 delete: deleteProject,
 addRepository,
 removeRepository,
 // 飞书配置
 getFeishuConfig,
 setFeishuConfig,
 deleteFeishuConfig,
 testFeishuConfig,
 // Webhook Token 管理
 refreshWebhookToken,
 updateWebhookToken,
}
