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
import { Separator } from '~/components/ui/separator'
import { PLATFORM_LABELS } from '~/types'
useHead({
 title: '新建仓库 - Friday AI',
})
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: '',
 git_url: '',
 git_platform: 'github' as GitPlatform,
 default_branch: 'main',
 claude_md_path: 'developer-notes.md',
 description: '',
 // 凭证信息（必填）
 access_token: '',
 git_user_name: 'Friday AI Agent',
 git_user_email: 'ai-agent@friday.dev',
})
// 表单验证
const errors = reactive({
 name: '',
 git_url: '',
 access_token: '',
})
function validate: boolean {
 errors.name = ''
 errors.git_url = ''
 errors.access_token = ''
 if (!form.name.trim) {
 errors.name = '请输入仓库名称'
 }
 if (!form.git_url.trim) {
 errors.git_url = '请输入仓库 URL'
 }
 else if (!form.git_url.match(/^(https?:\/\/|git@)/)) {
 errors.git_url = '请输入有效的仓库 URL'
 }
 if (!form.access_token.trim) {
 errors.access_token = '请输入 Access Token'
 }
 return !errors.name && !errors.git_url && !errors.access_token
}
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 const repository = await repositoriesStore.createRepository(form)
 success('创建成功', '仓库和凭证已创建')
 router.push(`/repositories/${repository.id}`)
 }
 catch (e) {
 showError('创建失败', e instanceof Error ? e.message: '无法创建仓库')
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
 <RouterLink to="/repositories" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 ← 返回仓库列表
 </RouterLink>
 <Card>
 <CardHeader>
 <CardTitle>新建仓库</CardTitle>
 <CardDescription>
 配置 Git 仓库信息，用于 AI 辅助开发任务
 </CardDescription>
 </CardHeader>
 <CardContent>
 <form class="space-y-6" @submit.prevent="handleSubmit">
 <!-- 仓库名称 -->
 <div class="space-y-2">
 <Label for="name">仓库名称 *</Label>
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
 <Label for="git_url">仓库 URL *</Label>
 <Input
 id="git_url"
 v-model="form.git_url"
 placeholder="https://github.com/user/repo.git":class="{ 'border-red-500': errors.git_url }"
 />
 <p v-if="errors.git_url" class="text-sm text-red-500">
 {{ errors.git_url }}
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
 <!-- 描述 -->
 <div class="space-y-2">
 <Label for="description">描述（可选）</Label>
 <textarea
 id="description"
 v-model="form.description"
 class="flex min-h-[60px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
 placeholder="仓库描述..."
 />
 </div>
 <Separator />
 <!-- 凭证配置区域 -->
 <div class="space-y-4">
 <div>
 <h3 class="text-lg font-medium">
 Git 凭证配置
 </h3>
 <p class="text-sm text-muted-foreground">
 配置用于访问仓库的 Access Token（必填）
 </p>
 </div>
 <!-- Access Token -->
 <div class="space-y-2">
 <Label for="access_token">Access Token *</Label>
 <Input
 id="access_token"
 v-model="form.access_token"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER 或 glpat-xxxxxxxxxxxx":class="{ 'border-red-500': errors.access_token }"
 />
 <p v-if="errors.access_token" class="text-sm text-red-500">
 {{ errors.access_token }}
 </p>
 <p class="text-xs text-muted-foreground">
 需要仓库读写权限的个人访问令牌（PAT），该令牌会被加密存储
 </p>
 </div>
 <!-- Git 用户信息 -->
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label for="git_user_name">Git 用户名</Label>
 <Input
 id="git_user_name"
 v-model="form.git_user_name"
 placeholder="Friday AI Agent"
 />
 </div>
 <div class="space-y-2">
 <Label for="git_user_email">Git 邮箱</Label>
 <Input
 id="git_user_email"
 v-model="form.git_user_email"
 type="email"
 placeholder="ai-agent@friday.dev"
 />
 </div>
 </div>
 <p class="text-xs text-muted-foreground">
 Git 用户信息将用于提交代码时的作者信息
 </p>
 </div>
 <!-- 提交按钮 -->
 <div class="flex items-center gap-4 pt-4">
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="mr-2 animate-spin">⏳</span>
 {{ submitting ? '创建中...': '创建仓库' }}
 </Button>
 <RouterLink to="/repositories">
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
