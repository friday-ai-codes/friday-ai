<script setup lang="ts">
import { onMounted, ref as vueRef } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
import { useRouter } from 'vue-router'
import client from '~/api/client'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectGroup,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { Textarea } from '~/components/ui/textarea'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { getNodeDefinition } from '~/types/workflow/registry'
const emit = defineEmits<{
 close:
 confirm: [data: { name: string, description?: string, project_id: string }]
 cancel:
 closed:
}>
const router = useRouter
const workflowsStore = useWorkflowsStore
const projectsStore = useProjectsStore
const { handleError } = useErrorHandler
const { success, error: showError } = useToast
// ============================================================================
// Tabs
// ============================================================================
type TabType = 'blank' | 'import'
const activeTab = vueRef<TabType>('blank')
// ============================================================================
// Form (blank tab)
// ============================================================================
const form = reactive({
 name: '',
 description: '',
 project_id: '',
})
// ============================================================================
// Template
// ============================================================================
interface WorkflowTemplate {
 template_id: string
 name: string
 description: string
 version: string
}
const templates = vueRef<WorkflowTemplate>
const selectedTemplateId = vueRef<string | null>(null)
const templatesLoading = vueRef(false)
async function fetchTemplates {
 templatesLoading.value = true
 try {
 templates.value = await client.get<WorkflowTemplate>('/workflows/templates/')
 }
 catch {
 templates.value =
 }
 finally {
 templatesLoading.value = false
 }
}
function selectTemplate(id: string | null) {
 selectedTemplateId.value = id
 if (id) {
 const tpl = templates.value.find(t => t.template_id === id)
 if (tpl && !form.name) {
 form.name = tpl.name
 }
 }
}
const errors = reactive({
 name: '',
 project_id: '',
})
function validate: boolean {
 errors.name = ''
 errors.project_id = ''
 if (!form.name.trim) {
 errors.name = '请输入工作流名称'
 }
 if (!form.project_id) {
 errors.project_id = '请选择所属项目'
 }
 return !errors.name && !errors.project_id
}
// ============================================================================
// JSON Import
// ============================================================================
interface ParsedWorkflow {
 name: string
 description: string
 icon: string
 trigger_type: string
 trigger_config: Record<string, unknown>
 nodes: unknown
 edges: unknown
}
const importFile = vueRef<File | null>(null)
const importPreview = vueRef<ParsedWorkflow | null>(null)
const importErrors = vueRef<string>
const importWarnings = vueRef<string>
const isDragOver = vueRef(false)
const fileInputRef = vueRef<HTMLInputElement | null>(null)
function handleFileSelect(event: Event) {
 const input = event.target as HTMLInputElement
 if (input.files && input.files[0]) {
 parseWorkflowFile(input.files[0])
 }
}
function handleDrop(event: DragEvent) {
 event.preventDefault
 isDragOver.value = false
 if (event.dataTransfer?.files[0]) {
 parseWorkflowFile(event.dataTransfer.files[0])
 }
}
function handleDragOver(event: DragEvent) {
 event.preventDefault
 isDragOver.value = true
}
function handleDragLeave {
 isDragOver.value = false
}
function parseWorkflowFile(file: File) {
 importFile.value = file
 importPreview.value = null
 importErrors.value =
 importWarnings.value =
 const reader = new FileReader
 reader.onload = (e) => {
 try {
 const text = e.target?.result as string
 const data = JSON.parse(text) as Record<string, unknown>
 // Validate required fields
 if (!data.name || typeof data.name !== 'string') {
 importErrors.value.push('缺少必需字段: name')
 }
 if (!Array.isArray(data.nodes)) {
 importErrors.value.push('缺少必需字段: nodes（必须为数组）')
 }
 if (!Array.isArray(data.edges)) {
 importErrors.value.push('缺少必需字段: edges（必须为数组）')
 }
 if (importErrors.value.length > 0) {
 return
 }
 const nodes = data.nodes as Array<Record<string, unknown>>
 const edges = data.edges as Array<Record<string, unknown>>
 // Validate node types
 const unknownTypes: string =
 for (const node of nodes) {
 const nodeType = node.node_type as string
 if (nodeType && !getNodeDefinition(nodeType)) {
 unknownTypes.push(nodeType)
 }
 }
 if (unknownTypes.length > 0) {
 importWarnings.value.push(`未知节点类型: ${[...new Set(unknownTypes)].join(', ')}`)
 }
 importPreview.value = {
 name: data.name as string,
 description: (data.description as string) || '',
 icon: (data.icon as string) || '',
 trigger_type: (data.trigger_type as string) || 'manual',
 trigger_config: (data.trigger_config as Record<string, unknown>) || {},
 nodes,
 edges,
 }
 // Pre-fill form name if empty
 if (!form.name) {
 form.name = data.name as string
 }
 }
 catch {
 importErrors.value.push('JSON 解析失败: 文件不是有效的 JSON 格式')
 }
 }
 reader.readAsText(file)
}
function clearImport {
 importFile.value = null
 importPreview.value = null
 importErrors.value =
 importWarnings.value =
 if (fileInputRef.value) {
 fileInputRef.value.value = ''
 }
}
// ============================================================================
// Submit
// ============================================================================
const submitting = vueRef(false)
async function handleSubmit {
 if (activeTab.value === 'blank') {
 await handleBlankSubmit
 }
 else {
 await handleImportSubmit
 }
}
async function handleBlankSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 let workflow
 if (selectedTemplateId.value) {
 workflow = await client.post<{ id: string }>('/workflows/from-template/', {
 template_id: selectedTemplateId.value,
 project_id: form.project_id,
 name: form.name,
 description: form.description || undefined,
 })
 }
 else {
 workflow = await workflowsStore.createWorkflow({
 name: form.name,
 description: form.description || undefined,
 project: form.project_id,
 trigger_type: 'manual',
 is_active: true,
 })
 }
 success('创建成功', '工作流已创建')
 emit('close')
 emit('confirm', { name: form.name, description: form.description, project_id: form.project_id })
 if (workflow?.id) {
 router.push(`/workflows/${workflow.id}`)
 }
 }
 catch (e: unknown) {
 handleError(e, '创建工作流')
 }
 finally {
 submitting.value = false
 }
}
async function handleImportSubmit {
 if (!importPreview.value) {
 showError('请先选择 JSON 文件')
 return
 }
 if (importErrors.value.length > 0) {
 showError('文件验证失败', importErrors.value[0])
 return
 }
 if (!form.project_id) {
 errors.project_id = '请选择所属项目'
 showError('请选择所属项目')
 return
 }
 submitting.value = true
 try {
 // Transform edges: backend expects source_node_id/target_node_id
 const transformedEdges = importPreview.value.edges.map((edge: any) => ({
 source_node_id: edge.source_node || edge.source_node_id,
 target_node_id: edge.target_node || edge.target_node_id,
 source_handle: edge.source_handle || 'default',
 target_handle: edge.target_handle || 'default',
 condition: edge.condition || null,
 label: edge.label || '',
 style: edge.style || {},
 }))
 // Transform nodes: strip id/short_id to let backend regenerate them
 const transformedNodes = importPreview.value.nodes.map((node: any) => ({
 node_type: node.node_type,
 name: node.name,
 description: node.description || '',
 position_x: node.position_x ?? 0,
 position_y: node.position_y ?? 0,
 config: node.config || {},
 on_error: node.on_error || 'abort',
 retry_times: node.retry_times ?? 0,
 retry_delay: node.retry_delay ?? 5,
 node_timeout_seconds: node.node_timeout_seconds ?? null,
 fallback_values: node.fallback_values ?? null,
 run_condition: node.run_condition ?? null,
 metadata: node.metadata ?? {},
 }))
 const workflow = await client.post<{ id: string }>('/workflows/', {
 name: form.name || importPreview.value.name,
 description: form.description || importPreview.value.description || undefined,
 project: form.project_id,
 trigger_type: importPreview.value.trigger_type || 'manual',
 trigger_config: importPreview.value.trigger_config || {},
 nodes: transformedNodes,
 edges: transformedEdges,
 from_import: true,
 })
 success('导入成功', '工作流已创建')
 emit('close')
 emit('confirm', { name: form.name, description: form.description, project_id: form.project_id })
 if (workflow?.id) {
 router.push(`/workflows/${workflow.id}/edit`)
 }
 }
 catch (e: unknown) {
 handleError(e, '导入工作流')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('close')
 emit('cancel')
}
// ============================================================================
// Lifecycle
// ============================================================================
onMounted( => {
 projectsStore.fetchProjects
 fetchTemplates
})
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10">
 <span class="icon-[lucide--git-branch-plus] text-xl text-purple-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 新建工作流
 </h3>
 <p class="text-sm text-muted-foreground">
 从模板、空白或 JSON 导入创建工作流
 </p>
 </div>
 </div>
 <button
 type="button"
 class=" rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
 @click="handleCancel"
 >
 <span class="icon-[lucide--x] text-lg" />
 </button>
 </div>
 <!-- Tabs -->
 <div class="px-6 pt-4 shrink-0">
 <div class="flex gap-1 rounded-xl bg-muted/50 border border-border/30">
 <button
 type="button"
 class="flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-all":class="activeTab === 'blank' ? 'bg-card text-foreground shadow-sm': 'text-muted-foreground hover:text-foreground'"
 @click="activeTab = 'blank'"
 >
 新建空白
 </button>
 <button
 type="button"
 class="flex-1 px-3 py-2 text-sm font-medium rounded-lg transition-all":class="activeTab === 'import' ? 'bg-card text-foreground shadow-sm': 'text-muted-foreground hover:text-foreground'"
 @click="activeTab = 'import'"
 >
 从 JSON 导入
 </button>
 </div>
 </div>
 <!-- Body -->
 <form class="px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
 <!-- ====== Blank Tab ====== -->
 <template v-if="activeTab === 'blank'">
 <!-- 模板选择 -->
 <div v-if="templates.length > 0 || templatesLoading" class="space-y-2">
 <Label class="text-foreground">选择模板</Label>
 <div class="grid grid-cols-2 gap-2">
 <!-- 空白工作流 -->
 <button
 type="button"
 class="flex flex-col items-start gap-1.5 rounded-xl border text-left transition-all duration-150":class="[selectedTemplateId === null ? 'border-primary bg-primary/5 ring-1 ring-primary/30': 'border-border/50 hover:border-border hover:bg-muted/30']"
 @click="selectTemplate(null)"
 >
 <div class="flex items-center gap-2">
 <span
 class="icon-[lucide--file-plus] text-base":class="selectedTemplateId === null ? 'text-primary': 'text-muted-foreground'"
 />
 <span class="text-sm font-medium">空白工作流</span>
 </div>
 <p class="text-[11px] text-muted-foreground leading-snug">
 从零开始搭建
 </p>
 </button>
 <!-- 模板列表 -->
 <button
 v-for="tpl in templates":key="tpl.template_id"
 type="button"
 class="flex flex-col items-start gap-1.5 rounded-xl border text-left transition-all duration-150":class="[selectedTemplateId === tpl.template_id ? 'border-primary bg-primary/5 ring-1 ring-primary/30': 'border-border/50 hover:border-border hover:bg-muted/30']"
 @click="selectTemplate(tpl.template_id)"
 >
 <div class="flex items-center gap-2">
 <span
 class="icon-[lucide--workflow] text-base":class="selectedTemplateId === tpl.template_id ? 'text-primary': 'text-muted-foreground'"
 />
 <span class="text-sm font-medium">{{ tpl.name }}</span>
 </div>
 <p class="text-[11px] text-muted-foreground leading-snug line-clamp-2">
 {{ tpl.description }}
 </p>
 </button>
 </div>
 <div v-if="templatesLoading" class="flex items-center justify-center py-2">
 <span class="icon-[lucide--loader-circle] animate-spin text-muted-foreground mr-2" />
 <span class="text-xs text-muted-foreground">加载模板...</span>
 </div>
 </div>
 </template>
 <!-- ====== Import Tab ====== -->
 <template v-if="activeTab === 'import'">
 <div class="space-y-3">
 <!-- File drop zone -->
 <div
 class="relative border-2 border-dashed rounded-xl text-center transition-colors cursor-pointer":class="[
 isDragOver
 ? 'border-primary bg-primary/5': importErrors.length > 0
 ? 'border-destructive bg-destructive/5': importPreview
 ? 'border-green-500 bg-green-500/5': 'border-border/50 hover:border-border hover:bg-muted/20',
 ]"
 @click="fileInputRef?.click"
 @drop="handleDrop"
 @dragover="handleDragOver"
 @dragleave="handleDragLeave"
 >
 <input
 ref="fileInputRef"
 type="file"
 accept=".json"
 class="hidden"
 @change="handleFileSelect"
 >
 <span
 class="icon-[lucide--upload] text-2xl mx-auto mb-2 block":class="importErrors.length > 0 ? 'text-destructive': importPreview ? 'text-green-500': 'text-muted-foreground'"
 />
 <p class="text-sm font-medium text-foreground">
 {{ importFile ? importFile.name: '点击或拖拽 JSON 文件到此处' }}
 </p>
 <p class="text-xs text-muted-foreground mt-1">
 支持 .json 格式的工作流定义文件
 </p>
 </div>
 <!-- Clear button -->
 <div v-if="importFile" class="flex justify-end">
 <button
 type="button"
 class="text-xs text-muted-foreground hover:text-foreground transition-colors"
 @click.stop="clearImport"
 >
 清除文件
 </button>
 </div>
 <!-- Errors -->
 <div v-if="importErrors.length > 0" class="space-y-1">
 <div
 v-for="(err, idx) in importErrors":key="idx"
 class="flex items-center gap-1.5 text-sm text-destructive"
 >
 <span class="icon-[lucide--alert-circle] text-xs" />
 {{ err }}
 </div>
 </div>
 <!-- Warnings -->
 <div v-if="importWarnings.length > 0" class="space-y-1">
 <div
 v-for="(warn, idx) in importWarnings":key="idx"
 class="flex items-center gap-1.5 text-sm text-amber-600"
 >
 <span class="icon-[lucide--alert-triangle] text-xs" />
 {{ warn }}
 </div>
 </div>
 <!-- Preview -->
 <div v-if="importPreview" class="rounded-xl border border-border/50 bg-muted/20 space-y-2">
 <div class="flex items-center gap-2 text-sm">
 <span class="icon-[lucide--check-circle] text-green-500" />
 <span class="font-medium">解析成功</span>
 </div>
 <div class="grid grid-cols-2 gap-2 text-xs">
 <div class="flex items-center gap-1.5">
 <span class="text-muted-foreground">节点数:</span>
 <span class="font-mono font-medium">{{ importPreview.nodes.length }}</span>
 </div>
 <div class="flex items-center gap-1.5">
 <span class="text-muted-foreground">边数:</span>
 <span class="font-mono font-medium">{{ importPreview.edges.length }}</span>
 </div>
 </div>
 <div v-if="importPreview.nodes.length > 0" class="flex flex-wrap gap-1">
 <span
 v-for="nodeType in [...new Set(importPreview.nodes.map((n: any) => n.node_type).filter(Boolean))]":key="nodeType"
 class="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium"
 >
 {{ nodeType }}
 </span>
 </div>
 </div>
 </div>
 </template>
 <!-- 工作流名称 -->
 <div class="space-y-2">
 <Label for="name" class="flex items-center gap-1 text-foreground">
 工作流名称
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：自动部署流程"
 class="":class="{ 'border-destructive': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.name }}
 </p>
 </div>
 <!-- 所属项目 -->
 <div class="space-y-2">
 <Label class="flex items-center gap-1 text-foreground">
 所属项目
 <span class="text-destructive">*</span>
 </Label>
 <Select v-model="form.project_id">
 <SelectTrigger:class="{ 'border-destructive': errors.project_id }">
 <SelectValue placeholder="选择所属项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectGroup>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectGroup>
 </SelectContent>
 </Select>
 <p v-if="errors.project_id" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.project_id }}
 </p>
 <p v-if="projectsStore.projects.length === 0 && !projectsStore.loading" class="text-sm text-yellow-600 flex items-center gap-1">
 <span class="icon-[lucide--alert-triangle]" />
 暂无可用项目，请先创建项目
 </p>
 </div>
 <!-- 工作流描述 -->
 <div class="space-y-2">
 <Label for="description" class="text-foreground">描述</Label>
 <Textarea
 id="description"
 v-model="form.description"
 placeholder="工作流的简要描述..."
 rows="3"
 class="resize-none"
 />
 </div>
 <!-- Footer -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting || (projectsStore.projects.length === 0)">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--plus] mr-2" />
 {{ activeTab === 'import' ? '导入': '创建' }}
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
