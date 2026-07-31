/**
 * 蓝图查看器路由页的页面测试（Phase 115-06）。
 *
 * 覆盖的九条（编号与 115-06-PLAN Task 3 ⑦逐条对应）：
 *  1. ⭐ **十段容器无条件渲染** —— doc 查询**还在 loading** 时 `section[id]` 计数就已经是 10。
 *     这是全相位最隐蔽的一条（P-4）：`AnchorNavLayout` 只在 mount 那一刻按 `sections` 逐个
 *     `getElementById`，段容器若写成条件渲染，observer 一个也挂不上 ⇒ 左栏高亮永远停在第一段，
 *     **而点击跳转照常工作** ⇒ 人肉走查只会觉得「高亮有点怪」。变异：给段容器加 `v-if="doc"`
 *     ⇒ 本条转红。
 *  2. ⭐ `sections` 恒 10 项，且零批注的段 `badge` **=== `''`**（⛔ 不是 `0`：那个布局件的空值
 *     判定不排除 0，会渲染出一个灰色的 0）。
 *  3. ⭐ 404 只有一句中性文案，且**不渲染任何蓝图元信息**（§20 断言 4）。
 *  4. ⭐ 确认门快照 404 ⇒ 页面**正常渲染**、无错误态、**toast 一次都没被调用**（§8.2 例外一 / P-10）。
 *  5. ⭐ approve 409 blocked ⇒ 打开解药面板，未决清单逐条可点。
 *  6. ⭐ `reflow.status = 'noop'` **不当失败**：不出错误 toast、页面无错误态。
 *  7. 零乐观更新：动作成功后调 `invalidateQueries`，且**没有** `setQueryData`。
 *  8. 生成中按段增量：空段出骨架 + 进度文案，非空段立即实渲（⛔ 不是全页 loading）。
 *  9. 历史版本只读：常驻提示出现，且线程侧栏拿到 `readonly === true`。
 *
 * 范式照 `pages/knowledge/__tests__/entity-detail.spec.ts`（手写最小 i18n 键树，⛔ 不 import
 * `zh-CN.json`）。⭐ 任何可能间接渲染时序图的组件一律 stub。
 */

import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import BlueprintViewerPage from '~/pages/knowledge/blueprints/[id].vue'
import { annotationCounts, sidebarGroups } from '~/utils/blueprintAnnotations'

const ARTIFACT_ID = '11111111-1111-1111-1111-111111111111'

const {
  routeState,
  routerReplace,
  toastMocks,
  api,
  timelineApi,
} = vi.hoisted(() => ({
  routeState: {
    params: { id: '11111111-1111-1111-1111-111111111111' } as Record<string, string>,
    query: {} as Record<string, string>,
  },
  routerReplace: vi.fn(),
  toastMocks: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
    loading: vi.fn(),
    promise: vi.fn(),
  },
  api: {
    getBlueprintDocument: vi.fn(),
    getBlueprintEvents: vi.fn(),
    getBlueprintThreads: vi.fn(),
    getBlueprintReviewSnapshot: vi.fn(),
    getBlueprintGate: vi.fn(),
    approveBlueprint: vi.fn(),
    rejectBlueprint: vi.fn(),
    answerThread: vi.fn(),
    resolveFinding: vi.fn(),
    dismissFinding: vi.fn(),
    createBlueprintComment: vi.fn(),
  },
  timelineApi: { getArtifactTimeline: vi.fn() },
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace: routerReplace, push: vi.fn(), back: vi.fn() }),
  RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
}))

vi.mock('@vueuse/head', () => ({ useHead: vi.fn() }))

vi.mock('~/composables/useToast', () => ({ useToast: () => toastMocks }))

