<script setup lang="ts">
import type MarkdownIt from 'markdown-it'
import type { ConversationMessage, StreamTimelineItem, ToolCallData } from '~/types/chat'
import { Checkbox } from '~/components/ui/checkbox'
import { getMarkdownRenderer } from '~/composables/useMarkdownRenderer'
import DocSummaryCard from './DocSummaryCard.vue'
import TechPlanCard from './TechPlanCard.vue'
const props = defineProps<{
 message: ConversationMessage
 isStreaming?: boolean
 streamingContent?: string
 streamingThinking?: string
 streamingToolCalls?: Array<{ id: string, name: string, input: Record<string, unknown>, result?: string, status: 'running' | 'done' }>
 streamingTimeline?: StreamTimelineItem
 streamingStatus?: 'streaming' | 'interrupted' | 'budget_exceeded' | null
 streamingNarrations?: string
 streamingPendingText?: string
 deepAnalysisLogs?: Array<{ type: string, content: string, ts: number }>
 streamingDocSummary?: {
 type: 'summary' | 'error' | 'loading'
 title?: string
 wordCount?: number
 preview?: string
 truncated?: boolean
 truncatedLength?: number
 errorType?: 'permission_denied' | 'not_found' | 'not_configured' | 'unknown'
 errorMessage?: string
 } | null
}>
const emit = defineEmits<{
 exportSingle: [messageId: string]
}>
const chatStore = useChatStore
const isSelected = computed( =>
 chatStore.selectedMessageIds.has(props.message.id),
)
// 飞书文档摘要数据：流式来自 prop，历史来自消息 metadata
const docSummary = computed( => {
 if (props.isStreaming && props.streamingDocSummary) {
 return props.streamingDocSummary
 }
 const meta = props.message.metadata as Record<string, unknown> | undefined
 return (meta?.docSummary as typeof props.streamingDocSummary) || null
})
const renderedHtml = ref('')
const mdReady = ref(false)
let mdInstance: MarkdownIt | null = null
const contentSource = computed( => (
 props.isStreaming
 ? (props.streamingContent || ''): props.message.content
))
const renderContent = useDebounceFn( => {
 if (!mdInstance)
 return
 renderedHtml.value = contentSource.value
 ? mdInstance.render(contentSource.value): ''
}, 80)
onMounted(async => {
 mdInstance = await getMarkdownRenderer
 mdReady.value = true
 renderContent
})
watch(
 contentSource,
 => {
 if (mdReady.value)
 renderContent
 },
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
const showThinking = ref(!!props.isStreaming)
watch( => props.streamingThinking, (val) => {
 if (val && !thinkingStartTime.value)
 thinkingStartTime.value = Date.now
})
watch( => props.isStreaming, (streaming) => {
 if (!streaming && thinkingStartTime.value)
 thinkingDuration.value = Math.round((Date.now - thinkingStartTime.value) / 1000)
})
watch( => props.message.id, => {
 showThinking.value = !!props.isStreaming
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
// 工具调用数据（流式或历史），含 id 去重
const toolCalls = computed( => {
 let calls: Array<{ id: string, name: string, input: Record<string, unknown>, result?: string, status: string }>
 if (props.isStreaming && props.streamingToolCalls && props.streamingToolCalls.length > 0) {
 calls = props.streamingToolCalls
 }
 else if (props.message.tool_calls && props.message.tool_calls.length > 0) {
 const mapped = props.message.tool_calls.map((tc: ToolCallData) => ({
 ...tc,
 status: tc.status || 'done',
 result: tc.result || undefined,
 }))
 const deepCalls = mapped.filter(tc => isDeepAnalysisTool(tc.name))
 if (deepCalls.length > 1) {
 const primary = deepCalls.find(tc => tc.result || (tc.input && Object.keys(tc.input).length > 0)) || deepCalls[0]
 const ghostIds = new Set(deepCalls.filter(tc => tc.id !== primary.id).map(tc => tc.id))
 calls = mapped.filter(tc => !ghostIds.has(tc.id))
 }
 else {
 calls = mapped
 }
 }
 else {
 return
 }
 // 按 id 去重，保留首次出现
 const seen = new Set<string>
 return calls.filter((tc) => {
 if (seen.has(tc.id))
 return false
 seen.add(tc.id)
 return true
 })
})
// 工具名称映射
const TOOL_LABELS: Record<string, string> = {
 browse_file_content: '浏览文件',
 list_project_structure: '空间结构',
 get_project_overview: '空间概览',
 search_repository_code: '搜索代码',
 list_project_repositories: '仓库列表',
 get_repository_info: '仓库信息',
 deep_analysis: '深度分析',
 create_coding_plan: '编码方案',
 update_coding_plan: '更新方案',
}
function toolLabel(name: string): string {
 const bare = name.replace(/^mcp__[^_]+__/, '')
 return TOOL_LABELS[bare] || bare
}
function toolAction(name: string, input: Record<string, unknown>, result?: string): string {
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
 return '获取空间概览'
 case 'list_project_repositories':
 return '列出所有仓库'
 case 'list_project_structure':
 return '浏览文件结构'
 case 'get_repository_info':
 return '获取仓库详情'
 case 'deep_analysis': {
 const desc = (input?.task_description as string) || ''
 let label = desc ? `分析「${desc.slice(0, 30)}${desc.length > 30 ? '...': ''}」`: '深度代码分析'
 if (result) {
 const resultStr = typeof result === 'string' ? result: JSON.stringify(result)
 try {
 const parsed = JSON.parse(resultStr)
 const sid = parsed?.data?.session_id
 if (sid)
 label += ` · ${sid}`
 }
 catch {
 const m = resultStr.match(/session: ([\w-]+)/)
 if (m)
 label += ` · ${m[1]}`
 }
 }
 return label
 }
 default: {
 const entries = Object.entries(input || {}).slice(0, 2)
 const desc = entries.map(([k, v]) => `${k}: ${typeof v === 'string' ? v.slice(0, 30): JSON.stringify(v)}`).join(', ')
 return desc || '执行操作'
 }
 }
}
// 叙述文本（流式或历史）
const narrations = computed( => {
 if (props.isStreaming)
 return props.streamingNarrations ||
 const meta = props.message.metadata as Record<string, unknown> | undefined
 return (meta?.narrations as string) ||
})
const showNarrations = ref(false)
const hasNarrations = computed( => narrations.value.length > 0)
// 流式中正在输入的叙述文本（尚未归档到 narrations）
const pendingNarration = computed( => {
 if (!props.isStreaming)
 return ''
 return props.streamingPendingText || ''
})
const timelineItems = computed<StreamTimelineItem>( => {
 const items = props.isStreaming
 ? [...(props.streamingTimeline || )]: Array.isArray((props.message.metadata as Record<string, unknown> | undefined)?.timeline)
 ? [...((props.message.metadata as Record<string, unknown>).timeline as StreamTimelineItem)]:
 if (props.isStreaming && pendingNarration.value.trim) {
 items.push({
 id: '__pending_narration__',
 kind: 'narration',
 text: pendingNarration.value,
 })
 }
 return items
})
const hasTimeline = computed( => timelineItems.value.length > 0)
// 工具调用详情展开
const expandedTools = ref<Set<string>>(new Set)
function toggleTool(id: string) {
 if (expandedTools.value.has(id))
 expandedTools.value.delete(id)
 else
 expandedTools.value.add(id)
}
// 工具分组展开状态（连续同类工具默认收起为一组，参考 Cursor 风格）
const expandedGroups = ref<Set<string>>(new Set)
function toggleGroup(id: string) {
 if (expandedGroups.value.has(id))
 expandedGroups.value.delete(id)
 else
 expandedGroups.value.add(id)
}
// 拥有专属卡片渲染的工具不参与分组（CodingPlanCard / deep-analysis-panel）
const UNGROUPABLE_TOOLS = new Set(['deep_analysis', 'create_coding_plan', 'update_coding_plan'])
function isGroupableTool(name: string): boolean {
 return !UNGROUPABLE_TOOLS.has(name.replace(/^mcp__[^_]+__/, ''))
}
interface ToolItemShape {
 id: string
 name: string
 input: Record<string, unknown>
 result?: string
 status: 'running' | 'done'
 batch_id?: string
}
interface ToolGroupNode {
 id: string
 kind: 'tool-group'
 /** 同 batch 但工具名可能不同时为 undefined，仅在单一同名时填值（用于显示组标签） */
 toolName?: string
 items: ToolItemShape
 /** 区分分组来源：batch_id（后端语义批） / consecutive-same（兼容历史） */
 source: 'batch' | 'consecutive-same'
}
type DisplayItem = StreamTimelineItem | ToolGroupNode | (ToolItemShape & { kind: 'tool' })
/**
 * 时间线分组策略（per v25.0 chat-timeline-batch 设计）：
 *
 * 1. 优先按 `batch_id` 分组：后端 chat_runner 给同一 LLM turn 的所有 tool_call
 * 打同一个 batch_id，这是语义上"同批并行决定"的边界。即使工具名不同
 * （比如同时搜 collection + favorite + 笔记），也归到一组横向 chip 流。
 *
 * 2. 没有 batch_id（历史消息 / 老后端 / 单工具调用）退化到"连续同名"分组，
 * 保持旧契约不破坏 (per `web/src/components/chat/__tests__/chat-visual-contract.spec.ts`)。
 *
 * 3. UNGROUPABLE_TOOLS（deep_analysis / coding_plan）始终单独成块，
 * 它们有专属卡片渲染，不参与任何分组。
 */
function packGroups<T extends ToolItemShape>(
 flat: Array<T | StreamTimelineItem>,
 toToolShape: (t: T) => ToolItemShape,
): DisplayItem {
 const out: DisplayItem =
 let i = 0
 while (i < flat.length) {
 const cur = flat[i] as T | StreamTimelineItem
 const isTool = 'name' in cur && (('kind' in cur && (cur as StreamTimelineItem).kind === 'tool') || !('kind' in cur))
 if (!isTool) {
 out.push(cur as StreamTimelineItem)
 i++
 continue
 }
 const curTool = cur as T
 if (!isGroupableTool(curTool.name)) {
 out.push({ ...toToolShape(curTool), kind: 'tool' } as DisplayItem)
 i++
 continue
 }
 const curBatch = curTool.batch_id
 const bare = curTool.name.replace(/^mcp__[^_]+__/, '')
 let j = i + 1
 while (j < flat.length) {
 const next = flat[j] as T | StreamTimelineItem
 const nextIsTool = 'name' in next && (('kind' in next && (next as StreamTimelineItem).kind === 'tool') || !('kind' in next))
 if (!nextIsTool)
 break
 const nextTool = next as T
 if (!isGroupableTool(nextTool.name))
 break
 if (curBatch) {
 // batch 模式：只要 batch_id 一致就归入（工具名可以不同）
 if (nextTool.batch_id !== curBatch)
 break
 }
 else {
 // 兼容模式：要求工具名一致
 if (nextTool.batch_id)
 break
 if (nextTool.name.replace(/^mcp__[^_]+__/, '') !== bare)
 break
 }
 j++
 }
 if (j - i >= 2) {
 const run = (flat.slice(i, j) as T).map(toToolShape)
 const uniqueNames = new Set(run.map(it => it.name.replace(/^mcp__[^_]+__/, '')))
 out.push({
 id: `group-${curTool.id}`,
 kind: 'tool-group',
 toolName: uniqueNames.size === 1 ? curTool.name: undefined,
 items: run,
 source: curBatch ? 'batch': 'consecutive-same',
 })
 }
 else {
 out.push({ ...toToolShape(curTool), kind: 'tool' } as DisplayItem)
 }
 i = j
 }
 return out
}
const groupedTimelineItems = computed<DisplayItem>( =>
 packGroups<Extract<StreamTimelineItem, { kind: 'tool' }>>(
 timelineItems.value,
 t => ({ id: t.id, name: t.name, input: t.input, result: t.result, status: t.status, batch_id: t.batch_id }),
 ),
)
const groupedToolCalls = computed<DisplayItem>( =>
 packGroups<ToolItemShape>(
 toolCalls.value as ToolItemShape,
 t => ({ id: t.id, name: t.name, input: t.input, result: t.result, status: t.status, batch_id: t.batch_id }),
 ),
)
function groupStatus(items: ToolItemShape): 'running' | 'done' {
 return items.some(it => it.status === 'running') ? 'running': 'done'
}
function lastItemDescription(items: ToolItemShape): string {
 if (items.length === 0)
 return ''
 const last = items[items.length - 1]
 return toolAction(last.name, last.input || {}, last.result)
}
/**
 * 同 batch 多工具时的简略标签：合并工具名 + 总数。
 * 例如 [search ×3, browse ×1] -> "搜索代码 ×3 · 浏览文件 ×1"
 */
function groupLabel(group: ToolGroupNode): string {
 if (group.toolName)
 return toolLabel(group.toolName)
 const counts = new Map<string, number>
 for (const it of group.items) {
 const bare = it.name.replace(/^mcp__[^_]+__/, '')
 counts.set(bare, (counts.get(bare) || 0) + 1)
 }
 return Array.from(counts.entries)
 .map(([n, c]) => `${toolLabel(n)}${c > 1 ? ` ×${c}`: ''}`)
 .join(' · ')
}
/** 同 batch 多工具的 chip 简短文案（去掉"搜索代码"前缀，只留关键词） */
function chipSummary(item: ToolItemShape): string {
 const bare = item.name.replace(/^mcp__[^_]+__/, '')
 if (bare === 'search_repository_code') {
 const q = (item.input?.query as string) || ''
 return q.length > 24 ? `${q.slice(0, 24)}…`: q || '搜索'
 }
 if (bare === 'browse_file_content') {
 const p = (item.input?.file_path as string) || (item.input?.path as string) || ''
 const seg = p.split('/').pop || p
 return seg.length > 24 ? `${seg.slice(0, 24)}…`: seg || '文件'
 }
 // 默认退化到 toolAction 完整描述
 return toolAction(item.name, item.input || {}, item.result)
}
// 是否使用 chip 横排模式：batch 来源的组使用 chip 模式，纵向列表保留给"连续同名"
function shouldUseChipLayout(group: ToolGroupNode): boolean {
 return group.source === 'batch'
}
// 单条 thinking item 的展开状态（默认收起，仅显示首行预览）
const expandedThinking = ref<Set<string>>(new Set)
function toggleThinking(id: string) {
 if (expandedThinking.value.has(id))
 expandedThinking.value.delete(id)
 else
 expandedThinking.value.add(id)
}
function thinkingPreview(text: string): string {
 const trimmed = text.trim
 const firstLine = trimmed.split('\n')[0] || ''
 return firstLine.length > 80 ? `${firstLine.slice(0, 80)}…`: firstLine
}
function thinkingIsMultiline(text: string): boolean {
 const trimmed = text.trim
 return trimmed.includes('\n') || trimmed.length > 80
}
// 深度分析实时日志
const deepAnalysisExpanded = ref(true)
const resolvedDeepAnalysisLogs = computed( => {
 if (props.isStreaming)
 return props.deepAnalysisLogs ||
 const meta = props.message.metadata as Record<string, unknown> | undefined
 const logs = meta?.deep_analysis_logs
 return Array.isArray(logs) ? logs as Array<{ type: string, content: string, ts: number }>:
})
const hasDeepAnalysisLogs = computed( =>
 resolvedDeepAnalysisLogs.value.length > 0,
)
function isDeepAnalysisTool(name: string): boolean {
 return name.replace(/^mcp__[^_]+__/, '') === 'deep_analysis'
}
function isCodingPlanTool(name: string): boolean {
 const bare = name.replace(/^mcp__[^_]+__/, '')
 return bare === 'create_coding_plan' || bare === 'update_coding_plan'
}
// 从 toolCalls 中提取 coding plan 数据
const codingPlanData = computed( => {
 const planTool = toolCalls.value.find(tc => isCodingPlanTool(tc.name))
 if (!planTool)
 return null
 // tech_plan 和 affected_files 来自 tool input（不在 result 中）
 const input = planTool.input || {}
 const techPlan = (input.tech_plan as string) || ''
 // Phase：兼容 file_path / path 两种 schema 字段名
 const affectedFiles = (input.affected_files as Array<{ file_path?: string, path?: string, change_type: string }>) ||
 // session_id / status / coding_plan_id 来自 tool result。
 // 防御性双轨：result 在快照(snapshot) / langchain_runner 路径里是 JSON string，
 // 但历史上 chat_runner 曾直接发 dict（未序列化）—— 这里两种形态都吃。
 let sessionId = ''
 let planId = ''
 let sessionStatus: string = 'draft'
 if (planTool.result) {
 const raw: unknown = planTool.result
 let parsed: { session_id?: string, coding_session_id?: string, coding_plan_id?: string, status?: string } | null = null
 if (typeof raw === 'string') {
 try {
 parsed = JSON.parse(raw)
 }
 catch {
 parsed = null
 }
 }
 else if (typeof raw === 'object') {
 parsed = raw as { session_id?: string, coding_session_id?: string, coding_plan_id?: string, status?: string }
 }
 if (parsed) {
 // Phase：优先用 coding_session_id（新返回），回退到 session_id（兼容 alias）
 sessionId = parsed.coding_session_id || parsed.session_id || ''
 planId = parsed.coding_plan_id || ''
 sessionStatus = parsed.status || 'draft'
 }
 }
 return { sessionId, planId, techPlan, affectedFiles, status: sessionStatus }
})
// 编码方案的实时状态（优先使用 store 中的 activeCodingSession）
const codingPlanStatus = computed( => {
 const data = codingPlanData.value
 if (!data)
 return 'draft'
 const active = chatStore.activeCodingSession
 if (active && active.sessionId === data.sessionId) {
 return active.status
 }
 return data.status as 'draft' | 'confirmed' | 'running' | 'completed' | 'failed'
})
const codingPlanConfirming = computed( => {
 const data = codingPlanData.value
 if (!data)
 return false
 const active = chatStore.activeCodingSession
 return !!(active && active.sessionId === data.sessionId && active.isConfirming)
})
// 从 tool result 中提取分支名（: 服务端推断的分支名传给 CodingPlanCard）
const codingPlanBranchName = computed( => {
 const data = codingPlanData.value
 if (!data)
 return undefined
 const active = chatStore.activeCodingSession
 if (active && active.sessionId === data.sessionId && active.status === 'draft') {
 // 同 codingPlanData：result 可能是 JSON string（snapshot 路径）也可能是 object
 // （chat_runner 历史路径），两种都吃。
 const raw: unknown = toolCalls.value.find(tc => isCodingPlanTool(tc.name))?.result
 if (!raw)
 return undefined
 let parsed: { branch_name?: string } | null = null
 if (typeof raw === 'string') {
 try {
 parsed = JSON.parse(raw)
 }
 catch {
 parsed = null
 }
 }
 else if (typeof raw === 'object') {
 parsed = raw as { branch_name?: string }
 }
 return parsed?.branch_name || undefined
 }
 return undefined
})
const primaryDeepAnalysisId = computed( => {
 const da = toolCalls.value.find(tc => isDeepAnalysisTool(tc.name))
 return da?.id || ''
})
const TOOL_LABELS_CN: Record<string, string> = {
 Read: '读取文件',
 Grep: '搜索代码',
 Glob: '查找文件',
 LS: '列出目录',
 Bash: '执行命令',
 Write: '写入文件',
 Edit: '编辑文件',
 MultiEdit: '批量编辑',
 WebFetch: '网页抓取',
 WebSearch: '网络搜索',
 TodoRead: '读取待办',
 TodoWrite: '写入待办',
}
function tryParseToolCall(content: string): { toolName: string, toolLabel: string, argsText: string, parsedArgs: Record<string, unknown> | null } | null {
 const matched = content.match(/^(\w+)\((.*)\)$/s)
 if (!matched)
 return null
 const toolName = matched[1]
 const argsText = matched[2]
 let parsedArgs: Record<string, unknown> | null = null
 try {
 parsedArgs = JSON.parse(argsText)
 }
 catch {
 parsedArgs = null
 }
 return {
 toolName,
 toolLabel: TOOL_LABELS_CN[toolName] || toolName,
 argsText,
 parsedArgs,
 }
}
/**
 * 把 deep_analysis 容器原始日志解析为一条 UI 友好的展示项。
 *
 * 设计要点：
 * - 单一行结构（icon + label + text），不再"标题 + 摘要 + detail"三层重复展示。
 * 原本 text 类型 title/summary/detail 全是 log.content，UI 上同一段话出现两遍。
 * - 后端 `[task:text] [思考] xxx` 走的是 text 类型，这里识别 `[思考]` 前缀提
 * 升为 thinking 类，沿用 timeline-step--thinking 的视觉语言。
 * - tool_call：直接把关键参数（文件路径 / 查询词 / 命令）打到行上，避免「读取
 * 文件」三个字独占一行毫无信息量；完整 args JSON 留到点开 detail 才显示。
 */
type DeepLogKind = 'thinking' | 'text' | 'tool' | 'result' | 'system' | 'progress' | 'error'
interface DeepLogView {
 kind: DeepLogKind
 icon: string
 label: string
 text: string
 detail: string
 expandable: boolean
}
function decorateDeepLog(log: { type: string, content: string }): DeepLogView | null {
 const raw = (log.content || '').trim
 // block / message 类型多为 SDK 内部噪音，过滤；保留有真实内容的极少数情况
 if (log.type === 'block' || log.type === 'message') {
 if (!raw || ['ThinkingBlock', 'UserMessage', 'AssistantMessage', 'SystemMessage', 'ResultMessage'].includes(raw))
 return null
 return { kind: 'system', icon: 'icon-[lucide--info]', label: '', text: raw, detail: '', expandable: false }
 }
 if (log.type === 'tool_call') {
 const parsed = tryParseToolCall(raw)
 if (!parsed)
 return { kind: 'tool', icon: 'icon-[lucide--terminal]', label: '工具调用', text: raw, detail: '', expandable: false }
 const { toolName, toolLabel, argsText, parsedArgs } = parsed
 let text = ''
 if (toolName === 'Read')
 text = (parsedArgs?.file_path as string) || (parsedArgs?.path as string) || argsText
 else if (toolName === 'Glob')
 text = (parsedArgs?.pattern as string) || (parsedArgs?.path as string) || argsText
 else if (toolName === 'Grep')
 text = (parsedArgs?.pattern as string) || argsText
 else if (toolName === 'Bash')
 text = (parsedArgs?.command as string) || argsText
 else
 text = argsText
 const detail = parsedArgs ? JSON.stringify(parsedArgs, null, 2): argsText
 return {
 kind: 'tool',
 icon: 'icon-[lucide--terminal]',
 label: toolLabel,
 text: text || '执行',
 detail: detail && detail !== text ? detail: '',
 expandable: !!(detail && detail !== text),
 }
 }
 if (log.type === 'text') {
 // [思考] 前缀来自 task/core/executor.py，归一为 thinking
 if (raw.startsWith('[思考]')) {
 const body = raw.slice('[思考]'.length).trim
 return {
 kind: 'thinking',
 icon: 'icon-[lucide--sparkles]',
 label: '思考',
 text: body,
 detail: '',
 expandable: false,
 }
 }
 return { kind: 'text', icon: 'icon-[lucide--file-text]', label: '', text: raw, detail: '', expandable: false }
 }
 if (log.type === 'result') {
 const costMatch = raw.match(/cost=\$([\d.]+)/)
 const text = costMatch ? `任务已完成 · 费用 $${costMatch[1]}`: (raw || '任务已完成')
 return { kind: 'result', icon: 'icon-[lucide--check-circle-2]', label: '', text, detail: '', expandable: false }
 }
 if (log.type === 'progress')
 return { kind: 'progress', icon: 'icon-[lucide--loader]', label: '', text: raw || '任务仍在执行中', detail: '', expandable: false }
 if (log.type === 'error')
 return { kind: 'error', icon: 'icon-[lucide--alert-circle]', label: '', text: raw || '任务执行失败', detail: '', expandable: false }
 if (log.type === 'system')
 return { kind: 'system', icon: 'icon-[lucide--cpu]', label: '', text: raw || '系统状态更新', detail: '', expandable: false }
 if (!raw)
 return null
 return { kind: 'text', icon: 'icon-[lucide--info]', label: '', text: raw, detail: '', expandable: false }
}
const expandedDeepLogs = ref<Set<number>>(new Set)
function toggleDeepLog(i: number) {
 if (expandedDeepLogs.value.has(i))
 expandedDeepLogs.value.delete(i)
 else
 expandedDeepLogs.value.add(i)
}
/**
 * 判定文本是否值得"点击展开看全文"。短单行直接全量展示，不需要展开按钮。
 * 阈值经验值 120 字符 / 2 行，与 timeline-step--thinking 的判定保持一致。
 */
function isLongText(text: string): boolean {
 return text.length > 120 || text.includes('\n')
}
function previewText(text: string): string {
 const firstLine = text.split('\n')[0] || ''
 return firstLine.length > 120 ? `${firstLine.slice(0, 120)}…`: firstLine
}
// waiting phase 空内容时隐藏空 bubble，让 ChatStatusBar 单独呈现
const hideEmptyBubble = computed( =>
 props.isStreaming
 && !renderedHtml.value
 && toolCalls.value.length === 0
 && !hasNarrations.value
 && chatStore.currentPhase === 'waiting',
)
</script>
<template>
 <!-- ======================== 用户消息 ======================== -->
 <div v-if="message.role === 'user'" class="user-message-row">
 <div class="user-bubble">
 {{ message.content }}
 </div>
 </div>
 <!-- ======================== AI 消息 ======================== -->
 <div v-else-if="!hideEmptyBubble" class="ai-message group">
 <!-- 多选模式 Checkbox (per, ) -->
 <div v-if="chatStore.isExportSelectMode && props.message.role === 'assistant'" class="mr-2 flex items-center shrink-0">
 <Checkbox:checked="isSelected" @update:checked="chatStore.toggleMessageSelect(props.message.id)" />
 </div>
 <div class="assistant-avatar">
 <img src="/logo-mark.svg" alt="" aria-hidden="true" class="assistant-avatar-logo">
 </div>
 <div class="assistant-message-shell">
 <div class="assistant-message-header">
 <div class="assistant-title">
 <span>Friday AI</span>
 <span v-if="metadata?.model" class="assistant-model">{{ metadata.model }}</span>
 </div>
 <span class="assistant-time">{{ formatTime(message.created_at) }}</span>
 </div>
 <!-- 飞书文档摘要卡片 -- 在 AI 回答之前展示 -->
 <DocSummaryCard
 v-if="docSummary && message.role === 'assistant'":type="docSummary.type":title="docSummary.title":word-count="docSummary.wordCount":preview="docSummary.preview":truncated="docSummary.truncated":truncated-length="docSummary.truncatedLength":error-type="docSummary.errorType":error-message="docSummary.errorMessage"
 />
 <!--
 Thinking 折叠块（兼容路径）：
 - 仅当 timeline 为空但有 thinking 文本时显示（老消息 / 老后端不带
 thinking 时间线节点的情况）。
 - 有 timeline 时，thinking 会作为 timeline-step 节点直接交错渲染
 在工具批次之间，不走此块。
 -->
 <div v-if="!hasTimeline && hasThinking" class="thinking-block">
 <button class="thinking-header" @click="showThinking = !showThinking">
 <span class="thinking-icon":class="isStreaming ? 'animate-pulse': ''">
 <span class="icon-[lucide--sparkles] text-[10px]" />
 </span>
 <span v-if="isStreaming">思考中...</span>
 <span v-else-if="thinkingDuration > 0">思考过程 · {{ thinkingDuration }}s</span>
 <span v-else>思考过程</span>
 <span
 class="icon-[lucide--chevron-right] ml-auto text-[10px] text-muted-foreground transition-transform duration-150":class="showThinking ? 'rotate-90': ''"
 />
 </button>
 <div v-if="showThinking" class="thinking-content">
 {{ thinkingText }}
 </div>
 </div>
 <!-- 叙述文本折叠块（工具调用间的操作描述） -->
 <div v-if="!hasTimeline && (hasNarrations || pendingNarration)" class="narration-block">
 <button class="narration-toggle" @click="showNarrations = !showNarrations">
 <span class="icon-[lucide--bot] text-[10px]" />
 <span>{{ isStreaming ? '分析中...': '分析过程' }}</span>
 <span class="narration-count">{{ narrations.length }}{{ pendingNarration ? '+1': '' }} 步</span>
 <span
 class="icon-[lucide--chevron-right] text-[9px] transition-transform duration-150":class="showNarrations ? 'rotate-90': ''"
 />
 </button>
 <div v-if="showNarrations" class="narration-content">
 <p v-for="(n, i) in narrations":key="i">
 {{ n.trim }}
 </p>
 <p v-if="pendingNarration" class="opacity-60">
 {{ pendingNarration.trim }}
 </p>
 </div>
 </div>
 <!-- 工具调用 — 行内 pill 流（同 batch 横排 chip，其余按连续同名折叠） -->
 <div v-if="hasTimeline" class="timeline-flow">
 <template v-for="item in groupedTimelineItems":key="item.id">
 <!-- thinking step：默认显示首行预览，多行/超长时点开看全文 -->
 <div
 v-if="item.kind === 'thinking'"
 class="timeline-step timeline-step--thinking":class="{ 'is-expandable': thinkingIsMultiline(item.text), 'is-expanded': expandedThinking.has(item.id) }"
 @click="thinkingIsMultiline(item.text) && toggleThinking(item.id)"
 >
 <div class="timeline-step-label">
 <span class="icon-[lucide--sparkles] text-[10px]" />
 思考
 <span
 v-if="thinkingIsMultiline(item.text)"
 class="icon-[lucide--chevron-right] ml-auto text-[10px] text-muted-foreground/50 transition-transform duration-150":class="expandedThinking.has(item.id) ? 'rotate-90': ''"
 />
 </div>
 <div v-if="expandedThinking.has(item.id) || !thinkingIsMultiline(item.text)" class="timeline-step-text">
 {{ item.text.trim }}
 </div>
 <div v-else class="timeline-step-text timeline-step-text--preview">
 {{ thinkingPreview(item.text) }}
 </div>
 </div>
 <!-- narration step -->
 <div v-else-if="item.kind === 'narration'" class="timeline-step timeline-step--narration">
 <div class="timeline-step-label">
 <span class="icon-[lucide--bot] text-[10px]" />
 分析
 </div>
 <div class="timeline-step-text">
 {{ item.text.trim }}
 </div>
 </div>
 <!-- tool group：batch 来源 → 横向 chip 流；连续同名 → 纵向折叠 -->
 <div v-else-if="item.kind === 'tool-group'" class="tool-group">
 <!-- batch 模式：扁平横向 chip 排列（不需要二次点击展开列表） -->
 <div v-if="shouldUseChipLayout(item)" class="tool-batch">
 <div class="tool-batch-header">
 <span v-if="groupStatus(item.items) === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-name">{{ groupLabel(item) }}</span>
 <span class="tool-pill-count">{{ item.items.length }}</span>
 </div>
 <div class="tool-batch-chips">
 <button
 v-for="child in item.items":key="child.id"
 class="tool-chip":class="{ 'tool-chip--running': child.status === 'running', 'tool-chip--expanded': expandedTools.has(child.id) }":title="toolAction(child.name, child.input || {}, child.result)"
 @click="toggleTool(child.id)"
 >
 <span v-if="child.status === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-chip-text">{{ chipSummary(child) }}</span>
 </button>
 </div>
 <!-- chip 展开后的详情列表（点谁展开谁） -->
 <div v-if="item.items.some((c: ToolItemShape) => expandedTools.has(c.id))" class="tool-batch-details">
 <template v-for="child in item.items":key="`detail-${child.id}`">
 <div v-if="expandedTools.has(child.id)" class="tool-detail tool-detail--batch">
 <div class="tool-detail-head">
 <span class="tool-pill-name">{{ toolLabel(child.name) }}</span>
 <span class="tool-pill-desc">{{ toolAction(child.name, child.input || {}, child.result) }}</span>
 </div>
 <div class="tool-detail-section">
 <span class="tool-detail-label">输入</span>
 <pre class="tool-detail-json">{{ JSON.stringify(child.input, null, 2) }}</pre>
 </div>
 <div v-if="child.result" class="tool-detail-section">
 <span class="tool-detail-label">输出</span>
 <pre class="tool-detail-json">{{ typeof child.result === 'string' && child.result.length > 600 ? `${child.result.slice(0, 600)}…`: child.result }}</pre>
 </div>
 </div>
 </template>
 </div>
 </div>
 <!-- 兼容模式：连续同名 → 旧的"折叠成组"样式，保持历史会话契约 -->
 <template v-else>
 <button class="tool-pill tool-pill--group" @click="toggleGroup(item.id)">
 <span v-if="groupStatus(item.items) === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-name">{{ groupLabel(item) }}</span>
 <span class="tool-pill-count">{{ item.items.length }}</span>
 <span class="tool-pill-desc">最近：{{ lastItemDescription(item.items) }}</span>
 <span
 class="icon-[lucide--chevron-right] text-[10px] text-muted-foreground/50 transition-transform duration-200 ease-out":class="expandedGroups.has(item.id) ? 'rotate-90': ''"
 />
 </button>
 <Transition name="expand">
 <div v-if="expandedGroups.has(item.id)" class="tool-group-list">
 <div v-for="child in item.items":key="child.id" class="tool-inline tool-inline--child">
 <div class="tool-pill tool-pill--child" @click="toggleTool(child.id)">
 <span v-if="child.status === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-desc tool-pill-desc--child">{{ toolAction(child.name, child.input || {}, child.result) }}</span>
 <span
 v-if="child.input && Object.keys(child.input).length > 0"
 class="icon-[lucide--chevron-right] text-[9px] text-muted-foreground/40 transition-transform duration-150":class="expandedTools.has(child.id) ? 'rotate-90': ''"
 />
 </div>
 <div v-if="expandedTools.has(child.id)" class="tool-detail">
 <div class="tool-detail-section">
 <span class="tool-detail-label">输入</span>
 <pre class="tool-detail-json">{{ JSON.stringify(child.input, null, 2) }}</pre>
 </div>
 <div v-if="child.result" class="tool-detail-section">
 <span class="tool-detail-label">输出</span>
 <pre class="tool-detail-json">{{ typeof child.result === 'string' && child.result.length > 600 ? `${child.result.slice(0, 600)}…`: child.result }}</pre>
 </div>
 </div>
 </div>
 </div>
 </Transition>
 </template>
 </div>
 <!-- 单例 tool（含特殊工具：deep_analysis / coding_plan） -->
 <div v-else-if="item.kind === 'tool'" class="tool-inline">
 <div class="tool-pill" @click="toggleTool(item.id)">
 <span v-if="item.status === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-name">{{ toolLabel(item.name) }}</span>
 <span class="tool-pill-desc">{{ toolAction(item.name, item.input || {}, item.result) }}</span>
 <span
 v-if="item.input && Object.keys(item.input).length > 0"
 class="icon-[lucide--chevron-right] text-[9px] text-muted-foreground/40 transition-transform duration-150":class="expandedTools.has(item.id) ? 'rotate-90': ''"
 />
 </div>
 <TechPlanCard
 v-if="isCodingPlanTool(item.name) && item.status === 'done' && codingPlanData":plan-id="codingPlanData.planId":session-id="codingPlanData.sessionId":tech-plan="codingPlanData.techPlan":affected-files="codingPlanData.affectedFiles":status="codingPlanStatus":is-confirming="codingPlanConfirming":branch-name="codingPlanBranchName"
 @confirm="(_planId, sessionId, branchName) => sessionId && chatStore.handleConfirmCodingSession(sessionId, branchName)"
 />
 <div
 v-if="isDeepAnalysisTool(item.name) && hasDeepAnalysisLogs && item.id === primaryDeepAnalysisId"
 class="deep-analysis-panel"
 >
 <button class="deep-analysis-toggle" @click="deepAnalysisExpanded = !deepAnalysisExpanded">
 <span class="icon-[lucide--activity] text-[10px] text-primary" />
 <span>{{ item.status === 'running' ? '执行日志': '执行记录' }}</span>
 <span class="deep-analysis-count">{{ resolvedDeepAnalysisLogs.length }} 条</span>
 <span
 class="icon-[lucide--chevron-right] text-[9px] transition-transform duration-150":class="deepAnalysisExpanded ? 'rotate-90': ''"
 />
 </button>
 <div v-if="deepAnalysisExpanded" class="deep-analysis-logs">
 <template v-for="(log, i) in resolvedDeepAnalysisLogs":key="i">
 <component:is="decorateDeepLog(log)?.expandable || isLongText(decorateDeepLog(log)?.text || '') ? 'button': 'div'"
 v-if="decorateDeepLog(log)"
 class="deep-log-row":class="[
 `deep-log-row--${decorateDeepLog(log)!.kind}`,
 { 'is-expandable': decorateDeepLog(log)!.expandable || isLongText(decorateDeepLog(log)!.text), 'is-expanded': expandedDeepLogs.has(i) },
 ]":type="decorateDeepLog(log)?.expandable || isLongText(decorateDeepLog(log)?.text || '') ? 'button': undefined"
 @click="(decorateDeepLog(log)!.expandable || isLongText(decorateDeepLog(log)!.text)) && toggleDeepLog(i)"
 >
 <span:class="decorateDeepLog(log)!.icon" class="deep-log-icon" />
 <div class="deep-log-main">
 <div class="deep-log-head">
 <span v-if="decorateDeepLog(log)!.label" class="deep-log-label">{{ decorateDeepLog(log)!.label }}</span>
 <span
 class="deep-log-text":class="{ 'deep-log-text--clamp': isLongText(decorateDeepLog(log)!.text) && !expandedDeepLogs.has(i) }"
 >
 {{ isLongText(decorateDeepLog(log)!.text) && !expandedDeepLogs.has(i) ? previewText(decorateDeepLog(log)!.text): decorateDeepLog(log)!.text }}
 </span>
 <span
 v-if="decorateDeepLog(log)!.expandable || isLongText(decorateDeepLog(log)!.text)"
 class="icon-[lucide--chevron-right] deep-log-chevron":class="expandedDeepLogs.has(i) ? 'rotate-90': ''"
 />
 </div>
 <pre
 v-if="decorateDeepLog(log)!.expandable && expandedDeepLogs.has(i)"
 class="deep-log-detail"
 >{{ decorateDeepLog(log)!.detail }}</pre>
 </div>
 </component>
 </template>
 </div>
 </div>
 <div v-if="expandedTools.has(item.id) && !isCodingPlanTool(item.name)" class="tool-detail">
 <div class="tool-detail-section">
 <span class="tool-detail-label">输入</span>
 <pre class="tool-detail-json">{{ JSON.stringify(item.input, null, 2) }}</pre>
 </div>
 <div v-if="item.result" class="tool-detail-section">
 <span class="tool-detail-label">输出</span>
 <pre class="tool-detail-json">{{ typeof item.result === 'string' && item.result.length > 600 ? `${item.result.slice(0, 600)}…`: item.result }}</pre>
 </div>
 </div>
 </div>
 </template>
 </div>
 <!-- 非 timeline 路径：同样按分组渲染 -->
 <div v-else-if="toolCalls.length > 0" class="tool-flow">
 <template v-for="item in groupedToolCalls":key="item.id">
 <div v-if="item.kind === 'tool-group'" class="tool-group">
 <button class="tool-pill tool-pill--group" @click="toggleGroup(item.id)">
 <span v-if="groupStatus(item.items) === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-name">{{ toolLabel(item.toolName) }}</span>
 <span class="tool-pill-count">{{ item.items.length }}</span>
 <span class="tool-pill-desc">最近：{{ lastItemDescription(item.items) }}</span>
 <span
 class="icon-[lucide--chevron-right] text-[10px] text-muted-foreground/50 transition-transform duration-200 ease-out":class="expandedGroups.has(item.id) ? 'rotate-90': ''"
 />
 </button>
 <Transition name="expand">
 <div v-if="expandedGroups.has(item.id)" class="tool-group-list">
 <div v-for="child in item.items":key="child.id" class="tool-inline tool-inline--child">
 <div class="tool-pill tool-pill--child" @click="toggleTool(child.id)">
 <span v-if="child.status === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-desc tool-pill-desc--child">{{ toolAction(child.name, child.input || {}, child.result) }}</span>
 <span
 v-if="child.input && Object.keys(child.input).length > 0"
 class="icon-[lucide--chevron-right] text-[9px] text-muted-foreground/40 transition-transform duration-150":class="expandedTools.has(child.id) ? 'rotate-90': ''"
 />
 </div>
 <div v-if="expandedTools.has(child.id)" class="tool-detail">
 <div class="tool-detail-section">
 <span class="tool-detail-label">输入</span>
 <pre class="tool-detail-json">{{ JSON.stringify(child.input, null, 2) }}</pre>
 </div>
 <div v-if="child.result" class="tool-detail-section">
 <span class="tool-detail-label">输出</span>
 <pre class="tool-detail-json">{{ typeof child.result === 'string' && child.result.length > 600 ? `${child.result.slice(0, 600)}…`: child.result }}</pre>
 </div>
 </div>
 </div>
 </div>
 </Transition>
 </div>
 <div v-else-if="item.kind === 'tool'" class="tool-inline">
 <div class="tool-pill" @click="toggleTool(item.id)">
 <span v-if="item.status === 'running'" class="tool-dot tool-dot--running" />
 <span v-else class="tool-dot tool-dot--done" />
 <span class="tool-pill-name">{{ toolLabel(item.name) }}</span>
 <span class="tool-pill-desc">{{ toolAction(item.name, item.input || {}, item.result) }}</span>
 <span
 v-if="item.input && Object.keys(item.input).length > 0"
 class="icon-[lucide--chevron-right] text-[9px] text-muted-foreground/40 transition-transform duration-150":class="expandedTools.has(item.id) ? 'rotate-90': ''"
 />
 </div>
 <TechPlanCard
 v-if="isCodingPlanTool(item.name) && item.status === 'done' && codingPlanData":plan-id="codingPlanData.planId":session-id="codingPlanData.sessionId":tech-plan="codingPlanData.techPlan":affected-files="codingPlanData.affectedFiles":status="codingPlanStatus":is-confirming="codingPlanConfirming":branch-name="codingPlanBranchName"
 @confirm="(_planId, sessionId, branchName) => sessionId && chatStore.handleConfirmCodingSession(sessionId, branchName)"
 />
 <div
 v-if="isDeepAnalysisTool(item.name) && hasDeepAnalysisLogs && item.id === primaryDeepAnalysisId"
 class="deep-analysis-panel"
 >
 <button class="deep-analysis-toggle" @click="deepAnalysisExpanded = !deepAnalysisExpanded">
 <span class="icon-[lucide--activity] text-[10px] text-primary" />
 <span>{{ item.status === 'running' ? '执行日志': '执行记录' }}</span>
 <span class="deep-analysis-count">{{ resolvedDeepAnalysisLogs.length }} 条</span>
 <span
 class="icon-[lucide--chevron-right] text-[9px] transition-transform duration-150":class="deepAnalysisExpanded ? 'rotate-90': ''"
 />
 </button>
 <div v-if="deepAnalysisExpanded" class="deep-analysis-logs">
 <template v-for="(log, i) in resolvedDeepAnalysisLogs":key="i">
 <component:is="decorateDeepLog(log)?.expandable || isLongText(decorateDeepLog(log)?.text || '') ? 'button': 'div'"
 v-if="decorateDeepLog(log)"
 class="deep-log-row":class="[
 `deep-log-row--${decorateDeepLog(log)!.kind}`,
 { 'is-expandable': decorateDeepLog(log)!.expandable || isLongText(decorateDeepLog(log)!.text), 'is-expanded': expandedDeepLogs.has(i) },
 ]":type="decorateDeepLog(log)?.expandable || isLongText(decorateDeepLog(log)?.text || '') ? 'button': undefined"
 @click="(decorateDeepLog(log)!.expandable || isLongText(decorateDeepLog(log)!.text)) && toggleDeepLog(i)"
 >
 <span:class="decorateDeepLog(log)!.icon" class="deep-log-icon" />
 <div class="deep-log-main">
 <div class="deep-log-head">
 <span v-if="decorateDeepLog(log)!.label" class="deep-log-label">{{ decorateDeepLog(log)!.label }}</span>
 <span
 class="deep-log-text":class="{ 'deep-log-text--clamp': isLongText(decorateDeepLog(log)!.text) && !expandedDeepLogs.has(i) }"
 >
 {{ isLongText(decorateDeepLog(log)!.text) && !expandedDeepLogs.has(i) ? previewText(decorateDeepLog(log)!.text): decorateDeepLog(log)!.text }}
 </span>
 <span
 v-if="decorateDeepLog(log)!.expandable || isLongText(decorateDeepLog(log)!.text)"
 class="icon-[lucide--chevron-right] deep-log-chevron":class="expandedDeepLogs.has(i) ? 'rotate-90': ''"
 />
 </div>
 <pre
 v-if="decorateDeepLog(log)!.expandable && expandedDeepLogs.has(i)"
 class="deep-log-detail"
 >{{ decorateDeepLog(log)!.detail }}</pre>
 </div>
 </component>
 </template>
 </div>
 </div>
 <div v-if="expandedTools.has(item.id) && !isCodingPlanTool(item.name)" class="tool-detail">
 <div class="tool-detail-section">
 <span class="tool-detail-label">输入</span>
 <pre class="tool-detail-json">{{ JSON.stringify(item.input, null, 2) }}</pre>
 </div>
 <div v-if="item.result" class="tool-detail-section">
 <span class="tool-detail-label">输出</span>
 <pre class="tool-detail-json">{{ typeof item.result === 'string' && item.result.length > 600 ? `${item.result.slice(0, 600)}…`: item.result }}</pre>
 </div>
 </div>
 </div>
 </template>
 </div>
 <!-- 正文（工具调用全部完成后的最终回答） -->
 <div v-if="isStreaming && !renderedHtml && toolCalls.length === 0 && !hasNarrations && !hasTimeline" class="flex items-center py-2">
 <span class="typing-cursor" />
 </div>
 <div
 v-if="renderedHtml"
 class="ai-prose"
 v-html="renderedHtml"
 />
 <span v-if="isStreaming && renderedHtml" class="typing-cursor" />
 <!-- 流式中等待工具返回的光标 -->
 <div v-if="isStreaming && !renderedHtml && (toolCalls.length > 0 || hasNarrations || hasTimeline)" class="flex items-center py-1">
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
 <!-- 操作栏 -->
 <div class="action-bar">
 <button class="action-btn" @click="copyContent">
 <span v-if="copied" class="icon-[lucide--check] text-primary" />
 <span v-else class="icon-[lucide--copy]" />
 <span class="action-label">{{ copied ? '已复制': '复制' }}</span>
 </button>
 <button
 v-if="props.message.role === 'assistant'"
 class="action-btn action-btn--feishu"
 title="导出到飞书"
 @click="emit('exportSingle', props.message.id)"
 >
 <svg
 class="feishu-logo"
 viewBox="0 0 48 48"
 fill="none"
 xmlns="http://www.w3.org/2000/svg"
 aria-hidden="true"
 >
 <path d="M10 8c0 1 7 3.5 14.745 16.744 0 0 4.work-item.363 6.work-item.744 1.5-1 2.work-item.332 2.work-item.332C33.712 15.156 29.5 8 28 8z" fill="#00d6b9" />
 <path d="M43.5 18.5c-1-.work-item.65-1.work-item.5-1.5a15 15 0 0 0-3.288.668S32.5 18 31 19c-2.07 1.38-6.255 5.work-item.255 5.work-item.428 1.work-item.05 2.work-item.245 3.756 0 0 7 3 11.5 3 5.063 0 7-3.5 7-3.5 1.5-3.305 3.5-7 5.5-9.5" fill="#163c9a" />
 <path d="M4 17.5v17c0 1 6 5.5 15 5.5 10 0 17.05-7.705 19-12 0 0-1.937 3.5-7 3.5-4.5 0-11.5-3-11.5-3-5.work-item..03-6..work-item.117C4.974 17.953 4 17.093 4 17.5" fill="#3370ff" />
 </svg>
 <span class="action-label">导出到飞书</span>
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
 </div>
