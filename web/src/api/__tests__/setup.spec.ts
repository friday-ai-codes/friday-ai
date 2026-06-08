import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const postMock = vi.fn()

vi.mock('~/api/client', () => ({
  get: (url: string) => getMock(url),
  post: (url: string, body?: unknown) => postMock(url, body),
}))

const { getSetupStatus, initSetup } = await import('~/api/setup')

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
