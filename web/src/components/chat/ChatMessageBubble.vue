<script setup lang="ts">
import type { ConversationMessage } from '~/types/chat'
import { Avatar, AvatarFallback } from '~/components/ui/avatar'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import ChatToolCall from './ChatToolCall.vue'
import type MarkdownIt from 'markdown-it'
const props = defineProps<{
 message: ConversationMessage
 isStreaming?: boolean
 streamingContent?: string
 streamingThinking?: string
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
// Thinking 折叠状态
const thinkingExpanded = ref(false)
const hasThinking = computed( => !!props.streamingThinking)
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
 <!-- Thinking 折叠面板 -->
 <div
 v-if="isStreaming && hasThinking"
 class="mb-3 rounded-xl bg-muted/30 border border-border/30 overflow-hidden"
 >
 <button
 type="button"
 class="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="thinkingExpanded = !thinkingExpanded"
 >
 <span class="icon-[lucide--brain] text-primary/60 animate-pulse" />
 <span class="italic">正在思考...</span>
 <span
 class="ml-auto transition-transform duration-200":class="thinkingExpanded ? 'rotate-180': ''"
 >
 <span class="icon-[lucide--chevron-down] text-xs" />
 </span>
 </button>
 <div
 v-show="thinkingExpanded"
 class="px-3 pb-2 text-xs text-muted-foreground/80 italic whitespace-pre-wrap break-words max- overflow-y-auto"
 >
 {{ streamingThinking }}
 </div>
 </div>
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
 <!-- 工具调用卡片（流式） -->
 <template v-if="isStreaming && streamingToolCalls && streamingToolCalls.length > 0">
 <ChatToolCall
 v-for="tc in streamingToolCalls":key="tc.id":name="tc.name":input="tc.input":result="tc.result":status="tc.status"
 />
 </template>
 <!-- 工具调用卡片（历史消息） -->
 <template v-else-if="message.tool_calls && message.tool_calls.length > 0">
 <ChatToolCall
 v-for="tc in message.tool_calls":key="tc.id":name="tc.name":input="tc.input"
 status="done"
 />
 </template>
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
