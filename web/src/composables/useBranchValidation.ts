/**
 * 分支名解析与校验 composable
 *
 * 前端轻量校验 + 分支名解析/拼接。后端权威校验以 server/chat/branch_service.py 为准。
 * 正则模式复用后端 _VALID_BRANCH_CHARS 规则。
 */

// 分支名格式：{type}/{yymmdd}.{简短名称}，例 feat/260618.修复若干bug
const BRANCH_PATTERN = /^(feat|fix|chore|test)\/(\d{6})\.(.+)$/
// 简短名称允许中文、英文字母、数字、点、中划线、下划线（禁空格）
const VALID_SHORT_DESC_CHARS = /^[\w.\-\u4e00-\u9fff]+$/

export interface ParsedBranchName {
  type: 'feat' | 'fix' | 'chore' | 'test'
  date: string
  shortDesc: string
}

export interface ValidationResult {
  valid: boolean
  error?: string
}

export function useBranchValidation() {
  function parseBranchName(name: string): ParsedBranchName | null {
    const match = name.match(BRANCH_PATTERN)
    if (!match)
      return null
    return {
      type: match[1] as 'feat' | 'fix' | 'chore' | 'test',
      date: match[2],
      shortDesc: match[3],
    }
  }

  function buildBranchName(type: string, date: string, shortDesc: string): string {
    return `${type}/${date}.${shortDesc}`
  }

  function validateShortDesc(desc: string): ValidationResult {
    if (!desc.trim())
      return { valid: false, error: '描述不能为空' }
    if (/\s/.test(desc))
      return { valid: false, error: '分支名不能包含空格' }
    if (!VALID_SHORT_DESC_CHARS.test(desc))
      return { valid: false, error: '只允许中文、英文字母、数字、点、中划线、下划线' }
    // 用 feat 前缀估算最大长度（最短类型 + / + 6 位日期 + 点 + 描述）
    const fullLength = new TextEncoder().encode(`feat/000000.${desc}`).length
    if (fullLength > 255)
      return { valid: false, error: '分支名超过最大长度' }
    return { valid: true }
  }

  return { parseBranchName, buildBranchName, validateShortDesc }
}
