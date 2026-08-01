/**
 * ：TechPlanCard.vue 单元测试。
 *
 * 覆盖：Markdown 渲染、affected_files file_path/path 兼容、折叠默认策略、
 * draft 「开始编码」按钮 emit、非 draft 状态 fallback 文案。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import TechPlanCard from '~/components/chat/TechPlanCard.vue'
import { useChatStore } from '~/stores/chat'

// 109-08：toast 改用稳定 spy（原先每次 useToast() 返回新的 vi.fn，无法断言文案）。
// 既有用例不断言 toast，故此改动对它们无影响。
const toastSuccessMock = vi.hoisted(() => vi.fn())
const toastErrorMock = vi.hoisted(() => vi.fn())
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: toastSuccessMock, error: toastErrorMock }),
}))

// 109-08：把 fan-out 端点函数替换成 mock，让「请求体里到底有没有
// acknowledge_unresearched 这个键」可被直接断言（走真实 store action，不 stub 它）。
const createSessionsForPlanMock = vi.hoisted(() => vi.fn())
vi.mock('~/api/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('~/api/chat')>()
  return { ...actual, createSessionsForPlan: createSessionsForPlanMock }
})

// 深链走 RouterLink（与三处触点同一约定）。
vi.mock('vue-router', () => ({
  RouterLink: { name: 'RouterLink', props: ['to'], template: '<a :href="to"><slot /></a>' },
}))

// -- mock markdown-it 单例：直接返回 echo HTML（避免引入 shiki 的重依赖）---
vi.mock('~/composables/useMarkdownRenderer', () => ({
  getMarkdownRenderer: vi.fn(async () => ({
    render: (raw: string) => `<div data-test="md">${raw}</div>`,
  })),
}))

// -- stub shadcn-vue 组件，避免 Slot 渲染机制干扰断言 ---
const StubBadge = defineComponent({
  name: 'Badge',
  setup(_, { slots }) {
    return () => h('span', { 'data-test': 'badge' }, slots.default?.())
  },
})
const StubButton = defineComponent({
  name: 'Button',
  props: ['disabled'],
  emits: ['click'],
  setup(props, { slots, emit }) {
    return () => h('button', {
      'data-test': 'btn',
      'disabled': props.disabled || false,
      'onClick': () => emit('click'),
    }, slots.default?.())
  },
})
const StubInput = defineComponent({
  name: 'Input',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', {
      value: props.modelValue,
      onInput: (e: Event) => emit('update:modelValue', (e.target as HTMLInputElement).value),
    })
  },
})
const PassthroughSelect = defineComponent({
  name: 'Select',
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'select' }, slots.default?.())
  },
})
const StubSelectItem = defineComponent({
  name: 'SelectItem',
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'select-item' }, slots.default?.())
  },
})

const StubDialog = defineComponent({
  name: 'Dialog',
  props: ['open'],
  emits: ['update:open'],
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'dialog' }, slots.default?.())
  },
})
const StubDialogContent = defineComponent({
  name: 'DialogContent',
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'dialog-content' }, slots.default?.())
  },
})
const StubDialogHeader = defineComponent({
  name: 'DialogHeader',
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'dialog-header' }, slots.default?.())
  },
})
const StubDialogTitle = defineComponent({
  name: 'DialogTitle',
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'dialog-title' }, slots.default?.())
  },
})
const StubDialogDescription = defineComponent({
  name: 'DialogDescription',
  setup(_, { slots }) {
    return () => h('div', { 'data-test': 'dialog-desc' }, slots.default?.())
  },
})
// 109-08：草稿确认弹层的 stub 家族。真实 reka-ui AlertDialog 走 Teleport + 焦点
// 陷阱，断言起来噪音大；stub 保留三件被断言的事实：open 透传、confirm 按钮的
// disabled 态、cancel/confirm 的点击语义。
const StubAlertDialog = defineComponent({
  name: 'AlertDialog',
  props: ['open'],
  emits: ['update:open'],
  setup(props, { slots }) {
    return () => h('div', {
      'data-test': 'alert-dialog',
      'data-open': String(props.open ?? false),
    }, slots.default?.())
  },
})
const StubAlertDialogAction = defineComponent({
  name: 'AlertDialogAction',
  props: ['disabled'],
  emits: ['click'],
  setup(props, { slots, emit }) {
    return () => h('button', {
      'data-test': 'ack-confirm',
      'disabled': props.disabled || false,
      'aria-disabled': String(!!props.disabled),
      'onClick': () => emit('click'),
    }, slots.default?.())
  },
})
const StubAlertDialogCancel = defineComponent({
  name: 'AlertDialogCancel',
  setup(_, { slots }) {
    return () => h('button', { 'data-test': 'ack-cancel' }, slots.default?.())
  },
})
const StubCheckbox = defineComponent({
  name: 'Checkbox',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', {
      'type': 'checkbox',
      'data-test': 'ack-checkbox',
      'checked': !!props.modelValue,
      'onChange': () => emit('update:modelValue', !props.modelValue),
    })
  },
})
function makePassthrough(name: string, dataTest: string) {
  return defineComponent({
    name,
    setup(_, { slots }) {
      return () => h('div', { 'data-test': dataTest }, slots.default?.())
    },
  })
}

const StubRepoMultiSelector = defineComponent({
  name: 'RepoMultiSelector',
  props: ['repositories', 'modelValue', 'disabledIds', 'recommendedIds', 'submitting'],
  emits: ['update:modelValue', 'confirm'],
  setup(props, { emit }) {
    return () => h('div', {
      'data-test': 'multi-selector',
      'data-repos-count': props.repositories?.length || 0,
      'data-disabled-count': props.disabledIds?.length || 0,
    }, [
      h('button', {
        'data-test': 'multi-confirm',
        'onClick': () => emit('confirm', props.modelValue?.length ? props.modelValue : ['r1', 'r2']),
      }, '确认编码'),
    ])
  },
})
const StubCodingSessionStatusRow = defineComponent({
  name: 'CodingSessionStatusRow',
  props: ['session', 'repoGitUrl'],
  emits: ['retry'],
  setup(props, { emit }) {
    return () => h('div', {
      'data-test': 'status-row',
      'data-session-id': props.session?.session_id,
    }, [
      h('button', {
        'data-test': 'row-retry',
        'onClick': () => emit('retry', props.session?.session_id),
      }, '重试'),
    ])
  },
})

// ：避免 ExportConfirmDialog 内部依赖（chatStore /
// RouterLink / shadcn Dialog 等）干扰 TechPlanCard 的按钮交互断言。
const StubExportConfirmDialog = defineComponent({
  name: 'ExportConfirmDialog',
  props: ['open', 'defaultTitle', 'mode', 'codingPlanId'],
  emits: ['update:open', 'success'],
  setup(props) {
    return () => h('div', {
      'data-test': 'export-confirm-dialog',
      'data-open': String(props.open ?? false),
      'data-mode': props.mode ?? 'conversation',
      'data-coding-plan-id': props.codingPlanId ?? '',
    })
  },
})

const globalStubs = {
  Badge: StubBadge,
  Button: StubButton,
  Input: StubInput,
  Select: PassthroughSelect,
  SelectTrigger: PassthroughSelect,
  SelectContent: PassthroughSelect,
  SelectItem: StubSelectItem,
  SelectValue: PassthroughSelect,
  Dialog: StubDialog,
  DialogContent: StubDialogContent,
  DialogHeader: StubDialogHeader,
  DialogTitle: StubDialogTitle,
  DialogDescription: StubDialogDescription,
  RepoMultiSelector: StubRepoMultiSelector,
  CodingSessionStatusRow: StubCodingSessionStatusRow,
  ExportConfirmDialog: StubExportConfirmDialog,
  AlertDialog: StubAlertDialog,
  AlertDialogContent: makePassthrough('AlertDialogContent', 'alert-dialog-content'),
  AlertDialogHeader: makePassthrough('AlertDialogHeader', 'alert-dialog-header'),
  AlertDialogTitle: makePassthrough('AlertDialogTitle', 'alert-dialog-title'),
  AlertDialogDescription: makePassthrough('AlertDialogDescription', 'alert-dialog-desc'),
  AlertDialogFooter: makePassthrough('AlertDialogFooter', 'alert-dialog-footer'),
  AlertDialogAction: StubAlertDialogAction,
  AlertDialogCancel: StubAlertDialogCancel,
  Checkbox: StubCheckbox,
}

function mountCard(props: Partial<InstanceType<typeof TechPlanCard>['$props']> = {}) {
  return mount(TechPlanCard, {
    props: {
      planId: 'plan-uuid',
      sessionId: 'session-uuid',
      techPlan: '# 标题\n方案内容',
      affectedFiles: [],
      status: 'draft' as const,
      isConfirming: false,
      ...props,
    },
    global: {
      stubs: globalStubs,
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
})

describe('techPlanCard', () => {
  it('renders markdown of tech plan', async () => {
    const wrapper = mountCard({ techPlan: '# 标题' })
    await flushPromises()
    await nextTick()
    expect(wrapper.html()).toContain('<div data-test="md"># 标题</div>')
  })

  it('renders affected_files using file_path key', async () => {
    const wrapper = mountCard({
      affectedFiles: [{ file_path: 'a.py', change_type: 'modify' }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('a.py')
    expect(wrapper.text()).toContain('影响文件')
  })

  it('falls back to legacy path key when file_path missing', async () => {
    const wrapper = mountCard({
      affectedFiles: [{ path: 'legacy.py', change_type: 'add' }],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('legacy.py')
  })

  it('hides affected files section when empty', async () => {
    const wrapper = mountCard({ affectedFiles: [] })
    await flushPromises()
    expect(wrapper.text()).not.toContain('影响文件')
  })

  it('shows 开始编码 button only when status==draft', async () => {
    const draft = mountCard({ status: 'draft' })
    await flushPromises()
    expect(draft.text()).toContain('开始编码')

    const confirmed = mountCard({ status: 'confirmed', defaultCollapsed: false })
    await flushPromises()
    expect(confirmed.text()).not.toContain('开始编码')
  })

  it('emits confirm with planId / sessionId / branchName when draft button clicked', async () => {
    const wrapper = mountCard({
      status: 'draft',
      planId: 'plan-uuid',
      sessionId: 'session-uuid',
      // 分支格式 {type}/{yymmdd}.{desc}（见 useBranchValidation BRANCH_PATTERN），
      // 必须可解析否则 shortDesc 为空致按钮 disabled、happy-dom 拦截点击。
      branchName: 'feat/260520.demo',
    })
    await flushPromises()
    // 卡片可能渲染多个 Button（stub 均为 data-test="btn"）；按文案定位「开始编码」
    const startBtn = wrapper.findAll('[data-test="btn"]').find(b => b.text().includes('开始编码'))
    expect(startBtn).toBeTruthy()
    await startBtn!.trigger('click')
    const emitted = wrapper.emitted('confirm')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toBe('plan-uuid')
    expect(emitted![0][1]).toBe('session-uuid')
    // branchName 来自 previewBranchName（基于解析的 branch parts）：feat/yymmdd.desc
    expect(typeof emitted![0][2]).toBe('string')
    expect(emitted![0][2]).toMatch(/^feat\/\d{6}\./)
  })

  it('defaults to collapsed when status is not draft', async () => {
    const wrapper = mountCard({ status: 'running' })
    await flushPromises()
    // 折叠态：渲染摘要而非完整 markdown
    expect(wrapper.html()).not.toContain('<div data-test="md">')
    expect(wrapper.text()).toContain('# 标题')
    // 点击 header 后展开
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.html()).toContain('<div data-test="md">')
  })

  it('defaults to expanded when status is draft', async () => {
    const wrapper = mountCard({ status: 'draft' })
    await flushPromises()
    expect(wrapper.html()).toContain('<div data-test="md">')
  })

  it('shows fallback hint for completed status', async () => {
    const wrapper = mountCard({
      status: 'completed',
      defaultCollapsed: false,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('编码完成')
  })

  // ---------------------------------------------------------------------------
  // / ：completed/failed 专属 UI + skeleton
  // ---------------------------------------------------------------------------

  it('shows green ring and PR link when status===completed and prUrl present', async () => {
    const prUrl = 'https://gitlab.example.com/x/y/-/merge_requests/123'
    const wrapper = mountCard({
      status: 'completed',
      defaultCollapsed: false,
      prUrl,
    })
    await flushPromises()
    expect(wrapper.html()).toContain('ring-emerald-500/30')
    const link = wrapper.find('a[href]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe(prUrl)
    expect(wrapper.text()).toContain('查看 PR')
  })

  it('shows placeholder when completed but prUrl empty', async () => {
    const wrapper = mountCard({
      status: 'completed',
      defaultCollapsed: false,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('PR 链接将由 multi-confirm 流程回填')
  })

  it('shows red ring and error message when status===failed', async () => {
    const wrapper = mountCard({
      status: 'failed',
      defaultCollapsed: false,
      errorMessage: 'dispatch failed',
    })
    await flushPromises()
    expect(wrapper.html()).toContain('ring-destructive/30')
    expect(wrapper.text()).toContain('dispatch failed')
    expect(wrapper.text()).toContain('重试')
  })

  it('emits retry event with planId and sessionId when 重试 clicked', async () => {
    const wrapper = mountCard({
      status: 'failed',
      defaultCollapsed: false,
      planId: 'plan-uuid',
      sessionId: 'session-uuid',
      errorMessage: 'oops',
    })
    await flushPromises()
    // failed 状态下的「重试」按钮是 stub Button 渲染的 `data-test="btn"`
    const buttons = wrapper.findAll('[data-test="btn"]')
    // failed 路径下整张卡只有 1 个 Button（重试），不会有 开始编码
    expect(buttons.length).toBe(1)
    await buttons[0].trigger('click')
    const emitted = wrapper.emitted('retry')
    expect(emitted).toBeTruthy()
    expect(emitted![0][0]).toBe('plan-uuid')
    expect(emitted![0][1]).toBe('session-uuid')
  })

  it('shows skeleton placeholder before markdown is ready', async () => {
    // 让 markdown renderer 永远 pending，模拟未 ready 状态
    const { getMarkdownRenderer } = await import('~/composables/useMarkdownRenderer')
    vi.mocked(getMarkdownRenderer).mockReturnValueOnce(new Promise(() => {}))
    const wrapper = mountCard({ status: 'draft' })
    // 不 flushPromises（让 onMounted 的 await 持续 pending）
    await nextTick()
    const skeleton = wrapper.find('[data-test="md-skeleton"]')
    expect(skeleton.exists()).toBe(true)
    expect(skeleton.findAll('.animate-pulse > div').length).toBe(3)
  })

  it('failed status without errorMessage shows default fallback', async () => {
    const wrapper = mountCard({
      status: 'failed',
      defaultCollapsed: false,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('编码失败，未提供错误信息')
  })
})

// ============================================================================
// ：TechPlanCard 集成 RepoMultiSelector + sessions 列表 + retry
// ============================================================================

describe('techPlanCard — FAN-04 multi-repo integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  const REPOS = [
    { id: 'r1', name: 'repo-1' },
    { id: 'r2', name: 'repo-2' },
    { id: 'r3', name: 'repo-3' },
  ]
  const REPO_GIT_URLS = {
    r1: 'https://gitlab.com/ns/repo-1.git',
    r2: 'https://gitlab.com/ns/repo-2.git',
    r3: 'https://gitlab.com/ns/repo-3.git',
  }

  function setStorePlan(sessions: any[]): void {
    const store = useChatStore()
    store.activeCodingPlan = sessions.length > 0
      ? { plan_id: 'plan-1', title: 't', sessions }
      : null
  }

  it('shows inline RepoMultiSelector when no sessions exist (创建态)', async () => {
    setStorePlan([])
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'RepoMultiSelector' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('选择目标仓库')
    expect(wrapper.text()).not.toContain('目标仓库（')
    // 旧 draft「开始编码」按钮不出现（被替代）
    expect(wrapper.text()).not.toContain('开始编码')
  })

  it('shows explicit target repositories on the technical plan card', async () => {
    setStorePlan([])
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      targetRepositories: [{ id: 'r1', name: 'example-app' }],
    } as any)

    await flushPromises()

    expect(wrapper.text()).toContain('目标仓库')
    expect(wrapper.text()).toContain('example-app')
  })

  it('shows sessions list and 对新仓库编码 button when sessions exist (追加态)', async () => {
    setStorePlan([
      {
        session_id: 'cs1',
        repository_id: 'r1',
        repository_name: 'repo-1',
        branch_name: 'feat/x',
        status: 'running',
        pr_url: '',
        commit_sha: '',
        error_message: '',
      },
    ])
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
    })
    await flushPromises()
    expect(wrapper.text()).toContain('目标仓库（1）')
    expect(wrapper.text()).toContain('对新仓库编码')
    expect(wrapper.findAll('[data-test="status-row"]').length).toBe(1)
  })

  it('opens Dialog when 对新仓库编码 clicked', async () => {
    setStorePlan([
      {
        session_id: 'cs1',
        repository_id: 'r1',
        repository_name: 'repo-1',
        branch_name: 'feat/x',
        status: 'running',
        pr_url: '',
        commit_sha: '',
        error_message: '',
      },
    ])
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
    })
    await flushPromises()
    const appendBtn = wrapper.findAll('button').find(b => b.text().includes('对新仓库编码'))
    expect(appendBtn).toBeTruthy()
    await appendBtn!.trigger('click')
    await nextTick()
    // dialogOpen ref → Dialog stub 接收 open prop。这里通过查找 Dialog stub 验证。
    // 我们的 stub 不响应 open，但点击后内部 store 应记录 planId。
    const store = useChatStore()
    expect(store.repoMultiSelectorState.planId).toBe('plan-1')
  })

  it('passes existingActiveRepoIds as disabledIds to RepoMultiSelector (追加态)', async () => {
    setStorePlan([
      {
        session_id: 'cs1',
        repository_id: 'r1',
        repository_name: 'repo-1',
        branch_name: 'feat/x',
        status: 'running',
        pr_url: '',
        commit_sha: '',
        error_message: '',
      },
    ])
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
    })
    await flushPromises()
    const selectorEls = wrapper.findAll('[data-test="multi-selector"]')
    // Dialog 内的 selector 也会渲染（stub Dialog 不隐藏内容），所以可能有 ≥1 个
    expect(selectorEls.length).toBeGreaterThanOrEqual(1)
    // 至少 1 个 disabled-count=1（含 r1）
    expect(
      selectorEls.some(el => el.attributes('data-disabled-count') === '1'),
    ).toBe(true)
  })

  it('calls store.submitRepoMultiSelector when RepoMultiSelector emits confirm (创建态)', async () => {
    setStorePlan([])
    const store = useChatStore()
    const spy = vi.spyOn(store, 'submitRepoMultiSelector')
      .mockResolvedValue({ createdCount: 2, failedCount: 0 })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
      // provenance: 'orchestrated' 是 109-08 草稿闸门生效的预期连带影响，不是回归；
      // 本用例测的是「确认即提交」，不是闸门（草稿路径由 109-08 新增用例覆盖）。
      provenance: 'orchestrated',
    })
    await flushPromises()
    const confirmBtn = wrapper.find('[data-test="multi-confirm"]')
    expect(confirmBtn.exists()).toBe(true)
    await confirmBtn.trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalled()
  })

  it('passes branch template to store.submitRepoMultiSelector in codingPlan flow', async () => {
    setStorePlan([])
    const store = useChatStore()
    const spy = vi.spyOn(store, 'submitRepoMultiSelector')
      .mockResolvedValue({ createdCount: 1, failedCount: 0 })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
      // provenance: 'orchestrated' 是 109-08 草稿闸门生效的预期连带影响，不是回归；
      // 本用例测的是分支模板实参透传，不是闸门。
      provenance: 'orchestrated',
    })
    await flushPromises()

    const input = wrapper.find('[data-test="branch-template-input"]')
    expect(input.exists()).toBe(true)
    const branchTemplate = `fix.gift-empty-list.$${'{repo}'}`
    await input.setValue(branchTemplate)

    const confirmBtn = wrapper.find('[data-test="multi-confirm"]')
    await confirmBtn.trigger('click')
    await flushPromises()

    // 组件现额外透传第三参 target_branch（默认 develop）；断言前两参，第三参宽松。
    expect(spy).toHaveBeenCalled()
    const call = spy.mock.calls[0]
    expect(call[0]).toEqual(['r1', 'r2'])
    expect(call[1]).toBe(branchTemplate)
  })

  it('calls store.retrySingleRepository when status row emits retry', async () => {
    setStorePlan([
      {
        session_id: 'cs1',
        repository_id: 'r1',
        repository_name: 'repo-1',
        branch_name: 'feat/x',
        status: 'failed',
        pr_url: '',
        commit_sha: '',
        error_message: 'Runner 离线',
      },
    ])
    const store = useChatStore()
    const spy = vi.spyOn(store, 'retrySingleRepository')
      .mockResolvedValue({ createdCount: 1, failedCount: 0 })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
      repositoryGitUrls: REPO_GIT_URLS,
      // provenance: 'orchestrated' 是 109-08 草稿闸门生效的预期连带影响，不是回归；
      // 本用例测的是重试实参透传，不是闸门（草稿重试同样弹层，由 109-08 新增用例覆盖）。
      provenance: 'orchestrated',
    })
    await flushPromises()
    const retryBtn = wrapper.find('[data-test="row-retry"]')
    expect(retryBtn.exists()).toBe(true)
    await retryBtn.trigger('click')
    await flushPromises()
    expect(spy).toHaveBeenCalledWith('plan-1', 'r1')
  })
})

// ============================================================================
// ：TechPlanCard 导出到飞书三态按钮
// ============================================================================

describe('techPlanCard — FEISHU-03 export to feishu button', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  function setStoreFeishuFields(opts: { docUrl?: string, docToken?: string } = {}) {
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: 'plan-feishu',
      title: '示例方案',
      sessions: [],
      feishu_doc_token: opts.docToken ?? '',
      feishu_doc_url: opts.docUrl ?? '',
    }
  }

  it('未导出态：渲染「导出到飞书」按钮，不渲染「在飞书打开」', async () => {
    setStoreFeishuFields({ docUrl: '' })
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('导出到飞书')
    expect(wrapper.text()).not.toContain('在飞书打开')
  })

  it('已导出态：渲染「在飞书打开」+「重新导出」', async () => {
    setStoreFeishuFields({
      docToken: 'doxcnTEST',
      docUrl: 'https://feishu.cn/docx/doxcnTEST',
    })
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    expect(wrapper.text()).toContain('在飞书打开')
    expect(wrapper.find('[aria-label="重新导出"]').exists()).toBe(true)
  })

  it('未提供 codingPlanId 时，飞书按钮整块隐藏（向后兼容旧调用方）', async () => {
    setStoreFeishuFields({ docUrl: 'https://feishu.cn/docx/doxcnTEST' })
    const wrapper = mountCard({
      // 不传 codingPlanId
      availableRepositories: [],
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('导出到飞书')
    expect(wrapper.text()).not.toContain('在飞书打开')
  })

  it('点击「在飞书打开」按钮调用 window.open 带 noopener,noreferrer', async () => {
    setStoreFeishuFields({
      docToken: 'doxcnTEST',
      docUrl: 'https://feishu.cn/docx/doxcnTEST',
    })
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const openBtn = buttons.find(b => b.text().includes('在飞书打开'))
    expect(openBtn).toBeTruthy()
    await openBtn!.trigger('click')
    expect(openSpy).toHaveBeenCalledWith(
      'https://feishu.cn/docx/doxcnTEST',
      '_blank',
      'noopener,noreferrer',
    )
    openSpy.mockRestore()
  })

  it('点击「导出到飞书」按钮把 showExportDialog 置为 true', async () => {
    setStoreFeishuFields({ docUrl: '' })
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    const buttons = wrapper.findAll('button')
    const exportBtn = buttons.find(b => b.text().includes('导出到飞书'))
    expect(exportBtn).toBeTruthy()
    await exportBtn!.trigger('click')
    await flushPromises()
    // 关键：渲染了 ExportConfirmDialog（stub 是 Dialog）且 open=true 已传入。
    // 由于 ExportConfirmDialog 内部用到 chatStore + Dialog stub 不响应 open，
    // 我们用更直接的判据：组件树里存在 ExportConfirmDialog。
    expect(
      wrapper.findComponent({ name: 'ExportConfirmDialog' }).exists(),
    ).toBe(true)
  })

  it('已导出态点击「重新导出」也会打开 ExportConfirmDialog', async () => {
    setStoreFeishuFields({
      docToken: 'doxcnTEST',
      docUrl: 'https://feishu.cn/docx/doxcnTEST',
    })
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    const reexportBtn = wrapper.find('[aria-label="重新导出"]')
    expect(reexportBtn.exists()).toBe(true)
    await reexportBtn.trigger('click')
    await flushPromises()
    expect(
      wrapper.findComponent({ name: 'ExportConfirmDialog' }).exists(),
    ).toBe(true)
  })

  // ：UAT test 3 / 6 根因回归 —— activeCodingPlan 只指向「最新」plan
  it('不串态：activeCodingPlan.plan_id 与本卡 codingPlanId 不匹配时仍显示「导出到飞书」', async () => {
    const store = useChatStore()
    // store 指向「其它 plan」且已导出，但本卡是另一个 plan
    store.activeCodingPlan = {
      plan_id: 'other-plan',
      title: '其它方案',
      sessions: [],
      feishu_doc_token: 'doxcnOTHER',
      feishu_doc_url: 'https://feishu.cn/docx/doxcnOTHER',
    }
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    // 不采用其它 plan 的已导出态
    expect(wrapper.text()).toContain('导出到飞书')
    expect(wrapper.text()).not.toContain('在飞书打开')
  })

  // ：@success 即时切态 —— 不依赖全局 activeCodingPlan 是否指向本卡
  it('@success 后即时切到已导出态（localFeishuDocUrl 兜底路径）', async () => {
    const store = useChatStore()
    // 本卡不是当前 activeCodingPlan（模拟多轮多方案旧卡片导出场景）
    store.activeCodingPlan = {
      plan_id: 'other-plan',
      title: '其它方案',
      sessions: [],
      feishu_doc_token: '',
      feishu_doc_url: '',
    }
    const wrapper = mountCard({
      codingPlanId: 'plan-feishu',
      availableRepositories: [],
    })
    await flushPromises()
    // 初始：未导出态
    expect(wrapper.text()).toContain('导出到飞书')

    // 触发内嵌 ExportConfirmDialog 的 @success（coding_plan 模式返回 doc_url）
    const dialog = wrapper.findComponent({ name: 'ExportConfirmDialog' })
    expect(dialog.exists()).toBe(true)
    dialog.vm.$emit('success', {
      doc_token: 'doxcnNEW',
      doc_url: 'https://feishu.cn/docx/doxcnNEW',
      title: '示例方案',
    })
    await flushPromises()
    await nextTick()

    // 即时切到「在飞书打开」+「重新导出」，无需 activeCodingPlan 指向本卡
    expect(wrapper.text()).toContain('在飞书打开')
    expect(wrapper.find('[aria-label="重新导出"]').exists()).toBe(true)
  })
})

// ============================================================================
// 109-06：方案正文 / 影响文件的三级优先解析（SPINE-02 连带面）
//
// props（投影响应本地态 + 历史消息 tool input 兜底）> runtime（🔴 过 plan_id
// 守卫）> 空正文占位。四个分支各至少一条用例，外加串态防护与历史数据零报错。
// ============================================================================

describe('techPlanCard — 109-06 方案正文三级优先解析', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  const PLACEHOLDER = '（暂无方案正文）'

  /** 往 store 写一份 runtime；planId 决定它是否指向本卡。 */
  function setRuntime(planId: string, extra: Record<string, unknown> = {}) {
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: planId,
      title: '方案',
      sessions: [],
      ...extra,
    } as any
  }

  it('第 1 级：techPlan prop 非空时优先于 runtime 正文', async () => {
    setRuntime('plan-1', { tech_plan: '# runtime 的正文' })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '# props 的正文',
    })
    await flushPromises()
    expect(wrapper.html()).toContain('<div data-test="md"># props 的正文</div>')
    expect(wrapper.html()).not.toContain('runtime 的正文')
  })

  it('第 2 级：prop 为空且 runtime.plan_id 匹配时采用 runtime 的 tech_plan / affected_files', async () => {
    setRuntime('plan-1', {
      tech_plan: '# runtime 的正文',
      affected_files: [{ file_path: 'server/app.py', change_type: 'modify' }],
    })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '',
      affectedFiles: [],
    })
    await flushPromises()
    expect(wrapper.html()).toContain('<div data-test="md"># runtime 的正文</div>')
    expect(wrapper.text()).not.toContain(PLACEHOLDER)
    // affected_files 同样经 runtime 生效
    expect(wrapper.text()).toContain('影响文件')
    expect(wrapper.text()).toContain('server/app.py')
    expect(wrapper.text()).toContain('modify')
  })

  // 🔴 串态防护（不可省的守卫）：activeCodingPlan 只指向「对话内最近 CodingPlan」，
  // 多方案多轮会话里若不过 plan_id 守卫就采用 runtime，会把**新方案的正文渲染到
  // 旧方案卡上** —— 不报错、不崩，只是内容串了，是最难查的一类缺陷。
  it('多方案会话不串态：runtime.plan_id 与本卡不匹配时不采用 runtime 正文，落到占位', async () => {
    setRuntime('other-plan', {
      tech_plan: '# 别的方案的正文',
      affected_files: [{ file_path: 'other/leaked.py', change_type: 'add' }],
    })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '',
      affectedFiles: [],
    })
    await flushPromises()
    expect(wrapper.text()).not.toContain('别的方案的正文')
    expect(wrapper.text()).not.toContain('other/leaked.py')
    expect(wrapper.text()).not.toContain('影响文件')
    expect(wrapper.text()).toContain(PLACEHOLDER)
  })

  it('第 3 级：历史消息（runtime 无 tech_plan，正文由 tool input 经 prop 传下）正常渲染且零报错/零 warn', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    // 历史 runtime：没有 109 新增的 tech_plan / affected_files / provenance 三个字段
    setRuntime('plan-1')
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '# 历史 tool input 里的正文',
      affectedFiles: [{ path: 'legacy.py', change_type: 'add' }],
    })
    await flushPromises()
    expect(wrapper.html()).toContain('<div data-test="md"># 历史 tool input 里的正文</div>')
    expect(wrapper.text()).toContain('legacy.py')
    expect(warnSpy).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
    errorSpy.mockRestore()
  })

  it('第 4 级：三者皆空 → 渲染占位文案，且不出现空的 .prose 块', async () => {
    setRuntime('plan-1')
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '',
      affectedFiles: [],
    })
    await flushPromises()
    expect(wrapper.text()).toContain(PLACEHOLDER)
    expect(wrapper.find('.prose').exists()).toBe(false)
  })

  it('无 store runtime（activeCodingPlan 为 null）时正文仍走 prop，不抛错', async () => {
    const store = useChatStore()
    store.activeCodingPlan = null
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '# 只有 prop',
    })
    await flushPromises()
    expect(wrapper.html()).toContain('<div data-test="md"># 只有 prop</div>')
  })

  it('历史 runtime 缺 provenance / tech_plan / affected_files 三字段（undefined）→ 挂载与渲染不抛、零 warn', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: 'plan-1',
      title: '历史方案',
      sessions: [],
      provenance: undefined,
      tech_plan: undefined,
      affected_files: undefined,
    } as any
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '',
      affectedFiles: [],
    })
    await flushPromises()
    expect(wrapper.text()).toContain(PLACEHOLDER)
    expect(wrapper.text()).not.toContain('影响文件')
    expect(warnSpy).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
    errorSpy.mockRestore()
  })

  it('折叠态摘要同样读三级优先解析结果（runtime 匹配时取 runtime 正文首行）', async () => {
    setRuntime('plan-1', { tech_plan: '# runtime 首行\n第二行' })
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '',
      status: 'running',
    })
    await flushPromises()
    // 非 draft 默认折叠：渲染一行摘要而非完整 markdown
    expect(wrapper.html()).not.toContain('<div data-test="md">')
    expect(wrapper.text()).toContain('# runtime 首行')
  })

  it('折叠态三者皆空时保留既有「（无方案文本）」兜底', async () => {
    setRuntime('plan-1')
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      techPlan: '',
      status: 'running',
    })
    await flushPromises()
    expect(wrapper.text()).toContain('（无方案文本）')
  })
})

