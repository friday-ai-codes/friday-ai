/**
 * IngestPanel 守护测试（Plan 32-03，ING-01 / 32-UI-SPEC AC 第 9 条）。
 *
 * 以**真实** `zh-CN.json` 注入 i18n（防关键文案被改空），mock `ingestApi` + 装配 vue-query。
 * 覆盖：
 * (a) 渲染标题 / CTA / 三步骤名 / 三状态文案（真实 zh-CN.json 锁定）；
 * (b) 空提交 → 内联 errorRequired，未调 dispatch；
 * (c) 合法提交 → dispatch(board, mr)，run_id 后轮询 getRun 三步 ok → 完成提示；
 * (d) completed + 含 failed/skipped 步 → partial 提示 + 该步 error；
 * (e) getRun 报错 → loadError 行（不清空结果）。
 */
import type { IngestRun } from '~/api/ingest'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import IngestPanel from '../IngestPanel.vue'

// ---- mocks ----
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: vi.fn() }),
}))
vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))
vi.mock('~/api/ingest', () => ({
  ingestApi: {
    dispatch: vi.fn(),
    getRun: vi.fn(),
  },
}))

const { ingestApi } = await import('~/api/ingest')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function mountPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(IngestPanel, {
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function makeRun(overrides: Partial<IngestRun> = {}): IngestRun {
  return {
    run_id: 'run-1',
    status: 'completed',
    steps: {
      work_item: { status: 'ok', identifier: 'WI-100' },
      document: { status: 'ok', identifier: 'DOC-1' },
      mr_diff: { status: 'ok', identifier: 'arch-9' },
    },
    ...overrides,
  }
}

describe('ingestPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('a: 真实 zh-CN.json 锁定标题 / CTA / 三步骤名 / 三状态文案（被改空即失败）', () => {
    // 直接断言真实 messages（最强守护：copy 被清空/改名即红）
    expect(zhCN.ingest.title).toBe('一键摄取')
    expect(zhCN.ingest.form.submit).toBe('开始摄取')
    expect(zhCN.ingest.steps.workItem).toBe('工作项')
    expect(zhCN.ingest.steps.document).toBe('PRD / 技术方案文档')
    expect(zhCN.ingest.steps.mrDiff).toBe('MR diff')
    expect(zhCN.ingest.status.ok).toBe('成功')
    expect(zhCN.ingest.status.failed).toBe('失败')
    expect(zhCN.ingest.status.skipped).toBe('已跳过')
    expect(zhCN.ingest.status.pending).toBe('等待中')

    // 渲染层：标题 + CTA 实际出现在页面
    const wrapper = mountPanel()
    const text = wrapper.text()
    expect(text).toContain('一键摄取')
    expect(text).toContain('开始摄取')
    // 空态文案
    expect(text).toContain('尚未发起摄取')
  })

  it('b: 空提交 → 内联 errorRequired，未调 dispatch', async () => {
    const wrapper = mountPanel()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('请输入链接')
    expect(ingestApi.dispatch).not.toHaveBeenCalled()
  })

  it('c: 合法提交 → dispatch(board, mr)，轮询渲染三步 ok + 完成提示', async () => {
    vi.mocked(ingestApi.dispatch).mockResolvedValue({ run_id: 'run-1', dispatched: true })
    vi.mocked(ingestApi.getRun).mockResolvedValue(makeRun())

    const wrapper = mountPanel()
    await wrapper.find('[data-testid="ingest-board-url"]').setValue('https://project.feishu.cn/x/story/detail/1')
    await wrapper.find('[data-testid="ingest-mr-url"]').setValue('https://gitlab.example.com/g/r/-/merge_requests/1')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(ingestApi.dispatch).toHaveBeenCalledWith(
      'https://project.feishu.cn/x/story/detail/1',
      'https://gitlab.example.com/g/r/-/merge_requests/1',
    )

    // run_id 后开启查询，拉取 getRun
    await flushPromises()
    await flushPromises()

    expect(ingestApi.getRun).toHaveBeenCalledWith('run-1')
    const text = wrapper.text()
    expect(text).toContain('摄取完成，相关内容已可检索')
    expect(text).toContain('工作项')
    expect(text).toContain('PRD / 技术方案文档')
    expect(text).toContain('MR diff')
    expect(text).toContain('成功')
  })

  it('d: completed + 含 failed/skipped 步 → partial 提示 + 该步 error', async () => {
    vi.mocked(ingestApi.dispatch).mockResolvedValue({ run_id: 'run-2', dispatched: true })
    vi.mocked(ingestApi.getRun).mockResolvedValue(makeRun({
      run_id: 'run-2',
      steps: {
        work_item: { status: 'ok', identifier: 'WI-1' },
        document: { status: 'failed', error: '文档解析失败' },
        mr_diff: { status: 'skipped', error: 'MR 未匹配仓库' },
      },
    }))

    const wrapper = mountPanel()
    await wrapper.find('[data-testid="ingest-board-url"]').setValue('https://feishu.cn/a/detail/1')
    await wrapper.find('[data-testid="ingest-mr-url"]').setValue('https://gitlab.example.com/g/r/-/merge_requests/2')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('部分步骤未完成')
    expect(text).toContain('失败')
    expect(text).toContain('已跳过')
    expect(text).toContain('文档解析失败')
    expect(text).toContain('MR 未匹配仓库')
  })

  it('e: getRun 报错 → loadError 行', async () => {
    vi.mocked(ingestApi.dispatch).mockResolvedValue({ run_id: 'run-3', dispatched: true })
    vi.mocked(ingestApi.getRun).mockRejectedValue(new Error('boom'))

    const wrapper = mountPanel()
    await wrapper.find('[data-testid="ingest-board-url"]').setValue('https://feishu.cn/a/detail/1')
    await wrapper.find('[data-testid="ingest-mr-url"]').setValue('https://gitlab.example.com/g/r/-/merge_requests/3')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await flushPromises()
    await flushPromises()

    expect(wrapper.find('[data-testid="ingest-load-error"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('加载摄取状态失败，请稍后重试')
  })
})
