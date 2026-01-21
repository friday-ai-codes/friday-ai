<script setup lang="ts">
import type { GitPlatform } from '~/types'
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
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
 git_user_name: 'Friday Codes AI Agent',
 git_user_email: 'ai@friday.codes',
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
const platforms: { value: GitPlatform, label: string, icon: string } = [
 { value: 'github', label: PLATFORM_LABELS.github, icon: 'lucide--github' },
 { value: 'gitlab', label: PLATFORM_LABELS.gitlab, icon: 'simple-icons--gitlab' },
 { value: 'gitea', label: PLATFORM_LABELS.gitea, icon: 'simple-icons--gitea' },
 { value: 'bitbucket', label: PLATFORM_LABELS.bitbucket, icon: 'simple-icons--bitbucket' },
]
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-8">
 <!-- 返回按钮 -->
 <RouterLink to="/repositories" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回仓库列表
 </RouterLink>
 <!-- 表单卡片 -->
 <div class="relative">
 <!-- 卡片光晕 -->
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 via-purple-500/10 to-violet-500/10 rounded-3xl blur-xl opacity-70" />
 <!-- 卡片主体 -->
 <div class="relative bg-card/80 backdrop-blur-sm rounded-2xl border border-border/50 overflow-hidden">
 <!-- 标题区域 -->
 <div class=" border-b border-border/50 bg-gradient-to-r from-violet-500/5 to-purple-500/5">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10">
 <span class="icon-[lucide--git-branch] text-2xl text-violet-500" />
 </div>
 <div>
 <h1 class="text-xl font-bold">新建仓库</h1>
 <p class="text-sm text-muted-foreground">
 配置 Git 仓库信息，用于 AI 辅助开发任务
 </p>
 </div>
 </div>
 </div>
 <!-- 表单内容 -->
 <form class=" space-y-6" @submit.prevent="handleSubmit">
 <!-- 仓库名称 -->
 <div class="space-y-2">
 <Label for="name" class="flex items-center gap-1">
 仓库名称
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：friday-ai"
 class=" bg-muted/30 border-border/50 focus:border-primary/50":class="{ 'border-destructive': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.name }}
 </p>
 </div>
 <!-- 仓库 URL -->
 <div class="space-y-2">
 <Label for="git_url" class="flex items-center gap-1">
 仓库 URL
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="git_url"
 v-model="form.git_url"
 placeholder="https://github.com/user/repo.git"
 class=" bg-muted/30 border-border/50 focus:border-primary/50":class="{ 'border-destructive': errors.git_url }"
 />
 <p v-if="errors.git_url" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.git_url }}
 </p>
 <p class="text-xs text-muted-foreground">
 支持 HTTPS 或 SSH 格式
 </p>
 </div>
 <!-- Git 平台和默认分支 -->
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label>Git 平台</Label>
 <Select v-model="form.git_platform">
 <SelectTrigger class=" bg-muted/30 border-border/50">
 <SelectValue placeholder="选择平台" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="p in platforms":key="p.value":value="p.value">
 <div class="flex items-center gap-2">
 <span:class="`icon-[${p.icon}]`" />
 {{ p.label }}
 </div>
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div class="space-y-2">
 <Label for="default_branch">默认分支</Label>
 <Input
 id="default_branch"
 v-model="form.default_branch"
 placeholder="main"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 </div>
 <!-- developer-notes.md 路径 -->
 <div class="space-y-2">
 <Label for="claude_md_path">developer-notes.md 路径</Label>
 <Input
 id="claude_md_path"
 v-model="form.claude_md_path"
 placeholder="developer-notes.md"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 <p class="text-xs text-muted-foreground">
 用于提供项目上下文的 Markdown 文件路径
 </p>
 </div>
 <!-- 描述 -->
 <div class="space-y-2">
 <Label for="description" class="flex items-center gap-2">
 描述
 <span class="text-xs text-muted-foreground font-normal">（可选）</span>
 </Label>
 <textarea
 id="description"
 v-model="form.description"
 class="flex min-h-[80px] w-full rounded-xl border bg-muted/30 border-border/50 px-4 py-3 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
 placeholder="仓库描述..."
 />
 </div>
 <!-- 凭证配置区域 -->
 <div class="relative -mx-6 bg-gradient-to-r from-amber-500/5 to-orange-500/5 border-y border-border/50">
 <div class="flex items-center gap-3 mb-4">
 <div class=" rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/10">
 <span class="icon-[lucide--key] text-xl text-amber-500" />
 </div>
 <div>
 <h3 class="font-semibold">Git 凭证配置</h3>
 <p class="text-sm text-muted-foreground">
 配置用于访问仓库的 Access Token（必填）
 </p>
 </div>
 </div>
 <!-- Access Token -->
 <div class="space-y-4">
 <div class="space-y-2">
 <Label for="access_token" class="flex items-center gap-1">
 Access Token
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="access_token"
 v-model="form.access_token"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER 或 glpat-xxxxxxxxxxxx"
 class=" bg-card/50 border-border/50 focus:border-primary/50":class="{ 'border-destructive': errors.access_token }"
 />
 <p v-if="errors.access_token" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
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
 class=" bg-card/50 border-border/50 focus:border-primary/50"
 />
 </div>
 <div class="space-y-2">
 <Label for="git_user_email">Git 邮箱</Label>
 <Input
 id="git_user_email"
 v-model="form.git_user_email"
 type="email"
 placeholder="ai@friday.codes"
 class=" bg-card/50 border-border/50 focus:border-primary/50"
 />
 </div>
 </div>
 <p class="text-xs text-muted-foreground">
 Git 用户信息将用于提交代码时的作者信息
 </p>
 </div>
 </div>
 <!-- 提交按钮 -->
 <div class="flex items-center gap-4 pt-4">
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
 创建仓库
 </template>
 </Button>
 <RouterLink to="/repositories">
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
