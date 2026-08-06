/**
 * 九个段组件与四张卡的组件测试（Phase 115-05）。
 *
 * 覆盖路径（编号与 115-05-PLAN Task 3 ⑤逐条对应）：
 *  1. 每段透传 blockCtx —— 七个走 `BlueprintBlockList` 的段各自至少交出一个块序列，
 *     且第一个的 `props()` 含 `threads` / `citations` / `readonly` / `activeThreadId` 四键。
 *  2. ⭐ 段组件零批注 —— `BlueprintBlockList` 被 stub 之后，若段组件自己渲染了划线标记就会
 *     在 `html()` 里露出来；七段一律不含。
 *  3. `RepoAssociationCard` —— role 双色 / `unsuitable` 的 reasons 原样交出 / ⭐ SC-3 跳转 /
 *     `cross_team` 与 `confirmed_at_gate` 两枚旁注徽标（各自正反并列）。
 *  4. `CurrentStateSection` —— finding 缺引用的质量信号（正反并列）+ 功能点 chip 的跨段跳转。
 *  5. ⭐ `ApiContractCard` 的读取位置 —— `data_source.availability` 正常读；⭐ **顶层有
 *     `availability` 而 `data_source` 内没有 ⇒ 渲染「未标注」**（113-05 决策的 UI 侧证伪：
 *     回落读顶层会让后端「写错位置」的缺陷被静默掩盖）。
 *  6. `ImpactMatrixTable` —— `reversible === false` 严格判等（缺键不加「不可逆」徽标）。
 *  7. `InteractionFlowsSection` —— mermaid 合成块的有无 + `api_ref` chip 的跨段跳转。
 *  8. `DecisionLogSection` —— `thread_id` 决定跳转入口的有无 / 缺键渲染「—」/ ⭐ `answer` 键被渲染 /
 *     `deferred_ideas` 折叠组头。
 *  9. ⭐ `BlueprintAssociationsSection` 零关联端点调用（两个 mock 的调用次数恒为 0）+ 分组统计 +
 *     `projectId` 为空时不渲染关联项目块。
 * 10. P-4 的段内半边 —— 空数据时各段仍渲染自己的内容区（空态卡），⛔ 不整段消失。
 *
 * 测试范式照 `components/prompts/__tests__/PromptVersionDiff.test.ts` 与
 * `pages/knowledge/__tests__/entity-detail.spec.ts`（手写最小 i18n 键树，⛔ 不 import `zh-CN.json`）。
 * ⭐ 任何可能间接渲染时序图的组件一律 stub 掉图表组件（否则要连带装它的模态插件）。
 */

import type {
  BlueprintApiContract,
  BlueprintCurrentStateAnalysis,
  BlueprintImpactAnalysis,
  BlueprintInteractionFlow,
  BlueprintRepoAssociation,
} from '~/types/blueprint'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import ApiContractCard from '~/components/blueprint/ApiContractCard.vue'
import BlueprintAssociationsSection from '~/components/blueprint/BlueprintAssociationsSection.vue'
import ImpactMatrixTable from '~/components/blueprint/ImpactMatrixTable.vue'
import ApiContractsSection from '~/components/blueprint/sections/ApiContractsSection.vue'
import CurrentStateSection from '~/components/blueprint/sections/CurrentStateSection.vue'
import DecisionLogSection from '~/components/blueprint/sections/DecisionLogSection.vue'
import ImpactAnalysisSection from '~/components/blueprint/sections/ImpactAnalysisSection.vue'
import ImplementationOverviewSection from '~/components/blueprint/sections/ImplementationOverviewSection.vue'
import InteractionFlowsSection from '~/components/blueprint/sections/InteractionFlowsSection.vue'
import RepoAssociationsSection from '~/components/blueprint/sections/RepoAssociationsSection.vue'
import RequirementSpecSection from '~/components/blueprint/sections/RequirementSpecSection.vue'

// ⭐ 关联段必须零调用这两个端点（P-5）：mock 出来只为断言「一次都没被调」。
vi.mock('~/api', () => ({
  knowledgeApi: {
    // 116-04 起 `getRelated` 是真实调用面（入参逐字断言）⇒ 必须 resolve 出数组，
    // 否则 TanStack Query 会把 undefined 当非法返回值。
    getRelated: vi.fn(async () => []),
    getArtifactAssociations: vi.fn(),
  },
  getRelated: vi.fn(),
  getArtifactAssociations: vi.fn(),
}))

