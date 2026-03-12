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
 streamingStatus?: 'streaming' | 'interrupted' | 'budget_exceeded' | null
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
// Thinking 时间追踪
const thinkingStartTime = ref<number | null>(null)
const thinkingDuration = ref(0)
// 监听 thinking 内容开始
watch( => props.streamingThinking, (val) => {
 if (val && !thinkingStartTime.value) {
 thinkingStartTime.value = Date.now
 }
})
// 流结束时计算持续时间
watch( => props.isStreaming, (streaming) => {
 if (!streaming && thinkingStartTime.value) {
 thinkingDuration.value = Math.round((Date.now - thinkingStartTime.value) / 1000)
 }
})
// 消息状态（中断/预算超出）
const messageStatus = computed( => {
 // 流式中优先使用 streamingStatus
 if (props.streamingStatus === 'interrupted' || props.streamingStatus === 'budget_exceeded') {
 return props.streamingStatus
 }
 // 历史消息从 metadata 读取
 const meta = props.message.metadata as Record<string, unknown> | undefined
 return (meta?.status as string) || null
})
// Token 用量显示
const tokenDisplay = computed( => {
 const m = props.message.metadata as Record<string, unknown> | undefined
 const inputTokens = m?.input_tokens as number | undefined
 const outputTokens = m?.output_tokens as number | undefined
 if (!inputTokens && !outputTokens) return ''
 return `\u2191${formatTokens(inputTokens || 0)} \u2193${formatTokens(outputTokens || 0)}`
})
function formatTokens(n: number): string {
 if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
 return String(n)
}
// 格式化时间
function formatTime(dateStr: string) {
 return new Date(dateStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
// 获取元信息
const metadata = computed( => props.message.metadata as { model?: string, usage?: { prompt_tokens?: number, completion_tokens?: number, total_tokens?: number, input_tokens?: number, output_tokens?: number } } | undefined)
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
 v-if="hasThinking || thinkingDuration > 0"
 class="mb-3 rounded-xl bg-muted/30 border border-border/30 overflow-hidden transition-all duration-200"
 >
 <button
 type="button"
 class="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
 @click="thinkingExpanded = !thinkingExpanded"
 >
 <span
 class="icon-[lucide--brain] text-primary/60":class="isStreaming && hasThinking ? 'animate-pulse': ''"
 />
 <span class="italic">
 <template v-if="isStreaming && hasThinking">正在思考...</template>
 <template v-else-if="thinkingDuration > 0">思考了 {{ thinkingDuration }} 秒</template>
 <template v-else>思考过程</template>
 </span>
 <span
 class="ml-auto transition-transform duration-200":class="thinkingExpanded ? 'rotate-180': ''"
 >
 <span class="icon-[lucide--chevron-down] text-xs" />
 </span>
 </button>
 <div
 v-show="thinkingExpanded"
 class="px-3 pb-2 text-xs text-muted-foreground/80 italic whitespace-pre-wrap break-words max- overflow-y-auto transition-all duration-200"
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
 <!-- 中断/预算 Badge -->
 <div
 v-if="messageStatus === 'interrupted'"
 class="inline-flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full text-[10px] font-medium
 bg-destructive/10 text-destructive border border-destructive/20"
 >
 <span class="icon-[lucide--octagon-x] text-xs" />
 已中断
 </div>
 <div
 v-else-if="messageStatus === 'budget_exceeded'"
 class="inline-flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full text-[10px] font-medium
 bg-yellow-500/10 text-yellow-600 border border-yellow-500/20"
 >
 <span class="icon-[lucide--wallet] text-xs" />
 已达到预算上限
 </div>
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
 <template v-if="tokenDisplay">
 <span>&middot;</span>
 <span class="font-mono text-[10px]">{{ tokenDisplay }}</span>
 </template>
 </div>
 </div>
 </div>
</template>
