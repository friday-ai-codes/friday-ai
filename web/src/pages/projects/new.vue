<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
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
 <div class="max-w-2xl mx-auto space-y-8">
 <!-- 返回按钮 -->
 <RouterLink to="/projects" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回项目列表
 </RouterLink>
 <!-- 表单卡片 -->
 <div class="relative">
 <!-- 卡片光晕 -->
 <div class="absolute -inset-1 bg-gradient-to-r from-blue-500/10 via-cyan-500/10 to-blue-500/10 rounded-3xl blur-xl opacity-70" />
 <!-- 卡片主体 -->
 <div class="relative bg-card/80 backdrop-blur-sm rounded-2xl border border-border/50 overflow-hidden">
 <!-- 标题区域 -->
 <div class=" border-b border-border/50 bg-gradient-to-r from-blue-500/5 to-cyan-500/5">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-plus] text-2xl text-blue-500" />
 </div>
 <div>
 <h1 class="text-xl font-bold">
 新建项目
 </h1>
 <p class="text-sm text-muted-foreground">
 创建一个新项目，用于管理飞书工作项和关联的 Git 仓库
 </p>
 </div>
 </div>
 </div>
 <!-- 表单内容 -->
 <form class=" space-y-6" @submit.prevent="handleSubmit">
 <!-- 项目名称 -->
 <div class="space-y-2">
 <Label for="name" class="flex items-center gap-1">
 项目名称
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：智课项目"
 class=" bg-muted/30 border-border/50 focus:border-primary/50":class="{ 'border-destructive': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
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
 class="bg-muted/30 border-border/50 focus:border-primary/50 resize-none"
 />
 </div>
 <!-- 飞书项目 Key -->
 <div class="space-y-2">
 <Label for="feishu_project_key" class="flex items-center gap-2">
 飞书项目 Key
 <span class="text-xs text-muted-foreground font-normal">（可选）</span>
 </Label>
 <Input
 id="feishu_project_key"
 v-model="form.feishu_project_key"
 placeholder="例如：project_key"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 <p class="text-xs text-muted-foreground">
 用于飞书项目管理 API 调用，可稍后在项目详情中配置
 </p>
 </div>
 <!-- 提示信息 -->
 <div class="flex items-start gap-3 rounded-xl bg-muted/50 border border-border/50">
 <span class="icon-[lucide--lightbulb] text-lg text-amber-500 flex-shrink-0 mt-0.5" />
 <p class="text-sm text-muted-foreground">
 创建项目后，您可以在项目详情页中关联 Git 仓库和配置飞书集成。
 </p>
 </div>
 <!-- 提交按钮 -->
 <div class="flex items-center gap-4 pt-4 border-t border-border/50">
 <Button
 type="submit":disabled="submitting"
 class="group relative overflow-hidden"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <template v-if="submitting">
 <span class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 创建中...
 </template>
 <template v-else>
 <span class="icon-[lucide--plus] mr-2" />
 创建项目
 </template>
 </Button>
 <RouterLink to="/projects">
 <Button type="button" variant="outline">
 取消
 </Button>
 </RouterLink>
 </div>
 </form>
 </div>
 </div>
 </div>
</template>
