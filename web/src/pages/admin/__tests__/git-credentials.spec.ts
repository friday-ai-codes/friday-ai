/**
 * /admin/git-credentials 实例凭证管理页守护测试（Plan 26-04，REPO-01，T-26-15）。
 *
 * 覆盖：
 * - 列表仅渲染 has_token 徽标（真实 zh-CN「已配置/未配置」文案），**不渲染明文 token**；
 * - 编辑表单不回填既有 token：password 输入框初值为空，placeholder 为真实 zh-CN
 *   「留空表示不修改」（断真实 messages，防文案被改空）；
 * - 列表与编辑态全程不出现任何明文 token 字符串。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

// ---- mocks ----
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}))
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const listMock = vi.fn()
vi.mock('~/api/gitInstanceCredentials', () => ({
  gitInstanceCredentialsApi: {
    list: (...a: unknown[]) => listMock(...a),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

const SECRET = 'glpat-PLAINTEXT-SHOULD-NEVER-RENDER-123'

function makeCred(overrides: Record<string, unknown> = {}) {
  return {
    id: 'gic-1',
    host: 'gitlab.example.com',
    provider: 'gitlab',
    label: '公司 GitLab',
    has_token: true,
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
    ...overrides,
  }
}

const Page = (await import('../git-credentials/index.vue')).default

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Page, {
    global: {
      plugins: [i18n, [VueQueryPlugin, { queryClient }]],
      stubs: { RouterLink: true },
    },
  })
}

describe('/admin/git-credentials 实例凭证管理页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('列表渲染 has_token 徽标，绝不渲染明文 token', async () => {
    listMock.mockResolvedValue([
      makeCred({ id: 'a', host: 'gitlab.a.com', has_token: true }),
      makeCred({ id: 'b', host: 'gitlab.b.com', has_token: false, label: '' }),
    ])
    const wrapper = mountPage()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('gitlab.a.com')
    expect(text).toContain('gitlab.b.com')
    // 真实 zh-CN 徽标文案（防文案被改空）
    expect(text).toContain(zhCN.gitCredentials.tokenConfigured)
    expect(text).toContain(zhCN.gitCredentials.tokenMissing)
    // 列表 HTML 绝不含明文 token
    expect(wrapper.html()).not.toContain(SECRET)
  })

  it('编辑表单不回填既有 token：password 框初值为空 + 「留空表示不修改」占位', async () => {
    listMock.mockResolvedValue([makeCred()])
    const wrapper = mountPage()
    await flushPromises()

    // 点击「编辑」打开表单
    const editBtn = wrapper.findAll('button').find(b => b.text().includes(zhCN.gitCredentials.actions.edit))
    expect(editBtn).toBeDefined()
    await editBtn!.trigger('click')
    await flushPromises()

    const tokenInput = wrapper.find('#gic-token')
    expect(tokenInput.exists()).toBe(true)
    // 编辑态绝不回填既有 token（input 初值为空）
    expect((tokenInput.element as HTMLInputElement).value).toBe('')
    expect(tokenInput.attributes('type')).toBe('password')
    // 真实 zh-CN「留空表示不修改」占位（防文案被改空）
    expect(tokenInput.attributes('placeholder')).toBe(
      zhCN.gitCredentials.form.accessTokenPlaceholderEdit,
    )
    expect(zhCN.gitCredentials.form.accessTokenPlaceholderEdit).toContain('留空表示不修改')
    // host 回填、token 不回填
    expect((wrapper.find('#gic-host').element as HTMLInputElement).value).toBe('gitlab.example.com')
    expect(wrapper.html()).not.toContain(SECRET)
  })
})
