import { describe, expect, it } from 'vitest'
import { ALL_NODE_DEFINITIONS, getNodeDef } from '../index'

describe('aLL_NODE_DEFINITIONS', () => {
  const migratedNodes = [
    // triggers
    'manual_trigger',
    'webhook_trigger',
    // control
    'delay',
    'condition',
    'parallel',
    'join',
    'human_approval',
    'foreach',
    'aggregate',
    // action
    'code',
    // integration
    'notify_feishu',
    'notify_feishu_im',
    'feishu_doc_create',
    'http_request',
    'merge_pr',
    'mcp_deploy',
    'fetch_group_chat',
    'join_group_chat',
    'group_chat_question',
  ]

  it('包含所有已迁移节点', () => {
    for (const nodeType of migratedNodes) {
      expect(ALL_NODE_DEFINITIONS[nodeType], `missing ${nodeType}`).toBeDefined()
    }
  })

  it('已迁移节点数量正确', () => {
    expect(Object.keys(ALL_NODE_DEFINITIONS).length).toBe(migratedNodes.length)
  })

  it.each(migratedNodes)('%s 有正确的基本属性', (nodeType) => {
    const def = ALL_NODE_DEFINITIONS[nodeType]
    expect(def.nodeType).toBe(nodeType)
    expect(def.displayName).toBeTruthy()
    expect(def.description).toBeTruthy()
    expect(def.icon).toBeTruthy()
    expect(def.color).toBeTruthy()
    expect(def.category).toBeTruthy()
    expect(def.schema).toBeDefined()
    expect(def.defaultConfig).toBeDefined()
  })

  describe('uiSchema 定义', () => {
    it('manual_trigger 有 uiSchema', () => {
      const def = getNodeDef('manual_trigger')
      expect(def?.uiSchema).toBeDefined()
      expect(def?.uiSchema?.fields?.input_schema?.widget).toBe('json-editor')
    })

    it('delay 有 uiSchema with groups', () => {
      const def = getNodeDef('delay')
      expect(def?.uiSchema).toBeDefined()
      expect(def?.uiSchema?.groups).toHaveLength(1)
      expect(def?.uiSchema?.groups?.[0].fields).toEqual(['delay_seconds', 'delay_until'])
      expect(def?.uiSchema?.fields?.delay_seconds?.widget).toBe('number')
    })

    it('condition 有 uiSchema', () => {
      const def = getNodeDef('condition')
      expect(def?.uiSchema?.fields?.conditions?.widget).toBe('json-editor')
    })

    it('parallel 有 uiSchema', () => {
      const def = getNodeDef('parallel')
      expect(def?.uiSchema?.fields?.branches?.widget).toBe('json-editor')
      expect(def?.uiSchema?.fields?.pass_input?.widget).toBe('boolean')
    })

    it('notify_feishu 有 uiSchema with groups and visible_if', () => {
      const def = getNodeDef('notify_feishu')
      expect(def?.uiSchema?.groups).toHaveLength(2)
      expect(def?.uiSchema?.fields?.title?.visible_if).toEqual({
        field: 'message_type',
        operator: 'eq',
        value: 'post',
      })
    })
  })

  describe('zod schema 验证', () => {
    it('delay defaultConfig 通过 schema 验证', () => {
      const def = getNodeDef('delay')!
      const result = def.schema.safeParse(def.defaultConfig)
      expect(result.success).toBe(true)
    })

    it('notify_feishu defaultConfig 通过 schema 验证', () => {
      const def = getNodeDef('notify_feishu')!
      const result = def.schema.safeParse(def.defaultConfig)
      expect(result.success).toBe(true)
    })

    it('condition defaultConfig 通过 schema 验证', () => {
      const def = getNodeDef('condition')!
      const result = def.schema.safeParse(def.defaultConfig)
      expect(result.success).toBe(true)
    })
  })
})
