/**
 * 阶段 1 确认门面板的组件测试（Phase 115-07）。
 *
 * 覆盖路径（编号与 115-07-PLAN Task 2 ②逐条对应）：
 *  1a/1b/1c. ⭐ **三种 gate 404 的行为完全一致** —— 「确认门未开启」/「artifact 不存在」/
 *     「该 artifact 没有蓝图编排会话」三个 `detail` 各跑一遍，断言**同一组**结果：面板不存在、
 *     错误态不存在、六个 toast mock 零调用。这是「⛔ 不靠 `detail` 文本分支判定」（P-10）唯一
 *     形状正确的可证伪判据 —— 一旦有人按文案分档，三条里必然有一条转红。
 *  2. gate 200 ⇒ 面板渲染，仓库行数 == 快照仓库数。
 *  3~9. ⭐ **七个动作各触发一次 POST**，且成功后 `['blueprint','gate',id]` 与
 *     `['blueprint','snapshot',id]` **双失效**（⛔ 零乐观更新）。
 *  10. ⭐ pending 行禁用 + 「调研中」；非 pending 行可用（正反并列）。
 *  11. ⭐ 存在 pending ⇒ 确认主按钮 `disabled` + Tooltip 文案；无 pending ⇒ 可用。
 *  12/13. ⭐ `confirm/` 409 两档：`blocked_reason === 'pending_clarification'` ⇒ 出现
 *     「前往未决线程」并 emit `goto-unresolved`；其余 `blocked_reason` ⇒ 只回显 `detail`，无该按钮。
 *  14/15. 破坏性动作走二次确认：确认框返回 `false` ⇒ **不发 POST**（`remove-repo` 与 `confirm` 各一条）。
 *  16/17. 编辑职责：空 / 纯空格 ⇒ 提交 `disabled`；有内容 ⇒ 一次 POST 且入参含文本与 `rerun`。
 *  18/19. `upgrade-research` **仅 `indirect` 行**渲染，且入参只有 `repository_id`。
 *  20. `rejected-to-boundary` 在无 rejected 候选时不渲染。
 *  21. ⛔ 面板内零 `refetchInterval`（源码扫描，与 `blueprint-source-guard.spec.ts` 互为双保险）。
 *
 * 范式照 `components/prompts/__tests__/PromptVersionDiff.test.ts`（覆盖路径编号清单 + 工厂 +
 * 正负成对 + `data-*` 定位）与 `pages/knowledge/__tests__/blueprintViewer.spec.ts`（手写最小
 * i18n 键树，⛔ 不 import `zh-CN.json`）。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import { ApiError } from '~/api/client'
import BlueprintGatePanel from '~/components/blueprint/BlueprintGatePanel.vue'
import BlueprintViewerPage from '~/pages/knowledge/blueprints/[id].vue'

const ARTIFACT_ID = '11111111-1111-1111-1111-111111111111'

const {
  routeState,
  routerReplace,
  toastMocks,
  confirmMock,
  api,
  timelineApi,
  reposApi,
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
  confirmMock: vi.fn(),
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
    confirmGate: vi.fn(),
    removeRepo: vi.fn(),
    addRepo: vi.fn(),
    reclassifyRole: vi.fn(),
    editResponsibility: vi.fn(),
    rejectedToBoundary: vi.fn(),
    upgradeResearch: vi.fn(),
  },
  timelineApi: { getArtifactTimeline: vi.fn() },
  reposApi: { list: vi.fn() },
}))

vi.mock('vue-router', () => ({
  useRoute: () => routeState,
  useRouter: () => ({ replace: routerReplace, push: vi.fn(), back: vi.fn() }),
  RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
}))

vi.mock('@vueuse/head', () => ({ useHead: vi.fn() }))
vi.mock('~/composables/useToast', () => ({ useToast: () => toastMocks }))
vi.mock('~/composables/useConfirmDialog', () => ({ useConfirmDialog: () => ({ confirm: confirmMock }) }))
vi.mock('~/api/blueprints', () => ({ default: api }))
vi.mock('~/api/deliveryArtifacts', () => ({ default: timelineApi }))
vi.mock('~/api/repositories', () => ({ repositoriesApi: reposApi }))

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
          progress: { fallbackDrafting: '起草中…' },
          annotation: { sidebarToggleEmpty: '批注', crossBlock: '跨块选区' },
          version: { historyNotice: '历史版本 v{n}', backToCurrent: '回到当前版本' },
          readonly: { notice: '已确认的蓝图不可直接改写' },
          repo: {
            roleDirect: '直接改动',
            roleIndirect: '间接影响',
            fitnessSuitable: '适配',
            fitnessPartial: '部分适配',
            fitnessUnsuitable: '不适配',
            responsibility: '本仓职责',
            empty: '本方案未关联任何仓库',
          },
          gate: {
            title: '仓库集确认门',
            notice: '确认仓库集与职责后才进入方案拟定；确认后锁定，后续变更须重开确认门',
            confirm: '确认仓库集并进入方案拟定',
            removeRepo: '移除仓库',
            addRepo: '手动加仓',
            addRepoPlaceholder: '选择要补进本方案的仓库…',
            addRepoSubmit: '加入本方案',
            reclassifyRole: '改判角色',
            editResponsibility: '修改职责',
            rejectedToBoundary: '沉淀为边界禁区',
            upgradeResearch: '升级深调研',
            pendingResearch: '调研中，暂不可确认',
            researching: '调研中',
            evidenceCount: '证据 {n}',
            responsibilityTitle: '修改本仓职责',
            responsibilityHint: '勾选下方选项才会重新调研该仓',
            responsibilityPlaceholder: '这个仓在本方案里承担什么？',
            rerunResearch: '重新调研该仓',
            save: '保存',
            cancel: '取消',
            unresolvedClarification: '存在未解决的阻塞澄清线程',
            gotoUnresolved: '前往未决线程',
            removeTitle: '从方案中移除该仓库？',
            removeBody: '移除后该仓的调研结论与职责将不再参与本方案，并可沉淀为仓库章程的边界禁区候选。',
            removeConfirm: '确认移除',
            lockTitle: '确认仓库集并锁定？',
            lockBody: '确认后仓库集与职责被锁定，后续变更必须重开确认门。你将被记入本方案的评审人名单。',
            lockConfirm: '确认锁定',
            confirmSuccess: '仓库集已锁定',
            removeSuccess: '已移除该仓库',
            addSuccess: '已加入该仓库',
            reclassifySuccess: '已改判角色',
            editSuccess: '已更新职责',
            upgradeSuccess: '已升级为深调研',
            boundarySuccess: '已沉淀 {n} 个仓库的边界禁区草案',
          },
          review: { approveSuccess: '已通过', rejectSuccess: '已驳回', panelUnavailable: '暂无审查面板' },
          finding: { resolveSuccess: '已修复', dismissSuccess: '已忽略', noopNotice: '此前已有结论' },
          thread: { commentCreated: '评论已提交' },
          error: {
            notFoundOrForbidden: '无权访问或该蓝图不存在',
            unavailable: '暂时读取不到该方案，请稍后重试',
            conflict: '方案已被其它操作更新，请刷新后重试',
            conflictVersion: '当前版本已到 v{version_no}',
            retry: '重试',
            refresh: '刷新重试',
            backToKnowledge: '返回知识库',
          },
        },
      },
    },
  },
})

// ── 面板内部依赖的最小 stub ───────────────────────────────────────────────────

/** `RepositoryPicker` 只 emit `update:modelValue`，测试里不需要它的弹层。 */
const RepositoryPickerStub = {
  name: 'RepositoryPicker',
  props: ['modelValue', 'repositories', 'placeholder', 'allowManualInput'],
  emits: ['update:modelValue'],
  template: '<div data-testid="repository-picker-stub" />',
}

