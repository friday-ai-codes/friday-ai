/**
 * 仓库代码片段反查 + 仓库章程读取（Phase 115，引用二级预览用；仓内此前无前端封装）。
 *
 * 对接后端 `server/repositories/chunk_at_views.py`（`file:line → chunk` 反查）与
 * `server/repositories/charter_views.py`（章程读取）。
 *
 * **易混淆对象辨析**：`~/api/repositories` 是仓库 CRUD 与索引面，本模块只覆盖蓝图 citation
 * 预览需要的两个读面；`repository-code-search` 是**需要 query 的向量检索**，做不了「按 path +
 * 行区间取源码」，⛔ 不要拿它当代码预览的数据源。
 *
 * ⭐ **P-3 的可用判据封装在本模块，⛔ 调用点不各自判**：
 * 后端对「无命中」与「被排除文件」**统一返回 200 `{"chunks": []}`**（`chunk_at_views.py:60`，
 * 刻意不可区分的存在性防线）⇒ 判据必须是 `!ok || chunks.length === 0`，**绝不能是「非 2xx」**。
 * 且它的错误体键是 **`error`** 而不是 `detail`：`ApiError.detail` 在响应体无 `detail` 键时会
 * 回落成无意义的 `'请求失败'`（`client.ts:237,242`，⚠️ **不是空串** —— UI-SPEC §3.6/§10.1 的
 * 「空串」判据是错的）⇒ ⛔ 任何调用点都不得回显它。故本模块把两个函数都做成**不上抛**：
 * `getChunkAt` 一律返回 `{ chunks, usable }`，`getRepositoryCharter` 失败返回 `null`。
 *
 * ⭐ **代码正文来源的定夺（本 plan 拍板，订正 UI-SPEC §3.6/§10.1）**：`chunks[]` 每项只有
 * `{chunk_id, file_path, line_start, line_end, chunk_index}`，**没有代码正文**；全仓也没有
 * 「按 path + 行区间取源码」的读面，而 `components/execution/JsonViewer.vue` 的 docstring 自承
 * 是「替代那个代码编辑器内核的只读展示」——仓内根本没有该编辑器的只读封装。⇒
 * `CitationCodePreview` 本相位**降级为「文件路径 + 行号区间 + citation 自带的 quote 快照」**，
 * 用与 `pseudocode` 块同一套 `<pre class="font-mono">` + 行号渲染。⛔ 不引入任何代码编辑器
 * 内核、⛔ 不新增后端端点——那个读面超出本相位「只加读面」的边界，归属 Phase 116。
 *
 * ⭐ **Phase 116-07 后续（该顺延目标已兑现）**：上一段的结论对 115 相位仍然成立，但那个读面
 * 已由 116-07 补上 —— `getRepositoryFileLines`（`GET /repositories/<id>/file-lines/`）按
 * `path` + 行区间返回带行号的源码正文行，`CitationCodePreview` 据此升级为真正的代码预览
 * （正文 + 行高亮）。⛔ 仍然不引任何代码编辑器内核 / 高亮库：呈现沿用 115-03 已建的
 * `<pre class="font-mono">` + 行号列形态。
 */

import { get } from './client'

/** `chunk-at` 返回的单个 chunk 引用（⚠️ **不含代码正文**，只有定位信息）。 */
export interface RepoChunkRef {
  chunk_id: string
  file_path: string
  line_start: number
  line_end: number
  chunk_index: number
}

/**
 * `chunk-at` 的归一结果。
 *
 * `usable === false` 覆盖**全部**不可用情形：400（缺 `path` / `line` 非正整数）、404（仓不存在）、
 * 5xx、网络失败，以及**最容易漏的那一种** —— 200 但 `chunks` 为空（无命中或文件被排除规则挡掉，
 * 两者对外刻意不可区分）。调用方只看 `usable`，⛔ 不看状态码、不读错误体。
 */
export interface ChunkAtResult {
  chunks: RepoChunkRef[]
  usable: boolean
}

/** `charter` 返回的仓库章程（各 JSON 字段形状由 service 决定，逐键可选链）。 */
export interface RepoCharter {
  id: string
  repository: string
  version: number
  source: string
  confirmed_by: string | null
  positioning: string
  owned_domains: unknown
  boundaries: unknown
  placement_preferences: unknown
  audience: string
  form: string
  evolution: unknown
  /** pending 的 AI 修订草案（未确认生效）。 */
  draft_content: unknown
  created_at: string
  updated_at: string
}

