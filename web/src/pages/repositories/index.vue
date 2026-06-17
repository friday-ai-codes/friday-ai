<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import PageHeader from '~/components/common/PageHeader.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateRepositoryModal from '~/components/repository/CreateRepositoryModal.vue'
import SddMethodologyBadge from '~/components/repository/SddMethodologyBadge.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { PLATFORM_LABELS } from '~/types'

useHead({
  title: '仓库管理 - Friday AI',
})

const router = useRouter()
const repositoriesStore = useRepositoriesStore()
const { handleError } = useErrorHandler()

// 加载仓库列表
const loading = ref(true)

onMounted(async () => {
  try {
    await repositoriesStore.fetchRepositories()
  }
  catch (e: unknown) {
    handleError(e, '加载仓库列表')
  }
  finally {
    loading.value = false
  }
})

// 新建仓库弹窗
async function openCreateRepository() {
  const { open } = useModal<string>({
    component: markRaw(CreateRepositoryModal),
    onConfirm: (repositoryId) => {
      router.push(`/repositories/${repositoryId}`)
    },
  })
  await open()
}

// 平台图标映射
const platformIcons: Record<string, string> = {
  github: 'lucide--github',
  gitlab: 'simple-icons--gitlab',
  gitee: 'simple-icons--gitee',
}

const indexToneClasses: Record<string, string> = {
  indexed: 'bg-emerald-500',
  indexing: 'bg-blue-500 animate-pulse',
  failed: 'bg-red-500',
  cancelled: 'bg-slate-400',
  not_indexed: 'bg-amber-500',
}

const indexPanelClasses: Record<string, string> = {
  indexed: 'from-emerald-500/10 via-transparent to-transparent',
  indexing: 'from-blue-500/10 via-transparent to-transparent',
  failed: 'from-red-500/10 via-transparent to-transparent',
  cancelled: 'from-slate-400/10 via-transparent to-transparent',
  not_indexed: 'from-amber-500/10 via-transparent to-transparent',
}

function formatIndexedTime(value: string) {
  return new Date(value).toLocaleString('zh-CN')
}
</script>

