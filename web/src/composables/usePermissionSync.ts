/**
 * 权限变更实时同步 composable
 * 定期轮询 /api/auth/me/ 检测权限变更，通过 toast 通知用户
 */
import type { SpaceMembershipBrief } from '~/types'
import { usePolling } from '~/composables/usePolling'
import { useAuthStore } from '~/stores/auth'
/** 角色等级映射，用于判断权限升降 */
const ROLE_LEVELS: Record<string, number> = {
 viewer: 1,
 member: 2,
 admin: 3,
}
function roleLevel(role: string): number {
 return ROLE_LEVELS[role] ?? 0
}
export function usePermissionSync {
 const authStore = useAuthStore
 const router = useRouter
 const { warning, info } = useToast
 /**
 * 检测权限变化并通知用户
 * - 被移除出空间：toast 警告 + 跳转首页
 * - 角色降低：toast 提示
 * - 角色提升：静默更新，不打断用户
 */
 function detectPermissionChanges(
 oldMemberships: SpaceMembershipBrief,
 newMemberships: SpaceMembershipBrief,
 ) {
 // 无旧数据时不做对比（首次加载）
 if (oldMemberships.length === 0)
 return
 for (const oldM of oldMemberships) {
 const newM = newMemberships.find(m => m.space_id === oldM.space_id)
 if (!newM) {
 // 被移除出空间
 warning('您已被移除出空间，正在返回首页')
 router.push('/')
 return
 }
 if (roleLevel(newM.role) < roleLevel(oldM.role)) {
 // 角色降低
 info('您的空间权限已变更')
 }
 // 角色提升时静默更新，不提示
 }
 }
 const { start, stop } = usePolling(async => {
 if (!authStore.isAuthenticated)
 return
 // 保存旧权限快照（深拷贝）
 const oldMemberships = authStore.spaceMemberships.map(m => ({ ...m }))
 // 调用 fetchMe 获取最新权限
 await authStore.fetchMe
 // 对比权限变化
 detectPermissionChanges(oldMemberships, authStore.spaceMemberships)
 }, { interval: 60_000, immediate: false })
 // 仅在认证时启动轮询
 watch( => authStore.isAuthenticated, (authenticated) => {
 if (authenticated) {
 start
 }
 else {
 stop
 }
 }, { immediate: true })
 return { start, stop }
}
