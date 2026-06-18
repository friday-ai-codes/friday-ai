<script setup lang="ts">
import type { ColumnDef } from '@tanstack/vue-table'
import type { Runner } from '~/types'
import { useHead } from '@vueuse/head'
import { h } from 'vue'
import PageHeader from '~/components/common/PageHeader.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import CreateRunnerModal from '~/components/runners/CreateRunnerModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'

// 后端 Runner API 为 IsSuperUser；前端守卫仅 UX 兜底，避免普通用户点入即 403
definePage({ meta: { requiresAdmin: true } })

useHead({ title: 'Runner 管理 - Friday AI' })

const route = useRoute()
const router = useRouter()
const runnersStore = useRunnersStore()
const { handleError } = useErrorHandler()
const { success } = useToast()

// 创建 Runner 弹窗（原 /runners/new 页面已降级为弹窗）
const createModalOpen = ref(false)

async function handleRunnerCreated() {
  try {
    await runnersStore.fetchRunners()
  }
  catch {
    // 列表刷新失败不阻塞令牌展示
  }
}

const { status } = useRunnerMonitor()
const disconnectedTooLong = ref(false)
let disconnectTimer: ReturnType<typeof setTimeout> | undefined

watch(status, (val) => {
  if (val === 'connected') {
    disconnectedTooLong.value = false
    if (disconnectTimer) {
      clearTimeout(disconnectTimer)
      disconnectTimer = undefined
    }
  }
  else if (!disconnectTimer) {
    disconnectTimer = setTimeout(() => {
      disconnectedTooLong.value = true
      disconnectTimer = undefined
    }, 10_000)
  }
})

// 搜索/排序/分页/每页大小持久化到 URL（刷新可恢复）
const { pagination, sorting, globalFilter } = useTableUrlState()

const loading = ref(true)
onMounted(async () => {
  try {
    await runnersStore.fetchRunners()
  }
  catch (e: unknown) {
    handleError(e, '加载 Runner 列表')
  }
  finally {
    loading.value = false
  }

  // 旧 /runners/new URL 重定向过来时自动打开创建弹窗
  if (route.hash === '#new')
    createModalOpen.value = true
})

onUnmounted(() => {
  if (disconnectTimer)
    clearTimeout(disconnectTimer)
})

const deleteDialogOpen = ref(false)
const runnerToDelete = ref<{ id: string, name: string } | null>(null)
const deleting = ref(false)

function confirmDelete(runner: Runner) {
  runnerToDelete.value = { id: runner.id, name: runner.name }
  deleteDialogOpen.value = true
}

async function handleDelete() {
  if (!runnerToDelete.value)
    return
  deleting.value = true
  try {
    await runnersStore.removeRunner(runnerToDelete.value.id)
    success('删除成功', `Runner「${runnerToDelete.value.name}」已删除`)
    deleteDialogOpen.value = false
  }
  catch (e: unknown) { handleError(e, '删除 Runner') }
  finally { deleting.value = false }
}

function formatTimeAgo(dateStr: string | null) {
  if (!dateStr)
    return '从未'
  return useTimeAgo(new Date(dateStr)).value
}

function formatAbsoluteTime(dateStr: string | null) {
  if (!dateStr)
    return '从未连接'
  return new Date(dateStr).toLocaleString('zh-CN')
}

