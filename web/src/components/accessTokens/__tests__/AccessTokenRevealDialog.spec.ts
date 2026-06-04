import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AccessTokenRevealDialog from '~/components/accessTokens/AccessTokenRevealDialog.vue'
// ============================================================================
// Mocks：clipboard 复制 + toast（隔离 vue-sonner 副作用）
// ============================================================================
const copyMock = vi.fn
vi.mock('@vueuse/core', async (importOriginal) => {
 const actual = await importOriginal<typeof import('@vueuse/core')>
 return {
 ...actual,
 useClipboard: => ({ copy: copyMock }),
 }
})
const successMock = vi.fn
vi.mock('~/composables/useToast', => ({
 useToast: => ({ success: successMock, error: vi.fn }),
}))
const PLAINTEXT = 'FRIDAY_PAT_PLACEHOLDER'
// Dialog 原语用透传 stub，使内容内联渲染便于断言（规避 Teleport）
const dialogStubs = {
 Dialog: { template: '<div><slot /></div>' },
 DialogContent: { template: '<div><slot /></div>' },
 DialogHeader: { template: '<div><slot /></div>' },
 DialogTitle: { template: '<div><slot /></div>' },
 DialogDescription: { template: '<div><slot /></div>' },
}
describe('accessTokenRevealDialog', => {
 beforeEach( => {
 vi.clearAllMocks
 })
 it('renders_plaintext_once_with_warning', => {
 const wrapper = mount(AccessTokenRevealDialog, {
 props: { open: true, token: PLAINTEXT },
 global: { stubs: dialogStubs },
 })
 const html = wrapper.html
 expect(html).toContain(PLAINTEXT)
 expect(html).toContain('仅显示一次')
 })
 it('copy_calls_clipboard', async => {
 const wrapper = mount(AccessTokenRevealDialog, {
 props: { open: true, token: PLAINTEXT },
 global: { stubs: dialogStubs },
 })
 await wrapper.find('button').trigger('click')
 expect(copyMock).toHaveBeenCalledWith(PLAINTEXT)
 expect(successMock).toHaveBeenCalled
 })
 it('does_not_log_plaintext', async => {
 const logSpy = vi.spyOn(console, 'log').mockImplementation( => {})
 const warnSpy = vi.spyOn(console, 'warn').mockImplementation( => {})
 const errorSpy = vi.spyOn(console, 'error').mockImplementation( => {})
 const wrapper = mount(AccessTokenRevealDialog, {
 props: { open: true, token: PLAINTEXT },
 global: { stubs: dialogStubs },
 })
 await wrapper.find('button').trigger('click')
 const leaked = [...logSpy.mock.calls, ...warnSpy.mock.calls, ...errorSpy.mock.calls]
 .some(args => args.some(a => typeof a === 'string' && a.includes('friday_pat_')))
 expect(leaked).toBe(false)
 logSpy.mockRestore
 warnSpy.mockRestore
 errorSpy.mockRestore
 })
})
