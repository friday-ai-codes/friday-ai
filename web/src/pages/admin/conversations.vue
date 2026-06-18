<script setup lang="ts">
/**
 * 管理员只读会话后台页（ADMVW-01/02/03）。
 *
 * - DataTable 列出所有用户会话（owner / 标题 / 状态 / 标记 / 消息数 / 更新时间）。(ADMVW-01)
 * - 行点击 → getAdminConversation 取详情，在对话框中用 ReadonlyConversationView
 *   只读展示（无输入/发送/编辑/删除入口）。(ADMVW-02)
 * - 「克隆」动作 → forkAdminConversation → 跳转 /chat?conversation=<新 id>
 *   以普通 chat owner 身份续聊。(ADMVW-03)
 *
 * 筛选/分页持久化：能力（SDD/技术方案/编码）、状态、用户三个分面多选 + 表格搜索 +
 * 页码 + 每页大小 + 排序全部同步到 URL query，刷新后按当前视图恢复（单向 state→URL，
 * 初始 URL→state，无回环）。
 *
 * 前端 requiresAdmin 守卫仅 UX 兜底；真正授权在后端 IsSuperUser（09-02）。
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { AdminConversationDetail, AdminConversationListItem } from '~/api/adminConversations'
import type { FacetOption } from '~/components/common/FacetMultiSelect.vue'
import { computed, h, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  forkAdminConversation,
  getAdminConversation,
  listAdminConversations,
} from '~/api/adminConversations'
import ReadonlyConversationView from '~/components/admin/ReadonlyConversationView.vue'
import DataTable from '~/components/common/DataTable.vue'
import FacetMultiSelect from '~/components/common/FacetMultiSelect.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useTableUrlState } from '~/composables/useTableUrlState'
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

// 筛选/分页/排序/搜索全部持久化到 URL（刷新可恢复），单写入者统一管理
const { pagination, sorting, globalFilter, facets, resetFacets, activeFacetCount } = useTableUrlState({
  facets: {
    caps: { type: 'list' }, // sdd / plan / coding
    status: { type: 'list' },
    owners: { type: 'list' },
  },
})

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
    success('已克隆到我的名下')
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

// 相对时间（刚刚 / X 分钟前 / X 小时前 / X 天前 / X 个月前 / X 年前）；
// tooltip 仍展示 formatDate 的真实时间。
function formatRelative(dateStr: string): string {
  const t = new Date(dateStr).getTime()
  if (Number.isNaN(t))
    return dateStr
  const diff = Math.round((Date.now() - t) / 1000)
  if (diff < 0)
    return formatDate(dateStr)
  if (diff < 60)
    return '刚刚'
  if (diff < 3600)
    return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400)
    return `${Math.floor(diff / 3600)} 小时前`
  if (diff < 86400 * 30)
    return `${Math.floor(diff / 86400)} 天前`
  if (diff < 86400 * 365)
    return `${Math.floor(diff / 86400 / 30)} 个月前`
  return `${Math.floor(diff / 86400 / 365)} 年前`
}

// 会话状态 → 中文标签 + 语义色（与后端 Conversation.Status 七态对齐）。
// pulse 标记活跃态（进行中），其余为静态圆点。
interface StatusMeta {
  label: string
  /** 圆点 + 文字 + 边框背景的语义色组合 */
  dot: string
  cls: string
  pulse?: boolean
}
const STATUS_META: Record<string, StatusMeta> = {
  running: { label: '进行中', dot: 'bg-emerald-500', cls: 'text-emerald-700 bg-emerald-500/10 border-emerald-500/20', pulse: true },
  paused: { label: '已暂停', dot: 'bg-amber-500', cls: 'text-amber-700 bg-amber-500/10 border-amber-500/20' },
  interrupted: { label: '已中断', dot: 'bg-orange-500', cls: 'text-orange-700 bg-orange-500/10 border-orange-500/20' },
  completed: { label: '已完成', dot: 'bg-sky-500', cls: 'text-sky-700 bg-sky-500/10 border-sky-500/20' },
  stopped: { label: '已停止', dot: 'bg-slate-400', cls: 'text-slate-600 bg-slate-500/10 border-slate-500/20' },
  error: { label: '异常', dot: 'bg-red-500', cls: 'text-red-700 bg-red-500/10 border-red-500/20' },
  draft: { label: '草稿', dot: 'bg-muted-foreground/50', cls: 'text-muted-foreground bg-muted border-border/60' },
}

