/**
 * Quick Task：v25 legacy message → parts 数组 hydrate adapter。
 *
 * 纯函数 / 无外部依赖 / 仅前端运行时合成 —— 不写库（PLAN §D5）。
 *
 * 算法（确定性，三分支兜底）：
 * 规则 A：`msg.parts` 非空 → 直接返回（idempotent；v26.0+ 新消息）
 * 规则 B：`metadata.timeline` 非空 → 按 timeline 顺序合成（v25 末期 timeline-based 消息）
 * 规则 C：`metadata.narrations` 非空 → narrations 串 text part + tool_calls 串 tool_use part
 * （v25 era 典型 chat 答复）
 * 规则 D：兜底 —— 单 text part = `msg.content`
 *
 * 设计契约见 PLAN §D5；fixture 覆盖见 `__tests__/fixtures/v25-legacy-messages.json`。
 */
import type { ConversationMessage, MessagePart, StreamTimelineItem, TextPart, ThinkingPart, ToolCallData, ToolUsePart } from '~/types/chat'
function newPartId: string {
 if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function')
 return `p_${crypto.randomUUID.replace(/-/g, '').slice(0, 12)}`
 return `p_${Math.random.toString(36).slice(2, 14)}`
}
function makeTextPart(text: string, index: number, state: 'streaming' | 'done' = 'done'): TextPart {
 return { type: 'text', id: newPartId, index, text, state }
}
function makeThinkingPart(text: string, index: number, state: 'streaming' | 'done' = 'done'): ThinkingPart {
 return { type: 'thinking', id: newPartId, index, text, state }
}
function makeToolUsePart(
 data: {
 tool_call_id: string
 name: string
 input?: Record<string, unknown>
 result?: string | null
 status?: 'running' | 'done' | 'error'
 batch_id?: string | null
 },
 index: number,
): ToolUsePart {
 return {
 type: 'tool_use',
 id: newPartId,
 index,
 tool_call_id: data.tool_call_id,
 name: data.name,
 input: data.input || {},
 status: data.status || 'done',
 result: data.result ?? null,
 batch_id: data.batch_id ?? null,
 }
}
/**
 * v25 legacy message → parts 数组合成。
 *
 * @param msg ConversationMessage（可能没有 parts 字段或 parts: ）
 * @returns 顺序权威的 parts 数组；最差兜底也至少有 1 个 text part（避免空 bubble）。
 */
export function hydrateLegacyMessage(msg: ConversationMessage): MessagePart {
 // 规则 A：新消息直接返回（idempotent）—— index 缺失时按数组顺序补
 if (msg.parts && msg.parts.length > 0) {
 return msg.parts.map((p, i) => ({
 ...p,
 index: typeof p.index === 'number' ? p.index: i,
 })) as MessagePart
 }
 const meta = (msg.metadata || {}) as Record<string, unknown>
 const narrations = (meta.narrations as string) ||
 const timeline = (meta.timeline as StreamTimelineItem) ||
 const toolCalls = msg.tool_calls ||
 const finalContent = msg.content || ''
 const parts: MessagePart =
 let idx = 0
 const nextIndex = => idx++
 // 规则 B：有 timeline → 按 timeline 顺序合成
 if (timeline.length > 0) {
 const toolByCallId = new Map<string, ToolCallData>
 for (const tc of toolCalls) toolByCallId.set(tc.id, tc)
 for (const item of timeline) {
 if (item.kind === 'narration') {
 if (item.text && item.text.trim)
 parts.push(makeTextPart(item.text, nextIndex, 'done'))
 }
 else if (item.kind === 'thinking') {
 if (item.text && item.text.trim)
 parts.push(makeThinkingPart(item.text, nextIndex, 'done'))
 }
 else if (item.kind === 'tool') {
 // timeline 里的 tool item 已经携带完整 input / result / status，
 // 但 tool_calls 列表往往是更权威的 result 来源（落库时是从 tool_calls 抽的）；
 // 优先用 tool_calls 中匹配 id 的 result，fallback 到 timeline 自带。
 const fromList = toolByCallId.get(item.id)
 parts.push(makeToolUsePart({
 tool_call_id: item.id,
 name: fromList?.name || item.name,
 input: fromList?.input || item.input,
 result: fromList?.result ?? item.result ?? null,
 status: (fromList?.status as 'running' | 'done' | 'error' | undefined) || item.status || 'done',
 batch_id: item.batch_id ?? null,
 }, nextIndex))
 }
 }
 // timeline 收尾后 append 最终正文（content 中尚未出现在 timeline 的部分）
 if (finalContent && finalContent.trim)
 parts.push(makeTextPart(finalContent, nextIndex, 'done'))
 if (parts.length > 0)
 return parts
 }
 // 规则 C：无 timeline / 有 narrations → narrations 优先于 content
 // v25 era 典型：narration = 中间过渡文本，最终 content = 正式答复
 // 关键 case：F5 deep_analysis 长 markdown → 永远是顶层 text part，不再被
 // narration-block 折叠容器吃掉（PLAN §1 Goal 根治目标）
 if (narrations.length > 0 || toolCalls.length > 0) {
 for (const n of narrations) {
 if (n && n.trim)
 parts.push(makeTextPart(n, nextIndex, 'done'))
 }
 for (const tc of toolCalls) {
 parts.push(makeToolUsePart({
 tool_call_id: tc.id,
 name: tc.name,
 input: tc.input,
 result: tc.result ?? null,
 status: (tc.status as 'running' | 'done' | 'error' | undefined) || 'done',
 }, nextIndex))
 }
 if (finalContent && finalContent.trim)
 parts.push(makeTextPart(finalContent, nextIndex, 'done'))
 if (parts.length > 0)
 return parts
 }
 // 规则 D：兜底 —— 单 text part = content（即便 content 为空也写一个空 text part，
 // 避免上层渲染 v-for 取 length 时拿到空数组导致空 bubble）
 parts.push(makeTextPart(finalContent, nextIndex, 'done'))
 return parts
}
/**
 * Composable wrapper：返回纯函数（与项目其它 composable 命名一致）。
 */
export function useMessageParts {
 return { hydrateLegacyMessage }
}
