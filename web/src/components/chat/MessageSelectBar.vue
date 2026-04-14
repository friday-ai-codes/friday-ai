<script setup lang="ts">
/**
 * 多选模式操作条 -- 显示选中消息数、全选/取消/导出操作 (per,, )。
 */
import { Button } from '~/components/ui/button'
const emit = defineEmits<{ export: }>
const chatStore = useChatStore
const selectedCount = computed( => chatStore.selectedMessageIds.size)
</script>
<template>
 <div class="sticky top-0 z-10 bg-background/95 backdrop-blur-sm flex items-center px-4 border-b border-border/30 animate-slide-down">
 <!-- 左侧: 选中计数 -->
 <span class="text-sm text-muted-foreground">
 已选 <span class="font-semibold text-foreground">{{ selectedCount }}</span> 条消息
 </span>
 <!-- 中间: 全选 -->
 <Button
 variant="ghost"
 size="sm"
 class="ml-4 text-xs"
 @click="chatStore.selectAllAssistant"
 >
 全选 AI 回答
 </Button>
 <!-- 右侧: 取消 + 导出 -->
 <div class="ml-auto flex items-center gap-2">
 <Button
 variant="outline"
 size="sm"
 class="text-xs"
 @click="chatStore.exitExportSelectMode"
 >
 取消
 </Button>
 <Button
 size="sm"
 class="text-xs":disabled="selectedCount === 0"
 @click="emit('export')"
 >
 导出选中
 </Button>
 </div>
 </div>
</template>
