<script setup lang="ts">
import { onMounted } from 'vue'
import { VueFinalModal } from 'vue-final-modal'
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
const emit = defineEmits<{
 close:
 confirm: [data: { name: string, description?: string, project_id: string }]
 cancel:
 closed:
}>
const workflowsStore = useWorkflowsStore
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: '',
 description: '',
 project_id: '',
})
// 表单验证
const errors = reactive({
 name: '',
 project_id: '',
})
// 加载项目列表
onMounted( => {
 projectsStore.fetchProjects
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
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 await workflowsStore.createWorkflow({
 name: form.name,
 description: form.description || undefined,
 project: form.project_id,
 trigger_type: 'manual', // 默认为手动触发
 is_active: true,
 })
 success('创建成功', '工作流已创建')
 emit('close')
 emit('confirm', { name: form.name, description: form.description, project_id: form.project_id })
 }
 catch (e) {
 showError('创建失败', e instanceof Error ? e.message: '无法创建工作流')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('close')
 emit('cancel')
}
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
 <div class=".5 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/10">
 <span class="icon-[lucide--git-branch-plus] text-xl text-purple-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 新建工作流
 </h3>
 <p class="text-sm text-muted-foreground">
 创建一个新的工作流来自动化您的任务
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