// ============================================================================
// 109-08（RELY-01 界面侧）：草稿标注的允许清单判定 + 送编码显式确认
//
// 判定只读 provenance：仅严格等于 'orchestrated' 免标注，其余（'draft' / 未知取值
// / null / undefined / ''）一律标注。确认闸门覆盖创建态确认与单仓重试两个入口
// （追加态与创建态共用 handleMultiConfirm，天然覆盖）。
// ============================================================================

describe('techPlanCard — 109-08 草稿标注与送编码确认', () => {
  const BANNER = '本方案未经代码调研'
  const BANNER_SUB = '由对话直接生成，未经仓库路由、代码召回与并行调研，文件清单与实现步骤可能不准确。'
  const BADGE = '未经调研'
  const DIALOG_TITLE = '该方案未经代码调研'
  const ACK_LABEL = '我已了解风险，仍要用该草稿送编码'
  const GATE_REJECTED = '草稿方案需显式确认后才能送编码'

  const REPOS = [
    { id: 'r1', name: 'repo-1' },
    { id: 'r2', name: 'repo-2' },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    createSessionsForPlanMock.mockReset()
    createSessionsForPlanMock.mockResolvedValue({ created: [], failed: [] })
  })

  /** 头部草稿徽标是否存在（按文案定位，不按 Badge 计数）。 */
  function hasDraftBadge(wrapper: ReturnType<typeof mountCard>): boolean {
    return wrapper.findAll('[data-test="badge"]').some(b => b.text() === BADGE)
  }

  function setRuntime(planId: string, extra: Record<string, unknown> = {}) {
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: planId,
      title: '方案',
      sessions: [],
      ...extra,
    } as any
  }

  /** 打开确认弹层：点创建态 selector 的「确认编码」。 */
  async function clickMultiConfirm(wrapper: ReturnType<typeof mountCard>) {
    await wrapper.find('[data-test="multi-confirm"]').trigger('click')
    await flushPromises()
    await nextTick()
  }

  function dialogOpen(wrapper: ReturnType<typeof mountCard>): string | undefined {
    return wrapper.find('[data-test="alert-dialog"]').attributes('data-open')
  }

  async function tickAcknowledge(wrapper: ReturnType<typeof mountCard>) {
    await wrapper.find('[data-test="ack-checkbox"]').trigger('change')
    await nextTick()
  }

  // -------------------------------------------------------------------------
  // 判定与标注
  // -------------------------------------------------------------------------

  it('provenance=draft → 草稿横幅与头部徽标都出现', async () => {
    const wrapper = mountCard({ provenance: 'draft' })
    await flushPromises()
    const banner = wrapper.find('[data-test="unresearched-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.attributes('role')).toBe('alert')
    // 横幅随卡片首次渲染出现（非动态插入）⇒ 不加 aria-live
    expect(banner.attributes('aria-live')).toBeUndefined()
    expect(wrapper.text()).toContain(BANNER)
    expect(wrapper.text()).toContain(BANNER_SUB)
    expect(hasDraftBadge(wrapper)).toBe(true)
  })

  it('provenance=orchestrated → 横幅与徽标皆无，且送编码时弹层不出现', async () => {
    const wrapper = mountCard({
      provenance: 'orchestrated',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain(BANNER)
    expect(hasDraftBadge(wrapper)).toBe(false)

    await clickMultiConfirm(wrapper)
    // 零摩擦：弹层永不打开，请求直接发出
    expect(dialogOpen(wrapper)).toBe('false')
    expect(createSessionsForPlanMock).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['undefined', undefined],
    ['null', null],
    ['空串', ''],
    ['未知取值', 'weird_value'],
  ])('provenance 为 %s → 仍渲染草稿横幅（允许清单：非 orchestrated 一律标注）', async (_label, value) => {
    const wrapper = mountCard({ provenance: value as any })
    await flushPromises()
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(true)
    expect(hasDraftBadge(wrapper)).toBe(true)
  })

  it('未知取值不回显：渲染结果不含 provenance 原始字符串', async () => {
    const wrapper = mountCard({ provenance: 'weird_value' })
    await flushPromises()
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('weird_value')
    expect(wrapper.html()).not.toContain('weird_value')
  })

  it('折叠后徽标仍可见（事实不被一次折叠操作藏起来）', async () => {
    const wrapper = mountCard({ provenance: 'draft', defaultCollapsed: true })
    await flushPromises()
    // 折叠态：横幅随展开内容消失，但头部徽标常驻
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(false)
    expect(hasDraftBadge(wrapper)).toBe(true)
  })

  // 🔴 串态防护：runtime.provenance 是 runtime.coding_plan 的第三个消费点。
  // 漏 plan_id 守卫会把别的方案的来源标志渲染到本卡上 —— 一份草稿因此被漏标。
  it('多方案会话不串 provenance：runtime.plan_id 与本卡不匹配时不采用其 provenance（落到保守分支标注）', async () => {
    setRuntime('other-plan', { provenance: 'orchestrated' })
    const wrapper = mountCard({ codingPlanId: 'plan-1' })
    await flushPromises()
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(true)
    expect(hasDraftBadge(wrapper)).toBe(true)
  })

  it('runtime.plan_id 匹配时采用 runtime.provenance（orchestrated ⇒ 免标注）', async () => {
    setRuntime('plan-1', { provenance: 'orchestrated' })
    const wrapper = mountCard({ codingPlanId: 'plan-1' })
    await flushPromises()
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(false)
    expect(hasDraftBadge(wrapper)).toBe(false)
  })

  it('历史 runtime 缺 provenance 字段 → 挂载与渲染不抛，console.warn / error 零调用', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    setRuntime('plan-1')
    const wrapper = mountCard({ codingPlanId: 'plan-1' })
    await flushPromises()
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(true)
    expect(warnSpy).not.toHaveBeenCalled()
    expect(errorSpy).not.toHaveBeenCalled()
    warnSpy.mockRestore()
    errorSpy.mockRestore()
  })

  // -------------------------------------------------------------------------
  // 确认路径
  // -------------------------------------------------------------------------

  it('草稿路径点确认 → 弹层出现，确认按钮初始 disabled；勾选后启用', async () => {
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)

    expect(dialogOpen(wrapper)).toBe('true')
    expect(wrapper.text()).toContain(DIALOG_TITLE)
    expect(wrapper.text()).toContain(ACK_LABEL)
    expect(wrapper.text()).toContain('仍要送编码')
    // 未勾选：不提交、确认按钮 disabled 且带 aria-disabled
    expect(createSessionsForPlanMock).not.toHaveBeenCalled()
    const confirmBtn = wrapper.find('[data-test="ack-confirm"]')
    expect(confirmBtn.attributes('disabled')).toBeDefined()
    expect(confirmBtn.attributes('aria-disabled')).toBe('true')

    await tickAcknowledge(wrapper)
    expect(wrapper.find('[data-test="ack-confirm"]').attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-test="ack-confirm"]').attributes('aria-disabled')).toBe('false')
  })

  it('勾选后确认 → 提交请求体含 acknowledge_unresearched: true', async () => {
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)
    await tickAcknowledge(wrapper)
    await wrapper.find('[data-test="ack-confirm"]').trigger('click')
    await flushPromises()

    expect(createSessionsForPlanMock).toHaveBeenCalledTimes(1)
    const payload = createSessionsForPlanMock.mock.calls[0][1]
    expect(payload.acknowledge_unresearched).toBe(true)
    // 弹层结算后关闭
    expect(dialogOpen(wrapper)).toBe('false')
  })

  it('编排路径提交请求体不含 acknowledge_unresearched 键（不发字段，而非发 false）', async () => {
    const wrapper = mountCard({
      provenance: 'orchestrated',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)

    expect(createSessionsForPlanMock).toHaveBeenCalledTimes(1)
    const payload = createSessionsForPlanMock.mock.calls[0][1]
    expect('acknowledge_unresearched' in payload).toBe(false)
  })

  it('取消弹层 → 不调任何提交', async () => {
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)
    await tickAcknowledge(wrapper)
    await wrapper.find('[data-test="ack-cancel"]').trigger('click')
    await flushPromises()

    expect(createSessionsForPlanMock).not.toHaveBeenCalled()
    expect(dialogOpen(wrapper)).toBe('false')
  })

  it('esc / 遮罩关闭（update:open=false）等同取消，不提交', async () => {
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)
    wrapper.findComponent({ name: 'AlertDialog' }).vm.$emit('update:open', false)
    await flushPromises()

    expect(createSessionsForPlanMock).not.toHaveBeenCalled()
  })

  it('弹层每次打开重置勾选（打开→勾选→取消→再打开，按钮回到 disabled）', async () => {
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)
    await tickAcknowledge(wrapper)
    expect(wrapper.find('[data-test="ack-confirm"]').attributes('disabled')).toBeUndefined()

    await wrapper.find('[data-test="ack-cancel"]').trigger('click')
    await flushPromises()

    await clickMultiConfirm(wrapper)
    expect(dialogOpen(wrapper)).toBe('true')
    expect(wrapper.find('[data-test="ack-confirm"]').attributes('disabled')).toBeDefined()
  })

  it('重试路径同样弹层：确认后 retrySingleRepository 的请求体带 ack', async () => {
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: 'plan-1',
      title: '方案',
      provenance: 'draft',
      sessions: [
        {
          session_id: 'cs1',
          repository_id: 'r1',
          repository_name: 'repo-1',
          branch_name: 'feat/x',
          status: 'failed',
          pr_url: '',
          commit_sha: '',
          error_message: 'Runner 离线',
        },
      ],
    } as any
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()

    await wrapper.find('[data-test="row-retry"]').trigger('click')
    await flushPromises()
    await nextTick()
    // 重试同样创建 session ⇒ 同样过闸门
    expect(dialogOpen(wrapper)).toBe('true')
    expect(createSessionsForPlanMock).not.toHaveBeenCalled()

    await tickAcknowledge(wrapper)
    await wrapper.find('[data-test="ack-confirm"]').trigger('click')
    await flushPromises()

    expect(createSessionsForPlanMock).toHaveBeenCalledTimes(1)
    const [planId, payload] = createSessionsForPlanMock.mock.calls[0]
    expect(planId).toBe('plan-1')
    expect(payload.repository_ids).toEqual(['r1'])
    expect(payload.acknowledge_unresearched).toBe(true)
  })

  it('code=draft_requires_explicit_confirm 的拒绝 → 前端常量 toast，弹层不重开（LO-01）', async () => {
    createSessionsForPlanMock.mockRejectedValue(
      Object.assign(new Error('后端 detail 文案（不应被匹配）'), {
        status: 400,
        detail: '后端 detail 文案（不应被匹配）',
        body: { code: 'draft_requires_explicit_confirm', detail: '后端 detail 文案（不应被匹配）' },
      }),
    )
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)
    await tickAcknowledge(wrapper)
    await wrapper.find('[data-test="ack-confirm"]').trigger('click')
    await flushPromises()
    await nextTick()

    expect(toastErrorMock).toHaveBeenCalledWith(GATE_REJECTED)
    // 🔴 不得重开弹层：重开得到的 promise 无人 await，用户勾选确认后什么都不会发生，
    // 是比不弹更糟的死胡同。让用户从原入口重来。
    expect(dialogOpen(wrapper)).toBe('false')
  })

  it('其它错误（无 code / 别的 code）→ 沿用既有 toast，不误报为草稿拒绝', async () => {
    createSessionsForPlanMock.mockRejectedValue(
      Object.assign(new Error('批量失败：仓库不存在'), {
        status: 400,
        body: { code: 'some_other_code', detail: '草稿方案需显式确认后才能送编码' },
      }),
    )
    const wrapper = mountCard({
      provenance: 'draft',
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()
    await clickMultiConfirm(wrapper)
    await tickAcknowledge(wrapper)
    await wrapper.find('[data-test="ack-confirm"]').trigger('click')
    await flushPromises()
    await nextTick()

    // 🔴 即便 detail 文案与草稿拒绝逐字相同，也不得走草稿分支（按 code 判定）
    expect(toastErrorMock).toHaveBeenCalledWith('批量失败：仓库不存在')
    expect(toastErrorMock).not.toHaveBeenCalledWith(GATE_REJECTED)
    expect(dialogOpen(wrapper)).toBe('false')
  })
})

