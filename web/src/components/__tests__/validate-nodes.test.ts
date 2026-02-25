import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
const scriptPath = path.resolve(__dirname, '../../../scripts/validateNodeTypes.ts')
describe('validateNodeTypes 脚本验证', => {
 it('validateNodeTypes.ts 脚本文件应存在', => {
 expect(fs.existsSync(scriptPath)).toBe(true)
 })
 it('脚本应包含 node-types API 调用', => {
 const content = fs.readFileSync(scriptPath, 'utf-8')
 expect(content).toContain('node-types')
 })
 it('脚本应包含三文件解析逻辑', => {
 const content = fs.readFileSync(scriptPath, 'utf-8')
 expect(content).toContain('nodeTypeMapping')
 expect(content).toContain('NodePalette')
 })
 it('脚本应区分连接失败和节点不一致', => {
 const content = fs.readFileSync(scriptPath, 'utf-8')
 const hasConnectionHandling = content.includes('ECONNREFUSED') || content.includes('Backend not running')
 expect(hasConnectionHandling).toBe(true)
 })
})
