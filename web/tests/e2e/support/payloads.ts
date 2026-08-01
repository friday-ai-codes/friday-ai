/**
 * 后端载荷 builder —— 每一个都标注了形状出处，便于对账。
 *
 * 🔴 纪律：形状只从真实序列化产物抄，不从「前端能跑通」倒推。
 * 例如工具出参不是 `{output:{data}}` 而是 `{data, metadata}`，因为
 * `chat_runner._normalize_tool_result` 取的是 `ToolResult.output` 本身
 * （`server/agents/chat_runner.py:402`），再 `json.dumps` 成 part.result 字符串。
 */

import { E2E_SPACE } from './api'

export const CONVERSATION_ID = 'c-e2e-1'

/** 与 `ConversationSerializer` 对齐。 */
export function conversation(overrides: Record<string, unknown> = {}) {
  return {
    id: CONVERSATION_ID,
    space_id: E2E_SPACE.id,
    title: 'E2E 会话',
    model: 'claude-e2e',
    status: 'active',
    provider_credential_id: 'cred-1',
    bound_project_id: null,
    visibility: 'personal',
    created_by: null,
    is_archived: false,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    ...overrides,
  }
}

/** `ConversationDetail`：Conversation + messages。 */
export function conversationDetail(messages: unknown[], overrides: Record<string, unknown> = {}) {
  return { ...conversation(), messages, clarifications: [], routing_trace: null, ...overrides }
}

