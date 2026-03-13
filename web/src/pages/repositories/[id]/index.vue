<script setup lang="ts">
import { useHead } from '@vueuse/head'
import EditRepositoryModal from '~/components/repository/EditRepositoryModal.vue'
import IndexHistoryList from '~/components/repository/IndexHistoryList.vue'
import IndexStatsPanel from '~/components/repository/IndexStatsPanel.vue'
import RepositoryIndexCard from '~/components/repository/RepositoryIndexCard.vue'
import WebhookConfigPanel from '~/components/repository/WebhookConfigPanel.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { MarkdownPreview } from '~/components/ui/markdown-editor'
import { Separator } from '~/components/ui/separator'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute('/repositories/[id]/')
const router = useRouter
const repositoriesStore = useRepositoriesStore
const { success, error: showError } = useToast
const repositoryId = computed( => route.params.id)
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
// 编辑仓库
const editDialogOpen = ref(false)
async function handleEditSuccess {
 editDialogOpen.value = false
 await repositoriesStore.fetchRepository(repositoryId.value)
}
</script>
<template>
 <div class="space-y-8">
 <!-- 返回按钮 -->
 <RouterLink to="/repositories" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回仓库列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 仓库详情 -->
 <template v-else-if="repository">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div class="space-y-2">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--git-branch] text-2xl text-violet-500" />
 </div>
 <div>
 <h1 class="text-2xl font-bold flex items-center gap-3">
 {{ repository.name }}
 <Badge variant="outline">
 {{ PLATFORM_LABELS[repository.git_platform] }}
 </Badge>
 </h1>
 <p class="text-sm text-muted-foreground font-mono">
 {{ repository.default_branch }}
 </p>
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <Button variant="outline" class="group" @click="editDialogOpen = true">
 <span class="icon-[lucide--edit] mr-2 group-hover:scale-110 transition-transform" />
 编辑
 </Button>
 <Button variant="destructive" class="group" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-2 group-hover:scale-110 transition-transform" />
 删除
 </Button>
 </div>
 </div>
 <div class="grid gap-6 md:grid-cols-2">
 <!-- 基本信息 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 via-purple-500/10 to-violet-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-violet-500/5 to-purple-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--info] text-violet-500" />
 基本信息
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-4 pt-6">
 <div>
 <label class="text-sm text-muted-foreground">仓库 URL</label>
 <p class="font-mono text-sm mt-1 break-all">
 {{ repository.git_url }}
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <label class="text-sm text-muted-foreground">描述</label>
 <div v-if="repository.description" class="mt-1">
 <MarkdownPreview:content="repository.description" />
 </div>
 <p v-else class="text-sm mt-1 text-muted-foreground">
 暂无描述
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div v-if="repository.proxy_url">
 <label class="text-sm text-muted-foreground">代理 URL</label>
 <p class="font-mono text-sm mt-1">
 {{ repository.proxy_url }}
 </p>
 <Separator class="bg-border/50 mt-4" />
 </div>
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
 </div>
 <!-- 凭证状态 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-amber-500/10 via-orange-500/10 to-amber-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--key] text-amber-500" />
 凭证配置
 </CardTitle>
 <CardDescription>Git 仓库访问凭证</CardDescription>
 </div>
 <RouterLink:to="`/repositories/${repository.id}/credential`">
 <Button variant="outline" size="sm" class="group">
 <span class="icon-[lucide--key] mr-2 group-hover:scale-110 transition-transform" />
 管理凭证
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent class="pt-6">
 <div v-if="credential" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-2xl text-emerald-500" />
 </div>
 <div>
 <p class="font-medium">
 凭证已配置
 </p>
 <p class="text-sm text-muted-foreground">
 类型：{{ credential.auth_type === 'ssh_key' ? 'SSH 密钥': 'Access Token' }}
 </p>
 </div>
 </div>
 <Separator class="bg-border/50" />
 <div>
 <label class="text-sm text-muted-foreground">Git 用户</label>
 <p class="text-sm mt-1">
 {{ credential.git_user_name }} &lt;{{ credential.git_user_email }}&gt;
 </p>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--lock] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground">
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
 <!-- 代码索引 -->
 <RepositoryIndexCard:repository-id="repository.id" />
 <!-- 索引健康与配置 ( + ) -->
 <WebhookConfigPanel:repository="repository" @updated="repositoriesStore.fetchRepository(repositoryId)" />
 <!-- 索引统计 -->
 <IndexStatsPanel:repository-id="repository.id" />
 <!-- 索引历史 -->
 <IndexHistoryList:repository-id="repository.id" />
 <!-- 关联项目 -->
 <div class="relative md:col-span-2">
 <div class="absolute -inset-1 bg-gradient-to-r from-blue-500/10 via-cyan-500/10 to-blue-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-blue-500/5 to-cyan-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--folder] text-blue-500" />
 关联项目
 </CardTitle>
 <CardDescription>使用此仓库的项目</CardDescription>
 </CardHeader>
 <CardContent class="pt-6">
 <div v-if="repository.projects && repository.projects.length === 0" class="text-center py-6 text-muted-foreground">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--folder] text-3xl" />
 </div>
 <p>暂无关联项目</p>
 </div>
 <div v-else class="space-y-2">
 <RouterLink
 v-for="(project, index) in repository.projects":key="project.id":to="`/projects/${project.id}`"
 class="flex items-center justify-between rounded-xl border border-border/50 bg-muted/30 hover:bg-muted/50 hover:border-blue-500/30 transition-all group"
 >
 <div class="flex items-center gap-4">
 <div class="w-8 rounded-lg bg-gradient-to-br from-blue-500/20 to-cyan-500/10 flex items-center justify-center text-sm font-medium text-blue-600">
 {{ index + 1 }}
 </div>
 <span class="font-medium group-hover:text-blue-600 transition-colors">{{ project.name }}</span>
 </div>
 <span class="icon-[lucide--chevron-right] text-muted-foreground group-hover:translate-x-1 transition-transform" />
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </div>
 </div>
 </template>
 <!-- 仓库不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="仓库不存在"
 description="未找到该仓库，可能已被删除"
 action-label="返回列表"
 gradient="from-violet-500/20 to-purple-500/20"
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
 <!-- 编辑对话框 -->
 <EditRepositoryModal
 v-if="repository"
 v-model="editDialogOpen":repository="repository"
 @confirm="handleEditSuccess"
 @cancel="editDialogOpen = false"
 @closed="editDialogOpen = false"
 />
 </div>
</template>
