<script setup lang="ts">
import type { GitPlatform } from '~/types'
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { PLATFORM_LABELS } from '~/types'
useHead({
 title: '新建项目 - Friday AI',
})
const router = useRouter
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: '',
 repo_url: '',
 git_platform: 'github' as GitPlatform,
 default_branch: 'main',
 claude_md_path: 'developer-notes.md',
 feishu_project_key: '',
})
// 表单验证
const errors = reactive({
 name: '',
 repo_url: '',
})
function validate: boolean {
 errors.name = ''
 errors.repo_url = ''
 if (!form.name.trim) {
 errors.name = '请输入项目名称'
 }
 if (!form.repo_url.trim) {
 errors.repo_url = '请输入仓库 URL'
 }
 else if (!form.repo_url.match(/^(https?:\/\/|git@)/)) {
 errors.repo_url = '请输入有效的仓库 URL'
 }
 return !errors.name && !errors.repo_url
}
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 const project = await projectsStore.createProject(form)
 success('创建成功', '项目已创建，接下来配置凭证')
 router.push(`/projects/${project.id}/credential`)
 }
 catch (e) {
 showError('创建失败', e instanceof Error ? e.message: '无法创建项目')
 }
 finally {
 submitting.value = false
 }
}
// 平台选项
const platforms: { value: GitPlatform, label: string } = [
 { value: 'github', label: PLATFORM_LABELS.github },
 { value: 'gitlab', label: PLATFORM_LABELS.gitlab },
 { value: 'gitea', label: PLATFORM_LABELS.gitea },
 { value: 'bitbucket', label: PLATFORM_LABELS.bitbucket },
]
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
 配置 Git 仓库信息，用于 AI 辅助开发任务
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
 placeholder="例如：friday-ai":class="{ 'border-red-500': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-red-500">
 {{ errors.name }}
 </p>
 </div>
 <!-- 仓库 URL -->
 <div class="space-y-2">
 <Label for="repo_url">仓库 URL *</Label>
 <Input
 id="repo_url"
 v-model="form.repo_url"
 placeholder="https://github.com/user/repo.git":class="{ 'border-red-500': errors.repo_url }"
 />
 <p v-if="errors.repo_url" class="text-sm text-red-500">
 {{ errors.repo_url }}
 </p>
 <p class="text-xs text-muted-foreground">
 支持 HTTPS 或 SSH 格式
 </p>
 </div>
 <!-- Git 平台 -->
 <div class="space-y-2">
 <Label>Git 平台</Label>
 <Select v-model="form.git_platform">
 <SelectTrigger>
 <SelectValue placeholder="选择平台" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="p in platforms":key="p.value":value="p.value">
 {{ p.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <!-- 默认分支 -->
 <div class="space-y-2">
 <Label for="default_branch">默认分支</Label>
 <Input
 id="default_branch"
 v-model="form.default_branch"
 placeholder="main"
 />
 </div>
 <!-- developer-notes.md 路径 -->
 <div class="space-y-2">
 <Label for="claude_md_path">developer-notes.md 路径</Label>
 <Input
 id="claude_md_path"
 v-model="form.claude_md_path"
 placeholder="developer-notes.md"
 />
 <p class="text-xs text-muted-foreground">
 用于提供项目上下文的 Markdown 文件路径
 </p>
 </div>
 <!-- 飞书项目 Key -->
 <div class="space-y-2">
 <Label for="feishu_project_key">飞书项目 Key（可选）</Label>
 <Input
 id="feishu_project_key"
 v-model="form.feishu_project_key"
 placeholder="project_key"
 />
 <p class="text-xs text-muted-foreground">
 用于飞书项目管理 API 调用
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
