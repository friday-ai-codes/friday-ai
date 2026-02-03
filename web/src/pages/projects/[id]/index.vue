<script setup lang="ts">
import type { ClaudeConfigRead } from '~/api/settings'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { refreshWebhookToken, updateWebhookToken } from '~/api/projects'
import { getProjectClaudeConfig } from '~/api/settings'
import BaseModal from '~/components/modal/BaseModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute('/projects/[id]/')
const router = useRouter
const projectsStore = useProjectsStore
const repositoriesStore = useRepositoriesStore
const executionsStore = useExecutionsStore
const { success, error: showError } = useToast
const { copy } = useClipboard
const projectId = computed( => route.params.id)
useHead({
 title: computed( => projectsStore.currentProject?.name
 ? `${projectsStore.currentProject.name} - Friday AI`: '项目详情 - Friday AI'),
})
// 加载项目和相关任务
const loading = ref(true)
const claudeConfig = ref<ClaudeConfigRead | null>(null)
onMounted(async => {
 try {
 await Promise.all([
 projectsStore.fetchProject(projectId.value),
 projectsStore.fetchFeishuConfig(projectId.value),
 executionsStore.fetchExecutions(undefined, projectId.value),
 repositoriesStore.fetchRepositories,
 ])
 try {
 claudeConfig.value = await getProjectClaudeConfig(projectId.value)
 }
 catch {
 claudeConfig.value = null
 }
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取项目详情')
 }
 finally {
 loading.value = false
 }
})
// 删除项目
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 deleting.value = true
 try {
 await projectsStore.deleteProject(projectId.value)
 success('删除成功', '项目已删除')
 router.push('/projects')
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除项目')
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
const project = computed( => projectsStore.currentProject)
const feishuConfig = computed( => projectsStore.currentFeishuConfig)
const projectExecutions = computed( => executionsStore.executions)
// 关联仓库 - 穿梭框模式
const linkDialogOpen = ref(false)
const selectedToLink = ref<Set<string>>(new Set)
const selectedToUnlink = ref<Set<string>>(new Set)
const linking = ref(false)
const availableRepositories = computed( => {
 if (!project.value)
 return
 const linkedIds = project.value.repositories?.map(r => r.id) ??
 return repositoriesStore.repositories.filter(r => !linkedIds.includes(r.id))
})
const linkedRepositories = computed( => {
 return project.value?.repositories ??
})
function toggleSelectToLink(id: string) {
 if (selectedToLink.value.has(id)) {
 selectedToLink.value.delete(id)
 }
 else {
 selectedToLink.value.add(id)
 }
}
function toggleSelectToUnlink(id: string) {
 if (selectedToUnlink.value.has(id)) {
 selectedToUnlink.value.delete(id)
 }
 else {
 selectedToUnlink.value.add(id)
 }
}
function selectAllAvailable {
 availableRepositories.value.forEach(r => selectedToLink.value.add(r.id))
}
function clearSelectToLink {
 selectedToLink.value.clear
}
function selectAllLinked {
 linkedRepositories.value.forEach(r => selectedToUnlink.value.add(r.id))
}
function clearSelectToUnlink {
 selectedToUnlink.value.clear
}
async function handleLinkSelected {
 if (selectedToLink.value.size === 0)
 return
 linking.value = true
 try {
 const promises = Array.from(selectedToLink.value).map(id =>
 projectsStore.addRepository(projectId.value, id),
 )
 await Promise.all(promises)
 success('关联成功', `已关联 ${selectedToLink.value.size} 个仓库`)
 selectedToLink.value.clear
 }
 catch (e) {
 showError('关联失败', e instanceof Error ? e.message: '无法关联仓库')
 }
 finally {
 linking.value = false
 }
}
async function handleUnlinkSelected {
 if (selectedToUnlink.value.size === 0)
 return
 linking.value = true
 try {
 const promises = Array.from(selectedToUnlink.value).map(id =>
 projectsStore.removeRepository(projectId.value, id),
 )
 await Promise.all(promises)
 success('解除关联成功', `已解除 ${selectedToUnlink.value.size} 个仓库`)
 selectedToUnlink.value.clear
 }
 catch (e) {
 showError('解除关联失败', e instanceof Error ? e.message: '无法解除关联仓库')
 }
 finally {
 linking.value = false
 }
}
function openLinkDialog {
 selectedToLink.value.clear
 selectedToUnlink.value.clear
 linkDialogOpen.value = true
}
// Webhook Token 管理
async function copyWebhookToken {
 if (!project.value?.webhook_token)
 return
 await copy(project.value.webhook_token)
 success('已复制', 'Webhook Token 已复制到剪贴板')
}
const refreshTokenDialogOpen = ref(false)
const refreshingToken = ref(false)
async function handleRefreshToken {
 refreshingToken.value = true
 try {
 await refreshWebhookToken(projectId.value)
 await projectsStore.fetchProject(projectId.value)
 success('刷新成功', '已生成新的 Webhook Token')
 refreshTokenDialogOpen.value = false
 }
 catch (e) {
 showError('刷新失败', e instanceof Error ? e.message: '无法刷新 Token')
 }
 finally {
 refreshingToken.value = false
 }
}
const customTokenDialogOpen = ref(false)
const customTokenValue = ref('')
const customTokenLoading = ref(false)
function openCustomTokenDialog {
 customTokenValue.value = project.value?.webhook_token || ''
 customTokenDialogOpen.value = true
}
async function handleCustomToken {
 if (!customTokenValue.value.trim) {
 showError('验证错误', 'Token 不能为空')
 return
 }
 if (customTokenValue.value.length > 32) {
 showError('验证错误', 'Token 长度不能超过 32 个字符')
 return
 }
 customTokenLoading.value = true
 try {
 await updateWebhookToken(projectId.value, { token: customTokenValue.value })
 await projectsStore.fetchProject(projectId.value)
 success('保存成功', 'Webhook Token 已更新')
 customTokenDialogOpen.value = false
 }
 catch (e) {
 showError('保存失败', e instanceof Error ? e.message: '无法更新 Token')
 }
 finally {
 customTokenLoading.value = false
 }
}
</script>
<template>
 <div class="space-y-8">
 <!-- 返回按钮 -->
 <RouterLink to="/projects" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回项目列表
 </RouterLink>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="4" />
 <!-- 项目详情 -->
 <template v-else-if="project">
 <!-- 头部 -->
 <div class="flex items-start justify-between">
 <div class="space-y-2">
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-500/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-2xl text-blue-500" />
 </div>
 <div>
 <h1 class="text-2xl font-bold">
 {{ project.name }}
 </h1>
 <p class="text-sm text-muted-foreground">
 {{ project.description || '暂无描述' }}
 </p>
 </div>
 </div>
 </div>
 <div class="flex items-center gap-2">
 <RouterLink:to="`/projects/${project.id}/edit`">
 <Button variant="outline" class="group">
 <span class="icon-[lucide--pencil] mr-2 group-hover:scale-110 transition-transform" />
 编辑
 </Button>
 </RouterLink>
 <Button variant="destructive" class="group" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-2 group-hover:scale-110 transition-transform" />
 删除
 </Button>
 </div>
 </div>
 <div class="grid gap-6 md:grid-cols-2">
 <!-- 基本信息 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-blue-500/10 via-cyan-500/10 to-blue-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-blue-500/5 to-cyan-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--info] text-blue-500" />
 基本信息
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-4 pt-6">
 <div>
 <label class="text-sm text-muted-foreground">飞书项目 Key</label>
 <p class="font-mono text-sm mt-1">
 {{ project.feishu_project_key || '未配置' }}
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div class="flex gap-8">
 <div>
 <label class="text-sm text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(project.created_at) }}
 </p>
 </div>
 <div>
 <label class="text-sm text-muted-foreground">更新时间</label>
 <p class="text-sm mt-1">
 {{ formatDate(project.updated_at) }}
 </p>
 </div>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 关联仓库 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 via-purple-500/10 to-violet-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-violet-500/5 to-purple-500/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--git-branch] text-violet-500" />
 关联仓库
 </CardTitle>
 <CardDescription>关联的 Git 仓库</CardDescription>
 </div>
 <Button variant="outline" size="sm" class="group" @click="openLinkDialog">
 <span class="icon-[lucide--settings-2] mr-2 group-hover:rotate-90 transition-transform" />
 管理仓库
 </Button>
 </CardHeader>
 <CardContent class="pt-6">
 <div v-if="project.repositories?.length === 0" class="text-center py-6 text-muted-foreground">
 <span class="icon-[lucide--git-branch] text-3xl mb-2 block opacity-50" />
 暂无关联仓库
 </div>
 <div v-else class="space-y-3">
 <div
 v-for="repo in project.repositories":key="repo.id"
 class="flex items-center justify-between rounded-xl border border-border/50 bg-muted/30 hover:bg-muted/50 transition-colors"
 >
 <div>
 <div class="flex items-center gap-2">
 <span class="font-medium">{{ repo.name }}</span>
 <Badge variant="outline" class="text-xs">
 {{ PLATFORM_LABELS[repo.git_platform] }}
 </Badge>
 </div>
 <div class="text-sm text-muted-foreground mt-1 font-mono text-xs">
 {{ repo.git_url }}
 </div>
 </div>
 <RouterLink:to="`/repositories/${repo.id}`">
 <Button variant="ghost" size="icon" class=" w-8" title="查看详情">
 <span class="icon-[lucide--eye]" />
 </Button>
 </RouterLink>
 </div>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 飞书配置 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-emerald-500/10 via-green-500/10 to-emerald-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-emerald-500/5 to-green-500/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--message-square] text-emerald-500" />
 飞书配置
 </CardTitle>
 <CardDescription>飞书项目 Webhook 集成</CardDescription>
 </div>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button variant="outline" size="sm" class="group">
 <span class="icon-[lucide--settings] mr-2 group-hover:rotate-90 transition-transform" />
 管理配置
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent class="pt-6">
 <div v-if="feishuConfig?.is_configured" class="flex items-center gap-3">
 <div class=" rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-2xl text-emerald-500" />
 </div>
 <div>
 <p class="font-medium">
 已配置
 </p>
 <p class="text-sm text-muted-foreground">
 插件 ID：{{ feishuConfig.plugin_id }}
 </p>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--link] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground">
 尚未配置飞书集成
 </p>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button class="mt-4" size="sm">
 配置飞书
 </Button>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- Claude 配置 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-orange-500/10 via-amber-500/10 to-orange-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-orange-500/5 to-amber-500/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--bot] text-orange-500" />
 Claude 配置
 </CardTitle>
 <CardDescription>AI 开发任务配置</CardDescription>
 </div>
 <RouterLink:to="`/projects/${project.id}/claude`">
 <Button variant="outline" size="sm" class="group">
 <span class="icon-[lucide--bot] mr-2 group-hover:scale-110 transition-transform" />
 管理配置
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent class="pt-6">
 <div v-if="claudeConfig?.has_api_key" class="flex items-center gap-3">
 <div class=" rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-2xl text-emerald-500" />
 </div>
 <div>
 <p class="font-medium">
 已配置
 </p>
 <p class="text-sm text-muted-foreground">
 来源：{{ claudeConfig.source === 'project' ? '项目配置': claudeConfig.source === 'system' ? '系统默认': '环境变量' }}
 </p>
 <p v-if="claudeConfig.base_url" class="text-sm text-muted-foreground">
 Base URL：{{ claudeConfig.base_url }}
 </p>
 </div>
 </div>
 <div v-else class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--bot] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground">
 尚未配置 Claude API 密钥
 </p>
 <RouterLink:to="`/projects/${project.id}/claude`">
 <Button class="mt-4" size="sm">
 配置 Claude
 </Button>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- Webhook Token 管理 -->
 <div class="relative md:col-span-2">
 <div class="absolute -inset-1 bg-gradient-to-r from-cyan-500/10 via-blue-500/10 to-cyan-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-cyan-500/5 to-blue-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--key] text-cyan-500" />
 Webhook Token
 </CardTitle>
 <CardDescription>用于验证飞书 Webhook 请求的来源</CardDescription>
 </CardHeader>
 <CardContent class="space-y-4 pt-6">
 <div class="space-y-2">
 <Label class="text-muted-foreground">当前 Token</Label>
 <div class="flex items-center gap-2">
 <code class="flex-1 px-4 py-3 bg-muted/50 rounded-xl font-mono text-sm overflow-hidden text-ellipsis border border-border/50">
 {{ project.webhook_token }}
 </code>
 <Button
 variant="outline"
 size="icon"
 class=" w-11"
 title="复制 Token"
 @click="copyWebhookToken"
 >
 <span class="icon-[lucide--copy]" />
 </Button>
 </div>
 </div>
 <div class="flex items-start gap-3 rounded-xl bg-amber-500/10 border border-amber-500/20">
 <span class="icon-[lucide--alert-triangle] text-xl text-amber-500 shrink-0 mt-0.5" />
 <p class="text-sm text-amber-700 dark:text-amber-300">
 请勿泄露此 Token，它用于验证 Webhook 请求的来源。如果 Token 泄露，请立即刷新。
 </p>
 </div>
 <div class="flex gap-3">
 <Button variant="outline" class="group" @click="refreshTokenDialogOpen = true">
 <span class="icon-[lucide--refresh-cw] mr-2 group-hover:rotate-180 transition-transform duration-500" />
 刷新 Token
 </Button>
 <Button variant="outline" class="group" @click="openCustomTokenDialog">
 <span class="icon-[lucide--pencil] mr-2 group-hover:scale-110 transition-transform" />
 自定义 Token
 </Button>
 </div>
 </CardContent>
 </Card>
 </div>
 </div>
 <!-- 相关执行 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-amber-500/10 via-orange-500/10 to-amber-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-amber-500/5 to-orange-500/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--layers] text-amber-500" />
 相关执行
 </CardTitle>
 <CardDescription>此项目下的工作流执行记录</CardDescription>
 </div>
 <RouterLink:to="`/executions?project_id=${project.id}`">
 <Button variant="outline" size="sm" class="group">
 查看全部
 <span class="icon-[lucide--arrow-right] ml-2 group-hover:translate-x-1 transition-transform" />
 </Button>
 </RouterLink>
 </CardHeader>
 <CardContent class="pt-6">
 <div v-if="projectExecutions.length === 0" class="text-center py-8 text-muted-foreground">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--inbox] text-3xl" />
 </div>
 <p>暂无执行记录</p>
 </div>
 <div v-else class="space-y-2">
 <RouterLink
 v-for="(execution, index) in projectExecutions.slice(0, 5)":key="execution.id":to="`/executions/${execution.id}`"
 class="flex items-center justify-between rounded-xl border border-border/50 bg-muted/30 hover:bg-muted/50 hover:border-amber-500/30 transition-all group"
 >
 <div class="flex items-center gap-4">
 <div class="w-8 rounded-lg bg-gradient-to-br from-amber-500/20 to-orange-500/10 flex items-center justify-center text-sm font-medium text-amber-600">
 {{ index + 1 }}
 </div>
 <div>
 <span class="font-medium group-hover:text-amber-600 transition-colors">{{ execution.workflow_name }}</span>
 <Badge
 class="ml-3":class="{
 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300': execution.status === 'pending',
 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300': execution.status === 'running',
 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300': execution.status === 'completed',
 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300': execution.status === 'failed',
 'bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300': execution.status === 'waiting_approval',
 }"
 >
 {{ execution.status === 'pending' ? '等待中': execution.status === 'running' ? '运行中': execution.status === 'completed' ? '已完成': execution.status === 'failed' ? '失败': execution.status === 'waiting_approval' ? '待审批': execution.status }}
 </Badge>
 </div>
 </div>
 <div class="flex items-center gap-3">
 <span class="text-sm text-muted-foreground">
 {{ formatDate(execution.created_at) }}
 </span>
 <span class="icon-[lucide--chevron-right] text-muted-foreground group-hover:translate-x-1 transition-transform" />
 </div>
 </RouterLink>
 </div>
 </CardContent>
 </Card>
 </div>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目，可能已被删除"
 action-label="返回列表"
 gradient="from-blue-500/20 to-cyan-500/20"
 @action="router.push('/projects')"
 />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除项目"
 description="确定要删除此项目吗？此操作不可撤销，相关的凭证配置也将被删除。"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
 <!-- 管理仓库关联对话框 - 穿梭框样式 -->
 <BaseModal
 v-model="linkDialogOpen"
 title="管理仓库关联"
 size="md"
 >
 <div class="space-y-4">
 <p class="text-sm text-muted-foreground">
 在左侧选择要关联的仓库，在右侧选择要解除关联的仓库
 </p>
 <div class="grid grid-cols-2 gap-6">
 <!-- 左侧：可用仓库 -->
 <div class="flex flex-col">
 <!-- 标题栏 - 固定高度 -->
 <div class="flex items-center justify-between mb-3">
 <h4 class="text-sm font-medium flex items-center gap-2">
 <span class="icon-[lucide--inbox] text-muted-foreground" />
 可用仓库
 <span class="text-xs text-muted-foreground font-normal">({{ availableRepositories.length }})</span>
 </h4>
 <div class="flex items-center gap-1">
 <Button
 v-if="availableRepositories.length > 0"
 variant="ghost"
 size="sm"
 class=" px-2 text-xs"
 @click="selectAllAvailable"
 >
 全选
 </Button>
 <Button
 v-if="selectedToLink.size > 0"
 variant="ghost"
 size="sm"
 class=" px-2 text-xs"
 @click="clearSelectToLink"
 >
 清空
 </Button>
 </div>
 </div>
 <!-- 列表区域 - 固定高度 -->
 <div class="border border-border/50 rounded-xl bg-muted/20 overflow-y-auto mb-3">
 <div v-if="availableRepositories.length === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground">
 <span class="icon-[lucide--package] text-2xl mb-2 opacity-50" />
 <span class="text-sm">没有可用仓库</span>
 </div>
 <div v-else class=" space-y-1">
 <div
 v-for="repo in availableRepositories":key="repo.id"
 class="flex items-center gap-3 .5 rounded-lg cursor-pointer transition-colors":class="selectedToLink.has(repo.id) ? 'bg-primary/10 border border-primary/30': 'hover:bg-muted/50 border border-transparent'"
 @click="toggleSelectToLink(repo.id)"
 >
 <div
 class="w-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors":class="selectedToLink.has(repo.id) ? 'bg-primary border-primary': 'border-muted-foreground/30'"
 >
 <span v-if="selectedToLink.has(repo.id)" class="icon-[lucide--check] text-xs text-primary-foreground" />
 </div>
 <div class="min-w-0 flex-1">
 <div class="font-medium text-sm truncate">
 {{ repo.name }}
 </div>
 <div class="text-xs text-muted-foreground truncate">
 {{ repo.git_url }}
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 操作按钮 - 固定高度 -->
 <Button
 class="w-full group":disabled="selectedToLink.size === 0 || linking"
 @click="handleLinkSelected"
 >
 <span v-if="linking" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--arrow-right] mr-2 group-hover:translate-x-1 transition-transform" />
 关联选中 ({{ selectedToLink.size }})
 </Button>
 </div>
 <!-- 右侧：已关联仓库 -->
 <div class="flex flex-col">
 <!-- 标题栏 - 固定高度 -->
 <div class="flex items-center justify-between mb-3">
 <h4 class="text-sm font-medium flex items-center gap-2">
 <span class="icon-[lucide--link] text-violet-500" />
 已关联仓库
 <span class="text-xs text-muted-foreground font-normal">({{ linkedRepositories.length }})</span>
 </h4>
 <div class="flex items-center gap-1">
 <Button
 v-if="linkedRepositories.length > 0"
 variant="ghost"
 size="sm"
 class=" px-2 text-xs"
 @click="selectAllLinked"
 >
 全选
 </Button>
 <Button
 v-if="selectedToUnlink.size > 0"
 variant="ghost"
 size="sm"
 class=" px-2 text-xs"
 @click="clearSelectToUnlink"
 >
 清空
 </Button>
 </div>
 </div>
 <!-- 列表区域 - 固定高度 -->
 <div class="border border-border/50 rounded-xl bg-muted/20 overflow-y-auto mb-3">
 <div v-if="linkedRepositories.length === 0" class="flex flex-col items-center justify-center h-full text-muted-foreground">
 <span class="icon-[lucide--unlink] text-2xl mb-2 opacity-50" />
 <span class="text-sm">暂无关联仓库</span>
 </div>
 <div v-else class=" space-y-1">
 <div
 v-for="repo in linkedRepositories":key="repo.id"
 class="flex items-center gap-3 .5 rounded-lg cursor-pointer transition-colors":class="selectedToUnlink.has(repo.id) ? 'bg-destructive/10 border border-destructive/30': 'hover:bg-muted/50 border border-transparent'"
 @click="toggleSelectToUnlink(repo.id)"
 >
 <div
 class="w-5 rounded border-2 flex items-center justify-center shrink-0 transition-colors":class="selectedToUnlink.has(repo.id) ? 'bg-destructive border-destructive': 'border-muted-foreground/30'"
 >
 <span v-if="selectedToUnlink.has(repo.id)" class="icon-[lucide--check] text-xs text-destructive-foreground" />
 </div>
 <div class="min-w-0 flex-1">
 <div class="font-medium text-sm truncate">
 {{ repo.name }}
 </div>
 <div class="text-xs text-muted-foreground truncate">
 {{ repo.git_url }}
 </div>
 </div>
 </div>
 </div>
 </div>
 <!-- 操作按钮 - 固定高度 -->
 <Button
 variant="outline"
 class="w-full group text-destructive hover:bg-destructive/10":disabled="selectedToUnlink.size === 0 || linking"
 @click="handleUnlinkSelected"
 >
 <span v-if="linking" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 <span v-else class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 解除关联 ({{ selectedToUnlink.size }})
 </Button>
 </div>
 </div>
 <p v-if="availableRepositories.length === 0 && linkedRepositories.length === 0" class="text-sm text-muted-foreground text-center py-2">
 没有可用的仓库，请先<RouterLink to="/repositories/new" class="text-primary hover:underline">
 创建仓库
 </RouterLink>
 </p>
 </div>
 <template #footer>
 <div class="flex justify-end w-full">
 <Button variant="outline" @click="linkDialogOpen = false">
 完成
 </Button>
 </div>
 </template>
 </BaseModal>
 <!-- 刷新 Token 确认对话框 -->
 <ConfirmDialog
 v-model:open="refreshTokenDialogOpen"
 title="刷新 Webhook Token"
 description="刷新后，旧的 Token 将立即失效。请确保在飞书项目自动化规则中更新新的 Token，否则 Webhook 请求将无法验证通过。"
 confirm-text="刷新"
 variant="destructive":loading="refreshingToken"
 @confirm="handleRefreshToken"
 />
 <!-- 自定义 Token 对话框 -->
 <BaseModal
 v-model="customTokenDialogOpen"
 title="自定义 Webhook Token"
 size="md"
 >
 <div class="space-y-4">
 <p class="text-sm text-muted-foreground">
 输入自定义 Token（最大 32 字符），用于在飞书项目自动化规则中配置
 </p>
 <div class="py-2 space-y-4">
 <div class="space-y-2">
 <Label for="customToken">Token</Label>
 <Input
 id="customToken"
 v-model="customTokenValue"
 placeholder="输入自定义 Token"
 maxlength="32"
 class=" bg-muted/30 border-border/50 focus:border-primary/50"
 />
 <p class="text-sm text-muted-foreground">
 {{ customTokenValue.length }}/32 字符
 </p>
 </div>
 </div>
 </div>
 <template #footer>
 <div class="flex justify-end gap-3 w-full">
 <Button variant="outline" @click="customTokenDialogOpen = false">
 取消
 </Button>
 <Button:disabled="customTokenLoading" class="group relative overflow-hidden" @click="handleCustomToken">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="customTokenLoading" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 {{ customTokenLoading ? '保存中...': '保存' }}
 </Button>
 </div>
 </template>
 </BaseModal>
</template>
