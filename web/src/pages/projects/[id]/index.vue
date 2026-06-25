<script setup lang="ts">
import type { Project, ProjectStatus } from '~/api/projects'
import { useQuery } from '@tanstack/vue-query'
import { useHead } from '@vueuse/head'
import { computed, defineAsyncComponent, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi } from '~/api/projects'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import { Button } from '~/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'

const OverviewTab = defineAsyncComponent(() => import('~/components/project/workbench/OverviewTab.vue'))
const MembersTab = defineAsyncComponent(() => import('~/components/project/workbench/MembersTab.vue'))
const WorkItemsTab = defineAsyncComponent(() => import('~/components/project/workbench/WorkItemsTab.vue'))
const ArtifactsTab = defineAsyncComponent(() => import('~/components/project/workbench/ArtifactsTab.vue'))
const MemoryTab = defineAsyncComponent(() => import('~/components/project/workbench/MemoryTab.vue'))
const LinksTab = defineAsyncComponent(() => import('~/components/project/workbench/LinksTab.vue'))

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

const activeTab = ref('overview')

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

      <!-- Tab 导航（懒加载） -->
      <Tabs v-model="activeTab">
        <TabsList class="flex-wrap">
          <TabsTrigger value="overview">
            <span class="icon-[lucide--layout-dashboard] mr-1.5" />
            {{ t('projects.tabs.overview') }}
          </TabsTrigger>
          <TabsTrigger value="members">
            <span class="icon-[lucide--users] mr-1.5" />
            {{ t('projects.tabs.members') }}
          </TabsTrigger>
          <TabsTrigger value="workItems">
            <span class="icon-[lucide--list-checks] mr-1.5" />
            {{ t('projects.tabs.workItems') }}
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            <span class="icon-[lucide--package] mr-1.5" />
            {{ t('projects.tabs.artifacts') }}
          </TabsTrigger>
          <TabsTrigger value="memory">
            <span class="icon-[lucide--brain] mr-1.5" />
            {{ t('projects.tabs.memory') }}
          </TabsTrigger>
          <TabsTrigger value="links">
            <span class="icon-[lucide--network] mr-1.5" />
            {{ t('projects.tabs.links') }}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" class="mt-5">
          <OverviewTab v-if="activeTab === 'overview'" :project="project" />
        </TabsContent>
        <TabsContent value="members" class="mt-5">
          <MembersTab v-if="activeTab === 'members'" :project-id="project.id" :can-manage="canManage" />
        </TabsContent>
        <TabsContent value="workItems" class="mt-5">
          <WorkItemsTab v-if="activeTab === 'workItems'" :project-id="project.id" :can-manage="canManage" />
        </TabsContent>
        <TabsContent value="artifacts" class="mt-5">
          <ArtifactsTab v-if="activeTab === 'artifacts'" :project-id="project.id" :can-manage="canManage" />
        </TabsContent>
        <TabsContent value="memory" class="mt-5">
          <MemoryTab v-if="activeTab === 'memory'" :project-id="project.id" />
        </TabsContent>
        <TabsContent value="links" class="mt-5">
          <LinksTab v-if="activeTab === 'links'" :project-id="project.id" />
        </TabsContent>
      </Tabs>
    </div>
  </div>
</template>
