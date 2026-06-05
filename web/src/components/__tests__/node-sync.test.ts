import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { getDefaultPortsForNodeType } from '../workflow/editor/utils/portConfig'

// NodePalette.vue 通过文件读取 + 正则提取节点类型列表
const sidebarDir = path.resolve(__dirname, '../workflow/sidebar')

const paletteSource = fs.readFileSync(path.join(sidebarDir, 'NodePalette.vue'), 'utf-8')
const paletteSet = new Set(
  [...paletteSource.matchAll(/(?:type:\s*|fromDef\()'([^']+)'/g)].map(m => m[1]),
)

// 后端 29 个注册节点
const EXPECTED_NODES = [
  'manual_trigger',
  'webhook_trigger',
  'feishu_event_trigger',
  'fetch_work_item',
  'fetch_project_info',
  'context_retrieval',
  'http_request',
  'create_branch',
  'create_pr',
  'merge_pr',
  'notify_feishu',
  'mcp_deploy',
  'wait_feishu_field',
  'delay',
  'parallel',
  'join',
  'condition',
  'human_approval',
  'ai_prompt',
  'ai_coding_dispatcher',
  'ai_variable_extractor',
  'variable_extractor',
  'ai_plan_generation',
  'ai_plan_approval',
  'ai_coding',
  'ai_code_review',
  'fetch_group_chat',
  'join_group_chat',
  'group_chat_question',
]

describe('前端节点注册一致性', () => {
  it('不应包含幽灵节点 code_implement', () => {
    expect(paletteSet.has('code_implement')).toBe(false)
  })

  it('不应包含幽灵节点 technical_plan', () => {
    expect(paletteSet.has('technical_plan')).toBe(false)
  })

  it('nodePalette 应包含所有后端节点', () => {
    for (const node of EXPECTED_NODES) {
      expect(paletteSet, `paletteSet missing ${node}`).toContain(node)
    }
  })

  it('parallel 端口配置应有多输出', () => {
    const ports = getDefaultPortsForNodeType('parallel')
    const outputs = ports.filter(p => p.group === 'output')
    expect(outputs.length).toBeGreaterThanOrEqual(2)
  })

  it('join 端口配置应有多输入', () => {
    const ports = getDefaultPortsForNodeType('join')
    const inputs = ports.filter(p => p.group === 'input')
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })
})
