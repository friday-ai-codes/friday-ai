/**
 * Phase 75-04 系统日志页组件 spec（UI-04）。
 *
 *   (a) QueueCountersBar 渲染 4 计数 + dropped>0 命中琥珀 class。
 *   (b) SystemLogTable 选级别 error → 以 level=error 调 querySystemLogs。
 *   (c) logs.vue 无筛选清理 → 以 confirm_all=true 调 clearSystemLogs。
 *   (d) LogDrilldownSheet 给 conversationId → 调 getConversationDrilldown 并以 pre
 *       文本渲染 message（断言 HTML 转义 = 无 v-html）。
 *   (e) RuntimeLogConfigForm 保存 → 调 updateSetting('log.level', ...)。
 *
 * 触网全部 mock（~/api/system + ~/api/settings）；含 useQuery 的组件用 VueQueryPlugin
 * 注入 QueryClient；toast / errorHandler 经 mock 隔离。
 */
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { Select } from '~/components/ui/select'
import LogDrilldownSheet from '../LogDrilldownSheet.vue'
import QueueCountersBar from '../QueueCountersBar.vue'
import RuntimeLogConfigForm from '../RuntimeLogConfigForm.vue'
import SystemLogTable from '../SystemLogTable.vue'

// ---- mocks ----
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', async () => {
  const actual = await vi.importActual<typeof import('~/composables/useErrorHandler')>('~/composables/useErrorHandler')
  return { ...actual, useErrorHandler: () => ({ handleError: vi.fn() }) }
})
vi.mock('~/api/system', () => ({
  querySystemLogs: vi.fn(),
  clearSystemLogs: vi.fn(),
  getConversationDrilldown: vi.fn(),
  getCallDrilldown: vi.fn(),
  getWebhookEvent: vi.fn(),
}))
vi.mock('~/api/settings', () => ({
  getSetting: vi.fn(),
  updateSetting: vi.fn(),
}))

const {
  querySystemLogs,
  clearSystemLogs,
  getConversationDrilldown,
} = await import('~/api/system')
const { getSetting, updateSetting } = await import('~/api/settings')

function withQuery(component: any, props: Record<string, any> = {}, extra: Record<string, any> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(component, {
    props,
    global: { plugins: [[VueQueryPlugin, { queryClient }]], ...extra },
  })
}

describe('queueCountersBar', () => {
  it('(a) 渲染 4 计数 + dropped>0 命中琥珀 class', () => {
    const wrapper = mount(QueueCountersBar, {
      props: {
        counters: { queued: 10, max: 5000, written: 100, dropped: 5, write_failed: 0, sampled_out: 2 },
        loading: false,
      },
    })
    const text = wrapper.text()
    for (const label of ['队列深度', '已写入', '已丢弃', '落库失败'])
      expect(text).toContain(label)
    expect(text).toContain('5,000')
    expect(text).toContain('100')
    // dropped=5 > 0 → 琥珀色类命中。
    expect(wrapper.html()).toContain('text-amber-500')
    wrapper.unmount()
  })
})

describe('systemLogTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(querySystemLogs).mockResolvedValue({ items: [], total: 0, counters: {} })
  })

  it('(b) 选级别 error → 以 level=error 调 querySystemLogs', async () => {
    const wrapper = withQuery(SystemLogTable)
    await flushPromises()
    expect(querySystemLogs).toHaveBeenCalled()

    // 第一个 Select 为级别筛选。
    await wrapper.findAllComponents(Select)[0].vm.$emit('update:modelValue', 'error')
    await flushPromises()

    expect(querySystemLogs).toHaveBeenLastCalledWith(expect.objectContaining({ level: 'error' }))
    wrapper.unmount()
  })
})

describe('logsPage clear', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(clearSystemLogs).mockResolvedValue({ deleted: 3 })
  })

  it('(c) 无筛选清理 → 以 confirm_all=true 调 clearSystemLogs', async () => {
    const Logs = (await import('~/pages/admin/observability/logs.vue')).default
    const { AlertDialogAction } = await import('~/components/ui/alert-dialog')
    const wrapper = withQuery(Logs, {}, {
      stubs: {
        ObservabilityTabs: true,
        ObservabilityTimeRange: true,
        QueueCountersBar: true,
        SystemLogTable: true,
        RuntimeLogConfigForm: true,
        LogDrilldownSheet: true,
      },
    })
    await flushPromises()

    // 打开清理确认（SystemLogTable 被 stub，未 emit filtersChange → currentFilters 为空）。
    await wrapper.find('[aria-label="按当前筛选清理日志"]').trigger('click')
    await flushPromises()

    // 确认按钮（teleport，用组件树定位）。
    await wrapper.findComponent(AlertDialogAction).trigger('click')
    await flushPromises()

    expect(clearSystemLogs).toHaveBeenCalledWith(expect.objectContaining({ confirm_all: true }))
    wrapper.unmount()
  })
})

describe('logDrilldownSheet', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getConversationDrilldown).mockResolvedValue({
      conversation: { title: '会话A', status: 'active', model: 'gpt', created_at: '2026-06-25T00:00:00Z' },
      created_by: { id: '1', username: 'alice' },
      // message content 含 HTML，用以验证 pre 文本插值（转义）= 无 v-html。
      messages: [{ id: 'm1', role: 'user', content: '<b>hi</b>', created_at: '2026-06-25T00:00:00Z' }],
      related_logs: [],
      related_runs: [],
    })
  })

  it('(d) 给 conversationId → 调 getConversationDrilldown 且 message 经 pre 文本转义渲染', async () => {
    const wrapper = withQuery(LogDrilldownSheet, { open: true, context: { conversationId: 'c1' } })
    await flushPromises()

    expect(getConversationDrilldown).toHaveBeenCalledWith('c1')
    // Sheet 经 teleport 渲染到 body；断言 HTML 转义（无 v-html 注入风险）。
    const body = document.body.innerHTML
    expect(body).toContain('会话A')
    expect(body).toContain('&lt;b&gt;hi&lt;/b&gt;')
    expect(body).not.toContain('<b>hi</b>')
    wrapper.unmount()
  })
})

describe('runtimeLogConfigForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getSetting).mockResolvedValue({
      key: 'log.level',
      value: null,
      is_encrypted: false,
      has_value: false,
      description: null,
      updated_at: null,
    })
    vi.mocked(updateSetting).mockResolvedValue({
      key: 'log.level',
      value: '',
      is_encrypted: false,
      has_value: false,
      description: null,
      updated_at: null,
    })
  })

  it('(e) 保存 → 调 updateSetting(\'log.level\', ...)', async () => {
    const wrapper = mount(RuntimeLogConfigForm)
    await flushPromises()

    // 展开折叠区以渲染保存按钮。
    await wrapper.find('[aria-label="展开运行时日志配置"]').trigger('click')
    await flushPromises()

    const saveBtn = wrapper.findAll('button').find(b => b.text().includes('保存并生效'))
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(updateSetting).toHaveBeenCalledWith('log.level', '')
    wrapper.unmount()
  })
})
