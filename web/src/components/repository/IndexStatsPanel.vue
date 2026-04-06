<script setup lang="ts">
import type { IndexStatsResponse } from '~/api/repositories'
import { onMounted, ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { Progress } from '~/components/ui/progress'
const props = defineProps<{
 repositoryId: string
}>
const loading = ref(true)
const stats = ref<IndexStatsResponse | null>(null)
const error = ref(false)
async function loadStats {
 loading.value = true
 error.value = false
 try {
 stats.value = await repositoriesApi.getIndexStats(props.repositoryId)
 }
 catch {
 error.value = true
 }
 finally {
 loading.value = false
 }
}
// 语言颜色映射
const languageColors: Record<string, string> = {
 python: '#3572A5',
 typescript: '#3178C6',
 javascript: '#F7DF1E',
 vue: '#42B883',
 go: '#00ADD8',
 rust: '#DEA584',
 java: '#B07219',
 css: '#563D7C',
 html: '#E34C26',
 shell: '#89E051',
 markdown: '#083FA1',
 yaml: '#CB171E',
 json: '#292929',
 sql: '#E38C00',
 cpp: '#F34B7D',
 c: '#555555',
}
function getLanguageColor(lang: string): string {
 return languageColors[lang.toLowerCase] || '#6B7280'
}
// SVG 饼图计算
function getPieSlices(distribution: Record<string, number>) {
 const entries = Object.entries(distribution).sort((a, b) => b[1] - a[1])
 const total = entries.reduce((sum, [, count]) => sum + count, 0)
 if (total === 0)
 return
 let currentAngle = 0
 return entries.map(([lang, count]) => {
 const percentage = count / total
 const startAngle = currentAngle
 const endAngle = currentAngle + percentage * 360
 currentAngle = endAngle
 const startRad = ((startAngle - 90) * Math.PI) / 180
 const endRad = ((endAngle - 90) * Math.PI) / 180
 const largeArc = percentage > 0.5 ? 1: 0
 const x1 = 50 + 40 * Math.cos(startRad)
 const y1 = 50 + 40 * Math.sin(startRad)
 const x2 = 50 + 40 * Math.cos(endRad)
 const y2 = 50 + 40 * Math.sin(endRad)
 const path = entries.length === 1
 ? `M 50 50 m -40 0 a 40 40 0 1 1 80 0 a 40 40 0 1 1 -80 0`: `M 50 50 L ${x1} ${y1} A 40 40 0 ${largeArc} 1 ${x2} ${y2} Z`
 return {
 lang,
 count,
 percentage,
 path,
 color: getLanguageColor(lang),
 }
 })
}
onMounted(loadStats)
</script>
<template>
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--bar-chart-3] text-primary" />
 <h3 class="text-sm font-semibold">索引统计</h3>
 </div>
 <div class="">
 <!-- 加载状态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground">加载统计信息...</span>
 </div>
 <!-- 错误状态 -->
 <div v-else-if="error" class="text-center py-6">
 <div class="inline-flex rounded-full bg-destructive/10 mb-3">
 <span class="icon-[lucide--alert-triangle] text-2xl text-destructive" />
 </div>
 <p class="text-sm text-muted-foreground">
 无法加载统计信息
 </p>
 </div>
 <!-- 无数据 -->
 <div v-else-if="!stats || stats.chunks_total === 0" class="text-center py-6">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--bar-chart-3] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground">
 暂无索引数据
 </p>
 </div>
 <!-- 统计内容 -->
 <div v-else class="space-y-6">
 <!-- 数字指标 -->
 <div class="grid grid-cols-2 gap-3">
 <div class=" rounded-lg bg-muted/40 border border-border/50">
 <p class="text-xs text-muted-foreground">索引块数</p>
 <p class="text-xl font-bold text-foreground mt-0.5">
 {{ stats.chunks_total.toLocaleString }}
 </p>
 </div>
 <div class=" rounded-lg bg-muted/40 border border-border/50">
 <p class="text-xs text-muted-foreground">已索引文件</p>
 <p class="text-xl font-bold text-foreground mt-0.5">
 {{ stats.indexed_files_count.toLocaleString }}
 </p>
 </div>
 </div>
 <!-- 覆盖率进度条 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between text-sm">
 <span class="text-muted-foreground">索引覆盖率</span>
 <span class="font-medium":class="stats.coverage_percent >= 80 ? 'text-emerald-600': stats.coverage_percent >= 50 ? 'text-amber-600': 'text-destructive'">
 {{ stats.coverage_percent.toFixed(1) }}%
 </span>
 </div>
 <Progress:model-value="stats.coverage_percent" class="" />
 </div>
 <!-- 语言分布饼图 -->
 <div v-if="Object.keys(stats.language_distribution).length > 0" class="space-y-3">
 <p class="text-sm font-medium text-muted-foreground">
 语言分布
 </p>
 <div class="flex items-center gap-6">
 <!-- 饼图 -->
 <svg viewBox="0 0 100 100" class="w-24 shrink-0">
 <path
 v-for="slice in getPieSlices(stats.language_distribution)":key="slice.lang":d="slice.path":fill="slice.color"
 stroke="hsl(var(--card))"
 stroke-width="1"
 class="transition-opacity hover:opacity-80"
 />
 </svg>
 <!-- 图例 -->
 <div class="flex-1 space-y-1.5 min-w-0">
 <div
 v-for="slice in getPieSlices(stats.language_distribution).slice(0, 6)":key="slice.lang"
 class="flex items-center gap-2 text-sm"
 >
 <span class="w-2.5 .5 rounded-full shrink-0":style="{ backgroundColor: slice.color }" />
 <span class="truncate text-muted-foreground">{{ slice.lang }}</span>
 <span class="ml-auto text-xs font-medium tabular-nums">{{ (slice.percentage * 100).toFixed(0) }}%</span>
 </div>
 <p v-if="getPieSlices(stats.language_distribution).length > 6" class="text-xs text-muted-foreground pl-4.5">
 +{{ getPieSlices(stats.language_distribution).length - 6 }} 种语言
 </p>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
