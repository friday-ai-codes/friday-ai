<script setup lang="ts">
import type { GitPlatform } from '~/types'
import { VueFinalModal } from 'vue-final-modal'
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
const emit = defineEmits<{
 confirm: [repositoryId: string]
 cancel:
 closed:
}>
const repositoriesStore = useRepositoriesStore
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: '',
 git_url: '',
 git_platform: 'gitlab' as GitPlatform,
 default_branch: 'main',
 description: '',
 proxy_url: '',
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
 emit('confirm', repository.id)
 }
 catch (e) {
 showError('创建失败', e instanceof Error ? e.message: '无法创建仓库')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('cancel')
}
// 平台选项
const platforms: { value: GitPlatform, label: string, icon: string } = [
 { value: 'github', label: PLATFORM_LABELS.github, icon: 'lucide--github' },
 { value: 'gitlab', label: PLATFORM_LABELS.gitlab, icon: 'simple-icons--gitlab' },
 { value: 'gitea', label: PLATFORM_LABELS.gitea, icon: 'simple-icons--gitea' },
 { value: 'bitbucket', label: PLATFORM_LABELS.bitbucket, icon: 'simple-icons--bitbucket' },
]
const selectedPlatform = computed( => platforms.find(p => p.value === form.git_platform))
</script>
<template>
 <VueFinalModal
 class="flex justify-center items-center"
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-2xl w-full mx-4 max-h-[90vh]"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10">
 <span class="icon-[lucide--git-branch] text-xl text-violet-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 新建仓库
 </h3>
 <p class="text-sm text-muted-foreground">
 配置 Git 仓库信息，用于 AI 辅助开发任务
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
 <form class="flex-1 overflow-y-auto px-6 py-5 space-y-5" @submit.prevent="handleSubmit">
 <!-- 仓库名称 -->
 <div class="space-y-2">
 <Label for="name" class="flex items-center gap-1 text-foreground">
 仓库名称
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="name"
 v-model="form.name"
 placeholder="例如：friday-ai"
 class="":class="{ 'border-destructive': errors.name }"
 />
 <p v-if="errors.name" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.name }}
 </p>
 </div>
 <!-- 仓库 URL -->
 <div class="space-y-2">
 <Label for="git_url" class="flex items-center gap-1 text-foreground">
 仓库 URL
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="git_url"
 v-model="form.git_url"
 placeholder="https://github.com/user/repo.git"
 class="":class="{ 'border-destructive': errors.git_url }"
 />
 <p v-if="errors.git_url" class="text-sm text-destructive flex items-center gap-1">
 <span class="icon-[lucide--alert-circle]" />
 {{ errors.git_url }}
 </p>
 <p class="text-xs text-muted-foreground">
 支持 HTTPS 或 SSH 格式
 </p>
 </div>
 <!-- 代理 URL (可选) -->
 <div class="space-y-2">
 <Label for="proxy_url" class="flex items-center gap-1 text-foreground">
 Git 代理 URL
 <span class="text-xs font-normal text-muted-foreground">(可选)</span>
 </Label>
 <Input
 id="proxy_url"
 v-model="form.proxy_url"
 placeholder="http://proxy.example.com:8080"
 class=""
 />
 <p class="text-xs text-muted-foreground">
 用于该仓库 Git 操作的 HTTP 代理
 </p>
 </div>
 <!-- Git 平台和默认分支 -->
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label class="text-foreground">Git 平台</Label>
 <Select v-model="form.git_platform">
 <SelectTrigger class="">
 <SelectValue placeholder="选择平台">
 <div v-if="selectedPlatform" class="flex items-center gap-2">
 <span:class="`icon-[${selectedPlatform.icon}]`" />
 {{ selectedPlatform.label }}
 </div>
 </SelectValue>
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
 <Label for="default_branch" class="text-foreground">默认分支</Label>
 <Input
 id="default_branch"
 v-model="form.default_branch"
 placeholder="main"
 class=""
 />
 </div>
 </div>
 <!-- 凭证配置区域 -->
 <div class="relative -mx-2 bg-gradient-to-r from-amber-50 to-orange-50 border border-amber-200/50 rounded-xl">
 <div class="flex items-center gap-3 mb-4">
 <div class=" rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/10">
 <span class="icon-[lucide--key] text-lg text-amber-600" />
 </div>
 <div>
 <h4 class="font-semibold text-sm text-foreground">
 Git 凭证配置
 </h4>
 <p class="text-xs text-muted-foreground">
 配置用于访问仓库的 Access Token（必填）
 </p>
 </div>
 </div>
 <!-- Access Token -->
 <div class="space-y-4">
 <div class="space-y-2">
 <Label for="access_token" class="flex items-center gap-1 text-foreground">
 Access Token
 <span class="text-destructive">*</span>
 </Label>
 <Input
 id="access_token"
 v-model="form.access_token"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER 或 glpat-xxxxxxxxxxxx"
 class=" bg-white":class="{ 'border-destructive': errors.access_token }"
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
 <Label for="git_user_name" class="text-foreground">Git 用户名</Label>
 <Input
 id="git_user_name"
 v-model="form.git_user_name"
 placeholder="Friday AI Agent"
 class=" bg-white"
 />
 </div>
 <div class="space-y-2">
 <Label for="git_user_email" class="text-foreground">Git 邮箱</Label>
 <Input
 id="git_user_email"
 v-model="form.git_user_email"
 type="email"
 placeholder="ai@friday.codes"
 class=" bg-white"
 />
 </div>
 </div>
 </div>
 </div>
 <!-- Footer -->
 <div class="flex justify-end gap-3 pt-4 border-t border-border/50">
 <Button type="button" variant="outline":disabled="submitting" @click="handleCancel">
 取消
 </Button>
 <Button type="submit":disabled="submitting">
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--plus] mr-2" />
 创建仓库
 </Button>
 </div>
 </form>
 </VueFinalModal>
</template>
