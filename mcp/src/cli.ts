/**
 * friday-mcp CLI 入口。
 *
 * - 无参数：启动 stdio MCP server（供 Cursor / Claude Code / Codex 调用）
 * - init：写入用户级配置 ~/.friday/config.json 并校验连通性
 *
 * init 输出走 stderr 之外的 stdout 是安全的（init 模式下无 MCP 协议流）；
 * server 模式下绝不向 stdout 打印任何非协议内容。
 */

import process from 'node:process'
import { CONFIG_FILE, normalizeBaseUrl, resolveConfig, writeConfig } from './config.js'
import { runStdioServer } from './server.js'

function parseInitArgs(argv: string[]): { baseUrl?: string, token?: string } {
  const out: { baseUrl?: string, token?: string } = {}
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--base-url')
      out.baseUrl = argv[++i]
    else if (arg === '--token')
      out.token = argv[++i]
  }
  return out
}

async function checkHealth(baseUrl: string): Promise<boolean> {
  try {
    const resp = await fetch(`${baseUrl}/health`, { signal: AbortSignal.timeout(10_000) })
    return resp.ok
  }
  catch {
    return false
  }
}

async function runInit(argv: string[]): Promise<number> {
  const { baseUrl: rawBaseUrl, token } = parseInitArgs(argv)
  if (!rawBaseUrl || !token) {
    console.error('用法: friday-mcp init --base-url <Friday 实例地址> --token <访问令牌>')
    console.error('访问令牌在 Friday Web 控制台「个人资料 → 访问令牌」创建（明文只显示一次）。')
    return 1
  }

  let baseUrl: string
  try {
    baseUrl = normalizeBaseUrl(rawBaseUrl)
  }
  catch (e) {
    console.error(e instanceof Error ? e.message : String(e))
    return 1
  }

  writeConfig({ baseUrl, accessToken: token })
  console.log(`已写入 ${CONFIG_FILE}（权限 0600）`)

  const healthy = await checkHealth(baseUrl)
  if (healthy) {
    console.log(`连通性正常: ${baseUrl}/health`)
  }
  else {
    console.warn(`警告: 无法访问 ${baseUrl}/health —— 配置已保存，请确认地址可达（内网 / VPN / 端口）。`)
  }

  console.log('下一步: 在你的 IDE 注册 MCP server，例如 Claude Code:')
  console.log('  claude mcp add friday -- npx -y @friday-ai/mcp')
  console.log('Cursor 则在 .cursor/mcp.json 加入 {"friday": {"command": "npx", "args": ["-y", "@friday-ai/mcp"]}}')
  return 0
}

async function main(): Promise<void> {
  const [, , command, ...rest] = process.argv

  if (command === 'init') {
    process.exitCode = await runInit(rest)
    return
  }

  if (command === 'doctor') {
    const config = resolveConfig()
    if (!config) {
      console.error('未配置。运行: friday-mcp init --base-url <地址> --token <令牌>')
      process.exitCode = 1
      return
    }
    console.log(`baseUrl: ${config.baseUrl}`)
    console.log(`token: 已配置（${config.accessToken.length} 字符，不回显）`)
    const healthy = await checkHealth(config.baseUrl)
    console.log(healthy ? '连通性正常' : '连通性异常：/health 不可达')
    process.exitCode = healthy ? 0 : 1
    return
  }

  if (command && command !== 'serve') {
    console.error(`未知命令: ${command}（可用: init / doctor / serve）`)
    process.exitCode = 1
    return
  }

  await runStdioServer()
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : String(e))
  process.exit(1)
})
