<script setup lang="ts">
/**
 * 管理员只读会话后台页（ADMVW-01/02/03）。
 *
 * - DataTable 列出所有用户会话（owner / 标题 / 状态 / 消息数 / 更新时间）。(ADMVW-01)
 * - 行点击 → getAdminConversation 取详情，在对话框中用 ReadonlyConversationView
 *   只读展示（无输入/发送/编辑/删除入口）。(ADMVW-02)
 * - 「复制到我的名下」动作 → forkAdminConversation → 跳转 /chat?conversation=<新 id>
 *   以普通 chat owner 身份续聊。(ADMVW-03)
 *
 * 前端 requiresAdmin 守卫仅 UX 兜底；真正授权在后端 IsSuperUser（09-02）。
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { AdminConversationDetail, AdminConversationListItem } from '~/api/adminConversations'
import { h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  forkAdminConversation,
  getAdminConversation,
  listAdminConversations,
} from '~/api/adminConversations'
import ReadonlyConversationView from '~/components/admin/ReadonlyConversationView.vue'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

definePage({
  meta: { requiresAdmin: true },
})

const { handleError } = useErrorHandler()
const { success } = useToast()
const router = useRouter()

const conversations = ref<AdminConversationListItem[]>([])
const loading = ref(true)
const forking = ref<string | null>(null)

// 只读详情对话框
const detailOpen = ref(false)
const detailLoading = ref(false)
const detail = ref<AdminConversationDetail | null>(null)

async function loadConversations() {
  loading.value = true
  try {
    conversations.value = await listAdminConversations()
  }
  catch (e: unknown) {
    handleError(e, '加载会话列表')
  }
  finally {
    loading.value = false
  }
}

async function openDetail(item: AdminConversationListItem) {
  detailOpen.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await getAdminConversation(item.id)
  }
  catch (e: unknown) {
    handleError(e, '加载会话详情')
  }
  finally {
    detailLoading.value = false
  }
}

async function forkToOwn(item: AdminConversationListItem) {
  forking.value = item.id
  try {
    const { conversation_id } = await forkAdminConversation(item.id)
    success('已复制到我的名下')
    router.push(`/chat?conversation=${conversation_id}`)
  }
  catch (e: unknown) {
    handleError(e, '复制会话')
  }
  finally {
    forking.value = null
  }
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleString('zh-CN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// 会话状态 → 中文标签 + Badge variant
const STATUS_META: Record<string, { label: string, variant: 'default' | 'secondary' | 'outline' | 'destructive' }> = {
  running: { label: '运行中', variant: 'default' },
  completed: { label: '已完成', variant: 'secondary' },
  draft: { label: '草稿', variant: 'outline' },
  DRAFT: { label: '草稿', variant: 'outline' },
}

function statusMeta(status: string) {
  return STATUS_META[status] ?? { label: status, variant: 'outline' as const }
}

onMounted(() => {
  loadConversations()
})

const columns: ColumnDef<AdminConversationListItem>[] = [
  {
    id: 'owner',
    header: '所属用户',
    cell: ({ row }) => {
      const owner = row.original.owner
      const name = owner?.display_name || owner?.username || '—'
      const initial = name.charAt(0).toUpperCase()
      return h('div', { class: 'flex items-center gap-3' }, [
        h('div', {
          class: 'w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-medium shrink-0',
        }, initial),
        h('div', { class: 'min-w-0' }, [
          h('span', { class: 'font-medium text-sm text-foreground block' }, name),
          owner?.username
            ? h('span', { class: 'text-xs text-muted-foreground' }, `@${owner.username}`)
            : null,
        ]),
      ])
    },
    enableSorting: false,
  },
  {
    accessorKey: 'title',
    header: '标题',
    cell: ({ row }) => h('span', { class: 'text-sm text-foreground' }, row.original.title || '未命名会话'),
    enableSorting: true,
  },
  {
    id: 'status',
    header: '状态',
    cell: ({ row }) => {
      const meta = statusMeta(row.original.status)
      return h(Badge, { variant: meta.variant, class: 'text-xs' }, () => meta.label)
    },
    enableSorting: false,
  },
  {
    accessorKey: 'message_count',
    header: '消息数',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground tabular-nums' }, String(row.original.message_count ?? 0)),
    enableSorting: true,
  },
  {
    accessorKey: 'updated_at',
    header: '更新时间',
    cell: ({ row }) => h('span', { class: 'text-sm text-muted-foreground' }, formatDate(row.original.updated_at)),
    enableSorting: true,
  },
  {
    id: 'actions',
    header: '操作',
    cell: ({ row }) => h(Button, {
      variant: 'secondary',
      size: 'sm',
      disabled: forking.value === row.original.id,
      onClick: (e: Event) => {
        e.stopPropagation()
        forkToOwn(row.original)
      },
    }, () => 'fork 到我的名下'),
    enableSorting: false,
    enableHiding: false,
  },
]
</script>

<template>
  <PageContainer show-background>
    <PageHeader
      icon="lucide--messages-square"
      icon-gradient="from-primary/20 to-secondary/10"
      icon-color="text-primary"
      title="会话管理"
      description="只读浏览全部用户会话，可复制任意会话到自己名下后继续对话"
    />

    <DataTable
      :data="conversations"
      :columns="columns"
      table-id="admin-conversations-list"
      :loading="loading"
      :on-row-click="openDetail"
    />

    <!-- 只读详情对话框：无任何写入入口 -->
    <Dialog v-model:open="detailOpen">
      <DialogScrollContent class="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{{ detail?.title || '会话详情' }}</DialogTitle>
          <DialogDescription>
            只读查看 · 如需续聊请使用「fork 到我的名下」
          </DialogDescription>
        </DialogHeader>

        <div v-if="detailLoading" class="py-12 text-center text-sm text-muted-foreground">
          加载中...
        </div>
        <ReadonlyConversationView
          v-else
          :messages="detail?.messages ?? []"
        />
      </DialogScrollContent>
    </Dialog>
  </PageContainer>
</template>
