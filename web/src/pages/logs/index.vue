<script setup lang="ts">
import type { TriggerLog, TriggerLogStatus } from '~/api/logs'
import { useHead } from '@vueuse/head'
import { deleteTriggerLog, listTriggerLogs, retryTriggerLog } from '~/api/logs'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import TriggerLogList from '~/components/logs/TriggerLogList.vue'
useHead({
 title: '触发日志 - Friday AI',
})
const { error: showError, success } = useToast
// 过滤器
const projectFilter = ref('__all__')
const statusFilter = ref('__all__')
// 加载状态
const loading = ref(true)
const triggerLogs = ref<TriggerLog>
const total = ref(0)
// 加载项目列表
const projectsStore = useProjectsStore
onMounted(async => {
 try {
 await projectsStore.fetchProjects
 await fetchLogs
 }
 catch (e) {
 showError('加载失败', e instanceof Error ? e.message: '无法获取日志列表')
 }
 finally {
 loading.value = false
 }
})
// 获取日志列表
async function fetchLogs {
 loading.value = true
 try {
 const projectId = projectFilter.value === '__all__' ? undefined: projectFilter.value
 const status = statusFilter.value === '__all__' ? undefined: statusFilter.value as TriggerLogStatus
 const result = await listTriggerLogs({
 project_id: projectId,
 status,
 limit: 50,
 })
 triggerLogs.value = result.items ||
 total.value = result.total || 0
 }
 finally {
 loading.value = false
 }
}
// 监听过滤条件变化
watch([projectFilter, statusFilter], => {
 fetchLogs
})
// 状态选项
const statusOptions: { value: string, label: string, color: string } = [
 { value: '__all__', label: '全部状态', color: 'bg-muted' },
 { value: 'accepted', label: '已接受', color: 'bg-emerald-500' },
 { value: 'ignored', label: '已忽略', color: 'bg-gray-400' },
 { value: 'error', label: '错误', color: 'bg-red-500' },
 { value: 'duplicate', label: '重复', color: 'bg-amber-500' },
]
// 获取项目名称
function getProjectName(projectId: string | null) {
 if (!projectId)
 return '-'
 const project = projectsStore.projectById(projectId)
 return project?.name || projectId.slice(0, 8)
}
// 重试日志
async function handleRetry(logId: string) {
 try {
 await retryTriggerLog(logId)
 success('重试成功', '已重新处理该触发事件')
 await fetchLogs
 }
 catch (e) {
 showError('重试失败', e instanceof Error ? e.message: '无法重试')
 }
}
// 删除日志
async function handleDelete(logId: string) {
 try {
 await deleteTriggerLog(logId)
 success('删除成功', '日志已删除')
 await fetchLogs
 }
 catch (e) {
 showError('删除失败', e instanceof Error ? e.message: '无法删除')
 }
}
</script>
<template>
 <div class="space-y-8">
 <!-- 页面标题 -->
 <div class="flex items-center justify-between">
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/10 flex items-center justify-center">
 <span class="icon-[lucide--file-text] text-2xl text-cyan-500" />
 </div>
 <h1 class="text-2xl font-bold">触发日志</h1>
 </div>
 <p class="text-muted-foreground ml-12">
 查看飞书 Webhook 触发的工作项日志
 </p>
 </div>
 </div>
 <!-- 过滤器和统计 -->
 <div class="flex flex-col md:flex-row gap-4 md:items-center md:justify-between">
 <!-- 过滤器 -->
 <div class="flex flex-wrap items-center gap-3">
 <div class="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-muted/50 text-sm text-muted-foreground">
 <span class="icon-[lucide--filter]" />
 <span>筛选</span>
 </div>
 <!-- 项目过滤 -->
 <Select v-model="projectFilter">
 <SelectTrigger class="w-44 bg-card/50 border-border/50">
 <SelectValue placeholder="选择项目" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem value="__all__">全部项目</SelectItem>
 <SelectItem
 v-for="project in projectsStore.projects":key="project.id":value="project.id"
 >
 {{ project.name }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 状态过滤 -->
 <Select v-model="statusFilter">
 <SelectTrigger class="w-36 bg-card/50 border-border/50">
 <SelectValue placeholder="选择状态" />
 </SelectTrigger>
 <SelectContent>
 <SelectItem
 v-for="option in statusOptions":key="option.value":value="option.value"
 >
 {{ option.label }}
 </SelectItem>
 </SelectContent>
 </Select>
 <!-- 刷新按钮 -->
 <Button variant="outline" size="icon" class=" w-9" @click="fetchLogs">
 <span class="icon-[lucide--refresh-cw]" />
 </Button>
 </div>
 <!-- 统计信息 -->
 <div class="flex items-center gap-2 text-sm text-muted-foreground px-4 py-2 rounded-full bg-muted/30">
 <span class="icon-[lucide--database]" />
 共 {{ total }} 条记录
 </div>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <!-- 空状态 -->
 <EmptyState
 v-else-if="triggerLogs.length === 0"
 icon="lucide--file-text"
 title="暂无日志"
 description="飞书 Webhook 触发后将在此显示日志"
 gradient="from-cyan-500/20 to-blue-500/20"
 />
 <!-- 日志列表 -->
 <TriggerLogList
 v-else:logs="triggerLogs":loading="loading":get-project-name="getProjectName"
 @retry="handleRetry"
 @delete="handleDelete"
 @refresh="fetchLogs"
 />
 </div>
</template>
