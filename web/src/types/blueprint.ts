/**
 * 技术蓝图（blueprint/v1）的前端类型契约（Phase 115-02）。
 *
 * 字段名与后端**逐字同名**（snake_case，⛔ 不转驼峰）。三处权威来源：
 * - 正文结构：`server/services/process_runtime/blueprint_schema.py` 的 `BLUEPRINT_JSON_SCHEMA`
 *   （顶层 14 键，`required` 11 键）；
 * - 五个只读端点的响应键：`.planning/phases/115-ui/115-01-SUMMARY.md` §1 契约表
 *   （⚠️ 它订正了 UI-SPEC §3.3 两处：列表项状态键是 `current_status`、分页体是五键）；
 * - 人审 / 确认门端点：`server/delivery/api/blueprint_review_views.py`、`blueprint_gate_views.py`。
 *
 * **半可信字段纪律**：蓝图正文是 LLM 合成产物，schema 对多处只声明容器类型而不约束内部形状
 * （`text` / `options` / `payload` / `locator` / `decision_log` / `deferred_ideas` /
 * `execution_plan` / `routing_evidence` / `request_example` 等）。这些一律标成 `unknown`
 * 或裸 `Record`，消费方**必须逐项可选链 + 类型收窄**，⛔ 不得假设运行期形状。
 */

// ── 状态与枚举 ────────────────────────────────────────────────────────────────

/**
 * 蓝图状态（11 个状态机取值 + `''`）。
 *
 * `''` 是 **v0 旧数据**（升级前建的 artifact 未进状态机），是合法输入而非异常：
 * 它在 `~/config/blueprintStatus` 有专档（「旧版方案」），且在可编辑白名单**内**。
 */
export type BlueprintStatus
  = | ''
    | 'researching'
    | 'drafting'
    | 'ai_reviewing'
    | 'needs_clarification'
    | 'pending_review'
    | 'confirmed'
    | 'implementing'
    | 'implemented'
    | 'archived'
    | 'failed'
    | 'superseded'

/** Block 类型（schema `$defs.block.type` 的 enum 五值）。 */
export type BlueprintBlockType = 'paragraph' | 'pseudocode' | 'table' | 'list' | 'mermaid'

/** 引用来源类型（schema `$defs.citation.source_type` 的 enum 九值）。 */
export type CitationSourceType
  = | 'knowledge_entity'
    | 'rag_chunk'
    | 'repo_file'
    | 'artifact_version'
    | 'blueprint'
    | 'repo_charter'
    | 'work_item'
    | 'feishu_doc'
    | 'url'

/** 线程种类（`delivery.models.BlueprintThread.kind`）。 */
export type BlueprintThreadKind
  = | 'ai_clarification'
    | 'ai_review_finding'
    | 'human_comment'
    | 'repo_confirmation'

/** 线程严重级（`''` = 未分级，评论与确认门线程恒为 `''`）。 */
export type BlueprintThreadSeverity = '' | 'blocker' | 'warning' | 'info'

/** 线程处置态（**处置维度**，与 `anchor_status` 的锚定维度正交）。 */
export type BlueprintThreadStatus = 'open' | 'answered' | 'resolved' | 'dismissed'

/** 线程锚定态（**锚定维度**，`orphaned` = 后端判定原文已不存在）。 */
export type BlueprintAnchorStatus = 'anchored' | 'orphaned'

// ── 正文基元 ──────────────────────────────────────────────────────────────────

/**
 * 最小可锚定 / 可编辑内容单元。
 *
 * ⚠️ **`text` 的类型是 `unknown` 而非 `string | string[]`**：schema 对它**无任何类型约束**
 * （只有一句 description）。因此「`type: 'pseudocode'` 且 `text` 非空字符串」这种组合完全
 * 合法，取文本必须走 `~/utils/blueprintBlocks` 的 `blockText()` 按**字段优先级**判定，
 * ⛔ 绝不按 `type` 分派（P-13：坐标系与后端不一致会让批注圈错字且不报错）。
 */
