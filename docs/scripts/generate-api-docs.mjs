/**
 * OpenAPI Schema 到 VitePress Markdown 自动生成脚本
 *
 * 从 docs/public/schema.json 读取 OpenAPI 3.0 schema，
 * 按 Django App tag 分组生成 markdown 页面和侧边栏配置。
 *
 * 用法: node docs/scripts/generate-api-docs.mjs
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const SCHEMA_PATH = join(__dirname, '..', 'public', 'schema.json')
const API_DIR = join(__dirname, '..', 'api')
const SIDEBAR_PATH = join(__dirname, '..', '.vitepress', 'api-sidebar.json')
const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete']
// ---- Schema 加载与解析 ----
function loadSchema {
 if (!existsSync(SCHEMA_PATH)) {
 console.error(
 '请先生成 schema.json: cd server && python manage.py spectacular --color --file ../docs/public/schema.json'
 )
 process.exit(1)
 }
 return JSON.parse(readFileSync(SCHEMA_PATH, 'utf-8'))
}
/**
 * 解析 $ref 引用，将 #/components/schemas/Xxx 解析为实际 schema 对象
 */
function resolveRef(ref, schema) {
 const parts = ref.replace(/^#\//, '').split('/')
 let current = schema
 for (const part of parts) {
 current = current?.[part]
 if (current === undefined) return undefined
 }
 return current
}
/**
 * 递归解析 schema 中的所有 $ref，最大深度 5 防止无限递归
 */
function resolveSchema(obj, rootSchema, depth = 0) {
 if (!obj || typeof obj !== 'object' || depth > 5) return obj
 // 处理 $ref
 if (obj.$ref) {
 const resolved = resolveRef(obj.$ref, rootSchema)
 if (resolved) return resolveSchema(resolved, rootSchema, depth + 1)
 return obj
 }
 // 处理 array items
 if (obj.type === 'array' && obj.items) {
 return {
 ...obj,
 items: resolveSchema(obj.items, rootSchema, depth + 1),
 }
 }
 // 处理 object properties
 if (obj.properties) {
 const resolved = { ...obj, properties: {} }
 for (const [key, value] of Object.entries(obj.properties)) {
 resolved.properties[key] = resolveSchema(value, rootSchema, depth + 1)
 }
 return resolved
 }
 // 处理 allOf / oneOf / anyOf
 for (const combiner of ['allOf', 'oneOf', 'anyOf']) {
 if (Array.isArray(obj[combiner])) {
 return {
 ...obj,
 [combiner]: obj[combiner].map((item) =>
 resolveSchema(item, rootSchema, depth + 1)
 ),
 }
 }
 }
 return obj
}
// ---- 分组 ----
/**
 * 按 operation.tags[0] 分组所有端点
 */
function groupByTag(schema) {
 const groups = {}
 for (const [path, pathItem] of Object.entries(schema.paths || {})) {
 for (const method of HTTP_METHODS) {
 const operation = pathItem[method]
 if (!operation) continue
 const tag = operation.tags?.[0] || 'other'
 if (!groups[tag]) groups[tag] =
 groups[tag].push({
 path,
 method: method.toUpperCase,
 summary: operation.summary || '',
 description: operation.description || '',
 parameters: operation.parameters ||,
 requestBody: operation.requestBody || null,
 responses: operation.responses || {},
 })
 }
 }
 return groups
}
// ---- Markdown 渲染 ----
function renderSchemaProperties(schema) {
 if (!schema?.properties) return ''
 const lines = ['```json', '{']
 const entries = Object.entries(schema.properties)
 for (let i = 0; i < entries.length; i++) {
 const [key, prop] = entries[i]
 const type = prop.type || 'object'
 const desc = prop.description ? ` // ${prop.description}`: ''
 const comma = i < entries.length - 1 ? ',': ''
 if (type === 'array') {
 const itemType = prop.items?.type || 'object'
 lines.push(` "${key}": [${itemType}]${comma}${desc}`)
 } else {
 lines.push(` "${key}": "${type}"${comma}${desc}`)
 }
 }
 lines.push('}', '```')
 return lines.join('\n')
}
function renderEndpoint(ep, rootSchema) {
 const lines =
 lines.push(`### ${ep.method} \`${ep.path}\``)
 lines.push('')
 if (ep.summary) {
 lines.push(`**${ep.summary}**`)
 lines.push('')
 }
 if (ep.description) {
 lines.push(ep.description)
 lines.push('')
 }
 // 参数表
 if (ep.parameters.length > 0) {
 lines.push('#### 参数')
 lines.push('')
 lines.push('| 名称 | 位置 | 类型 | 必填 | 说明 |')
 lines.push('| --- | --- | --- | --- | --- |')
 for (const param of ep.parameters) {
 const type = param.schema?.type || 'string'
 const required = param.required ? '是': '否'
 const desc = param.description || '-'
 lines.push(`| ${param.name} | ${param.in} | ${type} | ${required} | ${desc} |`)
 }
 lines.push('')
 }
 // 请求体
 if (ep.requestBody) {
 lines.push('#### 请求体')
 lines.push('')
 const content = ep.requestBody.content?.['application/json']
 if (content?.schema) {
 const resolved = resolveSchema(content.schema, rootSchema)
 const rendered = renderSchemaProperties(resolved)
 if (rendered) {
 lines.push(rendered)
 lines.push('')
 }
 }
 }
 // 响应
 if (Object.keys(ep.responses).length > 0) {
 lines.push('#### 响应')
 lines.push('')
 for (const [code, response] of Object.entries(ep.responses)) {
 const desc = response.description || ''
 lines.push(`- **${code}**: ${desc}`)
 // 尝试渲染响应体 schema
 const content = response.content?.['application/json']
 if (content?.schema) {
 const resolved = resolveSchema(content.schema, rootSchema)
 const rendered = renderSchemaProperties(resolved)
 if (rendered) {
 lines.push('')
 lines.push(rendered)
 }
 }
 }
 lines.push('')
 }
 return lines.join('\n')
}
function renderTagPage(tag, endpoints, rootSchema) {
 const lines =
 lines.push('---')
 lines.push(`title: ${tag} API`)
 lines.push('---')
 lines.push('')
 lines.push(`# ${tag}`)
 lines.push('')
 for (let i = 0; i < endpoints.length; i++) {
 lines.push(renderEndpoint(endpoints[i], rootSchema))
 if (i < endpoints.length - 1) {
 lines.push('---')
 lines.push('')
 }
 }
 return lines.join('\n')
}
// ---- 侧边栏配置 ----
function generateSidebar(groups) {
 const items = [{ text: '概览', link: '/api/' }]
 for (const tag of Object.keys(groups).sort) {
 items.push({ text: tag, link: `/api/${tag}` })
 }
 const sidebar = [{ text: 'API 参考', items }]
 writeFileSync(SIDEBAR_PATH, JSON.stringify(sidebar, null, 2), 'utf-8')
}
// ---- 主流程 ----
function main {
 mkdirSync(API_DIR, { recursive: true })
 const schema = loadSchema
 const groups = groupByTag(schema)
 // 为每个 tag 生成独立页面
 for (const [tag, endpoints] of Object.entries(groups)) {
 const content = renderTagPage(tag, endpoints, schema)
 writeFileSync(join(API_DIR, `${tag}.md`), content, 'utf-8')
 }
 // 生成侧边栏配置
 generateSidebar(groups)
 // 生成 API 参考首页
 const tagLinks = Object.keys(groups)
 .sort
 .map((tag) => `- [${tag}](/api/${tag}) — ${groups[tag].length} 个端点`)
 .join('\n')
 const indexContent = `---
title: API 参考
---
# API 参考
本文档从 OpenAPI Schema 自动生成，与服务端代码保持同步。
## 端点分组
${tagLinks}:: tip 更新 API 文档
运行以下命令重新生成 schema 并更新文档：
\`\`\`bash
cd server && python manage.py spectacular --color --file ../docs/public/schema.json
cd .. && node docs/scripts/generate-api-docs.mjs
\`\`\`::
`
 writeFileSync(join(API_DIR, 'index.md'), indexContent, 'utf-8')
 console.log(`API 文档生成完成: ${Object.keys(groups).length} 个分组`)
}
main
