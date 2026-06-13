import type { NodeType } from '~/stores/useNodeTypesStore'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import {
  getDefaultConfig,
  getNodeDefinition,
  getNodesByCategory,
  hasNodeDefinition,
  validateNodeConfig,
} from '../registry'

/**
 * registry helper store 适配器单测（19-03）
 *
 * 验证 getNodeDefinition/getDefaultConfig/getNodesByCategory/validateNodeConfig
 * 全部从 useNodeTypesStore（唯一运行时源）取值，而非读已删除的硬编码注册表。
 */

function makeNodeType(overrides: Partial<NodeType> = {}): NodeType {
  return {
    node_type: 'ai_coding',
    display_name: 'AI 编码执行',
    description: 'AI 自动在容器中编码并创建 MR',
    icon: 'terminal',
    category: 'ai',
    config_schema: { properties: {}, required: [] },
    inputs: [],
    outputs: [],
    requires_container: false,
    is_blocking: false,
    ui_schema: null,
    default_config: { container_image: 'friday/claude-code:latest' },
    execution_mode: 'sync',
    ...overrides,
  }
}

describe('registry store 适配器', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('store 有该 type 时 getNodeDefinition 返回适配后的 camelCase 定义', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType()]

    const def = getNodeDefinition('ai_coding')
    expect(def?.nodeType).toBe('ai_coding')
    expect(def?.displayName).toBe('AI 编码执行')
    expect(def?.category).toBe('ai')
  })

  it('store 无该 type 时 getNodeDefinition 返回 undefined', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = []
    expect(getNodeDefinition('ai_coding')).toBeUndefined()
  })

  it('getDefaultConfig 返回后端下发的 default_config', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType({ default_config: { container_image: 'x', timeout_seconds: 60 } })]
    expect(getDefaultConfig('ai_coding')).toEqual({ container_image: 'x', timeout_seconds: 60 })
  })

  it('getNodesByCategory 从 store nodeTypesByCategory 派生分组', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [
      makeNodeType({ node_type: 'ai_coding', category: 'ai' }),
      makeNodeType({ node_type: 'create_branch', display_name: '创建分支', category: 'action' }),
    ]

    const byCategory = getNodesByCategory()
    expect(byCategory.ai.map(d => d.nodeType)).toContain('ai_coding')
    expect(byCategory.action.map(d => d.nodeType)).toContain('create_branch')
  })

  it('configComponent 由前端专属 CONFIG_COMPONENTS 注入', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType({ node_type: 'ai_coding' })]
    expect(typeof getNodeDefinition('ai_coding')?.configComponent).toBe('function')
  })

  it('hasNodeDefinition 反映 store 是否含该 type', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType()]
    expect(hasNodeDefinition('ai_coding')).toBe(true)
    expect(hasNodeDefinition('does_not_exist')).toBe(false)
  })

  it('validateNodeConfig 未知节点返回失败', () => {
    useNodeTypesStore().nodeTypes = []
    const result = validateNodeConfig('ai_coding', {})
    expect(result.success).toBe(false)
  })

  it('validateNodeConfig 缺失 required 字段时失败', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType({
      config_schema: { required: ['name'], properties: { name: { type: 'string' } } },
    })]

    const result = validateNodeConfig('ai_coding', {})
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.errors.name).toBeDefined()
    }
  })

  it('validateNodeConfig 顶层类型不匹配时失败', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType({
      config_schema: { required: [], properties: { timeout: { type: 'number' } } },
    })]

    const result = validateNodeConfig('ai_coding', { timeout: 'not-a-number' })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.errors.timeout).toBeDefined()
    }
  })

  it('validateNodeConfig required 满足且类型正确时通过', () => {
    const store = useNodeTypesStore()
    store.nodeTypes = [makeNodeType({
      config_schema: { required: ['name'], properties: { name: { type: 'string' } } },
    })]

    const result = validateNodeConfig('ai_coding', { name: 'demo' })
    expect(result.success).toBe(true)
  })
})
