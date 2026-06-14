/**
 * SensitiveSuggestionsPanel 守护测试（Plan 24-04，EXCL-03 / T-24-13/14/15）。
 *
 * 覆盖：
 * (a) list 含 real_secret + likely_sensitive → 渲染两行 + real_secret 高优先级告警（断真实 zh-CN 文案，防被改空）；
 * (b) 点击接受 → 触发 accept(repoId,id)，确认弹窗含「不会自动删除 / 需在清理面板显式执行」措辞（防过度删除承诺，T-24-14）；
 * (c) 点击忽略 → 触发 dismiss，列表 invalidate 后该建议消失；
 * (d) 空 suggestions → 渲染空态、无告警。
 */
import type { SensitiveActionResponse, SensitiveSuggestion, SensitiveSuggestionListResponse } from '~/api/sensitiveSuggestions'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import SensitiveSuggestionsPanel from '../SensitiveSuggestionsPanel.vue'

// ---- mocks ----
const confirmMock = vi.fn<(opts: unknown) => Promise<boolean>>()
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: confirmMock }),
}))
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
vi.mock('~/api/sensitiveSuggestions', () => ({
  sensitiveSuggestionsApi: {
    list: vi.fn(),
    accept: vi.fn(),
    dismiss: vi.fn(),
  },
}))

const { sensitiveSuggestionsApi } = await import('~/api/sensitiveSuggestions')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeSuggestion(overrides: Partial<SensitiveSuggestion> = {}): SensitiveSuggestion {
  return {
    id: 'sug-1',
    path: 'config/app.env',
    severity: 'likely_sensitive',
    detector: 'heuristic',
    reason: '命中 .env 文件名规则（第 1 行）',
    status: 'pending',
    detected_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
    ...overrides,
  }
}

function makeList(suggestions: SensitiveSuggestion[]): SensitiveSuggestionListResponse {
  return { suggestions }
}

function mountPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(SensitiveSuggestionsPanel, {
    props: { repoId: 'repo-1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function findButton(wrapper: ReturnType<typeof mountPanel>, text: string) {
  return wrapper.findAll('button').find(b => b.text().includes(text))
}

describe('sensitiveSuggestionsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.mockResolvedValue(true)
  })

  it('a: real_secret + likely_sensitive → 渲染两行 + real_secret 高优先级告警', async () => {
    vi.mocked(sensitiveSuggestionsApi.list).mockResolvedValue(makeList([
      makeSuggestion({ id: 'r1', path: 'secrets/prod.key', severity: 'real_secret', detector: 'content', reason: '命中 AWS Access Key 模式（第 3 行）' }),
      makeSuggestion({ id: 'l1', path: 'config/app.env', severity: 'likely_sensitive' }),
    ]))
    const wrapper = mountPanel()
    await flushPromises()
    const text = wrapper.text()
    // 两行路径都在
    expect(text).toContain('secrets/prod.key')
    expect(text).toContain('config/app.env')
    // real_secret 告警（断真实 zh-CN 文案，防被改空）
    expect(wrapper.find('[data-testid="real-secret-alert"]').exists()).toBe(true)
    expect(text).toContain('检测到真实密钥，高优先级')
    expect(text).toContain('真实密钥')
    expect(text).toContain('疑似敏感')
  })

  it('b: 点击接受 → accept(repoId,id)，确认弹窗含「不自动删 / 显式清理」措辞', async () => {
    vi.mocked(sensitiveSuggestionsApi.list).mockResolvedValue(makeList([
      makeSuggestion({ id: 'sug-9', path: 'config/app.env' }),
    ]))
    vi.mocked(sensitiveSuggestionsApi.accept).mockResolvedValue({
      suggestion: makeSuggestion({ id: 'sug-9', status: 'accepted' }),
      rule: { id: 'rule-1', pattern: 'config/app.env', rule_type: 'glob', source: 'ai_suggested' },
      cleanup_available: true,
    } as SensitiveActionResponse)

    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '接受')!.trigger('click')
    await flushPromises()

    // 确认弹窗明示「不会自动删除 + 需在清理面板显式执行」（T-24-14）
    expect(confirmMock).toHaveBeenCalledTimes(1)
    const confirmArg = confirmMock.mock.calls[0][0] as { description: string }
    expect(confirmArg.description).toContain('不会自动删除')
    expect(confirmArg.description).toContain('显式执行')
    // accept 入参断言
    expect(sensitiveSuggestionsApi.accept).toHaveBeenCalledWith('repo-1', 'sug-9')
  })

  it('c: 点击忽略 → dismiss，invalidate 后该建议消失', async () => {
    vi.mocked(sensitiveSuggestionsApi.list)
      .mockResolvedValueOnce(makeList([makeSuggestion({ id: 'sug-x', path: 'config/app.env' })]))
      .mockResolvedValue(makeList([]))
    vi.mocked(sensitiveSuggestionsApi.dismiss).mockResolvedValue({
      suggestion: makeSuggestion({ id: 'sug-x', status: 'dismissed' }),
    } as SensitiveActionResponse)

    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('config/app.env')

    await findButton(wrapper, '忽略')!.trigger('click')
    await flushPromises()

    expect(sensitiveSuggestionsApi.dismiss).toHaveBeenCalledWith('repo-1', 'sug-x')
    // invalidate 重查返回空 → 该建议消失，渲染空态
    await flushPromises()
    expect(wrapper.text()).not.toContain('config/app.env')
    expect(wrapper.text()).toContain('暂无待处理的敏感文件建议')
  })

  it('d: 空 suggestions → 渲染空态、无告警', async () => {
    vi.mocked(sensitiveSuggestionsApi.list).mockResolvedValue(makeList([]))
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('暂无待处理的敏感文件建议')
    expect(wrapper.find('[data-testid="real-secret-alert"]').exists()).toBe(false)
  })
})
