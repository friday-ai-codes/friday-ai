/**
 * useConnectionDragState 拖拽连接态 holder 单测（SLOT-03）。
 *
 * 覆盖：
 * - startConnect/endConnect 切换 dragging 与 source。
 * - isCompatibleTarget：兼容 input → true、不兼容 → false、空契约（default/error）→ true 通配。
 * - 未拖拽 / endConnect 后 isCompatibleTarget 恒 false。
 * - 模块级单例：两次取用共享同一 dragging（联动）。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import { useConnectionDragState } from '../useConnectionDragState'

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
      inputs: [
        { name: 'default', label: '', type: 'any', required: false, description: '' },
      ],
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
        // 兼容：input shape 与源 output shape 相等
        { name: 'request', label: '', type: 'any', required: false, description: '', shape: 'clarification_request' },
        // 不兼容：input shape 不同
        { name: 'doc', label: '', type: 'any', required: false, description: '', shape: 'feishu_document' },
        // 空契约通配 input
        { name: 'any', label: '', type: 'any', required: false, description: '' },
      ],
      outputs: [],
      requires_container: false,
      is_blocking: false,
    },
  ] as any
  return store
}

describe('useConnectionDragState 拖拽态切换', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedStore()
    useConnectionDragState().endConnect() // 复位单例
  })

  it('startConnect 置 dragging=true 并记录 source', () => {
    const { dragging, source, startConnect } = useConnectionDragState()
    expect(dragging.value).toBe(false)
    startConnect('n1', 'clarify', 'clarification_request')
    expect(dragging.value).toBe(true)
    expect(source.value).toEqual({ nodeId: 'n1', handleId: 'clarify', shape: 'clarification_request' })
  })

  it('endConnect 置 dragging=false 并清空 source', () => {
    const { dragging, source, startConnect, endConnect } = useConnectionDragState()
    startConnect('n1', 'clarify', 'clarification_request')
    endConnect()
    expect(dragging.value).toBe(false)
    expect(source.value).toBeNull()
  })
})

describe('isCompatibleTarget 契约兼容判定', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedStore()
    useConnectionDragState().endConnect()
  })

  it('未拖拽时恒 false', () => {
    const { isCompatibleTarget } = useConnectionDragState()
    expect(isCompatibleTarget('clarification_card', 'request')).toBe(false)
  })

  it('拖拽中：兼容 input → true、不兼容 → false', () => {
    const { startConnect, isCompatibleTarget } = useConnectionDragState()
    startConnect('n1', 'clarify', 'clarification_request')
    expect(isCompatibleTarget('clarification_card', 'request')).toBe(true)
    expect(isCompatibleTarget('clarification_card', 'doc')).toBe(false)
  })

  it('空契约（源或目标 shape 空）→ true 通配', () => {
    const { startConnect, isCompatibleTarget } = useConnectionDragState()
    // 目标 input 无 shape（通配）
    startConnect('n1', 'clarify', 'clarification_request')
    expect(isCompatibleTarget('clarification_card', 'any')).toBe(true)
    // 源 shape 空（default/error 通用出口）→ 任意目标皆通配
    startConnect('n1', 'default', undefined)
    expect(isCompatibleTarget('clarification_card', 'doc')).toBe(true)
  })

  it('endConnect 后 isCompatibleTarget 恒 false', () => {
    const { startConnect, endConnect, isCompatibleTarget } = useConnectionDragState()
    startConnect('n1', 'clarify', 'clarification_request')
    endConnect()
    expect(isCompatibleTarget('clarification_card', 'request')).toBe(false)
  })
})

describe('模块级单例联动', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedStore()
    useConnectionDragState().endConnect()
  })

  it('两实例共享同一 dragging（一处 startConnect 另一处可见）', () => {
    const a = useConnectionDragState()
    const b = useConnectionDragState()
    expect(b.dragging.value).toBe(false)
    a.startConnect('n1', 'clarify', 'clarification_request')
    expect(b.dragging.value).toBe(true)
    expect(b.source.value?.handleId).toBe('clarify')
    b.endConnect()
    expect(a.dragging.value).toBe(false)
  })
})
