<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import type { ConversationMessage } from '~/types/chat'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
const props = defineProps<{
 message: ConversationMessage
 isStreaming?: boolean
 streamingContent?: string
 streamingThinking?: string
 streamingToolCalls?: Array<{ id: string, name: string, input: Record<string, unknown>, result?: string, status: 'running' | 'done' }>
 streamingStatus?: 'streaming' | 'interrupted' | 'budget_exceeded' | null
}>
const renderedHtml = ref('')
const mdReady = ref(false)
let mdInstance: MarkdownIt | null = null
const renderContent = useDebounceFn( => {
 if (!mdInstance)
 return
 const content = props.isStreaming
 ? (props.streamingContent || ''): props.message.content
 if (content)
 renderedHtml.value = mdInstance.render(content)
}, 80)
onMounted(async => {
 mdInstance = await getMarkdownRenderer
 mdReady.value = true
 renderContent
})
watch(
 => props.isStreaming ? props.streamingContent: props.message.content,
 => { if (mdReady.value) renderContent },
)
// Thinking：流式来自 props，历史来自 metadata
const thinkingText = computed( => {
 if (props.isStreaming)
 return props.streamingThinking || ''
 const meta = props.message.metadata as Record<string, unknown> | undefined
 return (meta?.thinking as string) || ''
})
const hasThinking = computed( => !!thinkingText.value)
const thinkingStartTime = ref<number | null>(null)
const thinkingDuration = ref(0)
watch( => props.streamingThinking, (val) => {
 if (val && !thinkingStartTime.value)
 thinkingStartTime.value = Date.now
})
watch( => props.isStreaming, (streaming) => {
 if (!streaming && thinkingStartTime.value)
 thinkingDuration.value = Math.round((Date.now - thinkingStartTime.value) / 1000)
})
const messageStatus = computed( => {
 if (props.streamingStatus === 'interrupted' || props.streamingStatus === 'budget_exceeded')
 return props.streamingStatus
 const meta = props.message.metadata as Record<string, unknown> | undefined
 return (meta?.status as string) || null
})
const tokenDisplay = computed( => {
 const m = props.message.metadata as Record<string, unknown> | undefined
 const input = m?.input_tokens as number | undefined
 const output = m?.output_tokens as number | undefined
 if (!input && !output)
 return ''
 return `${fmt(input || 0)} in · ${fmt(output || 0)} out`
})
function fmt(n: number): string {
 return n >= 1000 ? `${(n / 1000).toFixed(1)}k`: String(n)
}
function formatTime(dateStr: string) {
 return new Date(dateStr).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
const metadata = computed( => props.message.metadata as { model?: string } | undefined)
const [copied, toggleCopied] = useToggle(false)
function copyContent {
 const content = props.isStreaming ? (props.streamingContent || ''): props.message.content
 if (content) {
 navigator.clipboard.writeText(content)
 toggleCopied(true)
 setTimeout( => toggleCopied(false), 2000)
 }
}
// 工具调用数据（流式或历史）
const toolCalls = computed( => {
 if (props.isStreaming && props.streamingToolCalls && props.streamingToolCalls.length > 0)
 return props.streamingToolCalls
 if (props.message.tool_calls && props.message.tool_calls.length > 0) {
 return props.message.tool_calls.map((tc: any) => ({
 ...tc,
 status: tc.status || 'done',
 result: tc.result || undefined,
 }))
 }
 return
})
// 工具名称映射
const TOOL_LABELS: Record<string, string> = {
 browse_file_content: '浏览文件',
 list_project_structure: '项目结构',
 get_project_overview: '项目概览',
 search_repository_code: '搜索代码',
 list_project_repositories: '仓库列表',
 get_repository_info: '仓库信息',
}
function toolLabel(name: string): string {
 const bare = name.replace(/^mcp__[^_]+__/, '')
 return TOOL_LABELS[bare] || bare
}
function toolAction(name: string, input: Record<string, unknown>): string {
 const bare = name.replace(/^mcp__[^_]+__/, '')
 switch (bare) {
 case 'search_repository_code': {
 const q = (input?.query as string) || ''
 return q ? `搜索「${q.slice(0, 40)}${q.length > 40 ? '...': ''}」`: '搜索代码'
 }
 case 'browse_file_content': {
 const p = (input?.file_path as string) || (input?.path as string) || ''
 return p ? `查看 ${p}`: '浏览文件内容'
 }
 case 'get_project_overview':
 return '获取项目概览'
 case 'list_project_repositories':
 return '列出所有仓库'
 case 'list_project_structure':
 return '浏览文件结构'
 case 'get_repository_info':
 return '获取仓库详情'
 default:
 return Object.entries(input || {}).slice(0, 2)
 .map(([k, v]) => `${k}: ${typeof v === 'string' ? v.slice(0, 30): JSON.stringify(v)}`)
 .join(', ') || '执行操作'
 }
}
// 工具调用详情展开
const expandedTools = ref<Set<string>>(new Set)
function toggleTool(id: string) {
 if (expandedTools.value.has(id))
 expandedTools.value.delete(id)
 else
 expandedTools.value.add(id)
}
</script>
<template>
 <!-- ======================== 用户消息 ======================== -->
 <div v-if="message.role === 'user'" class="flex justify-end pl-12">
 <div class="user-bubble">
 {{ message.content }}
 </div>
 </div>
 <!-- ======================== AI 消息 ======================== -->
 <div v-else class="ai-message group pr-8">
 <!-- 正文 -->
 <div v-if="isStreaming && !renderedHtml && toolCalls.length === 0" class="flex items-center py-2">
 <span class="typing-cursor" />
 </div>
 <div
 v-if="renderedHtml"
 class="ai-prose"
 v-html="renderedHtml"
 />
 <span v-if="isStreaming && renderedHtml" class="typing-cursor" />
 <!-- 工具调用 — 行内 pill 流 -->
 <div v-if="toolCalls.length > 0" class="tool-flow">
 <div v-for="tc in toolCalls":key="tc.id" class="tool-inline">
 <!-- 主行：状态 + 名称 + 描述 -->
 <div class="tool-pill" @click="toggleTool(tc.id)">
 <span v-if="tc.status === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-name">{{ toolLabel(tc.name) }}</span>
 <span class="tool-pill-desc">{{ toolAction(tc.name, tc.input || {}) }}</span>
 <span
 v-if="tc.input && Object.keys(tc.input).length > 0"
 class="icon-[lucide--chevron-right] text-[9px] text-muted-foreground/40 transition-transform duration-150":class="expandedTools.has(tc.id) ? 'rotate-90': ''"
 />
 </div>
 <!-- 展开详情 -->
 <div v-if="expandedTools.has(tc.id)" class="tool-detail">
 <div class="tool-detail-section">
 <span class="tool-detail-label">输入</span>
 <pre class="tool-detail-json">{{ JSON.stringify(tc.input, null, 2) }}</pre>
 </div>
 <div v-if="tc.result" class="tool-detail-section">
 <span class="tool-detail-label">输出</span>
 <pre class="tool-detail-json">{{ typeof tc.result === 'string' && tc.result.length > 600 ? tc.result.slice(0, 600) + '...': tc.result }}</pre>
 </div>
 </div>
 </div>
 </div>
 <!-- 流式中等待工具返回的光标 -->
 <div v-if="isStreaming && !renderedHtml && toolCalls.length > 0" class="flex items-center py-1">
 <span class="typing-cursor" />
 </div>
 <!-- 状态 Badge -->
 <div v-if="messageStatus === 'interrupted'" class="status-badge status-badge--interrupted">
 <span class="icon-[lucide--octagon-x] text-[10px]" />
 已中断
 </div>
 <div v-else-if="messageStatus === 'budget_exceeded'" class="status-badge status-badge--budget">
 <span class="icon-[lucide--wallet] text-[10px]" />
 已达到预算上限
 </div>
 <!-- Thinking — 全量展示，不折叠 -->
 <div v-if="hasThinking" class="thinking-block">
 <div class="thinking-header">
 <span class="thinking-icon":class="isStreaming ? 'animate-pulse': ''">
 <span class="icon-[lucide--sparkles] text-[10px]" />
 </span>
 <span v-if="isStreaming">思考中...</span>
 <span v-else-if="thinkingDuration > 0">思考过程 · {{ thinkingDuration }}s</span>
 <span v-else>思考过程</span>
 </div>
 <div class="thinking-content">
 {{ thinkingText }}
 </div>
 </div>
 <!-- 操作栏 -->
 <div class="action-bar">
 <button class="action-btn" @click="copyContent">
 <span v-if="copied" class="icon-[lucide--check] text-primary" />
 <span v-else class="icon-[lucide--copy]" />
 </button>
 <span class="action-divider" />
 <span class="action-meta">{{ formatTime(message.created_at) }}</span>
 <template v-if="metadata?.model">
 <span class="action-meta">·</span>
 <span class="action-meta">{{ metadata.model }}</span>
 </template>
 <template v-if="tokenDisplay">
 <span class="action-meta">·</span>
 <span class="action-meta font-mono">{{ tokenDisplay }}</span>
 </template>
 </div>
 </div>
</template>
<style scoped>
/* ============ User Bubble ============ */
.user-bubble {
 max-width: 80%;
 padding: 0.625rem 1rem;
 border-radius: 1.25rem 1.25rem 0.375rem 1.25rem;
 background: linear-gradient(135deg, #14b8a6, #06b6d4);
 color: white;
 font-size: 0.875rem;
 line-height: 1.625;
 white-space: pre-wrap;
 word-break: break-word;
 box-shadow: 0 1px 3px rgba(20, 184, 166, 0.2);
}
/* ============ AI Message ============ */
.ai-message {
 display: flex;
 flex-direction: column;
 gap: 0.625rem;
}
/* ============ Tool Flow — 行内 pill ============ */
.tool-flow {
 display: flex;
 flex-direction: column;
 gap: 0.25rem;
}
.tool-inline {
 display: flex;
 flex-direction: column;
}
.tool-pill {
 display: inline-flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.25rem 0.625rem;
 border-radius: 0.5rem;
 font-size: 0.75rem;
 cursor: pointer;
 transition: background 0.1s;
 width: fit-content;
 max-width: 100%;
}
.tool-pill:hover {
 background: hsl(210 40% 96%);
}
.tool-dot {
 width: 5px;
 height: 5px;
 border-radius: 50%;
 flex-shrink: 0;
}
.tool-dot--running {
 background: hsl(168 76% 42%);
 animation: pulse-dot 1.5s infinite;
}
.tool-dot--done {
 background: hsl(142 71% 45%);
}
.tool-pill-name {
 font-weight: 600;
 color: hsl(215 28% 17%);
 white-space: nowrap;
}
.tool-pill-desc {
 color: hsl(215 16% 47% / 0.7);
 font-size: 0.6875rem;
 overflow: hidden;
 text-overflow: ellipsis;
 white-space: nowrap;
 min-width: 0;
}
/* Tool detail (展开) */
.tool-detail {
 margin-left: 1.25rem;
 padding: 0.375rem 0.5rem;
 border-left: 2px solid hsl(214 32% 91% / 0.6);
 display: flex;
 flex-direction: column;
 gap: 0.375rem;
}
.tool-detail-section {
 display: flex;
 flex-direction: column;
 gap: 0.125rem;
}
.tool-detail-label {
 font-size: 0.5625rem;
 font-weight: 600;
 text-transform: uppercase;
 letter-spacing: 0.06em;
 color: hsl(215 16% 47% / 0.5);
}
.tool-detail-json {
 font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
 font-size: 0.625rem;
 line-height: 1.5;
 padding: 0.375rem 0.5rem;
 border-radius: 0.375rem;
 background: hsl(210 40% 96% / 0.6);
 color: hsl(215 28% 25%);
 white-space: pre-wrap;
 word-break: break-all;
 margin: 0;
 max-height: 10rem;
 overflow-y: auto;
}
/* ============ Thinking — 全量展示 ============ */
.thinking-block {
 border-radius: 0.625rem;
 border: 1px solid hsl(214 32% 91% / 0.5);
 background: hsl(210 40% 98% / 0.6);
 overflow: hidden;
}
.thinking-header {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.375rem 0.625rem;
 font-size: 0.6875rem;
 color: hsl(215 16% 47% / 0.7);
 border-bottom: 1px solid hsl(214 32% 91% / 0.4);
}
.thinking-icon {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 1.125rem;
 height: 1.125rem;
 border-radius: 0.3125rem;
 background: hsl(168 76% 42% / 0.08);
 color: hsl(168 76% 42%);
}
.thinking-content {
 padding: 0.5rem 0.625rem;
 font-size: 0.75rem;
 line-height: 1.7;
 color: hsl(215 16% 35%);
 white-space: pre-wrap;
 word-break: break-word;
 max-height: 30rem;
 overflow-y: auto;
}
/* ============ Prose ============ */
.ai-prose {
 font-size: 0.9375rem;
 line-height: 1.75;
 color: hsl(215 28% 17%);
}
.ai-prose:deep(h1) {
 font-size: 1.375rem;
 font-weight: 700;
 letter-spacing: -0.01em;
 margin: 1.75rem 0 0.75rem;
 color: hsl(215 28% 12%);
}
.ai-prose:deep(h1:first-child) { margin-top: 0; }
.ai-prose:deep(h2) {
 font-size: 1.175rem;
 font-weight: 650;
 letter-spacing: -0.005em;
 margin: 1.5rem 0 0.5rem;
 color: hsl(215 28% 12%);
}
.ai-prose:deep(h2:first-child) { margin-top: 0; }
.ai-prose:deep(h3) {
 font-size: 1rem;
 font-weight: 600;
 margin: 1.25rem 0 0.375rem;
 color: hsl(215 28% 15%);
}
.ai-prose:deep(h3:first-child) { margin-top: 0; }
.ai-prose:deep(p) { margin: 0.625rem 0; }
.ai-prose:deep(p:first-child) { margin-top: 0; }
.ai-prose:deep(p:last-child) { margin-bottom: 0; }
.ai-prose:deep(strong) {
 font-weight: 600;
 color: hsl(215 28% 12%);
}
.ai-prose:deep(a) {
 color: hsl(168 76% 36%);
 text-decoration: none;
 border-bottom: 1px solid hsl(168 76% 42% / 0.3);
 transition: border-color 0.15s;
}
.ai-prose:deep(a:hover) { border-bottom-color: hsl(168 76% 42%); }
.ai-prose:deep(ul) { list-style: disc; padding-left: 1.375rem; margin: 0.5rem 0; }
.ai-prose:deep(ol) { list-style: decimal; padding-left: 1.375rem; margin: 0.5rem 0; }
.ai-prose:deep(li) { margin: 0.25rem 0; padding-left: 0.25rem; }
.ai-prose:deep(li > p) { margin: 0.125rem 0; }
.ai-prose:deep(li:marker) { color: hsl(215 16% 60%); }
.ai-prose:deep(code) {
 font-size: 0.8125rem;
 font-weight: 500;
 padding: 0.125rem 0.375rem;
 border-radius: 0.3125rem;
 background: hsl(168 76% 42% / 0.07);
 color: hsl(168 56% 30%);
 font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', ui-monospace, monospace;
}
.ai-prose:deep(pre) {
 margin: 0.875rem 0;
 border-radius: 0.75rem;
 border: 1px solid hsl(214 32% 91% / 0.5);
 overflow-x: auto;
 font-size: 0.8125rem;
 line-height: 1.6;
}
.ai-prose:deep(pre code) {
 background: transparent;
 padding: 0;
 border-radius: 0;
 color: inherit;
 font-weight: 400;
}
.ai-prose:deep(blockquote) {
 border-left: 3px solid hsl(168 76% 42% / 0.4);
 padding: 0.25rem 0 0.25rem 1rem;
 margin: 0.75rem 0;
 color: hsl(215 16% 47%);
}
.ai-prose:deep(blockquote p) { margin: 0.25rem 0; }
.ai-prose:deep(hr) { border: none; border-top: 1px solid hsl(214 32% 91%); margin: 1.5rem 0; }
.ai-prose:deep(table) { width: 100%; border-collapse: collapse; font-size: 0.8125rem; margin: 0.875rem 0; }
.ai-prose:deep(th) { text-align: left; font-weight: 600; padding: 0.5rem 0.75rem; border-bottom: 2px solid hsl(214 32% 91%); }
.ai-prose:deep(td) { padding: 0.5rem 0.75rem; border-bottom: 1px solid hsl(214 32% 91% / 0.6); }
.ai-prose:deep(tr:last-child td) { border-bottom: none; }
/* ============ Typing Cursor ============ */
.typing-cursor {
 display: inline-block;
 width: 2px;
 height: 1.125rem;
 background: hsl(168 76% 42%);
 border-radius: 1px;
 animation: blink 1s step-end infinite;
 vertical-align: text-bottom;
 margin-left: 1px;
}
@keyframes blink { 50% { opacity: 0; } }
/* ============ Status Badge ============ */
.status-badge {
 display: inline-flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.25rem 0.625rem;
 border-radius: 9999px;
 font-size: 0.6875rem;
 font-weight: 500;
}
.status-badge--interrupted {
 background: hsl(0 72% 51% / 0.06);
 color: hsl(0 72% 51%);
 border: 1px solid hsl(0 72% 51% / 0.12);
}
.status-badge--budget {
 background: hsl(38 92% 50% / 0.06);
 color: hsl(38 80% 40%);
 border: 1px solid hsl(38 92% 50% / 0.12);
}
/* ============ Action Bar ============ */
.action-bar {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 padding-top: 0.125rem;
 opacity: 0;
 transition: opacity 0.15s;
}
.group:hover .action-bar { opacity: 1; }
.action-btn {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 1.5rem;
 height: 1.5rem;
 border-radius: 0.375rem;
 font-size: 0.75rem;
 color: hsl(215 16% 60%);
 cursor: pointer;
 transition: all 0.15s;
}
.action-btn:hover { background: hsl(210 40% 96%); color: hsl(215 28% 17%); }
.action-divider { width: 1px; height: 0.75rem; background: hsl(214 32% 91%); margin: 0 0.125rem; }
.action-meta { font-size: 0.6875rem; color: hsl(215 16% 60% / 0.7); }
@keyframes pulse-dot {
 0%, 100% { opacity: 1; }
 50% { opacity: 0.4; }
}
</style>