function statusMeta(status: string): StatusMeta {
  return STATUS_META[status] ?? { label: status, dot: 'bg-muted-foreground/50', cls: 'text-muted-foreground bg-muted border-border/60' }
}

// --- KPI 概览（客户端聚合已加载列表）---
interface OverviewStat {
  title: string
  value: number
  icon: string
  tone: string
}
const overviewStats = computed<OverviewStat[]>(() => {
  const list = conversations.value
  const totalMessages = list.reduce((sum, c) => sum + (c.message_count ?? 0), 0)
  const owners = new Set(list.map(c => c.owner?.id).filter(Boolean))
  const activeStatuses = new Set(['running', 'paused', 'interrupted'])
  const active = list.filter(c => activeStatuses.has(c.status)).length
  return [
    { title: '全部会话', value: list.length, icon: 'icon-[lucide--messages-square]', tone: 'text-primary bg-primary/10' },
    { title: '消息总数', value: totalMessages, icon: 'icon-[lucide--message-circle-more]', tone: 'text-sky-600 bg-sky-500/10' },
    { title: '涉及用户', value: owners.size, icon: 'icon-[lucide--users-round]', tone: 'text-violet-600 bg-violet-500/10' },
    { title: '活跃会话', value: active, icon: 'icon-[lucide--activity]', tone: 'text-emerald-600 bg-emerald-500/10' },
  ]
})

// --- 能力徽标元数据（SDD / 技术方案 / 编码），列表突出展示 + 分面筛选共用 ---
interface CapMeta {
  /** AdminConversationListItem 上的布尔字段名 */
  key: 'has_sdd_spec' | 'has_coding_plan' | 'has_coding_session'
  /** 分面过滤值 */
  value: string
  label: string
  icon: string
  /** 徽标配色 */
  cls: string
}
const CAP_META: CapMeta[] = [
  { key: 'has_sdd_spec', value: 'sdd', label: 'SDD', icon: 'icon-[lucide--scroll-text]', cls: 'text-violet-600 bg-violet-500/10 border-violet-500/20' },
  { key: 'has_coding_plan', value: 'plan', label: '技术方案', icon: 'icon-[lucide--clipboard-list]', cls: 'text-sky-600 bg-sky-500/10 border-sky-500/20' },
  { key: 'has_coding_session', value: 'coding', label: '编码', icon: 'icon-[lucide--code-2]', cls: 'text-emerald-600 bg-emerald-500/10 border-emerald-500/20' },
]

// --- 分面选项（带命中计数；基于全量列表，不随当前筛选变化）---
const capOptions = computed<FacetOption[]>(() =>
  CAP_META.map(c => ({
    value: c.value,
    label: c.label,
    icon: c.icon,
    count: conversations.value.filter(item => item[c.key]).length,
  })),
)
const statusOptions = computed<FacetOption[]>(() =>
  Object.entries(STATUS_META).map(([value, meta]) => ({
    value,
    label: meta.label,
    count: conversations.value.filter(c => c.status === value).length,
  })),
)
const ownerOptions = computed<FacetOption[]>(() => {
  const map = new Map<string, { label: string, count: number }>()
  for (const c of conversations.value) {
    const id = c.owner?.id
    if (!id)
      continue
    const label = c.owner?.display_name || c.owner?.username || id
    const cur = map.get(id)
    if (cur)
      cur.count++
    else
      map.set(id, { label, count: 1 })
  }
  return [...map.entries()]
    .map(([value, { label, count }]) => ({ value, label, count }))
    .sort((a, b) => (b.count ?? 0) - (a.count ?? 0))
})

