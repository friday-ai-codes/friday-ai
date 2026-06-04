import type { AccessTokenDto } from '~/types/accessToken'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccessTokenSettings from '~/components/accessTokens/AccessTokenSettings.vue'
import AccessTokenForm from '~/components/accessTokens/AccessTokenForm.vue'
import AccessTokenListTable from '~/components/accessTokens/AccessTokenListTable.vue'
import AccessTokenRevealDialog from '~/components/accessTokens/AccessTokenRevealDialog.vue'
// ============================================================================
// Mocks：store + toast/errorHandler（隔离 vue-sonner 与网络）
// ============================================================================
const fetchTokensMock = vi.fn.mockResolvedValue
const createTokenMock = vi.fn
const revokeTokenMock = vi.fn
vi.mock('~/stores/accessTokens', => ({
 useAccessTokenStore: => ({
 tokens: as AccessTokenDto,
 loading: false,
 fetchTokens: fetchTokensMock,
 createToken: createTokenMock,
 revokeToken: revokeTokenMock,
 }),
}))
vi.mock('~/composables/useToast', => ({
 useToast: => ({ success: vi.fn, error: vi.fn }),
}))
vi.mock('~/composables/useErrorHandler', => ({
 useErrorHandler: => ({ handleError: vi.fn }),
}))
// Dialog / AlertDialog 原语透传 stub，使内嵌内容始终渲染便于断言
const stubs = {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<div><slot /></div>' },
 DialogDescription: { template: '<div><slot /></div>' },
 AlertDialog: { template: '<div><slot /></div>' },
 AlertDialogContent: { template: '<div><slot /></div>' },
 AlertDialogHeader: { template: '<div><slot /></div>' },
 AlertDialogTitle: { template: '<div><slot /></div>' },
 AlertDialogDescription: { template: '<div><slot /></div>' },
 AlertDialogFooter: { template: '<div><slot /></div>' },
 AlertDialogCancel: { template: '<button><slot /></button>' },
 AlertDialogAction: {
 template: '<button class="confirm-revoke" @click="$emit(\'click\')"><slot /></button>',
 },
}
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
describe('accessTokenSettings', => {
 beforeEach( => {
 vi.clearAllMocks
 fetchTokensMock.mockResolvedValue
 })
 it('create_flow_opens_reveal_with_plaintext', async => {
 createTokenMock.mockResolvedValueOnce('friday_pat_NEWPLAIN')
 const wrapper = mount(AccessTokenSettings, { global: { stubs } })
 wrapper.findComponent(AccessTokenForm).vm.$emit('submit', { name: 'ci' })
 await flushPromises
 const reveal = wrapper.findComponent(AccessTokenRevealDialog)
 expect(reveal.props('open')).toBe(true)
 expect(reveal.props('token')).toBe('friday_pat_NEWPLAIN')
 })
 it('closing_reveal_clears_plaintext', async => {
 createTokenMock.mockResolvedValueOnce('friday_pat_TOCLEAR')
 const wrapper = mount(AccessTokenSettings, { global: { stubs } })
 wrapper.findComponent(AccessTokenForm).vm.$emit('submit', { name: 'ci' })
 await flushPromises
 const reveal = wrapper.findComponent(AccessTokenRevealDialog)
 expect(reveal.props('token')).toBe('friday_pat_TOCLEAR')
 // 关闭 reveal → 明文内存 ref 归 null
 reveal.vm.$emit('update:open', false)
 await flushPromises
 expect(reveal.props('token')).toBeNull
 })
 it('revoke_confirm_calls_store', async => {
 revokeTokenMock.mockResolvedValueOnce(makeToken({ revoked_at: '2026-06-04T10:00:00Z' }))
 const wrapper = mount(AccessTokenSettings, { global: { stubs } })
 wrapper.findComponent(AccessTokenListTable).vm.$emit('revoke', makeToken({ id: 'r-9' }))
 await flushPromises
 await wrapper.find('.confirm-revoke').trigger('click')
 await flushPromises
 expect(revokeTokenMock).toHaveBeenCalledWith('r-9')
 })
})
