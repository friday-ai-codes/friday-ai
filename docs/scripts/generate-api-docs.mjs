import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const SCHEMA_PATH = join(__dirname, '..', 'public', 'schema.json')
const API_DIR = join(__dirname, '..', 'api')
const SIDEBAR_PATH = join(__dirname, '..', '.vitepress', 'api-sidebar.json')
const HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete']

function loadSchema() {
  if (!existsSync(SCHEMA_PATH)) {
    console.error(
      'Generate schema first: cd server && python manage.py spectacular --color --file ../docs/public/schema.json',
    )
    process.exit(1)
  }

  return JSON.parse(readFileSync(SCHEMA_PATH, 'utf-8'))
}

function resolveRef(ref, schema) {
  const parts = ref.replace(/^#\//, '').split('/')
  let current = schema

  for (const part of parts) {
    current = current?.[part]
    if (current === undefined) return undefined
  }

  return current
}

function resolveSchema(obj, rootSchema, depth = 0) {
  if (!obj || typeof obj !== 'object' || depth > 5) return obj

  if (obj.$ref) {
    const resolved = resolveRef(obj.$ref, rootSchema)
    return resolved ? resolveSchema(resolved, rootSchema, depth + 1): obj
  }

  if (obj.type === 'array' && obj.items) {
    return {...obj,
      items: resolveSchema(obj.items, rootSchema, depth + 1),
    }
  }

  if (obj.properties) {
    const resolved = {...obj, properties: {} }
    for (const [key, value] of Object.entries(obj.properties)) {
      resolved.properties[key] = resolveSchema(value, rootSchema, depth + 1)
    }
    return resolved
  }

  for (const combiner of ['allOf', 'oneOf', 'anyOf']) {
    if (Array.isArray(obj[combiner])) {
      return {...obj,
        [combiner]: obj[combiner].map((item) =>
          resolveSchema(item, rootSchema, depth + 1),
        ),
      }
    }
  }

  return obj
}

function groupByTag(schema) {
  const groups = {}

  for (const [path, pathItem] of Object.entries(schema.paths || {})) {
    for (const method of HTTP_METHODS) {
      const operation = pathItem[method]
      if (!operation) continue

      const tag = operation.tags?.[0] || 'other'
      if (!groups[tag]) groups[tag] = []
      groups[tag].push({
        path,
        method: method.toUpperCase(),
        summary: operation.summary || '',
        description: operation.description || '',
        parameters: operation.parameters || [],
        requestBody: operation.requestBody || null,
        responses: operation.responses || {},
      })
    }
  }

  return groups
}

function renderSchemaProperties(schema) {
  if (!schema?.properties) return ''

  const lines = ['```json', '{']
  const entries = Object.entries(schema.properties)

  for (let index = 0; index < entries.length; index += 1) {
    const [key, prop] = entries[index]
    const comma = index < entries.length - 1 ? ',': ''
    const type = prop.type || 'object'

    if (type === 'array') {
      const itemType = prop.items?.type || 'object'
      lines.push(`  "${key}": ["${itemType}"]${comma}`)
    } else {
      lines.push(`  "${key}": "${type}"${comma}`)
    }
  }

  lines.push('}', '```')
  return lines.join('\n')
}

function renderEndpoint(endpoint, rootSchema) {
  const lines = [`### ${endpoint.method} \`${endpoint.path}\``, '']

  if (endpoint.summary) {
    lines.push(`**${endpoint.summary}**`, '')
  }

  if (endpoint.description) {
    lines.push(endpoint.description, '')
  }

  if (endpoint.parameters.length > 0) {
    lines.push('#### Parameters', '')
    lines.push('| Name | Location | Type | Required | Description |')
    lines.push('| --- | --- | --- | --- | --- |')

    for (const param of endpoint.parameters) {
      const type = param.schema?.type || 'string'
      const required = param.required ? 'yes': 'no'
      const description = String(param.description || '-').replace(/\|/g, '\\|')
      lines.push(`| ${param.name} | ${param.in} | ${type} | ${required} | ${description} |`)
    }

    lines.push('')
  }

  if (endpoint.requestBody) {
    const content = endpoint.requestBody.content?.['application/json']
    if (content?.schema) {
      const rendered = renderSchemaProperties(resolveSchema(content.schema, rootSchema))
      if (rendered) {
        lines.push('#### Request Body', '')
        lines.push(rendered, '')
      }
    }
  }

  if (Object.keys(endpoint.responses).length > 0) {
    lines.push('#### Responses', '')

    for (const [code, response] of Object.entries(endpoint.responses)) {
      lines.push(`- **${code}**: ${response.description || ''}`)
      const content = response.content?.['application/json']
      if (content?.schema) {
        const rendered = renderSchemaProperties(resolveSchema(content.schema, rootSchema))
        if (rendered) lines.push('', rendered)
      }
    }

    lines.push('')
  }

  return lines.join('\n')
}

function renderTagPage(tag, endpoints, rootSchema) {
  const lines = ['---', `title: ${tag} API`, '---', '', `# ${tag}`, '']

  for (let index = 0; index < endpoints.length; index += 1) {
    lines.push(renderEndpoint(endpoints[index], rootSchema))
    if (index < endpoints.length - 1) lines.push('---', '')
  }

  return lines.join('\n')
}

function generateSidebar(groups) {
  const items = [{ text: 'Overview', link: '/api/' }]

  for (const tag of Object.keys(groups).sort()) {
    items.push({ text: tag, link: `/api/${tag}` })
  }

  writeFileSync(
    SIDEBAR_PATH,
    JSON.stringify([{ text: 'API Reference', items }], null, 2),
    'utf-8',
  )
}

function main() {
  mkdirSync(API_DIR, { recursive: true })

  const schema = loadSchema()
  const groups = groupByTag(schema)

  for (const [tag, endpoints] of Object.entries(groups)) {
    writeFileSync(join(API_DIR, `${tag}.md`), renderTagPage(tag, endpoints, schema), 'utf-8')
  }

  generateSidebar(groups)

  const tagLinks = Object.keys(groups).sort().map((tag) => `- [${tag}](/api/${tag}) - ${groups[tag].length} endpoints`).join('\n')

  const indexContent = `---
title: API Reference
---

# API Reference

This section is generated from the OpenAPI schema.

## Endpoint Groups

${tagLinks}

## Refresh API Docs

\`\`\`bash
cd server && python manage.py spectacular --color --file ../docs/public/schema.json
cd .. && node docs/scripts/generate-api-docs.mjs
\`\`\`
`

  writeFileSync(join(API_DIR, 'index.md'), indexContent, 'utf-8')
  console.log(`Generated API docs for ${Object.keys(groups).length} groups.`)
}

main()
