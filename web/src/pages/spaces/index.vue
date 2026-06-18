<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { markRaw } from 'vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import TriggerLogDetailModal from '~/components/logs/TriggerLogDetailModal.vue'
import CreateSpaceModal from '~/components/space/CreateSpaceModal.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useTableUrlState } from '~/composables/useTableUrlState'

useHead({
  title: '空间管理 - Friday AI',
})

const router = useRouter()
const spacesStore = useSpacesStore()
const { handleError } = useErrorHandler()

// 加载空间列表
const loading = ref(true)

// 搜索 + 分页（卡片网格客户端分页），状态持久化到 URL（刷新可恢复）
const { pagination, globalFilter } = useTableUrlState({ pageSize: 12, sort: false })

const filteredSpaces = computed(() => {
  const q = globalFilter.value.trim().toLowerCase()
  if (!q)
    return spacesStore.spaces
  return spacesStore.spaces.filter(s =>
    [s.name, s.description].some(field => String(field ?? '').toLowerCase().includes(q)),
  )
})

const pagedSpaces = computed(() => {
  const start = pagination.value.pageIndex * pagination.value.pageSize
  return filteredSpaces.value.slice(start, start + pagination.value.pageSize)
})

onMounted(async () => {
  try {
    await spacesStore.fetchSpaces()
  }
  catch (e: unknown) {
    handleError(e, '加载空间列表')
  }
  finally {
    loading.value = false
  }
})

// 最近工作项详情弹窗（原 /logs/triggers/[id] 页面已统一为弹窗）
async function openTriggerLog(logId: string) {
  const { open } = useModal({
    component: markRaw(TriggerLogDetailModal),
    attrs: { logId },
  })
  await open()
}

// 新建空间弹窗
async function openCreateSpace() {
  const { open } = useModal<string>({
    component: markRaw(CreateSpaceModal),
    onConfirm: (spaceId) => {
      // 创建成功后跳转到空间详情
      router.push(`/spaces/${spaceId}`)
    },
  })
  await open()
}
</script>

<template>
  <PageContainer>
    <!-- 页面标题 -->
    <PageHeader
      icon="lucide--folder-git-2"
      icon-gradient="from-primary/20 to-primary/10"
      icon-color="text-primary"
      title="空间管理"
      description="管理您的 Git 仓库空间和凭证配置"
    >
      <template #actions>
        <Button @click="openCreateSpace">
          <span class="icon-[lucide--plus]" />
          新建空间
        </Button>
      </template>
    </PageHeader>

    <!-- 加载状态 -->
    <LoadingState v-if="loading" variant="card" :count="3" />

    <!-- 空状态 -->
    <EmptyState
      v-else-if="spacesStore.spaces.length === 0"
      icon="lucide--folder-git-2"
      title="暂无空间"
      description="创建您的第一个空间，开始使用 AI 辅助开发"
      action-label="新建空间"
      gradient="from-primary/20 to-primary/20"
      @action="openCreateSpace"
    />

    <template v-else>
      <!-- 搜索栏 -->
      <div class="relative w-full sm:w-72">
        <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground/70 text-sm pointer-events-none" />
        <input
          v-model="globalFilter"
          placeholder="搜索空间名、描述…"
          class="flex h-9 w-full rounded-lg border border-border/60 bg-background/90 pl-9 pr-3 py-1 text-sm placeholder:text-muted-foreground/70 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:border-ring/50"
        >
      </div>

      <!-- 搜索无结果 -->
      <EmptyState
        v-if="filteredSpaces.length === 0"
        icon="lucide--search-x"
        title="无匹配空间"
        description="试试更换关键词或清空搜索"
      />

      <!-- 空间列表 -->
      <div v-else class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <RouterLink
          v-for="space in pagedSpaces"
          :key="space.id"
          :to="`/spaces/${space.id}`"
          class="card card-interactive group flex flex-col"
        >
        <div class="p-4 flex-1 space-y-3">
          <!-- 标题行 -->
          <div class="flex items-center gap-2.5">
            <div class="p-1.5 rounded-lg bg-primary/10 shrink-0">
              <span class="icon-[lucide--folder-git-2] text-base text-primary" />
            </div>
            <h3 class="text-sm font-semibold text-foreground group-hover:text-primary transition-colors truncate flex-1">
              {{ space.name }}
            </h3>
          </div>

          <!-- 描述 -->
          <p v-if="space.description" class="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
            {{ space.description }}
          </p>

          <!-- 最近工作项 -->
          <div v-if="space.recent_work_items?.length" class="flex flex-col gap-1.5 pt-1">
            <button
              v-for="item in space.recent_work_items"
              :key="item.id"
              class="group/item flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors text-left w-full"
              @click.prevent="openTriggerLog(item.id)"
            >
              <span class="w-1 h-1 rounded-full bg-muted-foreground/30 group-hover/item:bg-primary group-hover/item:scale-150 transition-all shrink-0" />
              <span class="truncate flex-1 group-hover/item:text-primary transition-colors" :title="item.name">{{ item.name }}</span>
            </button>
          </div>

          <!-- 底部信息行 -->
          <div class="flex items-center gap-4 mt-auto pt-2">
            <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span class="icon-[lucide--git-branch] text-primary/60" />
              <span>{{ space.repositories?.length || 0 }} 个仓库</span>
            </div>
            <div class="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span class="icon-[lucide--play-circle] text-primary/60" />
              <span>{{ space.execution_count || 0 }} 次执行</span>
            </div>
          </div>
        </div>

        <!-- 底部操作栏 -->
        <div class="flex items-center px-4 py-2.5 border-t border-border/50 bg-muted/20">
          <span class="text-xs text-muted-foreground group-hover:text-primary transition-colors flex items-center gap-1">
            查看详情
            <span class="icon-[lucide--arrow-right]" />
          </span>
        </div>
        </RouterLink>
      </div>

      <!-- 分页器（仅有结果时显示） -->
      <GridPager
        v-if="filteredSpaces.length > 0"
        v-model:pagination="pagination"
        :total="filteredSpaces.length"
      />
    </template>
  </PageContainer>
</template>
