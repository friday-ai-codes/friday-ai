<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Separator } from '~/components/ui/separator'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { success, error: showError } = useToast
const repositoryId = computed( => route.params.id as string)
useHead({
 title: computed( => repositoriesStore.currentRepository?.name
 ? `${repositoriesStore.currentRepository.name} - Friday AI`: '仓库详情 - Friday AI'),
})
// 加载仓库
const loading = ref(true)
onMounted(async => {
 try {
 await Promise.all([
 repositoriesStore.fetchRepository(repositoryId.value),
 repositoriesStore.fetchCredential(repositoryId.value),
 ])
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取仓库详情')
 }
 finally {
 loading.value = false
 }
})
// 删除仓库
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 deleting.value = true
 try {
 await repositoriesStore.deleteRepository(repositoryId.value)
 success('删除成功', '仓库已删除')
 router.push('/repositories')
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除仓库')
 }
 finally {
 deleting.value = false
 deleteDialogOpen.value = false
 }
}
// 格式化日期
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 计算属性
const repository = computed( => repositoriesStore.currentRepository)
const credential = computed( => repositoriesStore.currentCredential)
</script>
<template>
 <div class="space-y-6">
 <!-- 返回按钮 -->
 <RouterLink to="/repositories" class="inline-flex items-center text-sm text-muted-foreground hover:text-foreground">
 <span class="icon-[lucide--arrow-left] mr-1" />
 返回仓库列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 仓库详情 -->
 <template v-else-if="repository">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div>
 <h1 class="text-2xl font-bold">
 {{ repository.name }}
 </h1>
 <p class="text-muted-foreground flex items-center gap-2 mt-1">
 <Badge variant="outline">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 <span>{{ repository.default_branch }}</span>
 </p>
 </div>
 <div class="flex items-center gap-2">
 <!-- TODO: 编辑功能 -->
 <Button variant="destructive" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-2" />
 删除
 </Button>
 </div>
 </div>
 <div class="grid gap-6 md:grid-cols-2">
 <!-- 基本信息 -->
 <Card>
 <CardHeader>
 <CardTitle>基本信息</CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <div>
 <label class="text-sm text-muted-foreground">仓库 URL</label>
 <p class="font-mono text-sm mt-1 break-all">
 {{ repository.git_url }}
 </p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">developer-notes.md 路径</label>
 <p class="font-mono text-sm mt-1">
 {{ repository.claude_md_path }}
 </p>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">描述</label>
 <p class="text-sm mt-1">
 {{ repository.description || '暂无描述' }}
 </p>
 </div>
 <Separator />
 <div class="flex gap-8">
 <div>
 <label class="text-sm text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(repository.created_at) }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">更新时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(repository.updated_at) }}
 </p>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- 凭证状态 -->
 <Card>
 <CardHeader class="flex flex-row items-center justify-between">
 <div>
 <CardTitle>凭证配置</CardTitle>
 <CardDescription>Git 仓库访问凭证</CardDescription>
 </div>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button variant="outline" size="sm">
 <span class="icon-[lucide--key] mr-2" />
 管理凭证
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent>
 <div v-if="credential" class="space-y-4">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--check-circle] text-2xl text-green-600" />
 <div>
 <p class="font-medium">
 凭证已配置
 </p>
 <p class="text-sm text-muted-foreground">
 类型：{{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </p>
 </div>
 </div>
 <Separator />
 <div>
 <label class="text-sm text-muted-foreground">Git 用户</label>
 <p class="text-sm mt-1">
 {{ credential.git_user_name }} &lt;{{ credential.git_user_email }}&gt;
 </p>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <span class="icon-[lucide--lock] text-4xl text-muted-foreground" />
 <p class="mt-2 text-muted-foreground">
 尚未配置凭证
 </p>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button class="mt-4" size="sm">
 配置凭证
 </Button>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </div>
 </template>
 <!-- 仓库不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="仓库不存在"
 description="未找到该仓库，可能已被删除"
 action-label="返回列表"
 @action="router.push('/repositories')"
 />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除仓库"
 description="确定要删除此仓库吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
</template>
