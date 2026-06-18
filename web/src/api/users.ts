/**
 * Users API 服务
 * 封装用户管理和邀请相关的 API 调用
 */

import type { AdminUserMembership, Invitation, MeUser, SystemUser } from '~/types'
import { get, patch, post } from './client'

/**
 * 获取当前用户完整信息（含 gravatar_url 和 project_memberships）
 */
export async function getMe(): Promise<MeUser> {
  return get<MeUser>('/auth/me/')
}

/**
 * 更新当前用户资料
 */
export async function updateProfile(data: { display_name: string }): Promise<MeUser> {
  return patch<MeUser>('/auth/me/profile/', data)
}

/**
 * 创建邀请令牌（仅超级管理员）
 */
export async function createInvitation(email?: string): Promise<Invitation> {
  return post<Invitation>('/auth/invite/', { email: email ?? '' })
}

/**
 * 校验邀请令牌有效性（公开端点）
 */
export async function validateInvitation(token: string): Promise<Invitation> {
  return get<Invitation>(`/auth/invite/?token=${encodeURIComponent(token)}`)
}

/**
 * 接受邀请并注册新用户（公开端点）
 */
export async function acceptInvitation(data: {
  token: string
  username: string
  password: string
  display_name?: string
}): Promise<SystemUser> {
  return post<SystemUser>('/auth/invite/accept/', data)
}

/**
 * 获取系统用户列表（仅超级管理员）
 */
export async function listUsers(): Promise<SystemUser[]> {
  return get<SystemUser[]>('/auth/users/')
}

/**
 * 更新用户状态（启用/禁用、授予/取消超级管理员，仅超级管理员）
 */
export async function updateUser(
  userId: string,
  data: { is_active?: boolean, is_superuser?: boolean },
): Promise<SystemUser> {
  return patch<SystemUser>(`/auth/users/${userId}/`, data)
}

/**
 * 获取指定用户的跨空间成员关系（仅超级管理员）
 */
export async function getUserMemberships(userId: string): Promise<AdminUserMembership[]> {
  return get<AdminUserMembership[]>(`/auth/users/${userId}/memberships/`)
}

export default {
  getMe,
  updateProfile,
  createInvitation,
  validateInvitation,
  acceptInvitation,
  listUsers,
  updateUser,
  getUserMemberships,
}
