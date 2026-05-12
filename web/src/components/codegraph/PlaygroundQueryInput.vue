<script setup lang="ts">
import type { PlaygroundSearchParams } from '~/api/codegraph'
import { repositoriesApi } from '~/api/repositories'
import { Button } from '~/components/ui/button'
import { Slider } from '~/components/ui/slider'
import { Textarea } from '~/components/ui/textarea'
const props = defineProps<{
 loading: boolean
}>
const emit = defineEmits<{
 'search': [params: PlaygroundSearchParams]
 'chat-prefill': [params: { query: string, repositoryIds: string }]
}>
const query = ref('')
const selectedRepoIds = ref<string>
const maxTokensArr = ref([8000])
const maxTokens = computed( => maxTokensArr.value[0] ?? 8000)
interface RepositoryOption {
 id: string
 name: string
}
const repositories = ref<RepositoryOption>
const repoDropdownOpen = ref(false)
onMounted(async => {
 try {
 const repos = await repositoriesApi.list
 repositories.value = repos.map(r => ({ id: r.id, name: r.name }))
 }
 catch {
 // 静默；空态 UI 已兜
 }
})
const selectedRepoLabels = computed( => {
 if (selectedRepoIds.value.length === 0)
 return '选择仓库（默认全部）'
 if (selectedRepoIds.value.length === 1) {
 const repo = repositories.value.find(r => r.id === selectedRepoIds.value[0])
 return repo?.name ?? selectedRepoIds.value[0]
 }
 return `已选 ${selectedRepoIds.value.length} 个仓库`
})
function toggleRepo(id: string) {
 const idx = selectedRepoIds.value.indexOf(id)
 if (idx === -1) {
 selectedRepoIds.value = [...selectedRepoIds.value, id]
 }
 else {
 selectedRepoIds.value = selectedRepoIds.value.filter(v => v !== id)
 }
}
function handleSearch {
 emit('search', {
 query: query.value,
 repositoryIds: selectedRepoIds.value,
 maxTokens: maxTokens.value,
 })
}
function handleChatPrefill {
 emit('chat-prefill', {
 query: query.value,
 repositoryIds: selectedRepoIds.value,
 })
}
const maxTokensDisplay = computed( => {
 const v = maxTokens.value
 return v >= 1000 ? `${(v / 1000).toFixed(0)}k`: String(v)
})
</script>
<template>
 <div class="card flex flex-col gap-4 w-[300px] shrink-0 self-start sticky top-4">
 <!-- 查询 -->
 <div>
 <label class="text-sm font-semibold mb-1.5 block">查询</label>
 <Textarea
 v-model="query"
 placeholder="输入自然语言查询，例如：处理认证的函数有哪些？"
 class="min-h-[120px] resize-none"
 />
 </div>
 <!-- 仓库多选 -->
 <div>
 <label class="text-sm font-semibold mb-1.5 block">仓库</label>
 <div class="relative">
 <button
 type="button"
 class="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm rounded-md border border-input bg-background hover:bg-accent/50 transition-colors"
 @click="repoDropdownOpen = !repoDropdownOpen"
 >
 <span class="truncate text-left">{{ selectedRepoLabels }}</span>
 <span class="icon-[lucide--chevron-down] shrink-0 text-muted-foreground" />
 </button>
 <div
 v-if="repoDropdownOpen"
 class="absolute z-10 mt-1 w-full rounded-md border border-border bg-popover shadow-md"
 >
 <div class="max- overflow-y-auto ">
 <div
 v-if="repositories.length === 0"
 class="px-3 py-2 text-xs text-muted-foreground"
 >
 暂无仓库
 </div>
 <button
 v-for="repo in repositories":key="repo.id"
 type="button"
 class="w-full flex items-center gap-2 px-3 py-1.5 text-sm rounded-sm hover:bg-accent/50 transition-colors text-left"
 @click="toggleRepo(repo.id)"
 >
 <span
 class="w-4 border rounded-sm flex items-center justify-center shrink-0":class="selectedRepoIds.includes(repo.id) ? 'bg-primary border-primary': 'border-input'"
 >
 <span v-if="selectedRepoIds.includes(repo.id)" class="icon-[lucide--check] w-3 text-primary-foreground" />
 </span>
 <span class="truncate">{{ repo.name }}</span>
 </button>
 </div>
 </div>
 </div>
 </div>
 <!-- 最大 Token 滑块 -->
 <div>
 <div class="flex justify-between mb-1.5">
 <label class="text-sm font-semibold">最大 Token</label>
 <span class="text-xs text-muted-foreground font-mono">{{ maxTokensDisplay }}</span>
 </div>
 <Slider
 v-model="maxTokensArr":min="1024":max="16384":step="512"
 />
 <div class="flex justify-between mt-1">
 <span class="text-xs text-muted-foreground">1k</span>
 <span class="text-xs text-muted-foreground">16k</span>
 </div>
 </div>
 <!-- 执行检索按钮 -->
 <Button:disabled="props.loading || !query.trim"
 class="w-full"
 @click="handleSearch"
 >
 <span v-if="props.loading" class="icon-[lucide--loader-circle] animate-spin mr-2 w-4 " />
 执行检索
 </Button>
 <!-- 在 Chat 中提问按钮 -->
 <Button
 variant="outline":disabled="!query.trim"
 class="w-full"
 @click="handleChatPrefill"
 >
 <span class="icon-[lucide--message-circle] mr-2 w-4 " />
 在 Chat 中提问
 </Button>
 </div>
</template>
