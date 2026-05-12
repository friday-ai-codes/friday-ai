<script setup lang="ts">
import type { IndexedFilesResponse } from '~/api/repositories'
import { useDebounceFn } from '@vueuse/core'
import { computed, onMounted, ref, watch } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { Button } from '~/components/ui/button'
import {
 Tooltip,
 TooltipContent,
 TooltipProvider,
 TooltipTrigger,
} from '~/components/ui/tooltip'
const props = defineProps<{
 repositoryId: string
 gitUrl?: string
}>
const loading = ref(false)
const data = ref<IndexedFilesResponse | null>(null)
const searchInput = ref('')
const search = ref('')
const page = ref(1)
const pageSize = 20
async function loadFiles {
 loading.value = true
 try {
 data.value = await repositoriesApi.getIndexedFiles(props.repositoryId, {
 search: search.value || undefined,
 page: page.value,
 page_size: pageSize,
 })
 }
 catch {
 // 全局拦截器已上报，这里不再二次提示
 }
 finally {
 loading.value = false
 }
}
const debouncedApplySearch = useDebounceFn( => {
 search.value = searchInput.value.trim
 page.value = 1
}, 300)
watch(searchInput, debouncedApplySearch)
watch([search, page], loadFiles)
onMounted(loadFiles)
const totalPages = computed( => {
 if (!data.value)
 return 0
 return Math.max(1, Math.ceil(data.value.total / pageSize))
})
const items = computed( => data.value?.items ?? )
const total = computed( => data.value?.total ?? 0)
function formatDate(input: string | null) {
 if (!input)
 return '-'
 return new Date(input).toLocaleString('zh-CN')
}
function shortSha(sha: string | null | undefined) {
 if (!sha)
 return ''
 return sha.slice(0, 7)
}
function commitUrl(sha: string) {
 if (!props.gitUrl)
 return ''
 return `${props.gitUrl.replace(/\.git$/, '')}/commit/${sha}`
}
function clearSearch {
 searchInput.value = ''
 search.value = ''
 page.value = 1
}
</script>
<template>
 <div class="card">
 <div class="px-5 py-3.5 border-b border-border/50">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--file-search] text-primary" />
 <h3 class="text-sm font-semibold">
 已索引文件
 </h3>
 <span class="text-xs text-muted-foreground">查询/搜索本仓库被索引的文件，以及各文件最近一次 commit</span>
 </div>
 </div>
 <div class=" space-y-4">
 <!-- 搜索栏 + 统计 -->
 <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
 <div class="relative w-full sm:max-w-md">
 <span class="icon-[lucide--search] absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm" />
 <input
 v-model="searchInput"
 type="text"
 placeholder="搜索文件路径，例如 server/views"
 class="w-full pl-9 pr-9 rounded-lg border border-border/60 bg-background text-sm focus:outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30 transition-colors"
 >
 <button
 v-if="searchInput"
 class="absolute right-2 top-1/2 -translate-y-1/2 rounded hover:bg-muted/50 transition-colors"
 @click="clearSearch"
 >
 <span class="icon-[lucide--x] text-xs text-muted-foreground" />
 </button>
 </div>
 <span class="text-xs text-muted-foreground">
 共 {{ total }} 个已索引文件{{ search ? `（匹配 "${search}"）`: '' }}
 </span>
 </div>
 <!-- 加载态 -->
 <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-muted-foreground text-sm">加载中...</span>
 </div>
 <!-- 空状态 -->
 <div v-else-if="!items.length" class="text-center py-8">
 <div class="inline-flex rounded-full bg-muted/50 mb-3">
 <span class="icon-[lucide--file-x] text-3xl text-muted-foreground" />
 </div>
 <p class="text-muted-foreground text-sm">
 {{ search ? '未找到匹配的文件': '尚无已索引文件' }}
 </p>
 </div>
 <!-- 列表 -->
 <div v-else class="overflow-hidden rounded-xl border border-border/50">
 <div class="grid grid-cols-[1fr_120px_180px] text-xs text-muted-foreground bg-muted/30 px-4 py-2 border-b border-border/50">
 <div>文件路径</div>
 <div>最近 commit</div>
 <div>索引时间</div>
 </div>
 <div>
 <div
 v-for="item in items":key="item.file_path"
 class="grid grid-cols-[1fr_120px_180px] items-center px-4 py-2.5 text-xs border-b border-border/30 last:border-b-0 hover:bg-muted/30 transition-colors"
 >
 <div class="min-w-0">
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <span class="font-mono truncate block text-foreground">{{ item.file_path }}</span>
 </TooltipTrigger>
 <TooltipContent>{{ item.file_path }}</TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 <div class="font-mono">
 <template v-if="item.last_commit_sha">
 <a
 v-if="gitUrl":href="commitUrl(item.last_commit_sha)"
 target="_blank"
 rel="noopener noreferrer"
 class="text-primary hover:underline inline-flex items-center gap-1":title="item.last_commit_sha"
 >
 {{ shortSha(item.last_commit_sha) }}
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <span v-else:title="item.last_commit_sha" class="text-foreground">
 {{ shortSha(item.last_commit_sha) }}
 </span>
 </template>
 <span v-else class="text-muted-foreground">—</span>
 </div>
 <div class="text-muted-foreground">
 {{ formatDate(item.indexed_at) }}
 </div>
 </div>
 </div>
 </div>
 <!-- 分页 -->
 <div v-if="totalPages > 1" class="flex items-center justify-between pt-1">
 <span class="text-xs text-muted-foreground">第 {{ page }} / {{ totalPages }} 页</span>
 <div class="flex items-center gap-1">
 <Button
 variant="outline"
 size="sm"
 class=" w-7 ":disabled="page <= 1"
 @click="page--"
 >
 <span class="icon-[lucide--chevron-left]" />
 </Button>
 <Button
 variant="outline"
 size="sm"
 class=" w-7 ":disabled="page >= totalPages"
 @click="page++"
 >
 <span class="icon-[lucide--chevron-right]" />
 </Button>
 </div>
 </div>
 </div>
 </div>
</template>
