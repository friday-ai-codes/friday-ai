<script setup lang="ts">
import type { GitPlatform } from '~/types'
import { VueFinalModal } from 'vue-final-modal'
import { repositoriesApi } from '~/api'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { MarkdownEditor } from '~/components/ui/markdown-editor'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { PLATFORM_LABELS } from '~/types'
const props = defineProps<{
 repository: {
 id: string
 name: string
 git_url: string
 git_platform: GitPlatform
 default_branch: string
 description?: string
 proxy_url?: string
 }
}>
const emit = defineEmits<{
 confirm:
 cancel:
 closed:
}>
const repositoriesStore = useRepositoriesStore
const { handleError } = useErrorHandler
const { success, error: showError } = useToast
// 表单数据
const form = reactive({
 name: props.repository.name,
 git_url: props.repository.git_url,
 git_platform: props.repository.git_platform,
 default_branch: props.repository.default_branch,
 description: props.repository.description || '',
 proxy_url: props.repository.proxy_url || '',
})
// 表单验证
const errors = reactive({
 name: '',
 git_url: '',
})
function validate: boolean {
 errors.name = ''
 errors.git_url = ''
 if (!form.name.trim) {
 errors.name = '请输入仓库名称'
 }
 if (!form.git_url.trim) {
 errors.git_url = '请输入仓库 URL'
 }
 else if (!form.git_url.match(/^(https?:\/\/|git@)/)) {
 errors.git_url = '请输入有效的仓库 URL'
 }
 return !errors.name && !errors.git_url
}
// 提交表单
const submitting = ref(false)
async function handleSubmit {
 if (!validate)
 return
 submitting.value = true
 try {
 await repositoriesStore.updateRepository(props.repository.id, form)
 success('更新成功', '仓库信息已更新')
 emit('confirm')
 }
 catch (e: unknown) {
 handleError(e, '更新仓库')
 }
 finally {
 submitting.value = false
 }
}
function handleCancel {
 emit('cancel')
}
// 测试连接
const testing = ref(false)
const testResult = ref<{ success: boolean, message?: string, error?: string, branches?: string } | null>(null)
// 当 repository prop 变化时，重置表单数据
watch( => props.repository, (newRepo) => {
 form.name = newRepo.name
 form.git_url = newRepo.git_url
 form.git_platform = newRepo.git_platform
 form.default_branch = newRepo.default_branch
 form.description = newRepo.description || ''
 form.proxy_url = newRepo.proxy_url || ''
 // 清除验证错误和测试结果
 errors.name = ''
 errors.git_url = ''
 testResult.value = null
}, { deep: true })
async function handleTestConnection {
 testing.value = true
 testResult.value = null
 try {
 const result = await repositoriesApi.testRepositoryConnection(props.repository.id)
 testResult.value = result
 if (result.success) {
 success('连接成功', '仓库可访问')
 }
 else {
 showError('连接失败', result.error || '无法连接到仓库')
 }
 }
 catch (e: unknown) {
 testResult.value = { success: false, error: e instanceof Error ? e.message: '测试连接失败' }
 handleError(e, '测试连接')
 }
 finally {
 testing.value = false
 }
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
 content-class="flex flex-col bg-card rounded-2xl shadow-lg border border-border/50 max-w-4xl w-full mx-4 max-h-[90vh]"
 overlay-transition="vfm-fade"
 content-transition="vfm-zoom"
 @closed="emit('closed')"
 >
 <!-- Header -->
 <div class="flex items-center justify-between px-6 py-5 border-b border-border/50 shrink-0">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10">
 <span class="icon-[lucide--edit] text-xl text-violet-600" />
 </div>
 <div>
 <h3 class="text-lg font-semibold text-foreground">
 编辑仓库
 </h3>
 <p class="text-sm text-muted-foreground">
 修改仓库基本信息和配置
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
 <!-- 描述 -->
 <div class="space-y-2">
 <Label for="description" class="flex items-center gap-1 text-foreground">
 描述
 <span class="text-xs font-normal text-muted-foreground">(支持 Markdown)</span>
 </Label>
 <MarkdownEditor
 v-model="form.description"
 placeholder="仓库描述，支持 Markdown 语法..."
 min-height="200px"
 max-height="800px"
 sticky-toolbar
 />
 </div>
 <!-- 测试连接 -->
 <div class="flex items-center justify-between rounded-xl bg-muted/30 border border-border/50">
 <div class="flex items-center gap-3">
 <div
 class=" rounded-lg transition-colors":class="testResult?.success ? 'bg-gradient-to-br from-emerald-500/20 to-teal-500/10': testResult && !testResult.success ? 'bg-gradient-to-br from-red-500/20 to-red-500/10': 'bg-gradient-to-br from-muted to-muted/50'"
 >
 <span
 v-if="testing"
 class="icon-[lucide--loader-circle] text-lg text-muted-foreground animate-spin"
 />
 <span
 v-else-if="testResult?.success"
 class="icon-[lucide--check-circle] text-lg text-emerald-600"
 />
 <span
 v-else-if="testResult && !testResult.success"
 class="icon-[lucide--x-circle] text-lg text-red-500"
 />
 <span
 v-else
 class="icon-[lucide--plug] text-lg text-muted-foreground"
 />
 </div>
 <div>
 <h4 class="font-medium text-sm text-foreground">
 {{ testing ? '正在测试连接...': testResult?.success ? '连接成功': testResult && !testResult.success ? '连接失败': '连接测试' }}
 </h4>
 <p class="text-xs text-muted-foreground">
 <template v-if="testing">
 验证仓库凭证中
 </template>
 <template v-else-if="testResult?.success">
 仓库可访问
 </template>
 <template v-else-if="testResult && !testResult.success">
 {{ testResult.error }}
 </template>
 <template v-else>
 验证仓库凭证是否有效
 </template>
 </p>
 </div>
 </div>
 <Button
 type="button"
 variant="outline"
 size="sm":disabled="testing"
 @click="handleTestConnection"
 >
 <span v-if="testing" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else-if="testResult" class="icon-[lucide--refresh-cw] mr-2" />
 <span v-else class="icon-[lucide--zap] mr-2" />
 {{ testing ? '测试中...': testResult ? '重新测试': '测试连接' }}
 </Button>
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
