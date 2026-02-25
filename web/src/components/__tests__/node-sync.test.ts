import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { nodeTypeMapping } from '../workflow/x6/nodeTypeMapping'
import { getDefaultPortsForNodeType } from '../workflow/x6/ports'
// 从 nodeTypeMapping.ts 直接 import 提取 workflowType
const mappingSet = new Set(nodeTypeMapping.map(m => m.workflowType))
// nodeRegistry.ts 和 NodePalette.vue 通过文件读取 + 正则提取
const x6Dir = path.resolve(__dirname, '../workflow/x6')
const sidebarDir = path.resolve(__dirname, '../workflow/sidebar')
const registrySource = fs.readFileSync(path.join(x6Dir, 'nodeRegistry.ts'), 'utf-8')
const registrySet = new Set(
 [...registrySource.matchAll(/^\s+(\w+):\s*X6/gm)].map(m => m[1]),
)
const paletteSource = fs.readFileSync(path.join(sidebarDir, 'NodePalette.vue'), 'utf-8')
const paletteSet = new Set(
 [...paletteSource.matchAll(/type:\s*'([^']+)'/g)].map(m => m[1]),
)
// 后端 27 个注册节点
const EXPECTED_NODES = [
 'manual_trigger', 'webhook_trigger', 'feishu_event_trigger',
 'fetch_work_item', 'fetch_project_info', 'context_retrieval',
 'http_request', 'create_branch', 'create_pr', 'merge_pr',
 'notify_feishu', 'mcp_deploy', 'wait_feishu_field',
 'delay', 'parallel', 'join',
 'condition', 'human_approval',
 'ai_prompt', 'ai_coding_dispatcher', 'ai_variable_extractor',
 'variable_extractor', 'ai_technical_plan',
 'ai_plan_generation', 'ai_plan_approval',
 'ai_coding', 'ai_code_review',
]
describe('前端三文件节点注册一致性', => {
 it('不应包含幽灵节点 code_implement', => {
 expect(mappingSet.has('code_implement')).toBe(false)
 expect(registrySet.has('code_implement')).toBe(false)
 expect(paletteSet.has('code_implement')).toBe(false)
 })
 it('不应包含幽灵节点 technical_plan', => {
 expect(mappingSet.has('technical_plan')).toBe(false)
 expect(registrySet.has('technical_plan')).toBe(false)
 expect(paletteSet.has('technical_plan')).toBe(false)
 })
 it('应包含所有后端节点', => {
 for (const node of EXPECTED_NODES) {
 expect(mappingSet, `mappingSet missing ${node}`).toContain(node)
 expect(registrySet, `registrySet missing ${node}`).toContain(node)
 expect(paletteSet, `paletteSet missing ${node}`).toContain(node)
 }
 })
 it('三文件节点列表应一致', => {
 // mapping 和 palette 应完全一致
 for (const node of mappingSet) {
 expect(paletteSet, `paletteSet missing ${node}`).toContain(node)
 }
 for (const node of paletteSet) {
 expect(mappingSet, `mappingSet missing ${node}`).toContain(node)
 }
 // registry 应包含 mapping 中所有节点
 for (const node of mappingSet) {
 expect(registrySet, `registrySet missing ${node}`).toContain(node)
 }
 })
 it('parallel 端口配置应有多输出', => {
 const ports = getDefaultPortsForNodeType('parallel')
 const outputs = ports.filter(p => p.group === 'output')
 expect(outputs.length).toBeGreaterThanOrEqual(2)
 })
 it('join 端口配置应有多输入', => {
 const ports = getDefaultPortsForNodeType('join')
 const inputs = ports.filter(p => p.group === 'input')
 expect(inputs.length).toBeGreaterThanOrEqual(2)
 })
})