export interface BlueprintBlock {
  /** 块稳定标识（版本间编辑保留，是 anchor 与 block 级 diff 的对齐键）。 */
  block_id: string
  type: BlueprintBlockType
  /** paragraph/mermaid 通常是 string、list 通常是 string[]，但 schema 零约束 ⇒ `unknown`。 */
  text?: unknown
  /** pseudocode 专用；schema 只声明 `type: object`，键均需可选链。 */
  code?: { language?: string, source?: string }
  /** table 专用：行数组（每行为单元格数组）；单元格类型无约束。 */
  rows?: unknown[][]
  /** 本块结论依据的引用 id（键指向文档级 `citations` 池）。 */
  citations?: string[]
}

/** 文档级引用池条目（块内只存 id，条目去重存放在 `content.citations`）。 */
export interface Citation {
  citation_id: string
  source_type: CitationSourceType
  /** 对应实体主键 / chunk id / URL。 */
  source_id?: string
  /**
   * 文件路径 / 行号 / heading / chunk 等定位信息。
   * ⚠️ 运行期形状无 schema 保证：`repo_file` 引用**未必**带 `line_start`
   * （缺失时 `chunk-at` 稳定 400 ⇒ 调用点应直接走快照兜底，见 `~/api/repositoryChunks`）。
   */
  locator?: Record<string, unknown>
  /** 被引用的关键原文摘录（来源不可达时作为兜底快照渲染）。 */
  quote?: string
  /** 展示用标题快照。 */
  title?: string
}

// ── 正文各段 ──────────────────────────────────────────────────────────────────

/** 文档元信息；`meta.summary` 是首屏执行摘要，`meta.project_id` 供关联项目使用。 */
export interface BlueprintMeta {
  title: string
  project_id: string
  summary?: BlueprintBlock[]
  space_id?: string
  /** 需求来源引用（项目 PRD / feature list / work item）；条目形状无约束。 */
  requirement_refs?: unknown[]
  language?: string
  revision_round?: number
}

/** 需求规格的功能点。 */
export interface BlueprintFeaturePoint {
  id: string
  title: string
  intent: 'greenfield' | 'brownfield' | 'fix'
  description?: BlueprintBlock[]
  source_ref?: string
  acceptance_criteria?: string[]
  test_cases?: unknown[]
}

export interface BlueprintRequirementSpec {
  goal: BlueprintBlock[]
  feature_points: BlueprintFeaturePoint[]
  background?: BlueprintBlock[]
  boundaries?: Record<string, unknown>
  constraints?: unknown[]
  ambiguity_report?: Record<string, unknown>
}

/** 单仓关联条目（确认门锁定的就是这一段）。 */
export interface BlueprintRepoAssociation {
  repository_id: string
  repository_name: string
  role: 'direct' | 'indirect'
  rationale?: {
    text?: BlueprintBlock[]
    constraint_refs?: string[]
    citations?: string[]
  }
  responsibility?: BlueprintBlock[]
  fitness?: {
    verdict?: 'suitable' | 'partial' | 'unsuitable'
    reasons?: BlueprintBlock[]
    citations?: string[]
  }
  planned_change_summary?: BlueprintBlock[]
  capabilities_used?: unknown[]
  /** 路由打分证据；schema 只声明 `type: object` ⇒ 逐键可选链。 */
  routing_evidence?: Record<string, unknown>
  decided_by?: 'ai' | 'human'
  confirmed_at_gate?: boolean
  support_needed?: BlueprintBlock[]
}

export interface BlueprintFinding {
  id: string
  text: BlueprintBlock[]
  kind: 'capability' | 'gap' | 'risk' | 'convention'
  citations: string[]
  topic?: string
  related_feature_points?: string[]
}

export interface BlueprintCurrentStateAnalysis {
  repository_id: string
  findings: BlueprintFinding[]
  summary?: BlueprintBlock[]
}

export interface BlueprintImplementationModule {
  id?: string
  name?: string
  feature_point_ids?: string[]
  repository_ids?: string[]
  narrative?: BlueprintBlock[]
}

export interface BlueprintImplementationItem {
  id: string
  feature_point_id: string
  repository_id: string
  change_type: 'create' | 'modify' | 'remove' | 'indirect_refine'
  title: string
  module_id?: string
  how?: BlueprintBlock[]
  existing_integration?: BlueprintBlock[]
  files_touched?: Array<{ path: string, action: 'create' | 'modify' | 'remove', note?: string }>
  depends_on?: string[]
  wave?: number
  test_strategy?: BlueprintBlock[]
  citations?: string[]
}

