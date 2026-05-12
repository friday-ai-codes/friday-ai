import { beforeEach, describe, expect, it, vi } from 'vitest'
const getMock = vi.fn
const postMock = vi.fn
const patchMock = vi.fn
const delMock = vi.fn
const uploadMock = vi.fn
class MockApiError extends Error {
 constructor(public status: number, public detail: string) {
 super(detail)
 this.name = 'ApiError'
 }
}
vi.mock('~/api/client', => ({
 get: (url: string, params?: unknown) => getMock(url, params),
 post: (url: string, body?: unknown) => postMock(url, body),
 patch: (url: string, body?: unknown) => patchMock(url, body),
 del: (url: string) => delMock(url),
 upload: (url: string, body?: unknown) => uploadMock(url, body),
 ApiError: MockApiError,
}))
const { repositoriesApi } = await import('~/api/repositories')
beforeEach( => {
 vi.clearAllMocks
})
describe('repositoriesApi.getIndexHistory', => {
 it('将分页和状态筛选作为 query params 传给 client.get', async => {
 getMock.mockResolvedValueOnce({ total: 0, items: })
 await repositoriesApi.getIndexHistory(
 '48338acf-35d3-4b44-abfc-c8946113529e',
 { limit: 5, offset: 10, status: 'failed' },
 )
 expect(getMock).toHaveBeenCalledWith(
 '/repositories/48338acf-35d3-4b44-abfc-c8946113529e/index/history/',
 { limit: 5, offset: 10, status: 'failed' },
 )
 })
})
