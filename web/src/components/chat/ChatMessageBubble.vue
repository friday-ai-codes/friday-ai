<script setup lang="ts">
import type { ConversationMessage } from '~/types/chat'
import { Avatar, AvatarFallback } from '~/components/ui/avatar'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import type MarkdownIt from 'markdown-it'
const props = defineProps<{
 message: ConversationMessage
 isStreaming?: boolean
 streamingContent?: string
 streamingToolCalls?: Array<{ id: string, name: string, input: Record<string, unknown>, result?: string, status: 'running' | 'done' }>
}>
// Markdown 渲染
const renderedHtml = ref('')
const mdReady = ref(false)
let mdInstance: MarkdownIt | null = null
onMounted(async => {
 mdInstance = await getMarkdownRenderer
 mdReady.value = true
 renderContent
})
// 渲染内容（含节流：流式期间 100ms，避免长回复卡顿）
const renderContent = useDebounceFn( => {
 if (!mdInstance) return
 const content = props.isStreaming
 ? (props.streamingContent || ''): props.message.content
 if (content) {
 renderedHtml.value = mdInstance.render(content)
 }
}, 100)
// 监听内容变化
watch(
 => props.isStreaming ? props.streamingContent: props.message.content,
 => {
 if (mdReady.value) renderContent
 },
)
// 格式化时间
function formatTime(dateStr: string) {
 return new Date(dateStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
// 获取元信息
const metadata = computed( => props.message.metadata as { model?: string, usage?: { prompt_tokens: number, completion_tokens: number, total_tokens: number } } | undefined)
</script>
<template>
 <div
 class="flex gap-3":class="message.role === 'user' ? 'flex-row-reverse': ''"
 >
 <!-- 头像 -->
 <Avatar class=" w-8 shrink-0 mt-1">
 <AvatarFallback:class="message.role === 'user'
 ? 'bg-gradient-to-br from-blue-500 to-cyan-400 text-white text-xs': 'bg-gradient-to-br from-primary/20 to-primary/10 text-primary text-xs'"
 >
 <span v-if="message.role === 'user'" class="icon-[lucide--user] text-sm" />
 <span v-else class="icon-[lucide--bot] text-sm" />
 </AvatarFallback>
 </Avatar>
 <!-- 气泡内容 -->
 <div class="max-w-[80%] space-y-1">
 <div
 class="rounded-2xl px-4 py-3":class="message.role === 'user'
 ? 'bg-gradient-to-r from-blue-500 to-cyan-400 text-white': 'bg-card/80 backdrop-blur-sm border border-border/50'"
 >
 <!-- 用户消息 -->
 <div v-if="message.role === 'user'" class="text-sm whitespace-pre-wrap break-words">
 {{ message.content }}
 </div>
 <!-- AI 消息 + Markdown 渲染 -->
 <div v-else>
 <!-- 流式中的光标（无内容时） -->
 <div
 v-if="isStreaming && !renderedHtml"
 class="flex items-center gap-1 text-sm text-muted-foreground"
 >
 <span class="inline-block w-2 bg-primary/60 animate-pulse rounded-sm" />
 </div>
 <!-- Markdown 渲染内容 -->
 <div
 v-else
 class="text-sm prose prose-sm dark:prose-invert max-w-none break-words
 prose-pre:bg-muted/50 prose-pre:border prose-pre:border-border/50 prose-pre:rounded-xl
 prose-code:text-primary prose-code:before:content-none prose-code:after:content-none"
 v-html="renderedHtml"
 />
 <!-- 流式打字光标 -->
 <span
 v-if="isStreaming && renderedHtml"
 class="inline-block w-2 bg-primary/60 animate-pulse rounded-sm ml-0.5"
 />
 <!-- 工具调用卡片插槽（Plan 填充） -->
 <slot name="tool-calls" />
 </div>
 </div>
 <!-- 元信息行 -->
 <div
 class="px-1 flex items-center gap-2 text-[10px] text-muted-foreground/60":class="message.role === 'user' ? 'justify-end': ''"
 >
 <span>{{ formatTime(message.created_at) }}</span>
 <template v-if="metadata?.model">
 <span>&middot;</span>
 <span>{{ metadata.model }}</span>
 </template>
 <template v-if="metadata?.usage">
 <span>&middot;</span>
 <span>{{ metadata.usage.total_tokens }} tokens</span>
 </template>
 </div>
 </div>
 </div>
</template>
