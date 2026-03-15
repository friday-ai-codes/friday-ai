/**
 * 权限判断 composable
 * 基于 auth store 的用户角色信息提供响应式权限属性
 */
import type { Ref } from 'vue'
import { useAuthStore } from '~/stores/auth'
export function usePermission(projectId?: Ref<string | undefined> | string) {
 const authStore = useAuthStore
 // 系统管理员（is_superuser）
 const isSystemAdmin = computed( => authStore.user?.is_superuser ?? false)
 // 当前用户在指定项目中的角色
 const projectRole = computed( => {
 const pid = typeof projectId === 'string' ? projectId: projectId?.value
 if (!pid) return null
 return authStore.projectMemberships.find(
 m => m.project_id === pid,
 )?.role ?? null
 })
 // 项目管理员（admin 角色或系统管理员）
 const isProjectAdmin = computed( =>
 isSystemAdmin.value || projectRole.value === 'admin',
 )
 // 可编辑（admin 或 member）
 const canEdit = computed( =>
 isSystemAdmin.value || ['admin', 'member'].includes(projectRole.value ?? ''),
 )
 // 可执行（与 canEdit 相同）
 const canExecute = computed( => canEdit.value)
 // 仅查看（viewer 角色）
 const isViewer = computed( =>
 projectRole.value === 'viewer' && !isSystemAdmin.value,
 )
 // 是否是项目成员（任意角色）
 const isProjectMember = computed( =>
 isSystemAdmin.value || projectRole.value !== null,
 )
 return {
 isSystemAdmin,
 isProjectAdmin,
 canEdit,
 canExecute,
 isViewer,
 isProjectMember,
 projectRole,
 }
}
