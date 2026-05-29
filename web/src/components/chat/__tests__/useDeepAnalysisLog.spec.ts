/**
 * useDeepAnalysisLog —— 深度分析日志解码逻辑单测。
 */
import { describe, expect, it } from 'vitest'
import { decorateDeepLog, isLongText, previewText, tryParseToolCall } from '~/composables/useDeepAnalysisLog'
describe('useDeepAnalysisLog', => {
 it('decorateDeepLog 把 [思考] 文本归一为 thinking', => {
 const v = decorateDeepLog({ type: 'text', content: '[思考] 我在想' })!
 expect(v.kind).toBe('thinking')
 expect(v.label).toBe('思考')
 expect(v.text).toBe('我在想')
 })
 it('decorateDeepLog 解析 tool_call → 中文名 + 结构化 detailValue', => {
 const v = decorateDeepLog({ type: 'tool_call', content: 'Read({"file_path": "a.py"})' })!
 expect(v.kind).toBe('tool')
 expect(v.label).toBe('读取文件')
 expect(v.text).toBe('a.py')
 expect(v.toolName).toBe('Read')
 expect(v.detailValue).toEqual({ file_path: 'a.py' })
 expect(v.expandable).toBe(true)
 })
 it('decorateDeepLog 过滤 SDK 噪音 block', => {
 expect(decorateDeepLog({ type: 'block', content: 'ThinkingBlock' })).toBeNull
 })
 it('decorateDeepLog result 抽取费用', => {
 const v = decorateDeepLog({ type: 'result', content: 'done cost=$0.02 tokens=10' })!
 expect(v.kind).toBe('result')
 expect(v.text).toContain('$0.02')
 })
 it('isLongText / previewText 行为', => {
 expect(isLongText('short')).toBe(false)
 expect(isLongText('a'.repeat(200))).toBe(true)
 expect(isLongText('line1\nline2')).toBe(true)
 expect(previewText('line1\nline2')).toBe('line1')
 })
 it('tryParseToolCall 非工具调用返回 null', => {
 expect(tryParseToolCall('just text')).toBeNull
 })
})
