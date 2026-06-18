<script setup lang="ts">
/**
 * 系统级 Prompt 管理页 —— 交付。
 *
 * 路由：/admin/prompts （由 unplugin-vue-router 文件系统扫描自动注册）
 * 守卫：definePage requiresAdmin = true，深链拦截非系统管理员
 *
 * 职责：
 *   - 拉取系统级 Prompt 列表（loadSystemList，支持 category 二次过滤）
 *   - DataTable 5 列：slug / title / category / updated_at / is_builtin
 *   - category 下拉过滤 (#filters slot) → watch 触发 store.loadSystemList(category)
 *   - "新建 Prompt" 按钮 → 打开 PromptEditor Sheet（mode='create'）
 *   - 行点击 → store.loadDetail + loadVersions → 打开 PromptEditor Sheet（mode='edit'）
 *   - 抽屉关闭由 PromptEditor 自身的 update:open 事件 + 内部脏检测拦截
 *
 * 与 -04 PromptEditor 的契约：
 *   - v-model:open 双向绑定 sheetOpen
 *   - :mode 由 editorMode ref 决定
 *   - :project-id 不传（系统级页面）
 *
 * 路由元信息（D-08 RBAC）：requiresAdmin: true → 全局导航守卫拦截非 admin
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { PromptCategory, PromptListItem } from '~/types/prompts'
import { storeToRefs } from 'pinia'
import { h } from 'vue'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import PromptEditor from '~/components/prompts/PromptEditor.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useTableUrlState } from '~/composables/useTableUrlState'
import { usePromptsStore } from '~/stores/prompts'

definePage({ meta: { requiresAdmin: true } })

const store = usePromptsStore()
const { systemList, loading } = storeToRefs(store)
const { handleError } = useErrorHandler()

// category 过滤（前端状态 → 触发后端二次 fetch，符合 D-02 决策）；
// 连同搜索/排序/分页/每页大小一并持久化到 URL（刷新可恢复）
const { pagination, sorting, globalFilter, facets } = useTableUrlState({
  facets: { category: { type: 'single', default: 'all' } },
})
const categoryFilter = computed<PromptCategory | 'all'>({
  get: () => facets.category as PromptCategory | 'all',
  set: v => (facets.category = v),
})

// Sheet 状态
const sheetOpen = ref(false)
const editorMode = ref<'edit' | 'create'>('edit')

// 分类文案映射（与 UI-SPEC §Copywriting 徽章表对齐）
const CATEGORY_LABEL: Record<PromptCategory, string> = {
  chat_agent: '对话',
  ai_node: 'AI 节点',
  aux_model: '辅助小模型',
  feishu_bot: '飞书群聊',
  repo_summary: '仓库描述',
}
const CATEGORY_VARIANT: Record<PromptCategory, 'default' | 'secondary'> = {
  chat_agent: 'default',
  ai_node: 'secondary',
  aux_model: 'secondary',
  feishu_bot: 'secondary',
  repo_summary: 'secondary',
}

async function load(): Promise<void> {
  try {
    await store.loadSystemList(
      categoryFilter.value === 'all' ? undefined : categoryFilter.value,
    )
  }
  catch (e) {
    handleError(e, '加载系统级 Prompt 列表')
  }
}

onMounted(load)
watch(categoryFilter, load)

function openRow(row: PromptListItem): void {
  editorMode.value = 'edit'
  store.loadDetail(row.id).catch((e: unknown) => handleError(e, '加载 Prompt 详情'))
  store.loadVersions(row.id).catch((e: unknown) => handleError(e, '加载版本历史'))
  sheetOpen.value = true
}

function openCreate(): void {
  editorMode.value = 'create'
  store.clearCurrent()
  sheetOpen.value = true
}

const columns: ColumnDef<PromptListItem>[] = [
  {
    accessorKey: 'slug',
    header: 'Slug',
    enableSorting: true,
    cell: ({ row }) =>
      h('code', { class: 'text-xs font-mono text-foreground' }, row.original.slug),
  },
  {
    accessorKey: 'title',
    header: '标题',
    enableSorting: true,
  },
  {
    accessorKey: 'category',
    header: '分类',
    enableSorting: true,
    cell: ({ row }) =>
      h(
        Badge,
        { variant: CATEGORY_VARIANT[row.original.category] },
        () => CATEGORY_LABEL[row.original.category],
      ),
  },
  {
    accessorKey: 'updated_at',
    header: '更新时间',
    enableSorting: true,
    cell: ({ row }) =>
      h(
        'span',
        { class: 'text-xs text-muted-foreground' },
        new Date(row.original.updated_at).toLocaleString('zh-CN'),
      ),
  },
  {
    id: 'is_builtin',
    header: '',
    enableSorting: false,
    cell: ({ row }) =>
      row.original.is_builtin
        ? h(Badge, { variant: 'secondary' }, () => '系统内置')
        : null,
  },
]
</script>

<template>
  <PageContainer show-background>
    <PageHeader
      icon="lucide--file-text"
      title="Prompt 管理"
      description="系统级提示词编辑与版本管理"
    >
      <template #actions>
        <Button @click="openCreate">
          新建 Prompt
        </Button>
      </template>
    </PageHeader>

    <DataTable
      v-model:pagination="pagination"
      v-model:sorting="sorting"
      v-model:global-filter="globalFilter"
      :data="systemList"
      :columns="columns"
      table-id="admin-prompts-list"
      :loading="loading"
      search-placeholder="搜索 slug、标题…"
      :on-row-click="openRow"
    >
      <template #filters>
        <Select v-model="categoryFilter">
          <SelectTrigger class="w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">
              全部分类
            </SelectItem>
            <SelectItem value="chat_agent">
              对话
            </SelectItem>
            <SelectItem value="ai_node">
              AI 节点
            </SelectItem>
            <SelectItem value="aux_model">
              辅助小模型
            </SelectItem>
            <SelectItem value="feishu_bot">
              飞书群聊
            </SelectItem>
            <SelectItem value="repo_summary">
              仓库描述
            </SelectItem>
          </SelectContent>
        </Select>
      </template>
    </DataTable>

    <PromptEditor
      v-model:open="sheetOpen"
      :mode="editorMode"
    />
  </PageContainer>
</template>
