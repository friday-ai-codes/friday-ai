<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
import type { IndexStatusResponse } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
const props = defineProps<{
 repositoryId: string
}>
const loading = ref(true)
const indexStatus = ref<IndexStatusResponse | null>(null)
const triggering = ref(false)
const deleting = ref(false)
let pollInterval: ReturnType<typeof setInterval> | null = null
// 索引状态标签
const statusLabels: Record<IndexStatus, string> = {
 [IndexStatus.NOT_INDEXED]: '未索引',
 [IndexStatus.INDEXING]: '索引中',
 [IndexStatus.INDEXED]: '已索引',
 [IndexStatus.FAILED]: '索引失败',
}
// 索引状态颜色
const statusVariants = computed( => {
 switch (indexStatus.value?.index_status) {
 case IndexStatus.INDEXED:
 return 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20'
 case IndexStatus.INDEXING:
 return 'bg-blue-500/10 text-blue-600 border-blue-500/20'
 case IndexStatus.FAILED:
 return 'bg-destructive/10 text-destructive border-destructive/20'
 default:
 return 'bg-muted text-muted-foreground border-border'
 }
})
// 加载索引状态
async function loadIndexStatus {
 try {
 indexStatus.value = await repositoriesApi.getIndexStatus(props.repositoryId)
 }
 catch (error) {
 console.error('Failed to load index status:', error)
 }
 finally {
 loading.value = false
 }
}
// 触发索引
async function triggerIndex {
 triggering.value = true
 try {
 await repositoriesApi.triggerIndex(props.repositoryId)
 toast.success('索引任务已启动')
 await loadIndexStatus
 startPolling
 }
 catch (error) {
 console.error('Failed to trigger index:', error)
 toast.error('启动索引失败')
 }
 finally {
 triggering.value = false
 }
}
// 删除索引
async function deleteIndex {
 deleting.value = true
 try {
 await repositoriesApi.deleteIndex(props.repositoryId)
 toast.success('索引已删除')
 await loadIndexStatus
 }
 catch (error) {
 console.error('Failed to delete index:', error)
 toast.error('删除索引失败')
 }
 finally {
 deleting.value = false
 }
}
// 开始轮询（索引进行中时）
function startPolling {
 if (pollInterval)
 return
 pollInterval = setInterval(async => {
 await loadIndexStatus
 if (indexStatus.value?.index_status !== IndexStatus.INDEXING) {
 stopPolling
 if (indexStatus.value?.index_status === IndexStatus.INDEXED) {
 toast.success('索引构建完成')
 }
 else if (indexStatus.value?.index_status === IndexStatus.FAILED) {
 toast.error('索引构建失败')
 }
 }
 }, 3000)
}
function stopPolling {
 if (pollInterval) {
 clearInterval(pollInterval)
 pollInterval = null
 }
}
// 格式化日期
function formatDate(dateStr: string | null) {
 if (!dateStr)
 return '-'
 return new Date(dateStr).toLocaleString('zh-CN')
}
// 计算进度百分比
const progressPercent = computed( => {
 if (!indexStatus.value || indexStatus.value.index_total_chunks === 0)
 return 0
 return Math.round(
 (indexStatus.value.index_processed_chunks / indexStatus.value.index_total_chunks) * 100,
 )
})
onMounted(async => {
 await loadIndexStatus
 if (indexStatus.value?.index_status === IndexStatus.INDEXING) {
 startPolling
 }
})
onUnmounted( => {
 stopPolling
})
</script>
<template>
 <div class="relative">
 <div class="absolute -inset-1 bg-gradient-to-r from-cyan-500/10 via-blue-500/10 to-cyan-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-cyan-500/5 to-blue-500/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--database] text-cyan-500" />
 代码索引
 </CardTitle>
 <CardDescription>向量化代码库用于语义搜索</CardDescription>
 </div>
 <Badge v-if="indexStatus":class="statusVariants" variant="outline">
 <span
 v-if="indexStatus.index_status === IndexStatus.INDEXING"
 class="icon-[lucide--loader-circle] animate-spin mr-1.5"
 />
 {{ statusLabels[indexStatus.index_status] }}
 </Badge>
 </CardHeader>
 <CardContent class="pt-6">
 <!-- 加载状态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground">加载索引状态...</span>
 </div>
 <!-- 索引状态 -->
 <div v-else-if="indexStatus" class="space-y-6">
 <!-- 已索引状态 -->
 <div v-if="indexStatus.index_status === IndexStatus.INDEXED" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-emerald-500/10">
 <span class="icon-[lucide--check-circle] text-2xl text-emerald-500" />
 </div>
 <div>
 <p class="font-medium">索引已就绪</p>
 <p class="text-sm text-muted-foreground">
 最后更新: {{ formatDate(indexStatus.last_indexed_at) }}
 </p>
 </div>
 </div>
 <div class="flex gap-2">
 <Button
 variant="outline":disabled="triggering"
 @click="triggerIndex"
 >
 <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--refresh-cw] mr-2" />
 重新索引
 </Button>
 <Button
 variant="outline"
 class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50":disabled="deleting"
 @click="deleteIndex"
 >
 <span v-if="deleting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--trash-2] mr-2" />
 删除索引
 </Button>
 </div>
 </div>
 <!-- 索引中状态 -->
 <div v-else-if="indexStatus.index_status === IndexStatus.INDEXING" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-blue-500/10">
 <span class="icon-[lucide--loader-circle] text-2xl text-blue-500 animate-spin" />
 </div>
 <div class="flex-1">
 <p class="font-medium">正在构建索引</p>
 <p class="text-sm text-muted-foreground">
 <template v-if="indexStatus.index_total_chunks > 0">
 正在生成向量: {{ indexStatus.index_processed_chunks }} / {{ indexStatus.index_total_chunks }} 块
 </template>
 <template v-else>
 正在解析代码，请稍候...
 </template>
 </p>
 </div>
 <div v-if="indexStatus.index_total_chunks > 0" class="text-sm font-medium text-blue-500">
 {{ progressPercent }}%
 </div>
 </div>
 <div class=" bg-muted rounded-full overflow-hidden">
 <div
 class="h-full bg-gradient-to-r from-blue-500 to-cyan-500 transition-all duration-300":style="{ width: indexStatus.index_total_chunks > 0 ? `${progressPercent}%`: '30%' }":class="{ 'animate-pulse': indexStatus.index_total_chunks === 0 }"
 />
 </div>
 </div>
 <!-- 失败状态 -->
 <div v-else-if="indexStatus.index_status === IndexStatus.FAILED" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-destructive/10">
 <span class="icon-[lucide--x-circle] text-2xl text-destructive" />
 </div>
 <div>
 <p class="font-medium">索引构建失败</p>
 <p class="text-sm text-muted-foreground">
 {{ indexStatus.index_error || '未知错误' }}
 </p>
 </div>
 </div>
 <Button:disabled="triggering"
 @click="triggerIndex"
 >
 <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--refresh-cw] mr-2" />
 重试
 </Button>
 </div>
 <!-- 未索引状态 -->
 <div v-else class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--database] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground mb-4">
 尚未建立代码索引
 </p>
 <Button:disabled="triggering"
 @click="triggerIndex"
 >
 <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--play] mr-2" />
 新建索引
 </Button>
 </div>
 </div>
 </CardContent>
 </Card>
 </div>
</template>
