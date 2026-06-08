import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const postMock = vi.fn()

vi.mock('~/api/client', () => ({
  get: (url: string) => getMock(url),
  post: (url: string, body?: unknown) => postMock(url, body),
}))

const { getSetupStatus, initSetup, setupProvider } = await import('~/api/setup')

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
