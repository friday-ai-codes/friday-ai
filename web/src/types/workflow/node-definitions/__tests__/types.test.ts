import type { UiSchema } from '../types'
import { describe, expect, it } from 'vitest'
import { z } from 'zod'
import { createNodeDefinition } from '../index'
import { buildUiSchema } from '../ui-schema'

describe('nodeDefinition 类型系统', () => {
  it('createNodeDefinition 返回正确结构', () => {
    const schema = z.object({
      delay_seconds: z.number().default(60),
    })

    const def = createNodeDefinition({
      nodeType: 'test_node',
      displayName: 'Test',
      description: 'A test node',
      icon: 'icon-[lucide--clock]',
      color: 'from-blue-500 to-cyan-400',
      category: 'control',
      schema,
      defaultConfig: schema.parse({}),
    })

    expect(def.nodeType).toBe('test_node')
    expect(def.displayName).toBe('Test')
    expect(def.category).toBe('control')
    expect(def.uiSchema).toBeUndefined()
    expect(def.configComponent).toBeUndefined()
  })

  it('createNodeDefinition 包含 uiSchema', () => {
    const uiSchema: UiSchema = {
      groups: [{ key: 'timing', label: 'Time', fields: ['delay_seconds'] }],
      fields: {
        delay_seconds: { widget: 'number', help: 'Delay in seconds' },
      },
    }

    const schema = z.object({ delay_seconds: z.number().default(60) })

    const def = createNodeDefinition({
      nodeType: 'test_node',
      displayName: 'Test',
      description: '',
      icon: 'box',
      color: 'from-blue-500 to-cyan-400',
      category: 'control',
      schema,
      defaultConfig: schema.parse({}),
      uiSchema,
    })

    expect(def.uiSchema).toBeDefined()
    expect(def.uiSchema?.groups).toHaveLength(1)
    expect(def.uiSchema?.fields?.delay_seconds?.widget).toBe('number')
  })
})

describe('buildUiSchema', () => {
  it('无 groups 时只包含 fields', () => {
    const result = buildUiSchema({
      name: { widget: 'text', placeholder: 'Enter name' },
      enabled: { widget: 'boolean' },
    })

    expect(result.groups).toBeUndefined()
    expect(result.fields?.name?.widget).toBe('text')
    expect(result.fields?.enabled?.widget).toBe('boolean')
  })

  it('有 groups 时包含 groups 和 fields', () => {
    const result = buildUiSchema(
      {
        url: { widget: 'text' },
        content: { widget: 'textarea' },
      },
      [{ key: 'message', label: 'Message', fields: ['url', 'content'] }],
    )

    expect(result.groups).toHaveLength(1)
    expect(result.groups?.[0].key).toBe('message')
    expect(result.groups?.[0].fields).toEqual(['url', 'content'])
    expect(result.fields?.url?.widget).toBe('text')
  })

  it('支持 visible_if 条件', () => {
    const result = buildUiSchema({
      message_type: { widget: 'select' },
      title: {
        widget: 'text',
        visible_if: { field: 'message_type', operator: 'eq', value: 'post' },
      },
    })

    expect(result.fields?.title?.visible_if?.field).toBe('message_type')
    expect(result.fields?.title?.visible_if?.operator).toBe('eq')
    expect(result.fields?.title?.visible_if?.value).toBe('post')
  })
})