/** 受控 `Dialog`：`open` 为真才渲染 slot，便于断言职责编辑弹窗内的控件。 */
const DialogStub = {
  name: 'Dialog',
  props: ['open'],
  emits: ['update:open'],
  template: '<div v-if="open"><slot /></div>',
}

const PASSTHROUGH = { template: '<div><slot /></div>' }

const CheckboxStub = {
  name: 'Checkbox',
  props: ['modelValue'],
  emits: ['update:modelValue'],
  template: '<button type="button" data-testid="checkbox-stub" @click="$emit(\'update:modelValue\', !modelValue)" />',
}

const PANEL_STUBS = {
  RepositoryPicker: RepositoryPickerStub,
  Dialog: DialogStub,
  DialogContent: PASSTHROUGH,
  DialogHeader: PASSTHROUGH,
  DialogFooter: PASSTHROUGH,
  DialogTitle: PASSTHROUGH,
  DialogDescription: PASSTHROUGH,
  Checkbox: CheckboxStub,
  Tooltip: PASSTHROUGH,
  TooltipProvider: PASSTHROUGH,
  TooltipTrigger: PASSTHROUGH,
  TooltipContent: PASSTHROUGH,
}

/** 页面级用例的 stub 清单，与 `blueprintViewer.spec.ts` 保持一致（⛔ 不改那个文件）。 */
const PAGE_STUBS = {
  ...PANEL_STUBS,
  PageContainer: PASSTHROUGH,
  AnchorNavLayout: { name: 'AnchorNavLayout', props: ['sections'], template: '<div><slot /></div>' },
  BlueprintViewerHeader: { name: 'BlueprintViewerHeader', template: '<div data-testid="viewer-header-stub" />' },
  BlueprintThreadSidebar: { name: 'BlueprintThreadSidebar', props: ['gateAvailable'], template: '<div data-testid="thread-sidebar-stub" />' },
  BlueprintBlockedDialog: true,
  BlueprintSectionNav: true,
  BlueprintStageTimeline: true,
  BlueprintBlockDiff: true,
  BlueprintQualityPanel: true,
  BlueprintRejectDialog: true,
  BlueprintSelectionPopover: true,
  CitationPreviewDialog: true,
  MermaidDiagram: true,
  RequirementSpecSection: true,
  RepoAssociationsSection: true,
  CurrentStateSection: true,
  ImplementationOverviewSection: true,
  ApiContractsSection: true,
  ImpactAnalysisSection: true,
  InteractionFlowsSection: true,
  MustHavesSection: true,
  DecisionLogSection: true,
  BlueprintAssociationsSection: true,
  ScrollArea: PASSTHROUGH,
  Sheet: PASSTHROUGH,
  SheetContent: PASSTHROUGH,
  SheetHeader: PASSTHROUGH,
  SheetTitle: PASSTHROUGH,
}

