<script setup lang="ts">
/**
 * 导出成功卡片 -- 在消息流中展示导出结果，包含飞书文档链接。
 * 复用 DocSummaryCard 的 .card.mt-2.animate-fade-in 结构 (per )。
 */
import { Badge } from '~/components/ui/badge'
const props = defineProps<{
 title: string
 url: string
 exportedAt: string
}>
const formattedTime = computed( => {
 try {
 return new Date(props.exportedAt).toLocaleString('zh-CN')
 }
 catch {
 return props.exportedAt
 }
})
</script>
<template>
 <div class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--file-check] text-primary" />
 <span class="text-sm font-semibold">已导出到飞书文档</span>
 <Badge
 variant="outline"
 class="ml-auto text-emerald-500 border-emerald-500/30 bg-emerald-500/5"
 >
 导出成功
 </Badge>
 </div>
 <div class=" space-y-1.5">
 <p class="text-sm font-semibold text-foreground">{{ title }}</p>
 <a:href="url"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 在飞书中查看
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <p class="text-xs text-muted-foreground">{{ formattedTime }}</p>
 </div>
 </div>
</template>