const knowledgeApiMock = await import('~/api')

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      projects: { workbench: { deps: { projectsTitle: '关联项目' } } },
      knowledge: {
        relation: { REFERENCES: '引用文档' },
        entity: { associations: { capabilities: '关联能力' } },
        blueprints: {
          sectionEmpty: '本方案未涉及{name}',
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
            goal: '目标',
            background: '背景',
            currentStateSummary: '现状综述',
            deferredIdeas: '本方案明确不做的事（{n}）',
          },
          spec: {
            intentGreenfield: '净新增',
            intentBrownfield: '存量改造',
            intentFix: '缺陷修复',
            acceptanceCriteria: '验收要点',
            acceptanceRest: '还有 {n} 条验收要点',
            gotoFeaturePoint: '点击跳到需求规格里的该功能点',
          },
          state: {
            kindCapability: '能力',
            kindGap: '缺口',
            kindRisk: '风险',
            kindConvention: '约定',
            missingCitations: '缺引用',
          },
          impl: {
            changeTypeCreate: '新建',
            changeTypeModify: '改动',
            changeTypeRemove: '删除',
            changeTypeIndirectRefine: '间接完善',
            existingIntegration: '与既有功能如何配合',
            testStrategy: '测试策略',
            how: '怎么做',
            filesTouched: '涉及文件（{n}）',
            filesTouchedRepo: '仓库 {repo} 内的相对路径',
            repoLabel: '仓库',
            modulesTitle: '功能模块',
            modulesTotal: '共 {n} 个',
            itemsTitle: '实现项',
            itemsTotal: '共 {n} 项',
            itemsFiltered: '显示 {n} / {total} 项',
            itemCount: '{n} 项实现',
            coveredFeaturePoints: '覆盖功能点',
            moduleItemsToggle: '展开本模块的 {n} 项实现',
            deliversFeaturePoint: '兑现功能点',
            dependsOn: '依赖',
            waveShort: 'wave {n}',
            waveAll: '全部',
            waveCount: 'wave {n} · {c} 项',
          },
          decision: { gotoThread: '查看对应线程' },
          associations: {
            citedByThis: '本蓝图引用了',
            relatedProject: '关联项目',
            referencedBy: '被哪些方案 / 知识引用',
            referencedByEmpty: '暂时没有其它方案或知识引用本蓝图',
            relatedKnowledge: '关联知识',
            relatedKnowledgeEmpty: '暂无已入图的关联知识',
          },
          repo: {
            role: '关联角色',
            roleDirect: '直接改动',
            roleIndirect: '间接影响',
            fitness: '适配判定',
            fitnessSuitable: '适配',
            fitnessPartial: '部分适配',
            fitnessUnsuitable: '不适配',
            fitnessReasons: '判定依据',
            routing: '路由依据',
            responsibility: '本仓职责',
            plannedChange: '计划改动',
            supportNeeded: '需要的支撑',
            openRepository: '打开仓库',
            decidedByHuman: '人工确认',
            decidedByAi: 'AI 判定',
            empty: '本方案未关联任何仓库',
            rationale: '选仓理由',
            capabilitiesUsed: '会被用到的能力',
            crossTeam: '跨组协作',
            confirmedAtGate: '已在确认门锁定',
            notConfirmedAtGate: '未经确认门锁定',
          },
          api: {
            directionProvided: '对外提供',
            directionConsumed: '对外依赖',
            availabilityExisting: '已有能力',
            availabilityNeedsSupport: '需要对方支撑',
            request: '请求示例',
            response: '响应示例',
            dataSource: '数据来源',
            dataSourceFrom: '来自 {name}',
            fieldsNeeded: '所需字段',
            consumers: '消费方',
            availabilityUnknown: '未标注',
            empty: '本方案未涉及接口契约',
          },
          impact: {
            kind: '影响类型',
            kindBehaviorChange: '行为变更',
            kindPerf: '性能',
            kindCompat: '兼容性',
            kindData: '数据',
            kindNone: '无影响',
            level: '回归范围',
            levelFull: '全量回归',
            levelSmoke: '冒烟回归',
            levelNone: '无需回归',
            feature: '受影响功能',
            businessImpact: '业务影响',
            compatRisks: '兼容风险',
            dataMigration: '数据迁移',
            rollback: '回滚方案',
            irreversible: '不可逆',
            empty: '本方案未评估影响范围',
          },
          flow: {
            trigger: '触发条件',
            actor: '参与方',
            seq: '序号',
            action: '动作',
            component: '落点',
            dataIn: '输入',
            dataOut: '输出',
            note: '说明',
            alternativePaths: '备选路径',
            actorUser: '用户',
            actorFrontend: '前端',
            actorBackend: '后端',
            actorService: '服务',
            empty: '本方案未描述交互流程',
          },
          mustHaves: { colPath: '路径', colProvides: '提供能力' },
          block: { expandAll: '展开全部', collapse: '收起' },
          citation: { open: '查看引用来源', empty: '本方案没有登记引用', sourceRepoFile: '仓库文件', sourceKnowledgeEntity: '知识条目' },
          annotation: { sidebarToggleEmpty: '批注' },
          quality: { noData: '暂无数据' },
          tabPanel: { filterRepository: '涉及仓库' },
        },
      },
    },
  },
})

/** ⭐ 把块序列 stub 掉：段组件若自己长出第二套划线逻辑，就会在 `html()` 里露出来。 */
const BlockListStub = {
  name: 'BlueprintBlockList',
  props: ['blocks', 'sectionPath', 'threads', 'citations', 'readonly', 'activeThreadId', 'showClosed', 'loading', 'plainMermaid', 'skeletonRows'],
  template: '<div data-testid="block-list-stub" />',
}

