<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import {
 Collapsible,
 CollapsibleContent,
 CollapsibleTrigger,
} from '~/components/ui/collapsible'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
const props = defineProps<{
 name: string
 input: Record<string, unknown>
 result?: string
 status: 'running' | 'done'
}>
const isOpen = ref(false)
// 用 Shiki 渲染参数 JSON
const renderedInput = ref('')
const renderedResult = ref('')
let mdInstance: MarkdownIt | null = null
onMounted(async => {
 mdInstance = await getMarkdownRenderer
 // 渲染参数为 JSON 代码块
 const jsonStr = JSON.stringify(props.input, null, 2)
 renderedInput.value = mdInstance.render(`\`\`\`json\n${jsonStr}\n\`\`\``)
 // 渲染结果（纯文本截断）
 if (props.result) {
 renderResult(props.result)
 }
})
function renderResult(text: string) {
 if (!mdInstance)
 return
 const truncated = text.length > 500
 ? `${text.slice(0, 500)}...`: text
 renderedResult.value = mdInstance.render(truncated)
}
// 监听 result 变化（流式更新）
watch( => props.result, (newResult) => {
 if (newResult) {
 renderResult(newResult)
 }
})
// 工具名称映射（友好显示名）
const TOOL_LABELS: Record<string, string> = {
 browse_file_content: '浏览文件',
 list_project_structure: '项目结构',
 get_project_overview: '项目概览',
 search_repository_code: '搜索代码',
 list_project_repositories: '仓库列表',
 get_repository_info: '仓库信息',
}
const displayName = computed( => TOOL_LABELS[props.name] || props.name)
</script>
<template>
 <Collapsible v-model:open="isOpen" class="my-2">
 <CollapsibleTrigger class="w-full">
 <div
 class="flex items-center gap-2 px-3 py-2 rounded-xl text-xs transition-colors
 bg-muted/30 hover:bg-muted/50 border border-border/30"
 >
 <!-- 状态图标 -->
 <span
 v-if="status === 'running'"
 class="icon-[lucide--loader-2] text-sm text-primary animate-spin"
 />
 <span
 v-else
 class="icon-[lucide--check-circle-2] text-sm text-emerald-500"
 />
 <!-- 工具图标 -->
 <span class="icon-[lucide--wrench] text-sm text-muted-foreground" />
 <!-- 工具名称 -->
 <span class="font-medium text-foreground">{{ displayName }}</span>
 <!-- 状态文本 -->
 <span class="text-muted-foreground">
 {{ status === 'running' ? '调用中...': '已完成' }}
 </span>
 <!-- 展开/折叠指示 -->
 <span class="ml-auto">
 <span
 class="icon-[lucide--chevron-down] text-sm text-muted-foreground transition-transform duration-200":class="isOpen ? 'rotate-180': ''"
 />
 </span>
 </div>
 </CollapsibleTrigger>
 <CollapsibleContent>
 <div class="mt-1 px-3 py-2 rounded-xl bg-muted/20 border border-border/20 space-y-2">
 <!-- 参数 -->
 <div>
 <p class="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">
 参数
 </p>
 <div
 class="text-xs prose prose-sm dark:prose-invert max-w-none
 prose-pre:text-[11px] prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border/30 prose-pre:rounded-lg prose-pre:"
 v-html="renderedInput"
 />
 </div>
 <!-- 结果 -->
 <div v-if="result">
 <p class="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1">
 结果
 </p>
 <div
 class="text-xs prose prose-sm dark:prose-invert max-w-none overflow-hidden"
 v-html="renderedResult"
 />
 </div>
 <div v-else-if="status === 'running'" class="text-xs text-muted-foreground italic">
 等待返回...
 </div>
 </div>
 </CollapsibleContent>
 </Collapsible>
</template>
