<script setup lang="ts">
/**
 * UserPermissionsModal — 用户权限编辑弹窗
 *
 * 在一个弹窗里集中管理某个用户的：
 *   - 全局权限：超级管理员开关（带「不能取消自己 / 必须保留最后一个超管」防护）
 *   - 空间权限：所属空间及角色（可加入多个空间、内联改角色、移除）
 */
import type { AdminUserMembership, Space, SystemUser } from '~/types'
import { computed, ref, watch } from 'vue'
import { addSpaceMember, removeSpaceMember, updateSpaceMember } from '~/api/members'
import { listSpaces } from '~/api/spaces'
import { getUserMemberships, updateUser } from '~/api/users'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { Switch } from '~/components/ui/switch'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

type SpaceRole = 'admin' | 'member' | 'viewer'

const props = defineProps<{
  user: SystemUser
  /** 当前登录用户 id，用于「不能取消自己」防护 */
  currentUserId?: string
  /** 系统当前超管数量，用于「必须保留最后一个超管」防护 */
  superuserCount: number
}>()

const emit = defineEmits<{
  /** 超管身份变更后回传最新用户对象，供父级更新列表 */
  (e: 'updated', user: SystemUser): void
}>()

const open = defineModel<boolean>('open', { default: false })

// confirmOpen：确认框是否正在显示。两个弹窗叠加时，点击确认框按钮对本弹窗而言是
// 「外部交互」，会被 reka-ui 误判为关闭本弹窗，故确认框打开期间屏蔽本弹窗的外部关闭。
const { confirm, isOpen: confirmOpen } = useConfirmDialog()
const { handleError } = useErrorHandler()
const { success } = useToast()

const isSuperuser = ref(props.user.is_superuser)
const memberships = ref<AdminUserMembership[]>([])
const allSpaces = ref<Space[]>([])
const loading = ref(false)
const saving = ref(false)

// 添加到空间
const showAddForm = ref(false)
const selectedSpaceId = ref('')
const selectedRole = ref<SpaceRole>('member')

const roleLabels: Record<SpaceRole, string> = {
  admin: '管理员',
  member: '成员',
  viewer: '观察者',
}

const isSelf = computed(() => props.user.id === props.currentUserId)
const isLastSuperuser = computed(() => props.user.is_superuser && props.superuserCount <= 1)
// 取消超管被禁止的场景：取消自己 / 系统仅剩一个超管
const blockRevoke = computed(() => isSuperuser.value && (isSelf.value || isLastSuperuser.value))

// 尚未加入的空间（用于「添加到空间」下拉）
const availableSpaces = computed(() => {
  const joined = new Set(memberships.value.map(m => m.space_id))
  return allSpaces.value.filter(s => !joined.has(s.id))
})

async function loadData() {
  loading.value = true
  try {
    const [m, s] = await Promise.all([
      getUserMemberships(props.user.id),
      listSpaces(),
    ])
    memberships.value = m
    allSpaces.value = s
  }
  catch (e: unknown) {
    handleError(e, '加载用户权限')
  }
  finally {
    loading.value = false
  }
}

watch(open, (isOpen) => {
  if (isOpen) {
    isSuperuser.value = props.user.is_superuser
    showAddForm.value = false
    selectedSpaceId.value = ''
    selectedRole.value = 'member'
    loadData()
  }
}, { immediate: true })

async function handleSuperuserToggle(next: boolean) {
  // 取消超管的防护：撞到限制时不发请求，给出提示
  if (!next && (isSelf.value || isLastSuperuser.value)) {
    handleError(
      new Error(isSelf.value ? '不能取消自己的超级管理员身份' : '系统必须保留至少一个超级管理员'),
      '变更超级管理员身份',
    )
    return
  }

  const name = props.user.display_name || props.user.username
  const ok = await confirm({
    title: next ? '授予超级管理员' : '取消超级管理员',
    description: next
      ? `确定将「${name}」设为超级管理员吗？该用户将获得整个系统的最高权限。`
      : `确定取消「${name}」的超级管理员身份吗？`,
    confirmText: next ? '授予' : '取消超管',
    variant: next ? 'default' : 'destructive',
  })
  if (!ok)
    return

  saving.value = true
  try {
    const updated = await updateUser(props.user.id, { is_superuser: next })
    isSuperuser.value = updated.is_superuser
    emit('updated', updated)
    success(updated.is_superuser ? '已设为超级管理员' : '已取消超级管理员')
  }
  catch (e: unknown) {
    handleError(e, '变更超级管理员身份')
  }
  finally {
    saving.value = false
  }
}

async function handleAddToSpace() {
  if (!selectedSpaceId.value)
    return
  saving.value = true
  try {
    await addSpaceMember(selectedSpaceId.value, {
      user_id: props.user.id,
      role: selectedRole.value,
    })
    // 复用按用户聚合的查询刷新列表（拿到 membership id 与空间名）
    memberships.value = await getUserMemberships(props.user.id)
    showAddForm.value = false
    selectedSpaceId.value = ''
    selectedRole.value = 'member'
    success('已加入空间')
  }
  catch (e: unknown) {
    handleError(e, '加入空间')
  }
  finally {
    saving.value = false
  }
}

async function handleRoleChange(m: AdminUserMembership, newRole: SpaceRole) {
  if (newRole === m.role)
    return
  saving.value = true
  try {
    await updateSpaceMember(m.space_id, props.user.id, { role: newRole })
    const idx = memberships.value.findIndex(x => x.id === m.id)
    if (idx !== -1)
      memberships.value[idx] = { ...m, role: newRole }
    success('角色已更新')
  }
  catch (e: unknown) {
    handleError(e, '更新角色')
  }
  finally {
    saving.value = false
  }
}

