/**
 * useConnectionValidator 守护测试（SLOT-03 第 4 条契约兼容 + 既有三规则零回归）。
 *
 * 覆盖：
 * - 既有三条规则逐字不变：防自连 / 四元组重复 / BFS 防环。
 * - 第 4 条契约兼容：双端 typed shape 不等 → 返回含中文 shape 名的 incompatibleBody
 *   （用真实 zh-CN.json 作 createI18n messages 断言，沿用 Phase 24/91 i18n 守护范式）。
 * - 空契约通配零回归：任一端空 shape（default/未声明）→ 返回 null（不拦既有合法连线）。
 */
import type { GraphEdge } from '@vue-flow/core'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'

// ---------------------------------------------------------------------------
// Mock @vue-flow/core：getEdges（既有三规则）+ findNode（第 4 条解析 nodeType）
// ---------------------------------------------------------------------------
const mockEdges = ref<GraphEdge[]>([])
const mockNodes = new Map<string, { data: { nodeType: string } }>()

vi.mock('@vue-flow/core', () => ({
  useVueFlow: () => ({
    getEdges: mockEdges,
    findNode: (id: string) => mockNodes.get(id),
  }),
}))

// 被测模块在 mock 之后导入
const { getValidationError } = await import('../useConnectionValidator')

// 真实 zh-CN.json i18n（守护中文文案不被改空）
const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })
const t = (i18n.global as any).t as (key: string, named?: Record<string, unknown>) => string

function seedStore() {
  const store = useNodeTypesStore()
  store.nodeTypes = [
    {
      node_type: 'ai_plan_research',
      display_name: 'AI 方案研究',
      description: '',
      icon: '',
      category: 'ai',
      config_schema: {},
      inputs: [{ name: 'default', label: '', type: 'any', required: false, description: '' }],
      outputs: [
        { name: 'clarify', label: '', type: 'any', required: false, description: '', shape: 'clarification_request' },
        { name: 'default', label: '', type: 'any', required: false, description: '' },
      ],
      requires_container: false,
      is_blocking: false,
    },
    {
      node_type: 'clarification_card',
      display_name: '澄清卡片',
      description: '',
      icon: '',
      category: 'ai',
      config_schema: {},
      inputs: [
        { name: 'clarification_request', label: '', type: 'any', required: false, description: '', shape: 'clarification_request' },
        { name: 'default', label: '', type: 'any', required: false, description: '' },
      ],
      outputs: [],
      requires_container: false,
      is_blocking: false,
    },
    {
      node_type: 'notify_feishu',
      display_name: '飞书通知',
      description: '',
      icon: '',
      category: 'integration',
      config_schema: {},
      inputs: [
        { name: 'message', label: '', type: 'any', required: false, description: '', shape: 'feishu_message' },
      ],
      outputs: [],
      requires_container: false,
      is_blocking: false,
    },
  ] as any

  mockNodes.clear()
  mockNodes.set('plan', { data: { nodeType: 'ai_plan_research' } })
  mockNodes.set('card', { data: { nodeType: 'clarification_card' } })
  mockNodes.set('notify', { data: { nodeType: 'notify_feishu' } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  mockEdges.value = []
  seedStore()
})

describe('既有三规则零回归', () => {
  it('防自连', () => {
    expect(getValidationError({ source: 'plan', target: 'plan', sourceHandle: 'default', targetHandle: 'default' }, t))
      .toBe('不能连接到自身')
  })

  it('四元组重复连线', () => {
    mockEdges.value = [
      { source: 'plan', target: 'card', sourceHandle: 'default', targetHandle: 'default' } as any,
    ]
    expect(getValidationError({ source: 'plan', target: 'card', sourceHandle: 'default', targetHandle: 'default' }, t))
      .toBe('已存在连接')
  })

  it('防环（BFS 可达 source）', () => {
    mockEdges.value = [
      { source: 'card', target: 'plan', sourceHandle: 'default', targetHandle: 'default' } as any,
    ]
    // plan → card 会与既有 card → plan 形成环
    expect(getValidationError({ source: 'plan', target: 'card', sourceHandle: 'default', targetHandle: 'default' }, t))
      .toBe('会形成环路')
  })
})

describe('第 4 条契约形状兼容', () => {
  it('双端 typed shape 不等 → 返回含中文 shape 名的 incompatibleBody', () => {
    // plan.clarify(output, clarification_request) → notify.message(input, feishu_message)：不兼容
    const err = getValidationError(
      { source: 'plan', target: 'notify', sourceHandle: 'clarify', targetHandle: 'message' },
      t,
    )
    expect(err).not.toBeNull()
    expect(err).toContain('形状不兼容')
    expect(err).toContain('澄清请求')
    expect(err).toContain('飞书消息')
    // 不暴露英文标识符
    expect(err).not.toContain('clarification_request')
    expect(err).not.toContain('feishu_message')
  })

  it('双端 typed shape 相等 → 放行（返回 null）', () => {
    // plan.clarify(clarification_request) → card.clarification_request(clarification_request)
    expect(getValidationError(
      { source: 'plan', target: 'card', sourceHandle: 'clarify', targetHandle: 'clarification_request' },
      t,
    )).toBeNull()
  })

  it('任一端空 shape（default 通用端口）→ 放行（零回归）', () => {
    // plan.default(output, 无 shape) → card.default(input, 无 shape)
    expect(getValidationError(
      { source: 'plan', target: 'card', sourceHandle: 'default', targetHandle: 'default' },
      t,
    )).toBeNull()
    // typed output → 空 input 也放行
    expect(getValidationError(
      { source: 'plan', target: 'card', sourceHandle: 'clarify', targetHandle: 'default' },
      t,
    )).toBeNull()
  })

  it('无 t 注入时不兼容仍返回非空（boolean 路径判非法）且为中文模板', () => {
    const err = getValidationError(
      { source: 'plan', target: 'notify', sourceHandle: 'clarify', targetHandle: 'message' },
    )
    expect(err).not.toBeNull()
    expect(err).toContain('形状不兼容')
  })
})

describe('i18n 守护：incompatibleBody 中文键不被改空', () => {
  it('含 workflow.editor.slot.incompatibleBody 与 shape 中文名', () => {
    expect(t('workflow.editor.slot.incompatibleBody', { source: 'A', target: 'B' }))
      .toBe('形状不兼容：「A」无法接入「B」')
    expect(t('workflow.editor.shape.clarificationRequest')).toBe('澄清请求')
    expect(t('workflow.editor.slot.attachedBadge')).toBe('附着')
    expect(t('workflow.editor.slot.imGatedHint')).toBe('需先添加「创建群聊」节点以提供 chat_id')
  })
})
