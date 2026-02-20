<script setup lang="ts">
import { useHead } from '@vueuse/head'
import type { Runner } from '~/types'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
useHead({
 title: 'Runner 管理 - Friday AI',
})
const runnersStore = useRunnersStore
const { success, error: showError } = useToast
// 加载 Runner 列表
const loading = ref(true)
onMounted(async => {
 try {
 await runnersStore.fetchRunners
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取 Runner 列表')
 }
 finally {
 loading.value = false
 }
})
// 删除 Runner
const deleteDialogOpen = ref(false)
const runnerToDelete = ref<{ id: string, name: string } | null>(null)
const deleting = ref(false)
function confirmDelete(runner: Runner) {
 runnerToDelete.value = { id: runner.id, name: runner.name }
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!runnerToDelete.value)
 return
 deleting.value = true
 try {
 await runnersStore.removeRunner(runnerToDelete.value.id)
 success('删除成功', `Runner「${runnerToDelete.value.name}」已删除`)
 deleteDialogOpen.value = false
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除 Runner')
 }
 finally {
 deleting.value = false
 }
}
// 相对时间格式化
function formatTimeAgo(dateStr: string | null) {
 if (!dateStr) return '从未'
 return useTimeAgo(new Date(dateStr)).value
}
// 绝对时间格式化（用于 Tooltip）
function formatAbsoluteTime(dateStr: string | null) {
 if (!dateStr) return '从未连接'
 return new Date(dateStr).toLocaleString('zh-CN')
}
</script>
<template>
 <PageContainer>
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--server] text-2xl text-violet-500" />
 </div>
 <h1 class="text-2xl font-bold">
 Runner 管理
 </h1>
 </div>
 <p class="text-muted-foreground ml-12">
 管理和监控您的 Runner 实例
 </p>
 </div>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="card":count="3" />
 <!-- 空状态：渐变 SVG 插画 -->
 <div v-else-if="runnersStore.runners.length === 0" class="relative flex flex-col items-center justify-center py-20 text-center">
 <!-- 背景光晕 -->
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 bg-gradient-to-br from-violet-500/15 to-purple-500/15 rounded-full blur-3xl" />
 </div>
 <!-- 渐变 SVG 插画 -->
 <div class="relative mb-8">
 <svg width="160" height="120" viewBox="0 0 160 120" fill="none" xmlns="http://www.w3.org/2000/svg" class="drop-shadow-lg">
 <!-- 服务器机架 -->
 <rect x="30" y="20" width="100" height="80" rx="12" class="fill-card/80 stroke-border/50" stroke-width="1.5" />
 <!-- 玻璃质感渐变 -->
 <rect x="30" y="20" width="100" height="80" rx="12" fill="url(#glass)" />
 <!-- 服务器槽位 1 -->
 <rect x="42" y="32" width="76" height="16" rx="4" class="fill-muted/50" />
 <circle cx="108" cy="40" r="4" class="fill-muted-foreground/20" />
 <!-- 服务器槽位 2 -->
 <rect x="42" y="56" width="76" height="16" rx="4" class="fill-muted/50" />
 <circle cx="108" cy="64" r="4" class="fill-muted-foreground/20" />
 <!-- 服务器槽位 3 -->
 <rect x="42" y="80" width="76" height="16" rx="4" class="fill-muted/30" />
 <circle cx="108" cy="88" r="4" class="fill-muted-foreground/10" />
 <!-- 渐变定义 -->
 <defs>
 <linearGradient id="glass" x1="30" y1="20" x2="130" y2="100" gradientUnits="userSpaceOnUse">
 <stop stop-color="rgb(139 92 246)" stop-opacity="0.1" />
 <stop offset="1" stop-color="rgb(168 85 247)" stop-opacity="0.05" />
 </linearGradient>
 </defs>
 </svg>
 </div>
 <h3 class="text-lg font-semibold mb-2">
 暂无 Runner
 </h3>
 <p class="text-muted-foreground mb-8 max-w-sm leading-relaxed">
 还没有注册任何 Runner。创建注册令牌来添加您的第一个 Runner 实例。
 </p>
 <Button class="group relative overflow-hidden" @click="$router.push('/runners/tokens')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--key-round] mr-2" />
 管理注册令牌
 </Button>
 </div>
 <!-- Runner 卡片网格 -->
 <div v-else class="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
 <RouterLink
 v-for="runner in runnersStore.runners":key="runner.id":to="`/runners/${runner.id}`"
 class="group relative"
 >
 <!-- 悬浮光晕 -->
 <div class="absolute -inset-0.5 bg-gradient-to-r from-violet-500 to-purple-500 rounded-2xl opacity-0 group-hover:opacity-20 blur-lg transition-opacity duration-500" />
 <!-- 卡片主体 -->
 <div
 class="relative h-full rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50 group-hover:border-primary/30 group-hover:shadow-lg transition-all duration-300":class="{ 'opacity-60': runner.status === 'offline' }"
 >
 <!-- 头部：名称 + 状态 + 删除 -->
 <div class="flex items-center justify-between mb-4">
 <div class="flex items-center gap-2.5 min-w-0">
 <h3 class="text-lg font-semibold truncate group-hover:text-primary transition-colors">
 {{ runner.name }}
 </h3>
 <!-- 状态指示器 -->
 <div class="relative flex-shrink-0">
 <template v-if="runner.status === 'online'">
 <!-- 在线：绿色脉冲呼吸灯 -->
 <span class="absolute inline-flex w-3 rounded-full bg-emerald-400 opacity-75 animate-ping" />
 <span class="relative inline-flex w-3 rounded-full bg-emerald-500" />
 </template>
 <template v-else>
 <!-- 离线：灰色静止 -->
 <span class="inline-flex w-3 rounded-full bg-gray-400" />
 </template>
 </div>
 </div>
 <!-- 删除按钮 -->
 <Button
 variant="ghost"
 size="icon"
 class="flex-shrink-0 w-8 hover:bg-destructive/10 hover:text-destructive"
 @click.prevent.stop="confirmDelete(runner)"
 >
 <span class="icon-[lucide--trash-2] text-sm" />
 </Button>
 </div>
 <!-- 信息区 -->
 <div class="grid grid-cols-2 gap-y-2.5 gap-x-4 text-sm text-muted-foreground">
 <!-- 版本 -->
 <div class="flex items-center gap-1.5">
 <span class="icon-[lucide--tag] text-xs" />
 <span class="truncate">{{ runner.version || '-' }}</span>
 </div>
 <!-- IP -->
 <div class="flex items-center gap-1.5">
 <span class="icon-[lucide--globe] text-xs" />
 <span class="truncate">{{ runner.ip_address || '-' }}</span>
 </div>
 <!-- 并发数 -->
 <div class="flex items-center gap-1.5">
 <span class="icon-[lucide--layers] text-xs" />
 <span>并发 {{ runner.concurrent }}</span>
 </div>
 <!-- 当前任务 -->
 <div class="flex items-center gap-1.5">
 <span class="icon-[lucide--activity] text-xs" />
 <span>任务 {{ runner.current_tasks }}</span>
 </div>
 <!-- 最后心跳 -->
 <div class="col-span-2 flex items-center gap-1.5">
 <span class="icon-[lucide--clock] text-xs" />
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <span class="cursor-help border-b border-dotted border-muted-foreground/30">
 {{ formatTimeAgo(runner.last_heartbeat) }}
 </span>
 </TooltipTrigger>
 <TooltipContent>
 <p>{{ formatAbsoluteTime(runner.last_heartbeat) }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 </div>
 <!-- Tags 区 -->
 <div v-if="runner.tags.length > 0" class="flex items-center gap-1.5 flex-wrap mt-3 pt-3 border-t border-border/30">
 <Badge v-for="tag in runner.tags.slice(0, 3)":key="tag" variant="secondary" class="text-xs">
 {{ tag }}
 </Badge>
 <Badge v-if="runner.tags.length > 3" variant="outline" class="text-xs text-muted-foreground">
 +{{ runner.tags.length - 3 }}
 </Badge>
 </div>
 </div>
 </RouterLink>
 </div>
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除 Runner":description="`确定要删除 Runner「${runnerToDelete?.name}」吗？此操作不可撤销。`"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </PageContainer>
</template>
