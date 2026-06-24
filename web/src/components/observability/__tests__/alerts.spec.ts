/**
 * Phase 75-03 告警事件页组件 spec（UI-03）。
 *
 *   (a) AlertEventsTable 渲染 8 列表头 + 一行事件含 rule_info.expr。
 *   (b) 选级别筛选 P0 → 以 severity=P0 调 listAlertEvents。
 *   (c) AlertRuleFormDialog 提交合法 body → 调 createAlertRule。
 *   (d) AlertRuleFormDialog 后端返回 ApiError(400) → 展示错误不崩。
 *   (e) AlertRulesPanel 删除走二次确认后 → 调 deleteAlertRule。
 *
 * 触网全部 mock（~/api/system）；含 useQuery 的组件用 VueQueryPlugin 注入 QueryClient。
 */
import type { AlertEventRow, AlertRule } from '~/api/system'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '~/api/client'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { Select } from '~/components/ui/select'
import AlertEventsTable from '../AlertEventsTable.vue'
import AlertRuleFormDialog from '../AlertRuleFormDialog.vue'
import AlertRulesPanel from '../AlertRulesPanel.vue'

// ---- mocks ----
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))
const handleErrorMock = vi.fn()
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: handleErrorMock }),
}))
vi.mock('~/api/system', () => ({
  listAlertEvents: vi.fn(),
  listAlertRules: vi.fn(),
  createAlertRule: vi.fn(),
  updateAlertRule: vi.fn(),
  deleteAlertRule: vi.fn(),
}))

const {
  listAlertEvents,
  listAlertRules,
  createAlertRule,
  deleteAlertRule,
} = await import('~/api/system')

function makeEvent(overrides: Partial<AlertEventRow> = {}): AlertEventRow {
  return {
    id: 1,
    rule: 5,
    severity: 'P0',
    title_zh: 'CPU 高负载',
    rule_info: { metric: 'cpu', op: 'gt', threshold: 85, expr: 'cpu_usage_percent > 85.00 (current 95.40) over last 5m' },
    target: { provider: 'anthropic' },
    target_key: 'provider=anthropic',
    status: 'firing',
    started_at: '2026-06-25T00:00:00Z',
    ended_at: null,
    duration_s: null,
    current_value: 95.4,
    last_seen_at: '2026-06-25T00:05:00Z',
    email_sent: 'sent',
    notified_channels: ['email'],
    created_at: '2026-06-25T00:00:00Z',
    ...overrides,
  }
}

function makeRule(overrides: Partial<AlertRule> = {}): AlertRule {
  return {
    id: 5,
    name: 'CPU 高负载告警',
    metric: 'cpu',
    op: 'gt',
    value: 85,
    window: 300,
    dimension: {},
    severity: 'P0',
    enabled: true,
    channels: ['email'],
    cooldown: 600,
    title_template: '',
    created_at: '2026-06-25T00:00:00Z',
    updated_at: '2026-06-25T00:00:00Z',
    ...overrides,
  }
}

function withQuery(component: any, props: Record<string, any> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(component, {
    props,
    global: { plugins: [[VueQueryPlugin, { queryClient }]] },
  })
}

describe('alertEventsTable', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listAlertEvents).mockResolvedValue({ items: [makeEvent()], total: 1 })
  })

  it('(a) 渲染 8 列表头 + 一行事件含 rule_info.expr', async () => {
    const wrapper = withQuery(AlertEventsTable, { rules: [] })
    await flushPromises()
    const text = wrapper.text()
    for (const head of ['时间', '级别', '状态', '维度', '规则ID', '标题', '持续时长', '邮件状态'])
      expect(text).toContain(head)
    expect(text).toContain('CPU 高负载')
    expect(text).toContain('cpu_usage_percent > 85.00 (current 95.40) over last 5m')
    wrapper.unmount()
  })

  it('(b) 选级别 P0 → 以 severity=P0 调 listAlertEvents', async () => {
    const wrapper = withQuery(AlertEventsTable, { rules: [] })
    await flushPromises()
    // 首次拉取无 severity。
    expect(listAlertEvents).toHaveBeenCalled()

    // 第一个 Select 为级别筛选；emit v-model 更新到 'P0'。
    await wrapper.findAllComponents(Select)[0].vm.$emit('update:modelValue', 'P0')
    await flushPromises()

    expect(listAlertEvents).toHaveBeenLastCalledWith(expect.objectContaining({ severity: 'P0' }))
    wrapper.unmount()
  })
})

describe('alertRuleFormDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('(c) 提交合法 body → 调 createAlertRule', async () => {
    vi.mocked(createAlertRule).mockResolvedValue(makeRule())
    const wrapper = mount(AlertRuleFormDialog, { props: { open: true, rule: null } })
    await flushPromises()

    // DialogContent 经 teleport 渲染，用组件树定位 Input / 提交按钮。
    const inputs = wrapper.findAllComponents(Input)
    await inputs.find(i => i.attributes('placeholder') === '如：CPU 高负载告警')!.setValue('新规则')
    await inputs.find(i => i.attributes('placeholder') === '如 85')!.setValue('90')
    const submitBtn = wrapper.findAllComponents(Button).find(b => b.attributes('type') === 'submit')!
    await submitBtn.trigger('click')
    await flushPromises()

    expect(createAlertRule).toHaveBeenCalledTimes(1)
    expect(createAlertRule).toHaveBeenCalledWith(expect.objectContaining({
      name: '新规则',
      metric: 'cpu',
      op: 'gt',
      value: 90,
      severity: 'P1',
      channels: ['email'],
    }))
    wrapper.unmount()
  })

  it('(d) 后端 ApiError(400) → 展示错误不崩', async () => {
    vi.mocked(createAlertRule).mockRejectedValue(new ApiError(400, '非法 metric'))
    const wrapper = mount(AlertRuleFormDialog, { props: { open: true, rule: null } })
    await flushPromises()

    const inputs = wrapper.findAllComponents(Input)
    await inputs.find(i => i.attributes('placeholder') === '如：CPU 高负载告警')!.setValue('新规则')
    await inputs.find(i => i.attributes('placeholder') === '如 85')!.setValue('90')
    const submitBtn = wrapper.findAllComponents(Button).find(b => b.attributes('type') === 'submit')!
    await submitBtn.trigger('click')
    await flushPromises()

    expect(createAlertRule).toHaveBeenCalledTimes(1)
    expect(handleErrorMock).toHaveBeenCalled()
    // 组件仍存活，不崩。
    expect(wrapper.findComponent(AlertRuleFormDialog).exists()).toBe(true)
    wrapper.unmount()
  })
})

describe('alertRulesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listAlertRules).mockResolvedValue({ items: [makeRule()], total: 1 })
    vi.mocked(deleteAlertRule).mockResolvedValue(undefined)
  })

  it('(e) 删除走二次确认后 → 调 deleteAlertRule', async () => {
    const { AlertDialogAction } = await import('~/components/ui/alert-dialog')
    const wrapper = withQuery(AlertRulesPanel)
    await flushPromises()
    expect(wrapper.text()).toContain('CPU 高负载告警')

    // 打开删除确认。
    await wrapper.find('[aria-label="删除规则"]').trigger('click')
    await flushPromises()

    // 确认按钮（teleport，用 findComponent 在组件树定位）。
    await wrapper.findComponent(AlertDialogAction).trigger('click')
    await flushPromises()

    expect(deleteAlertRule).toHaveBeenCalledWith(5)
    wrapper.unmount()
  })
})
