<script setup lang="ts">
/**
 * NodeConfigTab — 抽屉配置参数标签页
 *
 * 只读展示节点的配置参数（JSON 格式）。
 */
import { ScrollArea } from '~/components/ui/scroll-area'
defineProps<{
 config: Record<string, unknown>
}>
function formatJson(data: Record<string, unknown> | null | undefined): string {
 if (!data || Object.keys(data).length === 0)
 return ''
 return JSON.stringify(data, null, 2)
}
</script>
<template>
 <div class="space-y-2">
 <div class="text-sm font-medium text-foreground">
 节点配置
 </div>
 <ScrollArea class="max-h-[400px]">
 <div
 v-if="formatJson(config)"
 class="bg-muted/50 rounded-lg "
 >
 <pre class="text-xs text-foreground/80 whitespace-pre-wrap break-words font-mono">{{ formatJson(config) }}</pre>
 </div>
 <div v-else class="text-sm text-muted-foreground italic">
 (无配置)
 </div>
 </ScrollArea>
 </div>
</template>
