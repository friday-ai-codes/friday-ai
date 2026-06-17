/**
 * 上线文档（飞书 Bitable）同步 API。
 *
 * 两段式：`preview` 只读分页拉取并解析上线行（队列预览，不入库）；`sync` 把勾选的
 * 行批量派发后台入库（Release 账本 + MR diff 入知识库）。同步进度复用
 * `ingestApi.getBatch(batch_id)`（返回各 run 的 `release` / `mr_diff` 两步状态）。
 */

import { post } from './client'

/** 单行解析后的上线记录（与后端 `ReleaseRowPreview` 对齐）。 */
export interface ReleaseBitableRow {
  record_id: string
  business: string
  mr_url: string
  kanban_id: number | null
  /** 看板 id 来源：'看板id' 列 或 'feature分支'。 */
  kanban_source: string
  category: string
  /** 上线日期（ms epoch）。 */
  release_date: number | null
  feature_branch: string
  /** MR 是否命中已落库仓库。 */
  repo_matched: boolean
  repo_name: string
  /** 是否可入库（有 MR 且命中仓库）。 */
  ingestable: boolean
  raw_fields: Record<string, any>
}

/** 预览分页响应。 */
export interface ReleaseBitablePreview {
  rows: ReleaseBitableRow[]
  page_token: string | null
  has_more: boolean
  total: number | null
}

/** 批量同步派发响应（202）。 */
export interface ReleaseBitableSyncDispatch {
  batch_id: string
  runs: Array<{
    run_id: string
    record_id: string
    business: string
    mr_url: string
    kanban_id: number | null
  }>
}

export interface ReleaseBitablePreviewParams {
  app_token?: string
  table_id?: string
  page_token?: string
  page_size?: number
}

export const releaseBitableApi = {
  /** 分页拉取并解析上线文档行（只读，不入库）。 */
  preview: (params: ReleaseBitablePreviewParams = {}): Promise<ReleaseBitablePreview> =>
    post<ReleaseBitablePreview>('/delivery/release/bitable/preview/', params),

  /** 批量同步勾选的上线行（202 + batch_id），进度经 ingestApi.getBatch 轮询。 */
  sync: (
    rows: ReleaseBitableRow[],
    opts: { app_token?: string, table_id?: string } = {},
  ): Promise<ReleaseBitableSyncDispatch> =>
    post<ReleaseBitableSyncDispatch>('/delivery/release/bitable/sync/', { ...opts, rows }),
}
