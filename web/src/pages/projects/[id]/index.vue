<script setup lang="ts">
import type { ClaudeConfigRead } from '~/api/settings'
import { useClipboard } from '@vueuse/core'
import { useHead } from '@vueuse/head'
import { refreshWebhookToken, updateWebhookToken } from '~/api/projects'
import { getProjectClaudeConfig } from '~/api/settings'
import StatusBadge from '~/components/common/StatusBadge.vue'
import BaseModal from '~/components/modal/BaseModal.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'
import { Separator } from '~/components/ui/separator'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute('/projects/[id]/')
const router = useRouter
const projectsStore = useProjectsStore
const repositoriesStore = useRepositoriesStore
const executionsStore = useExecutionsStore
const { handleError } = useErrorHandler
const { success } = useToast
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
 const results = await Promise.allSettled([
 projectsStore.fetchProject(projectId.value),
 projectsStore.fetchFeishuConfig(projectId.value),
 executionsStore.fetchExecutions(undefined, projectId.value),
 repositoriesStore.fetchRepositories,
 ])
 // 逐个检查结果，失败的部分通过 toast 提示
 const names = ['项目信息', '飞书配置', '执行记录', '仓库列表']
 results.forEach((result, index) => {
 if (result.status === 'rejected') {
 handleError(result.reason, `加载${names[index]}`)
 }
 })
 // claudeConfig 单独处理，不在 allSettled 中
 try {
 claudeConfig.value = await getProjectClaudeConfig(projectId.value)
 }
 catch {
 claudeConfig.value = null
 }
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
 catch (e: unknown) {
 handleError(e, '删除项目')
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
 catch (e: unknown) {
 handleError(e, '关联仓库')
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
 catch (e: unknown) {
 handleError(e, '解除关联')
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
 catch (e: unknown) {
 handleError(e, '刷新 Token')
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
 handleError(new Error('Token 不能为空'), '验证')
 return
 }
 if (customTokenValue.value.length > 32) {
 handleError(new Error('Token 长度不能超过 32 个字符'), '验证')
 return
 }
 customTokenLoading.value = true
 try {
 await updateWebhookToken(projectId.value, { token: customTokenValue.value })
 await projectsStore.fetchProject(projectId.value)
 success('保存成功', 'Webhook Token 已更新')
 customTokenDialogOpen.value = false
 }
 catch (e: unknown) {
 handleError(e, '更新 Token')
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
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--folder-open] text-2xl text-primary" />
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
 <div class="grid gap-4 md:grid-cols-2">
 <!-- 基本信息 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--info] text-primary" />
 <h3 class="text-sm font-semibold">
 基本信息
 </h3>
 </div>
 <div class=" space-y-4">
 <div>
 <label class="text-xs text-muted-foreground">飞书项目 Key</label>
 <p class="font-mono text-sm mt-1 text-foreground">
 {{ project.feishu_project_key || '未配置' }}
 </p>
 </div>
 <Separator class="bg-border/50" />
 <div class="flex gap-8">
 <div>
 <label class="text-xs text-muted-foreground">创建时间</label>
 <p class="text-sm mt-1 text-foreground">
 {{ formatDate(project.created_at) }}
 </p>
 </div>
 <div>
 <label class="text-xs text-muted-foreground">更新时间</label>
 <p class="text-sm mt-1 text-foreground">
 {{ formatDate(project.updated_at) }}
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- 关联仓库 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--git-branch] text-primary" />
 <h3 class="text-sm font-semibold">
 关联仓库
 </h3>
 <span class="text-xs text-muted-foreground">({{ project.repositories?.length || 0 }})</span>
 </div>
 <Button variant="outline" size="sm" class=" text-xs" @click="openLinkDialog">
 <span class="icon-[lucide--settings-2] mr-1.5" />
 管理
 </Button>
 </div>
 <div class="">
 <div v-if="project.repositories?.length === 0" class="text-center py-6 text-muted-foreground">
 <span class="icon-[lucide--git-branch] text-2xl mb-2 block opacity-40" />
 <p class="text-sm">
 暂无关联仓库
 </p>
 </div>
 <div v-else class="space-y-2">
 <div
 v-for="repo in project.repositories":key="repo.id"
 class="flex items-center justify-between .5 rounded-lg border border-border/50 hover:bg-muted/40 transition-colors"
 >
 <div class="min-w-0 flex-1">
 <div class="flex items-center gap-2">
 <span class="text-sm font-medium text-foreground">{{ repo.name }}</span>
 <Badge variant="outline" class="text-xs">
 {{ PLATFORM_LABELS[repo.git_platform] }}
 </Badge>
 </div>
 <p class="text-xs text-muted-foreground mt-0.5 font-mono truncate">
 {{ repo.git_url }}
 </p>
 </div>
 <RouterLink:to="`/repositories/${repo.id}`">
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <Button variant="ghost" size="icon" class=" w-7">
 <span class="icon-[lucide--eye] text-sm" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>查看详情</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </RouterLink>
 </div>
 </div>
 </div>
 </div>
 <!-- 飞书配置 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--message-square] text-primary" />
 <h3 class="text-sm font-semibold">
 飞书配置
 </h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="feishuConfig?.is_configured" class="flex items-center gap-3">
 <div class=".5 rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-lg text-emerald-500" />
 </div>
 <div>
 <p class="text-sm font-medium text-foreground">
 已配置
 </p>
 <p class="text-xs text-muted-foreground">
 插件 ID：{{ feishuConfig.plugin_id }}
 </p>
 </div>
 </div>
 <div v-else class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--link] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">
 尚未配置飞书集成
 </p>
 </div>
 <RouterLink:to="`/projects/${project.id}/feishu`">
 <Button size="sm" class=" text-xs">
 配置
 </Button>
 </RouterLink>
 </div>
 </div>
 </div>
 <!-- Claude 配置 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--bot] text-primary" />
 <h3 class="text-sm font-semibold">
 Claude 配置
 </h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/claude`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="claudeConfig?.has_api_key" class="flex items-center gap-3">
 <div class=".5 rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-lg text-emerald-500" />
 </div>
 <div>
 <p class="text-sm font-medium text-foreground">
 已配置
 </p>
 <p class="text-xs text-muted-foreground">
 来源：{{ claudeConfig.source === 'project' ? '项目配置': claudeConfig.source === 'system' ? '系统默认': '环境变量' }}
 </p>
 <p v-if="claudeConfig.base_url" class="text-xs text-muted-foreground">
 Base URL：{{ claudeConfig.base_url }}
 </p>
 </div>
 </div>
 <div v-else class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--bot] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">
 尚未配置 Claude API 密钥
 </p>
 </div>
 <RouterLink:to="`/projects/${project.id}/claude`">
 <Button size="sm" class=" text-xs">
 配置
 </Button>
 </RouterLink>
 </div>
 </div>
 </div>
 <!-- Prompt 覆盖 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--file-text] text-primary" />
 <h3 class="text-sm font-semibold">
 Prompt 覆盖
 </h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/prompts`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--file-text] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">
 查看与编辑项目级提示词覆盖
 </p>
 <p class="text-xs text-muted-foreground">
 未覆盖的提示词会 fallback 到系统级
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- Provider 凭证（Phase / / ） -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--key-round] text-primary" />
 <h3 class="text-sm font-semibold">
 Provider 凭证
 </h3>
 </div>
 <RouterLink:to="`/projects/${project.id}/providers`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 管理
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div class="flex items-center gap-3 text-muted-foreground">
 <span class="icon-[lucide--key-round] text-lg opacity-40" />
 <div class="flex-1">
 <p class="text-sm">
 项目级 Provider 凭证覆盖
 </p>
 <p class="text-xs text-muted-foreground">
 仅本项目可见，覆盖系统默认
 </p>
 </div>
 </div>
 </div>
 </div>
 <!-- Webhook Token 管理 -->
 <div class="card md:col-span-2">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--key] text-primary" />
 <h3 class="text-sm font-semibold">
 Webhook Token
 </h3>
 <span class="text-xs text-muted-foreground ml-1">用于验证飞书 Webhook 请求的来源</span>
 </div>
 <div class=" space-y-4">
 <div class="space-y-2">
 <Label class="text-xs text-muted-foreground">当前 Token</Label>
 <div class="flex items-center gap-2">
 <code class="flex-1 px-3 py-2 bg-muted/40 rounded-lg font-mono text-sm overflow-hidden text-ellipsis border border-border/50 text-foreground">
 {{ project.webhook_token }}
 </code>
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <Button
 variant="outline"
 size="icon"
 class=" w-9"
 @click="copyWebhookToken"
 >
 <span class="icon-[lucide--copy]" />
 </Button>
 </TooltipTrigger>
 <TooltipContent>复制 Token</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 <div class="flex items-start gap-2.5 rounded-lg bg-amber-500/10 border border-amber-500/20">
 <span class="icon-[lucide--alert-triangle] text-amber-500 shrink-0 mt-0.5" />
 <p class="text-xs text-amber-700 dark:text-amber-300">
 请勿泄露此 Token。如果 Token 泄露，请立即刷新。
 </p>
 </div>
 <div class="flex gap-2">
 <Button variant="outline" size="sm" @click="refreshTokenDialogOpen = true">
 <span class="icon-[lucide--refresh-cw] mr-1.5" />
 刷新 Token
 </Button>
 <Button variant="outline" size="sm" @click="openCustomTokenDialog">
 <span class="icon-[lucide--pencil] mr-1.5" />
 自定义 Token
 </Button>
 </div>
 </div>
 </div>
 </div>
 <!-- 相关执行 -->
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--layers] text-primary" />
 <h3 class="text-sm font-semibold">
 相关执行
 </h3>
 </div>
 <RouterLink:to="`/executions?project_id=${project.id}`">
 <Button variant="ghost" size="sm" class=" text-xs group">
 查看全部
 <span class="icon-[lucide--arrow-right] ml-1 group-hover:translate-x-0.5 transition-transform" />
 </Button>
 </RouterLink>
 </div>
 <div class="">
 <div v-if="projectExecutions.length === 0" class="text-center py-6 text-muted-foreground">
 <span class="icon-[lucide--inbox] text-2xl mb-2 block opacity-40" />
 <p class="text-sm">
 暂无执行记录
 </p>
 </div>
 <div v-else class="space-y-1.5">
 <RouterLink
 v-for="(execution, index) in projectExecutions.slice(0, 5)":key="execution.id":to="`/executions/${execution.id}`"
 class="flex items-center justify-between rounded-lg hover:bg-muted/40 transition-colors group"
 >
 <div class="flex items-center gap-3">
 <div class="w-6 rounded bg-muted/60 flex items-center justify-center text-xs font-medium text-muted-foreground">
 {{ index + 1 }}
 </div>
 <div>
 <span class="text-sm font-medium text-foreground group-hover:text-primary transition-colors">{{ execution.workflow_name }}</span>
 <StatusBadge type="execution":status="execution.status" size="sm" class="ml-2" />
 </div>
 </div>
 <div class="flex items-center gap-2">
 <span class="text-xs text-muted-foreground">
 {{ formatDate(execution.created_at) }}
 </span>
 <span class="icon-[lucide--chevron-right] text-sm text-muted-foreground group-hover:translate-x-0.5 transition-transform" />
 </div>
 </RouterLink>
 </div>
 </div>
 </div>
 </template>
 <!-- 项目不存在 -->
 <EmptyState
 v-else
 icon="lucide--help-circle"
 title="项目不存在"
 description="未找到该项目，可能已被删除"
 action-label="返回列表"
 gradient="from-primary/20 to-primary/20"
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
 <span class="icon-[lucide--link] text-primary" />
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
 没有可用的仓库，请先<RouterLink to="/repositories" class="text-primary hover:underline">
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
 <span class="absolute inset-0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="customTokenLoading" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 {{ customTokenLoading ? '保存中...': '保存' }}
 </Button>
 </div>
 </template>
 </BaseModal>
</template>
