<script setup lang="ts">
import type { Runner } from '~/types'
import { useHead } from '@vueuse/head'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/tooltip'
import PageContainer from '~/components/layout/PageContainer.vue'
import PageHeader from '~/components/common/PageHeader.vue'
useHead({ title: 'Runner 管理 - Friday AI' })
const router = useRouter
const runnersStore = useRunnersStore
const { success, error: showError } = useToast
const { status } = useRunnerMonitor
const disconnectedTooLong = ref(false)
let disconnectTimer: ReturnType<typeof setTimeout> | undefined
watch(status, (val) => {
 if (val === 'connected') {
 disconnectedTooLong.value = false
 if (disconnectTimer) { clearTimeout(disconnectTimer); disconnectTimer = undefined }
 }
 else if (!disconnectTimer) {
 disconnectTimer = setTimeout( => { disconnectedTooLong.value = true; disconnectTimer = undefined }, 10_000)
 }
})
const loading = ref(true)
onMounted(async => {
 try { await runnersStore.fetchRunners }
 catch (e) { showError('加载失败', e instanceof Error ? e.message: '无法获取 Runner 列表') }
 finally { loading.value = false }
})
onUnmounted( => { if (disconnectTimer) clearTimeout(disconnectTimer) })
const deleteDialogOpen = ref(false)
const runnerToDelete = ref<{ id: string, name: string } | null>(null)
const deleting = ref(false)
function confirmDelete(runner: Runner) {
 runnerToDelete.value = { id: runner.id, name: runner.name }
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!runnerToDelete.value) return
 deleting.value = true
 try {
 await runnersStore.removeRunner(runnerToDelete.value.id)
 success('删除成功', `Runner「${runnerToDelete.value.name}」已删除`)
 deleteDialogOpen.value = false
 }
 catch (e) { showError('删除失败', e instanceof Error ? e.message: '无法删除 Runner') }
 finally { deleting.value = false }
}
function formatTimeAgo(dateStr: string | null) {
 if (!dateStr) return '从未'
 return useTimeAgo(new Date(dateStr)).value
}
function formatAbsoluteTime(dateStr: string | null) {
 if (!dateStr) return '从未连接'
 return new Date(dateStr).toLocaleString('zh-CN')
}
</script>
<template>
 <PageContainer>
 <!-- 页头 -->
 <PageHeader
 icon="lucide--server"
 icon-gradient="from-violet-500/20 to-purple-500/10"
 icon-color="text-violet-500"
 title="Runner"
 description="管理和监控您的 Runner 实例"
 >
 <template #title-suffix>
 <Badge variant="secondary">{{ runnersStore.runners.length }}</Badge>
 </template>
 <template #actions>
 <Button class="group relative overflow-hidden" @click="router.push('/runners/new')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-1.5" />
 新建 Runner
 </Button>
 </template>
 </PageHeader>
 <!-- 断线横幅 -->
 <Transition enter-active-class="transition-all duration-300" enter-from-class="opacity-0 -translate-y-2" enter-to-class="opacity-100 translate-y-0" leave-active-class="transition-all duration-200" leave-from-class="opacity-100" leave-to-class="opacity-0">
 <div v-if="disconnectedTooLong" class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-sm">
 <span class="icon-[lucide--wifi-off] text-base" />
 <span>连接已断开，正在重连...</span>
 <span v-if="status === 'disconnected'" class="ml-auto text-xs text-muted-foreground">无法连接，请刷新页面</span>
 </div>
 </Transition>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="5" />
 <!-- 空状态 -->
 <div v-else-if="runnersStore.runners.length === 0" class="relative flex flex-col items-center justify-center py-20 text-center">
 <div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 bg-gradient-to-br from-violet-500/15 to-purple-500/15 rounded-full blur-3xl" />
 </div>
 <span class="icon-[lucide--server] text-5xl text-muted-foreground/30 mb-4" />
 <h3 class="text-lg font-semibold mb-2">暂无 Runner</h3>
 <p class="text-muted-foreground mb-8 max-w-sm leading-relaxed">还没有注册任何 Runner。创建一个新的 Runner 来开始使用。</p>
 <Button class="group relative overflow-hidden" @click="router.push('/runners/new')">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-2" />
 新建 Runner
 </Button>
 </div>
 <!-- Runner 表格 -->
 <div v-else class="rounded-2xl border border-border/50 bg-card/80 backdrop-blur-sm overflow-hidden">
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead>状态</TableHead>
 <TableHead>Runner</TableHead>
 <TableHead>标签</TableHead>
 <TableHead>任务</TableHead>
 <TableHead>最后联系</TableHead>
 <TableHead class="w-16">操作</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <TableRow
 v-for="runner in runnersStore.runners":key="runner.id"
 class="cursor-pointer hover:bg-muted/50 transition-colors"
 @click="router.push(`/runners/${runner.id}`)"
 >
 <!-- 状态 -->
 <TableCell>
 <div class="flex items-center gap-2">
 <span v-if="runner.status === 'online'" class="relative flex .5 w-2.5">
 <span class="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />
 <span class="relative inline-flex .5 w-2.5 rounded-full bg-emerald-500" />
 </span>
 <span v-else class="inline-flex .5 w-2.5 rounded-full bg-gray-400" />
 <span class="text-sm">{{ runner.status === 'online' ? '在线': '离线' }}</span>
 <Badge v-if="runner.is_paused" variant="outline" class="text-xs text-amber-600 border-amber-300">已暂停</Badge>
 </div>
 </TableCell>
 <!-- Runner 信息 -->
 <TableCell>
 <div class="flex flex-col gap-0.5">
 <div class="flex items-center gap-2">
 <span class="font-medium text-foreground">{{ runner.name }}</span>
 <Badge v-if="runner.is_protected" variant="outline" class="text-xs">
 <span class="icon-[lucide--shield] mr-0.5 text-[10px]" />受保护
 </Badge>
 </div>
 <span class="text-xs text-muted-foreground">{{ runner.description || `#${runner.id.slice(0, 8)}` }} · {{ runner.ip_address || '-' }}</span>
 </div>
 </TableCell>
 <!-- 标签 -->
 <TableCell>
 <div class="flex items-center gap-1 flex-wrap">
 <Badge v-for="tag in runner.tags.slice(0, 3)":key="tag" variant="secondary" class="text-xs">{{ tag }}</Badge>
 <Badge v-if="runner.tags.length > 3" variant="outline" class="text-xs text-muted-foreground">+{{ runner.tags.length - 3 }}</Badge>
 <span v-if="runner.tags.length === 0" class="text-xs text-muted-foreground">-</span>
 </div>
 </TableCell>
 <!-- 任务数 -->
 <TableCell>
 <span class="text-sm">{{ runner.current_tasks }}</span>
 </TableCell>
 <!-- 最后联系 -->
 <TableCell>
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <span class="text-sm text-muted-foreground cursor-help border-b border-dotted border-muted-foreground/30">{{ formatTimeAgo(runner.last_heartbeat) }}</span>
 </TooltipTrigger>
 <TooltipContent>{{ formatAbsoluteTime(runner.last_heartbeat) }}</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </TableCell>
 <!-- 操作 -->
 <TableCell>
 <Button variant="ghost" size="icon" class=" w-8 hover:bg-destructive/10 hover:text-destructive" @click.stop="confirmDelete(runner)">
 <span class="icon-[lucide--trash-2] text-sm" />
 </Button>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </div>
 <!-- 删除确认 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除 Runner":description="`确定要删除 Runner「${runnerToDelete?.name}」吗？此操作不可撤销。`"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </PageContainer>
</template>
