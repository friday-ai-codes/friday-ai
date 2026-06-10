/**
 * Friday MCP stdio server。
 *
 * 每个工具调用透传到 POST {baseUrl}/api/mcp/tools/{name}/（Bearer PAT）。
 *
 * 审计串联：会话内记住服务端返回的最新 run_id，后续请求自动带
 * X-Friday-Run-ID，使多步 workflow 在 Friday Interaction Ledger 里
 * 聚合为同一条轨迹。
 *
 * 容错：缺配置 / 401 / 403 / 非 200 / 网络错误一律返回 isError 文本，
 * 绝不抛异常崩掉 stdio 进程；PAT 绝不进入任何返回文本或日志。
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from '@modelcontextprotocol/sdk/types.js'
import type { FridayConfig } from './config.js'
import { MISSING_CONFIG_MESSAGE, resolveConfig } from './config.js'
import { FRIDAY_TOOLS } from './tools.js'

export const SERVER_NAME = 'friday'
export const SERVER_VERSION = '0.1.0'

const REQUEST_TIMEOUT_MS = 120_000

interface ToolCallResult {
  // 索引签名满足 MCP SDK 的 ServerResult 结构要求
  [key: string]: unknown
  content: Array<{ type: 'text', text: string }>
  isError?: boolean
}

function textResult(text: string, isError = false): ToolCallResult {
  return isError
    ? { content: [{ type: 'text', text }], isError: true }
    : { content: [{ type: 'text', text }] }
}

/** 会话级 run_id 状态，独立成类便于测试。 */
export class RunContext {
  runId: string | null = null

  remember(body: unknown): void {
    if (typeof body === 'object' && body !== null) {
      const runId = (body as Record<string, unknown>).run_id
      if (typeof runId === 'string' && runId)
        this.runId = runId
    }
  }
}

/**
 * 执行单次工具调用（导出便于单测，不依赖 MCP transport）。
 */
export async function callFridayTool(
  toolName: string,
  args: Record<string, unknown>,
  runContext: RunContext,
  fetchImpl: typeof fetch = fetch,
  configResolver: () => FridayConfig | null = resolveConfig,
): Promise<ToolCallResult> {
  const config = configResolver()
  if (!config)
    return textResult(MISSING_CONFIG_MESSAGE, true)

  const url = `${config.baseUrl}/api/mcp/tools/${toolName}/`
  const headers: Record<string, string> = {
    'Authorization': `Bearer ${config.accessToken}`,
    'Content-Type': 'application/json',
  }
  if (runContext.runId)
    headers['X-Friday-Run-ID'] = runContext.runId

  let resp: Response
  try {
    resp = await fetchImpl(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(args ?? {}),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    })
  }
  catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    return textResult(`Friday 请求失败（网络 / 超时）: ${message}`, true)
  }

  if (resp.status === 401 || resp.status === 403) {
    return textResult(
      '令牌无效或已失效（401/403）。请在 Friday 个人资料页重新创建访问令牌，'
      + '然后运行: npx -y @friday-ai/mcp init --base-url <地址> --token <新令牌>',
      true,
    )
  }

  let bodyText: string
  try {
    bodyText = await resp.text()
  }
  catch {
    bodyText = ''
  }

  if (!resp.ok)
    return textResult(`Friday 工具 ${toolName} 失败（HTTP ${resp.status}）: ${bodyText.slice(0, 2000)}`, true)

  try {
    const body = JSON.parse(bodyText)
    runContext.remember(body)
    return textResult(JSON.stringify(body, null, 2))
  }
  catch {
    return textResult(`Friday 响应不是 JSON（HTTP ${resp.status}）: ${bodyText.slice(0, 500)}`, true)
  }
}

export function createServer(): Server {
  const server = new Server(
    { name: SERVER_NAME, version: SERVER_VERSION },
    { capabilities: { tools: {} } },
  )
  const runContext = new RunContext()

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: FRIDAY_TOOLS.map(t => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
    })),
  }))

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const { name, arguments: args } = request.params
    const known = FRIDAY_TOOLS.some(t => t.name === name)
    if (!known)
      return textResult(`未知工具: ${name}`, true)
    return callFridayTool(name, (args ?? {}) as Record<string, unknown>, runContext)
  })

  return server
}

export async function runStdioServer(): Promise<void> {
  const server = createServer()
  const transport = new StdioServerTransport()
  await server.connect(transport)
}