// --- 客户端多分面过滤（分面内 OR，分面间 AND）---
const filteredConversations = computed<AdminConversationListItem[]>(() => {
  const caps = facets.caps as string[]
  const statuses = new Set(facets.status as string[])
  const owners = new Set(facets.owners as string[])
  return conversations.value.filter((c) => {
    if (caps.length) {
      const hit = caps.some((cap) => {
        const meta = CAP_META.find(m => m.value === cap)
        return meta ? !!c[meta.key] : false
      })
      if (!hit)
        return false
    }
    if (statuses.size && !statuses.has(c.status))
      return false
    if (owners.size && !owners.has(c.owner?.id ?? ''))
      return false
    return true
  })
})

onMounted(() => {
  loadConversations()
})

const columns: ColumnDef<AdminConversationListItem>[] = [
  {
    id: 'owner',
    header: '所属用户',
    cell: ({ row }) => {
      const owner = row.original.owner
      const name = owner?.display_name || owner?.username || '匿名'
      const initial = name.charAt(0).toUpperCase()
      return h('div', { class: 'flex items-center gap-2.5 min-w-0' }, [
        h('div', {
          class: 'w-8 h-8 rounded-full bg-gradient-to-br from-primary/25 to-secondary/15 text-primary flex items-center justify-center text-xs font-semibold shrink-0 ring-1 ring-inset ring-primary/10',
        }, initial),
        h('div', { class: 'min-w-0 leading-tight' }, [
          h('span', { class: 'font-medium text-sm text-foreground block truncate' }, name),
          owner?.username
            ? h('span', { class: 'text-xs text-muted-foreground block truncate' }, `@${owner.username}`)
            : h('span', { class: 'text-xs text-muted-foreground/60' }, '历史 / 匿名'),
        ]),
      ])
    },
    enableSorting: false,
  },
  {
    accessorKey: 'title',
    header: '标题',
    cell: ({ row }) => {
      const title = row.original.title
      return h('div', { class: 'flex items-center gap-2 min-w-0 max-w-[280px]' }, [
        h('span', { class: 'icon-[lucide--message-square-text] text-base text-muted-foreground/50 shrink-0' }),
        title
          ? h('span', { class: 'text-sm text-foreground truncate', title }, title)
          : h('span', { class: 'text-sm italic text-muted-foreground/60' }, '未命名会话'),
      ])
    },
    enableSorting: true,
  },
  {
    id: 'status',
    header: '状态',
    cell: ({ row }) => {
      const meta = statusMeta(row.original.status)
      return h('span', {
        class: `inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border text-xs font-medium whitespace-nowrap ${meta.cls}`,
      }, [
        h('span', { class: `relative flex h-1.5 w-1.5 shrink-0` }, [
          meta.pulse
            ? h('span', { class: `absolute inline-flex h-full w-full rounded-full opacity-75 animate-ping ${meta.dot}` })
            : null,
          h('span', { class: `relative inline-flex h-1.5 w-1.5 rounded-full ${meta.dot}` }),
        ]),
        meta.label,
      ])
    },
    enableSorting: false,
  },
  {
    id: 'capabilities',
    header: '标记',
    cell: ({ row }) => {
      const c = row.original
      const items = CAP_META.filter(m => c[m.key])
      if (items.length === 0)
        return h('span', { class: 'text-xs text-muted-foreground/40' }, '—')
      return h('div', { class: 'flex flex-wrap items-center gap-1' }, items.map(m =>
        h('span', {
          key: m.value,
          class: `inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[0.7rem] font-medium whitespace-nowrap ${m.cls}`,
        }, [
          h('span', { class: `${m.icon} text-[0.8rem]` }),
          m.label,
        ])))
    },
    enableSorting: false,
  },
  {
    accessorKey: 'message_count',
    header: '消息数',
    cell: ({ row }) => h('span', {
      class: 'inline-flex items-center gap-1 text-sm text-muted-foreground tabular-nums',
    }, [
      h('span', { class: 'icon-[lucide--messages-square] text-sm text-muted-foreground/50' }),
      String(row.original.message_count ?? 0),
    ]),
    enableSorting: true,
  },
  {
    accessorKey: 'updated_at',
    header: '更新时间',
    // 相对时间展示，hover 原生 tooltip 显示真实时间
    cell: ({ row }) => h('span', {
      class: 'text-sm text-muted-foreground whitespace-nowrap cursor-default',
      title: formatDate(row.original.updated_at),
    }, formatRelative(row.original.updated_at)),
    enableSorting: true,
  },
  {
    id: 'actions',
    header: '操作',
    cell: ({ row }) => {
      const isForking = forking.value === row.original.id
      return h('div', { class: 'flex justify-end' }, [
        h(Button, {
          variant: 'outline',
          size: 'sm',
          disabled: isForking,
          class: 'h-8 gap-1.5 whitespace-nowrap',
          title: '克隆此会话到我的名下并继续对话',
          onClick: (e: Event) => {
            e.stopPropagation()
            forkToOwn(row.original)
          },
        }, () => [
          h('span', {
            class: isForking
              ? 'icon-[lucide--loader-2] text-sm animate-spin'
              : 'icon-[lucide--git-fork] text-sm',
          }),
          isForking ? '克隆中…' : '克隆',
        ]),
      ])
    },
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
      description="只读浏览全部用户会话，可克隆任意会话到自己名下后继续对话"
    />

    <!-- KPI 概览：数据密集型仪表盘风格，单卡分格避免多张小卡片的拥挤感 -->
    <section class="card overflow-hidden" aria-label="会话数据总览">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-px bg-border/60">
        <div
          v-for="stat in overviewStats"
          :key="stat.title"
          class="bg-card px-5 py-4 flex items-center gap-3.5"
        >
          <div
            class="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            :class="stat.tone"
          >
            <span class="text-xl" :class="stat.icon" aria-hidden="true" />
          </div>
          <div class="min-w-0">
            <p v-if="loading" class="w-12 h-7 bg-muted animate-pulse rounded" />
            <p v-else class="text-2xl font-bold text-foreground tabular-nums leading-none">
              {{ stat.value }}
            </p>
            <p class="text-xs text-muted-foreground mt-1.5 whitespace-nowrap">
              {{ stat.title }}
            </p>
          </div>
        </div>
      </div>
    </section>

    <DataTable
      v-model:pagination="pagination"
      v-model:sorting="sorting"
      v-model:global-filter="globalFilter"
      :data="filteredConversations"
      :columns="columns"
      table-id="admin-conversations-list"
      :loading="loading"
      :on-row-click="openDetail"
      search-placeholder="搜索标题…"
    >
      <template #filters>
        <FacetMultiSelect
          v-model="facets.caps"
          label="能力"
          icon="icon-[lucide--sparkles]"
          :options="capOptions"
          :searchable="false"
        />
        <FacetMultiSelect
          v-model="facets.status"
          label="状态"
          icon="icon-[lucide--circle-dot]"
          :options="statusOptions"
          :searchable="false"
        />
        <FacetMultiSelect
          v-model="facets.owners"
          label="用户"
          icon="icon-[lucide--user-round]"
          :options="ownerOptions"
          search-placeholder="搜索用户…"
          empty-text="无匹配用户"
        />
        <Button
          v-if="activeFacetCount > 0"
          variant="ghost"
          size="sm"
          class="h-9 gap-1 text-muted-foreground hover:text-foreground"
          @click="resetFacets"
        >
          <span class="icon-[lucide--x] text-sm" />
          清除（{{ activeFacetCount }}）
        </Button>
      </template>
    </DataTable>

    <!-- 只读详情对话框：无任何写入入口 -->
    <Dialog v-model:open="detailOpen">
      <DialogScrollContent class="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{{ detail?.title || '会话详情' }}</DialogTitle>
          <DialogDescription>
            只读查看 · 如需续聊请使用「克隆」
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
