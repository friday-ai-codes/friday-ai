/**
 * Friday 工具令牌绑定（Tool Token Binding）管理 DTO
 *
 * 与后端 server/tools/serializers.py 中的 ToolTokenBindingSerializer /
 * BoundTokenSerializer / BindableToolSerializer 字段一一对应。
 *
 * 安全契约（T-10-05）：绑定相关 DTO 永不含令牌明文 / token_hash；
 * 令牌仅以 name + 前后缀指纹 + is_valid 元数据呈现（见 BoundTokenDto）。
 */

/**
 * 绑定中引用的令牌元数据（绝不含明文 / token_hash）。
 *
 * 与后端 BoundTokenSerializer 白名单字段一一对应：仅指纹用于 UI 识别。
 */
export interface BoundTokenDto {
  id: string
  name: string
  /** 明文前缀，供 UI 指纹识别（非完整明文）。 */
  token_prefix: string
  /** 明文后 4 字符，供 UI 指纹识别（非完整明文）。 */
  token_suffix: string
  /** 后端计算：未吊销且未过期。 */
  is_valid: boolean
}

/** 一条工具→令牌绑定（仅元数据，明文绝不出现）。 */
export interface ToolBindingDto {
  id: number
  remote_tool: number
  remote_tool_name: string
  remote_tool_source: 'mcp' | 'skill'
  access_token: BoundTokenDto
  created_at: string
  updated_at: string
}

/** 可绑定工具（仅 mcp / skill，builtin 不入列）。 */
export interface BindableToolDto {
  id: number
  name: string
  description: string
  source: 'mcp' | 'skill'
}

/**
 * POST /api/tools/bindings/ body。
 *
 * access_token 为 AccessToken 的 UUID（仅引用，绝非明文）。
 */
export interface ToolBindingUpsertPayload {
  remote_tool: number
  access_token: string
}
