<script setup lang="ts">
/**
 * NodeDataTab — 抽屉输入/输出数据标签页
 *
 * 以 JSON 格式展示节点的输入数据和输出数据。
 * AI 节点的输出数据中，文本字段自动以 Markdown 渲染，
 * 非文本字段仍以 JSON 展示。可切换回原始 JSON 视图。
 */
import { computed, ref, watch } from 'vue'
import type { NodeExecution } from '~/stores/useExecutionsStore'
import { ScrollArea } from '~/components/ui/scroll-area'
import MarkdownRenderer from './MarkdownRenderer.vue'
const props = defineProps<{
 nodeExecution: NodeExecution
}>
/** AI 节点类型常量 */
const AI_NODE_TYPES = [
 'ai_prompt', 'ai_coding', 'ai_code_review',
 'ai_plan_generation', 'ai_coding_dispatcher',
] as const
const isAINode = computed( =>
 AI_NODE_TYPES.includes(props.nodeExecution.node_type as typeof AI_NODE_TYPES[number]),
)
/** 「查看原始数据」切换 */
const showRawOutput = ref(false)
/** 切换节点时重置视图模式 */
watch( => props.nodeExecution.id, => {
 showRawOutput.value = false
})
/** 智能文本字段检测：判断某个字段是否应该以 Markdown 渲染 */
function isMarkdownField(key: string, value: unknown): boolean {
 if (typeof value !== 'string') return false
 if (value.length < 20) return false
 // 关键字段名匹配
 const textFieldNames = [
 'text', 'content', 'output', 'result', 'summary',
 'description', 'plan', 'review', 'analysis', 'response',
 'final_result', 'text_output',
 ]
 if (textFieldNames.some(name => key.toLowerCase.includes(name))) return true
 // Markdown 标记检测
 const mdPatterns = /^#{1,6}\s|^\*\*|^- |^\d+\.\s|```|^\|.*\|$/m
 return mdPatterns.test(value)
}
/** 分离输出数据：Markdown 可渲染字段 */
const markdownFields = computed( => {
 if (!isAINode.value || showRawOutput.value) return
 const output = props.nodeExecution.output_data
 if (!output) return
 return Object.entries(output)
 .filter(([key, value]) => isMarkdownField(key, value))
 .map(([key, value]) => ({ key, value: value as string }))
})
/** 分离输出数据：剩余 JSON 字段 */
const jsonFields = computed( => {
 if (!isAINode.value || showRawOutput.value) return props.nodeExecution.output_data
 const output = props.nodeExecution.output_data
 if (!output) return null
 const mdKeys = new Set(markdownFields.value.map(f => f.key))
 const remaining = Object.fromEntries(
 Object.entries(output).filter(([key]) => !mdKeys.has(key)),
 )
 return Object.keys(remaining).length > 0 ? remaining: null
})
function formatJson(data: Record<string, any> | null | undefined): string {
 if (!data || Object.keys(data).length === 0) return ''
 return JSON.stringify(data, null, 2)
}
</script>
<template>
 <div class="space-y-4">
 <!-- 输入数据 -->
 <div class="space-y-2">
 <div class="text-sm font-medium text-foreground">
 输入数据
 </div>
 <ScrollArea class="max-h-[250px]">
 <div
 v-if="formatJson(nodeExecution.input_data)"
 class="bg-muted/50 rounded-lg "
 >
 <pre class="text-xs text-foreground/80 whitespace-pre-wrap break-words font-mono">{{ formatJson(nodeExecution.input_data) }}</pre>
 </div>
 <div v-else class="text-sm text-muted-foreground italic">
 (空)
 </div>
 </ScrollArea>
 </div>
 <!-- 输出数据 -->
 <div class="space-y-2">
 <div class="flex items-center justify-between">
 <div class="text-sm font-medium text-foreground">
 输出数据
 </div>
 <!-- AI 节点：原始数据 / 智能渲染 切换按钮 -->
 <button
 v-if="isAINode && markdownFields.length > 0"
 class="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
 @click="showRawOutput = !showRawOutput"
 >
 <span class="icon-[lucide--code-2] w-3.5 .5" />
 {{ showRawOutput ? '智能渲染': '查看原始数据' }}
 </button>
 </div>
 <ScrollArea class="max-h-[400px]">
 <!-- AI 节点智能渲染模式 -->
 <template v-if="isAINode && !showRawOutput && markdownFields.length > 0">
 <!-- Markdown 字段 -->
 <div
 v-for="field in markdownFields":key="field.key"
 class="space-y-1 mb-4"
 >
 <div class="text-xs font-medium text-muted-foreground uppercase tracking-wider">
 {{ field.key }}
 </div>
 <div class="bg-card/80 backdrop-blur-sm border border-border/50 rounded-xl ">
 <MarkdownRenderer:content="field.value" />
 </div>
 </div>
 <!-- 剩余 JSON 字段 -->
 <div v-if="jsonFields" class="space-y-1">
 <div class="text-xs font-medium text-muted-foreground uppercase tracking-wider">
 其他数据
 </div>
 <div class="bg-muted/50 rounded-lg ">
 <pre class="text-xs text-foreground/80 whitespace-pre-wrap break-words font-mono">{{ formatJson(jsonFields) }}</pre>
 </div>
 </div>
 </template>
 <!-- 原始 JSON 模式（非 AI 节点 / showRawOutput） -->
 <template v-else>
 <div
 v-if="formatJson(nodeExecution.output_data)"
 class="bg-muted/50 rounded-lg "
 >
 <pre class="text-xs text-foreground/80 whitespace-pre-wrap break-words font-mono">{{ formatJson(nodeExecution.output_data) }}</pre>
 </div>
 <div v-else class="text-sm text-muted-foreground italic">
 (空)
 </div>
 </template>
 </ScrollArea>
 </div>
 </div>
</template>
