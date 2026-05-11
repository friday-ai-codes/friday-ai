/**
 * Space Members API 服务
 * 封装空间成员管理相关的 API 调用
 */
import type { SpaceMembership } from '~/types'
import { del, get, patch, post } from './client'
/**
 * 获取空间成员列表
 */
export async function listSpaceMembers(spaceId: string): Promise<SpaceMembership> {
 return get<SpaceMembership>(`/spaces/${spaceId}/members/`)
}
/**
 * 添加空间成员
 */
export async function addSpaceMember(
 spaceId: string,
 data: { user_id: string, role: 'admin' | 'member' | 'viewer' },
): Promise<SpaceMembership> {
 return post<SpaceMembership>(`/spaces/${spaceId}/members/`, data)
}
/**
 * 更新空间成员角色
 */
export async function updateSpaceMember(
 spaceId: string,
 userId: string,
 data: { role: 'admin' | 'member' | 'viewer' },
): Promise<SpaceMembership> {
 return patch<SpaceMembership>(`/spaces/${spaceId}/members/${userId}/`, data)
}
/**
 * 移除空间成员
 */
export async function removeSpaceMember(spaceId: string, userId: string): Promise<void> {
 return del(`/spaces/${spaceId}/members/${userId}/`)
}
export default {
 listSpaceMembers,
 addSpaceMember,
 updateSpaceMember,
 removeSpaceMember,
}