export interface BlueprintImplementationOverview {
  requirement_narrative: BlueprintBlock[]
  items: BlueprintImplementationItem[]
  modules?: BlueprintImplementationModule[]
}

export interface BlueprintApiContract {
  id: string
  name: string
  kind: 'http' | 'rpc' | 'event' | 'mq'
  direction: 'provided' | 'consumed'
  repository_id?: string
  method?: string
  path?: string
  description?: BlueprintBlock[]
  /** 示例 / schema 四项均为裸 object：LLM 产出，渲染前必须做 JSON 安全序列化。 */
  request_example?: Record<string, unknown>
  response_example?: Record<string, unknown>
  request_schema?: Record<string, unknown>
  response_schema?: Record<string, unknown>
  data_source?: {
    from_service?: string
    from_api?: string
    fields_needed?: string[]
    availability?: 'existing' | 'needs_support'
    support_repository_id?: string
    notes?: BlueprintBlock[]
  }
  consumers?: string[]
  citations?: string[]
}

export interface BlueprintAffectedFeature {
  feature: string
  kind: 'behavior_change' | 'perf' | 'compat' | 'data' | 'none'
  repository_ids?: string[]
  description?: BlueprintBlock[]
  citations?: string[]
}

export interface BlueprintImpactAnalysis {
  business_impact: BlueprintBlock[]
  affected_features: BlueprintAffectedFeature[]
  regression_scope?: Array<{ area?: string, level?: 'full' | 'smoke' | 'none', reason?: string }>
  compat_risks?: BlueprintBlock[]
  /** 迁移条目形状无约束。 */
  data_migrations?: unknown[]
  rollback_plan?: BlueprintBlock[]
}

export interface BlueprintFlowStep {
  seq: number
  actor: string
  action: string
  component?: string
  api_ref?: string
  data_in?: string
  data_out?: string
  note?: BlueprintBlock[]
}

export interface BlueprintInteractionFlow {
  id: string
  name: string
  steps: BlueprintFlowStep[]
  trigger?: string
  alternative_paths?: unknown[]
  mermaid?: string
  citations?: string[]
}

/**
 * goal-backward 验收锚点。
 *
 * ⚠️ 三个子块**都不是 Block[]**（`truths` 是裸字符串数组，`artifacts` / `key_links`
 * 是零约束 array）⇒ 该段**不接批注层**（无 `block_id` 可锚，UI-SPEC §6.9 / §20 断言 9）。
 */
export interface BlueprintMustHaves {
  truths: string[]
  artifacts: unknown[]
  key_links: unknown[]
}

/**
 * blueprint/v1 正文（顶层 14 键；`required` 11 键，其余三键可选）。
 *
 * ⚠️ `decision_log` / `deferred_ideas` / `execution_plan` 是**零约束裸 array**（P-14）
 * ⇒ 类型 `unknown[]`，且它们**不在** `iterBlocks` 的走查范围内（后端 `iter_blocks`
 * 对它们零 `collect` ⇒ 后端不会往那里挂线程，前端也不得自行发明锚点）。
 */
export interface BlueprintV1 {
  /** 判别字段：不等于 `'blueprint/v1'` 时整页降级为「旧版方案」。 */
  schema_version: string
  meta: BlueprintMeta
  requirement_spec: BlueprintRequirementSpec
  repo_associations: BlueprintRepoAssociation[]
  current_state_analysis: BlueprintCurrentStateAnalysis[]
  implementation_overview: BlueprintImplementationOverview
  api_contracts: BlueprintApiContract[]
  impact_analysis: BlueprintImpactAnalysis
  interaction_flows: BlueprintInteractionFlow[]
  must_haves: BlueprintMustHaves
  /** 文档级引用池：`{citation_id: Citation}`（**是 object 不是 array**）。 */
  citations: Record<string, Citation>
  decision_log?: unknown[]
  deferred_ideas?: unknown[]
  execution_plan?: unknown[]
}

// ── 端点 ① 正文 ───────────────────────────────────────────────────────────────

