/**
 * Friday MCP 配置解析。
 *
 * 解析优先级：环境变量（FRIDAY_BASE_URL / FRIDAY_ACCESS_TOKEN）优先，
 * 回落到用户级配置文件 ~/.friday/config.json（{"baseUrl", "accessToken"}）。
 *
 * 安全约束：accessToken（PAT）绝不写入日志 / 错误信息 / 工具返回文本；
 * 配置文件以 0600 权限写入（仅当前用户可读写）。
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export interface FridayConfig {
  baseUrl: string
  accessToken: string
}

export const CONFIG_DIR = path.join(os.homedir(), '.friday')
export const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json')

/** 缺配置时给 agent / 用户看的提示文案（不含任何敏感值）。 */
export const MISSING_CONFIG_MESSAGE
  = 'Friday MCP 未配置。请运行: npx -y @friday-ai/mcp init --base-url <Friday 实例地址> --token <访问令牌>\n'
    + '访问令牌在 Friday Web 控制台「个人资料 → 访问令牌」创建。\n'
    + '也可以通过环境变量 FRIDAY_BASE_URL / FRIDAY_ACCESS_TOKEN 配置。'

/** 规范化 base URL：去尾部斜杠；仅接受 http/https。 */
export function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '')
  let parsed: URL
  try {
    parsed = new URL(trimmed)
  }
  catch {
    throw new Error(`无效的 Friday 地址: ${trimmed}`)
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:')
    throw new Error(`Friday 地址必须是 http/https: ${trimmed}`)
  return trimmed
}

function readConfigFile(filePath: string): Partial<FridayConfig> {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
    const parsed = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null)
      return {}
    return {
      baseUrl: typeof parsed.baseUrl === 'string' ? parsed.baseUrl : undefined,
      accessToken: typeof parsed.accessToken === 'string' ? parsed.accessToken : undefined,
    }
  }
  catch {
    // 文件不存在 / JSON 损坏一律视为未配置，由调用方给出统一引导
    return {}
  }
}

/**
 * 解析配置。env 优先（便于 mcp.json 内联覆盖与 CI），文件回落。
 * 返回 null 表示未配置（而不是抛错），由工具层返回结构化引导信息。
 */
export function resolveConfig(
  env: NodeJS.ProcessEnv = process.env,
  configFile: string = CONFIG_FILE,
): FridayConfig | null {
  const fileConfig = readConfigFile(configFile)
  const baseUrl = env.FRIDAY_BASE_URL?.trim() || fileConfig.baseUrl?.trim() || ''
  const accessToken = env.FRIDAY_ACCESS_TOKEN?.trim() || fileConfig.accessToken?.trim() || ''
  if (!baseUrl || !accessToken)
    return null
  try {
    return { baseUrl: normalizeBaseUrl(baseUrl), accessToken }
  }
  catch {
    return null
  }
}

/** 写入用户级配置文件（目录 0700、文件 0600，PAT 明文落盘的最小暴露面）。 */
export function writeConfig(
  config: FridayConfig,
  configFile: string = CONFIG_FILE,
): void {
  const dir = path.dirname(configFile)
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 })
  fs.writeFileSync(
    configFile,
    `${JSON.stringify({ baseUrl: config.baseUrl, accessToken: config.accessToken }, null, 2)}\n`,
    { mode: 0o600 },
  )
}