/** `ConversationRuntime` 的最小静默形态：没有任何在途运行。 */
export function idleRuntime(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: CONVERSATION_ID,
    active: false,
    mode: 'chat',
    coding_session: null,
    coding_plan: null,
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// 消息 / parts（`server/chat/parts.py` 的 discriminated union）
// ---------------------------------------------------------------------------

export interface ToolPartSeed {
  id: string
  name: string
  input?: Record<string, unknown>
  result?: string
  status?: 'running' | 'done' | 'error'
}

export function toolPart(seed: ToolPartSeed, index: number) {
  return {
    type: 'tool_use',
    id: `p-${seed.id}`,
    index,
    tool_call_id: seed.id,
    name: seed.name,
    input: seed.input ?? {},
    status: seed.status ?? 'done',
    result: seed.result ?? null,
  }
}

export function assistantMessage(id: string, parts: unknown[], content = '') {
  return {
    id,
    role: 'assistant',
    content,
    parts,
    metadata: {},
    created_at: '2026-08-01T00:00:10Z',
  }
}

export function userMessage(id: string, content: string) {
  return {
    id,
    role: 'user',
    content,
    parts: [{ type: 'text', id: `p-${id}`, index: 0, text: content, state: 'done' }],
    metadata: {},
    created_at: '2026-08-01T00:00:00Z',
  }
}

// ---------------------------------------------------------------------------
// analyze_repository_relevance 出参
// 形状出处：`RepositoryRelevanceOutput`（server/agents/tools/schemas/
// repository_relevance.py，schema 快照见 tests/agents/fixtures/
// repository_relevance_output_schema.json）+ ToolResult.output 的 `{data, metadata}`。
// ---------------------------------------------------------------------------

export interface CandidateSeed {
  repository_id: string
  repository_name: string
  score: number
  level: 'high' | 'medium' | 'low'
  evidence: string
  group?: 'in_project' | 'global' | ''
  breakdown?: Record<string, number>
  score_ranked?: number | null
  selected_by_ai?: boolean
  selected_by_user_final?: boolean
}

export interface RelevanceSeed {
  candidates: CandidateSeed[]
  block_order?: string[]
  degraded?: boolean
  degrade_reason?: string
  router_version?: string
  threshold?: number
}

export function relevanceResult(seed: RelevanceSeed): string {
  const candidates = seed.candidates.map(c => ({
    repository_id: c.repository_id,
    repository_name: c.repository_name,
    score: c.score,
    level: c.level,
    evidence: c.evidence,
    selected_by_ai: c.selected_by_ai ?? true,
    selected_by_user_final: c.selected_by_user_final ?? false,
    sub_project: '',
    sub_project_paths: [],
    breakdown: c.breakdown ?? {},
    group: c.group ?? '',
    trust: '',
    score_ranked: c.score_ranked ?? null,
  }))
  return JSON.stringify({
    data: {
      candidates,
      threshold: seed.threshold ?? 0.5,
      total_candidates: candidates.length,
      trace_id: 'trace-e2e-1',
      router_version: seed.router_version ?? 'v2',
      degraded: seed.degraded ?? false,
      degrade_reason: seed.degrade_reason ?? '',
      block_order: seed.block_order ?? [],
    },
    metadata: { searched_repositories: candidates.length, trace_id: 'trace-e2e-1' },
  })
}

/** 走完整用户路径需要的一条「仓库分级路由」助手消息。 */
export function relevanceMessage(seed: RelevanceSeed) {
  return assistantMessage(
    'msg-relevance',
    [toolPart({
      id: 'call-relevance',
      name: 'analyze_repository_relevance',
      input: { query: '给登录页加图形验证码' },
      result: relevanceResult(seed),
    }, 0)],
    '已完成仓库分级路由。',
  )
}

// ---------------------------------------------------------------------------
// start_plan_research 出参
// 形状出处：`server/agents/tools/plan_research_tools.py`
//   - 在途：`_maybe_suspend` 的 `__blocking_task__` 载荷
//   - 终态：`_map_terminal` 的 `{session_id, artifact_version_id, status:'done', message}`
// ---------------------------------------------------------------------------

export const PLAN_SESSION_ID = 'ps-e2e-1'
export const ARTIFACT_VERSION_ID = 'av-e2e-1'

export function planResearchRunningResult(sessionId = PLAN_SESSION_ID): string {
  return JSON.stringify({
    __blocking_task__: true,
    task_type: 'plan_research',
    task_id: sessionId,
    session_id: sessionId,
    params: { session_id: sessionId },
    placeholder: `已发起跨仓方案编排调研（session=${sessionId}，状态=researching）；深入调研容器运行中，调研完成后将自动融合并返回 canonical 主方案。`,
  })
}

export function planResearchDoneResult(
  sessionId = PLAN_SESSION_ID,
  artifactVersionId: string | null = ARTIFACT_VERSION_ID,
): string {
  return JSON.stringify({
    session_id: sessionId,
    artifact_version_id: artifactVersionId,
    status: 'done',
    message: '跨仓方案编排已完成，已产出技术方案产物（ArtifactVersion）。',
  })
}

export function orchestrationMessage(result: string, id = 'msg-orch') {
  return assistantMessage(
    id,
    [toolPart({
      id: 'call-orch',
      name: 'start_plan_research',
      input: { requirement: '给登录页加图形验证码' },
      result,
    }, 0)],
  )
}

// ---------------------------------------------------------------------------
// 编排运行时快照 / 事件
// 形状出处：`OrchestrationRuntime`（web/src/types/chat.ts，与后端
// runtime["orchestration"] 八键一一对应）；事件名与 payload 取自
// `server/services/process_runtime/builtin_processes.py`（`repo.routing` /
// `knowledge.recalling` / `repo.research.*`）。
// ---------------------------------------------------------------------------

export interface OrchestrationEvent {
  event: string
  ts: string
  payload: Record<string, unknown>
}

export function routingEvent(ts: string, opts: {
  candidates?: number
  degraded?: boolean
  degradeReason?: string
} = {}): OrchestrationEvent {
  return {
    event: 'repo.routing',
    ts,
    payload: {
      candidates: Array.from({ length: opts.candidates ?? 2 }, (_, i) => ({
        repo_id: `r-${i}`,
        confidence: 'high',
        score: 0.9 - i * 0.1,
        breakdown: { text: 0.7, breadth: 0.2 },
      })),
      router_version: 'v2',
      degraded: opts.degraded ?? false,
      degrade_reason: opts.degradeReason ?? '',
      auto_selected: false,
    },
  }
}

export function recallEvent(ts: string, hits = 12): OrchestrationEvent {
  return { event: 'knowledge.recalling', ts, payload: { query: '登录验证码', kinds: [], hits } }
}

export function transition(event: string, ts: string): OrchestrationEvent {
  return { event, ts, payload: {} }
}

export function researchEvent(
  kind: 'started' | 'completed' | 'failed',
  repoId: string,
  ts: string,
): OrchestrationEvent {
  return { event: `repo.research.${kind}`, ts, payload: { repo_id: repoId } }
}

export function orchestrationSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    session_id: PLAN_SESSION_ID,
    status: 'running',
    current_stage: 'research',
    has_classify: false,
    segment_count: 3,
    failure: null,
    events: [] as OrchestrationEvent[],
    events_truncated: false,
    ...overrides,
  }
}