async function handleRemoveFromSpace(m: AdminUserMembership) {
  const ok = await confirm({
    title: '移出空间',
    description: `确定将该用户从「${m.space_name}」移除吗？`,
    confirmText: '移除',
    variant: 'destructive',
  })
  if (!ok)
    return
  saving.value = true
  try {
    await removeSpaceMember(m.space_id, props.user.id)
    memberships.value = memberships.value.filter(x => x.id !== m.id)
    success('已移出空间')
  }
  catch (e: unknown) {
    handleError(e, '移出空间')
  }
  finally {
    saving.value = false
  }
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent
      class="sm:max-w-2xl max-h-[85vh] overflow-y-auto"
      @interact-outside="(e) => { if (confirmOpen) e.preventDefault() }"
      @escape-key-down="(e) => { if (confirmOpen) e.preventDefault() }"
    >
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <span class="icon-[lucide--shield-check] text-primary" />
          编辑权限
        </DialogTitle>
        <DialogDescription>
          管理「{{ user.display_name || user.username }}」的全局与空间权限
        </DialogDescription>
      </DialogHeader>

      <div v-if="loading" class="flex items-center justify-center py-10">
        <span class="icon-[lucide--loader-2] animate-spin text-2xl text-muted-foreground" />
      </div>

      <div v-else class="space-y-6">
        <!-- 全局权限 -->
        <section class="rounded-2xl border border-border/50 bg-card/60 p-4">
          <div class="flex items-center justify-between gap-4">
            <div class="space-y-0.5">
              <p class="font-medium text-sm flex items-center gap-2">
                <span class="icon-[lucide--crown] text-primary" />
                超级管理员
              </p>
              <p class="text-xs text-muted-foreground">
                拥有整个系统的最高权限，可管理所有空间、用户与系统设置
              </p>
            </div>
            <Switch
              :model-value="isSuperuser"
              :disabled="saving || blockRevoke"
              aria-label="超级管理员"
              @update:model-value="(v: boolean) => handleSuperuserToggle(v)"
            />
          </div>
          <p v-if="blockRevoke" class="mt-2 text-xs text-muted-foreground">
            <span class="icon-[lucide--info] align-[-2px]" />
            {{ isSelf ? '不能取消自己的超级管理员身份' : '系统必须保留至少一个超级管理员' }}
          </p>
        </section>

        <!-- 空间权限 -->
        <section class="rounded-2xl border border-border/50 bg-card/60 p-4 space-y-4">
          <div class="flex items-center justify-between gap-4">
            <div class="space-y-0.5">
              <p class="font-medium text-sm flex items-center gap-2">
                <span class="icon-[lucide--layout-grid] text-primary" />
                空间权限
              </p>
              <p class="text-xs text-muted-foreground">
                {{ isSuperuser ? '超级管理员已可访问所有空间，此处为额外的显式成员关系' : `已加入 ${memberships.length} 个空间` }}
              </p>
            </div>
            <Button
              v-if="!showAddForm && availableSpaces.length > 0"
              size="sm"
              variant="outline"
              class="shrink-0 gap-1.5"
              @click="showAddForm = true"
            >
              <span class="icon-[lucide--plus] text-sm" />
              加入空间
            </Button>
          </div>

          <!-- 加入空间表单 -->
          <div
            v-if="showAddForm"
            class="rounded-xl border border-primary/30 bg-background/50 p-3 space-y-3"
          >
            <div class="flex gap-2">
              <Select v-model="selectedSpaceId" class="flex-1">
                <SelectTrigger class="bg-background/50">
                  <SelectValue placeholder="选择空间" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem v-for="s in availableSpaces" :key="s.id" :value="s.id">
                    {{ s.name }}
                  </SelectItem>
                </SelectContent>
              </Select>
              <Select v-model="selectedRole">
                <SelectTrigger class="w-28 bg-background/50">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="admin">
                    管理员
                  </SelectItem>
                  <SelectItem value="member">
                    成员
                  </SelectItem>
                  <SelectItem value="viewer">
                    观察者
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div class="flex gap-2">
              <Button size="sm" :disabled="saving || !selectedSpaceId" @click="handleAddToSpace">
                确认加入
              </Button>
              <Button size="sm" variant="outline" @click="showAddForm = false">
                取消
              </Button>
            </div>
          </div>

          <!-- 空间列表 -->
          <div v-if="memberships.length === 0" class="py-6 text-center text-sm text-muted-foreground">
            尚未加入任何空间
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="m in memberships"
              :key="m.id"
              class="flex items-center justify-between gap-3 rounded-xl border border-border/30 bg-background/50 p-3"
            >
              <div class="min-w-0">
                <p class="font-medium text-sm truncate">
                  {{ m.space_name }}
                </p>
              </div>
              <div class="flex items-center gap-2 shrink-0">
                <Select
                  :model-value="m.role"
                  :disabled="saving"
                  @update:model-value="(v) => handleRoleChange(m, v as SpaceRole)"
                >
                  <SelectTrigger class="w-28 h-8 text-xs bg-background/50">
                    <SelectValue>{{ roleLabels[m.role] }}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">
                      管理员
                    </SelectItem>
                    <SelectItem value="member">
                      成员
                    </SelectItem>
                    <SelectItem value="viewer">
                      观察者
                    </SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  variant="ghost"
                  size="sm"
                  :disabled="saving"
                  class="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                  aria-label="移出空间"
                  @click="handleRemoveFromSpace(m)"
                >
                  <span class="icon-[lucide--user-minus] text-sm" />
                </Button>
              </div>
            </div>
          </div>
        </section>
      </div>
    </DialogContent>
  </Dialog>
</template>
