import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
function readSource(path: string): string {
 return readFileSync(`${process.cwd}/src/${path}`, 'utf8')
}
describe('chat visual contract', => {
 it('uses dedicated conversation item styling in the chat sidebar', => {
 const source = readSource('components/layout/AppSidebar.vue')
 expect(source).toContain('chat-conversation-item')
 expect(source).toContain('chat-conversation-item--active')
 expect(source).not.toContain('chat-conversation-status')
 })
 it('wraps assistant responses in a distinct message bubble shell', => {
 const source = readSource('components/chat/ChatMessageBubble.vue')
 expect(source).toContain('assistant-message-shell')
 expect(source).toContain('assistant-avatar')
 expect(source).not.toContain('padding-right: 1rem')
 })
 it('keeps the chat reading column at 768px and export cards in that flow', => {
 const areaSource = readSource('components/chat/ChatMessageArea.vue')
 const exportSource = readSource('components/chat/ExportSuccessCard.vue')
 expect(areaSource).toContain('max-width: 48rem')
 expect(areaSource).toContain('width: min(48rem, calc(100% - 2rem))')
 expect(areaSource).not.toContain('chat-message-stack mx-auto px-6')
 expect(exportSource).toContain('export-success-card')
 })
 it('uses a clean question card without decorative bars', => {
 const source = readSource('components/chat/ChatMessageBubble.vue')
 expect(source).toContain('user-bubble')
 expect(source).not.toContain('.user-bubble:before')
 })
 it('uses the Friday logo as the assistant avatar', => {
 const source = readSource('components/chat/ChatMessageBubble.vue')
 expect(source).toContain('/logo-mark.svg')
 })
 it('keeps wide markdown tables scrollable inside the assistant message', => {
 const source = readSource('components/chat/ChatMessageBubble.vue')
 expect(source).toContain('overflow-x: auto')
 expect(source).toContain('width: max-content')
 })
 it('shows persistent labeled message actions with a colorful Feishu icon', => {
 const source = readSource('components/chat/ChatMessageBubble.vue')
 expect(source).toContain('复制')
 expect(source).toContain('导出到飞书')
 expect(source).toContain('feishu-logo')
 expect(source).not.toContain('.group:hover .action-bar')
 expect(source).not.toMatch(/\.action-bar\s*\{[^}]*opacity:\s*0/)
 })
 it('groups parallel tool calls by batch_id into a horizontal chip flow', => {
 /*
 * Phase chat-timeline-batch 契约：后端 chat_runner 为同一 LLM turn
 * 内的多个 tool_call 打同一个 batch_id；前端按 batch_id 横向展示为
 * chip 流（节省纵向空间），避免历史 bug —— 一次 LLM 决定调 N 个工具
 * 在 UI 上铺成 N 行 pill。下面三项分别确保：
 * 1. 数据通路：types/SSEEvent / TimelineToolItem 携带 batch_id
 * 2. 分组逻辑：packGroups 识别 batch_id 走 'batch' 来源
 * 3. 渲染层：DOM 模板存在 tool-batch / tool-batch-chips / tool-chip 节点
 */
 const types = readSource('types/chat.ts')
 expect(types).toContain('batch_id?: string')
 const store = readSource('stores/chat.ts')
 expect(store).toContain('batch_id: event.batch_id')
 const bubble = readSource('components/chat/ChatMessageBubble.vue')
 expect(bubble).toContain('source: curBatch ? \'batch\': \'consecutive-same\'')
 expect(bubble).toContain('shouldUseChipLayout')
 expect(bubble).toContain('tool-batch-chips')
 expect(bubble).toContain('tool-chip')
 })
 it('inlines thinking nodes into the timeline with collapsible preview', => {
 /*
 * 用户在 v25.0 反馈：希望 thinking 不再放在独立折叠块，而是与
 * tool 批次交错出现（thinking → tools → thinking → tools → 正文），
 * 默认显示首行预览节省屏幕，点开可查看全文。本测试锁住该契约。
 */
 const bubble = readSource('components/chat/ChatMessageBubble.vue')
 expect(bubble).toContain('timeline-step--thinking')
 expect(bubble).toContain('timeline-step-text--preview')
 expect(bubble).toContain('thinkingPreview')
 expect(bubble).toContain('thinkingIsMultiline')
 expect(bubble).toContain('expandedThinking')
 })
})
