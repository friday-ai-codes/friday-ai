/**
 * 分支名解析与校验 composable
 *
 * 前端轻量校验 + 分支名解析/拼接。后端权威校验以 server/chat/branch_service.py 为准。
 * 正则模式复用后端 _VALID_BRANCH_CHARS 规则。
 */
const BRANCH_PATTERN = /^(feat|fix|chore)(\d{8})\.(.+)$/
const VALID_SHORT_DESC_CHARS = /^[\w.\-]+$/
export interface ParsedBranchName {
 type: 'feat' | 'fix' | 'chore'
 date: string
 shortDesc: string
}
export interface ValidationResult {
 valid: boolean
 error?: string
}
export function useBranchValidation {
 function parseBranchName(name: string): ParsedBranchName | null {
 const match = name.match(BRANCH_PATTERN)
 if (!match)
 return null
 return {
 type: match[1] as 'feat' | 'fix' | 'chore',
 date: match[2],
 shortDesc: match[3],
 }
 }
 function buildBranchName(type: string, date: string, shortDesc: string): string {
 return `${type}${date}.${shortDesc}`
 }
 function validateShortDesc(desc: string): ValidationResult {
 if (!desc.trim)
 return { valid: false, error: '描述不能为空' }
 if (!VALID_SHORT_DESC_CHARS.test(desc))
 return { valid: false, error: '只允许英文字母、数字、点、中划线' }
 // 用 feat 前缀估算最大长度（最短类型 + 8 位日期 + 点 + 描述）
 const fullLength = new TextEncoder.encode(`feat00000000.${desc}`).length
 if (fullLength > 255)
 return { valid: false, error: '分支名超过最大长度' }
 return { valid: true }
 }
 return { parseBranchName, buildBranchName, validateShortDesc }
}