// ── 工厂 ──────────────────────────────────────────────────────────────────────

function makeRepo(overrides: Record<string, unknown> = {}) {
  return {
    repository_id: 'repo-1',
    repository_name: 'order-service',
    role_suggestion: 'direct',
    responsibility: '承接下单主链路',
    confidence: 'high',
    fitness: { verdict: 'suitable' },
    current_state_summary: '现有下单接口位于 api/orders',
    routing_evidence: { citations: ['c1', 'c2'] },
    ...overrides,
  }
}

function makeGate(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: ARTIFACT_ID,
    session_id: 's-1',
    thread_id: 'th-1',
    thread_status: 'open',
    current_stage: 'repo_confirmation',
    repo_count: 2,
    pending_research_repository_ids: [] as string[],
    repos: [makeRepo(), makeRepo({ repository_id: 'repo-2', repository_name: 'billing-service', role_suggestion: 'indirect' })],
    ...overrides,
  }
}

function makeActionResult(overrides: Record<string, unknown> = {}) {
  return {
    action: 'confirm',
    repository_id: 'repo-1',
    thread_id: 'th-1',
    requires_research: false,
    ready_to_lock: true,
    locked: false,
    upgraded: false,
    locked_repo_count: 0,
    ...overrides,
  }
}

function makeDoc() {
  return {
    version_id: 'v-1',
    version_no: 3,
    is_current: true,
    produced_by_ref: 'ai',
    created_at: '2026-08-01T00:00:00Z',
    content: {
      schema_version: 'blueprint/v1',
      meta: { title: '订单履约链路重构', project_id: 'p-1' },
      requirement_spec: { goal: [], feature_points: [] },
      repo_associations: [],
      current_state_analysis: [],
      implementation_overview: { requirement_narrative: [], items: [] },
      api_contracts: [],
      impact_analysis: { business_impact: [], affected_features: [] },
      interaction_flows: [],
      must_haves: { truths: [], artifacts: [], key_links: [] },
      citations: {},
    },
    quality: { citation_coverage: 1, ai_rejection_rate: null, human_edit_volume: null, clarification_rounds: null },
  }
}

