import type { AccessTokenCreateResult, AccessTokenDto } from '~/types/accessToken'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
// ============================================================================
// Mock API client（vi.mock 自动 hoist，store 内 import 会拿到 mock 后的对象）
// ============================================================================
const listMock = vi.fn
const createMock = vi.fn
const revokeMock = vi.fn
vi.mock('~/api/accessTokens', => ({
 accessTokensApi: {
 list: (...args: unknown) => listMock(...args),
 create: (...args: unknown) => createMock(...args),
 revoke: (...args: unknown) => revokeMock(...args),
 },
}))
// dynamic import 保证 vi.mock 已就位后再载入 store
const { useAccessTokenStore } = await import('~/stores/accessTokens')
// ============================================================================
// Fixtures
// ============================================================================
function makeToken(overrides: Partial<AccessTokenDto> = {}): AccessTokenDto {
 return {
 id: overrides.id ?? 'tok-1',
 name: overrides.name ?? 'test',
 token_prefix: overrides.token_prefix ?? 'friday_pat_',
 created_at: overrides.created_at ?? '2026-06-04T00:00:00Z',
 expires_at: overrides.expires_at ?? null,
 revoked_at: overrides.revoked_at ?? null,
 last_used_at: overrides.last_used_at ?? null,
 is_valid: overrides.is_valid ?? true,
 }
}
describe('useAccessTokenStore', => {
 beforeEach( => {
 setActivePinia(createPinia)
 vi.clearAllMocks
 })
 it('createToken_inserts_metadata_without_plaintext', async => {
 const result: AccessTokenCreateResult = {
 ...makeToken({ id: 'new-1', name: 'ci' }),
 token: 'FRIDAY_PAT_PLACEHOLDER',
 }
 createMock.mockResolvedValueOnce(result)
 const store = useAccessTokenStore
 const plaintext = await store.createToken({ name: 'ci' })
 // action 返回值 === 明文
 expect(plaintext).toBe('FRIDAY_PAT_PLACEHOLDER')
 // 列表头部为新建项，但不含明文 token 字段
 expect(store.tokens[0].id).toBe('new-1')
 expect('token' in store.tokens[0]).toBe(false)
 // 整个 store 序列化后不含明文
 expect(JSON.stringify(store.tokens)).not.toContain('FRIDAY_PAT_PLACEHOLDER')
 })
 it('createToken_never_writes_storage', async => {
 const result: AccessTokenCreateResult = {
 ...makeToken({ id: 'new-2' }),
 token: 'FRIDAY_PAT_PLACEHOLDER',
 }
 createMock.mockResolvedValueOnce(result)
 const localSpy = vi.spyOn(Storage.prototype, 'setItem')
 const store = useAccessTokenStore
 await store.createToken({ name: 'no-storage' })
 // setItem 绝不被以明文调用
 const calledWithPlaintext = localSpy.mock.calls.some(args =>
 args.some(a => typeof a === 'string' && a.includes('FRIDAY_PAT_PLACEHOLDER')),
 )
 expect(calledWithPlaintext).toBe(false)
 localSpy.mockRestore
 })
 it('revokeToken_updates_row', async => {
 const original = makeToken({ id: 'r-1', revoked_at: null, is_valid: true })
 const revoked = makeToken({
 id: 'r-1',
 revoked_at: '2026-06-04T10:00:00Z',
 is_valid: false,
 })
 listMock.mockResolvedValueOnce([original])
 revokeMock.mockResolvedValueOnce(revoked)
 const store = useAccessTokenStore
 await store.fetchTokens
 await store.revokeToken('r-1')
 expect(store.tokens[0].revoked_at).toBe('2026-06-04T10:00:00Z')
 expect(store.tokens[0].is_valid).toBe(false)
 })
 it('fetchTokens 写入元数据列表', async => {
 listMock.mockResolvedValueOnce([makeToken({ id: 'a' }), makeToken({ id: 'b' })])
 const store = useAccessTokenStore
 await store.fetchTokens
 expect(store.tokens.map(t => t.id)).toEqual(['a', 'b'])
 })
 it('action 错误 re-throw 并写 lastError', async => {
 listMock.mockRejectedValueOnce(new Error('network'))
 const store = useAccessTokenStore
 await expect(store.fetchTokens).rejects.toThrow('network')
 expect(store.lastError).toBe('network')
 })
})
