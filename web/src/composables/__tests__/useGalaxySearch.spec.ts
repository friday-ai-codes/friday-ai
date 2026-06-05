/**
 * — useGalaxySearch composable 测试
 */
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGalaxySearch } from '~/composables/useGalaxySearch'

vi.mock('~/api/galaxy', () => ({
  searchGalaxyNodes: vi.fn(),
}))

const { searchGalaxyNodes } = await import('~/api/galaxy')

function makeNode(overrides: Partial<GalaxyNode> = {}): GalaxyNode {
  return {
    id: 'symbol:abc',
    type: 'symbol',
    label: 'MyFunction',
    file_path: 'src/utils.ts',
    repository_id: 'repo-1',
    line_start: 10,
    line_end: 20,
    metadata: {},
    degree: 5,
    ...overrides,
  }
}

function makeResult(overrides: Partial<GalaxySearchResult> = {}): GalaxySearchResult {
  return {
    id: 'symbol:abc',
    type: 'symbol',
    label: 'MyFunction',
    file_path: 'src/utils.ts',
    repository_id: 'repo-1',
    degree: 5,
    ...overrides,
  }
}

describe('useGalaxySearch', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  it('初始状态 results 为空，loading 为 false', () => {
    const { results, loading, error } = useGalaxySearch()
    expect(results.value).toEqual([])
    expect(loading.value).toBe(false)
    expect(error.value).toBeNull()
  })

  it('search() 空查询不调用 API', () => {
    const { search } = useGalaxySearch()
    search('')
    vi.runAllTimers()
    expect(searchGalaxyNodes).not.toHaveBeenCalled()
  })

  it('search() debounce 后调用 searchGalaxyNodes API', async () => {
    const mockResults = [makeResult()]
    vi.mocked(searchGalaxyNodes).mockResolvedValue(mockResults)

    const { results, search } = useGalaxySearch()
    search('MyFunction')
    vi.runAllTimers()
    // 等待 async 回调
    await Promise.resolve()
    await Promise.resolve()

    expect(searchGalaxyNodes).toHaveBeenCalledWith('MyFunction', 20)
    expect(results.value).toEqual(mockResults)
  })

  it('search() 在 API 调用期间设置 loading=true', async () => {
    let resolveSearch!: (v: GalaxySearchResult[]) => void
    vi.mocked(searchGalaxyNodes).mockImplementation(
      () => new Promise(r => (resolveSearch = r)),
    )

    const { loading, search } = useGalaxySearch()
    search('test')
    vi.runAllTimers()

    // 等待 debounce callback 开始执行
    await Promise.resolve()
    expect(loading.value).toBe(true)

    resolveSearch([])
    await Promise.resolve()
    await Promise.resolve()
    expect(loading.value).toBe(false)
  })

  it('aPI 错误时降级并设置 error', async () => {
    vi.mocked(searchGalaxyNodes).mockRejectedValue(new Error('网络错误'))

    const { error, search } = useGalaxySearch()
    search('test')
    vi.runAllTimers()
    await Promise.resolve()
    await Promise.resolve()

    expect(error.value).toBe('网络错误')
  })

  it('searchLocal() 通过 Fuse.js 过滤节点', () => {
    const { searchLocal } = useGalaxySearch()
    const nodes = [
      makeNode({ id: 'a', label: 'UserService' }),
      makeNode({ id: 'b', label: 'OrderService' }),
      makeNode({ id: 'c', label: 'ProductController' }),
    ]

    const results = searchLocal(nodes, 'User')
    expect(results.some(r => r.label === 'UserService')).toBe(true)
  })

  it('searchLocal() 空 query 返回空数组', () => {
    const { searchLocal } = useGalaxySearch()
    const nodes = [makeNode()]
    expect(searchLocal(nodes, '')).toEqual([])
  })

  it('setCorpus() + search() 后端结果先呈现，本地 Fuse 补充不重复', async () => {
    const apiResult = makeResult({ id: 'symbol:api', label: 'ApiFunc' })
    vi.mocked(searchGalaxyNodes).mockResolvedValue([apiResult])

    const nodes = [
      makeNode({ id: 'symbol:api', label: 'ApiFunc' }),
      makeNode({ id: 'symbol:local', label: 'LocalHelper' }),
    ]

    const { results, search, setCorpus } = useGalaxySearch()
    setCorpus(nodes)

    search('func')
    vi.runAllTimers()
    await Promise.resolve()
    await Promise.resolve()

    const ids = results.value.map(r => r.id)
    expect(ids).toContain('symbol:api')
    // 不重复
    expect(ids.filter(id => id === 'symbol:api').length).toBe(1)
  })

  it('多次快速调用 search() 只执行最后一次（debounce）', async () => {
    vi.mocked(searchGalaxyNodes).mockResolvedValue([])

    const { search } = useGalaxySearch()
    search('a')
    search('ab')
    search('abc')
    vi.runAllTimers()
    await Promise.resolve()
    await Promise.resolve()

    // 只调用一次 API（最后一次搜索）
    expect(searchGalaxyNodes).toHaveBeenCalledTimes(1)
    expect(searchGalaxyNodes).toHaveBeenCalledWith('abc', 20)
  })
})