/**
 * 方案质量四项（115-01-SUMMARY §3）。
 *
 * ⚠️ **`null` ≠ `0`**：`null` = 「没有数据源可算」，`0` = 「统计到了，值为零」。
 * ⛔ 前端**绝不**做 `v ?? 0` 归一——那会把「还没跑过 AI 审查」渲染成「零打回」，
 * 让评审据错误指标放行（UI-SPEC §20 断言 7）。无数据一律渲染
 * `t('knowledge.blueprints.quality.noData')`。
 */
export interface BlueprintQuality {
  /** 纯函数算得，**恒有值**（引用池为空时后端返 `1.0`，不返 null）。 */
  citation_coverage: number
  ai_rejection_rate: number | null
  human_edit_volume: number | null
  clarification_rounds: number | null
}

/** `GET /api/delivery/artifacts/<uuid>/blueprint/`（`?version_id=` 可选，缺省取 current）。 */
export interface BlueprintDocumentResponse {
  version_id: string
  version_no: number
  is_current: boolean
  /** 版本原因，四前缀之一或其它（映射见 `~/config/blueprintStatus` 的 `producedByReason`）。 */
  produced_by_ref: string
  created_at: string
  content: BlueprintV1
  quality: BlueprintQuality
  /**
   * 蓝图在交付知识图谱里的实体 id（Phase 116-04 纯追加第 8 键）。
   * 反查用：`GET /api/knowledge/related/<它>/?direction=in&relations=REFERENCES&max_hops=1`。
   * ⛔ 前端不复制该 id 的派生规则——后端 `generate_entity_id` 是唯一入口。
   */
  knowledge_entity_id: string
  /**
   * 所属项目 id（Phase 117 纯追加，LINK-02）。归属权威在 `content.meta.project_id`，
   * 本键是后端替消费方挖好的顶层口径，与列表端点一致；无归属时为 `null`。
   */
  project_id: string | null
  /** 所属项目名。项目已删或脏数据时为空串（此时 `project_id` 仍照实回传）。 */
  project_name: string
  /**
   * 展示标题派生（与列表 title 同口径：`{项目名} - 技术方案 - YYYY-MM-DD HH:mm`）。
   * ⭐ 优先于 `content.meta.title`；旧数据无需 DB 回填。
   */
  display_title: string
  /**
   * 版本谱系标签（quick-260806 节点重跑）。空串 = 旧数据未打标 ⇒ 展示回落 `v{version_no}`。
   */
  version_label?: string
}

// ── 端点 ② 阶段事件 ──────────────────────────────────────────────────────────

/**
 * 单条蓝图阶段事件。
 *
 * ⚠️ `payload` 的键由各 emit 点自定、**schema 层零保证**（P-8）⇒ 插值文案的每个键
 * 都可能缺；缺键时必须回落 `knowledge.blueprints.progress.*Generic` 的无参兜底文案，
 * ⛔ 不要指望 vue-i18n 报错（它会渲染成「正在调研 undefined…」）。
 */
export interface BlueprintEvent {
  id: string
  event: string
  payload: Record<string, unknown>
  /** ISO8601；升序返回。`ts` 允许 emit 端传入 ⇒ 与 `created_at` 可以不同。 */
  ts: string
}

/**
 * `GET .../blueprint/events/`。
 *
 * ⭐ **无会话时是 200 空结构**（`{session_id: '', current_stage: '', events: []}`），
 * 表示「尚未开始编排」，⛔ 不是错误态、不能走 404 的全页中性空态。
 */
export interface BlueprintEventsResponse {
  session_id: string
  current_stage: string
  events: BlueprintEvent[]
}

// ── 端点：按仓调研明细（结论 + agent 过程日志）────────────────────────────────

/**
 * 一条容器过程日志。
 *
 * `type` 与后端 `_TASK_LOG_PREFIXES` 的值域一致（`text` / `tool_call` / `tool_result` /
 * `block` / `result` / `system` / `message` / `progress` / `error`）。⛔ 不收窄成联合
 * 类型：容器侧新增前缀时，收窄会让新类型在这一层被 TS 挡掉而不是原样透出。
 */
export interface BlueprintRunLog {
  type: string
  /** 已在服务端过 `redact_secrets_in_text`，⛔ 前端不得再拼接明文。 */
  content: string
  ts: string
}