vi.mock('~/api/blueprints', () => ({ default: api }))
vi.mock('~/api/deliveryArtifacts', () => ({ default: timelineApi }))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          pageTitle: '技术方案',
          section: {
            requirementSpec: '需求规格',
            repoAssociations: '仓库关联',
            currentStateAnalysis: '现状分析',
            implementationOverview: '实现概述',
            apiContracts: 'API 契约',
            impactAnalysis: '影响范围',
            interactionFlows: '交互流程',
            mustHaves: '验收锚点',
            decisionLog: '决策记录',
            associations: '关联',
          },
          progress: {
            fallbackDrafting: '起草中…',
            fallbackResearching: '调研中…',
            fallbackAiReviewing: 'AI 审查中…',
          },
          annotation: { sidebarToggleEmpty: '批注', crossBlock: '评论只能针对同一段落内的文字，请缩小选区' },
          version: { historyNotice: '正在查看历史版本 v{n}，操作已禁用', backToCurrent: '回到当前版本' },
          readonly: { notice: '已确认的蓝图不可直接改写，要改请先驳回' },
          review: {
            approveSuccess: '已通过，蓝图进入「已确认」',
            rejectSuccess: '已驳回（第 {n} 轮修订）',
            answerApplied: '答案已回灌，已产出 v{version_no}',
            answerUnchanged: '答案已记录，本次未产生新版本',
            answerConflict: '答案已保存，部分块存在冲突需人工确认',
            answerFailed: '答案已保存，回灌未成功，可稍后重试',
            panelUnavailable: '该方案尚未进入人审阶段，暂无审查面板',
          },
          finding: { resolveSuccess: '已标记为已修复', dismissSuccess: '已标记为误报忽略', noopNotice: '该发现此前已有结论' },
          thread: { commentCreated: '评论已提交' },
          error: {
            notFoundOrForbidden: '无权访问或该蓝图不存在',
            unavailable: '暂时读取不到该方案，请稍后重试',
            conflict: '方案已被其它操作更新，请刷新后重试',
            conflictVersion: '当前版本已到 v{version_no}，请刷新后重试',
            retry: '重试',
            backToKnowledge: '返回知识库',
          },
        },
      },
    },
  },
})

/** ⭐ 保留 `sections` prop 以便断言（AnchorNavLayout 在测试里必被 stub）。 */
const AnchorNavLayoutStub = {
  name: 'AnchorNavLayout',
  props: ['sections'],
  template: '<div data-testid="anchor-nav-stub"><slot /></div>',
}

const HeaderStub = {
  name: 'BlueprintViewerHeader',
  props: ['doc', 'counts', 'versions', 'currentVersionId', 'readonly', 'isLive', 'showClosed', 'sidebarCollapsed', 'currentStatus', 'revisionRound', 'submitting'],
  emits: ['toggle-sidebar', 'open-annotations', 'change-version', 'open-diff', 'approve', 'reject', 'toggle-closed-annotations'],
  template: '<div data-testid="viewer-header-stub" />',
}

const SidebarStub = {
  name: 'BlueprintThreadSidebar',
  props: ['threads', 'orphanedThreads', 'activeThreadId', 'readonly', 'showClosed', 'kindFilters', 'gateAvailable', 'submitting', 'draft'],
  emits: ['select', 'answer', 'resolve', 'dismiss', 'goto-gate', 'create-comment', 'cancel-comment'],
  template: '<div data-testid="thread-sidebar-stub" />',
}

const BlockedDialogStub = {
  name: 'BlueprintBlockedDialog',
  props: ['open', 'threadIds', 'threads'],
  template: `<div v-if="open" data-testid="blueprint-blocked-dialog">
    <span v-for="id in threadIds" :key="id" data-testid="blueprint-blocked-item">{{ id }}</span>
  </div>`,
}

const STUBS = {
  PageContainer: { template: '<div><slot /></div>' },
  AnchorNavLayout: AnchorNavLayoutStub,
  BlueprintViewerHeader: HeaderStub,
  BlueprintThreadSidebar: SidebarStub,
  BlueprintBlockedDialog: BlockedDialogStub,
  BlueprintSectionNav: true,
  BlueprintStageTimeline: true,
  BlueprintBlockDiff: true,
  BlueprintQualityPanel: true,
  BlueprintRejectDialog: true,
  BlueprintSelectionPopover: true,
  CitationPreviewDialog: true,
  MermaidDiagram: true,
  RequirementSpecSection: { name: 'RequirementSpecSection', template: '<div data-testid="stub-requirement-spec" />' },
  RepoAssociationsSection: { name: 'RepoAssociationsSection', template: '<div data-testid="stub-repo-associations" />' },
  CurrentStateSection: true,
  ImplementationOverviewSection: true,
  ApiContractsSection: { name: 'ApiContractsSection', template: '<div data-testid="stub-api-contracts" />' },
  ImpactAnalysisSection: true,
  InteractionFlowsSection: true,
  MustHavesSection: true,
  DecisionLogSection: true,
  BlueprintAssociationsSection: true,
  ScrollArea: { template: '<div><slot /></div>' },
  Sheet: { template: '<div><slot /></div>' },
  SheetContent: { template: '<div><slot /></div>' },
  SheetHeader: { template: '<div><slot /></div>' },
  SheetTitle: { template: '<div><slot /></div>' },
}