const STUBS = {
  BlueprintBlockList: BlockListStub,
  MermaidDiagram: true,
  RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
  // 折叠区默认收起时 reka-ui 不挂载内容 ⇒ 拍平成直通 div，才能断言折叠里交出去的块序列
  // （沿用 115-04 对 Portal 类组件的同款做法）。
  Collapsible: { template: '<div><slot /></div>' },
  CollapsibleTrigger: { template: '<button type="button"><slot /></button>' },
  CollapsibleContent: { template: '<div><slot /></div>' },
}

// 九个段/卡的 props 形状各不相同，这里只做统一装配；逐段的类型正确性由 `pnpm type-check`
// 在组件与页面侧保证，测试内不重复一遍类型体操。
function mountWith(component: any, props: Record<string, unknown>) {
  // 关联段自 116-04 起用 TanStack Query 发反查请求 ⇒ 必须有 queryClient；
  // 每次 mount 一个全新实例，避免用例间共享缓存（retry 关掉，失败不重试拖慢用例）。
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(component, {
    props,
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]], stubs: STUBS },
  })
}

const BLOCK = { block_id: 'b1', type: 'paragraph' as const, text: '一段正文' }

const BLOCK_CTX = {
  threads: [],
  citations: {},
  readonly: false,
  activeThreadId: null,
  showClosed: false,
}

function makeAssociation(overrides: Partial<BlueprintRepoAssociation> = {}): BlueprintRepoAssociation {
  return {
    repository_id: 'repo-1',
    repository_name: 'onion-practice',
    role: 'direct',
    responsibility: [BLOCK],
    rationale: { text: [BLOCK] },
    fitness: { verdict: 'suitable', reasons: [BLOCK] },
    planned_change_summary: [BLOCK],
    ...overrides,
  }
}

function makeAnalysis(): BlueprintCurrentStateAnalysis[] {
  return [
    {
      repository_id: 'repo-1',
      summary: [BLOCK],
      findings: [
        { id: 'cs_1', kind: 'gap', topic: '缺口', text: [BLOCK], citations: [], related_feature_points: ['fp_1'] },
        { id: 'cs_2', kind: 'capability', topic: '能力', text: [BLOCK], citations: ['c1'] },
      ],
    },
  ]
}

function makeContract(overrides: Partial<BlueprintApiContract> = {}): BlueprintApiContract {
  return {
    id: 'api_1',
    name: '生成习题',
    kind: 'http',
    direction: 'consumed',
    method: 'POST',
    path: '/api/practice/generate',
    description: [BLOCK],
    ...overrides,
  }
}

function makeImpact(overrides: Partial<BlueprintImpactAnalysis> = {}): BlueprintImpactAnalysis {
  return {
    business_impact: [BLOCK],
    affected_features: [{ feature: '习题列表', kind: 'behavior_change', repository_ids: ['repo-1'], description: [BLOCK] }],
    ...overrides,
  }
}

function makeFlow(overrides: Partial<BlueprintInteractionFlow> = {}): BlueprintInteractionFlow {
  return {
    id: 'flow_1',
    name: '生成习题',
    trigger: '用户点击生成',
    steps: [{ seq: 1, actor: 'frontend', action: '提交表单', api_ref: 'api_1' }],
    ...overrides,
  }
}

/** 七个走块序列的段：一次装配好，供 1 / 2 两条断言复用。 */
function mountAllBlockSections() {
  return [
    ['requirement_spec', mountWith(RequirementSpecSection, {
      spec: { goal: [BLOCK], feature_points: [{ id: 'fp_1', title: '功能点一', intent: 'greenfield', description: [BLOCK] }] },
      ...BLOCK_CTX,
    })],
    ['repo_associations', mountWith(RepoAssociationsSection, { associations: [makeAssociation()], ...BLOCK_CTX })],
    ['current_state_analysis', mountWith(CurrentStateSection, { analysis: makeAnalysis(), ...BLOCK_CTX })],
    ['implementation_overview', mountWith(ImplementationOverviewSection, {
      overview: {
        requirement_narrative: [BLOCK],
        modules: [{ id: 'mod_1', name: '模块一', feature_point_ids: ['fp_1'], narrative: [BLOCK] }],
        items: [{ id: 'impl_1', feature_point_id: 'fp_1', repository_id: 'repo-1', change_type: 'create', title: '新建服务', how: [BLOCK], wave: 1 }],
      },
      ...BLOCK_CTX,
    })],
    ['api_contracts', mountWith(ApiContractsSection, { contracts: [makeContract()], ...BLOCK_CTX })],
    ['impact_analysis', mountWith(ImpactAnalysisSection, { impact: makeImpact(), ...BLOCK_CTX })],
    ['interaction_flows', mountWith(InteractionFlowsSection, { flows: [makeFlow({ mermaid: 'sequenceDiagram\nA->>B: x' })], ...BLOCK_CTX })],
  ] as Array<[string, ReturnType<typeof mountWith>]>
}

