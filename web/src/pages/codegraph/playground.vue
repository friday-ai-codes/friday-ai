<route lang="yaml">
meta:
 requiresAdmin: true
 title: 检索测试面板
</route>
<script setup lang="ts">
import type { PlaygroundSearchParams, PlaygroundSearchResponse } from '~/api/codegraph'
import type { SourceChunk } from '~/composables/useDiffusionGraph'
import { playgroundSearch } from '~/api/codegraph'
import CodePreviewDrawer from '~/components/codegraph/CodePreviewDrawer.vue'
import GraphRAGDiffusionTab from '~/components/codegraph/GraphRAGDiffusionTab.vue'
import LayerResultsAccordion from '~/components/codegraph/LayerResultsAccordion.vue'
import PlaygroundQueryInput from '~/components/codegraph/PlaygroundQueryInput.vue'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
const router = useRouter
const isLoading = ref(false)
const searchResult = ref<PlaygroundSearchResponse | null>(null)
const searchError = ref<string | null>(null)
// Phase Plan：Tabs 容器（per work item §10 硬约束 16，默认 layers）
const activeTab = ref<'layers' | 'graphrag'>('layers')
// Phase Plan：Drawer state（CodePreviewDrawer 占位，Plan 接力）
const drawerOpen = ref(false)
const selectedChunkId = ref<string | null>(null)
// Plan 完整实现（ 修复）：从 result.layers 中 layer === 'L3' 的 items 反查
// 抽取 source chunk 列表，作为二跳扩散图的"起点"节点（per ROADMAP §SC2）。
// 复用 CodePreviewDrawer.findChunkInLayers 同款解析模式（per work item §10 硬约束 6
// — 仅消费 L3 layers items，不引入新 chunk 详情 API），保持单一真值源。
function extractSourceChunks(result: PlaygroundSearchResponse | null): SourceChunk {
 if (!result?.layers)
 return
 const l3 = result.layers.find(l => l.layer === 'L3')
 if (!l3)
 return
 const out: SourceChunk =
 for (const raw of l3.items) {
 if (typeof raw !== 'object' || raw === null)
 continue
 const item = raw as Record<string, unknown>
 if (typeof item.chunk_id !== 'string' || typeof item.file_path !== 'string')
 continue
 out.push({
 chunk_id: item.chunk_id,
 file_path: item.file_path,
 line_start: typeof item.line_start === 'number' ? item.line_start: null,
 line_end: typeof item.line_end === 'number' ? item.line_end: null,
 content: typeof item.content === 'string' ? item.content: undefined,
 })
 }
 return out
}
function onDiffusionNodeClick(chunkId: string) {
 selectedChunkId.value = chunkId
 drawerOpen.value = true
}
async function handleSearch(params: PlaygroundSearchParams) {
 isLoading.value = true
 searchError.value = null
 try {
 searchResult.value = await playgroundSearch(params)
 }
 catch (err: unknown) {
 searchError.value = err instanceof Error ? err.message: '检索失败，请稍后重试'
 }
 finally {
 isLoading.value = false
 }
}
function handleChatPrefill(params: { query: string, repositoryIds: string }) {
 const q = encodeURIComponent(params.query)
 const ids = (params.repositoryIds ?? ).join(',')
 router.push(`/chat?prefilled_query=${q}&repository_ids=${ids}`)
}
</script>
<template>
 <div class="max-w-7xl mx-auto space-y-6">
 <!-- 页面 Header -->
 <div class="flex items-center gap-3">
 <div class=".5 rounded-xl bg-primary/10 flex items-center justify-center">
 <span class="icon-[lucide--beaker] text-2xl text-primary" />
 </div>
 <div>
 <h1 class="text-base font-semibold">
 检索测试面板
 </h1>
 <p class="text-sm text-muted-foreground">
 测试分层检索各阶段召回效果，验证图谱增强质量
 </p>
 </div>
 </div>
 <!-- 错误提示 -->
 <p v-if="searchError" class="text-sm text-destructive flex items-center gap-2">
 <span class="icon-[lucide--alert-circle]" />
 检索失败：{{ searchError }}
 </p>
 <!-- 左右分栏 -->
 <div class="flex gap-4 items-start">
 <!-- 左侧 QueryInput -->
 <PlaygroundQueryInput:loading="isLoading"
 @search="handleSearch"
 @chat-prefill="handleChatPrefill"
 />
 <!-- 右侧 Tabs 容器（Phase Plan：layers + graphrag 双 tab） -->
 <div class="card flex-1 min-w-0">
 <Tabs v-model="activeTab" class="w-full">
 <TabsList class="grid grid-cols-2 ">
 <TabsTrigger value="layers" class="flex items-center gap-1.5">
 <span class="icon-[lucide--layers]" />
 分层检索结果
 </TabsTrigger>
 <TabsTrigger value="graphrag" class="flex items-center gap-1.5">
 <span class="icon-[lucide--share-2]" />
 GraphRAG 二跳扩散
 </TabsTrigger>
 </TabsList>
 <TabsContent value="layers" class="mt-0">
 <LayerResultsAccordion:result="searchResult":loading="isLoading"
 class="border-none shadow-none"
 />
 </TabsContent>
 <TabsContent value="graphrag" class="mt-0">
 <GraphRAGDiffusionTab:hop1-neighbors="searchResult?.hop1_neighbors ?? ":hop2-neighbors="searchResult?.hop2_neighbors ?? ":source-chunks="extractSourceChunks(searchResult)":loading="isLoading"
 @node-click="onDiffusionNodeClick"
 />
 </TabsContent>
 </Tabs>
 </div>
 </div>
 <!-- 代码预览 Drawer（Plan 占位，Plan 实装） -->
 <CodePreviewDrawer
 v-model:open="drawerOpen":chunk-id="selectedChunkId":search-result="searchResult"
 />
 </div>
</template>