</template>
<style scoped>
/* ============ User Bubble ============ */
.user-message-row {
 display: flex;
 justify-content: flex-end;
 padding-left: 3.5rem;
}
.user-bubble {
 max-width: min(100%, 38rem);
 padding: 0.8125rem 1rem;
 border-radius: 1rem 1rem 0.375rem 1rem;
 border: 1px solid hsl(168 76% 42% / 0.18);
 background: hsl(0 0% 100% / 0.9);
 color: hsl(215 28% 18%);
 font-size: 0.925rem;
 font-weight: 600;
 line-height: 1.65;
 letter-spacing: -0.01em;
 white-space: pre-wrap;
 word-break: break-word;
 box-shadow: 0 1px 2px hsl(215 28% 17% / 0.05);
}
/* ============ AI Message ============ */
.ai-message {
 display: flex;
 align-items: flex-start;
 gap: 0.875rem;
}
.assistant-avatar {
 display: flex;
 align-items: center;
 justify-content: center;
 width: 2.375rem;
 height: 2.375rem;
 margin-top: 0.125rem;
 border-radius: 0.875rem;
 background: hsl(0 0% 100% / 0.84);
 border: 1px solid hsl(168 76% 42% / 0.18);
 box-shadow: 0 1px 2px hsl(215 28% 17% / 0.06);
 flex-shrink: 0;
}
.assistant-avatar-logo {
 width: 1.45rem;
 height: 1.45rem;
 object-fit: contain;
}
.assistant-message-shell {
 flex: 1;
 min-width: 0;
 max-width: 100%;
 padding: 0.95rem 1rem 0.7rem;
 border-radius: 1.125rem 1.125rem 1.125rem 0.4rem;
 border: 1px solid hsl(214 32% 86% / 0.9);
 background: hsl(0 0% 100% / 0.96);
 box-shadow: 0 1px 2px hsl(215 28% 17% / 0.05);
}
.assistant-message-header {
 display: flex;
 align-items: center;
 justify-content: space-between;
 gap: 1rem;
 margin-bottom: 0.75rem;
}
.assistant-title {
 display: flex;
 align-items: center;
 gap: 0.5rem;
 min-width: 0;
 color: hsl(215 28% 18%);
 font-size: 0.75rem;
 font-weight: 800;
 letter-spacing: 0.01em;
}
.assistant-model {
 overflow: hidden;
 max-width: 14rem;
 padding: 0.125rem 0.4375rem;
 border-radius: 9999px;
 background: hsl(215 16% 47% / 0.08);
 color: hsl(215 16% 45%);
 font-size: 0.625rem;
 font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', ui-monospace, monospace;
 font-weight: 600;
 text-overflow: ellipsis;
 white-space: nowrap;
}
.assistant-time {
 color: hsl(215 16% 60% / 0.82);
 font-size: 0.6875rem;
 font-weight: 600;
 font-variant-numeric: tabular-nums;
 flex-shrink: 0;
}
.timeline-flow + .ai-prose,
.tool-flow + .ai-prose {
 margin-top: 0.95rem;
 padding-top: 0.95rem;
 border-top: 1px solid hsl(214 32% 90% / 0.9);
}
/* ============ Timeline ============ */
.timeline-flow {
 display: flex;
 flex-direction: column;
 /* 同一时间线内部紧凑，让 tool group / 单 pill 自然成块 */
 gap: 0.375rem;
}
.timeline-step {
 border-radius: 0.625rem;
 border: 1px solid hsl(214 32% 91% / 0.5);
 background: hsl(210 40% 98% / 0.55);
 padding: 0.5rem 0.625rem;
}
.timeline-step--thinking {
 background: hsl(168 76% 96% / 0.55);
}
.timeline-step--thinking.is-expandable {
 cursor: pointer;
 transition: background-color 0.15s ease;
}
.timeline-step--thinking.is-expandable:hover {
 background: hsl(168 76% 94% / 0.7);
}
.timeline-step--narration {
 background: hsl(210 40% 98% / 0.7);
}
.timeline-step-label {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 font-size: 0.6875rem;
 font-weight: 600;
 color: hsl(215 16% 42% / 0.8);
 margin-bottom: 0.25rem;
}
.timeline-step-text {
 font-size: 0.75rem;
 line-height: 1.7;
 color: hsl(215 16% 35%);
 white-space: pre-wrap;
 word-break: break-word;
}
.timeline-step-text--preview {
 /* 收起态首行预览：单行省略 + 颜色弱化 */
 color: hsl(215 16% 50% / 0.85);
 white-space: nowrap;
 overflow: hidden;
 text-overflow: ellipsis;
}
/* ============ Tool Batch — 同 LLM turn 多工具横向 chip 流 ============ */
.tool-batch {
 display: flex;
 flex-direction: column;
 gap: 0.375rem;
 padding: 0.5rem 0.625rem;
 border-radius: 0.625rem;
 border: 1px solid hsl(214 32% 91% / 0.6);
 background: hsl(210 40% 98% / 0.5);
}
.tool-batch-header {
 display: inline-flex;
 align-items: center;
 gap: 0.5rem;
 font-size: 0.6875rem;
 color: hsl(215 16% 42%);
}
.tool-batch-chips {
 display: flex;
 flex-wrap: wrap;
 gap: 0.25rem 0.375rem;
}
.tool-chip {
 display: inline-flex;
 align-items: center;
 gap: 0.3125rem;
 padding: 0.1875rem 0.5rem;
 border-radius: 9999px;
 border: 1px solid hsl(214 32% 88% / 0.9);
 background: hsl(0 0% 100% / 0.9);
 font-size: 0.6875rem;
 color: hsl(215 16% 30%);
 cursor: pointer;
 max-width: 100%;
 transition:
 background-color 0.15s ease,
 border-color 0.15s ease;
 font-family: inherit;
}
.tool-chip:hover {
 border-color: hsl(168 76% 42% / 0.4);
 background: hsl(168 76% 96% / 0.5);
}
.tool-chip--running {
 border-color: hsl(168 76% 42% / 0.3);
 background: hsl(168 76% 97% / 0.7);
}
.tool-chip--expanded {
 border-color: hsl(168 76% 42% / 0.5);
 background: hsl(168 76% 95%);
}
.tool-chip-text {
 overflow: hidden;
 text-overflow: ellipsis;
 white-space: nowrap;
 max-width: 14rem;
 font-variant-numeric: tabular-nums;
}
.tool-batch-details {
 display: flex;
 flex-direction: column;
 gap: 0.5rem;
 margin-top: 0.25rem;
 padding-top: 0.5rem;
 border-top: 1px dashed hsl(214 32% 91%);
}
.tool-detail--batch {
 margin-left: 0;
 padding: 0;
 border-left: 0;
}
.tool-detail-head {
 display: flex;
 align-items: baseline;
 gap: 0.5rem;
 flex-wrap: wrap;
 padding: 0 0.125rem;
}
/* ============ Narration — 叙述折叠块 ============ */
.narration-block {
 border-radius: 0.5rem;
 border: 1px solid hsl(214 32% 91% / 0.5);
 background: hsl(210 40% 98% / 0.4);
 overflow: hidden;
}
.narration-toggle {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 width: 100%;
 padding: 0.375rem 0.625rem;
 font-size: 0.6875rem;
 color: hsl(215 16% 47% / 0.7);
 cursor: pointer;
 transition: background 0.1s;
}
.narration-toggle:hover {
 background: hsl(210 40% 96% / 0.6);
}
.narration-count {
 margin-left: auto;
 font-size: 0.625rem;
 color: hsl(215 16% 47% / 0.4);
}
.narration-content {
 padding: 0.375rem 0.625rem;
 border-top: 1px solid hsl(214 32% 91% / 0.4);
 font-size: 0.6875rem;
 line-height: 1.6;
 color: hsl(215 16% 47% / 0.6);
 max-height: 12rem;
 overflow-y: auto;
}
.narration-content p {
 margin: 0.25rem 0;
}
/* ============ Tool Flow — 行内 pill ============ */
.tool-flow {
 display: flex;
 flex-direction: column;
 gap: 0.375rem;
}
.tool-inline {
 display: flex;
 flex-direction: column;
}
.tool-pill {
 display: inline-flex;
 align-items: center;
 gap: 0.5rem;
 padding: 0.3125rem 0.75rem;
 border-radius: 0.5rem;
 font-size: 0.75rem;
 cursor: pointer;
 transition:
 background-color 0.15s ease,
 border-color 0.15s ease;
 width: fit-content;
 max-width: 100%;
 /* button reset：用作 <button> 时 */
 border: 0;
 background: transparent;
 text-align: left;
 font-family: inherit;
}
.tool-pill:hover {
 background: hsl(210 40% 96%);
}
.tool-pill:focus-visible {
 outline: 2px solid hsl(168 76% 42% / 0.4);
 outline-offset: 1px;
}
/* ============ Tool Group — Cursor 风格的"批量折叠" ============ */
.tool-group {
 display: flex;
 flex-direction: column;
}
.tool-pill--group {
 /* 组的头部稍微强调，建立"这是一组操作的入口" */
 background: hsl(210 40% 97% / 0.6);
 border: 1px solid hsl(214 32% 91% / 0.6);
 padding-right: 0.625rem;
}
.tool-pill--group:hover {
 background: hsl(210 40% 95%);
 border-color: hsl(214 32% 85%);
}
.tool-pill-count {
 display: inline-flex;
 align-items: center;
 justify-content: center;
 min-width: 1.125rem;
 height: 1rem;
 padding: 0 0.3125rem;
 border-radius: 9999px;
 background: hsl(215 16% 47% / 0.12);
 color: hsl(215 28% 30%);
 font-size: 0.625rem;
 font-weight: 600;
 font-variant-numeric: tabular-nums;
 flex-shrink: 0;
}
.tool-group-list {
 margin-top: 0.25rem;
 margin-left: 0.875rem;
 padding-left: 0.625rem;
 border-left: 1px dashed hsl(214 32% 91%);
 display: flex;
 flex-direction: column;
 gap: 0.125rem;
 overflow: hidden;
}
.tool-inline--child {
 /* 组内子项视觉降级 */
 font-size: 0.6875rem;
}
.tool-pill--child {
 padding: 0.1875rem 0.5rem;
 border-radius: 0.375rem;
 width: 100%;
}
.tool-pill--child:hover {
 background: hsl(210 40% 96% / 0.7);
}
.tool-pill-desc--child {
 /* §6 contrast-readability: 提高描述可读性 */
 color: hsl(215 16% 40%);
 font-size: 0.6875rem;
 flex: 1;
}
/* expand 过渡 */
.expand-enter-active,
.expand-leave-active {
 transition:
 max-height 0.22s ease-out,
 opacity 0.18s ease-out;
 overflow: hidden;
}
.expand-enter-from,
.expand-leave-to {
 max-height: 0;
 opacity: 0;
}
.expand-enter-to,
.expand-leave-from {
 max-height: 36rem;
 opacity: 1;
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
 /* §6 color-accessible-pairs：提高对比度 0.7 → 0.85 */
 color: hsl(215 16% 42%);
 font-size: 0.6875rem;
 overflow: hidden;
 text-overflow: ellipsis;
 white-space: nowrap;
 min-width: 0;
}
/* Deep Analysis Panel */
.deep-analysis-panel {
 margin-left: 1.25rem;
 margin-top: 0.125rem;
 border-radius: 0.375rem;
 border: 1px solid hsl(214 32% 91% / 0.5);
 background: hsl(210 40% 98% / 0.3);
 overflow: hidden;
}
.dark .deep-analysis-panel {
 border-color: hsl(214 32% 20% / 0.5);
 background: hsl(220 20% 12% / 0.3);
}
.deep-analysis-toggle {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 padding: 0.25rem 0.5rem;
 font-size: 0.6875rem;
 color: hsl(215 20% 50%);
 cursor: pointer;
 width: 100%;
 text-align: left;
}
.deep-analysis-toggle:hover {
 background: hsl(210 40% 95% / 0.5);
}
.deep-analysis-count {
 margin-left: auto;
 font-size: 0.625rem;
 opacity: 0.6;
 font-variant-numeric: tabular-nums;
}
.deep-analysis-logs {
 overflow: visible;
 padding: 0.25rem 0.375rem 0.375rem;
 display: flex;
 flex-direction: column;
 /* 紧凑行间距，避免每条都自带卡片阴影导致页面笨重 */
 gap: 1px;
}
/* ---- 单行日志（替代旧的 deep-analysis-log-card 卡片堆叠） ----
 * 设计目标（per 用户反馈）：
 * 1. 去掉"标题 + 摘要 + detail" 三层堆叠，避免同一段内容被显示两次
 * 2. 思考独立样式（与 timeline-step--thinking 配色一致），不再混入"分析输出"
 * 3. 工具调用直接把关键参数（文件路径/查询词）打到行上，鼠标进入提示"点击看完整参数"
 */
