/**
 * Spaces API 服务
 * 封装所有空间相关的 API 调用
 */

import type {
  FeishuConfig,
  FeishuConfigCreate,
  FeishuConfigTest,
  FeishuConfigTestResult,
  Space,
  SpaceCreate,
  SpaceRepositoryLink,
  SpaceRepositoryLinkCreate,
  SpaceRepositoryLinkUpdate,
  SpaceUpdate,
  WebhookTokenRead,
  WebhookTokenUpdate,
} from '~/types'
import { del, get, patch, post, put } from './client'

/**
 * 获取空间列表
 */
export async function listSpaces(): Promise<Space[]> {
  return get<Space[]>('/spaces/')
}

/**
 * 创建空间
 */
export async function createSpace(data: SpaceCreate): Promise<Space> {
  return post<Space>('/spaces/', data)
}

/**
 * 获取空间详情
 */
export async function getSpace(spaceId: string): Promise<Space> {
  return get<Space>(`/spaces/${spaceId}/`)
}

/**
 * 更新空间
 */
export async function updateSpace(spaceId: string, data: SpaceUpdate): Promise<Space> {
  return patch<Space>(`/spaces/${spaceId}/`, data)
}

/**
 * 删除空间
 */
export async function deleteSpace(spaceId: string): Promise<void> {
  return del(`/spaces/${spaceId}/`)
}

// ============================================================================
// 仓库关联管理（新 API：批量关联 + 权限管理）
// ============================================================================

/**
 * 获取空间关联的仓库列表
 */
export async function getSpaceRepositories(spaceId: string): Promise<SpaceRepositoryLink[]> {
  return get<SpaceRepositoryLink[]>(`/spaces/${spaceId}/repositories/`)
}

/**
 * 批量关联仓库到空间
 */
export async function linkRepositories(spaceId: string, data: SpaceRepositoryLinkCreate): Promise<{ created: SpaceRepositoryLink[], skipped: string[] }> {
  return post<{ created: SpaceRepositoryLink[], skipped: string[] }>(`/spaces/${spaceId}/repositories/`, data)
}

/**
 * 修改关联权限级别
 */
export async function updateRepositoryLink(spaceId: string, linkId: string, data: SpaceRepositoryLinkUpdate): Promise<SpaceRepositoryLink> {
  return patch<SpaceRepositoryLink>(`/spaces/${spaceId}/repositories/${linkId}/`, data)
}

/**
 * 移除仓库关联
 */
export async function unlinkRepository(spaceId: string, linkId: string): Promise<void> {
  return del(`/spaces/${spaceId}/repositories/${linkId}/`)
}

// ============================================================================
// 仓库关联管理（兼容旧调用方式，内部委托批量 API）
// ============================================================================

/**
 * 关联单个仓库（委托 linkRepositories 批量 API）
 */
export async function addRepository(spaceId: string, repositoryId: string): Promise<void> {
  await linkRepositories(spaceId, { repository_ids: [repositoryId] })
}

/**
 * 解除关联仓库
 */
export async function removeRepository(spaceId: string, repositoryId: string): Promise<void> {
  return del(`/spaces/${spaceId}/repositories/${repositoryId}/`)
}

// ============================================================================
// 飞书配置管理
// ============================================================================

/**
 * 获取空间的飞书配置
 */
export async function getFeishuConfig(spaceId: string): Promise<FeishuConfig> {
  return get<FeishuConfig>(`/feishu/spaces/${spaceId}/config/`)
}

/**
 * 设置空间的飞书配置
 */
export async function setFeishuConfig(
  spaceId: string,
  config: FeishuConfigCreate,
): Promise<FeishuConfig> {
  return put<FeishuConfig>(`/feishu/spaces/${spaceId}/config/`, config)
}

/**
 * 删除空间的飞书配置
 */
export async function deleteFeishuConfig(spaceId: string): Promise<void> {
  return del(`/feishu/spaces/${spaceId}/config/`)
}

/**
 * 测试空间的飞书配置
 * @param spaceId 空间 ID
 * @param testConfig 可选的临时配置，不传则使用已保存的配置
 */
export async function testFeishuConfig(
  spaceId: string,
  testConfig?: FeishuConfigTest,
): Promise<FeishuConfigTestResult> {
  return post<FeishuConfigTestResult>(`/feishu/spaces/${spaceId}/config/test/`, testConfig || {})
}

// ============================================================================
// Webhook Token 管理
// ============================================================================

/**
 * 刷新空间的 Webhook Token（生成新的随机 Token）
 */
export async function refreshWebhookToken(spaceId: string): Promise<WebhookTokenRead> {
  return post<WebhookTokenRead>(`/feishu/spaces/${spaceId}/refresh-token/`)
}

/**
 * 更新空间的 Webhook Token（自定义 Token，最大 32 字符）
 */
export async function updateWebhookToken(
  spaceId: string,
  data: WebhookTokenUpdate,
): Promise<WebhookTokenRead> {
  return put<WebhookTokenRead>(`/feishu/spaces/${spaceId}/token/`, data)
}

// ============================================================================
// 飞书文档导出配置
// ============================================================================

export interface FeishuDocConfig {
  feishu_doc_folder_token: string
}

/**
 * 获取飞书文档导出配置
 */
export async function getFeishuDocConfig(spaceId: string): Promise<FeishuDocConfig> {
  return get<FeishuDocConfig>(`/spaces/${spaceId}/feishu-doc-config/`)
}

/**
 * 更新飞书文档导出配置
 */
export async function updateFeishuDocConfig(
  spaceId: string,
  data: FeishuDocConfig,
): Promise<FeishuDocConfig> {
  return put<FeishuDocConfig>(`/spaces/${spaceId}/feishu-doc-config/`, data)
}

export default {
  list: listSpaces,
  create: createSpace,
  get: getSpace,
  update: updateSpace,
  delete: deleteSpace,
  addRepository,
  removeRepository,
  // 仓库关联管理（新 API）
  getSpaceRepositories,
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
