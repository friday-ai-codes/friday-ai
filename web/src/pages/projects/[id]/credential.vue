<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
const route = useRoute
const router = useRouter
const projectsStore = useProjectsStore
const { success, error: showError } = useToast
const projectId = computed( => route.params.id as string)
useHead({
 title: '凭证管理 - Friday AI',
})
// 加载数据
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 projectsStore.fetchProject(projectId.value),
 projectsStore.fetchCredential(projectId.value),
 ])
 } catch (e) {
 // 忽略凭证不存在的错误
 } finally {
 loading.value = false
 }
})
const project = computed( => projectsStore.currentProject)
const credential = computed( => projectsStore.currentCredential)
// SSH 密钥表单
const sshForm = reactive({
 file: null as File | null,
 gitUserName: 'Friday AI Agent',
 gitUserEmail: 'ai-agent@friday.dev',
})
// Access Token 表单
const tokenForm = reactive({
 token: '',
 gitUserName: 'Friday AI Agent',
 gitUserEmail: 'ai-agent@friday.dev',
})
// 上传状态
const uploading = ref(false)
// 处理文件选择
function handleFileChange(event: Event) {
 const target = event.target as HTMLInputElement
 if (target.files && target.files.length > 0) {
 sshForm.file = target.files[0] ?? null
 }
}
// 上传 SSH 密钥
async function handleUploadSshKey {
 if (!sshForm.file) {
 showError('请选择文件', '请选择 SSH 私钥文件')
 return
 }
 uploading.value = true
 try {
 await projectsStore.uploadSshKey(
 projectId.value,
 sshForm.file,
 sshForm.gitUserName,
 sshForm.gitUserEmail,
 )
 success('上传成功', 'SSH 密钥已配置')
 sshForm.file = null
 } catch (e) {
 showError('上传失败', e instanceof Error ? e.message: '无法上传 SSH 密钥')
 } finally {
 uploading.value = false
 }
}
// 设置 Access Token
async function handleSetToken {
 if (!tokenForm.token.trim) {
 showError('请输入 Token', '请输入 Access Token')
 return
 }
 uploading.value = true
 try {
 await projectsStore.setAccessToken(
 projectId.value,
 tokenForm.token,
 tokenForm.gitUserName,
 tokenForm.gitUserEmail,
 )
 success('设置成功', 'Access Token 已配置')
 tokenForm.token = ''
 } catch (e) {
 showError('设置失败', e instanceof Error ? e.message: '无法设置 Access Token')
 } finally {
 uploading.value = false
 }
}
// 删除凭证
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDeleteCredential {
 deleting.value = true
 try {
 await projectsStore.deleteCredential(projectId.value)
 success('删除成功', '凭证已删除')
 deleteDialogOpen.value = false
 } catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除凭证')
 } finally {
 deleting.value = false
 }
}
</script>
<template>
 <div class="max-w-2xl mx-auto space-y-6">
 <!-- 返回按钮 -->
 <RouterLink:to="`/projects/${projectId}`"
 class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground"
 >
 <span class="icon-[lucide--arrow-left] mr-1"></span>
 返回项目详情
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="2" />
 <template v-else-if="project">
 <div>
 <h1 class="text-2xl font-bold">凭证管理</h1>
 <p class="text-muted-foreground">配置 {{ project.name }} 的 Git 访问凭证</p>
 </div>
 <!-- 已有凭证 -->
 <Card v-if="credential">
 <CardHeader>
 <div class="flex items-center justify-between">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--check-circle] text-green-600"></span>
 <span>凭证已配置</span>
 </CardTitle>
 <CardDescription>
 类型：{{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </CardDescription>
 </div>
 <Button variant="destructive" size="sm" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1"></span>
 删除凭证
 </Button>
 </div>
 </CardHeader>
 <CardContent>
 <div class="space-y-4">
 <div>
 <label class="text-sm text-muted-foreground">Git 用户名</label>
 <p class="font-medium">{{ credential.git_user_name }}</p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">Git 邮箱</label>
 <p class="font-medium">{{ credential.git_user_email }}</p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">配置时间</label>
 <p class="font-medium">{{ new Date(credential.created_at).toLocaleString('zh-CN') }}</p>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- 配置新凭证 -->
 <Card v-else>
 <CardHeader>
 <CardTitle>配置凭证</CardTitle>
 <CardDescription>
 选择认证方式来配置 Git 仓库访问凭证
 </CardDescription>
 </CardHeader>
 <CardContent>
 <Tabs default-value="ssh" class="w-full">
 <TabsList class="grid w-full grid-cols-2">
 <TabsTrigger value="ssh">
 <span class="icon-[lucide--key] mr-1"></span>
 SSH 密钥
 </TabsTrigger>
 <TabsTrigger value="token">
 <span class="icon-[lucide--lock] mr-1"></span>
 Access Token
 </TabsTrigger>
 </TabsList>
 <!-- SSH 密钥 -->
 <TabsContent value="ssh" class="space-y-4 mt-4">
 <div class="space-y-2">
 <Label for="ssh-file">SSH 私钥文件 *</Label>
 <Input
 id="ssh-file"
 type="file"
 accept=".pem,.key,id_rsa,id_ed25519"
 @change="handleFileChange"
 />
 <p class="text-xs text-muted-foreground">
 支持 RSA、Ed25519 等格式的私钥文件
 </p>
 </div>
 <Separator />
 <div class="space-y-2">
 <Label for="ssh-user-name">Git 用户名</Label>
 <Input
 id="ssh-user-name"
 v-model="sshForm.gitUserName"
 placeholder="Friday AI Agent"
 />
 </div>
 <div class="space-y-2">
 <Label for="ssh-user-email">Git 邮箱</Label>
 <Input
 id="ssh-user-email"
 v-model="sshForm.gitUserEmail"
 placeholder="ai-agent@friday.dev"
 />
 </div>
 <Button:disabled="!sshForm.file || uploading"
 @click="handleUploadSshKey"
 >
 <span v-if="uploading" class="icon-[lucide--loader-circle] mr-2 animate-spin"></span>
 <span v-else class="icon-[lucide--upload] mr-2"></span>
 {{ uploading ? '上传中...': '上传 SSH 密钥' }}
 </Button>
 </TabsContent>
 <!-- Access Token -->
 <TabsContent value="token" class="space-y-4 mt-4">
 <div class="space-y-2">
 <Label for="token">Access Token *</Label>
 <Input
 id="token"
 v-model="tokenForm.token"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER"
 />
 <p class="text-xs text-muted-foreground">
 GitHub Personal Access Token 或其他平台的访问令牌
 </p>
 </div>
 <Separator />
 <div class="space-y-2">
 <Label for="token-user-name">Git 用户名</Label>
 <Input
 id="token-user-name"
 v-model="tokenForm.gitUserName"
 placeholder="Friday AI Agent"
 />
 </div>
 <div class="space-y-2">
 <Label for="token-user-email">Git 邮箱</Label>
 <Input
 id="token-user-email"
 v-model="tokenForm.gitUserEmail"
 placeholder="ai-agent@friday.dev"
 />
 </div>
 <Button:disabled="!tokenForm.token.trim || uploading"
 @click="handleSetToken"
 >
 <span v-if="uploading" class="icon-[lucide--loader-circle] mr-2 animate-spin"></span>
 <span v-else class="icon-[lucide--save] mr-2"></span>
 {{ uploading ? '设置中...': '设置 Access Token' }}
 </Button>
 </TabsContent>
 </Tabs>
 </CardContent>
 </Card>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目"
 action-label="返回列表"
 @action="router.push('/projects')"
 />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除凭证"
 description="确定要删除此凭证吗？删除后需要重新配置才能执行任务。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDeleteCredential"
 />
 </div>
</template>