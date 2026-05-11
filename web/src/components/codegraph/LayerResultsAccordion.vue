<script setup lang="ts">
import type { PlaygroundSearchResponse } from '~/api/codegraph'
import { Button } from '~/components/ui/button'
import { Skeleton } from '~/components/ui/skeleton'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
const props = defineProps<{
 result: PlaygroundSearchResponse | null
 loading: boolean
}>
interface LayerConfig {
 id: string
 label: string
 desc: string
 layerKey: string
}
const LAYERS: LayerConfig = [
 {
 id: 'l1',
 label: 'L1 仓库路由',
 desc: '根据查询匹配最相关仓库，返回路由理由及置信度评分',
 layerKey: 'L1',
 },
 {
 id: 'l2',
 label: 'L2 Symbol 查找',
 desc: '在路由仓库中检索匹配的代码符号（函数/类/接口）及签名',
 layerKey: 'L2',
 },
 {
 id: 'l3',
 label: 'L3 混合检索',
 desc: '向量相似度 + BM25 关键词检索代码片段，双路召回后合并排序',
 layerKey: 'L3',
 },
 {
 id: 'l4',
 label: 'L4 图谱扩展',
 desc: '从 L2 命中 Symbol 出发，沿调用图谱扩展 1-hop 邻居节点',
 layerKey: 'L4',
 },
 {
 id: 'l5',
 label: 'L5 上下文重组',
 desc: '将 L3/L4 结果按 token 预算拼装为最终 context，传入 LLM',
 layerKey: 'L5',
 },
]
function getLayerData(layerKey: string) {
 return props.result?.layers.find(l => l.layer === layerKey) ?? null
}
// 各层展开状态（初始全部折叠）
const openStates = ref<Record<string, boolean>>({
 l1: false,
 l2: false,
 l3: false,
 l4: false,
 l5: false,
})
function toggleLayer(id: string) {
 openStates.value[id] = !openStates.value[id]
}
// L5 final_context 展开状态
const l5Expanded = ref(false)
</script>
<template>
 <div class="card flex-1 min-w-0">
 <!-- 头部 -->
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--layers] text-primary" />
 <h3 class="text-sm font-semibold">
 分层检索结果
 </h3>
 <span v-if="!props.result && !props.loading" class="text-xs text-muted-foreground">执行检索后显示结果</span>
 </div>
 <div class=" space-y-2">
 <div
 v-for="layer in LAYERS":key="layer.id"
 class="border border-border/50 rounded-lg overflow-hidden"
 >
 <!-- Accordion 标题行 -->
 <button
 type="button"
 class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
 @click="toggleLayer(layer.id)"
 >
 <span
 class="icon-[lucide--chevron-right] text-muted-foreground transition-transform shrink-0":class="openStates[layer.id] ? 'rotate-90': ''"
 />
 <span class="text-sm font-semibold flex-1">{{ layer.label }}</span>
 <!-- 命中数 Badge -->
 <template v-if="props.loading">
 <Skeleton class=" w-12 rounded-full" />
 </template>
 <template v-else>
 <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-mono bg-muted text-muted-foreground tabular-nums">
 {{ getLayerData(layer.layerKey)?.result_count ?? '–' }} 条
 </span>
 </template>
 <!-- 错误状态 -->
 <span
 v-if="getLayerData(layer.layerKey)?.error"
 class="inline-flex items-center px-2 py-0.5 rounded-full text-xs bg-destructive/10 text-destructive"
 >
 错误
 </span>
 <!-- 功能说明 Tooltip -->
 <TooltipProvider>
 <Tooltip>
 <TooltipTrigger as-child>
 <span
 class="icon-[lucide--info] w-3.5 .5 text-muted-foreground cursor-help shrink-0"
 aria-label="功能说明"
 />
 </TooltipTrigger>
 <TooltipContent class="max-w-[240px]">
 {{ layer.desc }}
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </button>
 <!-- Accordion 内容 -->
 <div v-show="openStates[layer.id]" class="border-t border-border/50">
 <!-- Loading 骨架屏 -->
 <div v-if="props.loading" class=" space-y-2">
 <Skeleton class=" w-full" />
 <Skeleton class=" w-3/4" />
 <Skeleton class=" w-1/2" />
 </div>
 <!-- 错误提示 -->
 <div
 v-else-if="getLayerData(layer.layerKey)?.error"
 class=""
 >
 <p class="text-sm text-destructive flex items-center gap-2">
 <span class="icon-[lucide--alert-circle]" />
 {{ getLayerData(layer.layerKey)?.error }}
 </p>
 </div>
 <!-- 无结果 -->
 <div
 v-else-if="!props.result"
 class=" text-sm text-muted-foreground"
 >
 暂无数据
 </div>
 <!-- L5: final_context -->
 <div
 v-else-if="layer.id === 'l5'"
 class=""
 >
 <div class="relative">
 <div
 class="font-mono text-xs bg-muted/30 rounded-lg overflow-y-auto transition-all":class="l5Expanded ? 'max-h-none': 'max-'"
 >
 <pre class="whitespace-pre-wrap break-words">{{ props.result?.final_context ?? '' }}</pre>
 </div>
 <!-- 渐隐遮罩 + 展开按钮 -->
 <div
 v-if="!l5Expanded"
 class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-background/80 to-transparent rounded-b-lg flex items-end justify-center pb-2"
 >
 <Button variant="ghost" size="sm" class="text-xs " @click="l5Expanded = true">
 <span class="icon-[lucide--expand] mr-1.5 w-3.5 .5" />
 展开全文
 </Button>
 </div>
 <div v-else class="mt-2 flex justify-center">
 <Button variant="ghost" size="sm" class="text-xs " @click="l5Expanded = false">
 收起
 </Button>
 </div>
 </div>
 <p class="mt-2 text-xs text-muted-foreground font-mono">
 总计 {{ props.result?.total_tokens?.toLocaleString ?? '—' }} tokens
 </p>
 </div>
 <!-- L1~L4: items 列表 -->
 <div v-else class="">
 <div
 v-if="!getLayerData(layer.layerKey)?.items?.length"
 class="text-sm text-muted-foreground"
 >
 无结果
 </div>
 <div v-else class="space-y-2">
 <div
 v-for="(item, idx) in (getLayerData(layer.layerKey)?.items ?? )":key="idx"
 class="flex items-start gap-2 px-3 py-2 rounded-lg bg-muted/20 text-xs font-mono"
 >
 <pre class="whitespace-pre-wrap break-words text-xs">{{ JSON.stringify(item, null, 2) }}</pre>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
