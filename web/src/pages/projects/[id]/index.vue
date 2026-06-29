<script setup lang="ts">
import type { Project } from '~/api/projects'
import { useQuery } from '@tanstack/vue-query'
import { useHead } from '@vueuse/head'
import { computed, markRaw } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { projectsApi } from '~/api/projects'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import ProjectSettingsModal from '~/components/project/ProjectSettingsModal.vue'
import ProjectWarRoom from '~/components/project/warroom/ProjectWarRoom.vue'
import ProjectWorkspaceHeader from '~/components/project/warroom/ProjectWorkspaceHeader.vue'
import { useModal } from '~/composables/useModal'
import { usePermission } from '~/composables/usePermission'

const route = useRoute('/projects/[id]/')
const router = useRouter()
const { t } = useI18n()

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

// #8：打开项目配置弹窗（改名/换空间/状态流转），确认后刷新项目详情。
function openSettings() {
  if (!project.value)
    return
  const { open } = useModal({
    component: markRaw(ProjectSettingsModal),
    attrs: { project: project.value },
    onConfirm: () => {
      refetch()
    },
  })
  void open()
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
        @settings="openSettings"
      />

      <!-- 左中右工作台：会话列表 / AI 对话 / 项目资料 -->
      <div class="flex-1 min-h-0">
        <ProjectWarRoom :project="project" :can-manage="canManage" />
      </div>
    </div>
  </div>
</template>
