import { describe, expect, it } from 'vitest'
import {
  buildNodePath,
  buildNodeRef,
  buildPrefixPath,
  buildPrefixRef,
  isLikelyUuid,
} from '../variableRef'

describe('buildNodePath', () => {
  it('生成无大括号的节点变量路径（供 picker path 字段使用）', () => {
    expect(buildNodePath('aB1', 'data.name')).toBe('nodes.aB1.data.name')
  })

  it('单层字段路径', () => {
    expect(buildNodePath('aB1', 'output')).toBe('nodes.aB1.output')
  })

  it('嵌套 field path 透传不转义（dict 下钻）', () => {
    expect(buildNodePath('Xyz', 'data.user.name')).toBe('nodes.Xyz.data.user.name')
  })

  it('list 数字索引路径透传不转义', () => {
    expect(buildNodePath('Xyz', 'items.0.name')).toBe('nodes.Xyz.items.0.name')
  })
})

describe('buildNodeRef', () => {
  it('生成完整 {{nodes.<short_id>.<field>}} 引用（供端口复制/schema 展示）', () => {
    expect(buildNodeRef('aB1', 'output')).toBe('{{nodes.aB1.output}}')
  })

  it('嵌套路径同样包裹大括号', () => {
    expect(buildNodeRef('aB1', 'data.name')).toBe('{{nodes.aB1.data.name}}')
  })
})

describe('buildPrefixPath', () => {
  it('生成无大括号的非节点前缀路径', () => {
    expect(buildPrefixPath('trigger', 'event_type')).toBe('trigger.event_type')
  })

  it('input 前缀', () => {
    expect(buildPrefixPath('input', 'work_item_id')).toBe('input.work_item_id')
  })

  it('global 前缀嵌套路径透传', () => {
    expect(buildPrefixPath('global', 'meta.description')).toBe('global.meta.description')
  })
})

describe('buildPrefixRef', () => {
  it('生成完整 {{<prefix>.<field>}} 引用', () => {
    expect(buildPrefixRef('trigger', 'event_type')).toBe('{{trigger.event_type}}')
  })

  it('config 前缀', () => {
    expect(buildPrefixRef('config', 'model')).toBe('{{config.model}}')
  })
})

describe('isLikelyUuid', () => {
  it('标准小写 UUID v4 判定为 true', () => {
    expect(isLikelyUuid('a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d')).toBe(true)
  })

  it('大写 UUID 判定为 true（不区分大小写）', () => {
    expect(isLikelyUuid('A1B2C3D4-E5F6-4A7B-8C9D-0E1F2A3B4C5D')).toBe(true)
  })

  it('short_id（如 aB1）判定为 false', () => {
    expect(isLikelyUuid('aB1')).toBe(false)
  })

  it('uUID 前 8 位截断形式判定为 false', () => {
    expect(isLikelyUuid('a1b2c3d4')).toBe(false)
  })

  it('空字符串判定为 false', () => {
    expect(isLikelyUuid('')).toBe(false)
  })

  it('带前后缀的 UUID 子串判定为 false（必须整串匹配）', () => {
    expect(isLikelyUuid('x-a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d')).toBe(false)
  })
})
