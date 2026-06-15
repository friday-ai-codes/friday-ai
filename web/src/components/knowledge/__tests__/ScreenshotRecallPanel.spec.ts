/**
 * ScreenshotRecallPanel 守护测试（Plan 35-02，VIS-01 / 35-UI-SPEC AC 末条）。
 *
 * 以**真实** `zh-CN.json` 注入 i18n（防关键文案被改空），mock `screenshotRecallApi`
 * + useToast/useErrorHandler + 装配 vue-query。覆盖：
 * (a) 真实 zh-CN.json 锁标题 / 校验 / degraded / noResults / error 文案；
 * (b) 非图片 File → invalidType，不调 recall；
 * (c) >10MB File → tooLarge，不调 recall；
 * (d) 合法图片提交 → recall 调一次 + success 渲染召回项；
 * (e) degraded → amber 卡片 + settingsLink，且不弹 error toast；
 * (f) no-results → search-x 空态；
 * (g) recall reject → error 文案 + handleError。
 */
import type { ScreenshotRecallResult } from '~/api/screenshotRecall'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import ScreenshotRecallPanel from '../ScreenshotRecallPanel.vue'

// ---- hoisted mock handles（供断言「不弹 error toast / 调 handleError」） ----
const { toastErrorMock, handleErrorMock } = vi.hoisted(() => ({
  toastErrorMock: vi.fn(),
  handleErrorMock: vi.fn(),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ error: toastErrorMock, success: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: handleErrorMock }),
}))
vi.mock('~/api/screenshotRecall', () => ({
  screenshotRecallApi: {
    recall: vi.fn(),
  },
}))

const { screenshotRecallApi } = await import('~/api/screenshotRecall')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

// 轻量 RouterLink 桩：渲染 <a> 暴露 to/data-testid，避免引入完整 vue-router（UX-2）。
const RouterLinkStub = {
  name: 'RouterLink',
  props: { to: { type: [String, Object], required: true } },
  template: '<a :data-to="typeof to === \'string\' ? to : JSON.stringify(to)"><slot /></a>',
}

function mountPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return mount(ScreenshotRecallPanel, {
    global: {
      plugins: [i18n, [VueQueryPlugin, { queryClient }]],
      stubs: { RouterLink: RouterLinkStub },
    },
  })
}

function makeFile(name: string, type: string, size: number): File {
  const f = new File(['x'], name, { type })
  Object.defineProperty(f, 'size', { value: size, configurable: true })
  return f
}

async function selectFile(wrapper: ReturnType<typeof mountPanel>, f: File) {
  const input = wrapper.find('[data-testid="recall-file-input"]')
  Object.defineProperty(input.element, 'files', { value: [f], configurable: true })
  await input.trigger('change')
  await flushPromises()
}

function makeResult(overrides: Partial<ScreenshotRecallResult> = {}): ScreenshotRecallResult {
  return {
    degraded: false,
    results: [],
    ...overrides,
  }
}