function makeReviewSnapshot() {
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
  }
}

function mountPanel(snapshot: Record<string, unknown> = makeGate()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
  const setQueryDataSpy = vi.spyOn(queryClient, 'setQueryData')
  const wrapper = mount(BlueprintGatePanel, {
    props: { artifactId: ARTIFACT_ID, snapshot: snapshot as never },
    global: { plugins: [i18n, createPinia(), [VueQueryPlugin, { queryClient }]], stubs: PANEL_STUBS },
  })
  return { wrapper, invalidateSpy, setQueryDataSpy }
}

function mountPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = mount(BlueprintViewerPage, {
    global: { plugins: [i18n, createPinia(), [VueQueryPlugin, { queryClient }]], stubs: PAGE_STUBS },
  })
  return { wrapper }
}

const flush = () => new Promise(resolve => setTimeout(resolve, 60))

/** 双失效断言：⛔ 只失效 gate 会让正文停在旧状态。 */
function expectDoubleInvalidate(invalidateSpy: ReturnType<typeof vi.spyOn>): void {
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['blueprint', 'gate', ARTIFACT_ID] })
  expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['blueprint', 'snapshot', ARTIFACT_ID] })
}

beforeEach(() => {
  vi.clearAllMocks()
  routeState.query = {}
  localStorage.clear()
  confirmMock.mockResolvedValue(true)
  reposApi.list.mockResolvedValue([])
  timelineApi.getArtifactTimeline.mockResolvedValue({ versions: [] })
  api.getBlueprintDocument.mockResolvedValue(makeDoc())
  api.getBlueprintEvents.mockResolvedValue({ session_id: 's-1', current_stage: 'pending_review', events: [] })
  api.getBlueprintThreads.mockResolvedValue({ threads: [] })
  api.getBlueprintReviewSnapshot.mockResolvedValue(makeReviewSnapshot())
  api.getBlueprintGate.mockResolvedValue(makeGate())
  api.confirmGate.mockResolvedValue(makeActionResult({ locked: true }))
  api.removeRepo.mockResolvedValue(makeActionResult({ action: 'remove_repo' }))
  api.addRepo.mockResolvedValue(makeActionResult({ action: 'add_repo' }))
  api.reclassifyRole.mockResolvedValue(makeActionResult({ action: 'reclassify_role' }))
  api.editResponsibility.mockResolvedValue(makeActionResult({ action: 'edit_responsibility' }))
  api.rejectedToBoundary.mockResolvedValue({ candidate_count: 3, draft_count: 2, repository_count: 2 })
  api.upgradeResearch.mockResolvedValue(makeActionResult({ action: 'upgrade_research', upgraded: true }))
})

