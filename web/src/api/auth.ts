/**
 * Auth API 服务
 * 封装所有认证相关的 API 调用
 */
import type {
 AdminProfile,
 AdminProfileUpdate,
 ChangePasswordRequest,
 ForceChangePasswordRequest,
 LoginRequest,
 LoginResponse,
 RefreshResponse,
 User,
} from '~/types'
import { get, post, put } from './client'
/**
 * 用户登录
 * 注意：登录请求需要携带 credentials 以接收 HttpOnly Cookie
 */
export async function login(credentials: LoginRequest): Promise<LoginResponse> {
 return post<LoginResponse>('/auth/login/', credentials, {
 credentials: 'include', // 重要：接收 HttpOnly Cookie
 })
}
/**
 * 用户登出
 * 清除服务端的 Refresh Token Cookie
 */
export async function logout: Promise<void> {
 return post<void>('/auth/logout/', undefined, {
 credentials: 'include',
 })
}
/**
 * 刷新 Access Token
 * 使用 HttpOnly Cookie 中的 Refresh Token 获取新的 Access Token
 */
export async function refresh: Promise<RefreshResponse> {
 return post<RefreshResponse>('/auth/refresh/', undefined, {
 credentials: 'include', // 重要：发送 HttpOnly Cookie
 })
}
/**
 * 获取当前用户信息
 */
export async function getCurrentUser: Promise<User> {
 return get<User>('/auth/me/')
}
/**
 * 修改密码
 */
export async function changePassword(data: ChangePasswordRequest): Promise<void> {
 return post<void>('/auth/change-password/', data)
}
/**
 * 强制修改密码（首次登录或密码重置后）
 */
export async function forceChangePassword(data: ForceChangePasswordRequest): Promise<void> {
 return post<void>('/auth/force-change-password/', data)
}
/**
 * 获取管理员资料
 */
export async function getAdminProfile: Promise<AdminProfile> {
 return get<AdminProfile>('/auth/admin/profile/')
}
/**
 * 更新管理员资料
 */
export async function updateAdminProfile(data: AdminProfileUpdate): Promise<AdminProfile> {
 return put<AdminProfile>('/auth/admin/profile/', data)
}
/**
 * 管理员修改密码
 */
export async function adminChangePassword(data: ChangePasswordRequest): Promise<void> {
 return post<void>('/auth/admin/password/', data)
}
export default {
 login,
 logout,
 refresh,
 getCurrentUser,
 changePassword,
 forceChangePassword,
 getAdminProfile,
 updateAdminProfile,
 adminChangePassword,
}