function makeContent(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'blueprint/v1',
    meta: { title: '订单履约链路重构', project_id: 'p-1' },
    requirement_spec: { goal: [], feature_points: [{ id: 'fp_1', title: '功能点', intent: 'greenfield' }] },
    repo_associations: [],
    current_state_analysis: [],
    implementation_overview: { requirement_narrative: [], items: [] },
    api_contracts: [],
    impact_analysis: { business_impact: [], affected_features: [] },
    interaction_flows: [],
    must_haves: { truths: [], artifacts: [], key_links: [] },
    citations: {},
    ...overrides,
  }
}

function makeDoc(overrides: Record<string, unknown> = {}) {
  return {
    version_id: 'v-1',
    version_no: 3,
    is_current: true,
    produced_by_ref: 'ai',
    created_at: '2026-08-01T00:00:00Z',
    content: makeContent(),
    quality: { citation_coverage: 1, ai_rejection_rate: null, human_edit_volume: null, clarification_rounds: null },
    ...overrides,
  }
}

function makeSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: ARTIFACT_ID,
    session_id: 's-1',
    current_status: 'pending_review',
    revision_round: 0,
    findings: {},
    clarifications: [],
    comments: [],
    orphaned_threads: [],
    unresolved: [],
    review_round: 1,
    unresolved_blocker_count: 0,
    unresolved_blocker_thread_ids: [],
    ...overrides,
  }
}

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const setQueryDataSpy = vi.spyOn(queryClient, 'setQueryData')
  const wrapper = mount(BlueprintViewerPage, {
    global: {
      plugins: [i18n, createPinia(), [VueQueryPlugin, { queryClient }]],
      stubs: STUBS,
    },
  })
  return { wrapper, invalidateSpy, setQueryDataSpy }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 60))

beforeEach(() => {
  vi.clearAllMocks()
  routeState.query = {}
  localStorage.clear()
  timelineApi.getArtifactTimeline.mockResolvedValue({ versions: [] })
  api.getBlueprintDocument.mockResolvedValue(makeDoc())
  api.getBlueprintEvents.mockResolvedValue({ session_id: 's-1', current_stage: 'pending_review', events: [] })
  api.getBlueprintThreads.mockResolvedValue({ threads: [] })
  api.getBlueprintReviewSnapshot.mockResolvedValue(makeSnapshot())
  api.getBlueprintGate.mockRejectedValue(new ApiError(404, '确认门未开启'))
})

describe('蓝图查看器 —— ⭐ 十段容器无条件渲染（P-4）', () => {
  it('1. doc 查询还在 loading 时，section[id] 计数就已经是 10', () => {
    const { wrapper } = mountPage()
    // ⛔ 刻意不 await：这一刻三个查询都还没落地。
    expect(wrapper.findAll('section[id]')).toHaveLength(10)
  })

  it('2. sections 恒 10 项，且零批注的段 badge === \'\'（⛔ 不是 0）', async () => {
    const { wrapper } = mountPage()
    await flush()
    const sections = wrapper.findComponent(AnchorNavLayoutStub).props('sections') as Array<{ id: string, badge: unknown }>
    expect(sections).toHaveLength(10)
    // 有内容的段照常出数字…
    expect(sections.find(section => section.id === 'requirement_spec')?.badge).toBe('1')
    // …零内容的段一律空串（⛔ 传 0 会被渲染成一个灰色的 0）。
    const zeroKeys = [
      'repo_associations',
      'current_state_analysis',
      'implementation_overview',
      'api_contracts',
      'impact_analysis',
      'interaction_flows',
      'must_haves',
      'decision_log',
    ]
    for (const key of zeroKeys)
      expect(sections.find(section => section.id === key)?.badge).toBe('')
  })
})

