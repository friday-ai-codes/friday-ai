/**
 * 技术蓝图 API（Phase 115，只读供数面 + 人审 / 确认门动作）。
 *
 * 对接后端 `server/delivery/api/blueprint_doc_views.py`（正文 / 阶段事件 / 线程详情
 * GET+POST）、`blueprint_list_views.py`（列表）、`blueprint_review_views.py`（人审快照 +
 * 六动作）、`blueprint_gate_views.py`（确认门快照 + 七动作）。
 *
 * **易混淆对象辨析**：
 * - `~/api/deliveryArtifacts` 是**通用 artifact 面**（含旧 `technical_plan`），本模块只覆盖
 *   `blueprint_status != ''` 的蓝图；版本轨继续用它的 `getArtifactTimeline`，⛔ 本模块
 *   **不 re-export** 该函数（同一端点两个入口只会让 queryKey 与失效面漂移）。
 * - `~/api/artifacts` 是 initiatives 的**项目工件**，与 `delivery.Artifact` 不是同一实体，勿混用。
 *
 * ⛔ **本模块不封装 `~/api/knowledge` 里那两个「反向关联」查询**（P-5）：它们查的是
 * `initiatives.Artifact` 投影出来的 KnowledgeEntity，而蓝图活在 `delivery.Artifact` ⇒ 拿蓝图的
 * artifact id 去调**必然 404 或空**。「引用了本蓝图 / 关联知识」这半个能力本相位**范围收窄**，
 * 顺延 Phase 116 的知识图谱物化；本相位的「关联」段只做「本蓝图引用了」+「关联项目」。
 *
 * ⭐ **块级人工改写端点已封装**（`editBlueprintBlocks`，CLAR-03 闭环相位补入）：查看器的
 * block 编辑面经它落 `human_edit:{user_id}` 版本。115 当初把它排除在外是因为该相位不做正文
 * 编辑面；那条顺延现已兑现，说明见 `.planning/v0.20.0-MILESTONE-AUDIT.md`「CLAR-03 闭环」。
 *
 * 观测：全部端点后端侧已记 caller 事件（含 GET —— 谁读过哪份蓝图必须有痕），前端不重复上报；
 * ⛔ 任何调用点不得把蓝图正文 / 批注正文 / citation quote 写进 `console` 或埋点。
 */

import type {
  BlueprintAnswerResponse,
  BlueprintApproveResponse,
  BlueprintBlockEditResponse,
  BlueprintBlockOp,
  BlueprintBoundaryDraftResult,
  BlueprintDocumentResponse,
  BlueprintEventsResponse,
  BlueprintFindingActionResponse,
  BlueprintGateActionResult,
  BlueprintGateSnapshot,
  BlueprintListResponse,
  BlueprintRejectResponse,
  BlueprintResearchDetailResponse,
  BlueprintReviewSnapshot,
  BlueprintStageRerunResponse,
  BlueprintStagesResponse,
  BlueprintThreadsResponse,
  CreateBlueprintCommentPayload,
  CreateBlueprintCommentResponse,
  ListBlueprintsParams,
} from '~/types/blueprint'
import { get, post } from './client'

// ── ① 正文（含 quality 四项）────────────────────────────────────────────────

/** 取蓝图正文；`version_id` 缺省取当前版本，带上则取历史版本（只读模式）。 */
export async function getBlueprintDocument(
  artifactId: string,
  params: { version_id?: string } = {},
): Promise<BlueprintDocumentResponse> {
  const query: Record<string, string> = {}
  if (params.version_id)
    query.version_id = params.version_id
  return get<BlueprintDocumentResponse>(`/delivery/artifacts/${artifactId}/blueprint/`, query)
}

// ── ② 阶段事件 ──────────────────────────────────────────────────────────────

/**
 * 取蓝图阶段与活动事件流（无编排会话时是 200 空结构，⛔ 不是错误态）。
 *
 * `since_ts`（Phase 118）是**增量拉取**：只回该时刻之后的事件。活动级事件让单次编排的
 * 事件量上一个量级，而消费方是每几秒轮询的查看器 —— 不增量就是每轮把整条历史重传一遍。
 * 后端对非法 `since_ts` 回落全量（纯优化参数，不因坏时间戳把看进度打成错误页）。
 */
export async function getBlueprintEvents(
  artifactId: string,
  params: { since_ts?: string, limit?: number } = {},
): Promise<BlueprintEventsResponse> {
  const query: Record<string, string> = {}
  if (params.since_ts)
    query.since_ts = params.since_ts
  if (params.limit)
    query.limit = String(params.limit)
  return get<BlueprintEventsResponse>(
    `/delivery/artifacts/${artifactId}/blueprint/events/`,
    query,
  )
}

