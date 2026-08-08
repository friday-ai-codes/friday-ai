import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

function readSource(path: string): string {
  return readFileSync(`${process.cwd()}/src/${path}`, 'utf8')
}

describe('chat visual contract', () => {
  it('uses dedicated conversation item styling in the chat conversation list', () => {
    // 入口重构：会话列表从全局 AppSidebar 迁入 chat 页内部二级栏
    const source = readSource('components/chat/ChatConversationList.vue')

    expect(source).toContain('chat-conversation-item')
    expect(source).toContain('chat-conversation-item--active')
    expect(source).not.toContain('chat-conversation-status')
  })

  it('wraps assistant responses in a distinct message bubble shell', () => {
    const source = readSource('components/chat/ChatMessageBubble.vue')

    expect(source).toContain('assistant-message-shell')
    expect(source).toContain('assistant-avatar')
    expect(source).not.toContain('padding-right: 1rem')
  })

  it('keeps the chat reading column at 768px and export cards in that flow', () => {
    const areaSource = readSource('components/chat/ChatMessageArea.vue')
    const exportSource = readSource('components/chat/ExportSuccessCard.vue')

    expect(areaSource).toContain('max-width: 48rem')
    expect(areaSource).toContain('width: min(48rem, calc(100% - 2rem))')
    expect(areaSource).not.toContain('chat-message-stack mx-auto px-6')
    expect(exportSource).toContain('export-success-card')
  })

  it('uses a clean question card without decorative bars', () => {
    const source = readSource('components/chat/ChatMessageBubble.vue')

    expect(source).toContain('user-bubble')
    expect(source).not.toContain('.user-bubble::before')
  })

  it('uses the Friday logo as the assistant avatar', () => {
    const source = readSource('components/chat/ChatMessageBubble.vue')

    expect(source).toContain('/logo-mark.svg')
  })

  it('keeps wide markdown tables scrollable inside the assistant message', () => {
    const source = readSource('components/chat/ChatMessageBubble.vue')

    expect(source).toContain('overflow-x: auto')
    expect(source).toContain('width: max-content')
  })

  it('shows persistent labeled message actions with a colorful Feishu icon', () => {
    const source = readSource('components/chat/ChatMessageBubble.vue')

    expect(source).toContain('复制')
    expect(source).toContain('导出到飞书')
    expect(source).toContain('feishu-logo')
    expect(source).not.toContain('.group:hover .action-bar')
    expect(source).not.toMatch(/\.action-bar\s*\{[^}]*opacity:\s*0/)
  })

  it('collapses consecutive tool calls into a Cursor-style process group', () => {
    /*
     * 工具调用收拢重设计：连续的「思考 + 工具调用」收拢进一个默认收起的
     * 三层折叠面板（ToolProcessGroup），节省纵向空间。下面分别确保：
     *   1. 数据通路：types/SSEEvent 仍携带 batch_id（后端契约不变）
     *   2. 分组逻辑：ChatMessageBubble 产出 process-group 渲染节点
     *   3. 渲染层：使用 ToolProcessGroup 组件渲染折叠面板
     */
    const types = readSource('types/chat.ts')
    expect(types).toContain('batch_id?: string')

    const bubble = readSource('components/chat/ChatMessageBubble.vue')
    expect(bubble).toContain('kind: \'process-group\'')
    expect(bubble).toContain('ToolProcessGroup')

    const group = readSource('components/chat/ToolProcessGroup.vue')
    // 三层折叠：容器头 / 步骤行 / 单步详情
    expect(group).toContain('tpg-head')
    expect(group).toContain('tpg-row')
    expect(group).toContain('tpg-detail')
  })

  it('inlines thinking nodes into the timeline fully expanded by default', () => {
    /*
     * thinking 仍与 tool 批次交错出现（thinking → tools → thinking → tools → 正文），
     * 但默认呈现方式从「首行预览 + 点开看全文」改为「直接全文可见」——思考文本是
     * 「AI 正在干什么」的唯一实时反馈，截断在预览里等于没有。本测试锁住新契约。
     */
    const bubble = readSource('components/chat/ChatMessageBubble.vue')
    expect(bubble).toContain('timeline-step--thinking')

    // 折叠状态是「被手动收起的 id 集合」：流式后到的 part 不在集合里 ⇒ 天然展开。
    // 若改回「展开集合」，新到的 thinking part 会一个个退回收起态。
    expect(bubble).toContain('collapsedThinking')
    expect(bubble).toContain('isThinkingExpanded')

    // 预览截断已下线：class、截断函数、可折叠判定三者都不得残留。
    expect(bubble).not.toContain('timeline-step-text--preview')
    expect(bubble).not.toContain('thinkingPreview')
    expect(bubble).not.toContain('thinkingIsMultiline')

    // 思考正文不再被内层滚动区裁掉（滚动交给消息区）。
    expect(bubble).not.toMatch(/\.thinking-content\s*\{[^}]*max-height/)
  })

  it('shows a 正在思考 placeholder instead of a bare cursor while streaming', () => {
    /*
     * 上游首字到达前的空档可长达数秒，此时 displayParts 为空。原实现只渲染一个
     * 孤零零的闪烁光标，观感等同卡死。占位不得依赖任何后端事件，否则又要等网关。
     */
    const bubble = readSource('components/chat/ChatMessageBubble.vue')
    expect(bubble).toContain('thinking-placeholder')
    expect(bubble).toContain('正在思考')
    expect(bubble).toMatch(/isStreaming && !suppressTypingCursor && !hasVisibleContent/)
    // 🔴 空 text part 不算内容：流式兜底会合成一条 text='' 的 part，
    // 用 groupedDisplayItems.length === 0 判定的话占位永远不出现。
    expect(bubble).toContain('hasVisibleContent')
  })

  it('keeps thinking rows inside the process group expanded and untruncated', () => {
    /*
     * 与工具调用相邻的思考步骤原本要两级点击才能看到全文（容器折叠 + 行折叠），
     * 且长思考会被 .tpg-list 的内层滚动裁掉。
     */
    const group = readSource('components/chat/ToolProcessGroup.vue')
    expect(group).toContain('defaultExpanded: true')
    // thinking 行走「收起集合」，tool 行维持默认收起的「展开集合」
    expect(group).toContain('collapsedRows')
    expect(group).toContain('expandedRows')
    expect(group).not.toMatch(/\.tpg-list\s*\{[^}]*max-height/)
  })
})
