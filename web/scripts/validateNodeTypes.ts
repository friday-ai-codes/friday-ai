/**
 * CI 验证脚本：检测前端节点列表与后端 NodeRegistry 的一致性。
 *
 * 运行方式：npm run validate:node-types
 * 环境变量：API_BASE_URL（默认 http://localhost:8000）
 *
 * Exit codes:
 * 0 — 节点一致，或后端未运行（跳过验证）
 * 1 — 前后端节点列表不一致
 * 2 — 后端返回非网络错误（如 500）
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nodeTypeMapping } from '../src/components/workflow/x6/nodeTypeMapping'
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const apiBase = process.env.API_BASE_URL ?? 'http://localhost:8000'
// -- 提取前端节点列表 --
/** 从 nodeTypeMapping（直接 import，纯 TS 无 Vue 依赖）提取 */
function getMappingTypes: Set<string> {
 return new Set(nodeTypeMapping.map(m => m.workflowType))
}
/** 从 nodeRegistry.ts 用正则提取 shape key */
function getRegistryTypes: Set<string> {
 const file = path.resolve(__dirname, '../src/components/workflow/x6/nodeRegistry.ts')
 const content = fs.readFileSync(file, 'utf-8')
 const types = new Set<string>
 for (const match of content.matchAll(/^\s+(\w+):\s*X6/gm)) {
 types.add(match[1])
 }
 return types
}
/** 从 NodePalette.vue 用正则提取 type 字段 */
function getPaletteTypes: Set<string> {
 const file = path.resolve(__dirname, '../src/components/workflow/sidebar/NodePalette.vue')
 const content = fs.readFileSync(file, 'utf-8')
 const types = new Set<string>
 for (const match of content.matchAll(/type:\s*'([^']+)'/g)) {
 types.add(match[1])
 }
 return types
}
/** 集合差集 */
function diff(a: Set<string>, b: Set<string>): string {
 return [...a].filter(x => !b.has(x)).sort
}
async function main: Promise<void> {
 // 1. 获取后端节点列表
 let backendSet: Set<string>
 try {
 const res = await fetch(`${apiBase}/api/workflows/node-types/`)
 if (!res.ok) {
 console.error(`Backend returned HTTP ${res.status}`)
 process.exit(2)
 }
 const data = (await res.json) as { node_type: string }
 backendSet = new Set(data.map(n => n.node_type))
 } catch (err: unknown) {
 // Node fetch 将网络错误包裹在 cause 中
 const cause = (err as { cause?: { code?: string } }).cause
 const code = cause?.code ?? (err as NodeJS.ErrnoException).code
 if (code === 'ECONNREFUSED' || code === 'ENOTFOUND' || code === 'UND_ERR_CONNECT_TIMEOUT') {
 console.warn(`\u26A0 Backend not running at ${apiBase}, skipping validation`)
 process.exit(0)
 }
 console.error('Fetch error:', err)
 process.exit(2)
 }
 // 2. 提取前端三文件节点列表
 const mappingSet = getMappingTypes
 const registrySet = getRegistryTypes
 const paletteSet = getPaletteTypes
 // 3. 对比
 const checks = [
 { name: 'nodeTypeMapping', missing: diff(backendSet, mappingSet), extra: diff(mappingSet, backendSet) },
 { name: 'nodeRegistry', missing: diff(backendSet, registrySet), extra: diff(registrySet, backendSet) },
 { name: 'NodePalette', missing: diff(backendSet, paletteSet), extra: diff(paletteSet, backendSet) },
 ]
 let hasError = false
 for (const c of checks) {
 if (c.missing.length) { console.error(`[${c.name}] missing: ${c.missing.join(', ')}`); hasError = true }
 if (c.extra.length) { console.error(`[${c.name}] extra: ${c.extra.join(', ')}`); hasError = true }
 }
 if (hasError) {
 process.exit(1)
 }
 console.log('\u2713 All node types are in sync')
}
main
