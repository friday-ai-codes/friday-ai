<script setup lang="ts">
import type { Project, ProjectListFilters, ProjectStatus } from '~/api/projects'
import type { Space } from '~/types'
import { useQuery } from '@tanstack/vue-query'
import { useHead } from '@vueuse/head'
import { computed, markRaw, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { projectsApi } from '~/api/projects'
import spacesApi from '~/api/spaces'
import EmptyState from '~/components/common/EmptyState.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateProjectModal from '~/components/project/CreateProjectModal.vue'
import ProjectSearchPanel from '~/components/project/ProjectSearchPanel.vue'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { refDebounced, useLocalStorage } from '@vueuse/core'
import { useAuthStore } from '~/stores/auth'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

useHead({ title: () => `${t('projects.title')} - Friday AI` })

const ALL = '__all__'
const STATUSES: ProjectStatus[] = ['developing', 'archived', 'terminated']

// 所选空间用 localStorage 本地记忆（无后端偏好）：默认 __all__（全部空间），
// 用户选定后刷新/重进沿用所选空间。
const spaceFilter = useLocalStorage<string>('projects-selected-space', ALL)
const statusFilter = ref<string>(ALL)
const onlyMine = ref(false)
const searchInput = ref('')
const search = refDebounced(searchInput, 300)

// 全局/模糊搜索面板（WB-05）：默认折叠，在当前筛选可见的项目范围内做内容召回。
const showSearchPanel = ref(false)

// 可选空间列表（筛选下拉）。
const { data: spaces } = useQuery({
  queryKey: ['spaces', 'for-project-filter'],
  queryFn: () => spacesApi.list(),
})
const spaceOptions = computed<Space[]>(() => spaces.value ?? [])

const filters = computed<ProjectListFilters>(() => {
  const f: ProjectListFilters = {}
  if (spaceFilter.value !== ALL)
    f.space_id = spaceFilter.value
  if (statusFilter.value !== ALL)
    f.status = statusFilter.value as ProjectStatus
  if (onlyMine.value && authStore.user?.id)
    f.member = authStore.user.id
  if (search.value.trim())
    f.q = search.value.trim()
  return f
})

const { data, isLoading, isError, refetch } = useQuery({
  queryKey: ['projects', filters],
  queryFn: () => projectsApi.list(filters.value),
})

const projects = computed<Project[]>(() => data.value ?? [])
const isEmpty = computed(() => projects.value.length === 0)
const isFiltered = computed(() =>
  spaceFilter.value !== ALL
  || statusFilter.value !== ALL
  || onlyMine.value
  || !!search.value.trim(),
)

const statusLabel = computed(() =>
  statusFilter.value === ALL
    ? t('projects.filter.allStatus')
    : t(`projects.status.${statusFilter.value}`),
)
const spaceLabel = computed(() =>
  spaceFilter.value === ALL
    ? t('projects.filter.allSpace')
    : spaceOptions.value.find(s => s.id === spaceFilter.value)?.name ?? t('projects.filter.allSpace'),
)

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

async function openCreate() {
  const { open } = useModal<string>({
    component: markRaw(CreateProjectModal),
    onConfirm: (projectId) => {
      router.push(`/projects/${projectId}`)
    },
  })
  await open()
}
</script>

<template>
  <PageContainer>
    <PageHeader
      icon="lucide--folder-kanban"
      :title="t('projects.title')"
      :description="t('projects.subtitle')"
    >
      <template #actions>
        <Button data-testid="create-project-btn" @click="openCreate">
          <span class="icon-[lucide--plus] mr-1.5" />
          {{ t('projects.create') }}
        </Button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <div class="flex flex-wrap items-center gap-3">
      <Select v-model="spaceFilter">
        <SelectTrigger class="w-[200px]" :aria-label="t('projects.filter.space')">
          <span class="icon-[lucide--folder-git-2] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue>{{ spaceLabel }}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('projects.filter.allSpace') }}
          </SelectItem>
          <SelectItem v-for="s in spaceOptions" :key="s.id" :value="s.id">
            {{ s.name }}
          </SelectItem>
        </SelectContent>
      </Select>

      <Select v-model="statusFilter">
        <SelectTrigger class="w-[160px]" :aria-label="t('projects.filter.status')">
          <span class="icon-[lucide--filter] mr-1.5 text-sm text-muted-foreground" />
          <SelectValue>{{ statusLabel }}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          <SelectItem :value="ALL">
            {{ t('projects.filter.allStatus') }}
          </SelectItem>
          <SelectItem v-for="s in STATUSES" :key="s" :value="s">
            {{ t(`projects.status.${s}`) }}
          </SelectItem>
        </SelectContent>
      </Select>

      <label class="flex items-center gap-2 text-sm text-muted-foreground cursor-pointer select-none">
        <input v-model="onlyMine" type="checkbox" class="rounded border-border/60">
        {{ t('projects.filter.onlyMine') }}
      </label>

      <Button
        variant="outline"
        size="sm"
        data-testid="global-search-toggle"
        :aria-expanded="showSearchPanel"
        class="sm:ml-auto"
        @click="showSearchPanel = !showSearchPanel"
      >
        <span class="icon-[lucide--search-code] mr-1.5" />
        {{ showSearchPanel ? t('projects.search.close') : t('projects.search.open') }}
      </Button>

      <div class="relative w-full sm:w-64">
        <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 text-sm pointer-events-none" />
        <input
          v-model="searchInput"
          :placeholder="t('projects.filter.searchPlaceholder')"
          class="flex h-9 w-full rounded-lg border border-border/60 bg-background/90 pl-9 pr-3 py-1 text-sm placeholder:text-muted-foreground/70 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:border-ring/50"
        >
      </div>
    </div>

    <!-- 全局/模糊搜索面板（在当前筛选可见的项目范围内召回，结果带 repo/project 定位） -->
    <ProjectSearchPanel v-if="showSearchPanel" :projects="projects" />

    <!-- 状态 -->
    <LoadingState v-if="isLoading" variant="card" :count="3" :text="t('projects.loading')" />
    <div v-else-if="isError" class="py-12 text-center space-y-3">
      <p class="text-sm text-destructive">
        {{ t('projects.loadError') }}
      </p>
      <Button variant="outline" size="sm" @click="() => refetch()">
        {{ t('projects.retry') }}
      </Button>
    </div>
    <EmptyState
      v-else-if="isEmpty"
      icon="lucide--folder-kanban"
      :title="isFiltered ? t('projects.emptyFiltered') : t('projects.empty')"
      :description="isFiltered ? t('projects.emptyFilteredDesc') : t('projects.emptyDesc')"
      :action-label="isFiltered ? undefined : t('projects.create')"
      @action="openCreate"
    />

    <!-- 项目卡片网格 -->
    <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <RouterLink
        v-for="p in projects"
        :key="p.id"
        :to="`/projects/${p.id}`"
        class="card card-interactive group flex flex-col gap-3 p-4"
        data-testid="project-card"
      >
        <div class="flex items-start justify-between gap-2">
          <h3 class="font-semibold text-foreground truncate group-hover:text-primary transition-colors">
            {{ p.name }}
          </h3>
          <span
            class="shrink-0 px-2 py-0.5 rounded-full text-xs font-medium"
            :class="statusBadgeClass(p.status)"
          >
            {{ t(`projects.status.${p.status}`) }}
          </span>
        </div>
        <p v-if="p.description" class="text-sm text-muted-foreground line-clamp-2">
          {{ p.description }}
        </p>
        <div class="mt-auto flex items-center gap-3 text-xs text-muted-foreground">
          <span class="inline-flex items-center gap-1">
            <span class="icon-[lucide--folder-git-2]" />
            {{ p.space_name }}
          </span>
          <span class="inline-flex items-center gap-1">
            <span class="icon-[lucide--users]" />
            {{ t('projects.memberCount', { n: p.member_count }) }}
          </span>
          <span
            v-if="p.feishu_project_key"
            class="inline-flex items-center gap-1 text-primary/70"
            :title="t('projects.feishuLinked')"
          >
            <span class="icon-[lucide--link]" />
            {{ t('projects.feishuLinked') }}
          </span>
        </div>
      </RouterLink>
    </div>
  </PageContainer>
</template>
