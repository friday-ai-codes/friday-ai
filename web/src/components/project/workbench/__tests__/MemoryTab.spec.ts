/**
 * MemoryTab 记忆草稿确认守护测试（UI-03）。
 *
 * 覆盖：pending 草稿渲染 + 接受入库（confirmDraft）/ 拒绝（rejectDraft），二次确认。
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

const listMock = vi.fn().mockResolvedValue([])
const listDraftsMock = vi.fn()
const confirmDraftMock = vi.fn().mockResolvedValue({})
const rejectDraftMock = vi.fn().mockResolvedValue({})
vi.mock('~/api/projectMemory', () => ({
  projectMemoryApi: {
    list: (...a: unknown[]) => listMock(...a),
    listDrafts: (...a: unknown[]) => listDraftsMock(...a),
    create: vi.fn().mockResolvedValue({}),
    edit: vi.fn(),
    supersede: vi.fn(),
    confirmDraft: (...a: unknown[]) => confirmDraftMock(...a),
    rejectDraft: (...a: unknown[]) => rejectDraftMock(...a),
  },
}))

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': zhCN as any } })

const Comp = (await import('../MemoryTab.vue')).default

function mountTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(Comp, {
    props: { projectId: 'p1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

const DRAFT = {
  id: 'd1',
  project_id: 'p1',
  content: 'LLM 提议：登录态统一走 cookie-JWT',
  status: 'pending',
  source_conversation_id: 'c1',
  proposed_by_id: 'u1',
  confirmed_memory_id: null,
  created_at: '2026-06-20T00:00:00Z',
  updated_at: '2026-06-20T00:00:00Z',
}

describe('MemoryTab 草稿确认', () => {
  beforeEach(() => vi.clearAllMocks())

  it('渲染 pending 草稿区与真实文案', async () => {
    listDraftsMock.mockResolvedValue([DRAFT])
    const wrapper = mountTab()
    await flushPromises()
    expect(wrapper.find('[data-testid="draft-section"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.projects.memory.draft.title)
    expect(wrapper.text()).toContain('LLM 提议：登录态统一走 cookie-JWT')
  })

  it('接受草稿 → confirmDraft（二次确认）', async () => {
    listDraftsMock.mockResolvedValue([DRAFT])
    const wrapper = mountTab()
    await flushPromises()
    await wrapper.find('[data-testid="draft-accept"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalled()
    expect(confirmDraftMock).toHaveBeenCalledWith('p1', 'd1')
  })

  it('拒绝草稿 → rejectDraft（二次确认）', async () => {
    listDraftsMock.mockResolvedValue([DRAFT])
    const wrapper = mountTab()
    await flushPromises()
    await wrapper.find('[data-testid="draft-reject"]').trigger('click')
    await flushPromises()
    expect(confirmMock).toHaveBeenCalled()
    expect(rejectDraftMock).toHaveBeenCalledWith('p1', 'd1')
  })

  it('无草稿时不渲染草稿区', async () => {
    listDraftsMock.mockResolvedValue([])
    const wrapper = mountTab()
    await flushPromises()
    expect(wrapper.find('[data-testid="draft-section"]').exists()).toBe(false)
    expect(wrapper.text()).toContain(zhCN.projects.memory.empty)
  })
})
