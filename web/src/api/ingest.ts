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

export const ingestApi = {
  /** 派发后台摄取（202 + run_id），后台执行三步编排。 */
  dispatch: (boardUrl: string, mrUrl: string): Promise<IngestDispatch> =>
    post<IngestDispatch>('/delivery/ingest/', { board_url: boardUrl, mr_url: mrUrl }),

  /** 拉取某次摄取运行的真实步骤结果。 */
  getRun: (runId: string): Promise<IngestRun> =>
    get<IngestRun>(`/delivery/ingest/${runId}/`),
}
