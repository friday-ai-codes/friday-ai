<script setup lang="ts">
/**
 * 项目仓库管理标签页
 * 管理项目关联的代码仓库，支持批量关联、权限级别管理
 */
import type { ProjectRepositoryLink, Repository, RepositoryPermissionLevel } from '~/types'
import { useHead } from '@vueuse/head'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import {
 getProjectRepositories,
 linkRepositories,
 unlinkRepository,
 updateRepositoryLink,
} from '~/api/projects'
import { repositoriesApi } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { PLATFORM_LABELS } from '~/types'
const route = useRoute('/projects/[id]/repositories')
const projectId = computed( => route.params.id)
const { isProjectAdmin, isViewer } = usePermission(projectId)
const { handleError } = useErrorHandler
const { success } = useToast
useHead({ title: '仓库管理 - Friday AI' })
// 数据状态
const links = ref<ProjectRepositoryLink>
const allRepositories = ref<Repository>
const loading = ref(true)
// 对话框状态
const dialogOpen = ref(false)
const searchQuery = ref('')
const selectedRepoIds = ref<Set<string>>(new Set)
const linking = ref(false)
// 已关联仓库的 repository_id 集合
const linkedRepoIds = computed( => new Set(links.value.map(l => l.repository_id)))
// 可用仓库（过滤掉已关联的）+ 搜索
const filteredAvailableRepos = computed( => {
 const query = searchQuery.value.toLowerCase
 return allRepositories.value
 .filter(r => !linkedRepoIds.value.has(r.id))
 .filter(r => !query || r.name.toLowerCase.includes(query))
})
// 加载数据
async function loadLinks {
 try {
 links.value = await getProjectRepositories(projectId.value)
 }
 catch (e: unknown) {
 handleError(e, '加载仓库关联')
 }
}
onMounted(async => {
 try {
 await loadLinks
 }
 finally {
 loading.value = false
 }
})
// 打开关联对话框
async function openLinkDialog {
 dialogOpen.value = true
 searchQuery.value = ''
 selectedRepoIds.value.clear
 try {
 allRepositories.value = await repositoriesApi.list
 }
 catch (e: unknown) {
 handleError(e, '加载仓库列表')
 }
}
// 切换仓库选择
function toggleRepo(repoId: string) {
 if (selectedRepoIds.value.has(repoId)) {
 selectedRepoIds.value.delete(repoId)
 }
 else {
 selectedRepoIds.value.add(repoId)
 }
}
// 确认关联
async function handleLink {
 if (selectedRepoIds.value.size === 0)
 return
 linking.value = true
 try {
 const result = await linkRepositories(projectId.value, {
 repository_ids: Array.from(selectedRepoIds.value),
 })
 success(`已关联 ${result.created.length} 个仓库`)
 await loadLinks
 dialogOpen.value = false
 }
 catch (e: unknown) {
 handleError(e, '关联仓库')
 }
 finally {
 linking.value = false
 }
}
// 切换权限级别
async function togglePermission(link: ProjectRepositoryLink) {
 const newLevel: RepositoryPermissionLevel = link.permission_level === 'read_write' ? 'read_only': 'read_write'
 try {
 const updated = await updateRepositoryLink(projectId.value, link.id, { permission_level: newLevel })
 const idx = links.value.findIndex(l => l.id === link.id)
 if (idx >= 0)
 links.value[idx] = updated
 success(`权限已更新为${newLevel === 'read_write' ? '读写': '只读'}`)
 }
 catch (e: unknown) {
 handleError(e, '更新权限')
 }
}
// 移除关联
async function handleUnlink(link: ProjectRepositoryLink) {
 try {
 await unlinkRepository(projectId.value, link.id)
 links.value = links.value.filter(l => l.id !== link.id)
 success(`已移除 ${link.repository_name}`)
 }
 catch (e: unknown) {
 handleError(e, '移除关联')
 }
}
// 权限级别标签
function permissionLabel(level: RepositoryPermissionLevel) {
 return level === 'read_write' ? '读写': '只读'
}
</script>
<template>
 <div class="space-y-8">
 <!-- 返回按钮 -->
 <RouterLink:to="`/projects/${projectId}`" class="group inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors">
 <span class="icon-[lucide--arrow-left] mr-2 group-hover:-translate-x-1 transition-transform" />
 返回项目详情
 </RouterLink>
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--git-branch] text-2xl text-violet-500" />
 </div>
 <div>
 <h1 class="text-2xl font-bold">
 仓库管理
 </h1>
 <p class="text-muted-foreground">
 管理项目关联的代码仓库
 </p>
 </div>
 </div>
 </div>
 <TooltipProvider v-if="isProjectAdmin || isViewer">
 <Tooltip>
 <TooltipTrigger as-child>
 <div>
 <Button
 class="group relative overflow-hidden":disabled="isViewer"
 @click="openLinkDialog"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 关联仓库
 </Button>
 </div>
 </TooltipTrigger>
 <TooltipContent v-if="isViewer">
 无权限
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="links.length === 0"
 icon="lucide--git-branch"
 title="暂无关联仓库"
 description="将仓库关联到此项目以开始使用":action-label="isProjectAdmin ? '关联仓库': undefined"
 gradient="from-violet-500/20 to-purple-500/20"
 @action="openLinkDialog"
 />
 <!-- 仓库列表表格 -->
 <div v-else class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 via-purple-500/10 to-violet-500/10 rounded-3xl blur-xl opacity-70" />
 <div class="card overflow-hidden">
 <table class="w-full">
 <thead>
 <tr class="border-b border-border/50 bg-muted/30">
 <th class="text-left px-6 py-4 text-sm font-medium text-muted-foreground">
 仓库名称
 </th>
 <th class="text-left px-6 py-4 text-sm font-medium text-muted-foreground">
 权限级别
 </th>
 <th class="text-left px-6 py-4 text-sm font-medium text-muted-foreground">
 关联时间
 </th>
 <th v-if="isProjectAdmin || isViewer" class="text-right px-6 py-4 text-sm font-medium text-muted-foreground">
 操作
 </th>
 </tr>
 </thead>
 <tbody>
 <tr
 v-for="link in links":key="link.id"
 class="border-b border-border/30 last:border-0 hover:bg-muted/20 transition-colors"
 >
 <td class="px-6 py-4">
 <div class="font-medium">
 {{ link.repository_name }}
 </div>
 </td>
 <td class="px-6 py-4">
 <TooltipProvider v-if="isProjectAdmin">
 <Tooltip>
 <TooltipTrigger as-child>
 <button @click="togglePermission(link)">
 <Badge:variant="link.permission_level === 'read_write' ? 'default': 'secondary'"
 class="cursor-pointer hover:opacity-80 transition-opacity"
 >
 {{ permissionLabel(link.permission_level) }}
 </Badge>
 </button>
 </TooltipTrigger>
 <TooltipContent>
 点击切换为{{ link.permission_level === 'read_write' ? '只读': '读写' }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 <Badge
 v-else:variant="link.permission_level === 'read_write' ? 'default': 'secondary'"
 >
 {{ permissionLabel(link.permission_level) }}
 </Badge>
 </td>
 <td class="px-6 py-4 text-sm text-muted-foreground">
 {{ new Date(link.created_at).toLocaleString('zh-CN') }}
 </td>
 <td v-if="isProjectAdmin || isViewer" class="px-6 py-4 text-right">
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <div class="inline-block">
 <Button
 variant="ghost"
 size="sm"
 class="hover:bg-destructive/10 hover:text-destructive":disabled="isViewer"
 @click="handleUnlink(link)"
 >
 <span class="icon-[lucide--unlink] mr-1.5" />
 移除
 </Button>
 </div>
 </TooltipTrigger>
 <TooltipContent v-if="isViewer">
 无权限
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </td>
 </tr>
 </tbody>
 </table>
 </div>
 </div>
 <!-- 关联仓库对话框 -->
 <Dialog v-model:open="dialogOpen">
 <DialogContent class="sm:max-w-lg">
 <DialogHeader>
 <DialogTitle>关联仓库</DialogTitle>
 <DialogDescription>
 选择要关联到此项目的仓库
 </DialogDescription>
 </DialogHeader>
 <div class="space-y-4">
 <!-- 搜索框 -->
 <Input
 v-model="searchQuery"
 placeholder="搜索仓库名称..."
 class="bg-muted/30 border-border/50"
 >
 <template #prefix>
 <span class="icon-[lucide--search] text-muted-foreground" />
 </template>
 </Input>
 <!-- 仓库列表 -->
 <div class="max- overflow-y-auto space-y-1 border border-border/50 rounded-xl bg-muted/20">
 <div
 v-if="filteredAvailableRepos.length === 0"
 class="flex flex-col items-center justify-center py-8 text-muted-foreground"
 >
 <span class="icon-[lucide--package] text-2xl mb-2 opacity-50" />
 <span class="text-sm">{{ searchQuery ? '没有匹配的仓库': '没有可关联的仓库' }}</span>
 </div>
 <div
 v-for="repo in filteredAvailableRepos":key="repo.id"
 class="flex items-center gap-3 rounded-lg cursor-pointer transition-colors":class="selectedRepoIds.has(repo.id) ? 'bg-primary/10 border border-primary/30': 'hover:bg-muted/50 border border-transparent'"
 @click="toggleRepo(repo.id)"
 >
 <Checkbox:model-value="selectedRepoIds.has(repo.id)"
 @click.stop
 @update:model-value="toggleRepo(repo.id)"
 />
 <div class="min-w-0 flex-1">
 <div class="flex items-center gap-2">
 <span class="font-medium text-sm">{{ repo.name }}</span>
 <Badge variant="outline" class="text-xs">
 {{ PLATFORM_LABELS[repo.git_platform] }}
 </Badge>
 </div>
 <div class="text-xs text-muted-foreground truncate mt-0.5">
 {{ repo.git_url }}
 </div>
 </div>
 </div>
 </div>
 </div>
 <DialogFooter>
 <Button variant="outline" @click="dialogOpen = false">
 取消
 </Button>
 <Button:disabled="selectedRepoIds.size === 0 || linking"
 class="group relative overflow-hidden"
 @click="handleLink"
 >
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span v-if="linking" class="icon-[lucide--loader-circle] mr-2 animate-spin" />
 确认关联 ({{ selectedRepoIds.size }})
 </Button>
 </DialogFooter>
 </DialogContent>
 </Dialog>
 </div>
</template>
