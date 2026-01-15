<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
const projectId = route.params.id as string
useHead({
 title: '编辑项目 - Friday AI',
})
// 表单数据
const form = reactive({
 name: '',
 description: '',
 feishu_project_key: '',
})
// 加载项目数据
const loading = ref(true)
onMounted(async => {
 try {
 const project = await projectsStore.fetchProject(projectId)
 if (project) {
 form.name = project.name
 form.description = project.description || ''
 form.feishu_project_key = project.feishu_project_key || ''
 }
 }
 catch (e) {
 showError('加载失败', '无法加载项目信息')
 router.push('/projects')
 }
 finally {
 loading.value = false
 }
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
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 await projectsStore.updateProject(projectId, {
 name: form.name,
 description: form.description || undefined,
 feishu_project_key: form.feishu_project_key || null,
 })
 success('更新成功', '项目信息已更新')
 router.push(`/projects/${projectId}`)
 }
 catch (e) {
 showError('更新失败', e instanceof Error ? e.message: '无法更新项目')
 }
 finally {
 submitting.value = false
 }
}
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-6">
 <!-- 返回按钮 -->
 <RouterLink:to="`/projects/${projectId}`" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 ← 返回项目详情
 </RouterLink>
 <div v-if="loading" class="flex justify-center py-12">
 <div class="animate-spin text-2xl">
 ⏳
 </div>
 </div>
 <Card v-else>
 <CardHeader>
 <CardTitle>编辑项目</CardTitle>
 <CardDescription>
 修改项目基本信息
 </CardDescription>
 </CardHeader>
 <CardContent>
 <form class="space-y-6" @submit.prevent="handleSubmit">
 <!-- 项目名称 -->
 <div class="space-y-2">
 <Label for="name">项目名称 *</Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：智课项目":class="{ 'border-red-500': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-red-500">
 {{ errors.name }}
 </p>
 </div>
 <!-- 项目描述 -->
 <div class="space-y-2">
 <Label for="description">项目描述</Label>
 <Textarea
 id="description"
 v-model="form.description"
 placeholder="项目的简要描述..."
 rows="3"
 />
 </div>
 <!-- 飞书项目 Key -->
 <div class="space-y-2">
 <Label for="feishu_project_key">飞书项目 Key（可选）</Label>
 <Input
 id="feishu_project_key"
 v-model="form.feishu_project_key"
 placeholder="例如：project_key"
 />
 <p class="text-xs text-muted-foreground">
 用于飞书项目管理 API 调用
 </p>
 </div>
 <!-- 提交按钮 -->
 <div class="flex items-center gap-4 pt-4">
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="mr-2 animate-spin">⏳</span>
 {{ submitting ? '保存中...': '保存更改' }}
 </Button>
 <RouterLink:to="`/projects/${projectId}`">
 <Button type="button" variant="outline">
 取消
 </Button>
 </RouterLink>
 </div>
 </form>
 </CardContent>
 </Card>
 </div>
</template>
