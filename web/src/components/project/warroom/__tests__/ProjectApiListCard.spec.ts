/**
 * ProjectApiListCard 守护测试（项目作战室 P5 可编辑大盘）。
 *
 * 覆盖：清单渲染 / 成员可见新增表单+删除入口 / 非成员只读（无编辑控件）/ 空态。
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
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
}))

const listStateApisMock = vi.fn()
vi.mock('~/api/projectWorkspace', () => ({
  projectWorkspaceApi: {
    listStateApis: (...a: unknown[]) => listStateApisMock(...a),
    upsertStateApi: vi.fn(),
    patchStateApi: vi.fn(),
    deleteStateApi: vi.fn(),
  },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../ProjectApiListCard.vue')).default

function mountComp(canManage: boolean) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1', canManage },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

const ROWS = [
  { id: '1', project_id: 'p1', method: 'GET', path: '/api/x', params: {}, status: 'planned', source: 's', created_at: '', updated_at: '' },
  { id: '2', project_id: 'p1', method: 'POST', path: '/api/y', params: {}, status: 'done', source: 's', created_at: '', updated_at: '' },
]

describe('projectApiListCard（P5）', () => {
  beforeEach(() => vi.clearAllMocks())

  it('渲染清单行', async () => {
    listStateApisMock.mockResolvedValue(ROWS)
    const wrapper = mountComp(true)
    await flushPromises()
    expect(wrapper.findAll('[data-testid="api-row"]').length).toBe(2)
    expect(wrapper.text()).toContain('/api/x')
    expect(wrapper.text()).toContain('/api/y')
  })

  it('成员可见新增表单与删除入口', async () => {
    listStateApisMock.mockResolvedValue(ROWS)
    const wrapper = mountComp(true)
    await flushPromises()
    expect(wrapper.find('[data-testid="api-add-form"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="api-delete"]').exists()).toBe(true)
  })

  it('非成员只读：无新增表单与删除入口', async () => {
    listStateApisMock.mockResolvedValue(ROWS)
    const wrapper = mountComp(false)
    await flushPromises()
    expect(wrapper.find('[data-testid="api-add-form"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="api-delete"]').exists()).toBe(false)
  })

  it('空态文案', async () => {
    listStateApisMock.mockResolvedValue([])
    const wrapper = mountComp(true)
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.projects.warroom.apis.empty)
  })
})
