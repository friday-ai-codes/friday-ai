<script setup lang="ts">
import type { RunnerTaskAssignment } from '~/types'
import { useHead } from '@vueuse/head'
import { runnersApi } from '~/api'
import ConfirmDialog from '~/components/common/ConfirmDialog.vue'
import LoadingState from '~/components/common/LoadingState.vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import PageContainer from '~/components/layout/PageContainer.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
useHead({ title: 'Runner 详情 - Friday AI' })
const route = useRoute('/runners/[id]')
const router = useRouter
const runnersStore = useRunnersStore
const { success, error: showError } = useToast
// WS 实时状态
const { status: wsStatus } = useRunnerMonitor
// 断线横幅：断开超过 10 秒后显示
const disconnectedTooLong = ref(false)
let disconnectTimer: ReturnType<typeof setTimeout> | null = null
watch(wsStatus, (val) => {
 if (val === 'connected') {
 disconnectedTooLong.value = false
 if (disconnectTimer) {
 clearTimeout(disconnectTimer)
 disconnectTimer = null
 }
 }
 else if (!disconnectTimer) {
 disconnectTimer = setTimeout( => {
 disconnectedTooLong.value = true
 disconnectTimer = null
 }, 10_000)
 }
}, { immediate: true })
onUnmounted( => {
 if (disconnectTimer) {
 clearTimeout(disconnectTimer)
 disconnectTimer = null
 }
})
const runnerId = computed( => route.params.id)
const loading = ref(true)
const runner = computed( => runnersStore.currentRunner)
// 历史任务分页
const historyTasks = ref<RunnerTaskAssignment>
const historyTotal = ref(0)
const historyStatus = ref<string | undefined>(undefined)
async function fetchHistoryTasks({ currentPage, currentPageSize }: { currentPage: number, currentPageSize: number }) {
 const params: Record<string, string | number | undefined> = {
 page: currentPage,
 page_size: currentPageSize,
 }
 if (historyStatus.value)
 params.status = historyStatus.value
 const res = await runnersApi.getRunnerTasks(runnerId.value, params)
 historyTasks.value = res.results
 historyTotal.value = res.count
}
const { currentPage, pageCount, isFirstPage, isLastPage, prev, next } = useOffsetPagination({
 total: historyTotal,
 pageSize: 10,
 onPageChange: fetchHistoryTasks,
 onPageSizeChange: fetchHistoryTasks,
})
watch(historyStatus, => {
 currentPage.value = 1
 fetchHistoryTasks({ currentPage: 1, currentPageSize: 10 })
})
onMounted(async => {
 try {
 await runnersStore.fetchRunner(runnerId.value)
 await fetchHistoryTasks({ currentPage: 1, currentPageSize: 10 })
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取 Runner 详情')
 }
 finally {
 loading.value = false
 }
})
// 删除逻辑
const deleteDialogOpen = ref(false)
const deleting = ref(false)
async function handleDelete {
 deleting.value = true
 try {
 await runnersStore.removeRunner(runnerId.value)
 success('删除成功', `Runner「${runner.value?.name}」已删除`)
 router.push('/runners')
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除 Runner')
 }
 finally {
 deleting.value = false
 deleteDialogOpen.value = false
 }
}
function formatTime(dateStr: string | null) {
 if (!dateStr)
 return '从未'
 return new Date(dateStr).toLocaleString('zh-CN')
}
function formatTimeAgo(dateStr: string | null) {
 if (!dateStr)
 return '从未'
 return useTimeAgo(new Date(dateStr)).value
}
</script>
<template>
 <PageContainer>
 <!-- 顶部导航栏 -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-3">
 <Button variant="ghost" size="icon" @click="router.push('/runners')">
 <span class="icon-[lucide--arrow-left] w-5 " />
 </Button>
 <h1 class="text-2xl font-bold">
 {{ runner?.name || '加载中...' }}
 </h1>
 <div v-if="runner" class="relative flex-shrink-0 w-3 transition-all duration-300">
 <template v-if="runner.status === 'online'">
 <span class="absolute inset-0 rounded-full bg-emerald-400 opacity-75 animate-ping" />
 <span class="absolute inset-0 rounded-full bg-emerald-500" />
 </template>
 <template v-else>
 <span class="absolute inset-0 rounded-full bg-gray-400" />
 </template>
 </div>
 </div>
 <Button v-if="runner" variant="outline" size="sm" class="text-destructive hover:bg-destructive/10" @click="deleteDialogOpen = true">
 <span class="icon-[lucide--trash-2] mr-1.5" />
 删除
 </Button>
 </div>
 <!-- 断线横幅 -->
 <Transition enter-active-class="transition-all duration-300" enter-from-class="opacity-0 -translate-y-2" enter-to-class="opacity-100 translate-y-0" leave-active-class="transition-all duration-200" leave-from-class="opacity-100" leave-to-class="opacity-0">
 <div v-if="disconnectedTooLong" class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-sm">
 <span class="icon-[lucide--wifi-off] text-base" />
 <span>连接已断开，正在重连...</span>
 <span v-if="wsStatus === 'disconnected'" class="ml-auto text-xs text-muted-foreground">无法连接，请刷新页面</span>
 </div>
 </Transition>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton" />
 <!-- 主内容 -->
 <template v-else-if="runner">
 <!-- 基本信息卡片 -->
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-violet-500/10 via-purple-500/10 to-violet-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-violet-500/5 to-purple-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--info] text-violet-500" />
 基本信息
 </CardTitle>
 </CardHeader>
 <CardContent class="pt-6">
 <div class="grid grid-cols-2 md:grid-cols-4 gap-6">
 <div>
 <div class="text-sm text-muted-foreground">
 名称
 </div>
 <div class="font-medium mt-1">
 {{ runner.name }}
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 状态
 </div>
 <div class="mt-1">
 <StatusBadge type="runner":status="runner.status" />
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 版本
 </div>
 <div class="font-medium mt-1">
 {{ runner.version || '-' }}
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 IP 地址
 </div>
 <div class="font-medium mt-1 font-mono text-sm">
 {{ runner.ip_address || '-' }}
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 并发数
 </div>
 <div class="font-medium mt-1">
 {{ runner.concurrent }}
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 当前任务数
 </div>
 <div class="font-medium mt-1">
 {{ runner.current_tasks }}
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 作用域
 </div>
 <Badge variant="outline" class="mt-1">
 {{ runner.scope === 'global' ? '全局': '项目' }}
 </Badge>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 活跃状态
 </div>
 <Badge class="mt-1":variant="runner.is_active ? 'success': 'muted'">
 {{ runner.is_active ? '活跃': '停用' }}
 </Badge>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 注册时间
 </div>
 <div class="font-medium mt-1 text-sm">
 {{ formatTime(runner.registered_at) }}
 </div>
 </div>
 <div>
 <div class="text-sm text-muted-foreground">
 最后心跳
 </div>
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <div class="font-medium mt-1 text-sm cursor-help border-b border-dotted border-muted-foreground/30 w-fit">
 {{ formatTimeAgo(runner.last_heartbeat) }}
 </div>
 </TooltipTrigger>
 <TooltipContent>{{ formatTime(runner.last_heartbeat) }}</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 <div class="col-span-2">
 <div class="text-sm text-muted-foreground">
 标签
 </div>
 <div class="flex flex-wrap gap-1.5 mt-1">
 <Badge v-for="tag in runner.tags":key="tag" variant="secondary">
 {{ tag }}
 </Badge>
 <span v-if="runner.tags.length === 0" class="text-sm text-muted-foreground">-</span>
 </div>
 </div>
 </div>
 </CardContent>
 </Card>
 </div>
 <!-- 当前任务卡片 -->
 <Card class="bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-blue-500/5 to-cyan-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--play-circle] text-blue-500" />
 当前任务
 <Badge variant="secondary" class="ml-auto transition-colors duration-300">
 {{ runner.current_task_list.length }}
 </Badge>
 </CardTitle>
 </CardHeader>
 <CardContent class="pt-6">
 <p v-if="runner.current_task_list.length === 0" class="text-sm text-muted-foreground">
 暂无正在执行的任务
 </p>
 <TransitionGroup v-else name="task-list" tag="div" class="space-y-0 divide-y divide-border/30">
 <div v-for="task in runner.current_task_list":key="task.id" class="flex items-center justify-between py-3 first:pt-0 last:pb-0">
 <div class="flex items-center gap-3">
 <span class="font-medium">{{ task.name }}</span>
 <StatusBadge type="execution":status="task.status" />
 </div>
 <span class="text-xs text-muted-foreground font-mono">{{ task.id.slice(0, 8) }}</span>
 </div>
 </TransitionGroup>
 </CardContent>
 </Card>
 <!-- 历史任务卡片 -->
 <Card class="bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl">
 <CardHeader class="border-b border-border/50 bg-gradient-to-r from-emerald-500/5 to-teal-500/5">
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--history] text-emerald-500" />
 历史任务
 <Badge variant="secondary" class="ml-auto">
 {{ historyTotal }}
 </Badge>
 </CardTitle>
 <div class="flex gap-2 mt-2">
 <Button size="sm":variant="!historyStatus ? 'default': 'outline'" @click="historyStatus = undefined">
 全部
 </Button>
 <Button size="sm":variant="historyStatus === 'completed' ? 'default': 'outline'" @click="historyStatus = 'completed'">
 已完成
 </Button>
 <Button size="sm":variant="historyStatus === 'failed' ? 'default': 'outline'" @click="historyStatus = 'failed'">
 失败
 </Button>
 </div>
 </CardHeader>
 <CardContent class="pt-6">
 <p v-if="historyTasks.length === 0" class="text-sm text-muted-foreground">
 暂无历史任务
 </p>
 <div v-else class="space-y-0 divide-y divide-border/30">
 <div v-for="task in historyTasks":key="task.id" class="flex items-center justify-between py-3 first:pt-0 last:pb-0">
 <div class="flex items-center gap-3 min-w-0">
 <StatusBadge type="execution":status="task.status" />
 <span class="text-sm font-medium">{{ task.task_type }}</span>
 <span class="text-xs text-muted-foreground truncate max-w-48">{{ task.repo_url }}</span>
 </div>
 <div class="flex items-center gap-4 text-xs text-muted-foreground flex-shrink-0">
 <span>分配: {{ formatTime(task.assigned_at) }}</span>
 <span>完成: {{ formatTime(task.completed_at) }}</span>
 </div>
 </div>
 </div>
 <!-- 分页 -->
 <div v-if="pageCount > 1" class="flex items-center justify-between pt-4 border-t border-border/30 mt-4">
 <span class="text-sm text-muted-foreground">共 {{ historyTotal }} 条</span>
 <div class="flex items-center gap-2">
 <Button size="sm" variant="outline":disabled="isFirstPage" @click="prev">
 <span class="icon-[lucide--chevron-left]" />
 </Button>
 <span class="text-sm">{{ currentPage }} / {{ pageCount }}</span>
 <Button size="sm" variant="outline":disabled="isLastPage" @click="next">
 <span class="icon-[lucide--chevron-right]" />
 </Button>
 </div>
 </div>
 </CardContent>
 </Card>
 <!-- 实时日志 -->
 <RunnerLogPanel:runner-id="runnerId" />
 </template>
 <!-- 删除确认 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除 Runner":description="`确定要删除 Runner「${runner?.name}」吗？此操作不可撤销。`"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </PageContainer>
</template>
<style scoped>
.task-list-leave-active {
 transition: all 0.3s ease;
}
.task-list-leave-to {
 opacity: 0;
 transform: translateX(20px);
}
</style>
