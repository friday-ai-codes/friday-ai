/**
 * RepositoryGraphCard 单元测试（ / GRAPH-）
 *
 * 覆盖 UI-SPEC §8.1 的 6 类核心断言：
 *  1. StatusBadge 按 graph_build_status 渲染（type=graph + 5 态）
 *  2. idle 态显示「立即构建」，不显示「停止构建」
 *  3. running 态显示「停止构建」，不显示「立即构建」
 *  4. Header 嵌入 GraphAutoBuildToggle 且 initial 透传
 *  5. SSE progress 帧到达后进度条 / current_file 视图更新
 *  6. 「只清图谱」AlertDialog 二次确认 → 确认调 deleteGraph；onError 启 polling 兜底；
 *     「立即构建」点击调 rebuildGraph
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { deleteGraph, listGraphHistory, rebuildGraph } from '~/api/codegraph'
import { repositoriesApi } from '~/api/repositories'
import RepositoryGraphCard from '../RepositoryGraphCard.vue'

vi.mock('~/api/codegraph', () => ({
  rebuildGraph: vi.fn(),
  cancelGraphBuild: vi.fn(),
  deleteGraph: vi.fn(),
  listGraphHistory: vi.fn().mockResolvedValue({
    results: [],
    count: 0,
    next: null,
    previous: null,
  }),
}))

vi.mock('~/api/repositories', () => ({
  repositoriesApi: {
    get: vi.fn(),
    update: vi.fn(),
  },
}))

let mockOnEvent: ((event: unknown) => void) | undefined
let mockOnError: ((err: Error) => void) | undefined
const mockAbort = vi.fn()

vi.mock('~/composables/useGraphBuildStream', () => ({
  connectGraphProgressStream: vi.fn((_repoId: string, opts: {
    onEvent: (event: unknown) => void
    onError?: (err: Error) => void
  }) => {
    mockOnEvent = opts.onEvent
    mockOnError = opts.onError
    return { abort: mockAbort } as unknown as AbortController
  }),
}))

const successSpy = vi.fn()
const errorSpy = vi.fn()
const handleErrorSpy = vi.fn()

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: successSpy, error: errorSpy }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: handleErrorSpy }),
}))

// ===== shadcn 组件 stub（避免 reka-ui provider 依赖） =====
const ButtonStub = defineComponent({
  name: 'Button',
  props: { disabled: { type: Boolean, default: false }, variant: { type: String, default: 'default' } },
  template: '<button :disabled="disabled" v-bind="$attrs"><slot /></button>',
})

const TooltipStub = defineComponent({ template: '<div><slot /></div>' })
const TooltipProviderStub = defineComponent({ template: '<div><slot /></div>' })
const TooltipTriggerStub = defineComponent({ template: '<div><slot /></div>' })
const TooltipContentStub = defineComponent({ template: '<div><slot /></div>' })

// AlertDialog：透传 open 控制，让 trigger 点击后 content 始终渲染
const AlertDialogStub = defineComponent({
  name: 'AlertDialog',
  props: { open: { type: Boolean, default: false } },
  emits: ['update:open'],
  template: '<div data-testid="alert-dialog"><slot /></div>',
})
const AlertDialogTriggerStub = defineComponent({
  name: 'AlertDialogTrigger',
  template: '<div data-testid="alert-dialog-trigger"><slot /></div>',
})
const AlertDialogContentStub = defineComponent({
  name: 'AlertDialogContent',
  template: '<div data-testid="alert-dialog-content"><slot /></div>',
})
const AlertDialogHeaderStub = defineComponent({ template: '<div><slot /></div>' })
const AlertDialogTitleStub = defineComponent({ template: '<div><slot /></div>' })
const AlertDialogDescriptionStub = defineComponent({ template: '<div><slot /></div>' })
const AlertDialogFooterStub = defineComponent({ template: '<div><slot /></div>' })
const AlertDialogCancelStub = defineComponent({
  name: 'AlertDialogCancel',
  template: '<button data-testid="alert-cancel"><slot /></button>',
})
const AlertDialogActionStub = defineComponent({
  name: 'AlertDialogAction',
  props: { disabled: { type: Boolean, default: false } },
  template: '<button data-testid="alert-action" :disabled="disabled" v-bind="$attrs"><slot /></button>',
})

// GraphAutoBuildToggle 也 stub（避免 Switch / Tooltip 依赖）
const GraphAutoBuildToggleStub = defineComponent({
  name: 'GraphAutoBuildToggle',
  props: {
    repositoryId: { type: String, required: true },
    initial: { type: Boolean, required: true },
  },
  template: '<div data-testid="graph-auto-build-toggle" :data-initial="initial" />',
})

const stubComponents = {
  Button: ButtonStub,
  Tooltip: TooltipStub,
  TooltipProvider: TooltipProviderStub,
  TooltipTrigger: TooltipTriggerStub,
  TooltipContent: TooltipContentStub,
  AlertDialog: AlertDialogStub,
  AlertDialogTrigger: AlertDialogTriggerStub,
  AlertDialogContent: AlertDialogContentStub,
  AlertDialogHeader: AlertDialogHeaderStub,
  AlertDialogTitle: AlertDialogTitleStub,
  AlertDialogDescription: AlertDialogDescriptionStub,
  AlertDialogFooter: AlertDialogFooterStub,
  AlertDialogCancel: AlertDialogCancelStub,
  AlertDialogAction: AlertDialogActionStub,
  GraphAutoBuildToggle: GraphAutoBuildToggleStub,
  // StatusBadge / Badge 走真实组件以验证 props 透传
}

function buildRepo(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 'repo-1',
    name: 't',
    auto_build_graph_enabled: true,
    graph_build_status: 'idle',
    graph_stage: '',
    current_graph_file: '',
    graph_files_processed: 0,
    graph_files_total: 0,
    graph_last_built_at: null,
    index_status: 'indexed',
    ...overrides,
  }
}

function mountCard() {
  return mount(RepositoryGraphCard, {
    props: { repositoryId: 'repo-1' },
    global: { stubs: stubComponents },
  })
}

describe('repositoryGraphCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockOnEvent = undefined
    mockOnError = undefined
    mockAbort.mockReset()
  })

  it('1: StatusBadge 按 graph_build_status 渲染（type=graph + completed）', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'completed', graph_last_built_at: '2026-05-18T10:00:00Z' }) as never,
    )
    const wrapper = mountCard()
    await flushPromises()
    const badge = wrapper.findComponent({ name: 'StatusBadge' })
    expect(badge.exists()).toBe(true)
    expect(badge.props('type')).toBe('graph')
    expect(badge.props('status')).toBe('completed')
  })

  it('2: idle 态显示「立即构建」按钮，不显示「停止构建」', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'idle' }) as never,
    )
    const wrapper = mountCard()
    await flushPromises()
    expect(wrapper.text()).toContain('立即构建')
    expect(wrapper.text()).not.toContain('停止构建')
  })

  it('3: running 态按钮组只显示「停止构建」，不渲染「立即构建」/「重新构建」按钮', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'running' }) as never,
    )
    const wrapper = mountCard()
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const buttonTexts = buttons.map(b => b.text())
    expect(buttonTexts.some(t => t.includes('停止构建'))).toBe(true)
    expect(buttonTexts.some(t => t.includes('立即构建'))).toBe(false)
    expect(buttonTexts.some(t => t.includes('重新构建'))).toBe(false)
  })

  it('4: Header 嵌入 GraphAutoBuildToggle 并透传 initial', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ auto_build_graph_enabled: false }) as never,
    )
    const wrapper = mountCard()
    await flushPromises()
    const toggle = wrapper.find('[data-testid="graph-auto-build-toggle"]')
    expect(toggle.exists()).toBe(true)
    expect(toggle.attributes('data-initial')).toBe('false')
  })

  it('5: SSE progress 帧到达后进度条 width 与 current_file 视图更新', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'running' }) as never,
    )
    const wrapper = mountCard()
    await flushPromises()
    expect(mockOnEvent).toBeTypeOf('function')

    mockOnEvent?.({
      type: 'progress',
      ts: 't',
      graph: {
        status: 'running',
        stage: 'building',
        files_processed: 30,
        files_total: 100,
        percent: 30,
        current_file: 'server/services/foo.py',
        started_at: null,
        edge_count_so_far: 0,
        error_message: '',
      },
    })
    await wrapper.vm.$nextTick()

    const progressbar = wrapper.find('[role="progressbar"]')
    expect(progressbar.exists()).toBe(true)
    expect(progressbar.attributes('aria-valuenow')).toBe('30')
    expect(progressbar.attributes('style') ?? '').toContain('width: 30%')
    expect(wrapper.text()).toContain('server/services/foo.py')
    expect(wrapper.text()).toContain('30%')
  })

  it('6a: 「只清图谱」二次确认 — 点击 AlertDialogAction 调 deleteGraph(repoId)', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'completed', graph_last_built_at: '2026-05-18T10:00:00Z' }) as never,
    )
    vi.mocked(deleteGraph).mockResolvedValue(undefined as never)
    vi.mocked(listGraphHistory).mockResolvedValue({
      results: [
        {
          id: 'h1',
          trigger_type: 'manual',
          status: 'completed',
          files_total: 1,
          files_processed: 1,
          files_failed: 0,
          symbols_count: 10,
          imports_count: 5,
          calls_count: 3,
          endpoints_count: 1,
          started_at: null,
          finished_at: null,
          error_message: '',
          created_at: '2026-05-18T10:00:00Z',
        },
      ],
      count: 1,
      next: null,
      previous: null,
    } as never)

    const wrapper = mountCard()
    await flushPromises()

    // AlertDialog stub 始终渲染 content，因此直接点 alert-action 模拟确认
    const action = wrapper.find('[data-testid="alert-action"]')
    expect(action.exists()).toBe(true)
    await action.trigger('click')
    await flushPromises()
    expect(deleteGraph).toHaveBeenCalledWith('repo-1')
    expect(successSpy).toHaveBeenCalledWith('已清空图谱数据')
  })

  it('6b: SSE onError 触发 polling 兜底 — 3s 后再次拉 repositoriesApi.get', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'running' }) as never,
    )
    vi.useFakeTimers()
    try {
      const wrapper = mountCard()
      await flushPromises()
      const callsBefore = vi.mocked(repositoriesApi.get).mock.calls.length
      expect(mockOnError).toBeTypeOf('function')
      mockOnError?.(new Error('network'))
      // 推进 3 秒触发一次 setInterval 回调
      await vi.advanceTimersByTimeAsync(3100)
      await flushPromises()
      const callsAfter = vi.mocked(repositoriesApi.get).mock.calls.length
      expect(callsAfter).toBeGreaterThan(callsBefore)
      wrapper.unmount()
    }
    finally {
      vi.useRealTimers()
    }
  })

  it('6c: 「立即构建」点击调 rebuildGraph(repoId) 并 toast 成功', async () => {
    vi.mocked(repositoriesApi.get).mockResolvedValue(
      buildRepo({ graph_build_status: 'idle' }) as never,
    )
    vi.mocked(rebuildGraph).mockResolvedValue({ history_id: 'h1' } as never)
    const wrapper = mountCard()
    await flushPromises()
    const rebuildBtn = wrapper.findAll('button').find(b => b.text().includes('立即构建'))
    expect(rebuildBtn).toBeTruthy()
    await rebuildBtn!.trigger('click')
    await flushPromises()
    expect(rebuildGraph).toHaveBeenCalledWith('repo-1')
    expect(successSpy).toHaveBeenCalledWith('已开始构建图谱')
  })
})