/** 一次容器运行（同一个仓可能有多次：阶段一调研、阶段二分仓、以及各自的重试）。 */
export interface BlueprintResearchRun {
  session_id: string
  /** `research`（阶段一调研）/ `repo_plan`（阶段二分仓）；识别不出为空串。 */
  stage: string
  status: string
  started_at: string
  completed_at: string
  logs: BlueprintRunLog[]
  /**
   * ⚠️ 为真表示这条运行只剩 `last_output` 的尾窗（存量会话，全量表建立之前跑的），
   * 看到的**不是全程**。UI 必须显式标出，否则会被误读成「agent 只做了这几步」。
   */
  logs_truncated_tail: boolean
}

/** 单个仓库的调研结论与过程。`conclusion` 是 `PartialPlan.content`，键由产出侧自定。 */
export interface BlueprintResearchRepo {
  repository_id: string
  repository_name: string
  status: string
  attempt: number
  error: Record<string, unknown>
  conclusion: Record<string, unknown>
  runs: BlueprintResearchRun[]
}

/** `GET .../blueprint/research-detail/`；无会话时同为 200 空结构。 */
export interface BlueprintResearchDetailResponse {
  session_id: string
  repositories: BlueprintResearchRepo[]
}

// ── 端点：节点面（stages GET + rerun POST，quick-260806 节点重跑）──────────────

/**
 * 单个 stage 的节点快照条目。
 *
 * ⚠️ `state` 是该 stage 的 `stage_state` 分片，键由各 adapter 自定、**schema 层零保证**：
 * 消费方一律做成可读的键值 / 折叠 JSON 展示，⛔ 不得假设内部形状、⛔ 不整页倾倒大 JSON。
 */
export interface BlueprintStageEntry {
  /** 后端 stage key（`intake|decompose|route|repo_research|repo_confirmation|spec_gate|repo_plan|merge|ai_review`）。 */
  key: string
  /** 该 stage 的 stage_state 分片；无会话 / 尚未产出时为 `{}`。 */
  state: Record<string, unknown>
}

/** 带指令重跑的标记（当前 / 历史共用同一形状）。 */
export interface BlueprintStageRerunMarker {
  stage: string
  instruction: string
  run_label: string
  requested_by: string
  requested_at: string
}

/** 版本谱系条目（版本树切换器的供数；`version_label` 空串 = 旧数据回落 `v{version_no}`）。 */
export interface BlueprintStageVersionRow {
  version_id: string
  version_no: number
  version_label: string
  produced_by_ref: string
  created_at: string
  is_current: boolean
}

/**
 * `GET .../blueprint/stages/`。
 *
 * ⭐ **无会话时是 200 空结构**（`session_id: ''`、各 stage 的 `state` 为 `{}`），
 * `versions` 仍有效 —— ⛔ 不是错误态，版本树照常可用。
 */
export interface BlueprintStagesResponse {
  session_id: string
  current_stage: string
  session_status: string
  run_label: string
  stage_rerun: BlueprintStageRerunMarker | null
  stage_rerun_history: BlueprintStageRerunMarker[]
  /** 可重跑的**后端 stage key** 集合（UI 节点 key 需先经映射，如 confirmation → repo_confirmation）。 */
  rerunnable_stages: string[]
  stages: BlueprintStageEntry[]
  versions: BlueprintStageVersionRow[]
}

/** `POST .../blueprint/stages/rerun/` 的 200 响应；400 / 409 走 `ApiError.detail`。 */
export interface BlueprintStageRerunResponse {
  status: string
  run_label: string
  stage: string
  detail: string
  session_status: string
}

// ── 端点 ③④ 线程详情与选区评论 ───────────────────────────────────────────────

/** 线程锚点（block 内字符区间 + 原文快照）；无锚点的系统线程该字段为 `null`。 */
export interface BlueprintAnchor {
  section_path?: string
  block_id?: string
  start_offset?: number
  end_offset?: number
  quoted_text?: string
}

