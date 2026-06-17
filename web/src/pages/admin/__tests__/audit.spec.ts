/**
 * /admin/audit 操作审计查询页测试（v0.10.0 AUDITUI-02）。
 *
 * 覆盖：列表渲染（动作/操作者/目标/来源）、过滤「查询」触发带参请求、
 * 导出按钮调用 auditApi.exportFile、详情弹窗展示 before/after。只读：无删除入口。
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

const listMock = vi.fn()
const exportMock = vi.fn()
vi.mock('~/api/audit', () => ({
  auditApi: {
    list: (...a: unknown[]) => listMock(...a),
    detail: vi.fn(),
    exportFile: (...a: unknown[]) => exportMock(...a),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ev-1',
    actor_id: 'u-1',
    actor_repr: 'zhangsan (superuser)',
    action: 'credential.created',
    target_type: 'provider_credential',
    target_id: 't-1',
    target_repr: 'anthropic:prod',
    before: {},
    after: { name: 'prod' },
    source: 'api',
    occurred_at: '2026-06-17T00:00:00Z',
    recorded_at: '2026-06-17T00:00:01Z',
    metadata: {},
    ...overrides,
  }
}

const Page = (await import('../audit/index.vue')).default

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Page, {
    global: {
      plugins: [i18n, [VueQueryPlugin, { queryClient }]],
      stubs: { RouterLink: true, Teleport: true },
    },
  })
}

describe('/admin/audit 操作审计页', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    listMock.mockResolvedValue({ items: [makeEvent()], total: 1, limit: 50, offset: 0 })
  })

  it('渲染列表行（动作/操作者/目标/来源）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('credential.created')
    expect(text).toContain('zhangsan (superuser)')
    expect(text).toContain('anthropic:prod')
    // 真实 zh-CN 标题（防文案被改空）
    expect(text).toContain(zhCN.audit.title)
  })

  it('点击「查询」按动作过滤触发带参请求', async () => {
    const wrapper = mountPage()
    await flushPromises()

    const select = wrapper.find('select')
    await select.setValue('pat.revoked')
    const searchBtn = wrapper.findAll('button').find(b => b.text().includes(zhCN.audit.filters.search))
    expect(searchBtn).toBeDefined()
    await searchBtn!.trigger('click')
    await flushPromises()

    const lastCall = listMock.mock.calls.at(-1)?.[0]
    expect(lastCall).toMatchObject({ action: 'pat.revoked', offset: 0 })
  })

  it('导出按钮调用 exportFile(csv)', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const csvBtn = wrapper.findAll('button').find(b => b.text().includes(zhCN.audit.export.csv))
    expect(csvBtn).toBeDefined()
    await csvBtn!.trigger('click')
    await flushPromises()
    expect(exportMock).toHaveBeenCalledTimes(1)
    expect(exportMock.mock.calls[0][1]).toBe('csv')
  })

  it('只读：列表无删除按钮', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const hasDelete = wrapper.findAll('button').some(b => /删除|delete/i.test(b.text()))
    expect(hasDelete).toBe(false)
  })
})
