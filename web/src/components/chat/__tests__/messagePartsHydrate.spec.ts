/**
 * hydrate adapter 单元测试。
 *
 * 5 条真实 legacy fixture 覆盖 legacy hydrate 算法分支：
 *   F1：纯 content（单 text part）
 *   F2：content + narrations（legacy 典型）
 *   F3：content + tool_calls + narrations（含 routing trace）
 *   F4：content + timeline + tool_calls（legacy 末期 timeline-based）
 *   F5：deep_analysis 长 markdown 答复（关键 case，根治分析容器吃正文）
 * + 1 条 idempotent 测试：已有 parts 直接返回
 */

import type { ConversationMessage, MessagePart } from '~/types/chat'
import { describe, expect, it } from 'vitest'

import { hydrateLegacyMessage } from '~/composables/useMessageParts'
import legacyFixtures from './fixtures/legacy-messages.json'

function asMessage(raw: unknown): ConversationMessage {
  return raw as ConversationMessage
}

describe('hydrateLegacyMessage ', () => {
  it('f1: 纯 content → 单 text part', () => {
    const parts = hydrateLegacyMessage(asMessage(legacyFixtures.F1))
    expect(parts).toHaveLength(1)
    expect(parts[0].type).toBe('text')
    expect((parts[0] as { text: string }).text).toBe('你好，我是 Friday AI。')
    expect((parts[0] as { state: string }).state).toBe('done')
  })

  it('f2: content + narrations → narration 串 text + content text part', () => {
    const parts = hydrateLegacyMessage(asMessage(legacyFixtures.F2))
    // 2 narrations + 1 content = 3 text parts
    expect(parts).toHaveLength(3)
    expect(parts.every(p => p.type === 'text')).toBe(true)
    const texts = (parts as Array<{ text: string }>).map(p => p.text)
    expect(texts[0]).toContain('让我先搜索')
    expect(texts[1]).toContain('找到了')
    expect(texts[2]).toContain('## 总结')
    // F2 关键不变量：最终 markdown 是顶层 text part，不被任何容器包裹
    expect(texts[2]).toContain('apps/auth/login.py')
  })

  it('f3: content + tool_calls + narrations → narration + tool_use + content 顺序', () => {
    const parts = hydrateLegacyMessage(asMessage(legacyFixtures.F3))
    // 2 narrations + 1 tool_use + 1 content = 4 parts
    expect(parts).toHaveLength(4)
    const types = parts.map(p => p.type)
    expect(types).toEqual(['text', 'text', 'tool_use', 'text'])
    const toolPart = parts.find(p => p.type === 'tool_use') as { name: string, status: string, result: string }
    expect(toolPart.name).toBe('analyze_repository_relevance')
    expect(toolPart.status).toBe('done')
    expect(toolPart.result).toContain('trace-abc-123')
    // 最终 content 是顶层 text part
    expect((parts[parts.length - 1] as { text: string }).text).toContain('example-app')
  })

  it('f4: content + timeline + tool_calls → timeline 顺序权威 + content 收尾', () => {
    const parts = hydrateLegacyMessage(asMessage(legacyFixtures.F4))
    // timeline: thinking + narration + tool + narration + tool = 5 + 1 content = 6 parts
    expect(parts).toHaveLength(6)
    const types = parts.map(p => p.type)
    expect(types).toEqual(['thinking', 'text', 'tool_use', 'text', 'tool_use', 'text'])
    // index 单调
    expect(parts.map(p => p.index)).toEqual([0, 1, 2, 3, 4, 5])
    // 两个 tool_use 顺序 + name 校验
    const toolNames = parts.filter(p => p.type === 'tool_use').map(p => (p as { name: string }).name)
    expect(toolNames).toEqual(['list_project_structure', 'search_repository_code'])
    // 最终 content text part
    expect((parts[5] as { text: string }).text).toContain('已为你列出仓库')
  })

  it('f5: deep_analysis 长 markdown → 关键 case，markdown 是顶层 text part（根治分析容器吃正文）', () => {
    const parts = hydrateLegacyMessage(asMessage(legacyFixtures.F5))
    // 1 narration + 1 tool_use + 1 content = 3 parts
    expect(parts).toHaveLength(3)
    const types = parts.map(p => p.type)
    expect(types).toEqual(['text', 'tool_use', 'text'])

    // 关键不变量 1：deep_analysis tool_use 携带完整 result + name 正确
    const toolPart = parts[1] as { name: string, result: string, status: string }
    expect(toolPart.name).toBe('deep_analysis')
    expect(toolPart.status).toBe('done')
    expect(toolPart.result).toContain('cross_repo_relevance:trace-deep-456')

    // 关键不变量 2：长 markdown 答复以**独立 text part** 呈现
    // Goal：「不被错误归类为分析过程旁注」
    const mainContent = parts[2] as { type: string, text: string, state: string }
    expect(mainContent.type).toBe('text')
    expect(mainContent.state).toBe('done')
    expect(mainContent.text).toContain('# entrance 字段处理逻辑分析')
    expect(mainContent.text).toContain('## 1. example-app 仓库')
    expect(mainContent.text).toContain('## 2. problem-app 仓库')
    expect(mainContent.text).toContain('```python')
    expect(mainContent.text).toContain('| 字段 | 含义 | 默认值 |')

    // 关键不变量 3：narration 单独 text part，不包裹 markdown
    const narrationPart = parts[0] as { text: string }
    expect(narrationPart.text).toBe('让我深入分析两个仓库中 entrance 字段的处理逻辑...')
    expect(narrationPart.text).not.toContain('# entrance') // narration 不包含 markdown 主体
  })

  it('idempotent: 已有 parts 的 message 直接返回', () => {
    const existingParts: MessagePart[] = [
      { type: 'text', id: 'p1', index: 0, text: 'already hydrated', state: 'done' },
      { type: 'tool_use', id: 'p2', index: 1, tool_call_id: 'c1', name: 'foo', input: {}, status: 'done', result: 'ok' },
    ]
    const msg: ConversationMessage = {
      id: 'msg_existing',
      role: 'assistant',
      content: 'fallback content',
      parts: existingParts,
      created_at: '2026-05-01T00:00:00Z',
    }
    const parts = hydrateLegacyMessage(msg)
    expect(parts).toHaveLength(2)
    expect((parts[0] as { text: string }).text).toBe('already hydrated')
    expect((parts[1] as { name: string }).name).toBe('foo')
  })

  it('fallback: 空 content + 无 metadata → 至少 1 个 text part（兜底，不让用户看到空白 bubble）', () => {
    const msg: ConversationMessage = {
      id: 'msg_empty',
      role: 'assistant',
      content: '',
      created_at: '2026-05-01T00:00:00Z',
    }
    const parts = hydrateLegacyMessage(msg)
    expect(parts.length).toBeGreaterThanOrEqual(1)
    expect(parts[0].type).toBe('text')
  })

  it('f5 反退化断言：长 markdown 中的代码块/表格不被错误处理为 tool_use', () => {
    // 防御性：以前的 narration-block 实现会把 LLM 输出的「分析过程」标题（包含
    // 三段式 markdown 标题）整段吞进 narrations[]。hydrate 算法必须保证 content
    // 字段（不管 narrations 里塞了什么）始终作为顶层 text part 输出。
    const parts = hydrateLegacyMessage(asMessage(legacyFixtures.F5))
    const allText = parts
      .filter(p => p.type === 'text')
      .map(p => (p as { text: string }).text)
      .join('\n')
    // markdown 主体的关键标识符必须在 text part 集合中可读
    expect(allText).toContain('apps/study/views.py')
    expect(allText).toContain('apps/problem/middleware.py')
    expect(allText).toContain('return render(request,')
  })
})
