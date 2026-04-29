/**
 * 构建脚本：从 TypeScript NodeDefinition 生成 node-definitions.json
 *
 * 运行方式：pnpm run generate:node-defs
 *
 * 输出：web/src/types/workflow/node-definitions/node-definitions.json
 * 包含所有已迁移节点的 config_schema (JSON Schema) 和 ui_schema
 */
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
const __dirname = path.dirname(fileURLToPath(import.meta.url))
async function main: Promise<void> {
 // 动态导入 node-definitions（需要 tsx 支持）
 const { ALL_NODE_DEFINITIONS } = await import('../src/types/workflow/node-definitions/index')
 const nodes = Object.values(ALL_NODE_DEFINITIONS).map((def) => {
 // Zod 4 内置 toJSONSchema
 const jsonSchema = (def.schema as any).toJSONSchema
 return {
 node_type: def.nodeType,
 display_name: def.displayName,
 description: def.description,
 icon: def.icon,
 category: def.category,
 config_schema: jsonSchema,
 ui_schema: def.uiSchema ?? null,
 }
 })
 const output = {
 generated_at: new Date.toISOString,
 node_count: nodes.length,
 nodes,
 }
 const outputPath = path.resolve(__dirname, '../src/types/workflow/node-definitions/node-definitions.json')
 fs.writeFileSync(outputPath, JSON.stringify(output, null, 2), 'utf-8')
 console.log(`✓ Generated ${nodes.length} node definitions -> ${path.relative(process.cwd, outputPath)}`)
}
main.catch((err) => {
 console.error('Failed to generate node definitions:', err)
 process.exit(1)
})