describe('段组件 —— blockCtx 透传与零批注实现', () => {
  it('1. 七个段各自把 Block[] 交给块序列组件，且透传 blockCtx 四键', () => {
    for (const [key, wrapper] of mountAllBlockSections()) {
      const lists = wrapper.findAllComponents(BlockListStub)
      expect(lists.length, `${key} 应至少交出一个块序列`).toBeGreaterThan(0)
      const first = lists[0].props()
      expect(Object.keys(first), key).toEqual(expect.arrayContaining(['threads', 'citations', 'readonly', 'activeThreadId']))
    }
  })

  it('2. ⭐ 段组件零批注：七段的 html 均不含划线标记的 testid', () => {
    for (const [key, wrapper] of mountAllBlockSections())
      expect(wrapper.html(), key).not.toContain('blueprint-annotation-mark')
  })

  it('10. P-4 段内半边：空数据时各段仍渲染自己的内容区（空态卡），⛔ 不整段消失', () => {
    const empties: Array<[string, ReturnType<typeof mountWith>, string]> = [
      ['requirement_spec', mountWith(RequirementSpecSection, { spec: null, ...BLOCK_CTX }), 'blueprint-requirement-spec'],
      ['repo_associations', mountWith(RepoAssociationsSection, { associations: [], ...BLOCK_CTX }), 'blueprint-repo-associations'],
      ['current_state_analysis', mountWith(CurrentStateSection, { analysis: [], ...BLOCK_CTX }), 'blueprint-current-state'],
      ['implementation_overview', mountWith(ImplementationOverviewSection, { overview: null, ...BLOCK_CTX }), 'blueprint-implementation-overview'],
      ['api_contracts', mountWith(ApiContractsSection, { contracts: [], ...BLOCK_CTX }), 'blueprint-api-contracts'],
      ['impact_analysis', mountWith(ImpactAnalysisSection, { impact: null, ...BLOCK_CTX }), 'blueprint-impact-analysis'],
      ['interaction_flows', mountWith(InteractionFlowsSection, { flows: [], ...BLOCK_CTX }), 'blueprint-interaction-flows'],
      ['decision_log', mountWith(DecisionLogSection, { decisionLog: [], deferredIdeas: [] }), 'blueprint-decision-log'],
      ['associations', mountWith(BlueprintAssociationsSection, { artifactId: 'a1', citations: {}, projectId: null }), 'blueprint-associations'],
    ]
    for (const [key, wrapper, testid] of empties) {
      expect(wrapper.find(`[data-testid="${testid}"]`).exists(), `${key} 的内容区必须渲染`).toBe(true)
      expect(wrapper.text(), key).not.toBe('')
    }
  })
})

