/**
 * 蓝图查看器（`/knowledge/blueprints/:id`）的 e2e 载荷 builder。
 *
 * 🔴 形状出处逐条对账，⛔ 不从「前端能跑通」倒推：
 * - 正文 / 事件 / 线程三个端点的响应键：`.planning/milestones/v0.20.0-phases/115-ui/115-01-SUMMARY.md` §1 契约表；
 * - `content` 顶层 14 键（`required` 11 键）：`~/types/blueprint` 的 `BlueprintV1`，
 *   它又逐字对齐 `server/services/process_runtime/blueprint_schema.py`；
 * - 人审快照：`server/delivery/api/blueprint_review_views.py`（`BlueprintReviewSnapshot`）。
 *
 * ⚠️ `quality` 后三项刻意保持 `null`（无数据源）而不是 `0` —— 115-01-SUMMARY §3 的
 * 「`null` ≠ `0`」纪律，fixture 归一成 0 会让「无数据档」的渲染分支永不被走到。
 */

/** 固定 artifact id（UUID：范围闸与 `?version_id=` 都按 UUID 校验）。 */
export const BLUEPRINT_ARTIFACT_ID = '2f4a1c88-0d3e-4b71-9a52-6c8f1e7b0d44'
export const BLUEPRINT_VERSION_ID = '9b1d7e02-5f43-4c86-a10b-3e7d92f5c618'

/** 十个段 key，与 `pages/knowledge/blueprints/[id].vue` 的 `SECTION_KEYS` 逐字同序。 */
export const BLUEPRINT_SECTION_IDS = [
  'requirement_spec',
  'repo_associations',
  'current_state_analysis',
  'implementation_overview',
  'api_contracts',
  'impact_analysis',
  'interaction_flows',
  'must_haves',
  'decision_log',
  'associations',
] as const

/**
 * 一段合法的 mermaid 流程图源码。
 *
 * ⭐ 刻意用 `graph TD` 而不是 `sequenceDiagram`：`MermaidDiagram.vue` 的 `initialize`
 * 只给 `flowchart` 传了配置，流程图是该组件实际被用到的形态（UAT 原文也写「流程图」）。
 */
export const MERMAID_FLOW_SOURCE = [
  'graph TD',
  '  A[用户提交订单] --> B{库存充足?}',
  '  B -->|是| C[锁定库存]',
  '  B -->|否| D[进入缺货队列]',
  '  C --> E[生成履约单]',
].join('\n')

/** 一段**非法**源码：mermaid 解析失败 ⇒ 组件回退展示原文并出「无法渲染流程图」。 */
export const MERMAID_BROKEN_SOURCE = 'graph TD\n  A[[[[ --> ))))'

interface FlowSeed {
  id: string
  name: string
  /** `undefined` / `''` ⇒ `InteractionFlowsSection.mermaidBlocks` 返空数组，整块不合成。 */
  mermaid?: string
}

/**
 * 十段都有内容的正文。
 *
 * ⭐ 每段都必须**真有内容**：段容器虽然无条件渲染，但空段渲染的是 `CompactEmptyState`
 * （高度只有几十像素）⇒ 十段挤在一屏内，`IntersectionObserver` 的
 * `rootMargin: '-15% 0px -55% 0px'` 观察窗会同时命中多段，滚动跟随断言就失去分辨率。
 * 段高由 `paragraphs` 条数撑开，见 `longText()`。
 */
export function blueprintContent(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'blueprint/v1',
    meta: {
      title: '订单履约链路重构',
      project_id: 'b7c1e5a4-3d92-4f08-8e61-2a5c9d0f4b73',
      summary: [block('blk-summary', '把下单到履约的五个环节收敛到一条可观测链路上。')],
    },
    requirement_spec: {
      goal: [block('blk-goal', longText('目标'))],
      background: [block('blk-bg', longText('背景'))],
      feature_points: [
        {
          id: 'fp_1',
          title: '库存锁定改为幂等',
          intent: 'brownfield',
          description: [block('blk-fp1', longText('功能点一'))],
          acceptance_criteria: ['重复提交同一订单只锁一次库存'],
        },
      ],
    },
    repo_associations: [
      {
        repository_id: 'r-in',
        repository_name: 'onion-web',
        role: 'direct',
        rationale: { text: [block('blk-ra1', longText('关联理由'))] },
        responsibility: [block('blk-ra2', longText('承担职责'))],
      },
    ],
    current_state_analysis: [
      {
        repository_id: 'r-in',
        summary: [block('blk-cs0', longText('现状小结'))],
        findings: [
          {
            id: 'find_1',
            kind: 'gap',
            citations: [],
            text: [block('blk-cs1', longText('现状发现'))],
          },
        ],
      },
    ],
    implementation_overview: {
      requirement_narrative: [block('blk-io0', longText('实现概览'))],
      items: [
        {
          id: 'item_1',
          feature_point_id: 'fp_1',
          repository_id: 'r-in',
          change_type: 'modify',
          title: '库存锁定接口加幂等键',
          how: [block('blk-io1', longText('怎么做'))],
        },
      ],
    },
    api_contracts: [
      {
        id: 'api_lock',
        name: '锁定库存',
        kind: 'http',
        direction: 'provided',
        method: 'POST',
        path: '/api/inventory/lock',
        description: [block('blk-api1', longText('接口说明'))],
      },
    ],
    impact_analysis: {
      business_impact: [block('blk-ia0', longText('业务影响'))],
      affected_features: [
        {
          feature: '下单',
          kind: 'behavior_change',
          description: [block('blk-ia1', longText('受影响功能'))],
        },
      ],
    },
    interaction_flows: [flow({ id: 'flow_1', name: '下单履约主流程', mermaid: MERMAID_FLOW_SOURCE })],
    must_haves: {
      truths: Array.from({ length: 6 }, (_, i) => `可观察真相 ${i + 1}：${longText('真相')}`),
      artifacts: [],
      key_links: [],
    },
    decision_log: Array.from({ length: 4 }, (_, i) => ({
      id: `dec_${i + 1}`,
      decision: `决策 ${i + 1}`,
      rationale: longText('决策理由'),
    })),
    // ⭐ 引用池撑起末段（`associations`）的高度。它是十段里的最后一段，段矮就永远进不了
    // `AnchorNavLayout` 那个 15%~45% 的观察窗（滚到底也只能停在页尾），左栏第十项就点不亮。
    // 真实蓝图本就带几十条引用，这里照实给足。
    citations: citationPool(),
    ...overrides,
  }
}

