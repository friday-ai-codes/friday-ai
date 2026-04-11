import type { PromptDetail, PromptListItem, PromptVersion } from '~/types/prompts'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
// ============================================================================
// mock ~/api/prompts
// ============================================================================
const listMock = vi.fn
const getMock = vi.fn
const previewMock = vi.fn
const listVersionsMock = vi.fn
const updateMock = vi.fn
const createMock = vi.fn
const deleteMock = vi.fn
const activateMock = vi.fn
vi.mock('~/api/prompts', => ({
 promptsApi: {
 list: (...args: unknown) => listMock(...args),
 get: (...args: unknown) => getMock(...args),
 create: (...args: unknown) => createMock(...args),
 update: (...args: unknown) => updateMock(...args),
 delete: (...args: unknown) => deleteMock(...args),
 preview: (...args: unknown) => previewMock(...args),
 listVersions: (...args: unknown) => listVersionsMock(...args),
 activateVersion: (...args: unknown) => activateMock(...args),
 },
 PromptVariableMissingError: class extends Error {
 constructor(public slug: string, public missing: string) {
 super(`prompt_variable_missing: ${missing.join(', ')}`)
 this.name = 'PromptVariableMissingError'
 }
 },
}))
const { usePromptsStore } = await import('~/stores/prompts')
beforeEach( => {
 setActivePinia(createPinia)
 vi.clearAllMocks
})
// ============================================================================
// Fixtures
// ============================================================================
function makeListItem(overrides: Partial<PromptListItem> = {}): PromptListItem {
 return {
 id: overrides.id ?? 'id-1',
 slug: overrides.slug ?? 'slug.a',
 category: overrides.category ?? 'ai_node',
 scope: overrides.scope ?? 'system',
 project: overrides.project ?? null,
 title: overrides.title ?? 'Title',
 description: overrides.description ?? '',
 is_builtin: overrides.is_builtin ?? false,
 active_version_number: overrides.active_version_number ?? 1,
 created_at: overrides.created_at ?? '2026-04-11T00:00:00Z',
 updated_at: overrides.updated_at ?? '2026-04-11T00:00:00Z',
 }
}
// ============================================================================
// Tests
// ============================================================================
describe('usePromptsStore — actions', => {
 it('测试 1: loadSystemList 调 promptsApi.list({scope:system})', async => {
 const items = [makeListItem({ slug: 'sys.a' })]
 listMock.mockResolvedValueOnce(items)
 const store = usePromptsStore
 await store.loadSystemList
 expect(listMock).toHaveBeenCalledWith({ scope: 'system', category: undefined })
 expect(store.systemList).toEqual(items)
 expect(store.loading).toBe(false)
 })
 it('测试 2: loadSystemList(chat_agent) 携带 category', async => {
 listMock.mockResolvedValueOnce
 const store = usePromptsStore
 await store.loadSystemList('chat_agent')
 expect(listMock).toHaveBeenCalledWith({ scope: 'system', category: 'chat_agent' })
 })
 it('测试 3: loadProjectList 并发 fetch 系统级 + 项目级', async => {
 const sys = [makeListItem({ slug: 's.a' })]
 const proj = [makeListItem({ slug: 's.b', scope: 'project', project: 'proj-1' })]
 listMock.mockResolvedValueOnce(sys).mockResolvedValueOnce(proj)
 const store = usePromptsStore
 await store.loadProjectList('proj-1')
 expect(listMock).toHaveBeenNthCalledWith(1, { scope: 'system' })
 expect(listMock).toHaveBeenNthCalledWith(2, { scope: 'project', project_id: 'proj-1' })
 expect(store.systemList).toEqual(sys)
 expect(store.projectList).toEqual(proj)
 })
 it('测试 4: loadDetail 写入 currentPrompt', async => {
 const detail = { id: 'abc', slug: 's.a' } as PromptDetail
 getMock.mockResolvedValueOnce(detail)
 const store = usePromptsStore
 await store.loadDetail('abc')
 expect(getMock).toHaveBeenCalledWith('abc')
 // Pinia ref 会对对象做 reactive wrap，用 toEqual 做结构比较
 expect(store.currentPrompt).toEqual(detail)
 })
 it('测试 5: loadVersions 写入 versions 数组', async => {
 const versions = [{ id: 'v1', version: 1 }] as PromptVersion
 listVersionsMock.mockResolvedValueOnce(versions)
 const store = usePromptsStore
 await store.loadVersions('abc')
 expect(listVersionsMock).toHaveBeenCalledWith('abc')
 expect(store.versions).toEqual(versions)
 })
 it('测试 6: action 失败时 error 字段被设置且异常上抛', async => {
 listMock.mockRejectedValueOnce(new Error('网络挂了'))
 const store = usePromptsStore
 await expect(store.loadSystemList).rejects.toThrow('网络挂了')
 expect(store.error).toBe('网络挂了')
 expect(store.loading).toBe(false)
 })
})
describe('usePromptsStore — mergedProjectList', => {
 it('测试 7: 三态合并 overridden/fallback/project_only', => {
 const store = usePromptsStore
 store.systemList = [
 makeListItem({ id: 'sys-A', slug: 'slug.a' }),
 makeListItem({ id: 'sys-B', slug: 'slug.b' }),
 makeListItem({ id: 'sys-C', slug: 'slug.c' }),
 ]
 store.projectList = [
 makeListItem({ id: 'proj-B', slug: 'slug.b', scope: 'project', project: 'p1' }),
 makeListItem({ id: 'proj-D', slug: 'slug.d', scope: 'project', project: 'p1' }),
 ]
 const merged = store.mergedProjectList
 // 应有 4 条（A fallback, B overridden, C fallback, D project_only）
 expect(merged).toHaveLength(4)
 const bySlug = new Map(merged.map(m => [m.slug, m]))
 expect(bySlug.get('slug.a')?.status).toBe('fallback')
 expect(bySlug.get('slug.b')?.status).toBe('overridden')
 expect(bySlug.get('slug.c')?.status).toBe('fallback')
 expect(bySlug.get('slug.d')?.status).toBe('project_only')
 })
 it('测试 8: overridden 项保留 project_prompt 字段指向项目级副本', => {
 const store = usePromptsStore
 const sysB = makeListItem({ id: 'sys-B', slug: 'slug.b' })
 const projB = makeListItem({
 id: 'proj-B',
 slug: 'slug.b',
 scope: 'project',
 project: 'p1',
 title: '项目级覆盖',
 })
 store.systemList = [sysB]
 store.projectList = [projB]
 const merged = store.mergedProjectList
 expect(merged).toHaveLength(1)
 expect(merged[0].status).toBe('overridden')
 expect(merged[0].project_prompt?.id).toBe('proj-B')
 expect(merged[0].project_prompt?.title).toBe('项目级覆盖')
 // fallback 态下 project_prompt 应为 null
 store.projectList =
 const merged2 = store.mergedProjectList
 expect(merged2[0].status).toBe('fallback')
 expect(merged2[0].project_prompt).toBeNull
 })
})
