<script setup lang="ts">
import { onMounted } from 'vue'
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
const { success } = useToast
// ============================================================================
// Form
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
const templates = ref<WorkflowTemplate>
const selectedTemplateId = ref<string | null>(null)
const templatesLoading = ref(false)
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
// Submit
// ============================================================================
const submitting = ref(false)
async function handleSubmit {
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
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-lg w-full mx-4"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10">
 <span class="icon-[lucide--git-branch-plus] text-xl text-purple-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 新建工作流
 </h3>
 <p class="text-sm text-muted-foreground">
 从模板开始或创建空白工作流
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
 <!-- Body -->
 <form class="px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
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
 创建
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