// --- DataTable 列定义 ---
const columns: ColumnDef<Runner>[] = [
  {
    accessorKey: 'status',
    header: '状态',
    cell: ({ row }) => h(StatusBadge, { type: 'runner', status: row.original.status }),
    enableSorting: false,
    enableGlobalFilter: false,
  },
  {
    accessorKey: 'name',
    header: 'Runner',
    cell: ({ row }) => {
      const runner = row.original
      return h('div', { class: 'flex flex-col gap-0.5' }, [
        h('div', { class: 'flex items-center gap-2' }, [
          h('span', { class: 'font-medium text-foreground' }, runner.name),
          runner.is_protected
            ? h(Badge, { variant: 'outline', class: 'text-xs' }, () => [
                h('span', { class: 'icon-[lucide--shield] mr-0.5 text-[10px]' }),
                '受保护',
              ])
            : null,
        ]),
        h('span', { class: 'text-xs text-muted-foreground' }, `${runner.description || `#${runner.id.slice(0, 8)}`} · ${runner.ip_address || '-'}`),
      ])
    },
    enableSorting: true,
  },
  {
    accessorKey: 'tags',
    header: '标签',
    cell: ({ row }) => {
      const tags = row.original.tags
      return h('div', { class: 'flex items-center gap-1 flex-wrap' }, [
        ...tags.slice(0, 3).map(tag => h(Badge, { key: tag, variant: 'secondary', class: 'text-xs' }, () => tag)),
        tags.length > 3 ? h(Badge, { variant: 'outline', class: 'text-xs text-muted-foreground' }, () => `+${tags.length - 3}`) : null,
        tags.length === 0 ? h('span', { class: 'text-xs text-muted-foreground' }, '-') : null,
      ])
    },
    enableSorting: false,
    enableGlobalFilter: false,
  },
  {
    accessorKey: 'current_tasks',
    header: '任务数',
    cell: ({ row }) => h('span', { class: 'text-sm' }, String(row.original.current_tasks)),
    enableSorting: true,
  },
  {
    accessorKey: 'last_heartbeat',
    header: '最后联系',
    cell: ({ row }) => {
      const dateStr = row.original.last_heartbeat
      return h(TooltipProvider, null, () =>
        h(Tooltip, null, {
          default: () => [
            h(TooltipTrigger, { asChild: true }, () =>
              h('span', {
                class: 'text-sm text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/30',
              }, formatTimeAgo(dateStr))),
            h(TooltipContent, null, () => formatAbsoluteTime(dateStr)),
          ],
        }))
    },
    enableSorting: true,
    enableGlobalFilter: false,
  },
  {
    id: 'actions',
    header: '操作',
    cell: ({ row }) => h(Button, {
      variant: 'ghost',
      size: 'icon',
      class: 'h-8 w-8 hover:bg-destructive/10 hover:text-destructive',
      onClick: (e: Event) => {
        e.stopPropagation()
        confirmDelete(row.original)
      },
    }, () => h('span', { class: 'icon-[lucide--trash-2] text-sm' })),
    enableSorting: false,
    enableHiding: false,
  },
]
</script>

<template>
  <PageContainer show-background>
    <!-- 页头 -->
    <PageHeader
      icon="lucide--server"
      icon-gradient="from-primary/20 to-primary/10"
      icon-color="text-primary"
      title="Runner"
      description="管理和监控您的 Runner 实例"
    >
      <template #title-suffix>
        <Badge variant="secondary">
          {{ runnersStore.runners.length }}
        </Badge>
      </template>
      <template #actions>
        <Button class="group relative overflow-hidden" @click="createModalOpen = true">
          <span class="absolute inset-0 -translate-x-full group-hover:translate-x-full transition-transform duration-700" />
          <span class="icon-[lucide--plus] mr-1.5" />
          新建 Runner
        </Button>
      </template>
    </PageHeader>

    <!-- 断线横幅 -->
    <Transition
      enter-active-class="transition-all duration-300"
      enter-from-class="opacity-0 -translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition-all duration-200"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="disconnectedTooLong"
        class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-sm"
      >
        <span class="icon-[lucide--wifi-off] text-base" />
        <span>连接已断开，正在重连...</span>
        <span v-if="status === 'disconnected'" class="ml-auto text-xs text-muted-foreground">无法连接，请刷新页面</span>
      </div>
    </Transition>

    <!-- DataTable — 集成搜索/排序/分页/列可见性 -->
    <DataTable
      v-model:pagination="pagination"
      v-model:sorting="sorting"
      v-model:global-filter="globalFilter"
      :data="runnersStore.runners"
      :columns="columns"
      table-id="runners-list"
      :loading="loading"
      search-placeholder="搜索 Runner..."
      :on-row-click="(runner) => router.push(`/runners/${runner.id}`)"
    />

    <!-- 创建 Runner 弹窗 -->
    <CreateRunnerModal
      v-model:open="createModalOpen"
      @created="handleRunnerCreated"
    />

    <!-- 删除确认 -->
    <ConfirmDialog
      v-model:open="deleteDialogOpen"
      title="删除 Runner"
      :description="`确定要删除 Runner「${runnerToDelete?.name}」吗？此操作不可撤销。`"
      confirm-text="删除"
      variant="destructive"
      :loading="deleting"
      @confirm="handleDelete"
    />
  </PageContainer>
</template>
