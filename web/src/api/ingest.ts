/**
 * 一键摄取 API（Phase 32 one-click-ingest，ING-01）。
 *
 * 编排既有能力：给定 (看板/工作项 URL, MR URL)，后端串联三步 best-effort 摄取
 * （工作项 upsert / PRD·技术方案文档 + REFERENCES / MR diff 归档入图）并入库可检索。
 *
 * 派发→轮询范式（沿用 `reconcile.ts`）：`dispatch` 立即返回 `run_id`（202 后台执行），
 * 前端经 `getRun` 拉取真实步骤结果；`status==='running'` 持续 2s 轮询，completed/failed 停轮。
 * 字段名与 32-02 后端 `IngestRunSerializer` 严格对齐。
 */

import { get, post } from './client'

/** 单步状态：成功 / 失败 / 跳过（解析不出或不适用）/ 等待中（尚未执行）。 */
export type StepStatus = 'ok' | 'failed' | 'skipped' | 'pending'

/** Run 整体状态：运行中 / 已完成（含部分成功）/ 编排级失败。 */
export type RunStatus = 'running' | 'completed' | 'failed'

/** 单步结果（形状对齐后端 `default_steps`）。 */
export interface IngestStep {
  status: StepStatus
  /** work_item id / document id / archive id（后端已脱敏文本）。 */
  identifier?: string
  /** 可选外链（飞书 / MR / 知识实体详情）。 */
  link?: string
  /** failed/skipped 时的原因（后端已脱敏）。 */
  error?: string
}

/** 一次摄取运行记录（与后端 `IngestRunSerializer` 对齐）。 */
export interface IngestRun {
  run_id: string
  status: RunStatus
  steps: {
    work_item: IngestStep
    document: IngestStep
    mr_diff: IngestStep
  }
  started_at?: string
  completed_at?: string | null
}

/** POST `/delivery/ingest/` 派发的即时响应（202）。 */
export interface IngestDispatch {
  run_id: string
  dispatched: boolean
}

/** 批量摄取一组 (看板, MR) 输入。 */
export interface IngestBatchItem {
  board_url: string
  mr_url: string
}

/** POST `/delivery/ingest/batch/` 派发的即时响应（202）。 */
export interface IngestBatchDispatch {
  batch_id: string
  runs: Array<{ run_id: string, board_url: string, mr_url: string }>
}

/** 批量摄取中单条 run 的状态（含原始 URL 供对应展示）。 */
export interface IngestBatchRun extends IngestRun {
  board_url: string
  mr_url: string
}

/** 批量摄取聚合状态（任一 run running 则批 running，否则 completed）。 */
export interface IngestBatchStatus {
  batch_id: string
  status: 'running' | 'completed'
  runs: IngestBatchRun[]
}

// ============================================================================
// JSON 批量摄取（空间 + 工作项 id + 可选类型/ MR）
// ============================================================================

/** JSON 导入的单条原始输入（空间可写 名/系统 id/飞书 key；类型/ MR 可选）。 */
export interface JsonIngestItem {
  space: string
  work_item_id: number | string
  work_item_type?: string
  mr_url?: string
}

/** 后端逐项解析结果（resolve 预览 / 编辑列表用）。 */
export interface ResolvedJsonItem {
  space: string
  space_id: string
  space_name: string
  feishu_project_key: string
  work_item_id: number
  work_item_type: string
  mr_url: string
  board_url: string
  match_reason: string
  resolved: boolean
  error: string
}

/** JSON 批量摄取派发的单条 run（带回工作项三元组供拉关联文档）。 */
export interface JsonIngestBatchRun {
  run_id: string
  feishu_project_key: string
  work_item_type: string
  work_item_id: number
  mr_url: string
  board_url: string
  space_name: string
}

/** POST `/delivery/ingest/batch-json/` 派发响应（202）。 */
export interface JsonIngestBatchDispatch {
  batch_id: string
  runs: JsonIngestBatchRun[]
  skipped: Array<{ space: string, work_item_id: number, error: string }>
}