/**
 * 按 `path:line` 反查覆盖该行的 chunk（最具体的区间在前）。
 *
 * ⚠️ 调用前应先确认 citation 的 `locator.line_start` 存在：后端 `path` 与 `line` **均为必填**，
 * 缺 `line` 会稳定 400 ⇒ 缺失时**直接走快照兜底、不发这次注定失败的请求**。
 *
 * 恒不抛：任何失败都归一成 `{ chunks: [], usable: false }`。
 */
export async function getChunkAt(
  repositoryId: string,
  params: { path: string, line: number, branch_name?: string },
): Promise<ChunkAtResult> {
  const query: Record<string, string> = { path: params.path, line: String(params.line) }
  if (params.branch_name)
    query.branch_name = params.branch_name
  try {
    const data = await get<{ path: string, line: number, chunks: RepoChunkRef[] }>(
      `/repositories/${repositoryId}/chunk-at/`,
      query,
    )
    const chunks = Array.isArray(data?.chunks) ? data.chunks : []
    // ⭐ 判据是「有没有命中」而不是「请求成不成功」：200 + 空 chunks 同样不可用。
    return { chunks, usable: chunks.length > 0 }
  }
  catch {
    // ⛔ 不回显后端错误体（键是 `error`，`ApiError.detail` 只会给出 '请求失败'）。
    return { chunks: [], usable: false }
  }
}

/** `file-lines` 返回的单行源码（`line_no` **1-based**，与 citation 的 `line_start` 同口径）。 */
export interface RepoFileLine {
  line_no: number
  text: string
}

/**
 * `file-lines` 的归一结果（判据封装在这里，⛔ 调用点不各自判）。
 *
 * `usable === false` 覆盖**全部**不可用情形：400（参数缺失 / 非正整数 / `line_end < line_start`）、
 * 401/403、404（仓不存在）、5xx、网络失败，以及 ⭐ **最容易漏的那一种** —— 200 但 `lines` 为空。
 * 后端对「文件被排除规则挡掉」/「文件不存在」/「仓库无镜像」三者刻意返回**逐字相同**的 200 空
 * （不泄漏存在性），⇒ 判据必须是 `!ok || lines.length === 0`，**绝不能是「非 2xx」**（与 115-02
 * 为 `chunk-at` 立的判据同源）。
 */
export interface RepoFileLinesResult {
  lines: RepoFileLine[]
  truncated: boolean
  usable: boolean
}

/**
 * 按 `path` + 行区间读源码正文行（Phase 116-07，VIEW-02 的正文与行高亮数据面）。
 *
 * ⚠️ 后端 `path` / `line_start` / `line_end` **均为必填**，缺失稳定 400 ⇒ 调用前先确认
 * citation 的 `locator.line_start` 存在，⛔ 不发注定失败的那次往返。区间超后端硬上限时是
 * **截断**（`truncated: true`）而不是报错。
 *
 * 恒不抛：任何失败都归一成 `{ lines: [], truncated: false, usable: false }`。
 */
export async function getRepositoryFileLines(
  repositoryId: string,
  params: { path: string, lineStart: number, lineEnd: number, branchName?: string },
): Promise<RepoFileLinesResult> {
  const query: Record<string, string> = {
    path: params.path,
    line_start: String(params.lineStart),
    line_end: String(params.lineEnd),
  }
  if (params.branchName)
    query.branch_name = params.branchName
  try {
    const data = await get<{ lines: RepoFileLine[], truncated: boolean }>(
      `/repositories/${repositoryId}/file-lines/`,
      query,
    )
    const lines = Array.isArray(data?.lines) ? data.lines : []
    // ⭐ 判据是「有没有正文」而不是「请求成不成功」：200 + 空 lines 同样不可用。
    return { lines, truncated: Boolean(data?.truncated), usable: lines.length > 0 }
  }
  catch {
    // ⛔ 不回显后端错误体（键是 `error`，`ApiError.detail` 只会给出 '请求失败'）。
    return { lines: [], truncated: false, usable: false }
  }
}

/**
 * 取仓库章程；无章程 / 任何失败一律返回 `null`，调用方走 citation 快照兜底。
 *
 * 恒不抛（与 `getChunkAt` 同款容错：引用预览一律兜底不留白，⛔ 不关弹窗、不回显错误体）。
 */
export async function getRepositoryCharter(repositoryId: string): Promise<RepoCharter | null> {
  try {
    return await get<RepoCharter>(`/repositories/${repositoryId}/charter/`)
  }
  catch {
    return null
  }
}

export default {
  getChunkAt,
  getRepositoryFileLines,
  getRepositoryCharter,
}
