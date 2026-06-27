/**
 * useImCapability 图级 IM 能力判定单元测试（SLOT-04 / CONTEXT 决策 D / WR-01）。
 *
 * 覆盖：
 * - 图含 create_group_chat → hasImCapability=true → isImGated('notify_feishu_im')=false。
 * - 图含 create_work_item_chat（另一 IM 源）→ 同样具备能力。
 * - 图无任何 IM 源 + notify_feishu_im 发群（默认 chat_id 模式且无 receive_id）→ 门控。
 * - WR-01：notify_feishu（webhook 型）永不门控；notify_feishu_im 发个人
 *   （open_id/user_id）或已配置 receive_id（字面/变量化）不误报。
 * - 非 IM 依赖节点（ai_coding）恒 false（不论是否有源）。
 * - 源/依赖集导出常量内容正确。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('~/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}))

const { useWorkflowsStore } = await import('~/stores/useWorkflowsStore')
const { useImCapability, IM_SOURCE_TYPES, IM_DEPENDENT_TYPES } = await import('../useImCapability')

type Store = ReturnType<typeof useWorkflowsStore>

function makeNode(id: string, nodeType: string) {
  return {
    id,
    shortId: id.slice(0, 3),
    nodeType,
    name: id,
    description: '',
    position: { x: 0, y: 0 },
    config: {},
    onError: 'abort' as const,
    retryTimes: 0,
    retryDelay: 5,
    nodeTimeoutSeconds: null,
    fallbackValues: null,
    runCondition: null,
    metadata: {} as Record<string, unknown>,
  }
}

let store: Store

beforeEach(() => {
  setActivePinia(createPinia())
  store = useWorkflowsStore()
})

describe('useImCapability - 图级 IM 能力判定', () => {
  it('图含 create_group_chat → hasImCapability=true、IM 依赖节点不门控', () => {
    store.nodes.push(makeNode('a', 'create_group_chat'), makeNode('b', 'notify_feishu_im'))
    const { hasImCapability, isImGated } = useImCapability()

    expect(hasImCapability.value).toBe(true)
    expect(isImGated('notify_feishu_im')).toBe(false)
    expect(isImGated('notify_feishu')).toBe(false)
  })

  it('图含 create_work_item_chat（另一 IM 源）→ 同样具备 IM 能力', () => {
    store.nodes.push(makeNode('a', 'create_work_item_chat'))
    const { hasImCapability, isImGated } = useImCapability()

    expect(hasImCapability.value).toBe(true)
    expect(isImGated('notify_feishu_im')).toBe(false)
  })

  it('图无任何 IM 源 + notify_feishu_im 发群默认（无 receive_id）→ 门控', () => {
    store.nodes.push(makeNode('a', 'ai_coding'), makeNode('b', 'notify_feishu_im'))
    const { hasImCapability, isImGated } = useImCapability()

    expect(hasImCapability.value).toBe(false)
    // 默认 chat_id 模式且未配置 receive_id → 缺 chat_id 来源，门控
    expect(isImGated('notify_feishu_im')).toBe(true)
    expect(isImGated('notify_feishu_im', { receive_id_type: 'chat_id' })).toBe(true)
  })

  it('notify_feishu（webhook 型）永不门控（WR-01，无 chat_id 依赖）', () => {
    store.nodes.push(makeNode('a', 'ai_coding'), makeNode('b', 'notify_feishu'))
    const { isImGated } = useImCapability()

    expect(isImGated('notify_feishu')).toBe(false)
    expect(isImGated('notify_feishu', { webhook_url: 'https://example' })).toBe(false)
  })

  it('notify_feishu_im 发个人（open_id/user_id）→ 不误门控（WR-01）', () => {
    store.nodes.push(makeNode('a', 'ai_coding'), makeNode('b', 'notify_feishu_im'))
    const { isImGated } = useImCapability()

    expect(isImGated('notify_feishu_im', { receive_id_type: 'open_id' })).toBe(false)
    expect(isImGated('notify_feishu_im', { receive_id_type: 'user_id' })).toBe(false)
  })

  it('notify_feishu_im 已配置 receive_id（字面/变量化 chat_id）→ 不误门控（WR-01）', () => {
    store.nodes.push(makeNode('a', 'ai_coding'), makeNode('b', 'notify_feishu_im'))
    const { isImGated } = useImCapability()

    // 字面群 ID
    expect(isImGated('notify_feishu_im', { receive_id_type: 'chat_id', receive_id: 'oc_xxx' })).toBe(false)
    // 模板变量化 chat_id（如来自 fetch_group_chat）
    expect(isImGated('notify_feishu_im', { receive_id_type: 'chat_id', receive_id: '{{ chat_id }}' })).toBe(false)
    // 空白 receive_id 仍视为无来源 → 门控
    expect(isImGated('notify_feishu_im', { receive_id_type: 'chat_id', receive_id: '   ' })).toBe(true)
  })

  it('非 IM 依赖节点恒不门控（有源/无源均 false）', () => {
    store.nodes.push(makeNode('a', 'ai_coding'))
    const noSource = useImCapability()
    expect(noSource.isImGated('ai_coding')).toBe(false)

    store.nodes.push(makeNode('b', 'create_group_chat'))
    expect(noSource.isImGated('ai_coding')).toBe(false)
  })

  it('hasImCapability 随 store.nodes 变化响应式更新', () => {
    const { hasImCapability } = useImCapability()
    expect(hasImCapability.value).toBe(false)

    store.nodes.push(makeNode('a', 'create_group_chat'))
    expect(hasImCapability.value).toBe(true)
  })

  it('导出源/依赖集内容正确（WR-01：notify_feishu 不在依赖集）', () => {
    expect(IM_SOURCE_TYPES.has('create_group_chat')).toBe(true)
    expect(IM_SOURCE_TYPES.has('create_work_item_chat')).toBe(true)
    expect(IM_DEPENDENT_TYPES.has('notify_feishu_im')).toBe(true)
    expect(IM_DEPENDENT_TYPES.has('notify_feishu')).toBe(false)
  })
})
