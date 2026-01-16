<script setup lang="ts">
/**
 * 仓库凭证配置页面
 * 用于配置仓库的 Git 凭证（SSH Key 或 Access Token）
 */
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
const route = useRoute
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { success, error: showError } = useToast
const repositoryId = computed( => route.params.id as string)
useHead({
 title: '凭证配置 - Friday AI',
})
// 加载数据
const loading = ref(true)
async function loadData {
 loading.value = true
 try {
 await repositoriesStore.fetchRepository(repositoryId.value)
 await repositoriesStore.fetchCredential(repositoryId.value)
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取仓库详情')
 }
 finally {
 loading.value = false
 }
}
onMounted(loadData)
const repository = computed( => repositoriesStore.currentRepository)
const credential = computed( => repositoriesStore.currentCredential)
// 表单状态
const authType = ref<'ssh_key' | 'access_token'>('ssh_key')
const sshKeyFile = ref<File | null>(null)
const accessToken = ref('')
const gitUserName = ref('Friday AI Agent')
const gitUserEmail = ref('ai-agent@friday.dev')
const submitting = ref(false)
// 删除凭证
const deleteDialogOpen = ref(false)
const deleting = ref(false)
// 文件上传处理
function handleFileChange(event: Event) {
 const target = event.target as HTMLInputElement
 if (target.files && target.files.length > 0) {
 sshKeyFile.value = target.files[0]
 }
}
// 提交 SSH Key
async function handleSshKeySubmit {
 if (!sshKeyFile.value) {
 showError('请选择 SSH 密钥文件')
 return
 }
 submitting.value = true
 try {
 const formData = new FormData
 formData.append('file', sshKeyFile.value)
 formData.append('git_user_name', gitUserName.value)
 formData.append('git_user_email', gitUserEmail.value)
 await repositoriesStore.uploadSshKey(repositoryId.value, formData)
 success('配置成功', 'SSH 密钥已上传')
 sshKeyFile.value = null
 }
 catch (e) {
 showError('上传失败', e instanceof Error ? e.message: '无法上传 SSH 密钥')
 }
 finally {
 submitting.value = false
 }
}
// 提交 Access Token
async function handleAccessTokenSubmit {
 if (!accessToken.value.trim) {
 showError('请输入 Access Token')
 return
 }
 submitting.value = true
 try {
 const formData = new FormData
 formData.append('token', accessToken.value)
 formData.append('git_user_name', gitUserName.value)
 formData.append('git_user_email', gitUserEmail.value)
 await repositoriesStore.setAccessToken(repositoryId.value, formData)
 success('配置成功', 'Access Token 已保存')
 accessToken.value = ''
 }
 catch (e) {
 showError('保存失败', e instanceof Error ? e.message: '无法保存 Access Token')
 }
 finally {
 submitting.value = false
 }
}
// 删除凭证
async function handleDelete {
 deleting.value = true
 try {
 await repositoriesStore.deleteCredential(repositoryId.value)
 success('删除成功', '凭证已删除')
 deleteDialogOpen.value = false
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除凭证')
 }
 finally {
 deleting.value = false
 }
}
// 格式化日期
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-6">
 <!-- 返回按钮 -->
 <RouterLink:to="`/repositories/${repositoryId}`"
 class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
 >
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回仓库详情
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="2" />
 <template v-else-if="repository">
 <div>
 <h1 class="text-2xl font-bold">
 凭证配置
 </h1>
 <p class="text-muted-foreground">
 配置 {{ repository.name }} 的 Git 访问凭证
 </p>
 </div>
 <!-- 已有凭证显示 -->
 <Card v-if="credential">
 <CardHeader>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--check-circle] text-green-600" />
 凭证已配置
 </CardTitle>
 <CardDescription>当前凭证信息</CardDescription>
 </CardHeader>
 <CardContent class="space-y-4">
 <div class="grid gap-4">
 <div>
 <Label class="text-muted-foreground">认证类型</Label>
 <div class="mt-1">
 <Badge variant="outline">
 {{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </Badge>
 </div>
 </div>
 <Separator />
 <div>
 <Label class="text-muted-foreground">Git 用户</Label>
 <p class="mt-1 text-sm">
 {{ credential.git_user_name }} &lt;{{ credential.git_user_email }}&gt;
 </p>
 </div>
 <Separator />
 <div>
 <Label class="text-muted-foreground">创建时间</Label>
 <p class="mt-1 text-sm">
 {{ formatDate(credential.created_at) }}
 </p>
 </div>
 </div>
 <Separator />
 <div class="flex justify-end">
 <Button variant="destructive" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-2" />
 删除凭证
 </Button>
 </div>
 </CardContent>
 </Card>
 <!-- 配置新凭证 -->
 <template v-else>
 <!-- 认证类型选择 -->
 <Card>
 <CardHeader>
 <CardTitle>选择认证方式</CardTitle>
 <CardDescription>选择用于访问 Git 仓库的认证方式</CardDescription>
 </CardHeader>
 <CardContent>
 <div class="flex gap-4">
 <Button:variant="authType === 'ssh_key' ? 'default': 'outline'"
 class="flex-1"
 @click="authType = 'ssh_key'"
 >
 <span class="icon-[lucide--key] mr-2" />
 SSH 密钥
 </Button>
 <Button:variant="authType === 'access_token' ? 'default': 'outline'"
 class="flex-1"
 @click="authType = 'access_token'"
 >
 <span class="icon-[lucide--lock] mr-2" />
 Access Token
 </Button>
 </div>
 </CardContent>
 </Card>
 <!-- SSH Key 配置 -->
 <Card v-if="authType === 'ssh_key'">
 <CardHeader>
 <CardTitle>SSH 密钥配置</CardTitle>
 <CardDescription>上传用于访问仓库的 SSH 私钥文件</CardDescription>
 </CardHeader>
 <CardContent>
 <form class="space-y-4" @submit.prevent="handleSshKeySubmit">
 <div class="space-y-2">
 <Label for="ssh_key">SSH 私钥文件</Label>
 <Input
 id="ssh_key"
 type="file"
 accept=".pem,.key,id_rsa,id_ed25519"
 @change="handleFileChange"
 />
 <p class="text-xs text-muted-foreground">
 支持 RSA、ED25519 等格式的私钥文件（如 id_rsa、id_ed25519）
 </p>
 </div>
 <Separator />
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label for="git_user_name">Git 用户名</Label>
 <Input
 id="git_user_name"
 v-model="gitUserName"
 placeholder="Friday AI Agent"
 />
 </div>
 <div class="space-y-2">
 <Label for="git_user_email">Git 邮箱</Label>
 <Input
 id="git_user_email"
 v-model="gitUserEmail"
 type="email"
 placeholder="ai-agent@friday.dev"
 />
 </div>
 </div>
 <div class="flex justify-end">
 <Button type="submit":disabled="!sshKeyFile || submitting">
 <span v-if="submitting" class="icon-[lucide--loader-2] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--upload] mr-2" />
 上传密钥
 </Button>
 </div>
 </form>
 </CardContent>
 </Card>
 <!-- Access Token 配置 -->
 <Card v-if="authType === 'access_token'">
 <CardHeader>
 <CardTitle>Access Token 配置</CardTitle>
 <CardDescription>使用个人访问令牌 (PAT) 访问仓库</CardDescription>
 </CardHeader>
 <CardContent>
 <form class="space-y-4" @submit.prevent="handleAccessTokenSubmit">
 <div class="space-y-2">
 <Label for="access_token">Access Token</Label>
 <Input
 id="access_token"
 v-model="accessToken"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER"
 />
 <p class="text-xs text-muted-foreground">
 需要仓库读写权限的个人访问令牌
 </p>
 </div>
 <Separator />
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label for="git_user_name_token">Git 用户名</Label>
 <Input
 id="git_user_name_token"
 v-model="gitUserName"
 placeholder="Friday AI Agent"
 />
 </div>
 <div class="space-y-2">
 <Label for="git_user_email_token">Git 邮箱</Label>
 <Input
 id="git_user_email_token"
 v-model="gitUserEmail"
 type="email"
 placeholder="ai-agent@friday.dev"
 />
 </div>
 </div>
 <div class="flex justify-end">
 <Button type="submit":disabled="!accessToken.trim || submitting">
 <span v-if="submitting" class="icon-[lucide--loader-2] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--save] mr-2" />
 保存配置
 </Button>
 </div>
 </form>
 </CardContent>
 </Card>
 </template>
 <!-- 使用说明 -->
 <div class="rounded-lg border space-y-3">
 <h3 class="font-medium">
 配置说明
 </h3>
 <ul class="list-disc list-inside space-y-2 text-sm text-muted-foreground">
 <li>SSH 密钥：需要在 Git 平台（如 GitHub）上添加对应的公钥作为 Deploy Key</li>
 <li>Access Token：需要创建具有仓库读写权限的个人访问令牌</li>
 <li>凭证会被加密存储，确保安全性</li>
 <li>Git 用户信息将用于提交代码时的作者信息</li>
 </ul>
 </div>
 </template>
 <!-- 仓库不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="仓库不存在"
 description="未找到该仓库"
 action-label="返回列表"
 @action="router.push('/repositories')"
 />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除凭证"
 description="确定要删除此凭证吗？删除后需要重新配置才能执行任务。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
</template>
