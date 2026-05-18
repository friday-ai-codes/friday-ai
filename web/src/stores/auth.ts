/**
 * Auth Store
 * 管理用户认证状态（认证通过 HTTP-only Cookie，前端不管理 token）
 */
import type { AdminProfileUpdate, ChangePasswordRequest, ForceChangePasswordRequest, SpaceMembershipBrief, User } from '~/types'
import { authApi } from '~/api'
import { getMe, updateProfile } from '~/api/users'
export const useAuthStore = defineStore('auth', => {
 // ============================================================================
 // State
 // ============================================================================
 const user = ref<User | null>(null)
 const isAuthenticated = ref(false)
 const isInitialized = ref(false)
 const loading = ref(false)
 const error = ref<string | null>(null)
 const mustChangePassword = ref(false)
 const spaceMemberships = ref<SpaceMembershipBrief>
 const gravatarUrl = ref<string | null>(null)
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
 user.value = response.user
 isAuthenticated.value = true
 mustChangePassword.value = response.must_change_password
 // 登录成功后立即获取完整用户信息（含 spaceMemberships）
 try {
 await fetchMe
 }
 catch {
 // 静默忽略，不影响登录流程（与 initAuth 处理方式一致）
 }
 return { user: response.user, mustChangePassword: response.must_change_password }
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '登录失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 用户登出
 *
 * 注：Friday 只能清自己域下的 cookie，无法清 OIDC IdP（如飞书）域下的会话。
 * 为避免"点退出后再点 OIDC 登录被 IdP 静默放行、用户感觉没退出"的问题，
 * 这里在 sessionStorage 设置一个一次性标志，登录页发起 OIDC 授权时会读取
 * 该标志并附带 `prompt=login`，强制 IdP 重新交互一次。
 *
 * sessionStorage 而非 localStorage：标志只在当前浏览器标签页有效，不跨标签
 * 误伤其他登录态。
 */
 async function logout {
 try {
 await authApi.logout
 }
 catch {
 // 忽略登出错误，仍然清除本地状态
 }
 finally {
 user.value = null
 isAuthenticated.value = false
 try {
 sessionStorage.setItem('oidc_force_reauth', '1')
 }
 catch {
 // 隐私模式下 sessionStorage 可能不可用，静默忽略
 }
 }
 }
 /**
 * 初始化认证状态
 * 应用启动时调用，直接请求 /me 验证登录态（cookie 自动携带）
 */
 async function initAuth {
 if (isInitialized.value)
 return
 loading.value = true
 try {
 // 直接请求当前用户信息，cookie 自动携带 access token
 const currentUser = await authApi.getCurrentUser
 user.value = currentUser
 isAuthenticated.value = true
 // 获取扩展用户信息（含空间成员列表）
 try {
 const meData = await getMe
 spaceMemberships.value = meData.space_memberships
 gravatarUrl.value = meData.gravatar_url
 }
 catch {
 // 忽略 /me 扩展信息获取失败，不影响认证流程
 }
 }
 catch {
 // 用户未登录（401）或发生其他错误
 user.value = null
 isAuthenticated.value = false
 }
 finally {
 isInitialized.value = true
 loading.value = false
 }
 }
 /**
 * 获取当前用户完整信息（含空间成员列表和 gravatar）
 */
 async function fetchMe {
 try {
 const meData = await getMe
 spaceMemberships.value = meData.space_memberships
 gravatarUrl.value = meData.gravatar_url
 if (user.value) {
 user.value.display_name = meData.display_name
 }
 return meData
 }
 catch {
 // 忽略错误
 }
 }
 /**
 * 更新当前用户显示名
 */
 async function updateDisplayName(displayName: string) {
 const meData = await updateProfile({ display_name: displayName })
 if (user.value) {
 user.value.display_name = meData.display_name
 }
 return meData
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
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取用户信息失败'
 throw e
 }
 finally {
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
 mustChangePassword.value = false
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '修改密码失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 强制修改密码（首次登录或密码重置后）
 */
 async function forceChangePassword(data: ForceChangePasswordRequest) {
 loading.value = true
 error.value = null
 try {
 await authApi.forceChangePassword(data)
 mustChangePassword.value = false
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '修改密码失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 获取管理员资料
 */
 async function getAdminProfile {
 loading.value = true
 error.value = null
 try {
 return await authApi.getAdminProfile
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '获取管理员资料失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 更新管理员资料
 */
 async function updateAdminProfile(data: AdminProfileUpdate) {
 loading.value = true
 error.value = null
 try {
 const profile = await authApi.updateAdminProfile(data)
 // 更新本地用户信息
 if (user.value) {
 user.value.username = profile.username
 user.value.display_name = profile.display_name
 }
 return profile
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '更新管理员资料失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 管理员修改密码
 */
 async function adminChangePassword(data: ChangePasswordRequest) {
 loading.value = true
 error.value = null
 try {
 await authApi.adminChangePassword(data)
 mustChangePassword.value = false
 }
 catch (e) {
 error.value = e instanceof Error ? e.message: '修改密码失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 重置状态（用于测试或清理）
 */
 function $reset {
 user.value = null
 isAuthenticated.value = false
 isInitialized.value = false
 loading.value = false
 error.value = null
 mustChangePassword.value = false
 spaceMemberships.value =
 gravatarUrl.value = null
 }
 return {
 // State
 user,
 isAuthenticated,
 isInitialized,
 loading,
 error,
 mustChangePassword,
 spaceMemberships,
 gravatarUrl,
 // Getters
 isAdmin,
 displayName,
 // Actions
 login,
 logout,
 initAuth,
 fetchCurrentUser,
 fetchMe,
 updateDisplayName,
 changePassword,
 forceChangePassword,
 getAdminProfile,
 updateAdminProfile,
 adminChangePassword,
 $reset,
 }
})