describe('蓝图查看器 —— 错误分档', () => {
  it('3. ⭐ 404 只有一句中性文案，且不渲染任何蓝图元信息（§20 断言 4）', async () => {
    api.getBlueprintDocument.mockRejectedValue(new ApiError(404, '未找到'))
    const { wrapper } = mountPage()
    await flush()
    const text = wrapper.text()
    const hits = text.split('无权访问或该蓝图不存在').length - 1
    expect(hits).toBe(1)
    expect(text).not.toContain('订单履约链路重构')
    expect(wrapper.find('[data-testid="viewer-header-stub"]').exists()).toBe(false)
    expect(wrapper.findAll('section[id]')).toHaveLength(0)
  })

  it('4. ⭐ 确认门 404 ⇒ 页面正常渲染、无错误态、toast 一次都没被调用（例外一 / P-10）', async () => {
    const { wrapper } = mountPage()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-error-state"]').exists()).toBe(false)
    expect(wrapper.findAll('section[id]')).toHaveLength(10)
    expect(wrapper.find('[data-testid="blueprint-gate-mount"]').exists()).toBe(false)
    for (const spy of Object.values(toastMocks))
      expect(spy).not.toHaveBeenCalled()
  })
})

describe('蓝图查看器 —— 动作端点接线', () => {
  it('5. ⭐ approve 409 blocked ⇒ 打开解药面板，未决清单逐条渲染', async () => {
    api.approveBlueprint.mockRejectedValue(
      new ApiError(409, '存在未决阻塞', { unresolved_blocker_thread_ids: ['t-a', 't-b'] }),
    )
    const { wrapper } = mountPage()
    await flush()
    wrapper.findComponent(HeaderStub).vm.$emit('approve')
    await flush()
    expect(wrapper.find('[data-testid="blueprint-blocked-dialog"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="blueprint-blocked-item"]')).toHaveLength(2)
  })

  it('6. ⭐ reflow.status = noop 不当失败：无错误 toast、页面无错误态', async () => {
    api.answerThread.mockResolvedValue({
      status: 'ok',
      thread_id: 't-1',
      reflow: { status: 'noop', version_id: '', version_no: 0, conflict_block_ids: [], thread_id: 't-1', detail: '' },
    })
    const { wrapper } = mountPage()
    await flush()
    wrapper.findComponent(SidebarStub).vm.$emit('answer', 't-1', '这是答案')
    await flush()
    expect(toastMocks.error).not.toHaveBeenCalled()
    expect(toastMocks.info).toHaveBeenCalled()
    expect(wrapper.find('[data-testid="blueprint-error-state"]').exists()).toBe(false)
  })

  it('7. 零乐观更新：成功后调 invalidateQueries，且没有 setQueryData', async () => {
    api.approveBlueprint.mockResolvedValue({ status: 'ok', current_status: 'confirmed', artifact_id: ARTIFACT_ID })
    const { wrapper, invalidateSpy, setQueryDataSpy } = mountPage()
    await flush()
    invalidateSpy.mockClear()
    wrapper.findComponent(HeaderStub).vm.$emit('approve')
    await flush()
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['blueprint'] })
    expect(setQueryDataSpy).not.toHaveBeenCalled()
  })
})

describe('蓝图查看器 —— 生成中与历史版本', () => {
  it('8. 生成中按段增量：空段出骨架 + 进度文案，非空段立即实渲', async () => {
    api.getBlueprintReviewSnapshot.mockResolvedValue(makeSnapshot({ current_status: 'drafting' }))
    const { wrapper } = mountPage()
    await flush()
    // 需求规格段有一个功能点 ⇒ 立即实渲
    expect(wrapper.find('[data-testid="stub-requirement-spec"]').exists()).toBe(true)
    // API 契约段为空 + 生成中 ⇒ 骨架 + 进度文案，⛔ 不是全页 loading
    const apiSection = wrapper.find('section#api_contracts')
    expect(apiSection.attributes('aria-busy') ?? apiSection.find('[aria-busy="true"]').exists()).toBeTruthy()
    expect(apiSection.text()).toContain('起草中…')
    expect(wrapper.find('[data-testid="stub-api-contracts"]').exists()).toBe(false)
  })

  it('9. 历史版本 ⇒ 常驻只读提示出现，且侧栏拿到 readonly', async () => {
    routeState.query = { version: 'v-0' }
    api.getBlueprintDocument.mockResolvedValue(makeDoc({ is_current: false, version_no: 2 }))
    const { wrapper } = mountPage()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-history-notice"]').exists()).toBe(true)
    expect(wrapper.findComponent(SidebarStub).props('readonly')).toBe(true)
  })
})

