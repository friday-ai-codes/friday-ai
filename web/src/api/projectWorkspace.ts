/**
 * 项目工作区 API（v0.16.0 Phase 84）。
 *
 * 封装 Phase 84-01 新增的工作区 REST 端点：单文档正文 + block 分区读取、人工区写回
 * （经 Phase 83 DocSyncService block 级回灌）、feature list 树 + 进度灯、work-items 含状态、
 * StateApi 清单维护、项目基础搜索；并复用 Phase 82 已有的 docs 列表 / 重建工作区端点。
 *
 * ── 契约单一来源（与 84-01 serializer snake_case wire 字段严格对齐，禁止前端改名）──
 *   ProjectDoc（list）      : id, project_id, doc_type, feishu_document_id, feishu_doc_token,
 *                            sync_status, last_synced_revision, created_at, updated_at
 *   ProjectDocContent（GET）: doc_type, sync_status, last_synced_revision, rendered_markdown,
 *                            blocks:[{ block_id, db_ref, section, text, editable }]
 *   ProjectStateApi        : id, project_id, method, path, params, status, source,
 *                            created_at, updated_at
 *   work-item（含状态）     : status_state_key, status_display_name, module_normalized（叠加于 ProjectWorkItem）
 *   feature node           : module → 功能点 → 验收项（kind/name/children），功能点带 state 四态灯
 *   search result          : locator（属哪个 repo/project）
 *
 * 字段漂移由守护测试无法捕获（mock 隔离后端），故以此清单为前后端共同基准。
 */

import { del, get, patch, post, put } from './client'

/** 工作区文件类型（闭集，对齐 84-01 doc_type 校验）。 */
export type ProjectDocType = 'memory' | 'state' | 'milestones' | 'research' | 'preflight'

/** 文档同步状态（对齐后端 ProjectDoc.sync_status）。 */
export type DocSyncStatus = 'idle' | 'syncing' | 'synced' | 'error' | string

/** block 分区（system=系统区只读 / human=人工区可编辑）。 */
export type DocSection = 'system' | 'human'

/** 工作区文件容器（列表项，DOC-01~05）。 */
export interface ProjectDoc {
  id: string
  project_id: string
  doc_type: ProjectDocType
  feishu_document_id: string
  feishu_doc_token: string
  sync_status: DocSyncStatus
  last_synced_revision: number | null
  created_at: string
  updated_at: string
}

/** 单文档 block（系统区/人工区分区，84-01 ProjectDocContentSerializer）。 */
export interface DocBlock {
  block_id: string
  db_ref: string
  section: DocSection
  text: string
  editable: boolean
}

/** 单文档渲染内容 + block 列表（84-01 GET docs/<doc_type>/）。 */
export interface ProjectDocContent {
  doc_type: ProjectDocType
  sync_status: DocSyncStatus
  last_synced_revision: number | null
  rendered_markdown: string
  blocks: DocBlock[]
}

/** 人工区写回单元（仅 section==human 的 block 可写）。 */
export interface HumanBlockWrite {
  block_id: string
  text: string
}

/** 结构化 API 清单条目状态（对齐后端 ApiStatus）。 */
export type StateApiStatus = 'planned' | 'in_progress' | 'done' | string

/** 项目结构化 API 清单条目（DOC-02）。 */
export interface StateApi {
  id: string
  project_id: string
  method: string
  path: string
  params: Record<string, unknown>
  status: StateApiStatus
  source: string
  created_at: string
  updated_at: string
}

/** 新增/更新 StateApi 请求体。 */
export interface StateApiInput {
  method?: string
  path?: string
  params?: Record<string, unknown>
  status?: StateApiStatus
}

/** feature 节点种类（模块 → 功能点 → 验收项）。 */
export type FeatureNodeKind = 'module' | 'feature' | 'acceptance'

/** feature 功能点进度四态灯（对齐 84-01 WorkItem 状态映射）。 */
export type FeatureState = 'todo' | 'in_progress' | 'testing' | 'done'

/** feature list 树节点（WB-02，84-01 ProjectFeatureNodeSerializer）。 */
export interface FeatureNode {
  kind: FeatureNodeKind
  name: string
  /** 功能点节点带四态灯；模块/验收项可为空。 */
  state?: FeatureState
  /** 关联 WorkItem 状态镜像（功能点节点）。 */
  status_state_key?: string
  status_display_name?: string
  module_normalized?: string
  children?: FeatureNode[]
}

/** 含 WorkItem 状态的工作项（84-01 扩展 ProjectWorkItemListView）。 */
export interface ProjectWorkItemWithStatus {
  id: string
  feishu_work_item_id: number
  work_item_type: string
  title: string
  feishu_project_key: string
  provenance: string
  attached_at: string
  status_state_key: string
  status_display_name: string
  module_normalized: string
}

