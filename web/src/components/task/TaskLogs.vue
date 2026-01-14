<script setup lang="ts">
import { useScroll } from '@vueuse/core';
import { tasksApi } from '~/api';
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card';
import { usePolling } from '~/composables/usePolling';
const props = defineProps<{
 taskId: string
 active?: boolean
}>
const logs = ref<string>('')
const logContainer = ref<HTMLElement | null>(null)
const { y } = useScroll(logContainer)
const autoScroll = ref(true)
// 检测用户是否手动向上滚动，如果是则暂停自动滚动
watch(y, (newY, oldY) => {
 if (!logContainer.value) return
 const { scrollHeight, clientHeight } = logContainer.value
 // 如果距离底部超过 50px，则认为是手动滚动
 const isAtBottom = scrollHeight - clientHeight - newY < 50
 if (isAtBottom) {
 autoScroll.value = true
 } else if (newY < oldY) {
 // 用户向上滚动
 autoScroll.value = false
 }
})
// 轮询获取日志
const { start, stop, isPolling, error } = usePolling(
 async => {
 try {
 const response = await tasksApi.getLogs(props.taskId, 500)
 if (response.logs !== logs.value) {
 logs.value = response.logs
 // 自动滚动到底部
 if (autoScroll.value) {
 nextTick( => {
 if (logContainer.value) {
 logContainer.value.scrollTop = logContainer.value.scrollHeight
 }
 })
 }
 }
 } catch (e) {
 console.error('Failed to fetch logs:', e)
 throw e
 }
 },
 {
 interval: 2000,
 immediate: true,
 }
)
// 监听 active 属性变化
watch(
 => props.active,
 (newVal) => {
 if (newVal) {
 start
 } else {
 stop
 }
 },
 { immediate: true }
)
</script>
<template>
 <Card class="h-full flex flex-col">
 <CardHeader class="py-3 px-4 border-b">
 <div class="flex items-center justify-between">
 <CardTitle class="text-sm font-medium">执行日志</CardTitle>
 <div class="flex items-center gap-2">
 <span v-if="isPolling" class="flex w-2 rounded-full bg-green-500 animate-pulse" />
 <span v-else class="flex w-2 rounded-full bg-gray-300" />
 <span class="text-xs text-muted-foreground">{{ isPolling ? '实时更新中': '已停止更新' }}</span>
 </div>
 </div>
 </CardHeader>
 <CardContent class="flex-1 overflow-hidden relative">
 <div
 ref="logContainer"
 class="h-full overflow-y-auto font-mono text-xs bg-black text-white whitespace-pre-wrap"
 >
 <div v-if="error" class="text-red-400 mb-2">
 获取日志失败: {{ error.message }}
 </div>
 <div v-if="!logs && !error" class="text-gray-500 italic">
 暂无日志...
 </div>
 {{ logs }}
 </div>
 <!-- 自动滚动提示/按钮 -->
 <button
 v-if="!autoScroll"
 class="absolute bottom-4 right-4 bg-primary text-primary-foreground text-xs px-3 py-1 rounded shadow-md hover:bg-primary/90 transition-colors"
 @click=" => { autoScroll = true; if(logContainer) logContainer.scrollTop = logContainer.scrollHeight; }"
 >
 ↓ 滚动到底部
 </button>
 </CardContent>
 </Card>
</template>