.deep-log-row {
 display: flex;
 align-items: flex-start;
 gap: 0.5rem;
 width: 100%;
 padding: 0.3125rem 0.5rem;
 border-radius: 0.375rem;
 border: 0;
 background: transparent;
 text-align: left;
 font-family: inherit;
 color: hsl(215 16% 35%);
 transition: background-color 0.12s ease;
}
.deep-log-row.is-expandable {
 cursor: pointer;
}
.deep-log-row.is-expandable:hover {
 background: hsl(210 40% 96% / 0.7);
}
.deep-log-row.is-expanded {
 background: hsl(210 40% 96% / 0.5);
}
.deep-log-icon {
 display: inline-flex;
 align-items: center;
 justify-content: center;
 width: 0.875rem;
 height: 1.05rem;
 font-size: 11px;
 color: hsl(215 16% 50% / 0.7);
 flex-shrink: 0;
}
.deep-log-main {
 flex: 1;
 min-width: 0;
 display: flex;
 flex-direction: column;
 gap: 0.25rem;
}
.deep-log-head {
 display: flex;
 align-items: center;
 gap: 0.375rem;
 min-width: 0;
}
.deep-log-label {
 font-size: 0.6875rem;
 font-weight: 600;
 color: hsl(215 28% 30%);
 flex-shrink: 0;
}
.deep-log-text {
 font-size: 0.75rem;
 line-height: 1.55;
 color: hsl(215 16% 38%);
 white-space: pre-wrap;
 word-break: break-word;
 min-width: 0;
 flex: 1;
}
.deep-log-text--clamp {
 white-space: nowrap;
 overflow: hidden;
 text-overflow: ellipsis;
}
.deep-log-chevron {
 font-size: 10px;
 color: hsl(215 16% 60% / 0.7);
 flex-shrink: 0;
 transition: transform 0.15s ease;
}
.deep-log-detail {
 margin: 0;
 padding: 0.4375rem 0.625rem;
 border-radius: 0.375rem;
 background: hsl(210 40% 96% / 0.7);
 font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
 font-size: 0.625rem;
 line-height: 1.55;
 color: hsl(215 20% 35%);
 white-space: pre-wrap;
 word-break: break-all;
 max-height: 14rem;
 overflow-y: auto;
}
/* ---- 按 kind 微调配色 ---- */
.deep-log-row--thinking .deep-log-icon {
 color: hsl(168 76% 42%);
}
.deep-log-row--thinking .deep-log-label {
 color: hsl(168 70% 32%);
}
.deep-log-row--thinking .deep-log-text {
 color: hsl(215 16% 35%);
 font-style: italic;
}
.deep-log-row--tool .deep-log-icon {
 color: hsl(217 91% 60%);
}
.deep-log-row--tool .deep-log-label {
 color: hsl(217 70% 40%);
}
.deep-log-row--tool .deep-log-text {
 font-family: 'SF Mono', 'Fira Code', ui-monospace, monospace;
 font-size: 0.6875rem;
 color: hsl(215 28% 28%);
}
.deep-log-row--result .deep-log-icon {
 color: hsl(142 71% 45%);
}
.deep-log-row--result .deep-log-text {
 color: hsl(142 50% 30%);
 font-weight: 500;
}
.deep-log-row--error .deep-log-icon {
 color: hsl(0 72% 51%);
}
.deep-log-row--error .deep-log-text {
 color: hsl(0 60% 40%);
}
.deep-log-row--progress .deep-log-icon {
 color: hsl(38 92% 50%);
 animation: pulse-dot 1.6s infinite;
}
.deep-log-row--system .deep-log-text,
.deep-log-row--text .deep-log-text {
 color: hsl(215 16% 42%);
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
 width: 100%;
 background: transparent;
 border-left: 0;
 border-right: 0;
 border-top: 0;
 text-align: left;
 cursor: pointer;
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
.ai-prose:deep(h1:first-child) {
 margin-top: 0;
}
.ai-prose:deep(h2) {
 font-size: 1.175rem;
 font-weight: 650;
 letter-spacing: -0.005em;
 margin: 1.5rem 0 0.5rem;
 color: hsl(215 28% 12%);
}
.ai-prose:deep(h2:first-child) {
 margin-top: 0;
}
.ai-prose:deep(h3) {
 font-size: 1rem;
 font-weight: 600;
 margin: 1.25rem 0 0.375rem;
 color: hsl(215 28% 15%);
}
.ai-prose:deep(h3:first-child) {
 margin-top: 0;
}
.ai-prose:deep(p) {
 margin: 0.625rem 0;
}
.ai-prose:deep(p:first-child) {
 margin-top: 0;
}
.ai-prose:deep(p:last-child) {
 margin-bottom: 0;
}
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
.ai-prose:deep(a:hover) {
 border-bottom-color: hsl(168 76% 42%);
}
.ai-prose:deep(ul) {
 list-style: disc;
 padding-left: 1.375rem;
 margin: 0.5rem 0;
}
.ai-prose:deep(ol) {
 list-style: decimal;
 padding-left: 1.375rem;
 margin: 0.5rem 0;
}
.ai-prose:deep(li) {
 margin: 0.25rem 0;
 padding-left: 0.25rem;
}
.ai-prose:deep(li > p) {
 margin: 0.125rem 0;
}
.ai-prose:deep(li:marker) {
 color: hsl(215 16% 60%);
}
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
.ai-prose:deep(blockquote p) {
 margin: 0.25rem 0;
}
.ai-prose:deep(hr) {
 border: none;
 border-top: 1px solid hsl(214 32% 91%);
 margin: 1.5rem 0;
}
.ai-prose:deep(table) {
 display: block;
 width: max-content;
 min-width: 100%;
 max-width: 100%;
 overflow-x: auto;
 border-collapse: collapse;
 font-size: 0.8125rem;
 margin: 0.875rem 0;
 border: 1px solid hsl(214 32% 91% / 0.8);
 border-radius: 0.875rem;
 scrollbar-width: thin;
}
.ai-prose:deep(th) {
 text-align: left;
 font-weight: 600;
 padding: 0.625rem 0.875rem;
 border-bottom: 2px solid hsl(214 32% 91%);
 white-space: nowrap;
}
.ai-prose:deep(td) {
 padding: 0.625rem 0.875rem;
 border-bottom: 1px solid hsl(214 32% 91% / 0.6);
 vertical-align: top;
 white-space: nowrap;
}
.ai-prose:deep(td code),
.ai-prose:deep(th code) {
 white-space: nowrap;
}
.ai-prose:deep(tr:last-child td) {
 border-bottom: none;
}
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
@keyframes blink {
 50% {
 opacity: 0;
 }
}
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
 flex-wrap: wrap;
 gap: 0.5rem;
 padding-top: 0.75rem;
}
.action-btn {
 display: inline-flex;
 align-items: center;
 justify-content: center;
 gap: 0.375rem;
 min-height: 1.875rem;
 padding: 0.3125rem 0.625rem;
 border-radius: 9999px;
 border: 1px solid hsl(214 32% 88% / 0.9);
 background: hsl(0 0% 100% / 0.72);
 font-size: 0.75rem;
 font-weight: 600;
 color: hsl(215 16% 42%);
 cursor: pointer;
 transition:
 background-color 0.15s ease,
 border-color 0.15s ease,
 color 0.15s ease;
}
.action-btn:hover {
 border-color: hsl(214 32% 82%);
 background: hsl(210 40% 98%);
 color: hsl(215 28% 17%);
}
.action-btn--feishu {
 border-color: hsl(168 76% 42% / 0.22);
 color: hsl(168 70% 28%);
}
.action-btn--feishu:hover {
 border-color: hsl(168 76% 42% / 0.34);
 background: hsl(168 76% 42% / 0.06);
}
.action-label {
 line-height: 1rem;
 white-space: nowrap;
}
.feishu-logo {
 display: inline-block;
 width: 1rem;
 height: 1rem;
 flex-shrink: 0;
}
.action-divider {
 width: 1px;
 height: 1rem;
 background: hsl(214 32% 91%);
 margin: 0 0.125rem;
}
.action-meta {
 font-size: 0.6875rem;
 color: hsl(215 16% 60% / 0.7);
}
@keyframes pulse-dot {
 0%,
 100% {
 opacity: 1;
 }
 50% {
 opacity: 0.4;
 }
}
</style>