// ⭐ 三种 404 的 `detail` 各跑一遍，断言**同一组**结果 —— 一旦有人按文案分档，必有一条转红。
describe('⭐ gate 非 200 ⇒ 不渲染且不报错（§8.2 例外一 / P-10）', () => {
  it('1a. 404「确认门未开启」⇒ 面板不存在、无错误态、toast 零调用', async () => {
    api.getBlueprintGate.mockRejectedValue(new ApiError(404, '确认门未开启'))
    const { wrapper } = mountPage()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-error-state"]').exists()).toBe(false)
    for (const spy of Object.values(toastMocks))
      expect(spy).not.toHaveBeenCalled()
  })

  it('1b. 404「artifact 不存在」⇒ 行为与 1a 逐字相同', async () => {
    api.getBlueprintGate.mockRejectedValue(new ApiError(404, 'artifact 不存在'))
    const { wrapper } = mountPage()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-error-state"]').exists()).toBe(false)
    for (const spy of Object.values(toastMocks))
      expect(spy).not.toHaveBeenCalled()
  })

  it('1c. 404「该 artifact 没有蓝图编排会话」⇒ 行为与 1a 逐字相同', async () => {
    api.getBlueprintGate.mockRejectedValue(new ApiError(404, '该 artifact 没有蓝图编排会话'))
    const { wrapper } = mountPage()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-panel"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-error-state"]').exists()).toBe(false)
    for (const spy of Object.values(toastMocks))
      expect(spy).not.toHaveBeenCalled()
  })

  it('2. gate 200 ⇒ 面板在页面上渲染，仓库行数 == 快照仓库数', async () => {
    const { wrapper } = mountPage()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-mount"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="blueprint-gate-panel"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="blueprint-gate-repo-row"]')).toHaveLength(2)
  })
})

describe('⭐ 七个动作：一次 POST + 双失效（⛔ 零乐观更新）', () => {
  it('3. confirm：二次确认通过后发一次 POST 且双失效', async () => {
    const { wrapper, invalidateSpy, setQueryDataSpy } = mountPanel()
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-confirm"]').trigger('click')
    await flush()
    expect(api.confirmGate).toHaveBeenCalledTimes(1)
    expect(api.confirmGate).toHaveBeenCalledWith(ARTIFACT_ID)
    expectDoubleInvalidate(invalidateSpy)
    expect(setQueryDataSpy).not.toHaveBeenCalled()
  })

  it('4. remove-repo：二次确认通过后发一次 POST 且入参含 repository_id', async () => {
    const { wrapper, invalidateSpy } = mountPanel()
    await flush()
    await wrapper.findAll('[data-testid="blueprint-gate-remove-repo"]')[0].trigger('click')
    await flush()
    expect(api.removeRepo).toHaveBeenCalledTimes(1)
    expect(api.removeRepo).toHaveBeenCalledWith(ARTIFACT_ID, { repository_id: 'repo-1' })
    expectDoubleInvalidate(invalidateSpy)
  })

  it('5. add-repo：选中一个仓 ⇒ 一次 POST，成功后选择器清空', async () => {
    const { wrapper, invalidateSpy } = mountPanel()
    await flush()
    wrapper.findComponent(RepositoryPickerStub).vm.$emit('update:modelValue', ['repo-9'])
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-add-repo-submit"]').trigger('click')
    await flush()
    expect(api.addRepo).toHaveBeenCalledTimes(1)
    expect(api.addRepo).toHaveBeenCalledWith(ARTIFACT_ID, { repository_id: 'repo-9' })
    expect(wrapper.findComponent(RepositoryPickerStub).props('modelValue')).toEqual([])
    expectDoubleInvalidate(invalidateSpy)
  })

  it('6. reclassify-role：segmented control 即时提交一次 POST', async () => {
    const { wrapper, invalidateSpy } = mountPanel()
    await flush()
    // 第一行是 direct ⇒ 点「间接影响」触发改判
    await wrapper.findAll('[data-testid="blueprint-gate-role-indirect"]')[0].trigger('click')
    await flush()
    expect(api.reclassifyRole).toHaveBeenCalledTimes(1)
    expect(api.reclassifyRole).toHaveBeenCalledWith(ARTIFACT_ID, { repository_id: 'repo-1', role: 'indirect' })
    expectDoubleInvalidate(invalidateSpy)
  })

  it('7. edit-responsibility：受控 Dialog 提交一次 POST，入参含文本与 rerun', async () => {
    const { wrapper, invalidateSpy } = mountPanel()
    await flush()
    await wrapper.findAll('[data-testid="blueprint-gate-edit-responsibility"]')[0].trigger('click')
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-responsibility-input"]').setValue('只做下单主链路')
    await wrapper.find('[data-testid="blueprint-gate-responsibility-rerun"]').trigger('click')
    await wrapper.find('[data-testid="blueprint-gate-responsibility-submit"]').trigger('click')
    await flush()
    expect(api.editResponsibility).toHaveBeenCalledTimes(1)
    expect(api.editResponsibility).toHaveBeenCalledWith(ARTIFACT_ID, {
      repository_id: 'repo-1',
      responsibility: '只做下单主链路',
      rerun: true,
    })
    expectDoubleInvalidate(invalidateSpy)
  })

  it('8. upgrade-research：indirect 行发一次 POST，入参只有 repository_id', async () => {
    const { wrapper, invalidateSpy } = mountPanel()
    await flush()
    const buttons = wrapper.findAll('[data-testid="blueprint-gate-upgrade-research"]')
    expect(buttons).toHaveLength(1)
    await buttons[0].trigger('click')
    await flush()
    expect(api.upgradeResearch).toHaveBeenCalledTimes(1)
    expect(api.upgradeResearch).toHaveBeenCalledWith(ARTIFACT_ID, { repository_id: 'repo-2' })
    expectDoubleInvalidate(invalidateSpy)
  })

  it('9. rejected-to-boundary：存在 rejected 候选时发一次 POST', async () => {
    const snapshot = makeGate({
      repos: [makeRepo(), makeRepo({ repository_id: 'repo-3', removed: true })],
    })
    const { wrapper, invalidateSpy } = mountPanel(snapshot)
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-rejected-to-boundary"]').trigger('click')
    await flush()
    expect(api.rejectedToBoundary).toHaveBeenCalledTimes(1)
    expectDoubleInvalidate(invalidateSpy)
  })
})

