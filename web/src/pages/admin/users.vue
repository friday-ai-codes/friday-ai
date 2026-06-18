<script setup lang="ts">
import type { ColumnDef } from '@tanstack/vue-table'
import type { Invitation, SystemUser, UserSource } from '~/types'
import { h } from 'vue'
import { createInvitation, listUsers, updateUser } from '~/api/users'
import UserPermissionsModal from '~/components/admin/UserPermissionsModal.vue'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useTableUrlState } from '~/composables/useTableUrlState'
import { useToast } from '~/composables/useToast'
import { useAuthStore } from '~/stores/auth'

definePage({
  meta: { requiresAdmin: true },
})

const { handleError } = useErrorHandler()
const { success } = useToast()
const auth = useAuthStore()

// 搜索/排序/分页/每页大小持久化到 URL（刷新可恢复）
const { pagination, sorting, globalFilter } = useTableUrlState()

const users = ref<SystemUser[]>([])
const loading = ref(true)
const saving = ref(false)

// 权限编辑弹窗
const editingUser = ref<SystemUser | null>(null)
const permissionsOpen = ref(false)

// 当前登录用户 id 与系统超管数量：用于「不能取消自己」「保留最后一个超管」的前端防护
const currentUserId = computed(() => auth.user?.id)
const superuserCount = computed(() => users.value.filter(u => u.is_superuser).length)

function openPermissions(user: SystemUser) {
  editingUser.value = user
  permissionsOpen.value = true
}

function onUserUpdated(updated: SystemUser) {
  // 整体重建数组引用，确保 DataTable 立即重算（角色徽章、超管计数实时刷新）
  users.value = users.value.map(u => (u.id === updated.id ? updated : u))
  // 同步弹窗持有的用户对象，避免重开时仍显示旧状态
  if (editingUser.value?.id === updated.id)
    editingUser.value = updated
}

// 邀请创建
const inviteEmail = ref('')
const creatingInvite = ref(false)
const newInvitation = ref<Invitation | null>(null)
const inviteLink = ref('')

async function loadUsers() {
  loading.value = true
  try {
    users.value = await listUsers()
  }
  catch (e: unknown) {
    handleError(e, '加载用户')
  }
  finally {
    loading.value = false
  }
}

async function toggleUserActive(user: SystemUser) {
  saving.value = true
  try {
    const updated = await updateUser(user.id, { is_active: !user.is_active })
    const idx = users.value.findIndex(u => u.id === user.id)
    if (idx !== -1)
      users.value[idx] = updated
    success(updated.is_active ? '用户已启用' : '用户已禁用')
  }
  catch (e: unknown) {
    handleError(e, '切换用户状态')
  }
  finally {
    saving.value = false
  }
}

async function generateInviteLink() {
  creatingInvite.value = true
  newInvitation.value = null
  inviteLink.value = ''
  try {
    const invitation = await createInvitation(inviteEmail.value.trim() || undefined)
    newInvitation.value = invitation
    const baseUrl = window.location.origin
    inviteLink.value = `${baseUrl}/invite/${invitation.token}`
    inviteEmail.value = ''
    success('邀请链接已生成')
  }
  catch (e: unknown) {
    handleError(e, '生成邀请链接')
  }
  finally {
    creatingInvite.value = false
  }
}

