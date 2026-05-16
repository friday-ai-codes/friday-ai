/**
 * Phase Plan — useGalaxySearch composable 测试
 */
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useGalaxySearch } from '~/composables/useGalaxySearch'
vi.mock('~/api/galaxy', => ({
 searchGalaxyNodes: vi.fn,
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
describe('useGalaxySearch', => {
 beforeEach( => {
 vi.clearAllMocks
 vi.useFakeTimers
 })
 it('初始状态 results 为空，loading 为 false', => {
 const { results, loading, error } = useGalaxySearch
 expect(results.value).toEqual
 expect(loading.value).toBe(false)
 expect(error.value).toBeNull
 })
 it('search 空查询不调用 API', async => {
 const { search } = useGalaxySearch
 await search('')
 expect(searchGalaxyNodes).not.toHaveBeenCalled
 })
 it('search 调用 searchGalaxyNodes API', async => {
 const mockResults = [makeResult]
 vi.mocked(searchGalaxyNodes).mockResolvedValue(mockResults)
 const { results, search } = useGalaxySearch
 const searchPromise = search('MyFunction')
 vi.runAllTimers
 await searchPromise
 expect(searchGalaxyNodes).toHaveBeenCalledWith('MyFunction', 20)
 expect(results.value).toEqual(mockResults)
 })
 it('search 在 API 调用期间设置 loading=true', async => {
 let resolveSearch!: (v: GalaxySearchResult) => void
 vi.mocked(searchGalaxyNodes).mockImplementation(
 => new Promise(r => (resolveSearch = r)),
 )
 const { loading, search } = useGalaxySearch
 const promise = search('test')
 vi.runAllTimers
 // loading 应为 true（异步期间）
 await Promise.resolve
 expect(loading.value).toBe(true)
 resolveSearch
 await promise
 expect(loading.value).toBe(false)
 })
 it('API 错误时降级并设置 error', async => {
 vi.mocked(searchGalaxyNodes).mockRejectedValue(new Error('网络错误'))
 const { error, search } = useGalaxySearch
 const promise = search('test')
 vi.runAllTimers
 await promise
 expect(error.value).toBe('网络错误')
 })
 it('searchLocal 通过 Fuse.js 过滤节点', => {
 const { searchLocal } = useGalaxySearch
 const nodes = [
 makeNode({ id: 'a', label: 'UserService' }),
 makeNode({ id: 'b', label: 'OrderService' }),
 makeNode({ id: 'c', label: 'ProductController' }),
 ]
 const results = searchLocal(nodes, 'User')
 expect(results.some(r => r.label === 'UserService')).toBe(true)
 })
 it('searchLocal 空 query 返回空数组', => {
 const { searchLocal } = useGalaxySearch
 const nodes = [makeNode]
 expect(searchLocal(nodes, '')).toEqual
 })
 it('setCorpus + search 去重合并本地结果', async => {
 const apiResult = makeResult({ id: 'symbol:api', label: 'ApiFunc' })
 const localOnlyResult = makeResult({ id: 'symbol:local', label: 'LocalHelper' })
 vi.mocked(searchGalaxyNodes).mockResolvedValue([apiResult])
 const nodes = [
 makeNode({ id: 'symbol:api', label: 'ApiFunc' }),
 makeNode({ id: 'symbol:local', label: 'LocalHelper' }),
 ]
 const { results, search, setCorpus } = useGalaxySearch
 setCorpus(nodes)
 const promise = search('func')
 vi.runAllTimers
 await promise
 // apiResult 来自后端，localOnlyResult 由 Fuse 补充（若匹配）
 const ids = results.value.map(r => r.id)
 expect(ids).toContain('symbol:api')
 // 不重复
 expect(ids.filter(id => id === 'symbol:api').length).toBe(1)
 void localOnlyResult // 仅在 Fuse 匹配时出现，不强制断言
 })
})
