import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()
const postMock = vi.fn()

class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail)
    this.name = 'ApiError'
  }
}

vi.mock('~/api/client', () => ({
  get: (url: string, params?: unknown) => getMock(url, params),
  post: (url: string, body?: unknown) => postMock(url, body),
  patch: vi.fn(),
  del: vi.fn(),
  upload: vi.fn(),
  ApiError: MockApiError,
}))

const { getSymbols, getCallsForSymbol, getImports, getNeighbors } = await import('~/api/codegraph')

const REPO = '48338acf-35d3-4b44-abfc-c8946113529e'

beforeEach(() => {
  vi.clearAllMocks()
})

describe('codegraph API URL 构造', () => {
  it('getSymbols 不把 query 拼进 path，而是通过 params 传给 client.get', async () => {
    getMock.mockResolvedValueOnce({ count: 0, offset: 0, limit: 50, results: [] })

    await getSymbols({ repositoryId: REPO, limit: 50, offset: 0 })

    const [url, params] = getMock.mock.calls[0]
    expect(url).toBe(`/repositories/${REPO}/codegraph/symbols/`)
    expect(url).not.toContain('?')
    expect(params).toMatchObject({ limit: 50, offset: 0 })
  })

  it('getNeighbors 拼对 url 并以 params 传 node_type/id/direction', async () => {
    getMock.mockResolvedValueOnce({ node_type: 'file', direction: 'both', nodes: [], edges: [] })

    await getNeighbors(REPO, 'file', 'src/a.ts', 'down')

    const [url, params] = getMock.mock.calls[0]
    expect(url).toBe(`/repositories/${REPO}/codegraph/graph/neighbors/`)
    expect(url).not.toContain('?')
    expect(params).toMatchObject({ node_type: 'file', id: 'src/a.ts', direction: 'down' })
  })

  it('getNeighbors direction 默认 both', async () => {
    getMock.mockResolvedValueOnce({ node_type: 'component', direction: 'both', nodes: [], edges: [] })

    await getNeighbors(REPO, 'component', 'abc-id')

    const [, params] = getMock.mock.calls[0]
    expect(params).toMatchObject({ node_type: 'component', id: 'abc-id', direction: 'both' })
  })

  it('getSymbols 多个 symbol_type 通过数组传给 params（client 负责多次 append）', async () => {
    getMock.mockResolvedValueOnce({ count: 0, offset: 0, limit: 50, results: [] })

    await getSymbols({
      repositoryId: REPO,
      symbolTypes: ['FUNCTION', 'CLASS'],
      name: 'foo',
      filePath: 'src/a.py',
    })

    const [url, params] = getMock.mock.calls[0]
    expect(url).toBe(`/repositories/${REPO}/codegraph/symbols/`)
    expect(params).toMatchObject({
      name: 'foo',
      file_path: 'src/a.py',
      symbol_type: ['FUNCTION', 'CLASS'],
    })
  })

  it('getCallsForSymbol 不把 query 拼进 path', async () => {
    getMock.mockResolvedValueOnce({ seed_symbol_id: 'sym', nodes: [], edges: [] })

    await getCallsForSymbol(REPO, 'sym-1', 1, 5)

    const [url, params] = getMock.mock.calls[0]
    expect(url).toBe(`/repositories/${REPO}/codegraph/symbols/sym-1/calls/`)
    expect(url).not.toContain('?')
    expect(params).toMatchObject({ max_per_hop: 5 })
  })

  it('getImports 不把 query 拼进 path', async () => {
    getMock.mockResolvedValueOnce({ count: 0, offset: 0, limit: 50, results: [] })

    await getImports(REPO, { limit: 50, offset: 0, sourceFile: 'src/a.py' })

    const [url, params] = getMock.mock.calls[0]
    expect(url).toBe(`/repositories/${REPO}/codegraph/imports/`)
    expect(url).not.toContain('?')
    expect(params).toMatchObject({ limit: 50, offset: 0, source_file: 'src/a.py' })
  })
})