async function copyInviteLink() {
  if (!inviteLink.value)
    return
  try {
    await navigator.clipboard.writeText(inviteLink.value)
    success('链接已复制到剪贴板')
  }
  catch (e: unknown) {
    handleError(e, '复制链接')
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

// 用户来源 → 中文标签 + 图标 + 强调色
const SOURCE_META: Record<UserSource, { label: string, icon: string, tone: string }> = {
  feishu: { label: '飞书', icon: 'icon-[lucide--message-circle]', tone: 'text-sky-600 bg-sky-500/10 border-sky-500/20' },
  google: { label: 'Google', icon: 'icon-[lucide--chrome]', tone: 'text-amber-600 bg-amber-500/10 border-amber-500/20' },
  github: { label: 'GitHub', icon: 'icon-[lucide--github]', tone: 'text-foreground bg-muted border-border/60' },
  oidc_other: { label: 'SSO', icon: 'icon-[lucide--shield-check]', tone: 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20' },
  invitation: { label: '邀请', icon: 'icon-[lucide--mail]', tone: 'text-violet-600 bg-violet-500/10 border-violet-500/20' },
  admin: { label: '管理员', icon: 'icon-[lucide--user-cog]', tone: 'text-primary bg-primary/10 border-primary/20' },
  system: { label: '系统', icon: 'icon-[lucide--settings]', tone: 'text-muted-foreground bg-muted border-border/60' },
}

function getSourceMeta(source: UserSource | undefined) {
  return SOURCE_META[source ?? 'admin'] ?? SOURCE_META.admin
}

onMounted(() => {
  loadUsers()
})

// --- DataTable 列定义 ---
const columns: ColumnDef<SystemUser>[] = [
  {
    accessorKey: 'username',
    header: '用户',
    cell: ({ row }) => {
      const user = row.original
      const displayName = user.display_name || user.username
      const initial = displayName.charAt(0).toUpperCase()
      return h('div', { class: 'flex items-center gap-3' }, [
        h('div', {
          class: 'w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center text-sm font-medium shrink-0',
        }, initial),
        h('div', { class: 'min-w-0' }, [
          h('span', { class: 'font-medium text-sm text-foreground block' }, displayName),
          h('span', { class: 'text-xs text-muted-foreground' }, `@${user.username}`),
        ]),
      ])
    },
    enableSorting: true,
  },
  {
    id: 'role',
    header: '角色',
    cell: ({ row }) => row.original.is_superuser
      ? h(Badge, { variant: 'outline', class: 'text-xs' }, () => '超级管理员')
      : h('span', { class: 'text-sm text-muted-foreground' }, '普通用户'),
    enableSorting: false,
  },
  {
    id: 'source',
    header: '来源',
    cell: ({ row }) => {
      const meta = getSourceMeta(row.original.source)
      return h('span', {
        class: `inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium border ${meta.tone}`,
      }, [
        h('span', { class: `${meta.icon} text-[0.85rem]` }),
        meta.label,
      ])
    },
    enableSorting: false,
  },
  {
    id: 'status',
    header: '状态',
    cell: ({ row }) => h(Badge, {
      variant: row.original.is_active ? 'default' : 'destructive',
      class: 'text-xs',
    }, () => row.original.is_active ? '启用' : '禁用'),
    enableSorting: false,
  },
  {
    accessorKey: 'created_at',
    header: '注册时间',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, formatDate(row.original.created_at)),
    enableSorting: true,
  },
  {
    id: 'actions',
    header: '操作',
    cell: ({ row }) => {
      const user = row.original
      const btns = []

      // 启用/禁用：仅普通用户可切换（超管不提供禁用入口，与原行为一致）
      if (!user.is_superuser) {
        btns.push(h(Button, {
          variant: 'secondary',
          size: 'sm',
          disabled: saving.value,
          onClick: (e: Event) => {
            e.stopPropagation()
            toggleUserActive(user)
          },
        }, () => user.is_active ? '禁用' : '启用'))
      }

      // 编辑权限：在弹窗里统一管理超管开关 + 各空间角色
      btns.push(h(Button, {
        variant: 'outline',
        size: 'sm',
        onClick: (e: Event) => {
          e.stopPropagation()
          openPermissions(user)
        },
      }, () => '编辑权限'))

      return h('div', { class: 'flex items-center justify-end gap-2' }, btns)
    },
    enableSorting: false,
    enableHiding: false,
  },
]
</script>

<template>
  <PageContainer show-background>
    <!-- 页头 -->
    <PageHeader
      icon="lucide--users"
      icon-gradient="from-primary/20 to-secondary/10"
      icon-color="text-primary"
      title="用户管理"
      description="管理系统用户、邀请新成员、设置用户权限"
    />

    <!-- 邀请新用户 -->
    <div class="group relative">
      <div class="card overflow-hidden">
        <div class="flex items-center gap-3 p-6 border-b border-border/50">
          <div class="p-2.5 rounded-xl bg-primary/10 flex items-center justify-center">
            <span class="icon-[lucide--user-plus] text-2xl text-primary" />
          </div>
          <div>
            <h2 class="text-lg font-semibold">
              邀请新用户
            </h2>
            <p class="text-sm text-muted-foreground">
              生成邀请链接，有效期 7 天
            </p>
          </div>
        </div>

        <div class="p-6 space-y-4">
          <div class="flex gap-3">
            <div class="flex-1">
              <Label for="invite-email" class="text-xs text-muted-foreground mb-1.5 block">
                预填邮箱（可选）
              </Label>
              <Input
                id="invite-email"
                v-model="inviteEmail"
                type="email"
                placeholder="user@example.com"
                class="bg-background/50"
              />
            </div>
            <div class="flex items-end">
              <Button
                :disabled="creatingInvite"
                @click="generateInviteLink"
              >
                <span v-if="creatingInvite" class="icon-[lucide--loader-2] animate-spin" />
                <span v-else class="icon-[lucide--link]" />
                生成链接
              </Button>
            </div>
          </div>

          <!-- 生成的邀请链接 -->
          <div
            v-if="inviteLink"
            class="p-4 rounded-xl bg-primary/5 border border-primary/20 space-y-2"
          >
            <div class="flex items-center justify-between gap-2">
              <p class="text-xs text-muted-foreground">
                邀请链接（有效期至 {{ newInvitation ? formatDate(newInvitation.expires_at) : '' }}）
              </p>
              <Button
                variant="ghost"
                size="sm"
                @click="copyInviteLink"
              >
                <span class="icon-[lucide--copy]" />
                复制
              </Button>
            </div>
            <p class="text-sm font-mono break-all text-foreground/70 bg-background/50 rounded-lg p-2">
              {{ inviteLink }}
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- 用户列表 DataTable -->
    <DataTable
      v-model:pagination="pagination"
      v-model:sorting="sorting"
      v-model:global-filter="globalFilter"
      :data="users"
      :columns="columns"
      table-id="admin-users-list"
      :loading="loading"
      search-placeholder="搜索用户名、显示名…"
    />

    <!-- 权限编辑弹窗 -->
    <UserPermissionsModal
      v-if="editingUser"
      v-model:open="permissionsOpen"
      :user="editingUser"
      :current-user-id="currentUserId"
      :superuser-count="superuserCount"
      @updated="onUserUpdated"
    />
  </PageContainer>
</template>