/**
 * 取按仓的调研结论与 agent 过程明细（无编排会话时是 200 空结构，⛔ 不是错误态）。
 *
 * 与 `getBlueprintEvents` 的分工：事件流是**阶段级标量**（`findings_count` / `verdict`），
 * 本端点是**过程与结论正文**（agent 调了哪些工具、读回什么、每仓得出哪些 findings）。
 * 载荷比事件流重得多 ⇒ ⛔ 不进 5s 轮询，只在抽屉打开时按需取。
 */
export async function getBlueprintResearchDetail(
  artifactId: string,
  params: { log_limit?: number } = {},
): Promise<BlueprintResearchDetailResponse> {
  const query: Record<string, string> = {}
  if (params.log_limit)
    query.log_limit = String(params.log_limit)
  return get<BlueprintResearchDetailResponse>(
    `/delivery/artifacts/${artifactId}/blueprint/research-detail/`,
    query,
  )
}

// ── 节点面：stages GET + 带指令重跑 POST（quick-260806 节点重跑）───────────────

/**
 * 取按 stage 聚合的节点快照（stage_state 分片 + 重跑标记/历史 + 版本谱系）。
 *
 * ⭐ 无会话时是 200 空结构（`session_id: ''`、各 `state` 为 `{}`），`versions` 仍有效，
 * ⛔ 不是错误态 —— 与 `getBlueprintEvents` 同款语义。
 */
export async function getBlueprintStages(artifactId: string): Promise<BlueprintStagesResponse> {
  return get<BlueprintStagesResponse>(`/delivery/artifacts/${artifactId}/blueprint/stages/`)
}

/**
 * 带操作员指令重跑某个 stage。
 *
 * 状态码分档：**200** `status: accepted`（响应带新 `run_label`）；**400** 非法 stage / 无会话；
 * **409** 并发冲突（会话仍在跑）。400 / 409 一律经 `ApiError.detail` 原样回显。
 * ⚠️ `stage` 收的是**后端 stage key**（UI 节点 `confirmation` 需先映射成 `repo_confirmation`）。
 */
export async function rerunBlueprintStage(
  artifactId: string,
  payload: { stage: string, instruction?: string },
): Promise<BlueprintStageRerunResponse> {
  return post<BlueprintStageRerunResponse>(
    `/delivery/artifacts/${artifactId}/blueprint/stages/rerun/`,
    payload,
  )
}

// ── ③④ 线程详情 + 选区评论 ─────────────────────────────────────────────────

/** 取线程详情（含 `options` 与多轮 `messages`，快照面不带这两者）。 */
export async function getBlueprintThreads(artifactId: string): Promise<BlueprintThreadsResponse> {
  return get<BlueprintThreadsResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/threads/`,
  )
}

/** 针对选中片段发起评论（后端一律建 `human_comment` 且 `blocking=false`，评论不钉死蓝图）。 */
export async function createBlueprintComment(
  artifactId: string,
  payload: CreateBlueprintCommentPayload,
): Promise<CreateBlueprintCommentResponse> {
  return post<CreateBlueprintCommentResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/threads/`,
    payload,
  )
}

// ── ⑤ 列表 ──────────────────────────────────────────────────────────────────

/**
 * 列成员可见的蓝图（筛选 + 五键分页）。
 *
 * ⚠️ query 参数名保留字面 `blueprint_status`（那是后端的参数名），但**响应项的状态键是
 * `current_status`** —— 两者刻意不同名，见 `~/types/blueprint` 的说明。
 */
export async function listBlueprints(
  params: ListBlueprintsParams = {},
): Promise<BlueprintListResponse> {
  const query: Record<string, string> = {}
  if (params.project_id)
    query.project_id = params.project_id
  if (params.blueprint_status)
    query.blueprint_status = params.blueprint_status
  if (params.repository_id)
    query.repository_id = params.repository_id
  if (params.q)
    query.q = params.q
  if (params.page)
    query.page = String(params.page)
  if (params.page_size)
    query.page_size = String(params.page_size)
  return get<BlueprintListResponse>('/delivery/blueprints/', query)
}

// ── 人审面（复用 114-05 的七端点，本相位调六个）──────────────────────────────

/** 取人审只读快照（findings 三级分组 / 澄清 / 评论 / 失锚 / 未决阻塞清单）。 */
export async function getBlueprintReviewSnapshot(
  artifactId: string,
): Promise<BlueprintReviewSnapshot> {
  return get<BlueprintReviewSnapshot>(`/delivery/artifacts/${artifactId}/blueprint-review/`)
}

