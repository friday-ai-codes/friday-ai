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
 <div class="export-success-card animate-fade-in">
 <div class="export-success-card__header">
 <span class="export-success-card__icon icon-[lucide--file-check]" />
 <span class="text-sm font-semibold">已导出到飞书文档</span>
 <Badge
 variant="outline"
 class="ml-auto border-emerald-500/30 bg-emerald-500/5 text-emerald-600"
 >
 导出成功
 </Badge>
 </div>
 <div class=" space-y-1.5">
 <p class="text-sm font-semibold text-foreground">
 {{ title }}
 </p>
 <a:href="url"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 在飞书中查看
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <p class="text-xs text-muted-foreground">
 {{ formattedTime }}
 </p>
 </div>
 </div>
</template>
<style scoped>
.export-success-card {
 width: 100%;
 overflow: hidden;
 border: 1px solid hsl(214 32% 88% / 0.9);
 border-radius: 1rem;
 background: hsl(0 0% 100% / 0.94);
 box-shadow: 0 1px 2px hsl(215 28% 17% / 0.05);
}
.export-success-card__header {
 display: flex;
 align-items: center;
 gap: 0.5rem;
 padding: 0.75rem 1rem;
 border-bottom: 1px solid hsl(214 32% 91% / 0.75);
}
.export-success-card__icon {
 color: hsl(168 76% 36%);
}
</style>
