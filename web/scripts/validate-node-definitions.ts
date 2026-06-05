/**
 * CI 验证脚本：检查 NodeDefinition 契约的三层一致性
 *
 * 替代 validateNodeTypes.ts，新增字段级检查。
 *
 * 检查内容：
 * 1. 名称一致性：ALL_NODE_DEFINITIONS 中的节点在 NodePalette 中存在
 * 2. ui_schema 合法性：uiSchema.fields 中引用的字段在 config_schema 中存在
 * 3. 后端一致性：TypeScript config_schema 与后端 API config_schema 字段对齐
 *
 * 运行方式：pnpm run validate:node-defs
 * 环境变量：API_BASE_URL（默认 http://localhost:10241）
 *
 * Exit codes:
 *   0 — 一致
 *   1 — 不一致
 *   2 — 后端返回非网络错误
 */
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const apiBase = process.env.API_BASE_URL ?? 'http://localhost:10241'

async function main(): Promise<void> {
  const { ALL_NODE_DEFINITIONS } = await import('../src/types/workflow/node-definitions/index')

  let hasError = false

  // ===== 1. ui_schema 合法性检查 =====
  console.log('\n--- ui_schema field validation ---')
  for (const [nodeType, def] of Object.entries(ALL_NODE_DEFINITIONS)) {
    if (!def.uiSchema?.fields)
      continue

    // Zod 4 内置 toJSONSchema
    const jsonSchema = (def.schema as any).toJSONSchema() as Record<string, unknown>
    const properties = (jsonSchema.properties ?? {}) as Record<string, unknown>
    const validKeys = new Set(Object.keys(properties))

    for (const fieldKey of Object.keys(def.uiSchema.fields)) {
      if (!validKeys.has(fieldKey)) {
        console.error(`✗ Node '${nodeType}': ui_schema field '${fieldKey}' not in config_schema properties`)
        hasError = true
      }
    }
  }
  if (!hasError) {
    console.log(`✓ All ui_schema fields valid (${Object.keys(ALL_NODE_DEFINITIONS).length} nodes checked)`)
  }

  // ===== 2. NodePalette 名称一致性 =====
  console.log('\n--- NodePalette consistency ---')
  const palettePath = path.resolve(__dirname, '../src/components/workflow/sidebar/NodePalette.vue')
  const paletteSource = fs.readFileSync(palettePath, 'utf-8')
  const paletteTypes = new Set(
    [...paletteSource.matchAll(/(?:type:\s*|fromDef\()'([^']+)'/g)].map(m => m[1]),
  )

  const defTypes = new Set(Object.keys(ALL_NODE_DEFINITIONS))
  for (const nodeType of defTypes) {
    if (!paletteTypes.has(nodeType)) {
      console.error(`✗ Node '${nodeType}': in ALL_NODE_DEFINITIONS but not in NodePalette`)
      hasError = true
    }
  }
  if ([...defTypes].every(t => paletteTypes.has(t))) {
    console.log(`✓ All ${defTypes.size} defined nodes present in NodePalette`)
  }

  // ===== 3. 后端一致性（可选，后端可能未运行）=====
  console.log('\n--- Backend consistency ---')
  let backendSchemas: Map<string, Record<string, unknown>>
  try {
    const res = await fetch(`${apiBase}/api/workflows/node-types/`)
    if (!res.ok) {
      if (res.status === 401 || res.status === 403) {
        console.warn(`⚠ Backend requires auth (HTTP ${res.status}), skipping backend validation`)
        process.exit(hasError ? 1 : 0)
      }
      console.error(`Backend returned HTTP ${res.status}`)
      process.exit(2)
    }
    const data = (await res.json()) as Array<{ node_type: string, config_schema: Record<string, unknown> }>
    backendSchemas = new Map(data.map(n => [n.node_type, n.config_schema]))
  }
  catch (err: unknown) {
    const cause = (err as { cause?: { code?: string } }).cause
    const code = cause?.code ?? (err as NodeJS.ErrnoException).code
    if (code === 'ECONNREFUSED' || code === 'ENOTFOUND' || code === 'UND_ERR_CONNECT_TIMEOUT') {
      console.warn(`⚠ Backend not running at ${apiBase}, skipping backend validation`)
      process.exit(hasError ? 1 : 0)
    }
    console.error('Fetch error:', err)
    process.exit(2)
  }

  // 字段级对比
  for (const [nodeType, def] of Object.entries(ALL_NODE_DEFINITIONS)) {
    const backendSchema = backendSchemas.get(nodeType)
    if (!backendSchema) {
      console.warn(`⚠ Node '${nodeType}': not in backend (may be frontend-only or not yet deployed)`)
      continue
    }

    const tsJsonSchema = (def.schema as any).toJSONSchema() as Record<string, unknown>
    const tsProps = new Set(Object.keys((tsJsonSchema.properties ?? {}) as Record<string, unknown>))
    const backendProps = new Set(Object.keys((backendSchema.properties ?? {}) as Record<string, unknown>))

    const missingInBackend = [...tsProps].filter(k => !backendProps.has(k))
    const extraInBackend = [...backendProps].filter(k => !tsProps.has(k))

    if (missingInBackend.length || extraInBackend.length) {
      console.error(`✗ Node '${nodeType}': field mismatch`)
      if (missingInBackend.length)
        console.error(`  - Missing in backend: ${missingInBackend.join(', ')}`)
      if (extraInBackend.length)
        console.error(`  - Extra in backend: ${extraInBackend.join(', ')}`)
      hasError = true
    }
  }
  if (!hasError) {
    console.log(`✓ All fields aligned with backend`)
  }

  process.exit(hasError ? 1 : 0)
}

main().catch((err) => {
  console.error('Validation failed:', err)
  process.exit(2)
})
