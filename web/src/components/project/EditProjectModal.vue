<script setup lang="ts">
import { VueFinalModal } from 'vue-final-modal'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
const props = defineProps<{
 projectId: string
}>
const emit = defineEmits<{
 confirm: [project: any]
 cancel:
 closed:
}>
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: '',
 description: '',
 feishu_project_key: '',
})
// 表单验证
const errors = reactive({
 name: '',
})
function validate: boolean {
 errors.name = ''
 if (!form.name.trim) {
 errors.name = '请输入项目名称'
 }
 return !errors.name
}
// 加载状态
const loading = ref(false)
const submitting = ref(false)
// 获取项目详情
async function fetchProjectData {
 loading.value = true
 try {
 const project = await projectsStore.fetchProject(props.projectId)
 if (project) {
 form.name = project.name
 form.description = project.description || ''
 form.feishu_project_key = project.feishu_project_key || ''
 }
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取项目详情')
 emit('cancel')
 }
 finally {
 loading.value = false
 }
}
onMounted( => {
 fetchProjectData
})
// 提交表单
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 const project = await projectsStore.updateProject(props.projectId, {
 name: form.name,
 description: form.description || undefined,
 feishu_project_key: form.feishu_project_key || null,
 })
 success('更新成功', '项目已更新')
 emit('confirm', project)
 }
 catch (e) {
 showError('更新失败', e instanceof Error ? e.message: '无法更新项目')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
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
 <div class=".5 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10">
 <span class="icon-[lucide--pencil] text-xl text-blue-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 编辑项目
 </h3>
 <p class="text-sm text-muted-foreground">
 修改项目基本信息和配置
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
 <div v-if="loading" class=" flex justify-center items-center">
 <span class="icon-[lucide--loader-circle] text-3xl animate-spin text-muted-foreground" />
 </div>
 <form v-else class="px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
 <!-- 项目名称 -->
 <div class="space-y-2">
 <Label for="name" class="flex items-center gap-1 text-foreground">
 项目名称
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：智课项目"
 class="":class="{ 'border-destructive': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.name }}
 </p>
 </div>
 <!-- 项目描述 -->
 <div class="space-y-2">
 <Label for="description" class="text-foreground">项目描述</Label>
 <Textarea
 id="description"
 v-model="form.description"
 placeholder="项目的简要描述..."
 rows="3"
 class="resize-none"
 />
 </div>
 <!-- 飞书项目 Key -->
 <div class="space-y-2">
 <Label for="feishu_project_key" class="flex items-center gap-2 text-foreground">
 飞书项目 Key
 <span class="text-xs text-muted-foreground font-normal">(可选)</span>
 </Label>
 <Input
 id="feishu_project_key"
 v-model="form.feishu_project_key"
 placeholder="例如：project_key"
 class=""
 />
 <p class="text-xs text-muted-foreground">
 用于飞书项目管理 API 调用
 </p>
 </div>
 <!-- Footer -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存修改
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
