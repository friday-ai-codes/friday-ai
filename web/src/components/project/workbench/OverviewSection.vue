<script setup lang="ts">
import type { Project, ProjectMember, ProjectRole, ProjectStatus } from '~/api/projects'
import type { ProjectDoc } from '~/api/projectWorkspace'
import { useMutation, useQuery, useQueryClient } from '@tanstack/vue-query'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { projectsApi } from '~/api/projects'
import { projectWorkspaceApi } from '~/api/projectWorkspace'
import OverviewTab from '~/components/project/workbench/OverviewTab.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const props = defineProps<{ project: Project, canManage?: boolean }>()

const { t } = useI18n()
const { handleError } = useErrorHandler()
const { success } = useToast()
const queryClient = useQueryClient()

const projectId = computed(() => props.project.id)

// ── 人员（带身份）────────────────────────────────────────────
const {
  data: membersData,
  isLoading: membersLoading,
  isError: membersError,
  refetch: refetchMembers,
} = useQuery({
  queryKey: ['project-members', projectId],
  queryFn: () => projectsApi.listMembers(props.project.id),
})
const members = computed<ProjectMember[]>(() => membersData.value ?? [])

/** 后端 ProjectRole → 前端身份键（PM/开发负责人/开发者/测试）。 */
function identityKey(role: ProjectRole): 'pm' | 'owner' | 'developer' | 'qa' {
  if (role === 'pm')
    return 'pm'
  if (role === 'owner')
    return 'owner'
  if (role === 'qa')
    return 'qa'
  return 'developer'
}

// ── 状态栏（项目状态 + 工作区 docs 同步概要 + 重建）──────────────
const {
  data: docsData,
  isError: docsError,
  refetch: refetchDocs,
} = useQuery({
  queryKey: ['project-docs', projectId],
  queryFn: () => projectWorkspaceApi.listDocs(props.project.id),
  // 任一文件 syncing 时持续轮询同步状态（仿 ReconcilePanel 派发→轮询）。
  refetchInterval: query =>
    (query.state.data?.some((d: ProjectDoc) => d.sync_status === 'syncing') ? 2000 : false),
})
const docs = computed<ProjectDoc[]>(() => docsData.value ?? [])
const docsReady = computed(() => docs.value.length > 0)
const anySyncing = computed(() => docs.value.some(d => d.sync_status === 'syncing'))
const anyError = computed(() => docs.value.some(d => d.sync_status === 'error'))

const syncSummary = computed(() => {
  if (anySyncing.value)
    return t('projects.workbench.overview.syncing')
  if (anyError.value)
    return t('projects.workbench.overview.syncError')
  if (docsReady.value)
    return t('projects.workbench.overview.synced')
  return t('projects.workbench.overview.syncIdle')
})

const rebuildMutation = useMutation({
  mutationFn: () => projectWorkspaceApi.rebuildWorkspace(props.project.id),
  onSuccess: () => {
    success(t('projects.workbench.rebuild'), t('projects.workbench.rebuilt'))
    queryClient.invalidateQueries({ queryKey: ['project-docs', projectId] })
    refetchDocs()
  },
  onError: (e: unknown) => handleError(e, t('projects.workbench.rebuildFailed')),
})
const isRebuilding = computed(() => rebuildMutation.isPending.value)

function statusBadgeVariant(status: ProjectStatus): 'success' | 'muted' | 'destructive' {
  switch (status) {
    case 'developing':
      return 'success'
    case 'terminated':
      return 'destructive'
    default:
      return 'muted'
  }
}
</script>

<template>
  <div class="space-y-6" data-testid="workbench-overview-section">
    <!-- 状态栏 -->
    <section class="card" data-testid="overview-status-bar">
      <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
        <span class="icon-[lucide--activity] text-primary" />
        <h2 class="text-sm font-semibold text-foreground">
          {{ t('projects.workbench.overview.statusTitle') }}
        </h2>
      </header>
      <div class="p-5 flex flex-wrap items-center gap-3">
        <Badge :variant="statusBadgeVariant(project.status)">
          {{ t(`projects.status.${project.status}`) }}
        </Badge>
        <span class="text-sm text-muted-foreground inline-flex items-center gap-1.5">
          <span
            class="size-2 rounded-full"
            :class="anySyncing ? 'bg-amber-500 animate-pulse' : anyError ? 'bg-destructive' : docsReady ? 'bg-emerald-500' : 'bg-muted-foreground/40'"
          />
          {{ syncSummary }}
        </span>
        <span class="text-xs text-muted-foreground">
          {{ t('projects.workbench.overview.docCount', { n: docs.length }) }}
        </span>
        <div v-if="docsError" class="text-xs text-destructive inline-flex items-center gap-2">
          {{ t('projects.workbench.overview.docsLoadError') }}
          <button class="text-primary underline" @click="() => refetchDocs()">
            {{ t('projects.retry') }}
          </button>
        </div>
        <Button
          size="sm"
          variant="outline"
          class="ml-auto"
          :disabled="isRebuilding"
          data-testid="rebuild-workspace-btn"
          @click="() => rebuildMutation.mutate()"
        >
          <span class="icon-[lucide--refresh-cw] mr-1.5" :class="isRebuilding ? 'animate-spin' : ''" />
          {{ isRebuilding ? t('projects.workbench.rebuilding') : t('projects.workbench.rebuild') }}
        </Button>
      </div>
    </section>

    <!-- 工作区未就绪空态 -->
    <section v-if="!docsReady && !docsError" class="card p-5" data-testid="overview-empty">
      <div class="flex flex-col items-center justify-center py-8 text-center gap-1.5">
        <span class="icon-[lucide--folder-clock] text-2xl text-muted-foreground/50" />
        <p class="text-sm font-medium text-foreground">
          {{ t('projects.workbench.overview.emptyTitle') }}
        </p>
        <p class="text-xs text-muted-foreground max-w-sm">
          {{ t('projects.workbench.overview.emptyDesc') }}
        </p>
      </div>
    </section>

    <!-- 概览（复用 OverviewTab） -->
    <OverviewTab :project="project" />

    <!-- 人员（带身份） -->
    <section class="card" data-testid="overview-people">
      <header class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
        <span class="icon-[lucide--users] text-primary" />
        <h2 class="text-sm font-semibold text-foreground">
          {{ t('projects.workbench.overview.peopleTitle') }}
        </h2>
      </header>
      <div class="p-5">
        <div v-if="membersLoading" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.loading') }}
        </div>
        <div v-else-if="membersError" class="py-4 text-center space-y-2">
          <p class="text-sm text-destructive">
            {{ t('projects.workbench.overview.peopleLoadError') }}
          </p>
          <button class="text-sm text-primary underline" @click="() => refetchMembers()">
            {{ t('projects.retry') }}
          </button>
        </div>
        <div v-else-if="members.length === 0" class="text-sm text-muted-foreground py-4 text-center">
          {{ t('projects.workbench.overview.peopleEmpty') }}
        </div>
        <ul v-else class="space-y-2">
          <li
            v-for="member in members"
            :key="member.id"
            class="flex items-center justify-between gap-3"
            data-testid="overview-member-row"
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
            <Badge variant="secondary" class="shrink-0">
              <span v-if="identityKey(member.role) === 'owner'" class="icon-[lucide--crown]" />
              {{ t(`projects.workbench.overview.identity.${identityKey(member.role)}`) }}
            </Badge>
          </li>
        </ul>
      </div>
    </section>
  </div>
</template>
