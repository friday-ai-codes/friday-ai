import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

function readSource(path: string): string {
  return readFileSync(`${process.cwd()}/src/${path}`, 'utf8')
}

describe('chat visual contract', () => {
  it('uses dedicated conversation item styling in the chat sidebar', () => {
    const source = readSource('components/layout/AppSidebar.vue')

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

  it('inlines thinking nodes into the timeline with collapsible preview', () => {
    /*
     * 用户在 legacy 反馈：希望 thinking 不再放在独立折叠块，而是与
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