/** 线程内单条消息（`author` 是 SET_NULL FK ⇒ 必须容忍 `author_user_id === null`）。 */
export interface BlueprintThreadMessage {
  id: string
  author_type: 'ai' | 'human'
  /** 作者被删 / AI 作者 → `null`；⚠️ 同场景 `author_display` 是 `''` 而不是 null。 */
  author_user_id: string | null
  author_display: string
  body: string
  created_at: string
}

/**
 * 线程详情（`_thread_row` 九键 + `options` / `last_reminded_at` / `messages` 三补键）。
 *
 * ⚠️ `status` 与 `anchor_status` **正交**：一条 `open` 的失锚线程同时满足两个维度，
 * 侧栏分组必须带上 `&& anchor_status !== 'orphaned'` 的否定项，否则它会出现两次
 * （§20 断言 11，判据实现在 `~/utils/blueprintAnnotations` 的 `sidebarGroups`）。
 */
export interface BlueprintThreadDetail {
  thread_id: string
  kind: BlueprintThreadKind
  severity: BlueprintThreadSeverity
  status: BlueprintThreadStatus
  blocking: boolean
  anchor_status: BlueprintAnchorStatus
  /** 非 dict / 无锚点 → `null`。 */
  anchor: BlueprintAnchor | null
  return_stage: string
  created_at: string
  /**
   * 双形态（后端 `JSONField` **无 schema 校验**）：
   * - 规格门结构化澄清：`{ text, options: string[], recommended?, related_feature_points?, citations? }`
   * - 扁平候选答案：`{ label?, value?, note? }`（旧 composer 点选填入）
   * 前端用 `isStructuredClarificationQuestions` 分流。
   */
  options: Array<
    | { text?: string, question?: string, options?: string[], recommended?: string, related_feature_points?: string[], citations?: string[] }
    | { label?: string, value?: string, note?: string }
  >
  /** 从未提醒 → `null`。 */
  last_reminded_at: string | null
  /** 已发出的提醒次数（Phase 117，WAIT-03）。 */
  reminder_count?: number
  /** 提醒到上限后的显式到期时刻；未到期 → `''` / 缺省。到期**不等于**线程已处置。 */
  expired_at?: string | null
  /** 按 `created_at` 升序。 */
  messages: BlueprintThreadMessage[]
}

/** `GET .../blueprint-review/threads/`。 */
export interface BlueprintThreadsResponse {
  threads: BlueprintThreadDetail[]
}

/** 选区评论的入参 body（`anchor` 可缺省 ⇒ 建无锚点的整篇评论）。 */
export interface CreateBlueprintCommentPayload {
  body: string
  anchor?: BlueprintAnchor
}

/** `POST .../blueprint-review/threads/` 的 200 响应（两键）。 */
export interface CreateBlueprintCommentResponse {
  thread_id: string
  /** ⭐ 状态一律以响应体这个键为准，⛔ 前端不得自行乐观推断下一状态。 */
  current_status: BlueprintStatus
}

// ── 端点 ⑤ 列表 ───────────────────────────────────────────────────────────────

/** 列表项引用到的仓库摘要。 */
export interface BlueprintListRepository {
  id: string
  name: string
  role: 'direct' | 'indirect'
}

/**
 * 蓝图列表项。
 *
 * ⭐ 状态键是 **`current_status`** 而不是 `blueprint_status`（115-01 对 UI-SPEC §3.3 的
 * 订正，P-1）：后端 INV-6 字段级守卫扫全 `server/`，响应键用模型字段名即判旁路写。
 */
export interface BlueprintListItem {
  artifact_id: string
  title: string
  /** `meta.summary` 首块纯文本，≤200 字符。 */
  summary: string
  current_status: BlueprintStatus
  /** 读不到 → `null`（⚠️ 其余字符串字段读不到一律 `''`，不是 null）。 */
  project_id: string | null
  /** 取不到回落 `''`。 */
  project_name: string
  repositories: BlueprintListRepository[]
  thread_count: number
  /** 判据：`severity=blocker` 且 `blocking=true` 且 `status ∈ {open, answered}`。 */
  unresolved_blocker_count: number
  revision_round: number
  current_version_no: number
  /** Artifact 创建时间（ISO8601）；列表排序与展示标题时间戳的权威来源。 */
  created_at: string
  updated_at: string
}

