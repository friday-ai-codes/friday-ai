<route lang="yaml">
meta:
 requiresAdmin: true
 title: 检索测试面板
</route>
<script setup lang="ts">
import type { PlaygroundSearchParams, PlaygroundSearchResponse } from '~/api/codegraph'
import { playgroundSearch } from '~/api/codegraph'
import LayerResultsAccordion from '~/components/codegraph/LayerResultsAccordion.vue'
import PlaygroundQueryInput from '~/components/codegraph/PlaygroundQueryInput.vue'
const router = useRouter
const isLoading = ref(false)
const searchResult = ref<PlaygroundSearchResponse | null>(null)
const searchError = ref<string | null>(null)
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
 <!-- 右侧 LayerResultsAccordion -->
 <LayerResultsAccordion:result="searchResult":loading="isLoading"
 class="flex-1 min-w-0"
 />
 </div>
 </div>
</template>