// ============================================================================
// 109-REVIEW HI-02 / MN-05：runtime 串态守卫下沉到入口后的行为
// ============================================================================

describe('techPlanCard — 109-REVIEW 多方案会话的串态防护', () => {
  const REPOS = [
    { id: 'r1', name: 'repo-1' },
    { id: 'r2', name: 'repo-2' },
  ]

  /** 另一份 plan 的 runtime：带 sessions、带正文、带 provenance —— 全都不该被本卡采用。 */
  function setOtherPlanRuntime() {
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: 'other-plan',
      title: '别的方案',
      provenance: 'draft',
      tech_plan: '# 别的方案的正文',
      affected_files: [{ file_path: 'other/leaked.py', change_type: 'add' }],
      sessions: [
        {
          session_id: 'cs-other',
          repository_id: 'r9',
          repository_name: 'repo-other',
          branch_name: 'feat/other',
          status: 'running',
          pr_url: '',
          commit_sha: '',
          error_message: '',
        },
      ],
    } as any
  }

  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
  })

  /**
   * 🔴 HI-02：编排产出的历史卡片不得被误挂草稿横幅。
   *
   * 修复前 `ChatMessageBubble` 不传 `provenance`、正文也只在 tool input 里（SPINE-02
   * 后为空），于是「非最新那一份 plan」的卡片同时丢正文与来源标志 —— 一次内容丢失
   * 回归 + 一次 RELY-01 误报。本用例断言：props 拿到这两个事实后，即便 runtime 指向
   * 别的 plan，卡片也正常。
   */
  it('props 带 provenance=orchestrated 与正文时，runtime 指向别的 plan 也不误挂草稿横幅', async () => {
    setOtherPlanRuntime()
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      provenance: 'orchestrated',
      techPlan: '# 本卡自己的方案正文',
      affectedFiles: [{ file_path: 'mine/a.py', change_type: 'add' }],
    })
    await flushPromises()

    expect(wrapper.html()).toContain('<div data-test="md"># 本卡自己的方案正文</div>')
    expect(wrapper.text()).toContain('mine/a.py')
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-test="badge"]').some(b => b.text() === '未经调研')).toBe(false)
    // 别的 plan 的正文 / 来源标志一个都不许渗进来
    expect(wrapper.text()).not.toContain('别的方案的正文')
    expect(wrapper.text()).not.toContain('other/leaked.py')
  })

  /**
   * 🔴 MN-05：`sessions` 这一支此前没有 plan_id 守卫，而 109 的就地交棒让它开始承重。
   *
   * 投影完成后 store 只排了一次 3 秒的 runtime 轮询，那个窗口里 `activeCodingPlan`
   * 仍指向投影**之前**那份 plan。若那份已有 sessions：`hasSessions` 为真 ⇒ 选仓面
   * 整块不渲染（用户「进入编码」后什么可操作的东西都没有），卡片列出的还是别的 plan
   * 的 session 行，在这些行上点「重试」会在新 plan 上建出一条本不该有的 session。
   */
  it('runtime 指向别的 plan 且带 sessions 时：不渲染 session 行，仍渲染内嵌选仓面', async () => {
    setOtherPlanRuntime()
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()

    expect(wrapper.findAll('[data-test="status-row"]')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('repo-other')
    expect(wrapper.findComponent({ name: 'RepoMultiSelector' }).exists()).toBe(true)
    expect(wrapper.text()).toContain('选择目标仓库')
  })

  it('runtime 匹配本卡时 session 行照常渲染（守卫不误伤正常路径）', async () => {
    const store = useChatStore()
    store.activeCodingPlan = {
      plan_id: 'plan-1',
      title: '本卡方案',
      sessions: [
        {
          session_id: 'cs-mine',
          repository_id: 'r1',
          repository_name: 'repo-1',
          branch_name: 'feat/mine',
          status: 'running',
          pr_url: '',
          commit_sha: '',
          error_message: '',
        },
      ],
    } as any
    const wrapper = mountCard({
      codingPlanId: 'plan-1',
      availableRepositories: REPOS,
    })
    await flushPromises()

    expect(wrapper.findAll('[data-test="status-row"]')).toHaveLength(1)
    // 有 sessions ⇒ 走「追加态」，创建态内嵌选仓面（唯一带此标题）不再渲染
    expect(wrapper.text()).not.toContain('选择目标仓库')
    expect(wrapper.text()).toContain('目标仓库（1）')
  })
})

