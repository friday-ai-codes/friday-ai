<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Textarea } from '~/components/ui/textarea'
useHead({
 title: '新建项目 - Friday AI',
})
const router = useRouter
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
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 const project = await projectsStore.createProject({
 name: form.name,
 description: form.description || undefined,
 feishu_project_key: form.feishu_project_key || null,
 })
 success('创建成功', '项目已创建')
 router.push(`/projects/${project.id}`)
 }
 catch (e) {
 showError('创建失败', e instanceof Error ? e.message: '无法创建项目')
 }
 finally {
 submitting.value = false
 }
}
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/projects" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 ← 返回项目列表
 </RouterLink>
 <Card>
 <CardHeader>
 <CardTitle>新建项目</CardTitle>
 <CardDescription>
 创建一个新项目，用于管理飞书工作项和关联的 Git 仓库
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
 用于飞书项目管理 API 调用，可稍后在项目详情中配置
 </p>
 </div>
 <!-- 提示信息 -->
 <div class="rounded-lg border bg-muted/50 ">
 <p class="text-sm text-muted-foreground">
 <span class="icon-[lucide--info] mr-1.5 inline-block align-text-bottom" />
 创建项目后，您可以在项目详情页中关联 Git 仓库和配置飞书集成。
 </p>
 </div>
 <!-- 提交按钮 -->
 <div class="flex items-center gap-4 pt-4">
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="mr-2 animate-spin">⏳</span>
 {{ submitting ? '创建中...': '创建项目' }}
 </Button>
 <RouterLink to="/projects">
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
