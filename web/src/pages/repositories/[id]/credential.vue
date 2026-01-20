<script setup lang="ts">
/**
 * 仓库凭证配置页面
 * 用于查看和更新仓库的 Git 凭证（仅 Access Token）
 */
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '~/components/ui/dialog'
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
const accessToken = ref('')
const gitUserName = ref('Friday Codes AI Agent')
const gitUserEmail = ref('ai@friday.codes')
const submitting = ref(false)
// 更新凭证对话框
const updateDialogOpen = ref(false)
// 提交更新或创建 Access Token
async function handleAccessTokenUpdate {
 if (!accessToken.value.trim) {
 showError('请输入新的 Access Token')
 return
 }
 submitting.value = true
 try {
 // 直接调用接口，后端会自动判断是创建还是更新
 await repositoriesStore.setAccessToken(repositoryId.value, {
 token: accessToken.value,
 git_user_name: gitUserName.value,
 git_user_email: gitUserEmail.value,
 })
 success('保存成功', credential.value ? 'Access Token 已更新': 'Access Token 已配置')
 accessToken.value = ''
 updateDialogOpen.value = false
 // 重新加载凭证信息
 await repositoriesStore.fetchCredential(repositoryId.value)
 }
 catch (e) {
 showError('保存失败', e instanceof Error ? e.message: '无法保存 Access Token')
 }
 finally {
 submitting.value = false
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
 <CardDescription>当前凭证信息（Access Token 已脱敏，不会显示原文）</CardDescription>
 </CardHeader>
 <CardContent class="space-y-4">
 <div class="grid gap-4">
 <div>
 <Label class="text-muted-foreground">认证类型</Label>
 <div class="mt-1">
 <Badge variant="outline">
 Access Token
 </Badge>
 </div>
 </div>
 <Separator />
 <div>
 <Label class="text-muted-foreground">Access Token</Label>
 <p class="mt-1 text-sm font-mono text-muted-foreground">
 ••••••••••••••••
 </p>
 <p class="text-xs text-muted-foreground mt-1">
 出于安全考虑，Access Token 不会显示。如需更新请点击下方按钮。
 </p>
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
 <Button variant="outline" @click="updateDialogOpen = true">
 <span class="icon-[lucide--refresh-cw] mr-2" />
 更新凭证
 </Button>
 </div>
 </CardContent>
 </Card>
 <!-- 无凭证提示 -->
 <Card v-else>
 <CardHeader>
 <CardTitle class="flex items-center gap-2 text-amber-600">
 <span class="icon-[lucide--alert-triangle]" />
 凭证未配置
 </CardTitle>
 <CardDescription>该仓库尚未配置 Git 访问凭证，请配置 Access Token</CardDescription>
 </CardHeader>
 <CardContent class="space-y-4">
 <p class="text-sm text-muted-foreground">
 需要配置 Access Token 才能执行 Git 操作（如克隆、推送分支等）。
 </p>
 <Button @click="updateDialogOpen = true">
 <span class="icon-[lucide--plus] mr-2" />
 配置 Access Token
 </Button>
 </CardContent>
 </Card>
 <!-- 使用说明 -->
 <div class="rounded-lg border space-y-3">
 <h3 class="font-medium">
 安全说明
 </h3>
 <ul class="list-disc list-inside space-y-2 text-sm text-muted-foreground">
 <li>Access Token 会被加密存储在数据库中</li>
 <li>前端和 API 不会返回或显示 Token 原文</li>
 <li>Token 仅在执行 Git 操作时解密使用</li>
 <li>如果 Token 泄露，请及时在 Git 平台撤销并更新</li>
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
 <!-- 更新凭证对话框 -->
 <Dialog v-model:open="updateDialogOpen">
 <DialogContent>
 <DialogHeader>
 <DialogTitle>更新 Access Token</DialogTitle>
 <DialogDescription>
 输入新的 Access Token，更新后旧的 Token 将被替换
 </DialogDescription>
 </DialogHeader>
 <form class="space-y-4" @submit.prevent="handleAccessTokenUpdate">
 <div class="space-y-2">
 <Label for="new_access_token">新 Access Token</Label>
 <Input
 id="new_access_token"
 v-model="accessToken"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER 或 glpat-xxxxxxxxxxxx"
 />
 </div>
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label for="update_git_user_name">Git 用户名</Label>
 <Input
 id="update_git_user_name"
 v-model="gitUserName"
 placeholder="Friday AI Agent"
 />
 </div>
 <div class="space-y-2">
 <Label for="update_git_user_email">Git 邮箱</Label>
 <Input
 id="update_git_user_email"
 v-model="gitUserEmail"
 type="email"
 placeholder="ai@friday.codes"
 />
 </div>
 </div>
 <DialogFooter>
 <Button type="button" variant="outline" @click="updateDialogOpen = false">
 取消
 </Button>
 <Button type="submit":disabled="!accessToken.trim || submitting">
 <span v-if="submitting" class="icon-[lucide--loader-2] mr-2 animate-spin" />
 更新
 </Button>
 </DialogFooter>
 </form>
 </DialogContent>
 </Dialog>
 </div>
</template>
