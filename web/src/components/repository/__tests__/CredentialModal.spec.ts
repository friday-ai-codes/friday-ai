/**
 * CredentialModal — 凭证管理弹窗 component 测试（Phase/02/03）
 *
 * 覆盖：
 * 1. 打开弹窗（无凭证）渲染 Access Token 表单 → 提交调用现有 API（setAccessToken mock）
 * + emit('saved') + 关闭弹窗
 * 2. 已有凭证时脱敏展示（••••）+ 认证类型徽标，不回显明文；点击「更新凭证」切到表单
 * 3. 保存失败：错误提示不含明文 Token（脱敏红线，T-）
 * 4. 旧路由 redirect 守卫：credential.vue 声明 redirect → `#credential`（，静态断言）
 *
 * vi.mock('~/api/repositories') 拦截 setAccessToken；mock useToast 捕获 success/error
 * 文案以断言脱敏；stub shadcn Dialog/Input/Button 让弹窗内容直接渲染。
 */
import type { GitCredential } from '~/types'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import CredentialModal from '../CredentialModal.vue'
vi.mock('~/api/repositories', => ({
 repositoriesApi: {
 setAccessToken: vi.fn,
 },
}))
// 捕获 toast 文案，断言脱敏（success/error 描述不含明文 Token）
const successSpy = vi.fn
const errorSpy = vi.fn
vi.mock('~/composables/useToast', => ({
 useToast: => ({
 success: successSpy,
 error: errorSpy,
 warning: vi.fn,
 info: vi.fn,
 loading: vi.fn,
 promise: vi.fn,
 dismissAll: vi.fn,
 toast: {},
 }),
}))
const PLAINTEXT_TOKEN = 'GITHUB_TOKEN_PLACEHOLDER'
// ===== stubs =====
const PassthroughStub = defineComponent({ template: '<div><slot /></div>' })
const InputStub = defineComponent({
 name: 'Input',
 props: { modelValue: { type: String, default: '' } },
 emits: ['update:modelValue'],
 inheritAttrs: false,
 template: `<input
 v-bind="$attrs":value="modelValue"
 @input="$emit('update:modelValue', $event.target.value)"
 />`,
})
const ButtonStub = defineComponent({
 name: 'Button',
 props: { disabled: { type: Boolean, default: false } },
 template: '<button:disabled="disabled" v-bind="$attrs"><slot /></button>',
})
const stubs = {
 Dialog: PassthroughStub,
 DialogContent: PassthroughStub,
 DialogHeader: PassthroughStub,
 DialogTitle: PassthroughStub,
 DialogDescription: PassthroughStub,
 Label: PassthroughStub,
 Badge: PassthroughStub,
 Separator: defineComponent({ template: '<hr />' }),
 Input: InputStub,
 Button: ButtonStub,
}
function makeCredential(overrides: Partial<GitCredential> = {}): GitCredential {
 return {
 id: 'cred-1',
 repository_id: 'repo-1',
 auth_type: 'access_token',
 git_user_name: 'Friday AI',
 git_user_email: 'ai@friday.codes',
 created_at: '2026-06-01T00:00:00Z',
 ...overrides,
 }
}
function mountModal(props: Record<string, unknown> = {}) {
 return mount(CredentialModal, {
 props: { repositoryId: 'repo-1', open: true, credential: null, ...props },
 global: { stubs },
 })
}
describe('credentialModal', => {
 beforeEach( => {
 vi.clearAllMocks
 vi.mocked(repositoriesApi.setAccessToken).mockResolvedValue(makeCredential)
 })
 it('无凭证时渲染表单并提交调用 setAccessToken + emit saved', async => {
 const wrapper = mountModal
 // Access Token 表单可见
 const tokenInput = wrapper.find('#cred_access_token')
 expect(tokenInput.exists).toBe(true)
 await tokenInput.setValue(PLAINTEXT_TOKEN)
 await wrapper.find('form').trigger('submit')
 await flushPromises
 expect(repositoriesApi.setAccessToken).toHaveBeenCalledTimes(1)
 expect(repositoriesApi.setAccessToken).toHaveBeenCalledWith(
 'repo-1',
 expect.objectContaining({ token: PLAINTEXT_TOKEN }),
 )
 // 保存成功 emit('saved') + 关闭弹窗
 expect(wrapper.emitted('saved')).toBeTruthy
 const openEvents = wrapper.emitted('update:open') as boolean | undefined
 expect(openEvents?.some(e => e[0] === false)).toBe(true)
 })
 it('已有凭证时脱敏展示，不回显明文，可切换到更新表单', async => {
 const wrapper = mountModal({ credential: makeCredential({ auth_type: 'ssh_key' }) })
 // 默认展示态：脱敏占位符 + 认证类型，无 token 输入框
 expect(wrapper.text).toContain('••••••••••••••••')
 expect(wrapper.text).toContain('SSH 密钥')
 expect(wrapper.find('#cred_access_token').exists).toBe(false)
 expect(wrapper.text).not.toContain(PLAINTEXT_TOKEN)
 // 点击「更新凭证」切到表单
 const updateBtn = wrapper.findAll('button').find(b => b.text.includes('更新凭证'))
 await updateBtn!.trigger('click')
 expect(wrapper.find('#cred_access_token').exists).toBe(true)
 })
 it('保存失败时错误提示不含明文 Token（脱敏红线）', async => {
 vi.mocked(repositoriesApi.setAccessToken).mockRejectedValue(new Error('凭证保存失败'))
 const wrapper = mountModal
 await wrapper.find('#cred_access_token').setValue(PLAINTEXT_TOKEN)
 await wrapper.find('form').trigger('submit')
 await flushPromises
 expect(errorSpy).toHaveBeenCalled
 // 任何 toast 文案都不得包含用户输入的明文 Token
 const allToastArgs = [...successSpy.mock.calls, ...errorSpy.mock.calls].flat.join(' | ')
 expect(allToastArgs).not.toContain(PLAINTEXT_TOKEN)
 // 保存失败不应 emit saved
 expect(wrapper.emitted('saved')).toBeFalsy
 })
 it('旧路由 credential.vue 声明 redirect → #credential', => {
 const credentialPagePath = resolve(
 process.cwd,
 'src/pages/repositories/[id]/credential.vue',
 )
 const source = readFileSync(credentialPagePath, 'utf-8')
 expect(source).toContain('redirect')
 expect(source).toContain('#credential')
 expect(source).toContain('/repositories/')
 })
})