describe('repoAssociationCard —— UI-SPEC §6.3', () => {
  it('3a. role 两档徽标文案不同（双色，⛔ 无第三色）', () => {
    const direct = mountWith(RepoAssociationsSection, { associations: [makeAssociation({ role: 'direct' })], ...BLOCK_CTX })
    const indirect = mountWith(RepoAssociationsSection, { associations: [makeAssociation({ role: 'indirect' })], ...BLOCK_CTX })

    expect(direct.text()).toContain('直接改动')
    expect(direct.text()).not.toContain('间接影响')
    expect(indirect.text()).toContain('间接影响')
    expect(indirect.text()).not.toContain('直接改动')
  })

  it('3b. fitness unsuitable ⇒ 不适配徽标，reasons 原样交给块序列（⛔ 不做解析）', () => {
    const wrapper = mountWith(RepoAssociationsSection, {
      associations: [makeAssociation({ fitness: { verdict: 'unsuitable', reasons: [BLOCK] } })],
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-verdict="unsuitable"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('不适配')
    const reasonList = wrapper.findAllComponents(BlockListStub).find(list => String(list.props('sectionPath')).endsWith('fitness.reasons'))
    expect(reasonList?.props('blocks')).toEqual([BLOCK])
  })

  it('3c. ⭐ SC-3：卡内 RouterLink 指向 /repositories/{repository_id}', () => {
    const wrapper = mountWith(RepoAssociationsSection, { associations: [makeAssociation()], ...BLOCK_CTX })

    expect(wrapper.find('[data-testid="blueprint-repo-open"]').attributes('href')).toBe('/repositories/repo-1')
  })

  it('3d. cross_team === true ⇒ 跨组徽标；缺键 ⇒ 不出现（正反并列）', () => {
    const crossed = mountWith(RepoAssociationsSection, {
      associations: [makeAssociation({ routing_evidence: { score: 0.833, confidence: 'high', cross_team: true } })],
      ...BLOCK_CTX,
    })
    const plain = mountWith(RepoAssociationsSection, {
      associations: [makeAssociation({ routing_evidence: { score: 0.833, confidence: 'high' } })],
      ...BLOCK_CTX,
    })

    expect(crossed.find('[data-cross-team="true"]').exists()).toBe(true)
    expect(crossed.find('[data-testid="blueprint-repo-routing-score"]').text()).toBe('0.83')
    expect(plain.find('[data-cross-team="true"]').exists()).toBe(false)
  })

  it('3e. confirmed_at_gate 三态：false / true / 缺键各自不同', () => {
    const notLocked = mountWith(RepoAssociationsSection, { associations: [makeAssociation({ confirmed_at_gate: false })], ...BLOCK_CTX })
    const locked = mountWith(RepoAssociationsSection, { associations: [makeAssociation({ confirmed_at_gate: true })], ...BLOCK_CTX })
    const missing = mountWith(RepoAssociationsSection, { associations: [makeAssociation()], ...BLOCK_CTX })

    expect(notLocked.find('[data-confirmed-at-gate="false"]').exists()).toBe(true)
    expect(locked.find('[data-confirmed-at-gate="true"]').exists()).toBe(true)
    expect(missing.find('[data-confirmed-at-gate="true"]').exists()).toBe(false)
    expect(missing.find('[data-confirmed-at-gate="false"]').exists()).toBe(false)
  })

  it('3f. indirect 专属的能力清单缺键渲染「—」且不含 undefined', () => {
    const wrapper = mountWith(RepoAssociationsSection, {
      associations: [makeAssociation({ role: 'indirect', capabilities_used: [{}] })],
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-testid="blueprint-repo-capability"]').text()).toContain('—')
    expect(wrapper.text()).not.toContain('undefined')
  })
})

describe('currentStateSection —— UI-SPEC §6.4', () => {
  it('4a. finding 的 citations 为空 ⇒ 出现缺引用的质量信号徽标', () => {
    const wrapper = mountWith(CurrentStateSection, { analysis: makeAnalysis(), ...BLOCK_CTX })

    const flagged = wrapper.findAll('[data-missing-citations="true"]')
    expect(flagged).toHaveLength(1)
  })

  it('4b. finding 的 citations 非空 ⇒ 该条不出现质量信号徽标（负向对照）', () => {
    const wrapper = mountWith(CurrentStateSection, {
      analysis: [{ repository_id: 'repo-1', findings: [{ id: 'cs_2', kind: 'capability', text: [BLOCK], citations: ['c1'] }] }],
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-missing-citations="true"]').exists()).toBe(false)
  })

  it('4c. 点 related_feature_points chip ⇒ emit goto-anchor 载荷 fp-<id>', async () => {
    const wrapper = mountWith(CurrentStateSection, { analysis: makeAnalysis(), ...BLOCK_CTX })

    await wrapper.find('[data-testid="blueprint-feature-point-chip"]').trigger('click')

    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual(['fp-fp_1'])
  })
})

describe('apiContractCard —— ⭐ availability 的读取位置（113-05 决策）', () => {
  it('5a. data_source.availability = needs_support ⇒ warning 徽标 + 支持仓可点', () => {
    const wrapper = mountWith(ApiContractCard, {
      contract: makeContract({ data_source: { availability: 'needs_support', support_repository_id: 'repo-2', from_service: 'user-svc' } }),
      supportRepoName: '用户中心',
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-availability="needs_support"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('需要对方支撑')
    expect(wrapper.find('[data-testid="blueprint-api-support-repo"]').attributes('href')).toBe('/repositories/repo-2')
  })

  it('5b. ⭐ 顶层有 availability 而 data_source 内没有 ⇒ 渲染「未标注」（⛔ 不回落读顶层）', () => {
    const contract = { ...makeContract({ data_source: { from_service: 'user-svc' } }), availability: 'existing', support_repository_id: 'repo-9' }
    const wrapper = mountWith(ApiContractCard, { contract, ...BLOCK_CTX })

    expect(wrapper.find('[data-availability="unknown"]').exists()).toBe(true)
    expect(wrapper.find('[data-availability="existing"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="blueprint-api-support-repo"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('未标注')
  })

  it('5c. data_source.availability = existing ⇒ success 徽标（正向对照）', () => {
    const wrapper = mountWith(ApiContractCard, {
      contract: makeContract({ data_source: { availability: 'existing' } }),
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-availability="existing"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('已有能力')
  })
})

describe('impactMatrixTable —— UI-SPEC §6.7', () => {
  it('6a. reversible === false ⇒ 出现不可逆徽标', () => {
    const wrapper = mountWith(ImpactMatrixTable, {
      impact: makeImpact({ data_migrations: [{ description: '习题表加列', reversible: false }] }),
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-irreversible="true"]').exists()).toBe(true)
  })

  it('6b. reversible 缺键 ⇒ 不出现该徽标（⭐ 严格判等，⛔ 不用真值判断）', () => {
    const wrapper = mountWith(ImpactMatrixTable, {
      impact: makeImpact({ data_migrations: [{ description: '习题表加列' }] }),
      ...BLOCK_CTX,
    })

    expect(wrapper.find('[data-testid="blueprint-data-migration"]').exists()).toBe(true)
    expect(wrapper.find('[data-irreversible="true"]').exists()).toBe(false)
  })

  it('6c. 窄屏降级是卡片堆叠而不是横向滚动表（双份结构同时存在于 DOM）', () => {
    const wrapper = mountWith(ImpactMatrixTable, { impact: makeImpact(), ...BLOCK_CTX })

    expect(wrapper.find('[data-testid="blueprint-impact-cards"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="blueprint-impact-row"]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid="blueprint-impact-card"]')).toHaveLength(1)
  })
})

describe('interactionFlowsSection —— UI-SPEC §6.8', () => {
  it('7a. mermaid 为空 ⇒ 交出的块序列里没有 mermaid 型块', () => {
    const wrapper = mountWith(InteractionFlowsSection, { flows: [makeFlow()], ...BLOCK_CTX })

    const blocks = wrapper.findAllComponents(BlockListStub).flatMap(list => (list.props('blocks') ?? []) as Array<{ type: string }>)
    expect(blocks.some(block => block.type === 'mermaid')).toBe(false)
  })

  it('7b. mermaid 非空 ⇒ 合成块交给块序列，且 threads 恒为空（后端不会往合成块挂线程）', () => {
    const wrapper = mountWith(InteractionFlowsSection, {
      flows: [makeFlow({ mermaid: 'sequenceDiagram\nA->>B: x' })],
      threads: [{ thread_id: 't1' }],
      citations: {},
      readonly: false,
      activeThreadId: null,
      showClosed: false,
    })

    const diagram = wrapper.findAllComponents(BlockListStub).find(list => ((list.props('blocks') ?? []) as Array<{ type: string }>).some(block => block.type === 'mermaid'))
    expect(diagram).toBeTruthy()
    expect((diagram!.props('blocks') as Array<{ block_id: string }>)[0].block_id).toBe('flow-flow_1-mermaid')
    expect(diagram!.props('threads')).toEqual([])
  })

  it('7c. 点 api_ref chip ⇒ emit goto-anchor 载荷 api-<契约 id>', async () => {
    const wrapper = mountWith(InteractionFlowsSection, { flows: [makeFlow()], ...BLOCK_CTX })

    await wrapper.find('[data-testid="blueprint-api-ref-chip"]').trigger('click')

    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual(['api-api_1'])
  })
})

describe('decisionLogSection —— P-14 零约束裸 array', () => {
  it('8a. 条目带 thread_id ⇒ 出现跳转入口并 emit open-thread', async () => {
    const wrapper = mountWith(DecisionLogSection, {
      decisionLog: [{ thread_id: 'th_1', question: '要不要加缓存', answer: '先不加', decision: 'accepted' }],
      deferredIdeas: [],
    })

    const button = wrapper.find('[data-testid="blueprint-decision-goto-thread"]')
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    expect(wrapper.emitted('open-thread')?.[0]).toEqual(['th_1'])
  })

  it('8b. 条目不带 thread_id ⇒ 不渲染跳转入口（⛔ 不留点了没反应的按钮）', () => {
    const wrapper = mountWith(DecisionLogSection, {
      decisionLog: [{ question: '要不要加缓存', answer: '先不加' }],
      deferredIdeas: [],
    })

    expect(wrapper.find('[data-testid="blueprint-decision-goto-thread"]').exists()).toBe(false)
  })

  it('8c. ⭐ answer 键被渲染；缺键条目渲染「—」且文本不含 undefined、不抛', () => {
    const wrapper = mountWith(DecisionLogSection, {
      decisionLog: [{ answer: '这条答案必须出现' }, {}],
      deferredIdeas: [],
    })

    expect(wrapper.text()).toContain('这条答案必须出现')
    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).not.toContain('undefined')
    expect(wrapper.findAll('[data-testid="blueprint-decision-entry"]')).toHaveLength(2)
  })

  it('8d. deferredIdeas 非空 ⇒ 折叠组头带条数；为空 ⇒ 整块不渲染（正反并列）', () => {
    const withIdeas = mountWith(DecisionLogSection, { decisionLog: [], deferredIdeas: ['先不做多租户', { text: '先不做导出' }] })
    const without = mountWith(DecisionLogSection, { decisionLog: [{ question: 'q' }], deferredIdeas: [] })

    expect(withIdeas.find('[data-testid="blueprint-deferred-ideas"]').exists()).toBe(true)
    expect(withIdeas.find('[data-testid="blueprint-deferred-ideas"]').text()).toContain('2')
    expect(without.find('[data-testid="blueprint-deferred-ideas"]').exists()).toBe(false)
  })

  it('8e. 非法 decided_at 原样显示而不是抛或渲染成空', () => {
    const wrapper = mountWith(DecisionLogSection, {
      decisionLog: [{ question: 'q', decided_at: 'not-a-date' }],
      deferredIdeas: [],
    })

    expect(wrapper.find('[data-field="decided-at"]').text()).toBe('not-a-date')
  })
})

describe('blueprintAssociationsSection —— ⭐ SC-4 反查（116-04 交付）', () => {
  it('9a-1. ⭐ getRelated 被真实调用：in/out 两块的入参逐字（relations + maxHops: 1）', () => {
    vi.mocked(knowledgeApiMock.knowledgeApi.getRelated).mockClear()
    mountWith(BlueprintAssociationsSection, {
      artifactId: 'artifact-1',
      citations: { c1: { citation_id: 'c1', source_type: 'repo_file' } },
      projectId: 'proj-1',
      projectName: '洋葱练习',
      knowledgeEntityId: 'entity-1',
    })

    const calls = vi.mocked(knowledgeApiMock.knowledgeApi.getRelated).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls).toContainEqual(['entity-1', {
      direction: 'in',
      relations: ['REFERENCES'],
      maxHops: 1,
    }])
    expect(calls).toContainEqual(['entity-1', {
      direction: 'out',
      relations: ['REFERENCES'],
      maxHops: 1,
    }])
  })

  it('9a-2. ⭐ getArtifactAssociations 仍恒为 0：它查 initiatives.Artifact 投影，对 delivery.Artifact id 依然必然落空（116 改走 getRelated，不是把它修好了）', () => {
    mountWith(BlueprintAssociationsSection, {
      artifactId: 'artifact-1',
      citations: { c1: { citation_id: 'c1', source_type: 'repo_file' } },
      projectId: 'proj-1',
      projectName: '洋葱练习',
      knowledgeEntityId: 'entity-1',
    })

    expect(knowledgeApiMock.knowledgeApi.getArtifactAssociations).toHaveBeenCalledTimes(0)
  })

  it('9a-3. knowledgeEntityId 为空 ⇒ 两块都不发请求（证明 enabled 不是摆设）', () => {
    vi.mocked(knowledgeApiMock.knowledgeApi.getRelated).mockClear()
    mountWith(BlueprintAssociationsSection, {
      artifactId: 'artifact-1',
      citations: { c1: { citation_id: 'c1', source_type: 'repo_file' } },
      projectId: 'proj-1',
      knowledgeEntityId: null,
    })

    expect(knowledgeApiMock.knowledgeApi.getRelated).toHaveBeenCalledTimes(0)
  })

  it('9b. 引用池按 source_type 分组统计正确', () => {
    const wrapper = mountWith(BlueprintAssociationsSection, {
      artifactId: 'artifact-1',
      citations: {
        c1: { citation_id: 'c1', source_type: 'repo_file' },
        c2: { citation_id: 'c2', source_type: 'repo_file' },
        c3: { citation_id: 'c3', source_type: 'knowledge_entity' },
      },
      projectId: null,
    })

    const groups = wrapper.findAll('[data-testid="blueprint-associations-group"]')
    expect(groups).toHaveLength(2)
    expect(wrapper.find('[data-source-type="repo_file"]').text()).toContain('2')
    expect(wrapper.find('[data-source-type="knowledge_entity"]').text()).toContain('1')
  })

  it('9c. projectId 为空 ⇒ 关联项目块不渲染；非空 ⇒ 渲染站内跳转（正反并列）', () => {
    const without = mountWith(BlueprintAssociationsSection, { artifactId: 'a1', citations: { c1: { citation_id: 'c1', source_type: 'url' } }, projectId: null })
    const withProject = mountWith(BlueprintAssociationsSection, { artifactId: 'a1', citations: {}, projectId: 'proj-1', projectName: '洋葱练习' })

    expect(without.find('[data-testid="blueprint-associations-project"]').exists()).toBe(false)
    expect(withProject.find('[data-testid="blueprint-associations-project-link"]').attributes('href')).toBe('/projects/proj-1')
    expect(withProject.text()).toContain('洋葱练习')
  })
})

describe('实现概述 —— ⭐ 功能点 ← 模块 → 实现项 三层连通（quick-260806-fpx）', () => {
  const FEATURE_POINTS = {
    fp_1: {
      id: 'fp_1',
      title: '入口与课程包权益鉴权',
      intent: 'brownfield' as const,
      acceptance_criteria: ['无权益不渲染入口', '置灰态不展示购买引导'],
    },
    fp_2: { id: 'fp_2', title: '题型图谱页', intent: 'greenfield' as const },
  }

  function makeOverview() {
    return {
      requirement_narrative: [BLOCK],
      modules: [{
        id: 'mod_1',
        name: '入口与课程包权益鉴权',
        feature_point_ids: ['fp_1', 'fp_2'],
        repository_ids: ['repo-1'],
        narrative: [BLOCK],
      }],
      items: [
        {
          id: 'impl_1',
          feature_point_id: 'fp_1',
          module_id: 'mod_1',
          repository_id: 'repo-1',
          change_type: 'modify' as const,
          title: '改造 SpecialCard 入口',
          wave: 1,
          depends_on: ['impl_2'],
          how: [BLOCK],
        },
        {
          id: 'impl_2',
          feature_point_id: 'fp_2',
          module_id: 'mod_1',
          repository_id: 'repo-1',
          change_type: 'create' as const,
          title: '新建题型图谱页',
          wave: 2,
          how: [BLOCK],
        },
      ],
    }
  }

  function mountOverview(props: Record<string, unknown> = {}) {
    return mountWith(ImplementationOverviewSection, {
      overview: makeOverview(),
      featurePoints: FEATURE_POINTS,
      repoNames: { 'repo-1': 'onion-learning' },
      ...BLOCK_CTX,
      ...props,
    })
  }

  it('11a. 模块卡挂 mod-<id> 锚点，实现项卡的模块 chip 跳得回来', async () => {
    const wrapper = mountOverview()

    expect(wrapper.find('#mod-mod_1').exists()).toBe(true)
    await wrapper.find('[data-testid="blueprint-impl-module-link"]').trigger('click')
    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual(['mod-mod_1'])
  })

  it('11b. ⭐ 实现项卡渲染 feature_point_id（schema 必填项，整改前从未渲染）且带标题', async () => {
    const wrapper = mountOverview()
    const chip = wrapper.find('#impl-impl_1 [data-testid="blueprint-feature-point-chip"]')

    expect(chip.exists()).toBe(true)
    // 索引命中 ⇒ 出标题而不只是一个 fp_1
    expect(chip.text()).toContain('入口与课程包权益鉴权')
    await chip.trigger('click')
    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual(['fp-fp_1'])
  })

  it('11c. 功能点索引缺项 ⇒ chip 降级成只有 id，⛔ 不消失（悄悄少一个更难排查）', () => {
    const wrapper = mountOverview({ featurePoints: {} })
    const chip = wrapper.find('#impl-impl_1 [data-testid="blueprint-feature-point-chip"]')

    expect(chip.exists()).toBe(true)
    expect(chip.text()).toContain('fp_1')
    expect(wrapper.find('[data-testid="blueprint-feature-point-preview"]').exists()).toBe(false)
  })

  it('11d. 模块卡列出本模块的实现项，点一条跳 impl-<id>', async () => {
    const wrapper = mountOverview()
    const links = wrapper.findAll('[data-testid="blueprint-module-item-link"]')

    expect(links).toHaveLength(2)
    await links[1].trigger('click')
    expect(wrapper.emitted('goto-anchor')?.[0]).toEqual(['impl-impl_2'])
  })

  it('11e. ⭐ T-fpx-01 波次筛选把目标筛掉时，跳转前自动清筛选（否则滚向不存在的锚点，静默失败）', async () => {
    const wrapper = mountOverview()

    await wrapper.find('[data-testid="blueprint-wave-chip"][data-wave="1"]').trigger('click')
    expect(wrapper.find('#impl-impl_2').exists()).toBe(false)

    const link = wrapper
      .findAll('[data-testid="blueprint-module-item-link"]')
      .find(node => node.attributes('data-impl-id') === 'impl_2')!
    await link.trigger('click')

    expect(wrapper.emitted('goto-anchor')?.at(-1)).toEqual(['impl-impl_2'])
    expect(wrapper.find('#impl-impl_2').exists()).toBe(true)
  })

  it('11f. depends_on chip 跳 impl-<dep>，同样走筛选自解', async () => {
    const wrapper = mountOverview()

    await wrapper.find('[data-testid="blueprint-wave-chip"][data-wave="1"]').trigger('click')
    await wrapper.find('#impl-impl_1 [data-testid="blueprint-impl-depends-on"]').trigger('click')

    expect(wrapper.emitted('goto-anchor')?.at(-1)).toEqual(['impl-impl_2'])
    expect(wrapper.find('#impl-impl_2').exists()).toBe(true)
  })

  it('11g. 「全部」是显式复位入口，⛔ 复位不只藏在「再点一次当前波次」这个不可见约定里', async () => {
    const wrapper = mountOverview()

    await wrapper.find('[data-testid="blueprint-wave-chip"][data-wave="2"]').trigger('click')
    expect(wrapper.findAll('[data-testid="blueprint-impl-item"]')).toHaveLength(1)

    await wrapper.find('[data-testid="blueprint-wave-chip-all"]').trigger('click')
    expect(wrapper.findAll('[data-testid="blueprint-impl-item"]')).toHaveLength(2)
  })

  it('11h. ⭐ 仓库归属显式可见：元信息带「仓库」字样，涉及文件标注仓内相对路径，动作徽标中文', () => {
    const overview = makeOverview()
    const withFiles = {
      ...overview.items[0],
      files_touched: [{ path: 'apps/learn-textbook-sync/src/x.ts', action: 'edit' }],
    }
    const wrapper = mountOverview({ overview: { ...overview, items: [withFiles, overview.items[1]] } })

    const repoChip = wrapper.find('#impl-impl_1 [data-testid="blueprint-impl-repo"]')
    expect(repoChip.exists()).toBe(true)
    expect(repoChip.text()).toContain('仓库')
    expect(repoChip.text()).toContain('onion-learning')

    const filesRepo = wrapper.find('#impl-impl_1 [data-testid="blueprint-impl-files-repo"]')
    expect(filesRepo.exists()).toBe(true)
    expect(filesRepo.text()).toContain('onion-learning')

    // 动作徽标中文化：LLM 吐的同义 token（edit）归一成「改动」
    const fileRow = wrapper.find('#impl-impl_1 [data-testid="blueprint-impl-file"]')
    expect(fileRow.text()).toContain('改动')
    expect(fileRow.text()).not.toContain('edit')
  })
})