/**
 * `GET /api/delivery/blueprints/` 的分页体。
 *
 * ⭐ **五键手写分页**（115-01 对 UI-SPEC §3.3 的第二处订正）：过滤发生在 Python 侧
 * 而非 queryset 上，DRF 的分页 helper 用不上。
 */
export interface BlueprintListResponse {
  total: number
  items: BlueprintListItem[]
  page: number
  page_size: number
  has_next: boolean
}

/** 列表查询参数（全部可选、可组合；空值不进 query）。 */
export interface ListBlueprintsParams {
  project_id?: string
  /** ⚠️ 这是**后端的 query 参数名**（前端侧不受 INV-6 守卫约束），与响应键 `current_status` 不同名。 */
  blueprint_status?: string
  repository_id?: string
  /** 标题 + 摘要 icontains。 */
  q?: string
  page?: number
  page_size?: number
}

// ── 复用端点：人审快照与七动作 ────────────────────────────────────────────────

/**
 * 快照里的线程条目（`_thread_row` 九键）。
 *
 * ⚠️ **不含 `options`、不含任何消息** —— 这正是端点 ③ 必须新增的原因。同一 `thread_id`
 * 在两处都出现时以 `threads/` 的 `BlueprintThreadDetail` 为准（它更全），快照条目只在
 * `threads/` 尚未就绪时占位。
 */
export interface BlueprintThreadRow {
  thread_id: string
  kind: BlueprintThreadKind
  severity: BlueprintThreadSeverity
  status: BlueprintThreadStatus
  blocking: boolean
  anchor_status: BlueprintAnchorStatus
  anchor: BlueprintAnchor | null
  return_stage: string
  created_at: string
  /** 已发出的提醒次数（Phase 117，WAIT-03）。 */
  reminder_count: number
  /** 最近一次提醒时刻；从未提醒 → `''`（⚠️ 空串不是 null，与 `BlueprintThreadDetail` 不同）。 */
  last_reminded_at: string
  /**
   * 提醒到上限后的显式到期时刻；未到期 → `''`。
   *
   * ⚠️ 到期**不改** `status`/`blocking` —— 一条 `expired_at` 非空的线程仍是 `open` 且仍阻塞
   * confirm。它的含义只有「系统不再催了」，⛔ 不要据此把线程当作已处置。
   */
  expired_at: string
}

/** `GET .../blueprint-review/` —— 人审只读快照（十键）。 */
export interface BlueprintReviewSnapshot {
  artifact_id: string
  session_id: string
  current_status: BlueprintStatus
  revision_round: number
  /** AI 审查发现按 severity 三级分组。 */
  findings: Record<string, BlueprintThreadRow[]>
  clarifications: BlueprintThreadRow[]
  comments: BlueprintThreadRow[]
  /**
   * 失锚线程。⭐ **直接渲染、前端不再二次过滤**（114 MJ-02 已保证里面只有真失锚；
   * 再过滤只会把真失锚也滤掉，§20 断言 5）。
   */
  orphaned_threads: BlueprintThreadRow[]
  /** AI 审查轮次内的未决条目（形状由 stage_state 决定，无 schema 保证）。 */
  unresolved: unknown[]
  review_round: number
  unresolved_blocker_count: number
  /** ⭐ 409 blocked 时**必须逐条渲染成可点处置入口**：那是超界死锁的唯一解药。 */
  unresolved_blocker_thread_ids: string[]
}

/** approve 的 200 响应。 */
export interface BlueprintApproveResponse {
  status: string
  current_status: BlueprintStatus
  artifact_id: string
}

/** reject 的 200 响应（先落版本再转状态 ⇒ 带版本键）。 */
export interface BlueprintRejectResponse {
  status: string
  version_id: string
  version_no: number
  revision_round: number
  thread_id: string
  current_status: BlueprintStatus
  /**
   * **归一后**的重跑范围（Phase 120）。⚠️ 可能与请求里传的不同 —— 后端对非法值回落
   * `merge` 而不是 400，回显必须用这个值，⛔ 不要回显请求里那个。
   */
  rework_scope: string
  /** `repos` 范围下被失效（将被重跑）的仓数；其它范围恒 0。 */
  reworked_repository_count: number
}