/**
 * ⭐ MJ-03 回归：顶栏的「未决 BLOCKER」必须与后端 confirm 闸同口径。
 *
 * 判据源是人审快照的权威字段 `unresolved_blocker_count`（后端由 confirm 闸的**同一个方法**
 * 产出）。口径漂移的症状很具体：顶栏说「0 条未决」，用户点「确认」必吃 409 —— 信息面在
 * 鼓励用户按一个注定失败的按钮。
 */
describe('蓝图查看器 —— 顶栏未决 BLOCKER 计数（MJ-03）', () => {
  /** 前端派生会漏计的两类：失锚的 open BLOCKER、已作答的 BLOCKER。 */
  function makeBlockerThread(overrides: Record<string, unknown> = {}) {
    return {
      thread_id: 'th-blocker',
      kind: 'ai_review_finding',
      severity: 'blocker',
      status: 'open',
      blocking: true,
      anchor_status: 'anchored',
      anchor: { block_id: 'b1', section_path: 'requirement_spec', start_offset: 0, end_offset: 1 },
      question: '',
      created_at: '2026-08-01T00:00:00Z',
      messages: [],
      ...overrides,
    }
  }

  it('10. 顶栏取快照的权威 unresolved_blocker_count，⛔ 不取本地派生', async () => {
    api.getBlueprintReviewSnapshot.mockResolvedValue(makeSnapshot({ unresolved_blocker_count: 2 }))
    api.getBlueprintThreads.mockResolvedValue({ threads: [] })
    const { wrapper } = mountPage()
    await flush()
    expect((wrapper.findComponent(HeaderStub).props('counts') as { blocker: number }).blocker).toBe(2)
  })

  it('11. 权威值为 0 时不被本地派生覆盖（?? 而不是 ||）', async () => {
    api.getBlueprintReviewSnapshot.mockResolvedValue(makeSnapshot({ unresolved_blocker_count: 0 }))
    api.getBlueprintThreads.mockResolvedValue({ threads: [makeBlockerThread()] })
    const { wrapper } = mountPage()
    await flush()
    expect((wrapper.findComponent(HeaderStub).props('counts') as { blocker: number }).blocker).toBe(0)
  })

  it('12. ⭐ 快照未就绪时的本地占位也要算上失锚与已作答的 BLOCKER', () => {
    // 快照缺席 ⇒ 顶栏落到本地派生。它必须与后端三条 AND 同口径，否则占位期同样在说谎。
    const list = [
      makeBlockerThread({ thread_id: 'orphaned', anchor_status: 'orphaned' }),
      makeBlockerThread({ thread_id: 'answered', status: 'answered' }),
      // 对照：已处置的 BLOCKER 不计入（证明判据非恒真）
      makeBlockerThread({ thread_id: 'resolved', status: 'resolved' }),
    ] as never
    expect(annotationCounts(sidebarGroups(list), list).unresolvedBlocker).toBe(2)
  })

  it('13. 段 badge 与顶栏计数同口径：失锚/已作答的 BLOCKER 让所在段标红', async () => {
    api.getBlueprintReviewSnapshot.mockResolvedValue(makeSnapshot({ unresolved_blocker_count: 1 }))
    api.getBlueprintThreads.mockResolvedValue({ threads: [makeBlockerThread({ status: 'answered' })] })
    const { wrapper } = mountPage()
    await flush()
    const sections = wrapper.findComponent(AnchorNavLayoutStub).props('sections') as Array<{ id: string, badgeTone: string }>
    expect(sections.find(section => section.id === 'requirement_spec')?.badgeTone).toBe('danger')
  })
})
