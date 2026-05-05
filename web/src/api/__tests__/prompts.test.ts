import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import fixture from './__fixtures__/prompt-preview-error.json'
// ============================================================================
// mock client.ts —— 所有被测 HTTP 函数都转调 get/post/patch/del
// ============================================================================
const getMock = vi.fn
const postMock = vi.fn
const patchMock = vi.fn
const delMock = vi.fn
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
 ApiError: MockApiError,
}))
// 必须在 vi.mock 之后 import 被测模块
const { promptsApi, PromptVariableMissingError } = await import('~/api/prompts')
beforeEach( => {
 vi.clearAllMocks
})
afterEach( => {
 vi.restoreAllMocks
})
// ============================================================================
// Tests
// ============================================================================
describe('promptsApi.list', => {
 it('测试 1: scope=system 时调 GET /prompts/?scope=system', async => {
 getMock.mockResolvedValueOnce
 await promptsApi.list({ scope: 'system' })
 expect(getMock).toHaveBeenCalledWith('/prompts/', { scope: 'system' })
 })
 it('测试 2: scope=project + project_id 时传两个 query 参数', async => {
 getMock.mockResolvedValueOnce
 await promptsApi.list({
 scope: 'project',
 project_id: '11111111-1111-1111-1111-111111111111',
 })
 expect(getMock).toHaveBeenCalledWith('/prompts/', {
 scope: 'project',
 project_id: '11111111-1111-1111-1111-111111111111',
 })
 })
 it('测试 3: 携带 category 时合并进 query', async => {
 getMock.mockResolvedValueOnce
 await promptsApi.list({ scope: 'system', category: 'chat_agent' })
 expect(getMock).toHaveBeenCalledWith('/prompts/', {
 scope: 'system',
 category: 'chat_agent',
 })
 })
})
describe('promptsApi.get', => {
 it('测试 4: 调 GET /prompts/<id>/ 返回 PromptDetail', async => {
 const detail = { id: 'abc', slug: 'foo', category: 'ai_node' }
 getMock.mockResolvedValueOnce(detail)
 const result = await promptsApi.get('abc')
 // mock 包装把 params=undefined 也传入，断言时匹配 (url, undefined)
 expect(getMock).toHaveBeenCalledWith('/prompts/abc/', undefined)
 expect(result).toEqual(detail)
 })
})
describe('promptsApi.create', => {
 it('测试 5: 调 POST /prompts/ 传 payload JSON', async => {
 const payload = {
 slug: 'test.slug',
 category: 'ai_node' as const,
 scope: 'system' as const,
 title: '测试',
 description: '',
 body: '{{name}}',
 variables_schema: {},
 change_note: '',
 }
 postMock.mockResolvedValueOnce({ id: 'new-id' })
 await promptsApi.create(payload)
 expect(postMock).toHaveBeenCalledWith('/prompts/', payload)
 })
})
describe('promptsApi.update', => {
 it('测试 6: 调 PATCH /prompts/<id>/ 传部分 payload', async => {
 patchMock.mockResolvedValueOnce({ id: 'abc' })
 await promptsApi.update('abc', { body: '新 body' })
 expect(patchMock).toHaveBeenCalledWith('/prompts/abc/', { body: '新 body' })
 })
})
describe('promptsApi.delete', => {
 it('测试 7: 调 DELETE /prompts/<id>/ 返回 void', async => {
 delMock.mockResolvedValueOnce(undefined)
 const result = await promptsApi.delete('abc')
 expect(delMock).toHaveBeenCalledWith('/prompts/abc/')
 expect(result).toBeUndefined
 })
})
describe('promptsApi.preview', => {
 it('测试 8: 成功路径调 POST /prompts/<id>/preview/ body={variables:...}', async => {
 postMock.mockResolvedValueOnce({ rendered: 'Hi Alice' })
 const result = await promptsApi.preview('abc', { name: 'Alice' })
 expect(postMock).toHaveBeenCalledWith('/prompts/abc/preview/', {
 variables: { name: 'Alice' },
 })
 expect(result).toEqual({ rendered: 'Hi Alice' })
 })
 it('测试 9: 422 响应抛 PromptVariableMissingError，带 slug + missing', async => {
 // 第一次 post 抛 ApiError(422) 触发 fallback path
 postMock.mockRejectedValueOnce(new MockApiError(422, 'prompt_variable_missing'))
 // fetchPreviewDirect 通过 globalThis.fetch 重新读 body
 const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
 new Response(JSON.stringify(fixture), {
 status: 422,
 headers: { 'Content-Type': 'application/json' },
 }),
 )
 try {
 await promptsApi.preview('abc', {})
 throw new Error('expected to throw PromptVariableMissingError')
 }
 catch (e) {
 expect(e).toBeInstanceOf(PromptVariableMissingError)
 const err = e as InstanceType<typeof PromptVariableMissingError>
 expect(err.slug).toBe(fixture.slug)
 expect(err.missing).toEqual(fixture.missing)
 }
 finally {
 fetchSpy.mockRestore
 }
 })
})
describe('promptsApi.listVersions', => {
 it('测试 10: 调 GET /prompts/<id>/versions/', async => {
 getMock.mockResolvedValueOnce
 await promptsApi.listVersions('abc')
 expect(getMock).toHaveBeenCalledWith('/prompts/abc/versions/', undefined)
 })
})
describe('promptsApi.activateVersion', => {
 it('测试 11: 调 POST /prompts/<id>/activate/<version-id>/ 返回 PromptDetail', async => {
 postMock.mockResolvedValueOnce({ id: 'abc' })
 await promptsApi.activateVersion('abc', 'v-uuid')
 expect(postMock).toHaveBeenCalledWith('/prompts/abc/activate/v-uuid/', undefined)
 })
})
