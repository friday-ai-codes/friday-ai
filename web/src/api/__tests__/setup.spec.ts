import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const postMock = vi.fn()

vi.mock('~/api/client', () => ({
  get: (url: string) => getMock(url),
  post: (url: string, body?: unknown) => postMock(url, body),
}))

const { getSetupStatus, initSetup, setupProvider, getSecurityCheck, setupFeishu, setupRag } = await import('~/api/setup')

beforeEach(() => {
  vi.clearAllMocks()
})

describe('getSetupStatus', () => {
  it('returns status from backend', async () => {
    getMock.mockResolvedValueOnce({ needs_setup: true, is_initialized: false })

    const result = await getSetupStatus()

    expect(result.needs_setup).toBe(true)
    expect(result.is_initialized).toBe(false)
    expect(getMock).toHaveBeenCalledWith('/auth/setup/status/')
  })

  it('rejects on network error', async () => {
    getMock.mockRejectedValueOnce(new Error('Network Error'))

    await expect(getSetupStatus()).rejects.toThrow('Network Error')
  })
})

describe('initSetup', () => {
  it('calls post with correct path and data', async () => {
    postMock.mockResolvedValueOnce(undefined)

    await initSetup({ username: 'admin', password: 'admin1234' })

    expect(postMock).toHaveBeenCalledWith('/auth/setup/', { username: 'admin', password: 'admin1234' })
  })

  it('rejects when backend returns error', async () => {
    postMock.mockRejectedValueOnce(new Error('Forbidden'))

    await expect(initSetup({ username: 'admin', password: 'admin1234' })).rejects.toThrow('Forbidden')
  })
})

describe('setupProvider', () => {
  it('posts to the wizard endpoint with config payload', async () => {
    postMock.mockResolvedValueOnce({
      id: 'cred-1',
      provider_type: 'anthropic',
      name: 'default',
      scope: 'system',
      default_model: 'claude-sonnet-4-5',
      is_default: true,
      claude_code_bound: true,
    })

    const result = await setupProvider({
      api_key: 'sk-ant-x',
      base_url: 'https://api.anthropic.com',
      model: 'claude-sonnet-4-5',
      context_length: 200000,
      supports_vision: true,
    })

    expect(result.is_default).toBe(true)
    expect(result.claude_code_bound).toBe(true)
    expect(postMock).toHaveBeenCalledWith('/providers/setup-wizard/', {
      api_key: 'sk-ant-x',
      base_url: 'https://api.anthropic.com',
      model: 'claude-sonnet-4-5',
      context_length: 200000,
      supports_vision: true,
    })
  })

  it('propagates backend actionable error', async () => {
    postMock.mockRejectedValueOnce(new Error('连接或鉴权失败：401。请检查 API Key'))

    await expect(
      setupProvider({ api_key: 'bad', base_url: 'https://x', model: 'm' }),
    ).rejects.toThrow('请检查 API Key')
  })
})

describe('getSecurityCheck', () => {
  it('reads the security check endpoint', async () => {
    getMock.mockResolvedValueOnce({
      secure: false,
      secret_key_secure: false,
      encryption_key_set: false,
      keys_independent: false,
      risks: [{ code: 'secret_key_default', level: 'warning' }],
    })

    const result = await getSecurityCheck()

    expect(result.secure).toBe(false)
    expect(result.risks[0].code).toBe('secret_key_default')
    expect(getMock).toHaveBeenCalledWith('/system/security-check/')
  })
})

describe('setupFeishu', () => {
  it('posts feishu credentials to the wizard endpoint', async () => {
    postMock.mockResolvedValueOnce({ feishu_configured: true })

    const result = await setupFeishu({ app_id: 'cli_x', app_secret: 's' })

    expect(result.feishu_configured).toBe(true)
    expect(postMock).toHaveBeenCalledWith('/system/setup-feishu/', { app_id: 'cli_x', app_secret: 's' })
  })
})

describe('setupRag', () => {
  it('posts rag config to the wizard endpoint', async () => {
    postMock.mockResolvedValueOnce({ rag_configured: true, written_keys: ['qdrant_url'] })

    const result = await setupRag({ qdrant_url: 'http://qdrant:6333' })

    expect(result.rag_configured).toBe(true)
    expect(postMock).toHaveBeenCalledWith('/system/setup-rag/', { qdrant_url: 'http://qdrant:6333' })
  })
})
