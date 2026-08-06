<script setup lang="ts">
import type { Project, ProjectListFilters, ProjectStatus } from '~/api/projects'
import type { BadgeVariants } from '~/components/ui/badge'
import type { Space } from '~/types'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { refDebounced, useLocalStorage } from '@vueuse/core'
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
import { Avatar, AvatarFallback } from '~/components/ui/avatar'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useAuthStore } from '~/stores/auth'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()
const queryClient = useQueryClient()

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

// 自愈：localStorage 记忆的空间可能已不存在（空间被删 / 切换了数据库实例）。
// 拿旧 ID 去过滤只会得到一个「看起来数据全丢了」的空列表——空间清单就绪后
// 校验一次，失配即回落「全部」。（与 chat.vue 对 chat-space-id 的自愈同一口径）
watch(spaceOptions, (options) => {
  if (!options.length || spaceFilter.value === ALL)
    return
  if (!options.some(space => String(space.id) === spaceFilter.value))
    spaceFilter.value = ALL
}, { immediate: true })

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

function statusVariant(status: ProjectStatus): BadgeVariants['variant'] {
  switch (status) {
    case 'developing':
      return 'success'
    case 'terminated':
      return 'destructive'
    default:
      return 'muted'
  }
}

async function openCreate() {
  const { open } = useModal<string>({
    component: markRaw(CreateProjectModal),
    onConfirm: (projectId) => {
      // 刷新项目列表缓存（创建后返回列表即可见新项目），并跳转到详情页。
      queryClient.invalidateQueries({ queryKey: ['projects'] })
      if (projectId)
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
      icon-gradient="from-primary/10 to-primary/10"
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
    <div class="flex flex-wrap items-center gap-2.5">
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

      <Label
        class="inline-flex items-center gap-2 h-9 px-3 rounded-lg border text-sm cursor-pointer select-none transition-colors"
        :class="onlyMine ? 'border-primary/30 bg-primary/5 text-foreground' : 'border-border/60 text-muted-foreground hover:bg-muted/50'"
      >
        <Checkbox v-model="onlyMine" data-testid="only-mine-checkbox" class="size-4" />
        {{ t('projects.filter.onlyMine') }}
      </Label>

      <div class="sm:ml-auto flex items-center gap-2.5 w-full sm:w-auto">
        <div class="relative flex-1 sm:w-64">
          <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 text-sm pointer-events-none z-10" />
          <Input
            v-model="searchInput"
            :placeholder="t('projects.filter.searchPlaceholder')"
            class="h-9 pl-9 rounded-lg"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          class="h-9"
          data-testid="global-search-toggle"
          :aria-expanded="showSearchPanel"
          @click="showSearchPanel = !showSearchPanel"
        >
          <span class="icon-[lucide--search-code] mr-1.5" />
          {{ showSearchPanel ? t('projects.search.close') : t('projects.search.open') }}
        </Button>
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
    <div v-else class="grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
      <RouterLink
        v-for="p in projects"
        :key="p.id"
        :to="`/projects/${p.id}`"
        class="card card-interactive group flex flex-col p-5"
        data-testid="project-card"
      >
        <!-- 头部：头像 + 名称/空间 + 状态 -->
        <div class="flex items-center gap-3">
          <Avatar shape="square" class="size-10 rounded-xl bg-primary/10 ring-1 ring-primary/15 shrink-0">
            <AvatarFallback class="bg-transparent rounded-xl text-primary font-semibold">
              {{ (p.name || '?').slice(0, 1).toUpperCase() }}
            </AvatarFallback>
          </Avatar>
          <div class="min-w-0 flex-1">
            <h3 class="font-semibold text-foreground truncate group-hover:text-primary transition-colors">
              {{ p.name }}
            </h3>
            <p class="text-xs text-muted-foreground inline-flex items-center gap-1 max-w-full truncate">
              <span class="icon-[lucide--folder-git-2] text-[11px] shrink-0" />
              <span class="truncate">{{ p.space_name }}</span>
            </p>
          </div>
          <Badge :variant="statusVariant(p.status)" class="shrink-0">
            {{ t(`projects.status.${p.status}`) }}
          </Badge>
        </div>

        <!-- 描述 -->
        <p class="mt-3.5 text-sm text-muted-foreground line-clamp-2 min-h-10">
          {{ p.description || t('projects.overview.noDescription') }}
        </p>

        <!-- 底部：成员 / 飞书 + 打开提示 -->
        <div class="mt-4 pt-3 border-t border-border/50 flex items-center gap-3 text-xs text-muted-foreground">
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
          <span class="ml-auto inline-flex items-center text-primary opacity-0 -translate-x-1 transition-all duration-200 group-hover:opacity-100 group-hover:translate-x-0">
            <span class="icon-[lucide--arrow-right]" />
          </span>
        </div>
      </RouterLink>
    </div>
  </PageContainer>
</template>
