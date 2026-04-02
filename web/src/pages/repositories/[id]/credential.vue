<script setup lang="ts">
/**
 * 仓库凭证配置页面
 * 用于查看和更新仓库的 Git 凭证（仅 Access Token）
 */
import { useHead } from '@vueuse/head'
import { useErrorHandler } from '~/composables/useErrorHandler'
import BaseModal from '~/components/modal/BaseModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
const route = useRoute('/repositories/[id]/credential')
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { handleError } = useErrorHandler
const { success } = useToast
const repositoryId = computed( => route.params.id)
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
 catch (e: unknown) {
 handleError(e, '加载凭证')
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
 handleError(new Error('请输入新的 Access Token'), '保存凭证')
 return
 }
 submitting.value = true
 try {
 await repositoriesStore.setAccessToken(repositoryId.value, {
 token: accessToken.value,
 git_user_name: gitUserName.value,
 git_user_email: gitUserEmail.value,
 })
 success('保存成功', credential.value ? 'Access Token 已更新': 'Access Token 已配置')
 accessToken.value = ''
 updateDialogOpen.value = false
 await repositoriesStore.fetchCredential(repositoryId.value)
 }
 catch (e: unknown) {
 handleError(e, '保存 Access Token')
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
 <div class="max-w-2xl mx-auto space-y-8">
 <!-- 返回按钮 -->
 <RouterLink:to="`/repositories/${repositoryId}`"
 class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors"
 >
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回仓库详情
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="2" />
 <template v-else-if="repository">
 <!-- 页面标题 -->
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-500/10 flex items-center justify-center">
 <span class="icon-[lucide--key] text-2xl text-amber-500" />
 </div>
 <div>
 <h1 class="text-2xl font-bold">
 凭证配置
 </h1>
 <p class="text-sm text-muted-foreground">
 配置 {{ repository.name }} 的 Git 访问凭证
 </p>
 </div>
 </div>
 </div>
 <!-- 已有凭证显示 -->
 <div v-if="credential" class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-emerald-500/10 via-green-500/10 to-emerald-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-emerald-500/5 to-green-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--check-circle] text-emerald-500" />
 凭证已配置
 </CardTitle>
 <CardDescription>当前凭证信息（Access Token 已脱敏，不会显示原文）</CardDescription>
 </CardHeader>
 <CardContent class="space-y-4 pt-6">
 <div class="grid gap-4">
 <div>
 <Label class="text-muted-foreground">认证类型</Label>
 <div class="mt-2">
 <Badge variant="outline" class="px-3 py-1">
 <span class="icon-[lucide--key] mr-2" />
 Access Token
 </Badge>
 </div>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <Label class="text-muted-foreground">Access Token</Label>
 <p class="mt-2 text-sm font-mono text-muted-foreground bg-muted/50 px-4 py-3 rounded-xl border border-border/50">
 ••••••••••••••••
 </p>
 <p class="text-xs text-muted-foreground mt-2">
 出于安全考虑，Access Token 不会显示。如需更新请点击下方按钮。
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <Label class="text-muted-foreground">Git 用户</Label>
 <p class="mt-2 text-sm">
 {{ credential.git_user_name }} &lt;{{ credential.git_user_email }}&gt;
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <Label class="text-muted-foreground">创建时间</Label>
 <p class="mt-2 text-sm">
 {{ formatDate(credential.created_at) }}
 </p>
 </div>
 </div>
 <div class="flex justify-end pt-4 border-t border-border/50">
 <Button variant="outline" class="group" @click="updateDialogOpen = true">
 <span class="icon-[lucide--refresh-cw] mr-2 group-hover:rotate-180 transition-transform duration-500" />
 更新凭证
 </Button>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 无凭证提示 -->
 <div v-else class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-amber-500/10 via-orange-500/10 to-amber-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5">
 <CardTitle class="flex items-center gap-2 text-amber-600">
 <span class="icon-[lucide--alert-triangle]" />
 凭证未配置
 </CardTitle>
 <CardDescription>该仓库尚未配置 Git 访问凭证，请配置 Access Token</CardDescription>
 </CardHeader>
 <CardContent class="space-y-4 pt-6">
 <p class="text-sm text-muted-foreground">
 需要配置 Access Token 才能执行 Git 操作（如克隆、推送分支等）。
 </p>
 <Button class="group relative overflow-hidden" @click="updateDialogOpen = true">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 配置 Access Token
 </Button>
 </CardContent>
 </Card>
 </div>
 <!-- 安全说明 -->
 <div class=" rounded-2xl border border-dashed border-border/50 bg-muted/20">
 <div class="flex items-start gap-3">
 <span class="icon-[lucide--shield] text-xl text-muted-foreground flex-shrink-0 mt-0.5" />
 <div class="space-y-3">
 <h3 class="font-medium">
 安全说明
 </h3>
 <ul class="list-disc list-inside space-y-1 text-sm text-muted-foreground">
 <li>Access Token 会被加密存储在数据库中</li>
 <li>前端和 API 不会返回或显示 Token 原文</li>
 <li>Token 仅在执行 Git 操作时解密使用</li>
 <li>如果 Token 泄露，请及时在 Git 平台撤销并更新</li>
 </ul>
 </div>
 </div>
 </div>
 </template>
 <!-- 仓库不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="仓库不存在"
 description="未找到该仓库"
 action-label="返回列表"
 gradient="from-amber-500/20 to-orange-500/20"
 @action="router.push('/repositories')"
 />
 <!-- 更新凭证对话框 -->
 <BaseModal
 v-model="updateDialogOpen":title="credential ? '更新 Access Token': '配置 Access Token'"
 size="md"
 >
 <div class="space-y-4">
 <p class="text-sm text-muted-foreground">
 {{ credential ? '输入新的 Access Token，更新后旧的 Token 将被替换': '输入 Access Token 以配置 Git 访问凭证' }}
 </p>
 <form id="credential-form" class="space-y-4" @submit.prevent="handleAccessTokenUpdate">
 <div class="space-y-2">
 <Label for="new_access_token">Access Token</Label>
 <Input
 id="new_access_token"
 v-model="accessToken"
 type="password"
 placeholder="GITHUB_TOKEN_PLACEHOLDER 或 glpat-xxxxxxxxxxxx"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <div class="grid gap-4 md:grid-cols-2">
 <div class="space-y-2">
 <Label for="update_git_user_name">Git 用户名</Label>
 <Input
 id="update_git_user_name"
 v-model="gitUserName"
 placeholder="Friday AI Agent"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 <div class="space-y-2">
 <Label for="update_git_user_email">Git 邮箱</Label>
 <Input
 id="update_git_user_email"
 v-model="gitUserEmail"
 type="email"
 placeholder="ai@friday.codes"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 </div>
 </div>
 </form>
 </div>
 <template #footer>
 <div class="flex justify-end gap-3 w-full">
 <Button type="button" variant="outline" @click="updateDialogOpen = false">
 取消
 </Button>
 <Button
 type="submit"
 form="credential-form":disabled="!accessToken.trim || submitting"
 class="group relative overflow-hidden"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="submitting" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 {{ submitting ? '保存中...': '保存' }}
 </Button>
 </div>
 </template>
 </BaseModal>
 </div>
</template>
