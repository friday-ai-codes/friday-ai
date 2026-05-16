<script setup lang="ts">
import type { DiffusionEdgeType, NeighborMetadata } from '~/api/codegraph'
import type { GalaxyEdgeType, GalaxyNode, GalaxyNodeDetail } from '~/api/galaxy'
import type { SourceChunk } from '~/composables/useDiffusionGraph'
import { ScrollArea } from '~/components/ui/scroll-area'
import {
 Sheet,
 SheetContent,
 SheetDescription,
 SheetHeader,
 SheetTitle,
} from '~/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import { getGalaxyNodeDetail } from '~/api/galaxy'
import { defineAsyncComponent, ref, watch } from 'vue'
import ReferencesList from './ReferencesList.vue'
// 懒加载 GraphRAGDiffusionTab（避免引入 VueFlow 拖慢初始加载）
const GraphRAGDiffusionTab = defineAsyncComponent(
 => import('~/components/codegraph/GraphRAGDiffusionTab.vue'),
)
// ============================================================================
// Props / Emits
// ============================================================================
const props = defineProps<{
 nodeId: string | null
 modelValue: boolean
}>
const emit = defineEmits<{
 (e: 'update:modelValue', value: boolean): void
 (e: 'node-select', nodeId: string): void
}>
// ============================================================================
// 状态
// ============================================================================
const nodeDetail = ref<GalaxyNodeDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const activeTab = ref('info')
const metadataExpanded = ref(false)
// ============================================================================
// Galaxy → DiffusionEdgeType 映射
// ============================================================================
const GALAXY_TO_DIFFUSION: Record<GalaxyEdgeType, DiffusionEdgeType> = {
 CALL: 'CALL',
 IMPORT: 'IMPORT',
 SAME_FILE: 'SAME_FILE',
 TEST_OF: 'TEST_OF',
 CO_CHANGED: 'CO_CHANGED',
 SEMANTIC: 'SEMANTIC',
 API_CALLS: 'CALL',
 IMPLEMENTS: 'CALL',
}
function toNeighborMetadata(
 neighbors: GalaxyNodeDetail['neighbors'],
): NeighborMetadata {
 return neighbors.map(nb => ({
 chunk_id: nb.node.id,
 file_path: nb.node.file_path,
 line_start: nb.node.line_start,
 line_end: nb.node.line_end,
 edge_type: GALAXY_TO_DIFFUSION[nb.edge_type],
 weight: 1.0,
 reason: '',
 hop: 1 as const,
 }))
}
function toSourceChunks(node: GalaxyNode): SourceChunk {
 return [{
 chunk_id: node.id,
 file_path: node.file_path,
 line_start: node.line_start,
 line_end: node.line_end,
 }]
}
// ============================================================================
// 数据获取
// ============================================================================
watch( => props.nodeId, async (id) => {
 if (!id) {
 nodeDetail.value = null
 return
 }
 loading.value = true
 error.value = null
 activeTab.value = 'info'
 try {
 nodeDetail.value = await getGalaxyNodeDetail(id)
 }
 catch (e: unknown) {
 error.value = e instanceof Error ? e.message: '加载节点详情失败'
 }
 finally {
 loading.value = false
 }
}, { immediate: true })
// ============================================================================
// 节点类型视觉
// ============================================================================
const TYPE_COLORS: Record<string, string> = {
 chunk_registry: 'bg-gray-500/20 text-gray-300 border-gray-500/30',
 symbol: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
 endpoint: 'bg-orange-500/20 text-orange-300 border-orange-500/30',
 api_wrapper: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
 api_call_site: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
}
function typeColor(type: string): string {
 return TYPE_COLORS[type] ?? 'bg-white/10 text-white/50 border-white/20'
}
// ============================================================================
// 操作
// ============================================================================
function handleClose(open: boolean) {
 if (!open) emit('update:modelValue', false)
}
function handleNodeSelect(nodeId: string) {
 emit('node-select', nodeId)
}
</script>
<template>
 <Sheet:open="modelValue"
 @update:open="handleClose"
 >
 <SheetContent
 side="right"
 class="min-w-[480px] max-w-[640px] bg-[#0a0a1f]/95 backdrop-blur-xl border-l border-white/10 flex flex-col"
 >
 <!-- Header -->
 <SheetHeader class="px-6 pt-6 pb-4 border-b border-white/10 shrink-0">
 <div class="flex items-start gap-3">
 <!-- 节点类型图标 -->
 <div class="mt-0.5 shrink-0">
 <span
 class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border":class="nodeDetail ? typeColor(nodeDetail.node.type): 'bg-white/10 text-white/30 border-white/10'"
 >
 {{ nodeDetail?.node.type.replace(/_/g, ' ') ?? '...' }}
 </span>
 </div>
 <div class="flex-1 min-w-0">
 <SheetTitle class="text-white text-base font-semibold leading-snug truncate">
 {{ nodeDetail?.node.label ?? (loading ? '加载中...': '节点详情') }}
 </SheetTitle>
 <SheetDescription
 v-if="nodeDetail"
 class="text-white/40 text-xs mt-1 truncate font-mono"
 >
 {{ nodeDetail.node.file_path }}
 </SheetDescription>
 <SheetDescription
 v-else
 class="sr-only"
 >
 Galaxy 节点详情面板
 </SheetDescription>
 </div>
 </div>
 </SheetHeader>
 <!-- 错误状态 -->
 <div
 v-if="error"
 class="flex-1 flex items-center justify-center"
 >
 <div class="text-center space-y-2">
 <span class="icon-[lucide--alert-circle] text-3xl text-destructive block" />
 <p class="text-destructive text-sm">
 {{ error }}
 </p>
 </div>
 </div>
 <!-- 加载状态 -->
 <div
 v-else-if="loading"
 class="flex-1 flex items-center justify-center"
 >
 <span class="icon-[lucide--loader-circle] text-3xl text-primary animate-spin" />
 </div>
 <!-- Tabs 三段式内容 -->
 <Tabs
 v-else-if="nodeDetail"
 v-model="activeTab"
 class="flex-1 flex flex-col overflow-hidden"
 >
 <TabsList class="shrink-0 mx-6 mt-4 bg-white/5 border border-white/10">
 <TabsTrigger
 value="info"
 class="data-[state=active]:bg-white/10 data-[state=active]:text-white text-white/50"
 >
 <span class="icon-[lucide--info] mr-1.5 text-sm" />
 基础信息
 </TabsTrigger>
 <TabsTrigger
 value="graph"
 class="data-[state=active]:bg-white/10 data-[state=active]:text-white text-white/50"
 >
 <span class="icon-[lucide--share-2] mr-1.5 text-sm" />
 关系图
 </TabsTrigger>
 <TabsTrigger
 value="refs"
 class="data-[state=active]:bg-white/10 data-[state=active]:text-white text-white/50"
 >
 <span class="icon-[lucide--list] mr-1.5 text-sm" />
 引用列表
 </TabsTrigger>
 </TabsList>
 <!-- Tab: 基础信息 -->
 <TabsContent
 value="info"
 class="flex-1 overflow-auto mt-0"
 >
 <ScrollArea class="h-full">
 <div class="px-6 py-4 space-y-6">
 <!-- 字段网格 -->
 <dl class="grid grid-cols-2 gap-x-4 gap-y-3">
 <div>
 <dt class="text-white/40 text-xs uppercase tracking-wider">
 仓库
 </dt>
 <dd class="text-white/80 text-sm mt-1 truncate">
 {{ nodeDetail.node.repository_id }}
 </dd>
 </div>
 <div>
 <dt class="text-white/40 text-xs uppercase tracking-wider">
 节点类型
 </dt>
 <dd class="mt-1">
 <span
 class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium border":class="typeColor(nodeDetail.node.type)"
 >
 {{ nodeDetail.node.type }}
 </span>
 </dd>
 </div>
 <div class="col-span-2">
 <dt class="text-white/40 text-xs uppercase tracking-wider">
 文件路径
 </dt>
 <dd class="text-white/80 text-xs mt-1 font-mono break-all">
 {{ nodeDetail.node.file_path }}
 </dd>
 </div>
 <div>
 <dt class="text-white/40 text-xs uppercase tracking-wider">
 行范围
 </dt>
 <dd class="text-white/80 text-sm mt-1">
 {{ nodeDetail.node.line_start }} — {{ nodeDetail.node.line_end }}
 </dd>
 </div>
 <div>
 <dt class="text-white/40 text-xs uppercase tracking-wider">
 连接度
 </dt>
 <dd class="text-white/80 text-sm mt-1 font-mono">
 {{ nodeDetail.node.degree }}
 </dd>
 </div>
 </dl>
 <!-- Metadata 折叠 -->
 <div v-if="nodeDetail.node.metadata && Object.keys(nodeDetail.node.metadata).length > 0">
 <button
 class="flex items-center gap-2 text-white/40 text-xs uppercase tracking-wider hover:text-white/60 transition-colors w-full"
 @click="metadataExpanded = !metadataExpanded"
 >
 <span
 class="icon-[lucide--chevron-right] text-sm transition-transform":class="metadataExpanded ? 'rotate-90': ''"
 />
 元数据
 </button>
 <div
 v-if="metadataExpanded"
 class="mt-2 rounded-lg bg-white/5 border border-white/10"
 >
 <pre class="text-white/60 text-xs font-mono whitespace-pre-wrap break-all">{{ JSON.stringify(nodeDetail.node.metadata, null, 2) }}</pre>
 </div>
 </div>
 </div>
 </ScrollArea>
 </TabsContent>
 <!-- Tab: 关系图（GraphRAGDiffusionTab 懒加载） -->
 <TabsContent
 value="graph"
 class="flex-1 mt-0 overflow-hidden"
 >
 <div class="h-[440px] relative">
 <Suspense v-if="activeTab === 'graph'">
 <GraphRAGDiffusionTab:hop1-neighbors="toNeighborMetadata(nodeDetail.neighbors)":hop2-neighbors="":source-chunks="toSourceChunks(nodeDetail.node)":loading="loading"
 @node-click="handleNodeSelect"
 />
 <template #fallback>
 <div class="absolute inset-0 flex items-center justify-center">
 <span class="icon-[lucide--loader-circle] text-3xl text-primary animate-spin" />
 </div>
 </template>
 </Suspense>
 <div
 v-else
 class="absolute inset-0 flex items-center justify-center text-white/20 text-sm"
 >
 切换到「关系图」Tab 加载图谱
 </div>
 </div>
 </TabsContent>
 <!-- Tab: 引用列表 -->
 <TabsContent
 value="refs"
 class="flex-1 mt-0 overflow-hidden"
 >
 <ReferencesList:called-by="nodeDetail.called_by":calls="nodeDetail.references":neighbors="nodeDetail.neighbors":loading="loading"
 class="h-full"
 @node-select="handleNodeSelect"
 />
 </TabsContent>
 </Tabs>
 <!-- 无 nodeId 空状态 -->
 <div
 v-else
 class="flex-1 flex items-center justify-center"
 >
 <p class="text-white/20 text-sm">
 请选择节点
 </p>
 </div>
 </SheetContent>
 </Sheet>
</template>