describe('⭐ pending 调研态（正反并列）', () => {
  it('10. 命中 pending 的行动作禁用 + 「调研中」；未命中的行可用', async () => {
    const { wrapper } = mountPanel(makeGate({ pending_research_repository_ids: ['repo-1'] }))
    await flush()
    const rows = wrapper.findAll('[data-testid="blueprint-gate-repo-row"]')
    expect(rows[0].attributes('data-pending')).toBe('true')
    expect(rows[0].text()).toContain('调研中')
    expect(rows[0].find('[data-testid="blueprint-gate-remove-repo"]').attributes('disabled')).toBeDefined()
    // 反面：未命中的行按钮可用，且没有「调研中」
    expect(rows[1].attributes('data-pending')).toBe('false')
    expect(rows[1].find('[data-testid="blueprint-gate-remove-repo"]').attributes('disabled')).toBeUndefined()
  })

  it('11. 存在 pending ⇒ 确认主按钮 disabled + Tooltip；无 pending ⇒ 可用', async () => {
    const blocked = mountPanel(makeGate({ pending_research_repository_ids: ['repo-1'] }))
    await flush()
    expect(blocked.wrapper.find('[data-testid="blueprint-gate-confirm"]').attributes('disabled')).toBeDefined()
    expect(blocked.wrapper.find('[data-testid="blueprint-gate-confirm-tooltip"]').text()).toContain('调研中，暂不可确认')

    const free = mountPanel()
    await flush()
    expect(free.wrapper.find('[data-testid="blueprint-gate-confirm"]').attributes('disabled')).toBeUndefined()
    expect(free.wrapper.find('[data-testid="blueprint-gate-confirm-tooltip"]').exists()).toBe(false)
  })
})

describe('⭐ confirm/ 的 409 两档', () => {
  it('12. blocked_reason = pending_clarification ⇒ 出现「前往未决线程」且点击 emit goto-unresolved', async () => {
    api.confirmGate.mockRejectedValue(
      new ApiError(409, '存在未解决的阻塞澄清线程', { blocked_reason: 'pending_clarification' }),
    )
    const { wrapper } = mountPanel()
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-confirm"]').trigger('click')
    await flush()
    const cure = wrapper.find('[data-testid="blueprint-gate-goto-unresolved"]')
    expect(cure.exists()).toBe(true)
    await cure.trigger('click')
    expect(wrapper.emitted('goto-unresolved')).toHaveLength(1)
  })

  it('13. 其余 blocked_reason ⇒ 只回显 detail，⛔ 无跳转按钮', async () => {
    api.confirmGate.mockRejectedValue(
      new ApiError(409, '确认门快照已被其它操作更新，请刷新后重新确认', { blocked_reason: 'snapshot_changed' }),
    )
    const { wrapper } = mountPanel()
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-confirm"]').trigger('click')
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-goto-unresolved"]').exists()).toBe(false)
    expect(toastMocks.error).toHaveBeenCalledWith('确认门快照已被其它操作更新，请刷新后重新确认', '刷新重试')
  })
})

