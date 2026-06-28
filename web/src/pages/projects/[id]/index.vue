<script setup lang="ts">
import type { Project, ProjectStatus } from '~/api/projects'
import { useQuery } from '@tanstack/vue-query'
import { useHead } from '@vueuse/head'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi } from '~/api/projects'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import ProjectWarRoom from '~/components/project/warroom/ProjectWarRoom.vue'
import ProjectWorkspaceHeader from '~/components/project/warroom/ProjectWorkspaceHeader.vue'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'

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

function goBack() {
  if (window.history.length > 1)
    router.back()
  else
    router.push('/projects')
}

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
</script>

<template>
  <!-- 全屏应用布局：高度由布局层 main(flex-1 min-h-0) 锁定，页面内部各自滚动 -->
  <div class="h-full flex flex-col min-h-0">
    <LoadingState v-if="isLoading" variant="skeleton" :count="4" class="p-6" />

    <div v-else-if="isError || !project" class="py-12 px-6">
      <EmptyState
        icon="lucide--help-circle"
        :title="t('projects.detail.notFound')"
        :description="t('projects.detail.notFoundDesc')"
        :action-label="t('projects.detail.backToList')"
        @action="router.push('/projects')"
      />
    </div>

    <div v-else class="flex flex-col h-full min-h-0">
      <!-- 顶部页头：返回 + 项目身份 + 状态动作 -->
      <ProjectWorkspaceHeader
        :project="project"
        :can-manage="canManage"
        @back="goBack"
        @transition="changeStatus"
      />

      <!-- 左中右工作台：会话列表 / AI 对话 / 项目资料 -->
      <div class="flex-1 min-h-0">
        <ProjectWarRoom :project="project" :can-manage="canManage" />
      </div>
    </div>
  </div>
</template>
