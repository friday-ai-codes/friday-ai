/**
 * 深度分析（subagent）容器原始日志 → UI 友好展示项的解码逻辑。
 *
 * 抽自 ChatMessageBubble.vue：容器 stdout 的 [task:*] 行经 Runner →
 * deep_analysis_registry → SubAgentSession.last_output.logs 落盘，前端拿到的是
 * `{ type, content }` 列表。这里把它解码为单行结构（icon + label + text +
 * 可选结构化 detail），并把工具名归一为中文。
 */
export type DeepLogKind = 'thinking' | 'text' | 'tool' | 'result' | 'system' | 'progress' | 'error'
export interface DeepLogView {
 kind: DeepLogKind
 icon: string
 label: string
 text: string
 /** 工具参数等可展开详情的 JSON 文本（结构化失败时的兜底文本） */
 detail: string
 /** 可结构化展示的详情值（对象 → StructuredJsonView；缺省回退 detail 文本） */
 detailValue?: unknown
 /** 工具调用对应的原始工具名（供结构化视图做工具上下文） */
 toolName?: string
 expandable: boolean
}
/** SubAgent 容器内置工具名 → 中文 */
export const TOOL_LABELS_CN: Record<string, string> = {
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
 Task: '子任务',
}
export function tryParseToolCall(content: string): {
 toolName: string
 toolLabel: string
 argsText: string
 parsedArgs: Record<string, unknown> | null
} | null {
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
 * 判定文本是否值得"点击展开看全文"。短单行直接全量展示，不需要展开按钮。
 * 阈值经验值 120 字符 / 2 行，与 timeline-step--thinking 的判定保持一致。
 */
export function isLongText(text: string): boolean {
 return text.length > 120 || text.includes('\n')
}
export function previewText(text: string): string {
 const firstLine = text.split('\n')[0] || ''
 return firstLine.length > 120 ? `${firstLine.slice(0, 120)}…`: firstLine
}
/**
 * 把一条 deep_analysis 容器日志解码为 UI 展示项；返回 null 表示该条应被过滤。
 */
export function decorateDeepLog(log: { type: string, content: string }): DeepLogView | null {
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
 const expandable = !!(detail && detail !== text)
 return {
 kind: 'tool',
 icon: 'icon-[lucide--terminal]',
 label: toolLabel,
 text: text || '执行',
 detail: expandable ? detail: '',
 detailValue: expandable ? (parsedArgs ?? argsText): undefined,
 toolName,
 expandable,
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
