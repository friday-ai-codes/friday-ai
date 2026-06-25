<script setup lang="ts">
import type { ProjectMember, ProjectRole } from '~/api/projects'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed, ref, toRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectsApi } from '~/api/projects'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'

const props = defineProps<{ projectId: string, canManage: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { confirm } = useConfirmDialog()
const { success } = useToast()
const queryClient = useQueryClient()

const projectIdRef = toRef(props, 'projectId')
const ASSIGNABLE_ROLES: ProjectRole[] = ['pm', 'frontend', 'backend', 'qa']

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project-members', projectIdRef],
  queryFn: () => projectsApi.listMembers(props.projectId),
})
const members = computed<ProjectMember[]>(() => data.value ?? [])
const owner = computed(() => members.value.find(m => m.role === 'owner'))

const busyUserId = ref<string>('')

function invalidate() {
  queryClient.invalidateQueries({ queryKey: ['project-members', projectIdRef] })
  queryClient.invalidateQueries({ queryKey: ['project', projectIdRef] })
}

async function changeRole(member: ProjectMember, role: ProjectRole) {
  if (member.role === role)
    return
  busyUserId.value = member.user.id
  try {
    await projectsApi.updateMemberRole(props.projectId, member.user.id, role)
    success(t('projects.members.roleChanged'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.members.roleChangeFailed'))
  }
  finally {
    busyUserId.value = ''
  }
}

async function transferOwner(member: ProjectMember) {
  const ok = await confirm({
    title: t('projects.members.transferTitle'),
    description: t('projects.members.transferConfirm', {
      name: member.user.display_name || member.user.username,
    }),
    confirmText: t('projects.members.transferConfirmText'),
  })
  if (!ok)
    return
  try {
    await projectsApi.transferOwner(props.projectId, member.user.id)
    success(t('projects.members.transferred'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.members.transferFailed'))
  }
}

async function removeMember(member: ProjectMember) {
  const ok = await confirm({
    title: t('projects.members.removeTitle'),
    description: t('projects.members.removeConfirm', {
      name: member.user.display_name || member.user.username,
    }),
    confirmText: t('projects.members.removeConfirmText'),
    variant: 'destructive',
  })
  if (!ok)
    return
  try {
    await projectsApi.removeMember(props.projectId, member.user.id)
    success(t('projects.members.removed'))
    invalidate()
  }
  catch (e: unknown) {
    handleError(e, t('projects.members.removeFailed'))
  }
}
</script>

<template>
  <div class="space-y-4">
    <div v-if="isLoading" class="text-sm text-muted-foreground py-8 text-center">
      {{ t('projects.loading') }}
    </div>
    <div v-else-if="isError" class="py-8 text-center space-y-2">
      <p class="text-sm text-destructive">
        {{ t('projects.members.loadError') }}
      </p>
      <button class="text-sm text-primary underline" @click="() => refetch()">
        {{ t('projects.retry') }}
      </button>
    </div>
    <div v-else-if="members.length === 0" class="text-sm text-muted-foreground py-8 text-center">
      {{ t('projects.members.empty') }}
    </div>

    <ul v-else class="divide-y divide-border/40 rounded-lg border border-border/40 bg-card">
      <li
        v-for="member in members"
        :key="member.id"
        class="flex items-center justify-between gap-3 px-4 py-3"
        data-testid="member-row"
      >
        <div class="min-w-0 flex items-center gap-3">
          <div class="size-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium text-primary shrink-0">
            {{ (member.user.display_name || member.user.username).slice(0, 1).toUpperCase() }}
          </div>
          <div class="min-w-0">
            <p class="text-sm font-medium text-foreground truncate">
              {{ member.user.display_name || member.user.username }}
            </p>
            <p class="text-xs text-muted-foreground truncate">
              @{{ member.user.username }}
            </p>
          </div>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <span
            v-if="member.role === 'owner'"
            class="px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/10 text-amber-600 dark:text-amber-400 inline-flex items-center gap-1"
          >
            <span class="icon-[lucide--crown]" />
            {{ t('projects.role.owner') }}
          </span>
          <template v-else>
            <Select
              v-if="canManage"
              :model-value="member.role"
              :disabled="busyUserId === member.user.id"
              @update:model-value="(v) => changeRole(member, v as ProjectRole)"
            >
              <SelectTrigger class="h-8 w-[120px] text-xs" :aria-label="t('projects.members.role')">
                <SelectValue>{{ t(`projects.role.${member.role}`) }}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="r in ASSIGNABLE_ROLES" :key="r" :value="r">
                  {{ t(`projects.role.${r}`) }}
                </SelectItem>
              </SelectContent>
            </Select>
            <span
              v-else
              class="px-2 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground"
            >
              {{ t(`projects.role.${member.role}`) }}
            </span>
          </template>

          <template v-if="canManage && member.role !== 'owner'">
            <button
              class="text-xs text-muted-foreground hover:text-primary transition-colors"
              :title="t('projects.members.transfer')"
              data-testid="transfer-owner-btn"
              @click="transferOwner(member)"
            >
              <span class="icon-[lucide--crown] text-base" />
            </button>
            <button
              class="text-xs text-muted-foreground hover:text-destructive transition-colors"
              :title="t('projects.members.remove')"
              @click="removeMember(member)"
            >
              <span class="icon-[lucide--user-minus] text-base" />
            </button>
          </template>
        </div>
      </li>
    </ul>

    <p v-if="!owner && members.length > 0" class="text-xs text-amber-600 dark:text-amber-400">
      {{ t('projects.members.noOwnerWarning') }}
    </p>
  </div>
</template>