/** 六类来源 × 五条的引用池（键是 `citation_id`，值是 `Citation`——是 object 不是 array）。 */
function citationPool(): Record<string, unknown> {
  const sourceTypes = ['knowledge_entity', 'rag_chunk', 'repo_file', 'blueprint', 'repo_charter', 'work_item']
  const pool: Record<string, unknown> = {}
  for (const [groupIndex, sourceType] of sourceTypes.entries()) {
    for (let i = 0; i < 5; i += 1) {
      const id = `cit_${groupIndex + 1}_${i + 1}`
      pool[id] = {
        citation_id: id,
        source_type: sourceType,
        source_id: `${sourceType}-${i + 1}`,
        title: `${sourceType} 引用条目 ${i + 1}`,
        quote: '被引用的关键原文摘录，用于来源不可达时的兜底快照展示。',
      }
    }
  }
  return pool
}

/** 单个 `interaction_flows` 条目；`mermaid` 缺省即「无源码」那一档。 */
export function flow(seed: FlowSeed) {
  return {
    id: seed.id,
    name: seed.name,
    trigger: '用户点击「提交订单」',
    ...(seed.mermaid === undefined ? {} : { mermaid: seed.mermaid }),
    steps: [
      { seq: 1, actor: 'user', action: '提交订单', component: 'CheckoutPage' },
      { seq: 2, actor: 'backend', action: '锁定库存', component: 'InventoryService', api_ref: 'api_lock' },
    ],
  }
}

/** paragraph 块；`text` 是 string（schema 对它零类型约束，`blockText()` 按字段优先级取）。 */
export function block(blockId: string, text: string) {
  return { block_id: blockId, type: 'paragraph', text }
}

/** 撑开段高用的长文本 —— 让十段在视口里可以逐段滚过去，而不是挤成一屏。 */
function longText(tag: string): string {
  return `${tag}：`
    + '这一段是为了把段落撑到足够高度而写的说明文字，它描述了当前链路里各个环节的职责边界、'
    + '数据流向与失败时的回退方式，以及为什么这次改造选择在服务端而不是网关层收敛幂等语义。'
    + '重复一遍以保证段落高度足以覆盖一屏：这一段是为了把段落撑到足够高度而写的说明文字，'
    + '它描述了当前链路里各个环节的职责边界、数据流向与失败时的回退方式。'
}

/** `GET /api/delivery/artifacts/<uuid>/blueprint/` 的 200 响应（八键）。 */
export function blueprintDocument(overrides: Record<string, unknown> = {}) {
  return {
    version_id: BLUEPRINT_VERSION_ID,
    version_no: 3,
    is_current: true,
    produced_by_ref: 'ai_draft:1',
    created_at: '2026-08-01T02:00:00Z',
    content: blueprintContent(),
    // ⚠️ 后三项保持 null（无数据源），⛔ 不归一成 0 —— 见文件头纪律。
    quality: {
      citation_coverage: 1,
      ai_rejection_rate: null,
      human_edit_volume: null,
      clarification_rounds: null,
    },
    knowledge_entity_id: '',
    ...overrides,
  }
}

/**
 * `GET .../blueprint/events/` 的 200 响应。
 *
 * 默认给「无会话」那一档（三键空结构）—— 115-01-SUMMARY §6 明说它**不是错误态**，
 * 且能让 `useBlueprintLive` 的 `isLive` 保持 false ⇒ ⛔ 不起轮询，e2e 不被定时器搅动。
 */
export function blueprintEvents(overrides: Record<string, unknown> = {}) {
  return { session_id: '', current_stage: '', events: [], ...overrides }
}

/** `GET .../blueprint-review/threads/` 的 200 响应。 */
export function blueprintThreads(threads: unknown[] = []) {
  return { threads }
}

/**
 * `GET .../blueprint-review/` 人审快照。
 *
 * `current_status: 'pending_review'` ⇒ 蓝图**可写**（`isBlueprintEditable`）⇒ 选区浮层
 * 会渲染「发起评论」。改成 `archived` 之类会让 UAT-2 的按钮消失。
 */
export function blueprintSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    artifact_id: BLUEPRINT_ARTIFACT_ID,
    session_id: 's-e2e-1',
    current_status: 'pending_review',
    revision_round: 0,
    findings: {},
    clarifications: [],
    comments: [],
    orphaned_threads: [],
    unresolved: [],
    review_round: 1,
    unresolved_blocker_count: 0,
    ...overrides,
  }
}
