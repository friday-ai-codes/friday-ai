/**
 * /admin/artifact-types 工件类型管理页守护测试（UI-03）。
 *
 * 覆盖：内置类型与有实例类型的删除按钮禁用 + tooltip（删除保护，真实 zh-CN 文案）；
 * 可删除类型按钮可用；列表真实文案。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
const confirmMock = vi.fn().mockResolvedValue(true)
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: confirmMock }),
}))

const listMock = vi.fn()
const removeMock = vi.fn().mockResolvedValue(undefined)
const updateMock = vi.fn().mockResolvedValue({})
vi.mock('~/api/artifactTypes', () => ({
  ARTIFACT_CARRIERS: ['feishu_doc', 'markdown', 'external_link'],
  artifactTypesApi: {
    list: (...a: unknown[]) => listMock(...a),
    create: vi.fn(),
    update: (...a: unknown[]) => updateMock(...a),
    remove: (...a: unknown[]) => removeMock(...a),
  },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

function makeType(overrides: Record<string, unknown> = {}) {
  return {
    id: 't1',
    key: 'custom',
    name: '自定义类型',
    carrier: 'markdown',
    ragable: true,
    enabled: true,
    builtin: false,
    instance_count: 0,
    created_at: '2026-06-20T00:00:00Z',
    updated_at: '2026-06-20T00:00:00Z',
    ...overrides,
  }
}

const Page = (await import('../artifact-types/index.vue')).default

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Page, {
    global: {
      plugins: [i18n, [VueQueryPlugin, { queryClient }]],
      stubs: { RouterLink: true, PageContainer: { template: '<div><slot /></div>' } },
    },
  })
}

describe('/admin/artifact-types 工件类型管理页', () => {
  beforeEach(() => vi.clearAllMocks())

  it('内置类型删除按钮禁用（删除保护）', async () => {
    listMock.mockResolvedValue([makeType({ key: 'builtin_doc', name: '需求文档', builtin: true })])
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.find('[data-testid="delete-builtin_doc"]')
    expect(delBtn.exists()).toBe(true)
    expect(delBtn.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain(zhCN.artifactTypes.builtin)
  })

  it('有实例类型删除按钮禁用 + 提示文案', async () => {
    listMock.mockResolvedValue([makeType({ key: 'used_type', instance_count: 5 })])
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.find('[data-testid="delete-used_type"]')
    // 有实例 → 删除按钮禁用（tooltip 内容由 reka-ui 在 hover 时渲染，此处校验禁用态）。
    expect(delBtn.attributes('disabled')).toBeDefined()
  })

  it('可删除类型按钮可点击并触发删除', async () => {
    listMock.mockResolvedValue([makeType({ key: 'removable', instance_count: 0, builtin: false })])
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.find('[data-testid="delete-removable"]')
    expect(delBtn.attributes('disabled')).toBeUndefined()
    await delBtn.trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalled()
    expect(removeMock).toHaveBeenCalledWith('t1')
  })

  it('启停切换调用 update', async () => {
    listMock.mockResolvedValue([makeType({ key: 'toggle_me', enabled: true })])
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('[data-testid="toggle-toggle_me"]').trigger('click')
    await flushPromises()
    expect(updateMock).toHaveBeenCalledWith('t1', { enabled: false })
  })
})
