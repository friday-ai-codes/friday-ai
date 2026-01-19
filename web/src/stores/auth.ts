/**
 * Auth Store
 * 管理用户认证状态
 */
import type { ChangePasswordRequest, User } from '~/types'
import { authApi } from '~/api'
import { clearAccessToken, setAccessToken } from '~/api/client'
export const useAuthStore = defineStore('auth', => {
 // ============================================================================
 // State
 // ============================================================================
 const user = ref<User | null>(null)
 const isAuthenticated = ref(false)
 const isInitialized = ref(false)
 const loading = ref(false)
 const error = ref<string | null>(null)
 // ============================================================================
 // Getters
 // ============================================================================
 const isAdmin = computed( => user.value?.is_superuser ?? false)
 const displayName = computed( => user.value?.display_name || user.value?.username || '')
 // ============================================================================
 // Actions
 // ============================================================================
 /**
 * 用户登录
 */
 async function login(username: string, password: string) {
 loading.value = true
 error.value = null
 try {
 const response = await authApi.login({ username, password })
 // 存储 Access Token 到内存
 setAccessToken(response.access_token)
 user.value = response.user
 isAuthenticated.value = true
 return response.user
 } catch (e) {
 error.value = e instanceof Error ? e.message: '登录失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 用户登出
 */
 async function logout {
 try {
 await authApi.logout
 } catch {
 // 忽略登出错误，仍然清除本地状态
 } finally {
 clearAccessToken
 user.value = null
 isAuthenticated.value = false
 }
 }
 /**
 * 刷新 Token（静默刷新）
 */
 async function refreshToken {
 try {
 const response = await authApi.refresh
 setAccessToken(response.access_token)
 return response.access_token
 } catch (e) {
 // 刷新失败，清除状态
 clearAccessToken
 user.value = null
 isAuthenticated.value = false
 throw e
 }
 }
 /**
 * 初始化认证状态
 * 应用启动时调用，尝试通过 Refresh Token 恢复登录状态
 */
 async function initAuth {
 if (isInitialized.value) return
 loading.value = true
 try {
 // 尝试刷新 Token
 const response = await authApi.refresh
 setAccessToken(response.access_token)
 // 获取用户信息
 const currentUser = await authApi.getCurrentUser
 user.value = currentUser
 isAuthenticated.value = true
 } catch {
 // 刷新失败，用户未登录
 clearAccessToken
 user.value = null
 isAuthenticated.value = false
 } finally {
 isInitialized.value = true
 loading.value = false
 }
 }
 /**
 * 获取当前用户信息
 */
 async function fetchCurrentUser {
 loading.value = true
 error.value = null
 try {
 const currentUser = await authApi.getCurrentUser
 user.value = currentUser
 return currentUser
 } catch (e) {
 error.value = e instanceof Error ? e.message: '获取用户信息失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 修改密码
 */
 async function changePassword(data: ChangePasswordRequest) {
 loading.value = true
 error.value = null
 try {
 await authApi.changePassword(data)
 } catch (e) {
 error.value = e instanceof Error ? e.message: '修改密码失败'
 throw e
 } finally {
 loading.value = false
 }
 }
 /**
 * 重置状态（用于测试或清理）
 */
 function $reset {
 clearAccessToken
 user.value = null
 isAuthenticated.value = false
 isInitialized.value = false
 loading.value = false
 error.value = null
 }
 return {
 // State
 user,
 isAuthenticated,
 isInitialized,
 loading,
 error,
 // Getters
 isAdmin,
 displayName,
 // Actions
 login,
 logout,
 refreshToken,
 initAuth,
 fetchCurrentUser,
 changePassword,
 $reset,
 }
})
