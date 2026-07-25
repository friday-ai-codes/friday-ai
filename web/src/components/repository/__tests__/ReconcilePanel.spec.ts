/**
 * ReconcilePanel 守护测试（Plan 23-04，EXCL-06 / W1/W2/W3 / §9.1/§9.2）。
 *
 * 覆盖：
 * (a) 有 excluded_paths → 渲染 match_count + 列表；
 * (b) degraded:true → 渲染「对账不可信」警示、不渲染空态/已一致、清理按钮禁用（W3）；
 * (c) 普通清理 → 确认 → 调 cleanup(repoId,'normal')，成功后 reconcile 重查 match_count==0 → 空态（差异归零）；
 * (d) 敏感清理 → 强确认（destructive + 不可逆/不承诺物理消失措辞）→ cleanup(repoId,'sensitive')，
 *     派发后经 getCleanupStatus 返回 sensitive.unscrubbed + caveat → 渲染真实未清面 + caveat（W1/W2）；
 * (e) 空态正确渲染。
 */
import type { CleanupRun, ReconcileReport } from '~/api/reconcile'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import zhCN from '~/locales/zh-CN.json'
import ReconcilePanel from '../ReconcilePanel.vue'

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
vi.mock('~/api/reconcile', () => ({
  reconcileApi: {
    getReconcile: vi.fn(),
    cleanup: vi.fn(),
    getCleanupStatus: vi.fn(),
  },
}))

const { reconcileApi } = await import('~/api/reconcile')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN as any },
})

function makeReport(overrides: Partial<ReconcileReport> = {}): ReconcileReport {
  return {
    indexed_count: 10,
    excluded_paths: [],
    match_count: 0,
    suggested_mode: 'normal',
    degraded: false,
    error: '',
    ...overrides,
  }
}

function mountPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(ReconcilePanel, {
    props: { repositoryId: 'repo-1' },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

function findButton(wrapper: ReturnType<typeof mountPanel>, text: string) {
  return wrapper.findAll('button').find(b => b.text().includes(text))
}

describe('reconcilePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.mockResolvedValue(true)
    vi.mocked(reconcileApi.getCleanupStatus).mockResolvedValue({ status: 'none' } as CleanupRun)
  })

  it('a: 有差异 → 渲染 match_count + excluded_paths 列表', async () => {
    vi.mocked(reconcileApi.getReconcile).mockResolvedValue(makeReport({
      match_count: 2,
      excluded_paths: ['*.env', 'secrets/key.pem'],
    }))
    const wrapper = mountPanel()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('已索引但现命中排除规则的文件')
    expect(text).toContain('2')
    expect(text).toContain('*.env')
    expect(text).toContain('secrets/key.pem')
  })

  it('b: degraded → 「对账不可信」警示、不渲染空态/已一致、清理按钮禁用（W3）', async () => {
    vi.mocked(reconcileApi.getReconcile).mockResolvedValue(makeReport({
      degraded: true,
      error: 'matcher build failed',
    }))
    const wrapper = mountPanel()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('对账不可信')
    // 不渲染空态/已一致
    expect(text).not.toContain('无差异，已索引内容与当前排除规则一致')
    // 双清理按钮均禁用
    const normalBtn = findButton(wrapper, '普通清理')
    const sensitiveBtn = findButton(wrapper, '敏感清理')
    expect(normalBtn?.attributes('disabled')).toBeDefined()
    expect(sensitiveBtn?.attributes('disabled')).toBeDefined()
  })

  it('c: 普通清理 → 确认 → cleanup(repoId,normal)，重查后差异归零 → 空态', async () => {
    vi.mocked(reconcileApi.getReconcile)
      .mockResolvedValueOnce(makeReport({ match_count: 1, excluded_paths: ['*.env'] }))
      .mockResolvedValue(makeReport({ match_count: 0, excluded_paths: [] }))
    vi.mocked(reconcileApi.cleanup).mockResolvedValue({
      mode: 'normal',
      match_count: 1,
      dispatched: true,
      run_id: 'run-1',
    })
    vi.mocked(reconcileApi.getCleanupStatus).mockResolvedValue({
      status: 'completed',
      mode: 'normal',
      match_count: 1,
      sensitive: null,
    } as CleanupRun)

    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('*.env')

    await findButton(wrapper, '普通清理')!.trigger('click')
    await flushPromises()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(reconcileApi.cleanup).toHaveBeenCalledWith('repo-1', 'normal')

    // 重查使差异归零 → 渲染空态
    await flushPromises()
    expect(wrapper.text()).toContain('无差异，已索引内容与当前排除规则一致')
  })

  it('d: 敏感清理 → 强确认(不可逆/不承诺物理消失) → cleanup(sensitive)，状态端点回显真实 unscrubbed + caveat（W1/W2）', async () => {
    vi.mocked(reconcileApi.getReconcile).mockResolvedValue(makeReport({
      match_count: 1,
      excluded_paths: ['secrets/key.pem'],
    }))
    vi.mocked(reconcileApi.cleanup).mockResolvedValue({
      mode: 'sensitive',
      match_count: 1,
      dispatched: true,
      run_id: 'run-2',
    })
    vi.mocked(reconcileApi.getCleanupStatus).mockResolvedValue({
      status: 'completed',
      mode: 'sensitive',
      match_count: 1,
      sensitive: {
        scrubbed: { code_change_archive: { scrubbed: 3, deleted: 1 } },
        unscrubbed: ['prompt_snapshot', 'backups', 'git_objects'],
        caveat: '本地 git object 与 Git 历史不承诺物理消失',
        errors: [],
      },
    } as CleanupRun)

    const wrapper = mountPanel()
    await flushPromises()

    await findButton(wrapper, '敏感清理')!.trigger('click')
    await flushPromises()

    // 强确认：destructive + 如实措辞
    expect(confirmMock).toHaveBeenCalledWith(expect.objectContaining({
      variant: 'destructive',
      description: expect.stringContaining('不可逆'),
    }))
    const confirmArg = confirmMock.mock.calls[0][0] as { description: string }
    expect(confirmArg.description).toContain('不承诺从 git 历史或备份中物理消失')
    expect(reconcileApi.cleanup).toHaveBeenCalledWith('repo-1', 'sensitive')

    // 状态端点回显真实未清面 + caveat（非静态文案）
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('以下内容未能清除')
    expect(text).toContain('prompt_snapshot')
    expect(text).toContain('git_objects')
    expect(text).toContain('本地 git object 与 Git 历史不承诺物理消失')
  })

  it('e: 空态 → 渲染「无差异，已索引内容与当前排除规则一致」', async () => {
    vi.mocked(reconcileApi.getReconcile).mockResolvedValue(makeReport({ match_count: 0 }))
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('无差异，已索引内容与当前排除规则一致')
  })
})