/** 工作项关联文档（单条）。 */
export interface WorkItemArtifactDocument {
  document_type: string
  canonical_url: string
  external_ref: string
  version: number | null
  has_content: boolean
  last_synced_at: string | null
}

// ============================================================================
// URL 爬取（飞书文档 / 多维表格 / wiki / 通用链接 → AI 抽成可关联条目）
// ============================================================================

/** 爬取结果状态。 */
export type CrawlStatus = 'ok' | 'feishu_not_configured' | 'empty' | 'error'

/** 爬取出的单条原始条目（形状与 JsonIngestItem 对齐，可直接喂 resolve）。 */
export interface CrawlItem {
  space: string
  work_item_id: number
  work_item_type: string
  mr_url: string
}

/** POST `/delivery/ingest/crawl/` 响应。 */
export interface CrawlResult {
  status: CrawlStatus
  /** 来源类型：feishu_doc / feishu_bitable / feishu_wiki / generic。 */
  source_kind: string
  items: CrawlItem[]
  /** 人类可读提示（empty/error/feishu_not_configured 时展示）。 */
  message: string
  /** feishu_not_configured 时的系统设置深链（如 `/admin#integration`）。 */
  settings_deeplink: string
}

/** 工作项摘要 + 关联文档列表（GET `/delivery/work-items/artifacts/`）。 */
export interface WorkItemArtifacts {
  work_item: {
    id: string
    title: string
    status_display_name: string
    prd_url: string
    tech_doc_url: string
  }
  documents: WorkItemArtifactDocument[]
}

export const ingestApi = {
  /** 派发后台摄取（202 + run_id），后台执行三步编排。 */
  dispatch: (boardUrl: string, mrUrl: string): Promise<IngestDispatch> =>
    post<IngestDispatch>('/delivery/ingest/', { board_url: boardUrl, mr_url: mrUrl }),

  /** 拉取某次摄取运行的真实步骤结果。 */
  getRun: (runId: string): Promise<IngestRun> =>
    get<IngestRun>(`/delivery/ingest/${runId}/`),

  /** 批量派发后台摄取（202 + batch_id + runs），各组共享 batch_id 独立编排。 */
  dispatchBatch: (items: IngestBatchItem[]): Promise<IngestBatchDispatch> =>
    post<IngestBatchDispatch>('/delivery/ingest/batch/', { items }),

  /** 拉取整批摄取的聚合状态与各 run 真实步骤结果。 */
  getBatch: (batchId: string): Promise<IngestBatchStatus> =>
    get<IngestBatchStatus>(`/delivery/ingest/batch/${batchId}/`),

  /** 解析预览 JSON 导入项（逐项空间解析 + 校验，不落库）。 */
  resolveItems: (items: JsonIngestItem[]): Promise<{ items: ResolvedJsonItem[] }> =>
    post<{ items: ResolvedJsonItem[] }>('/delivery/ingest/resolve/', { items }),

  /** 爬取一个 URL（飞书文档/多维表格/wiki/通用链接）→ AI 抽成可关联条目。 */
  crawlUrl: (url: string): Promise<CrawlResult> =>
    post<CrawlResult>('/delivery/ingest/crawl/', { url }),

  /** 派发 JSON 批量摄取（可解析项建 run + 有界并发；不可解析项 skipped 回报）。 */
  dispatchJsonBatch: (
    items: JsonIngestItem[],
    concurrency: number,
  ): Promise<JsonIngestBatchDispatch> =>
    post<JsonIngestBatchDispatch>('/delivery/ingest/batch-json/', { items, concurrency }),

  /** 按三元组拉取工作项摘要 + 关联文档（PRD/技术方案等）。 */
  getWorkItemArtifacts: (
    feishuProjectKey: string,
    workItemType: string,
    workItemId: number,
  ): Promise<WorkItemArtifacts> =>
    get<WorkItemArtifacts>('/delivery/work-items/artifacts/', {
      feishu_project_key: feishuProjectKey,
      work_item_type: workItemType,
      work_item_id: workItemId,
    }),
}
