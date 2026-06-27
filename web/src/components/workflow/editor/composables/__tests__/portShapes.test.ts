/**
 * portShapes 纯逻辑单测（SLOT-03 契约兼容地基）。
 *
 * 覆盖：
 * - arePortShapesCompatible 四态：空通配 / 相等 / 不等 / 缺失（undefined）。
 * - resolvePortShape：命中 input/output 端口取 shape；store 未就绪/未知端口返回 undefined 不抛。
 * - SHAPE_DISPLAY_KEY 7 个 typed shape 映射齐备 + shapeDisplayName 中文名/回退。
 */
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { useNodeTypesStore } from '~/stores/useNodeTypesStore'
import {
  arePortShapesCompatible,
  resolvePortShape,
  SHAPE_DISPLAY_KEY,
  shapeDisplayName,
} from '../portShapes'

describe('arePortShapesCompatible（空通配 + 双非空相等放行）', () => {
  it('任一端为空/undefined → 放行（零回归命门）', () => {
    expect(arePortShapesCompatible('', 'x')).toBe(true)
    expect(arePortShapesCompatible('x', '')).toBe(true)
    expect(arePortShapesCompatible(undefined, 'x')).toBe(true)
    expect(arePortShapesCompatible('x', undefined)).toBe(true)
    expect(arePortShapesCompatible('', '')).toBe(true)
    expect(arePortShapesCompatible(undefined, undefined)).toBe(true)
  })

  it('双端非空且相等 → 放行', () => {
    expect(arePortShapesCompatible('clarification_request', 'clarification_request')).toBe(true)
  })

  it('双端非空且不等 → 拒绝', () => {
    expect(arePortShapesCompatible('a', 'b')).toBe(false)
    expect(arePortShapesCompatible('clarification_request', 'feishu_message')).toBe(false)
  })
})

describe('resolvePortShape（按 node_type + handle 解析）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('store 未就绪（无数据）→ undefined 不抛', () => {
    expect(resolvePortShape('any', 'default', 'output')).toBeUndefined()
  })

  it('命中 output / input 端口取 shape；未知端口 → undefined', () => {
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
    ] as any

    expect(resolvePortShape('ai_plan_research', 'clarify', 'output')).toBe('clarification_request')
    // 通用端口无 shape → undefined（通配，零回归）
    expect(resolvePortShape('ai_plan_research', 'default', 'output')).toBeUndefined()
    expect(resolvePortShape('ai_plan_research', 'default', 'input')).toBeUndefined()
    // 未知端口 / 未知节点类型 → undefined 不抛
    expect(resolvePortShape('ai_plan_research', 'nope', 'output')).toBeUndefined()
    expect(resolvePortShape('unknown_node', 'clarify', 'output')).toBeUndefined()
  })
})

describe('shape 中文显示名映射', () => {
  it('shape key 映射覆盖 7 个 typed shape', () => {
    expect(Object.keys(SHAPE_DISPLAY_KEY)).toHaveLength(7)
    expect(SHAPE_DISPLAY_KEY.clarification_request).toBe('workflow.editor.shape.clarificationRequest')
    expect(SHAPE_DISPLAY_KEY.feishu_message).toBe('workflow.editor.shape.feishuMessage')
  })

  it('shapeDisplayName：有映射用 t(key)，无映射回退原 shape，空 → 空串', () => {
    const t = (k: string) => (k === 'workflow.editor.shape.clarificationRequest' ? '澄清请求' : k)
    expect(shapeDisplayName('clarification_request', t)).toBe('澄清请求')
    expect(shapeDisplayName('unmapped_shape', t)).toBe('unmapped_shape')
    expect(shapeDisplayName('clarification_request')).toBe('clarification_request')
    expect(shapeDisplayName('')).toBe('')
    expect(shapeDisplayName(undefined)).toBe('')
  })
})