/** 人审通过（存在未决 BLOCKER finding 时 409，响应体带可点清单）。 */
export async function approveBlueprint(artifactId: string): Promise<BlueprintApproveResponse> {
  return post<BlueprintApproveResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/approve/`,
  )
}

/**
 * 人审驳回（`comment` 是驳回理由，必填由 UI 层保证；成功后先落新版本再转状态）。
 *
 * `rework_scope`（Phase 120）决定这次打回重跑到哪一步；不传由后端回落 `merge`（改动前的
 * 唯一路径）。`rework_repository_ids` 仅 `repos` 范围有意义。
 */
export async function rejectBlueprint(
  artifactId: string,
  payload: {
    comment?: string
    anchor?: Record<string, unknown>
    rework_scope?: string
    rework_repository_ids?: string[]
  } = {},
): Promise<BlueprintRejectResponse> {
  return post<BlueprintRejectResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/reject/`,
    payload,
  )
}

/** 回复澄清 / 评论线程（端点**恒 200**，`reflow.status` 只决定 toast 语气，⛔ 不当失败）。 */
export async function answerThread(
  artifactId: string,
  threadId: string,
  payload: { body: string },
): Promise<BlueprintAnswerResponse> {
  return post<BlueprintAnswerResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/threads/${threadId}/answer/`,
    payload,
  )
}

/** 处置审查发现为「已修复」（`reason` 必填；⛔ finding 走 answer 通道一律 400）。 */
export async function resolveFinding(
  artifactId: string,
  threadId: string,
  payload: { reason: string },
): Promise<BlueprintFindingActionResponse> {
  return post<BlueprintFindingActionResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/threads/${threadId}/resolve/`,
    payload,
  )
}

/** 处置审查发现为「误报忽略」（`reason` 必填）。 */
export async function dismissFinding(
  artifactId: string,
  threadId: string,
  payload: { reason: string },
): Promise<BlueprintFindingActionResponse> {
  return post<BlueprintFindingActionResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/threads/${threadId}/dismiss/`,
    payload,
  )
}

/**
 * 人工直接改写 block 正文（CLAR-03）。
 *
 * ⭐ **归属可审计**：成功版本的 `produced_by_ref == "human_edit:{user_id}"`，这是全仓唯一
 * 的「这一版是人写的」通道（`ArtifactVersion` 无 `created_by_user_id`），也是 AI 侧
 * `arestore_human_blocks` 人工块保护集的判据源 —— 换句话说，**经本函数落的版本才受
 * 「AI 不得覆盖人工」那条保护链庇护**。
 *
 * 状态码分档：
 * - **200** `status ∈ {applied, unchanged}` —— 前者已落新版本并重锚定，后者同 content_hash
 *   未翻版本（重放安全，⛔ 不是失败）。
 * - **400** `status ∈ {rejected, invalid}` —— 载荷结构性不可应用 / 编辑后不过 schema /
 *   蓝图当前状态不在可编辑白名单。三者**都不落版本**；`ApiError.body.rejected` 逐条给出
 *   `reason`，其中 `block_not_found` 意味着基线已被推进（并发冲突），解药是刷新重来。
 */
export async function editBlueprintBlocks(
  artifactId: string,
  payload: { ops: BlueprintBlockOp[] },
): Promise<BlueprintBlockEditResponse> {
  return post<BlueprintBlockEditResponse>(
    `/delivery/artifacts/${artifactId}/blueprint-review/edit-blocks/`,
    payload,
  )
}

// ── 确认门（复用 112-05 的八端点）────────────────────────────────────────────

/**
 * 取确认门只读快照。
 *
 * ⚠️ **该端点的 404 是正常态**（「确认门未开启」）：调用方一律「非 200 ⇒ 不渲染 gate 面板」，
 * ⛔ 不进 404 全页空态分档、不弹 toast、不读 `detail` 文本分支。
 */
export async function getBlueprintGate(artifactId: string): Promise<BlueprintGateSnapshot> {
  return get<BlueprintGateSnapshot>(`/delivery/artifacts/${artifactId}/blueprint-gate/`)
}

/** 确认锁定仓库集与职责（存在未决阻塞澄清 / 内容校验未过 → 409）。 */
export async function confirmGate(artifactId: string): Promise<BlueprintGateActionResult> {
  return post<BlueprintGateActionResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/confirm/`,
  )
}

