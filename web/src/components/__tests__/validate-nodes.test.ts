import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const scriptPath = path.resolve(__dirname, '../../../scripts/validate-node-definitions.ts')

describe('validate-node-definitions 脚本验证', () => {
  it('validate-node-definitions.ts 脚本文件应存在', () => {
    expect(fs.existsSync(scriptPath)).toBe(true)
  })

  it('脚本应包含 node-types API 调用', () => {
    const content = fs.readFileSync(scriptPath, 'utf-8')
    expect(content).toContain('node-types')
  })

  it('脚本应使用正确的 /api/node-types/ 路径（不含 workflows/node-types）', () => {
    const content = fs.readFileSync(scriptPath, 'utf-8')
    expect(content).toContain('/api/node-types/')
    expect(content).not.toContain('workflows/node-types')
  })

  it('脚本应包含 3-layer 验证逻辑', () => {
    const content = fs.readFileSync(scriptPath, 'utf-8')
    expect(content).toContain('ui_schema')
    expect(content).toContain('config_schema')
  })

  it('脚本应区分连接失败和节点不一致', () => {
    const content = fs.readFileSync(scriptPath, 'utf-8')
    const hasConnectionHandling = content.includes('ECONNREFUSED') || content.includes('Backend not running')
    expect(hasConnectionHandling).toBe(true)
  })
})
