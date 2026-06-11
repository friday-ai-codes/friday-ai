<script setup lang="ts">
/**
 * SpacePromptsModal — 空间级 Prompt 覆盖管理弹窗
 *
 * 把原独立路由页 `pages/spaces/[id]/prompts.vue` 的全部功能迁入空间详情页弹窗：
 *   - 弹窗打开时并发拉取系统级 + 空间级 Prompt 列表（store.loadSpaceList 内部 Promise.all）
 *   - DataTable 渲染 mergedSpaceList computed（三态合并）
 *   - 三态徽章：overridden（空间级已覆盖，default）/ fallback（使用系统级 fallback，outline）
 *     / space_only（仅空间级，secondary）
 *   - usePermission(spaceId).canEdit 决定操作按钮启用：
 *     - canEdit=false：disabled + title="仅空间管理员可操作"（aria-disabled）+ onClick 早拒
 *     - canEdit=true + fallback：按钮文案 "创建空间级副本" → 走 PromptEditor mode='create'
 *     - canEdit=true + overridden|space_only：按钮文案 "编辑" → 走 mode='edit' +
 *       loadDetail(space_prompt.id ?? row.id)
 *   - 双层防御：onClick 内部 if (!canEdit.value) return + 后端 RBAC 兜底
 *
 * 与 PromptEditor 的契约：
 *   - v-model:open 双向绑定 sheetOpen
 *   - :mode 由 editorMode ref 决定
 *   - :space-id 显式透传 spaceId（防跨租户）
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { MergedSpaceListItem } from '~/stores/prompts'
import { storeToRefs } from 'pinia'
import { h } from 'vue'
import DataTable from '~/components/common/DataTable.vue'
import PromptEditor from '~/components/prompts/PromptEditor.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'
import { usePromptsStore } from '~/stores/prompts'

const props = defineProps<{
  spaceId: string
}>()

const open = defineModel<boolean>('open', { default: false })

const store = usePromptsStore()
const { mergedSpaceList, loading } = storeToRefs(store)
const { canEdit } = usePermission(props.spaceId)
const { handleError } = useErrorHandler()

const sheetOpen = ref(false)
const editorMode = ref<'edit' | 'create'>('edit')

async function load(): Promise<void> {
  try {
    await store.loadSpaceList(props.spaceId)
  }
  catch (e) {
    handleError(e, '加载 Prompt 列表')
  }
}

// 弹窗打开时加载列表
watch(open, (isOpen) => {
  if (isOpen)
    load()
}, { immediate: true })

/**
 * 行点击/按钮点击统一入口：
 *   - canEdit=false 双层防御：早拒（即使 disabled 被绕过也无副作用）
 *   - fallback：尚未存在空间级副本 → mode='create'
 *   - overridden：用 space_prompt.id 加载空间级副本详情
 *   - space_only：直接用 row.id（即空间级 Prompt 自身的 id）
 */
function openRow(row: MergedSpaceListItem): void {
  if (!canEdit.value)
    return
  if (row.status === 'fallback') {
    editorMode.value = 'create'
    store.clearCurrent()
  }
  else {
    editorMode.value = 'edit'
    const targetId = row.space_prompt?.id ?? row.id
    store.loadDetail(targetId).catch((e: unknown) => handleError(e, '加载 Prompt 详情'))
    store.loadVersions(targetId).catch((e: unknown) => handleError(e, '加载版本历史'))
  }
  sheetOpen.value = true
}

const STATUS_BADGE: Record<
  MergedSpaceListItem['status'],
  { variant: 'default' | 'outline' | 'secondary', label: string }
> = {
  overridden: { variant: 'default', label: '空间级已覆盖' },
  fallback: { variant: 'outline', label: '使用系统级 fallback' },
  space_only: { variant: 'secondary', label: '仅空间级' },
}

const columns: ColumnDef<MergedSpaceListItem>[] = [
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
    id: 'status',
    header: '覆盖状态',
    enableSorting: false,
    cell: ({ row }) => {
      const meta = STATUS_BADGE[row.original.status]
      return h(Badge, { variant: meta.variant }, () => meta.label)
    },
  },
  {
    id: 'actions',
    header: '操作',
    enableSorting: false,
    cell: ({ row }) => {
      const s = row.original.status
      const label = s === 'fallback' ? '创建空间级副本' : '编辑'
      const editable = canEdit.value
      return h(
        Button,
        {
          'size': 'sm',
          'variant': 'outline',
          'disabled': !editable,
          'title': editable ? '' : '仅空间管理员可操作',
          'aria-disabled': !editable,
          'onClick': () => openRow(row.original),
        },
        () => label,
      )
    },
  },
]
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="sm:max-w-4xl max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <span class="icon-[lucide--file-text] text-primary" />
          Prompt 覆盖
        </DialogTitle>
        <DialogDescription>
          空间级提示词覆盖与系统级 fallback
        </DialogDescription>
      </DialogHeader>

      <DataTable
        :data="mergedSpaceList"
        :columns="columns"
        table-id="space-prompts-list"
        :loading="loading"
      />

      <PromptEditor
        v-model:open="sheetOpen"
        :mode="editorMode"
        :space-id="spaceId"
      />
    </DialogContent>
  </Dialog>
</template>
