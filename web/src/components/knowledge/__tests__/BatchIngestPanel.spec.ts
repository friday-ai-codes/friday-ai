/**
 * BatchIngestPanel 守护测试（Plan 62-03，CRAWL-02 + 62-UI-SPEC）。
 *
 * 覆盖：
 * (a) 列表从后端 list 端点恢复 → 渲染 crawl-queue-item，状态徽标文案取自真实 zh-CN.json
 *     （T-62-08：关键状态/动作措辞不被改空）；不依赖任何内存 batchId。
 * (b) 行内 start/stop/retry → 分别调 ingestApi.startRun/stopRun/retryRun；
 *     stop 触发 useConfirmDialog 破坏性确认（variant=destructive + 真实停止确认措辞）。
 * (c) feishu_not_configured → 渲染 crawl-feishu-deeplink 引导（既有行为不回退）。
 */
import type { CrawlQueueItem, CrawlResult } from '~/api/ingest'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import BatchIngestPanel from '../BatchIngestPanel.vue'

// ---- mocks ----
const confirmMock = vi.fn<(opts: unknown) => Promise<boolean>>()
vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: confirmMock }),
}))
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), warning: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('~/api/ingest', () => ({
  ingestApi: {
    listQueue: vi.fn(),
    enqueueQueue: vi.fn(),
    crawlUrl: vi.fn(),
    startRun: vi.fn(),
    stopRun: vi.fn(),
    retryRun: vi.fn(),
  },
}))

const { ingestApi } = await import('~/api/ingest')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeItem(overrides: Partial<CrawlQueueItem> = {}): CrawlQueueItem {
  return {
    batch_id: '11111111-1111-1111-1111-111111111111',
    status: 'queued',
    total: 3,
    done: 1,
    url_count: 3,
    durable_job_id: 'job-1',
    idempotency_key: 'crawl_ingest:11111111-1111-1111-1111-111111111111',
    started_at: '2026-06-20T13:20:00Z',
    updated_at: '2026-06-20T13:42:00Z',
    error: '',
    ...overrides,
  }
}

function mountPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(BatchIngestPanel, {
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

describe('batchIngestPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.mockResolvedValue(true)
  })

  it('a: 列表从后端恢复 → 渲染各状态项，徽标文案取自真实 zh-CN.json（不依赖内存 batchId）', async () => {
    vi.mocked(ingestApi.listQueue).mockResolvedValue([
      makeItem({ batch_id: 'b-queued', status: 'queued' }),
      makeItem({ batch_id: 'b-running', status: 'running' }),
      makeItem({ batch_id: 'b-stopped', status: 'stopped' }),
      makeItem({ batch_id: 'b-failed', status: 'failed', error: '抓取超时' }),
      makeItem({ batch_id: 'b-completed', status: 'completed' }),
    ])
    const wrapper = mountPanel()
    await flushPromises()

    // 列表项数 = 后端返回项数（DB 真相源）。
    expect(wrapper.findAll('[data-testid="crawl-queue-item"]').length).toBe(5)

    // 状态徽标文案锁真实 zh-CN.json（关键措辞不被改空）。
    const text = wrapper.text()
    expect(text).toContain('排队中')
    expect(text).toContain('进行中')
    expect(text).toContain('已停止')
    expect(text).toContain('失败')
    expect(text).toContain('已完成')

    // failed 项展开后端 error 红字。
    expect(text).toContain('失败原因：抓取超时')
  })

  it('b1: 点击「开始」→ 调 ingestApi.startRun(batch_id)', async () => {
    vi.mocked(ingestApi.listQueue).mockResolvedValue([
      makeItem({ batch_id: 'b-stopped', status: 'stopped' }),
    ])
    vi.mocked(ingestApi.startRun).mockResolvedValue({ batch_id: 'b-stopped', action: 'start', dispatched: true })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="crawl-item-start"]').trigger('click')
    await flushPromises()

    expect(ingestApi.startRun).toHaveBeenCalledWith('b-stopped')
    expect(confirmMock).not.toHaveBeenCalled()
  })

  it('b2: 点击「停止」→ 破坏性确认（destructive + 真实措辞）→ 调 ingestApi.stopRun(batch_id)', async () => {
    vi.mocked(ingestApi.listQueue).mockResolvedValue([
      makeItem({ batch_id: 'b-running', status: 'running' }),
    ])
    vi.mocked(ingestApi.stopRun).mockResolvedValue({ batch_id: 'b-running', action: 'stop', stopped: 1 })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="crawl-item-stop"]').trigger('click')
    await flushPromises()

    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      variant: 'destructive',
      confirmText: '停止任务',
    }))
    const confirmArg = confirmMock.mock.calls[0][0] as { description: string }
    expect(confirmArg.description).toContain('幂等可重投')
    expect(ingestApi.stopRun).toHaveBeenCalledWith('b-running')
  })

  it('b2b: 停止确认被取消 → 不调 stopRun', async () => {
    confirmMock.mockResolvedValue(false)
    vi.mocked(ingestApi.listQueue).mockResolvedValue([
      makeItem({ batch_id: 'b-running', status: 'running' }),
    ])
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="crawl-item-stop"]').trigger('click')
    await flushPromises()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(ingestApi.stopRun).not.toHaveBeenCalled()
  })

  it('b3: 点击「重试」→ 调 ingestApi.retryRun(batch_id)（非破坏性，无确认）', async () => {
    vi.mocked(ingestApi.listQueue).mockResolvedValue([
      makeItem({ batch_id: 'b-completed', status: 'completed' }),
    ])
    vi.mocked(ingestApi.retryRun).mockResolvedValue({ batch_id: 'b-completed', action: 'retry', dispatched: true })
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="crawl-item-retry"]').trigger('click')
    await flushPromises()

    expect(ingestApi.retryRun).toHaveBeenCalledWith('b-completed')
    expect(confirmMock).not.toHaveBeenCalled()
  })

  it('c: feishu_not_configured → 渲染引导深链（既有行为不回退）', async () => {
    vi.mocked(ingestApi.listQueue).mockResolvedValue([])
    vi.mocked(ingestApi.crawlUrl).mockResolvedValue({
      status: 'feishu_not_configured',
      source_kind: 'feishu_doc',
      items: [],
      message: '尚未配置飞书应用，无法抓取该链接',
      settings_deeplink: '/admin#integration',
    } as CrawlResult)
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('[data-testid="crawl-url-input"]').setValue('https://x.feishu.cn/docx/abc')
    await wrapper.find('[data-testid="crawl-enqueue-button"]').trigger('click')
    await flushPromises()

    expect(ingestApi.crawlUrl).toHaveBeenCalledWith('https://x.feishu.cn/docx/abc')
    expect(ingestApi.enqueueQueue).not.toHaveBeenCalled()
    const deeplink = wrapper.find('[data-testid="crawl-feishu-deeplink"]')
    expect(deeplink.exists()).toBe(true)
    expect(wrapper.text()).toContain('尚未配置飞书应用，无法抓取该链接')
    expect(wrapper.text()).toContain('去配置飞书应用')
  })
})
