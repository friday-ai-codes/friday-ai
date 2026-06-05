/**
 * 权限判断 composable
 * 基于 auth store 的用户角色信息提供响应式权限属性
 */
import type { Ref } from 'vue'
import { useAuthStore } from '~/stores/auth'

export function usePermission(spaceId?: Ref<string | undefined> | string) {
  const authStore = useAuthStore()

  // 系统管理员（is_superuser）
  const isSystemAdmin = computed(() => authStore.user?.is_superuser ?? false)

  // 当前用户在指定空间中的角色
  const spaceRole = computed(() => {
    const pid = typeof spaceId === 'string' ? spaceId : spaceId?.value
    if (!pid)
      return null
    return authStore.spaceMemberships.find(
      m => m.space_id === pid,
    )?.role ?? null
  })

  // 空间管理员（admin 角色或系统管理员）
  const isSpaceAdmin = computed(() =>
    isSystemAdmin.value || spaceRole.value === 'admin',
  )

  // 可编辑（admin 或 member）
  const canEdit = computed(() =>
    isSystemAdmin.value || ['admin', 'member'].includes(spaceRole.value ?? ''),
  )

  // 可执行（与 canEdit 相同）
  const canExecute = computed(() => canEdit.value)

  // 仅查看（viewer 角色）
  const isViewer = computed(() =>
    spaceRole.value === 'viewer' && !isSystemAdmin.value,
  )

  // 是否是空间成员（任意角色）
  const isSpaceMember = computed(() =>
    isSystemAdmin.value || spaceRole.value !== null,
  )

  return {
    isSystemAdmin,
    isSpaceAdmin,
    canEdit,
    canExecute,
    isViewer,
    isSpaceMember,
    spaceRole,
  }
}