/** 手动录入的 feature 功能点（含可选验收项 + 状态）。 */
export interface FeatureListFeatureInput {
  name: string
  acceptance?: string[]
  status?: string
}

/** 手动录入的模块（含功能点）。 */
export interface FeatureListModuleInput {
  module: string
  features: FeatureListFeatureInput[]
}

/**
 * 设置 feature list（#4/#5 录入方式）：
 * - mode='manual'：手动录入模块/功能点/验收项（落 markdown 载体工件，可全文 RAG）。
 * - mode='feishu'：贴飞书多维表格链接（落 feishu_bitable 载体，经同步拉取）。
 * - mode='gitlab'：GitLab 文件链接（全局凭证鉴权取文 + AI 逐字解析结构）。
 * - mode='paste'：粘贴整篇文档（AI 逐字解析结构，内容保留原文）。
 */
export type FeatureListInput
  = | { mode: 'manual', modules: FeatureListModuleInput[], title?: string }
    | { mode: 'feishu', url: string, title?: string }
    | { mode: 'gitlab', url: string, title?: string }
    | { mode: 'paste', text: string, title?: string }

/** 项目搜索结果项（WB-05，84-01 ProjectSearchResultSerializer）。 */
export interface SearchResult {
  /** 命中内容片段。 */
  text: string
  /** 召回分数（可选）。 */
  score?: number
  /** 来源定位：属哪个 repo/project。 */
  locator: string
  [k: string]: unknown
}

export const projectWorkspaceApi = {
  /** 工作区文件容器列表（Phase 82 既有端点）。 */
  listDocs: (projectId: string): Promise<ProjectDoc[]> =>
    get<ProjectDoc[]>(`/projects/${projectId}/workspace/docs/`),

  /** 单文档渲染内容 + block 分区（WB-03）。 */
  getDocContent: (projectId: string, docType: ProjectDocType): Promise<ProjectDocContent> =>
    get<ProjectDocContent>(`/projects/${projectId}/workspace/docs/${docType}/`),

  /** 人工区写回（触发同步引擎 block 级回灌；仅项目成员）。 */
  updateHumanBlocks: (
    projectId: string,
    docType: ProjectDocType,
    blocks: HumanBlockWrite[],
  ): Promise<ProjectDocContent> =>
    put<ProjectDocContent>(
      `/projects/${projectId}/workspace/docs/${docType}/human-blocks/`,
      { blocks },
    ),

  /** 重建工作区（Phase 82 既有端点，派发→轮询 sync_status）。 */
  rebuildWorkspace: (projectId: string): Promise<{ rebuilt: boolean }> =>
    post(`/projects/${projectId}/workspace/rebuild/`, {}),

  /** 结构化 API 清单（DOC-02）。 */
  listStateApis: (projectId: string): Promise<StateApi[]> =>
    get<StateApi[]>(`/projects/${projectId}/workspace/state-apis/`),

  /** 新增结构化 API 清单条目。 */
  upsertStateApi: (projectId: string, data: StateApiInput): Promise<StateApi> =>
    post<StateApi>(`/projects/${projectId}/workspace/state-apis/`, data),

  /** 更新结构化 API 清单单条字段（84-01 新增 PATCH）。 */
  patchStateApi: (projectId: string, apiId: string, data: StateApiInput): Promise<StateApi> =>
    patch<StateApi>(`/projects/${projectId}/workspace/state-apis/${apiId}/`, data),

  /** 删除结构化 API 清单条目。 */
  deleteStateApi: (projectId: string, apiId: string): Promise<void> =>
    del(`/projects/${projectId}/workspace/state-apis/${apiId}/`),

  /** feature list 树 + 进度灯（WB-02）。 */
  getFeatureList: (projectId: string): Promise<FeatureNode[]> =>
    get<FeatureNode[]>(`/projects/${projectId}/feature-list/`),

  /** 设置/更新 feature list（#5 手动录入 或 飞书链接；仅项目成员）。 */
  setFeatureList: (projectId: string, data: FeatureListInput): Promise<{ ok: boolean }> =>
    post<{ ok: boolean }>(`/projects/${projectId}/feature-list/`, data),

  /** 项目工作项列表（含 WorkItem 状态字段，WB-02）。 */
  listWorkItems: (projectId: string): Promise<ProjectWorkItemWithStatus[]> =>
    get<ProjectWorkItemWithStatus[]>(`/projects/${projectId}/work-items/`),

  /** 项目基础模糊搜索（WB-05；深度项目域 RAG 留 Phase 85）。 */
  search: (projectId: string, q: string): Promise<SearchResult[]> =>
    get<SearchResult[]>(`/projects/${projectId}/search/`, { q }),
}

export default projectWorkspaceApi
