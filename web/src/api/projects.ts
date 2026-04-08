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
 ProjectRepositoryLink,
 ProjectRepositoryLinkCreate,
 ProjectRepositoryLinkUpdate,
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
 return get<Project>(`/projects/${projectId}/`)
}
/**
 * 更新项目
 */
export async function updateProject(projectId: string, data: ProjectUpdate): Promise<Project> {
 return patch<Project>(`/projects/${projectId}/`, data)
}
/**
 * 删除项目
 */
export async function deleteProject(projectId: string): Promise<void> {
 return del(`/projects/${projectId}/`)
}
// ============================================================================
// 仓库关联管理（新 API：批量关联 + 权限管理）
// ============================================================================
/**
 * 获取项目关联的仓库列表
 */
export async function getProjectRepositories(projectId: string): Promise<ProjectRepositoryLink> {
 return get<ProjectRepositoryLink>(`/projects/${projectId}/repositories/`)
}
/**
 * 批量关联仓库到项目
 */
export async function linkRepositories(projectId: string, data: ProjectRepositoryLinkCreate): Promise<{ created: ProjectRepositoryLink, skipped: string }> {
 return post<{ created: ProjectRepositoryLink, skipped: string }>(`/projects/${projectId}/repositories/`, data)
}
/**
 * 修改关联权限级别
 */
export async function updateRepositoryLink(projectId: string, linkId: string, data: ProjectRepositoryLinkUpdate): Promise<ProjectRepositoryLink> {
 return patch<ProjectRepositoryLink>(`/projects/${projectId}/repositories/${linkId}/`, data)
}
/**
 * 移除仓库关联
 */
export async function unlinkRepository(projectId: string, linkId: string): Promise<void> {
 return del(`/projects/${projectId}/repositories/${linkId}/`)
}
// ============================================================================
// 仓库关联管理（旧 API：保留向后兼容）
// ============================================================================
/**
 * 关联仓库
 */
export async function addRepository(projectId: string, repositoryId: string): Promise<void> {
 return post(`/projects/${projectId}/repositories/${repositoryId}/`)
}
/**
 * 解除关联仓库
 */
export async function removeRepository(projectId: string, repositoryId: string): Promise<void> {
 return del(`/projects/${projectId}/repositories/${repositoryId}/`)
}
// ============================================================================
// 飞书配置管理
// ============================================================================
/**
 * 获取项目的飞书配置
 */
export async function getFeishuConfig(projectId: string): Promise<FeishuConfig> {
 return get<FeishuConfig>(`/feishu/projects/${projectId}/config/`)
}
/**
 * 设置项目的飞书配置
 */
export async function setFeishuConfig(
 projectId: string,
 config: FeishuConfigCreate,
): Promise<FeishuConfig> {
 return put<FeishuConfig>(`/feishu/projects/${projectId}/config/`, config)
}
/**
 * 删除项目的飞书配置
 */
export async function deleteFeishuConfig(projectId: string): Promise<void> {
 return del(`/feishu/projects/${projectId}/config/`)
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
 return post<FeishuConfigTestResult>(`/feishu/projects/${projectId}/config/test/`, testConfig || {})
}
// ============================================================================
// Webhook Token 管理
// ============================================================================
/**
 * 刷新项目的 Webhook Token（生成新的随机 Token）
 */
export async function refreshWebhookToken(projectId: string): Promise<WebhookTokenRead> {
 return post<WebhookTokenRead>(`/feishu/projects/${projectId}/refresh-token/`)
}
/**
 * 更新项目的 Webhook Token（自定义 Token，最大 32 字符）
 */
export async function updateWebhookToken(
 projectId: string,
 data: WebhookTokenUpdate,
): Promise<WebhookTokenRead> {
 return put<WebhookTokenRead>(`/feishu/projects/${projectId}/token/`, data)
}
// ============================================================================
// 飞书文档导出配置 (Phase)
// ============================================================================
export interface FeishuDocConfig {
 feishu_doc_folder_token: string
}
/**
 * 获取飞书文档导出配置
 */
export async function getFeishuDocConfig(projectId: string): Promise<FeishuDocConfig> {
 return get<FeishuDocConfig>(`/projects/${projectId}/feishu-doc-config/`)
}
/**
 * 更新飞书文档导出配置
 */
export async function updateFeishuDocConfig(
 projectId: string,
 data: FeishuDocConfig,
): Promise<FeishuDocConfig> {
 return put<FeishuDocConfig>(`/projects/${projectId}/feishu-doc-config/`, data)
}
export default {
 list: listProjects,
 create: createProject,
 get: getProject,
 update: updateProject,
 delete: deleteProject,
 addRepository,
 removeRepository,
 // 仓库关联管理（新 API）
 getProjectRepositories,
 linkRepositories,
 updateRepositoryLink,
 unlinkRepository,
 // 飞书配置
 getFeishuConfig,
 setFeishuConfig,
 deleteFeishuConfig,
 testFeishuConfig,
 // Webhook Token 管理
 refreshWebhookToken,
 updateWebhookToken,
}