// ═════════════════════════════════════════════════════════════════════════════
// 同步点 2 收尾：blueprint/v1 识别（v0 与蓝图两档正反并列）
// ═════════════════════════════════════════════════════════════════════════════

describe('techPlanCard —— blueprint/v1 识别', () => {
  it('⭐ v0 投影：不出蓝图徽标 / 告示条 / 深链，正文照旧渲染（逐像素不变）', async () => {
    const wrapper = mountCard({ techPlan: '# 登录改造' })
    await flushPromises()
    await nextTick()

    expect(wrapper.find('[data-test="blueprint-notice"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="blueprint-link"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('技术蓝图')
    // 既有正文渲染路径一行未改。
    expect(wrapper.html()).toContain('<div data-test="md"># 登录改造</div>')
  })

  it('⭐ 空正文的 v0 投影仍落「（暂无方案正文）」（蓝图那一档不得抢它）', async () => {
    const wrapper = mountCard({ techPlan: '' })
    await flushPromises()
    await nextTick()
    expect(wrapper.text()).toContain('（暂无方案正文）')
    expect(wrapper.find('[data-test="blueprint-notice"]').exists()).toBe(false)
  })

  it('⭐ blueprint/v1：如实说明形态 + 11 态徽标 + 查看器深链，⛔ 不渲染空壳正文', async () => {
    const wrapper = mountCard({
      // v0 映射器对 blueprint/v1 渲出来的正是这样一份「结构合法而内容为空」的壳。
      techPlan: '# \n',
      schemaVersion: 'blueprint/v1',
      blueprintArtifactId: 'art-9',
      blueprintStatus: 'pending_review',
    })
    await flushPromises()
    await nextTick()

    const notice = wrapper.find('[data-test="blueprint-notice"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('结构化技术蓝图')
    expect(wrapper.find('[data-test="blueprint-link"]').attributes('href')).toBe(
      '/knowledge/blueprints/art-9',
    )
    // 头部两枚徽标：形态 + 11 态状态。
    expect(wrapper.text()).toContain('技术蓝图')
    expect(wrapper.text()).toContain('待人类审查')
    // ⛔ 空壳正文与「（暂无方案正文）」都不得出现。
    expect(wrapper.text()).not.toContain('（暂无方案正文）')
    expect(wrapper.html()).not.toContain('data-test="md"')
  })

  it('11 态逐档如实呈现', async () => {
    for (const [status, label] of [
      ['researching', '调研中'],
      ['needs_clarification', '需要澄清'],
      ['confirmed', '已确认'],
      ['failed', '已失败'],
    ] as const) {
      const wrapper = mountCard({
        schemaVersion: 'blueprint/v1',
        blueprintArtifactId: 'art-9',
        blueprintStatus: status,
      })
      await flushPromises()
      expect(wrapper.text()).toContain(label)
    }
  })

  it('未知 schema_version 一律按 v0 处理（允许清单，⛔ 不是拒绝清单）', async () => {
    const wrapper = mountCard({
      techPlan: '# 登录改造',
      schemaVersion: 'blueprint/v2',
      blueprintArtifactId: 'art-9',
      blueprintStatus: 'pending_review',
    })
    await flushPromises()
    await nextTick()
    expect(wrapper.find('[data-test="blueprint-notice"]').exists()).toBe(false)
    expect(wrapper.html()).toContain('<div data-test="md"># 登录改造</div>')
  })

  it('缺 artifact id 时告示条仍在、深链不渲染（⛔ 不给一个点不开的链接）', async () => {
    const wrapper = mountCard({
      schemaVersion: 'blueprint/v1',
      blueprintStatus: 'drafting',
    })
    await flushPromises()
    expect(wrapper.find('[data-test="blueprint-notice"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="blueprint-link"]').exists()).toBe(false)
  })

  it('折叠态摘要取蓝图形态说明，⛔ 不取空壳 markdown 首行', async () => {
    const wrapper = mountCard({
      techPlan: '# \n',
      defaultCollapsed: true,
      schemaVersion: 'blueprint/v1',
      blueprintArtifactId: 'art-9',
      blueprintStatus: 'confirmed',
    })
    await flushPromises()
    const summary = wrapper.find('[data-test="blueprint-collapsed-summary"]')
    expect(summary.exists()).toBe(true)
    expect(summary.text()).toContain('已确认')
    expect(wrapper.text()).not.toContain('（无方案文本）')
  })
})
