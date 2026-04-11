<script setup lang="ts">
/**
 * 项目级 Prompt 覆盖页 —— Phase Plan 交付。
 *
 * 路由：/projects/:id/prompts （由 unplugin-vue-router 文件系统扫描自动注册）
 *
 * 职责：
 * - useRoute 读取:id 参数作为 projectId
 * - 并发拉取系统级 + 项目级 Prompt 列表（store.loadProjectList 内部 Promise.all）
 * - DataTable 渲染 mergedProjectList computed（ 三态合并）
 * - 三态徽章：overridden（项目级已覆盖，default）/ fallback（使用系统级 fallback，outline）
 * / project_only（仅项目级，secondary）
 * - usePermission(projectId).canEdit 决定操作按钮启用：
 * - canEdit=false：disabled + title="仅项目管理员可操作"（aria-disabled）+ onClick 早拒
 * - canEdit=true + fallback：按钮文案 "创建项目级副本" → 走 PromptEditor mode='create'
 * - canEdit=true + overridden|project_only：按钮文案 "编辑" → 走 mode='edit' +
 * loadDetail(project_prompt.id ?? row.id)
 * - 双层防御（Threat T-）：onClick 内部 if (!canEdit.value) return + 后端 RBAC 兜底
 *
 * 与 Plan PromptEditor 的契约：
 * - v-model:open 双向绑定 sheetOpen
 * -:mode 由 editorMode ref 决定
 * -:project-id 显式透传 projectId（防 Threat T- 跨租户）
 */
import type { ColumnDef } from '@tanstack/vue-table'
import type { MergedProjectListItem } from '~/stores/prompts'
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
const projectId = (route.params as { id: string }).id
const store = usePromptsStore
const { mergedProjectList, loading } = storeToRefs(store)
const { canEdit } = usePermission(projectId)
const { handleError } = useErrorHandler
const sheetOpen = ref(false)
const editorMode = ref<'edit' | 'create'>('edit')
async function load: Promise<void> {
 try {
 await store.loadProjectList(projectId)
 }
 catch (e) {
 handleError(e, '加载 Prompt 列表')
 }
}
onMounted(load)
/**
 * 行点击/按钮点击统一入口：
 * - canEdit=false 双层防御：早拒（即使 disabled 被绕过也无副作用）
 * - fallback：尚未存在项目级副本 → mode='create'，由 PromptEditor 调用方
 * 侧的 store.createPrompt 完成 payload 组装（slug 复用系统级，scope='project'）
 * - overridden：用 project_prompt.id 加载项目级副本详情
 * - project_only：直接用 row.id（即项目级 Prompt 自身的 id）
 */
function openRow(row: MergedProjectListItem): void {
 if (!canEdit.value)
 return
 if (row.status === 'fallback') {
 editorMode.value = 'create'
 store.clearCurrent
 }
 else {
 editorMode.value = 'edit'
 const targetId = row.project_prompt?.id ?? row.id
 store.loadDetail(targetId).catch((e: unknown) => handleError(e, '加载 Prompt 详情'))
 store.loadVersions(targetId).catch((e: unknown) => handleError(e, '加载版本历史'))
 }
 sheetOpen.value = true
}
const STATUS_BADGE: Record<
 MergedProjectListItem['status'],
 { variant: 'default' | 'outline' | 'secondary', label: string }
> = {
 overridden: { variant: 'default', label: '项目级已覆盖' },
 fallback: { variant: 'outline', label: '使用系统级 fallback' },
 project_only: { variant: 'secondary', label: '仅项目级' },
}
const columns: ColumnDef<MergedProjectListItem> = [
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
 const label = s === 'fallback' ? '创建项目级副本': '编辑'
 const editable = canEdit.value
 return h(
 Button,
 {
 'size': 'sm',
 'variant': 'outline',
 'disabled': !editable,
 'title': editable ? '': '仅项目管理员可操作',
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
 description="项目级提示词覆盖与系统级 fallback"
 />
 <DataTable:data="mergedProjectList":columns="columns"
 table-id="project-prompts-list":loading="loading"
 />
 <PromptEditor
 v-model:open="sheetOpen":mode="editorMode":project-id="projectId"
 />
 </PageContainer>
</template>