/** 从方案中移除某仓（只收窄仓库集，既有结论不失效 ⇒ 不触发重调研）。 */
export async function removeRepo(
  artifactId: string,
  payload: { repository_id: string },
): Promise<BlueprintGateActionResult> {
  return post<BlueprintGateActionResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/remove-repo/`,
    payload,
  )
}

/** 手动加仓（新仓无任何 fitness ⇒ **必然**触发该仓调研）。 */
export async function addRepo(
  artifactId: string,
  payload: { repository_id: string, role?: string, responsibility?: string },
): Promise<BlueprintGateActionResult> {
  return post<BlueprintGateActionResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/add-repo/`,
    payload,
  )
}

/** 改判仓库角色（仅 `indirect → direct` 需要容器级 fitness ⇒ 触发重调研）。 */
export async function reclassifyRole(
  artifactId: string,
  payload: { repository_id: string, role: 'direct' | 'indirect' },
): Promise<BlueprintGateActionResult> {
  return post<BlueprintGateActionResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/reclassify-role/`,
    payload,
  )
}

/** 修改仓库职责（`rerun: true` 才触发重调研 —— 职责文本变化是否改变调研范围无法机械判定）。 */
export async function editResponsibility(
  artifactId: string,
  payload: { repository_id: string, responsibility: string, rerun?: boolean },
): Promise<BlueprintGateActionResult> {
  return post<BlueprintGateActionResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/edit-responsibility/`,
    payload,
  )
}

/**
 * 把 rejected 仓的路由理由一键沉淀为仓库章程的边界禁区草案。
 *
 * ⚠️ 项目范围**只由蓝图的 `meta.project_id` 决定**：body 里传 `project_id` 且与之不等 → 403。
 * 调用方一般只传 `repository_id` 作范围内收窄，⛔ 不要自行传 `project_id`。
 */
export async function rejectedToBoundary(
  artifactId: string,
  payload: { repository_id?: string } = {},
): Promise<BlueprintBoundaryDraftResult> {
  return post<BlueprintBoundaryDraftResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/rejected-to-boundary/`,
    payload,
  )
}

/** 把 indirect 仓升级为深调研（该仓调研本就在途时返回 `already_running: true`）。 */
export async function upgradeResearch(
  artifactId: string,
  payload: { repository_id: string },
): Promise<BlueprintGateActionResult> {
  return post<BlueprintGateActionResult>(
    `/delivery/artifacts/${artifactId}/blueprint-gate/upgrade-research/`,
    payload,
  )
}

/**
 * 飞书导出可用性探测（Phase 116-05，VIEW-05）。
 *
 * ⭐ **前端据 `available` 隐藏导出按钮**而不是点了才报错：三个 `reason`
 * （`no_space` / `no_folder_token` / `no_credentials`）只用于排障，⛔ 不做成文案分档。
 * ⚠️ 本查询的失败**不进错误分档**：它只决定按钮是否渲染，与页面权限判定无关。
 */
export async function getBlueprintExportAvailability(
  artifactId: string,
): Promise<{ available: boolean, reason: string | null }> {
  return get<{ available: boolean, reason: string | null }>(
    `/delivery/artifacts/${artifactId}/blueprint/export-feishu/availability/`,
  )
}

/**
 * 把蓝图导出为一篇飞书云文档（缺省导出最新一版）。
 *
 * 状态码分档：200 成功并给可点 `url`；400 配置/权限类（回显中性 `detail`）；
 * 502 上游不可用（提示稍后重试）。⛔ 后端绝不静默 200 空结构。
 */
export async function exportBlueprintToFeishu(
  artifactId: string,
  payload: { version_id?: string } = {},
): Promise<{ document_id: string, url: string, version_no: number, exported_at: string }> {
  return post<{ document_id: string, url: string, version_no: number, exported_at: string }>(
    `/delivery/artifacts/${artifactId}/blueprint/export-feishu/`,
    payload,
  )
}

export default {
  getBlueprintDocument,
  getBlueprintEvents,
  getBlueprintStages,
  rerunBlueprintStage,
  getBlueprintThreads,
  createBlueprintComment,
  listBlueprints,
  getBlueprintReviewSnapshot,
  approveBlueprint,
  rejectBlueprint,
  answerThread,
  resolveFinding,
  dismissFinding,
  editBlueprintBlocks,
  getBlueprintGate,
  confirmGate,
  removeRepo,
  addRepo,
  reclassifyRole,
  editResponsibility,
  rejectedToBoundary,
  upgradeResearch,
  getBlueprintExportAvailability,
  exportBlueprintToFeishu,
}