/**
 * answer 的回灌结果。
 *
 * ⭐ 端点**恒 200**，`status` 只决定 toast 语气，⛔ 绝不当作请求失败。
 */
export interface BlueprintReflowResult {
  status: string
  version_id: string
  version_no: number
  conflict_block_ids: string[]
  thread_id: string
  detail: string
}

/** answer 的 200 响应。 */
export interface BlueprintAnswerResponse {
  status: string
  thread_id: string
  reflow: BlueprintReflowResult
}

/** finding 处置（resolve / dismiss）的 200 响应。 */
export interface BlueprintFindingActionResponse {
  status: string
  thread_id: string
}

/**
 * block 级人工编辑的单条 op（CLAR-03）。
 *
 * 形状逐字对齐后端 `delivery/services/blueprint_block_edit.apply_block_ops`：
 * `insert` 用 `block_id` 作**锚点**、`position` 缺省 `after`；`replace` 的 `block.block_id`
 * 一律以路径上的原 id 为准（前端传不一致的 id 只换来一条提示级 `block_id_immutable`）。
 */
export interface BlueprintBlockOp {
  op: 'replace' | 'insert' | 'delete'
  block_id: string
  block?: BlueprintBlock
  position?: 'before' | 'after'
}

/**
 * 被拒条目。
 *
 * `reason` 六值：`unknown_op` / `block_not_found` / `missing_block` / `missing_block_id`
 * 为**硬失败**（整批不落版本、端点 400）；`block_id_immutable` 是**提示级**（随成功结果
 * 一并回显）；`apply_failed` 是整体兜底。
 */
export interface BlueprintBlockEditRejection {
  op: string
  block_id: string
  reason: string
}

/**
 * `POST .../blueprint-review/edit-blocks/` 的 **200** 响应。
 *
 * `status` 只可能是 `applied`（已落新版本）或 `unchanged`（同 content_hash 未翻版本，
 * 重放安全）—— `rejected` / `invalid` 两档由端点映射成 **400**，经 `ApiError.body` 取
 * `detail` 与 `rejected`，⛔ 不会走到这个类型上。
 */
export interface BlueprintBlockEditResponse {
  status: string
  version_id: string
  version_no: number
  rejected: BlueprintBlockEditRejection[]
  /** 重锚定恒定四键 `{checked, reanchored, orphaned, skipped}`（best-effort，可能全零）。 */
  reanchor: Record<string, number>
}

// ── 复用端点：确认门快照与八动作 ──────────────────────────────────────────────

/** 确认门快照的单仓条目。 */
export interface BlueprintGateRepo {
  repository_id: string
  repository_name: string
  role_suggestion: string
  responsibility: string
  confidence: string
  /** 适配结论；裸 JSONField ⇒ 逐键可选链。 */
  fitness: Record<string, unknown>
  current_state_summary: string
  routing_evidence: Record<string, unknown>
  task_status?: string
  pending_research?: boolean
  removed?: boolean
}

/**
 * `GET .../blueprint-gate/` —— 确认门只读快照。
 *
 * ⚠️ **该端点的 404 是正常态**（「确认门未开启」是绝大多数蓝图绝大多数时间的状态）：
 * 它只决定 gate 面板**是否渲染**，⛔ 不进 §8.2 的错误分档、不触发全页空态、不弹 toast。
 * 判据一律「非 200 ⇒ 不渲染」，⛔ 不读 `detail` 文本分支（那等于把后端文案当协议）。
 */
export interface BlueprintGateSnapshot {
  artifact_id: string
  session_id: string
  thread_id: string
  thread_status: string
  current_stage: string
  repo_count: number
  pending_research_repository_ids: string[]
  repos: BlueprintGateRepo[]
}

/** 确认门七动作的**形状恒定**结果（调用方无需判分支）。 */
export interface BlueprintGateActionResult {
  action: string
  repository_id: string | null
  thread_id: string
  requires_research: boolean
  ready_to_lock: boolean
  locked: boolean
  upgraded: boolean
  already_running?: boolean
  locked_repo_count: number
}

/** `rejected-to-boundary` 的 200 响应（沉淀章程草案的计数三键）。 */
export interface BlueprintBoundaryDraftResult {
  candidate_count: number
  draft_count: number
  repository_count: number
}
