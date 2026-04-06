<script setup lang="ts">
import type { IndexHistoryItem, IndexHistoryResponse } from '~/api/repositories'
import { onMounted, ref, watch } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
const props = defineProps<{
 repositoryId: string
}>
const loading = ref(true)
const history = ref<IndexHistoryResponse | null>(null)
const currentPage = ref(1)
const statusFilter = ref<string>('')
const pageSize = 5
// 筛选按钮配置
const filterButtons = [
 { status: 'pending', label: '等待中' },
 { status: 'running', label: '运行中' },
 { status: 'completed', label: '已完成' },
 { status: 'failed', label: '失败' },
]
const triggerLabels: Record<string, string> = {
 manual: '手动',
 webhook: 'Webhook',
 scheduled: '定时',
}
async function loadHistory {
 loading.value = true
 try {
 history.value = await repositoriesApi.getIndexHistory(props.repositoryId, {
 limit: pageSize,
 offset: (currentPage.value - 1) * pageSize,
 status: statusFilter.value || undefined,
 })
 }
 catch {
 // intentionally ignored
 }
 finally {
 loading.value = false
 }
}
function formatDate(dateStr: string | null) {
 if (!dateStr)
 return '-'
 return new Date(dateStr).toLocaleString('zh-CN')
}
function formatDuration(item: IndexHistoryItem) {
 if (!item.started_at || !item.finished_at)
 return '-'
 const ms = new Date(item.finished_at).getTime - new Date(item.started_at).getTime
 if (ms < 1000)
 return `${ms}ms`
 if (ms < 60000)
 return `${(ms / 1000).toFixed(1)}s`
 return `${(ms / 60000).toFixed(1)}min`
}
const totalPages = computed( => {
 if (!history.value)
 return 0
 return Math.ceil(history.value.total / pageSize)
})
function setFilter(status: string) {
 statusFilter.value = statusFilter.value === status ? '': status
 currentPage.value = 1
}
watch([currentPage, statusFilter], loadHistory)
onMounted(loadHistory)
</script>
<template>
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--history] text-primary" />
 <h3 class="text-sm font-semibold">索引历史</h3>
 </div>
 <p class="text-xs text-muted-foreground mt-0.5">查看每次索引操作的详细记录</p>
 </div>
 <div class="">
 <!-- 状态筛选 -->
 <div class="flex gap-2 mb-4">
 <Button
 v-for="btn in filterButtons":key="btn.status":variant="statusFilter === btn.status ? 'default': 'outline'"
 size="sm"
 class=" text-xs"
 @click="setFilter(btn.status)"
 >
 {{ btn.label }}
 </Button>
 </div>
 <!-- 加载状态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground">加载历史记录...</span>
 </div>
 <!-- 无记录 -->
 <div v-else-if="!history || history.items.length === 0" class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--history] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground">
 {{ statusFilter ? '该状态下暂无记录': '暂无索引历史' }}
 </p>
 </div>
 <!-- 历史列表 -->
 <div v-else class="space-y-3">
 <div
 v-for="item in history.items":key="item.id"
 class=" rounded-xl border border-border/50 bg-muted/20 hover:bg-muted/40 transition-colors space-y-3"
 >
 <!-- 头部：状态 + 触发方式 + 时间 -->
 <div class="flex items-center justify-between">
 <div class="flex items-center gap-2">
 <StatusBadge type="index":status="item.status" />
 <Badge variant="outline" class="bg-muted/50">
 {{ triggerLabels[item.trigger_type] || item.trigger_type }}
 </Badge>
 </div>
 <span class="text-xs text-muted-foreground">{{ formatDate(item.created_at) }}</span>
 </div>
 <!-- 文件变更统计 -->
 <div v-if="item.files_added || item.files_modified || item.files_deleted" class="flex gap-4 text-xs">
 <span v-if="item.files_added" class="text-emerald-600">
 <span class="icon-[lucide--plus] mr-0.5" />{{ item.files_added }} 新增
 </span>
 <span v-if="item.files_modified" class="text-amber-600">
 <span class="icon-[lucide--pencil] mr-0.5" />{{ item.files_modified }} 修改
 </span>
 <span v-if="item.files_deleted" class="text-destructive">
 <span class="icon-[lucide--minus] mr-0.5" />{{ item.files_deleted }} 删除
 </span>
 </div>
 <!-- SHA 范围 + 耗时 -->
 <div class="flex items-center justify-between text-xs text-muted-foreground">
 <span v-if="item.from_sha || item.to_sha" class="font-mono">
 {{ item.from_sha?.slice(0, 7) || '---' }} → {{ item.to_sha?.slice(0, 7) || '---' }}
 </span>
 <span v-else />
 <span v-if="item.started_at && item.finished_at">
 <span class="icon-[lucide--clock] mr-1" />{{ formatDuration(item) }}
 </span>
 </div>
 <!-- 摘要/错误 -->
 <p v-if="item.summary_text" class="text-xs text-muted-foreground bg-muted/30 rounded-lg px-3 py-2">
 {{ item.summary_text }}
 </p>
 <p v-if="item.error_message && item.status === 'failed'" class="text-xs text-destructive bg-destructive/5 rounded-lg px-3 py-2">
 {{ item.error_message }}
 </p>
 </div>
 <!-- 分页 -->
 <div v-if="totalPages > 1" class="flex items-center justify-between pt-2">
 <span class="text-xs text-muted-foreground">共 {{ history.total }} 条记录</span>
 <div class="flex items-center gap-1">
 <Button
 variant="outline"
 size="sm"
 class=" w-7 ":disabled="currentPage <= 1"
 @click="currentPage--"
 >
 <span class="icon-[lucide--chevron-left]" />
 </Button>
 <span class="text-xs text-muted-foreground px-2">{{ currentPage }} / {{ totalPages }}</span>
 <Button
 variant="outline"
 size="sm"
 class=" w-7 ":disabled="currentPage >= totalPages"
 @click="currentPage++"
 >
 <span class="icon-[lucide--chevron-right]" />
 </Button>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
