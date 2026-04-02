<script setup lang="ts">
import type { IndexStatusResponse } from '~/api/repositories'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Button } from '~/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '~/components/ui/card'
const props = defineProps<{
 repositoryId: string
}>
const loading = ref(true)
const indexStatus = ref<IndexStatusResponse | null>(null)
const triggering = ref(false)
const deleting = ref(false)
const { handleError } = useErrorHandler
const { success, error: showError } = useToast
let pollInterval: ReturnType<typeof setInterval> | null = null
// 加载索引状态
async function loadIndexStatus {
 try {
 indexStatus.value = await repositoriesApi.getIndexStatus(props.repositoryId)
 }
 catch {
 // intentionally ignored
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
 success('索引任务已启动')
 await loadIndexStatus
 startPolling
 }
 catch (e: unknown) {
 handleError(e, '启动索引')
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
 success('索引已删除')
 await loadIndexStatus
 }
 catch (e: unknown) {
 handleError(e, '删除索引')
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
 success('索引构建完成')
 }
 else if (indexStatus.value?.index_status === IndexStatus.FAILED) {
 showError('索引构建失败')
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
// 统一进度
const overallProgress = computed( => {
 return indexStatus.value?.overall_progress ?? 0
})
const overallStage = computed( => {
 return indexStatus.value?.overall_stage ?? '准备中...'
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
 <div class="absolute -inset-1 bg-gradient-to-r from-cyan-500/10 via-primary/10 to-cyan-500/10 rounded-3xl blur-xl opacity-70" />
 <Card class="relative bg-card/80 backdrop-blur-sm border-border/50">
 <CardHeader class="flex flex-row items-center justify-between border-b border-border/50 bg-gradient-to-r from-cyan-500/5 to-primary/5">
 <div>
 <CardTitle class="flex items-center gap-2">
 <span class="icon-[lucide--database] text-cyan-500" />
 代码索引
 </CardTitle>
 <CardDescription>向量化代码库用于语义搜索</CardDescription>
 </div>
 <StatusBadge v-if="indexStatus" type="index":status="indexStatus.index_status" />
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
 <p class="font-medium">
 索引已就绪
 </p>
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
 <div class=" rounded-full bg-primary/10">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 </div>
 <div class="flex-1">
 <p class="font-medium">
 正在构建索引
 </p>
 </div>
 </div>
 <!-- 统一索引进度 -->
 <div class="space-y-1.5">
 <div class="flex items-center justify-between text-sm">
 <span class="text-muted-foreground">
 <span class="icon-[lucide--loader-circle] mr-1.5 animate-spin" />
 {{ overallStage }}
 </span>
 <span class="font-medium text-primary">{{ overallProgress }}%</span>
 </div>
 <div class=".5 bg-muted rounded-full overflow-hidden">
 <div
 class="h-full bg-gradient-to-r from-teal-500 via-cyan-500 to-emerald-500 transition-all duration-500":style="{ width: `${overallProgress}%` }"
 />
 </div>
 </div>
 </div>
 <!-- 失败状态 -->
 <div v-else-if="indexStatus.index_status === IndexStatus.FAILED" class="space-y-4">
 <div class="flex items-center gap-3">
 <div class=" rounded-full bg-destructive/10">
 <span class="icon-[lucide--x-circle] text-2xl text-destructive" />
 </div>
 <div>
 <p class="font-medium">
 索引构建失败
 </p>
 <p class="text-sm text-muted-foreground">
 {{ indexStatus.index_error || '未知错误' }}
 </p>
 </div>
 </div>
 <div class="flex gap-2">
 <Button:disabled="triggering"
 @click="triggerIndex"
 >
 <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
 <span v-else class="icon-[lucide--refresh-cw] mr-2" />
 重试
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
