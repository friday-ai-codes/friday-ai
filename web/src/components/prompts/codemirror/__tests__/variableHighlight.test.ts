import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { extractVariables, PLACEHOLDER_RE, variableHighlight } from '../variableHighlight'
describe('extractVariables', => {
 it('提取单个变量', => {
 expect(extractVariables('{{name}}')).toEqual(['name'])
 })
 it('提取两个变量并字母序排序', => {
 expect(extractVariables('{{ name }} 和 {{ age }}')).toEqual(['age', 'name'])
 })
 it('允许下划线开头的变量名', => {
 expect(extractVariables('{{ _valid }}')).toEqual(['_valid'])
 })
 it('拒绝数字开头的变量名', => {
 expect(extractVariables('{{1invalid}}')).toEqual
 })
 it('对重复变量去重', => {
 expect(extractVariables('{{name}} {{name}} {{name}}')).toEqual(['name'])
 })
 it('空字符串返回空数组', => {
 expect(extractVariables('')).toEqual
 })
 it('连续调用不漏匹配（lastIndex 重置）', => {
 const body = '{{a}} {{b}}'
 expect(extractVariables(body)).toEqual(['a', 'b'])
 // 第二次必须也返回 ['a', 'b']，验证 lastIndex 已重置
 expect(extractVariables(body)).toEqual(['a', 'b'])
 })
})
// eslint-disable-next-line test/prefer-lowercase-title
describe('PLACEHOLDER_RE 契约（防后端 drift）', => {
 it('与后端 server/prompts/services.py _PLACEHOLDER_RE 字符级一致', => {
 // 从 __tests__ 目录向上 6 级到达仓库根：
 // __tests__ -> codemirror -> prompts -> components -> src -> web -> <root>
 const repoRoot = path.resolve(__dirname, '../../../../../..')
 const backendSource = readFileSync(
 path.join(repoRoot, 'server/prompts/services.py'),
 'utf-8',
 )
 // 后端字面量（TypeScript 字符串转义后的 raw regex 表达式）
 const backendPattern = '\\{\\{\\s*([a-zA-Z_][a-zA-Z0-9_]*)\\s*\\}\\}'
 // 断言后端源码包含这个字面量
 expect(backendSource).toContain(backendPattern)
 // 前端 RegExp.source 必须完全等同
 expect(PLACEHOLDER_RE.source).toBe(backendPattern)
 // 全局 flag 必需 —— MatchDecorator 要求 /g
 expect(PLACEHOLDER_RE.flags).toContain('g')
 })
})
describe('variableHighlight extension', => {
 it('返回值可作为 CodeMirror extension 使用（smoke test）', => {
 const ext = variableHighlight
 expect(ext).toBeDefined
 // ViewPlugin.fromClass 返回 ViewPlugin 实例对象
 expect(typeof ext).toBe('object')
 })
})