describe('screenshotRecallPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // happy-dom 不一定提供 objectURL，桩入避免预览创建/释放报错。
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock')
    globalThis.URL.revokeObjectURL = vi.fn()
  })

  it('a: 真实 zh-CN.json 锁关键文案（被改空即失败）', () => {
    expect(zhCN.screenshotRecall.title).toBe('截图识需求')
    expect(zhCN.screenshotRecall.validation.invalidType).toBe('请上传图片文件（PNG / JPEG / WebP）')
    expect(zhCN.screenshotRecall.validation.tooLarge).toBe('图片超过 10 MB，请压缩后重试')
    expect(zhCN.screenshotRecall.degraded.title).toBe('未配置多模态（vision）模型')
    expect(zhCN.screenshotRecall.degraded.body.length).toBeGreaterThan(0)
    expect(zhCN.screenshotRecall.degraded.settingsLink).toBe('前往系统设置')
    expect(zhCN.screenshotRecall.noResults.title).toBe('未召回到相关需求')
    expect(zhCN.screenshotRecall.error.length).toBeGreaterThan(0)

    const wrapper = mountPanel()
    const text = wrapper.text()
    expect(text).toContain('截图识需求')
    expect(text).toContain('尚未上传截图')
  })

  it('b: 非图片 File → invalidType 内联文案，未调 recall', async () => {
    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('note.txt', 'text/plain', 1024))

    expect(wrapper.find('[data-testid="recall-validation"]').text()).toBe(
      zhCN.screenshotRecall.validation.invalidType,
    )
    expect(screenshotRecallApi.recall).not.toHaveBeenCalled()
    expect(toastErrorMock).toHaveBeenCalled()
  })

  it('c: >10MB File → tooLarge 内联文案，未调 recall', async () => {
    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('big.png', 'image/png', 11 * 1024 * 1024))

    expect(wrapper.find('[data-testid="recall-validation"]').text()).toBe(
      zhCN.screenshotRecall.validation.tooLarge,
    )
    expect(screenshotRecallApi.recall).not.toHaveBeenCalled()
  })

  it('d: 合法图片提交 → recall 调一次 + success 召回项渲染', async () => {
    vi.mocked(screenshotRecallApi.recall).mockResolvedValue(makeResult({
      results: [{ work_item_id: 'WI-1', title: '登录页改版需求', relevance: 0.92, link: 'https://feishu.cn/x/1' }],
    }))

    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('shot.png', 'image/png', 2048))
    await wrapper.find('[data-testid="recall-submit"]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(screenshotRecallApi.recall).toHaveBeenCalledTimes(1)
    const item = wrapper.find('[data-testid="recall-item-0"]')
    expect(item.exists()).toBe(true)
    expect(item.text()).toContain('登录页改版需求')
    expect(item.text()).toContain('WI-1')
  })

  it('e: degraded → amber 卡片 + settingsLink，不弹 error toast', async () => {
    vi.mocked(screenshotRecallApi.recall).mockResolvedValue(makeResult({
      degraded: true,
      degraded_reason: 'no vision model',
      results: [],
    }))

    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('shot.png', 'image/png', 2048))
    await wrapper.find('[data-testid="recall-submit"]').trigger('click')
    await flushPromises()
    await flushPromises()

    const degraded = wrapper.find('[data-testid="recall-degraded"]')
    expect(degraded.exists()).toBe(true)
    expect(degraded.text()).toContain(zhCN.screenshotRecall.degraded.title)
    // UX-2：走 RouterLink（SPA 导航），to=/admin，而非整页刷新的裸 <a href>。
    const link = wrapper.findComponent(RouterLinkStub)
    expect(link.exists()).toBe(true)
    expect(link.props('to')).toBe('/admin')
    // 降级非错误：不弹 error toast、不走 handleError、无 error 行
    expect(handleErrorMock).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid="recall-error"]').exists()).toBe(false)
  })

  it('e2: degraded(extraction_failed) → 重试文案，不渲染系统设置入口（WR-01）', async () => {
    vi.mocked(screenshotRecallApi.recall).mockResolvedValue(makeResult({
      degraded: true,
      degraded_code: 'extraction_failed',
      results: [],
    }))

    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('shot.png', 'image/png', 2048))
    await wrapper.find('[data-testid="recall-submit"]').trigger('click')
    await flushPromises()
    await flushPromises()

    const degraded = wrapper.find('[data-testid="recall-degraded"]')
    expect(degraded.exists()).toBe(true)
    expect(degraded.text()).toContain(zhCN.screenshotRecall.degraded.extractionFailedTitle)
    // 运行期失败：不引导去系统设置（配置无误）。
    expect(wrapper.find('[data-testid="recall-degraded-link"]').exists()).toBe(false)
  })

  it('d2: success → 回显派生检索词，且死 key results.source 已移除（UX-3）', async () => {
    vi.mocked(screenshotRecallApi.recall).mockResolvedValue(makeResult({
      query: '登录页\n用户认证',
      results: [{ work_item_id: 'WI-9', title: '登录改版', relevance: 0.5 }],
    }))

    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('shot.png', 'image/png', 2048))
    await wrapper.find('[data-testid="recall-submit"]').trigger('click')
    await flushPromises()
    await flushPromises()

    const queryEl = wrapper.find('[data-testid="recall-query"]')
    expect(queryEl.exists()).toBe(true)
    expect(queryEl.text()).toContain('登录页')
    // 死 key 已清理（防止回归）。
    expect((zhCN.screenshotRecall.results as Record<string, unknown>).source).toBeUndefined()
  })

  it('f: no-results → search-x 空态', async () => {
    vi.mocked(screenshotRecallApi.recall).mockResolvedValue(makeResult({ degraded: false, results: [] }))

    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('shot.png', 'image/png', 2048))
    await wrapper.find('[data-testid="recall-submit"]').trigger('click')
    await flushPromises()
    await flushPromises()

    const noResults = wrapper.find('[data-testid="recall-no-results"]')
    expect(noResults.exists()).toBe(true)
    expect(noResults.text()).toContain(zhCN.screenshotRecall.noResults.title)
  })

  it('g: recall reject → error 文案 + handleError', async () => {
    vi.mocked(screenshotRecallApi.recall).mockRejectedValue(new Error('boom'))

    const wrapper = mountPanel()
    await selectFile(wrapper, makeFile('shot.png', 'image/png', 2048))
    await wrapper.find('[data-testid="recall-submit"]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[data-testid="recall-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.screenshotRecall.error)
    expect(handleErrorMock).toHaveBeenCalled()
    // UX-1：首次失败时 error 与 empty 互斥，空态不应同时渲染。
    expect(wrapper.find('[data-testid="recall-empty"]').exists()).toBe(false)
  })
})