describe('⭐ 破坏性动作的二次确认（正反并列）', () => {
  it('14. 移除仓：确认框返回 false ⇒ 不发 POST', async () => {
    confirmMock.mockResolvedValue(false)
    const { wrapper } = mountPanel()
    await flush()
    await wrapper.findAll('[data-testid="blueprint-gate-remove-repo"]')[0].trigger('click')
    await flush()
    expect(api.removeRepo).not.toHaveBeenCalled()
  })

  it('15. 确认锁定：确认框返回 false ⇒ 不发 POST', async () => {
    confirmMock.mockResolvedValue(false)
    const { wrapper } = mountPanel()
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-confirm"]').trigger('click')
    await flush()
    expect(api.confirmGate).not.toHaveBeenCalled()
  })

  it('16. 移除仓的确认文案逐字照 §16（标题 / 正文 / 按钮 / destructive）', async () => {
    const { wrapper } = mountPanel()
    await flush()
    await wrapper.findAll('[data-testid="blueprint-gate-remove-repo"]')[0].trigger('click')
    await flush()
    expect(confirmMock).toHaveBeenCalledWith({
      title: '从方案中移除该仓库？',
      description: '移除后该仓的调研结论与职责将不再参与本方案，并可沉淀为仓库章程的边界禁区候选。',
      confirmText: '确认移除',
      variant: 'destructive',
    })
  })
})

describe('编辑职责 / 升级深调研 / rejected 沉淀的渲染规则', () => {
  it('17. 编辑职责：空与纯空格都让提交 disabled，有内容才可提交', async () => {
    const { wrapper } = mountPanel(makeGate({ repos: [makeRepo({ responsibility: '' })] }))
    await flush()
    await wrapper.find('[data-testid="blueprint-gate-edit-responsibility"]').trigger('click')
    await flush()
    const submit = () => wrapper.find('[data-testid="blueprint-gate-responsibility-submit"]')
    expect(submit().attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="blueprint-gate-responsibility-input"]').setValue('   ')
    expect(submit().attributes('disabled')).toBeDefined()
    await wrapper.find('[data-testid="blueprint-gate-responsibility-input"]').setValue('有内容')
    expect(submit().attributes('disabled')).toBeUndefined()
  })

  it('18. upgrade-research 仅 indirect 行渲染：direct 行不出现该按钮', async () => {
    const { wrapper } = mountPanel(makeGate({ repos: [makeRepo({ role_suggestion: 'direct' })] }))
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-upgrade-research"]').exists()).toBe(false)
    expect(wrapper.findAll('[data-testid="blueprint-gate-repo-row"]')).toHaveLength(1)
  })

  it('19. rejected 候选为空 ⇒ 不渲染「沉淀为边界禁区」次级动作', async () => {
    const { wrapper } = mountPanel()
    await flush()
    expect(wrapper.find('[data-testid="blueprint-gate-rejected-to-boundary"]').exists()).toBe(false)
  })
})

describe('⛔ 面板不是 live 面', () => {
  it('20. 两个组件源码内零 refetchInterval（与源码守卫互为双保险）', () => {
    const root = resolve(process.cwd(), 'src/components/blueprint')
    for (const name of ['BlueprintGatePanel.vue', 'BlueprintGateRepoRow.vue']) {
      const source = readFileSync(resolve(root, name), 'utf8')
      expect(source).not.toMatch(/refetchInterval/)
      expect(source).not.toMatch(/setQueryData/)
    }
  })
})
