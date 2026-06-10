/**
 * 配置解析单测：env 优先级、文件回落、缺配置返回 null、0600 写入。
 */

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { normalizeBaseUrl, resolveConfig, writeConfig } from '../src/config.js'

const tmpFiles: string[] = []

function tmpConfigPath(): string {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'friday-mcp-')), 'config.json')
  tmpFiles.push(file)
  return file
}

afterEach(() => {
  for (const file of tmpFiles.splice(0)) {
    fs.rmSync(path.dirname(file), { recursive: true, force: true })
  }
})

describe('resolveConfig', () => {
  it('env 同时具备时直接生效（不读文件）', () => {
    const config = resolveConfig(
      { FRIDAY_BASE_URL: 'https://friday.internal/', FRIDAY_ACCESS_TOKEN: 'pat-1' },
      '/nonexistent/config.json',
    )
    expect(config).toEqual({ baseUrl: 'https://friday.internal', accessToken: 'pat-1' })
  })

  it('env 缺失时回落到配置文件', () => {
    const file = tmpConfigPath()
    fs.writeFileSync(file, JSON.stringify({ baseUrl: 'http://10.0.0.5:10240', accessToken: 'pat-file' }))
    const config = resolveConfig({}, file)
    expect(config).toEqual({ baseUrl: 'http://10.0.0.5:10240', accessToken: 'pat-file' })
  })

  it('env 与文件可混合：env 提供 token，文件提供 baseUrl', () => {
    const file = tmpConfigPath()
    fs.writeFileSync(file, JSON.stringify({ baseUrl: 'http://10.0.0.5:10240' }))
    const config = resolveConfig({ FRIDAY_ACCESS_TOKEN: 'pat-env' }, file)
    expect(config).toEqual({ baseUrl: 'http://10.0.0.5:10240', accessToken: 'pat-env' })
  })

  it('完全无配置时返回 null（不抛错）', () => {
    expect(resolveConfig({}, '/nonexistent/config.json')).toBeNull()
  })

  it('配置文件损坏（非 JSON）视为未配置', () => {
    const file = tmpConfigPath()
    fs.writeFileSync(file, 'not json{{{')
    expect(resolveConfig({}, file)).toBeNull()
  })

  it('非 http/https 地址视为未配置', () => {
    expect(
      resolveConfig({ FRIDAY_BASE_URL: 'ftp://x', FRIDAY_ACCESS_TOKEN: 'pat' }, '/nonexistent'),
    ).toBeNull()
  })
})

describe('normalizeBaseUrl', () => {
  it('去除尾部斜杠', () => {
    expect(normalizeBaseUrl('https://friday.internal///')).toBe('https://friday.internal')
  })

  it('拒绝非法 URL', () => {
    expect(() => normalizeBaseUrl('not a url')).toThrow()
  })

  it('拒绝非 http/https scheme', () => {
    expect(() => normalizeBaseUrl('javascript:alert(1)')).toThrow()
  })
})

describe('writeConfig', () => {
  it('写入 JSON 且权限为 0600', () => {
    const file = tmpConfigPath()
    fs.rmSync(path.dirname(file), { recursive: true, force: true })
    writeConfig({ baseUrl: 'https://friday.internal', accessToken: 'pat-w' }, file)

    const parsed = JSON.parse(fs.readFileSync(file, 'utf-8'))
    expect(parsed).toEqual({ baseUrl: 'https://friday.internal', accessToken: 'pat-w' })

    const mode = fs.statSync(file).mode & 0o777
    expect(mode).toBe(0o600)
  })
})