<template>
  <PageContainer>
    <!-- 页面标题 -->
    <PageHeader
      icon="lucide--git-branch"
      icon-gradient="from-primary/20 to-primary/10"
      icon-color="text-primary"
      title="仓库管理"
      description="管理您的 Git 仓库和凭证配置"
    >
      <template #actions>
        <Button variant="outline" @click="router.push('/repositories/tree')">
          <span class="icon-[lucide--folder-tree]" />
          知识树
        </Button>
        <Button @click="openCreateRepository">
          <span class="icon-[lucide--plus]" />
          新建仓库
        </Button>
      </template>
    </PageHeader>

    <!-- 加载状态 -->
    <LoadingState v-if="loading" variant="card" :count="3" />

    <!-- 空状态 -->
    <EmptyState
      v-else-if="repositoriesStore.repositories.length === 0"
      icon="lucide--git-branch"
      title="暂无仓库"
      description="创建您的第一个仓库，关联到空间以开始使用"
      action-label="新建仓库"
      gradient="from-primary/20 to-primary/10"
      @action="openCreateRepository()"
    />

    <!-- 仓库列表 -->
    <div v-else class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
      <article
        v-for="repository in repositoriesStore.repositories"
        :key="repository.id"
        class="repo-card group relative flex min-h-[220px] flex-col overflow-hidden rounded-lg border border-border/70 bg-card shadow-[0_1px_2px_rgba(15,23,42,0.06)] transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-[0_12px_28px_rgba(15,23,42,0.08)] focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/20"
        :class="{ 'repo-card--sdd': repository.methodology === 'SDD' }"
      >
        <div
          class="pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-b"
          :class="indexPanelClasses[repository.index_status] || indexPanelClasses.not_indexed"
        />

        <!-- SDD 项目专属：镂空绿色半透明水印（aria-hidden，纯装饰，置于内容下层） -->
        <span
          v-if="repository.methodology === 'SDD'"
          aria-hidden="true"
          class="sdd-watermark"
        >SDD</span>

        <RouterLink
          :to="`/repositories/${repository.id}`"
          class="relative flex flex-1 flex-col gap-4 p-4 outline-none"
        >
          <div class="flex items-start gap-3">
            <div class="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-primary/10">
              <span class="text-lg" :class="`icon-[${platformIcons[repository.git_platform] || 'lucide--git-branch'}]`" />
            </div>

            <div class="min-w-0 flex-1">
              <div class="flex items-start justify-between gap-2">
                <h3 class="truncate text-base font-semibold leading-6 text-foreground transition-colors group-hover:text-primary">
                  {{ repository.name }}
                </h3>
                <StatusBadge type="index" :status="repository.index_status" size="sm" class="shrink-0" />
              </div>

              <div class="mt-2 flex flex-wrap items-center gap-2">
                <Badge variant="outline" class="h-6 border-border/80 bg-background/70 px-2 text-xs font-medium">
                  {{ PLATFORM_LABELS[repository.git_platform] }}
                </Badge>
                <span class="repo-meta-item">
                  <span class="icon-[lucide--git-branch]" />
                  {{ repository.default_branch }}
                </span>
                <span v-if="repository.linked_spaces_count" class="repo-meta-item">
                  <span class="icon-[lucide--folder]" />
                  {{ repository.linked_spaces_count }} 个空间
                </span>
                <SddMethodologyBadge :methodology="repository.methodology" />
              </div>
            </div>
          </div>

          <div class="repo-url-chip" :title="repository.git_url">
            <span class="icon-[lucide--link-2] shrink-0 text-muted-foreground/70" />
            <span class="truncate">{{ repository.git_url }}</span>
          </div>

          <div class="mt-auto flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
            <span v-if="repository.last_indexed_at" class="repo-meta-item">
              <span class="icon-[lucide--clock-3]" />
              索引于 {{ formatIndexedTime(repository.last_indexed_at) }}
            </span>
            <span class="repo-meta-item">
              <span class="relative flex size-2">
                <span
                  class="absolute inline-flex size-full rounded-full opacity-20"
                  :class="indexToneClasses[repository.index_status] || indexToneClasses.not_indexed"
                />
                <span
                  class="relative inline-flex size-2 rounded-full"
                  :class="indexToneClasses[repository.index_status] || indexToneClasses.not_indexed"
                />
              </span>
              代码库状态同步
            </span>
          </div>
        </RouterLink>

        <!-- 底部操作栏 -->
        <div class="repo-card-actions relative flex items-center justify-between border-t border-border/60 bg-muted/20 px-4 py-3">
          <RouterLink
            :to="`/repositories/${repository.id}`"
            class="inline-flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
          >
            查看详情
            <span class="icon-[lucide--arrow-right] transition-transform group-hover:translate-x-0.5" />
          </RouterLink>

          <div class="flex items-center gap-1">
            <TooltipProvider :delay-duration="300">
              <RouterLink :to="`/repositories/${repository.id}?tab=indexing`" @click.stop>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button variant="ghost" size="icon-sm" class="text-muted-foreground hover:text-primary">
                      <span class="icon-[lucide--database]" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>代码索引</TooltipContent>
                </Tooltip>
              </RouterLink>
              <RouterLink :to="`/repositories/${repository.id}#credential`" @click.stop>
                <Tooltip>
                  <TooltipTrigger as-child>
                    <Button variant="ghost" size="icon-sm" class="text-muted-foreground hover:text-primary">
                      <span class="icon-[lucide--key]" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>凭证管理</TooltipContent>
                </Tooltip>
              </RouterLink>
            </TooltipProvider>
          </div>
        </div>
      </article>
    </div>
  </PageContainer>
</template>

<style scoped>
.repo-url-chip {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  border-radius: 0.5rem;
  border: 1px solid hsl(214 32% 91% / 0.72);
  background: hsl(210 40% 98% / 0.82);
  padding: 0.625rem 0.75rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  font-size: 0.75rem;
  line-height: 1rem;
  color: hsl(215 16% 47%);
}

.repo-meta-item {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 0.375rem;
  white-space: nowrap;
  color: hsl(215 16% 47%);
}

.repo-meta-item > :global([class*='icon-']) {
  flex-shrink: 0;
  font-size: 0.875rem;
}

/* ==================== SDD 项目卡片专属强调 ==================== */
/* emerald 边框 + 斜向淡绿底色，与普通卡片一眼区分（领导重点关注 SDD） */
.repo-card--sdd {
  border-color: hsl(160 84% 39% / 0.5);
  background-image: linear-gradient(135deg, hsl(152 76% 96% / 0.85), transparent 58%);
}

.repo-card--sdd:hover {
  border-color: hsl(160 84% 39% / 0.72);
}

:global(.dark) .repo-card--sdd {
  border-color: hsl(160 84% 45% / 0.38);
  background-image: linear-gradient(135deg, hsl(160 84% 30% / 0.14), transparent 58%);
}

:global(.dark) .repo-card--sdd:hover {
  border-color: hsl(160 84% 50% / 0.55);
}

/* 镂空（描边）半透明 SDD 水印：bleed 出卡片右下角，overflow-hidden 裁切 */
.sdd-watermark {
  position: absolute;
  right: -0.5rem;
  bottom: -1.75rem;
  font-family:
    ui-sans-serif,
    system-ui,
    -apple-system,
    'Segoe UI',
    sans-serif;
  font-size: 7rem;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -0.06em;
  color: transparent;
  -webkit-text-stroke: 2px hsl(160 84% 39% / 0.16);
  pointer-events: none;
  user-select: none;
}

:global(.dark) .sdd-watermark {
  -webkit-text-stroke-color: hsl(160 84% 52% / 0.22);
}
</style>
