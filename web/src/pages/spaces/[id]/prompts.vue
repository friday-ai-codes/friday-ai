<script setup lang="ts">
/**
 * 项目级 Prompt 覆盖页 —— Phase Plan 交付。
 *
 * 路由：/spaces/:id/prompts （由 unplugin-vue-router 文件系统扫描自动注册）
 *
 * 职责：
 * - useRoute 读取:id 参数作为 spaceId
 * - 并发拉取系统级 + 空间级 Prompt 列表（store.loadSpaceList 内部 Promise.all）
 * - DataTable 渲染 mergedSpaceList computed（ 三态合并）
 * - 三态徽章：overridden（空间级已覆盖，default）/ fallback（使用系统级 fallback，outline）
 * / space_only（仅空间级，secondary）
 * - usePermission(spaceId).canEdit 决定操作按钮启用：
 * - canEdit=false：disabled + title="仅空间管理员可操作"（aria-disabled）+ onClick 早拒
 * - canEdit=true + fallback：按钮文案 "创建空间级副本" → 走 PromptEditor mode='create'
 * - canEdit=true + overridden|space_only：按钮文案 "编辑" → 走 mode='edit' +
 * loadDetail(space_prompt.id ?? row.id)
 * - 双层防御（Threat T-）：onClick 内部 if (!canEdit.value) return + 后端 RBAC 兜底
 *
 * 与 Plan PromptEditor 的契约：
 * - v-model:open 双向绑定 sheetOpen
 * -:mode 由 editorMode ref 决定
 * -:space-id 显式透传 spaceId（防 Threat T- 跨租户）
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { MergedSpaceListItem } from '~/stores/prompts'
import { storeToRefs } from 'pinia'
import { h } from 'vue'
import { useRoute } from 'vue-router'
import DataTable from '~/components/common/DataTable.vue'
import PageHeader from '~/components/common/PageHeader.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import PromptEditor from '~/components/prompts/PromptEditor.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { usePermission } from '~/composables/usePermission'
import { usePromptsStore } from '~/stores/prompts'
const route = useRoute
const spaceId = (route.params as { id: string }).id
const store = usePromptsStore
const { mergedSpaceList, loading } = storeToRefs(store)
const { canEdit } = usePermission(spaceId)
const { handleError } = useErrorHandler
const sheetOpen = ref(false)
const editorMode = ref<'edit' | 'create'>('edit')
async function load: Promise<void> {
 try {
 await store.loadSpaceList(spaceId)
 }
 catch (e) {
 handleError(e, '加载 Prompt 列表')
 }
}
onMounted(load)
/**
 * 行点击/按钮点击统一入口：
 * - canEdit=false 双层防御：早拒（即使 disabled 被绕过也无副作用）
 * - fallback：尚未存在空间级副本 → mode='create'，由 PromptEditor 调用方
 * 侧的 store.createPrompt 完成 payload 组装（slug 复用系统级，scope='space'）
 * - overridden：用 space_prompt.id 加载空间级副本详情
 * - space_only：直接用 row.id（即空间级 Prompt 自身的 id）
 */
function openRow(row: MergedSpaceListItem): void {
 if (!canEdit.value)
 return
 if (row.status === 'fallback') {
 editorMode.value = 'create'
 store.clearCurrent
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
const columns: ColumnDef<MergedSpaceListItem> = [
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
 return h(Badge, { variant: meta.variant }, => meta.label)
 },
 },
 {
 id: 'actions',
 header: '操作',
 enableSorting: false,
 cell: ({ row }) => {
 const s = row.original.status
 const label = s === 'fallback' ? '创建空间级副本': '编辑'
 const editable = canEdit.value
 return h(
 Button,
 {
 'size': 'sm',
 'variant': 'outline',
 'disabled': !editable,
 'title': editable ? '': '仅空间管理员可操作',
 'aria-disabled': !editable,
 'onClick': => openRow(row.original),
 },
 => label,
 )
 },
 },
]
</script>
<template>
 <PageContainer show-background>
 <PageHeader
 icon="lucide--file-text"
 title="Prompt 覆盖"
 description="空间级提示词覆盖与系统级 fallback"
 />
 <DataTable:data="mergedSpaceList":columns="columns"
 table-id="space-prompts-list":loading="loading"
 />
 <PromptEditor
 v-model:open="sheetOpen":mode="editorMode":space-id="spaceId"
 />
 </PageContainer>
</template>
