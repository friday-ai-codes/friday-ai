/**
 * useImCapability 图级 IM 能力判定单元测试（SLOT-04 / CONTEXT 决策 D）。
 *
 * 覆盖：
 * - 图含 create_group_chat → hasImCapability=true → isImGated('notify_feishu_im')=false。
 * - 图含 create_work_item_chat（另一 IM 源）→ 同样具备能力。
 * - 图无任何 IM 源 → isImGated('notify_feishu_im')=true、isImGated('notify_feishu')=true。
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

  it('图无任何 IM 源 → IM 依赖节点被门控', () => {
    store.nodes.push(makeNode('a', 'ai_coding'), makeNode('b', 'notify_feishu_im'))
    const { hasImCapability, isImGated } = useImCapability()

    expect(hasImCapability.value).toBe(false)
    expect(isImGated('notify_feishu_im')).toBe(true)
    expect(isImGated('notify_feishu')).toBe(true)
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

  it('导出源/依赖集内容正确', () => {
    expect(IM_SOURCE_TYPES.has('create_group_chat')).toBe(true)
    expect(IM_SOURCE_TYPES.has('create_work_item_chat')).toBe(true)
    expect(IM_DEPENDENT_TYPES.has('notify_feishu')).toBe(true)
    expect(IM_DEPENDENT_TYPES.has('notify_feishu_im')).toBe(true)
  })
})