/** `PlanResearchSession`（runtime 顶层 `plan_research_sessions` 的一项）。 */
export function planResearchSession(
  repositoryId: string,
  repositoryName: string,
  status: 'RUNNING' | 'COMPLETED' | 'ERROR' = 'COMPLETED',
  planSessionId = PLAN_SESSION_ID,
) {
  return {
    session_id: `sub-${repositoryId}`,
    plan_session_id: planSessionId,
    repository_id: repositoryId,
    repository_name: repositoryName,
    status,
    logs: [
      { type: 'tool', content: `在 ${repositoryName} 检索登录相关实现`, ts: 1754000000 },
      { type: 'text', content: '已定位 LoginForm 组件', ts: 1754000001 },
    ],
  }
}

// ---------------------------------------------------------------------------
// 编排产出投影（POST /chat/coding-plans/from-artifact-version/）
// 形状出处：`ProjectPlanToCodingResponse`（web/src/types/chat.ts）。
// `tech_plan` 是 `render_merged_plan_markdown` 的**真实输出**：本串由
// `server/services/process_runtime/render.py` 对一份 MergedPlan 实跑得到，
// 用于 109-4 的 lark_md 方言呈现核验（项目符号是字面 `•`，不是 markdown 列表）。
// ---------------------------------------------------------------------------

export const LARK_MD_TECH_PLAN = [
  '**需求：给登录页加图形验证码**',
  '',
  '在 onion-web 登录页接入图形验证码，并由 sso-gateway 提供签发与校验接口。',
  '',
  '**📋 执行计划（共 2 项）**',
  '',
  '**1. 登录页接入验证码组件**  `onion-web`',
  '',
  '在登录表单中加入验证码输入框与刷新按钮。',
  '',
  '> 修改 LoginForm.vue，新增 captcha 字段并在提交时一并发送。',
  '',
  '**2. 验证码签发与校验接口**  `sso-gateway`',
  '',
  '提供 /captcha 签发与登录校验。',
  '',
  '**⚠️ 兼容风险**',
  '• 老版本 App 未带 captcha 字段，需要灰度开关兜底',
  '• 验证码服务不可用时需降级为短信验证',
].join('\n')

export function projectionResponse(overrides: Record<string, unknown> = {}) {
  return {
    coding_plan_id: 'cp-e2e-1',
    created: true,
    title: '需求：给登录页加图形验证码',
    tech_plan: LARK_MD_TECH_PLAN,
    affected_files: [{ file_path: 'src/components/LoginForm.vue', change_type: 'modify' }],
    recommended_repository_ids: ['r-in', 'r-out'],
    recommended_repositories: [
      { id: 'r-in', name: 'onion-web' },
      { id: 'r-out', name: 'sso-gateway' },
    ],
    provenance: 'draft',
    schema_version: '',
    blueprint_artifact_id: '',
    current_status: '',
    ...overrides,
  }
}

// ---------------------------------------------------------------------------
// 仓库路由权重配置
// 形状出处：`codegraph.services.repo_router_config.DEFAULT_WEIGHT_CONFIG`（实跑导出）。
// ---------------------------------------------------------------------------

export function weightConfig(overrides: Record<string, unknown> = {}) {
  return {
    weight_set_version: 'phase106-v2',
    weights: { text: 0.55, domain: 0.15, activity: 0.12, stack: 0.08, team: 0.05 },
    constants: {
      p: 2.0,
      b: 0.6,
      n_cap: 6.0,
      lam: 0.25,
      n_bar: null,
      half_life_days: 180.0,
      offset_days: 14.0,
      activity_floor: 0.05,
      deprecated_cap: 0.1,
      s_top_c_lo: 0.25,
      s_top_c_hi: 0.55,
      t2_c_lo: 0.25,
      t2_c_hi: 0.55,
      crit_band: 0.03,
    },
    criticality_anchors: { 核心: 1.0, 重要: 0.7, 一般: 0.4, 边缘: 0.15 },
    crit_weight_reserved: 0.05,
    t2_disabled_facets: [] as string[],
    embedding_model_id: null,
    calibrated_at: null,
    is_default: true,
    ...overrides,
  }
}

/** 服务端 400 的真实响应体（`RepoRouterWeightConfigView.put`）。 */
export function weightConfigRejection(errors: string[]) {
  return { detail: '权重配置校验失败', errors }
}
