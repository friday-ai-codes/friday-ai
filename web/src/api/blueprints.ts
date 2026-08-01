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
 * ⛔ **不封装人审那个「块级批量改写」端点**：本相位无 block 正文编辑面（顺延 116），零调用点。
 *
 * 观测：全部端点后端侧已记 caller 事件（含 GET —— 谁读过哪份蓝图必须有痕），前端不重复上报；
 * ⛔ 任何调用点不得把蓝图正文 / 批注正文 / citation quote 写进 `console` 或埋点。
 */

import type {
  BlueprintAnswerResponse,
  BlueprintApproveResponse,
  BlueprintBoundaryDraftResult,
  BlueprintDocumentResponse,
  BlueprintEventsResponse,
  BlueprintFindingActionResponse,
  BlueprintGateActionResult,
  BlueprintGateSnapshot,
  BlueprintListResponse,
  BlueprintRejectResponse,
  BlueprintReviewSnapshot,
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

/** 取蓝图阶段事件流（无编排会话时是 200 空结构，⛔ 不是错误态）。 */
export async function getBlueprintEvents(artifactId: string): Promise<BlueprintEventsResponse> {
  return get<BlueprintEventsResponse>(`/delivery/artifacts/${artifactId}/blueprint/events/`)
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

/** 人审驳回（`comment` 是驳回理由，必填由 UI 层保证；成功后先落新版本再转状态）。 */
export async function rejectBlueprint(
  artifactId: string,
  payload: { comment?: string, anchor?: Record<string, unknown> } = {},
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
  getBlueprintThreads,
  createBlueprintComment,
  listBlueprints,
  getBlueprintReviewSnapshot,
  approveBlueprint,
  rejectBlueprint,
  answerThread,
  resolveFinding,
  dismissFinding,
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
