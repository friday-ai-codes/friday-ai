<script setup lang="ts">
import type { Project, ProjectStatus } from '~/api/projects'
import type { WorkbenchSection } from '~/components/project/workbench/WorkbenchShell.vue'
import { useQuery } from '@tanstack/vue-query'
import { useHead } from '@vueuse/head'
import { computed, defineAsyncComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi } from '~/api/projects'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import WorkbenchShell from '~/components/project/workbench/WorkbenchShell.vue'
import { Button } from '~/components/ui/button'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'

const OverviewSection = defineAsyncComponent(() => import('~/components/project/workbench/OverviewSection.vue'))
const DocsSection = defineAsyncComponent(() => import('~/components/project/workbench/DocsSection.vue'))
const FeatureListSection = defineAsyncComponent(() => import('~/components/project/workbench/FeatureListSection.vue'))
const DependenciesSection = defineAsyncComponent(() => import('~/components/project/workbench/DependenciesSection.vue'))

const route = useRoute('/projects/[id]/')
const router = useRouter()
const { t } = useI18n()
const { handleError } = useErrorHandler()
const { confirm } = useConfirmDialog()
const { success } = useToast()

const projectId = computed(() => route.params.id as string)

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['project', projectId],
  queryFn: () => projectsApi.get(projectId.value),
})
const project = computed<Project | undefined>(() => data.value)

const spaceId = computed(() => project.value?.space_id)
const { isSpaceAdmin } = usePermission(spaceId)
const canManage = computed(() => isSpaceAdmin.value)

useHead({
  title: () => (project.value ? `${project.value.name} - Friday AI` : t('projects.detail.title')),
})

const sections = computed<WorkbenchSection[]>(() => [
  { id: 'overview', label: t('projects.workbench.nav.overview'), icon: 'icon-[lucide--layout-dashboard]' },
  { id: 'docs', label: t('projects.workbench.nav.docs'), icon: 'icon-[lucide--files]' },
  { id: 'feature', label: t('projects.workbench.nav.feature'), icon: 'icon-[lucide--list-tree]' },
  { id: 'deps', label: t('projects.workbench.nav.deps'), icon: 'icon-[lucide--network]' },
])

const STATUS_FLOW: Record<ProjectStatus, ProjectStatus[]> = {
  developing: ['archived', 'terminated'],
  archived: ['developing', 'terminated'],
  terminated: [],
}
const nextStatuses = computed<ProjectStatus[]>(() =>
  project.value ? STATUS_FLOW[project.value.status] : [],
)

async function changeStatus(to: ProjectStatus) {
  if (!project.value)
    return
  const ok = await confirm({
    title: t('projects.status.changeTitle'),
    description: t('projects.status.changeConfirm', {
      to: t(`projects.status.${to}`),
    }),
    confirmText: t('projects.status.changeConfirmText'),
    variant: to === 'terminated' ? 'destructive' : 'default',
  })
  if (!ok)
    return
  try {
    await projectsApi.transition(project.value.id, to)
    success(t('projects.status.changed'))
    await refetch()
  }
  catch (e: unknown) {
    handleError(e, t('projects.status.changeFailed'))
  }
}

function statusBadgeClass(status: ProjectStatus): string {
  switch (status) {
    case 'developing':
      return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
    case 'archived':
      return 'bg-muted text-muted-foreground'
    case 'terminated':
      return 'bg-destructive/10 text-destructive'
    default:
      return 'bg-muted text-muted-foreground'
  }
}
</script>

<template>
  <div class="px-4 py-6 sm:px-6 lg:px-8 max-w-6xl mx-auto">
    <LoadingState v-if="isLoading" variant="skeleton" :count="4" />

    <div v-else-if="isError || !project" class="py-12">
      <EmptyState
        icon="lucide--help-circle"
        :title="t('projects.detail.notFound')"
        :description="t('projects.detail.notFoundDesc')"
        :action-label="t('projects.detail.backToList')"
        @action="router.push('/projects')"
      />
    </div>

    <div v-else class="space-y-6">
      <!-- 面包屑 -->
      <nav class="flex items-center gap-1.5 text-sm text-muted-foreground">
        <RouterLink to="/projects" class="hover:text-foreground transition-colors">
          {{ t('projects.title') }}
        </RouterLink>
        <span class="icon-[lucide--chevron-right] text-xs" />
        <span class="text-foreground font-medium truncate">{{ project.name }}</span>
      </nav>

      <!-- 头部 -->
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div class="space-y-1.5 min-w-0">
          <div class="flex items-center gap-3">
            <h1 class="text-2xl font-bold text-foreground truncate">
              {{ project.name }}
            </h1>
            <span
              class="px-2 py-0.5 rounded-full text-xs font-medium shrink-0"
              :class="statusBadgeClass(project.status)"
            >
              {{ t(`projects.status.${project.status}`) }}
            </span>
          </div>
          <p class="text-sm text-muted-foreground">
            <span class="icon-[lucide--folder-git-2] mr-1 align-middle" />
            {{ project.space_name }}
          </p>
        </div>

        <div class="flex items-center gap-2">
          <a
            v-if="project.feishu_board_url"
            :href="project.feishu_board_url"
            target="_blank"
            rel="noopener noreferrer"
          >
            <Button variant="outline" size="sm">
              <span class="icon-[lucide--external-link] mr-1.5" />
              {{ t('projects.detail.feishuBoard') }}
            </Button>
          </a>
          <template v-if="canManage">
            <Button
              v-for="to in nextStatuses"
              :key="to"
              size="sm"
              :variant="to === 'terminated' ? 'destructive' : 'outline'"
              :data-testid="`status-to-${to}`"
              @click="changeStatus(to)"
            >
              {{ t(`projects.status.action.${to}`) }}
            </Button>
          </template>
        </div>
      </div>

      <!-- 工作台：左导航 + 右主内容区（section 懒加载） -->
      <WorkbenchShell :sections="sections" :nav-label="t('projects.workbench.nav.sectionLabel')">
        <template #default="{ active }">
          <OverviewSection v-if="active === 'overview'" :project="project" :can-manage="canManage" />
          <DocsSection v-else-if="active === 'docs'" :project-id="project.id" />
          <FeatureListSection v-else-if="active === 'feature'" :project-id="project.id" />
          <DependenciesSection v-else-if="active === 'deps'" :project-id="project.id" />
        </template>
      </WorkbenchShell>
    </div>
  </div>
</template>
