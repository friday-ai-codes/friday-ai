<script setup lang="ts">
/**
 * NodeDataTab — 抽屉输入/输出数据标签页
 *
 * 以 JSON 格式展示节点的输入数据和输出数据。
 */
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { ScrollArea } from '~/components/ui/scroll-area'
defineProps<{
 nodeExecution: NodeExecution
}>
function formatJson(data: Record<string, any> | null | undefined): string {
 if (!data || Object.keys(data).length === 0) return ''
 return JSON.stringify(data, null, 2)
}
</script>
<template>
 <div class="space-y-4">
 <!-- 输入数据 -->
 <div class="space-y-2">
 <div class="text-sm font-medium text-foreground">输入数据</div>
 <ScrollArea class="max-h-[250px]">
 <div
 v-if="formatJson(nodeExecution.input_data)"
 class="bg-muted/50 rounded-lg "
 >
 <pre class="text-xs text-foreground/80 whitespace-pre-wrap break-words font-mono">{{ formatJson(nodeExecution.input_data) }}</pre>
 </div>
 <div v-else class="text-sm text-muted-foreground italic">
 (空)
 </div>
 </ScrollArea>
 </div>
 <!-- 输出数据 -->
 <div class="space-y-2">
 <div class="text-sm font-medium text-foreground">输出数据</div>
 <ScrollArea class="max-h-[250px]">
 <div
 v-if="formatJson(nodeExecution.output_data)"
 class="bg-muted/50 rounded-lg "
 >
 <pre class="text-xs text-foreground/80 whitespace-pre-wrap break-words font-mono">{{ formatJson(nodeExecution.output_data) }}</pre>
 </div>
 <div v-else class="text-sm text-muted-foreground italic">
 (空)
 </div>
 </ScrollArea>
 </div>
 </div>
</template>
