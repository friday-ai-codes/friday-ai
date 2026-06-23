# Phase 68: 实时进度统一 + 进度条修复 - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous)

<domain>
## Phase Boundary

统一并修正索引/图谱/AI 描述的实时进度：索引进度条单调不回退、图谱实时进度独立轨、AI 描述生成状态前端可见。依赖 Phase 67 状态字段。
</domain>

<decisions>
## Implementation Decisions

### PROG-01 索引进度单调
- `_compute_index_progress` 改单调加权阶段进度：解析阶段 `files_processed/files_total` 映射 `[0, _FILE_PHASE_CEIL=20]`（封顶，不显示「100% 索引文件中」）；chunk 阶段 `embed×0.7+write×0.3` 映射 `[20,100]`，chunk 总量一建立即从 20% 续接，消除「文件级 90%→chunk 级 0%」归零跳变。
- 重新触发残留：既有 IndexTriggerView 已 reset 4 chunk 字段 + files_total/processed + current_indexing_file（零回归，criterion 1 满足）。

### PROG-02 阶段文案 / 图谱独立轨 / AI 描述状态
- 向量阶段文案（解析文件中/生成向量中/写入向量库...）+ 百分比：既有 `overall_stage`/`overall_progress`，前端 RepositoryIndexCard 已渲染。
- 图谱独立轨：SSE 帧顶层 `graph` 段（status/stage/percent/current_file/...）已由后端 `_build_graph_payload` 发射、RepositoryGraphCard 渲染（独立于向量轨，不把向量 100% 拉回）；前端 `useIndexProgressStream` 类型补 `graph` 字段使契约完整。
- AI 描述状态：`Repository.ai_summary_status`（not_started/pending=排队中/running=生成中/completed/failed）暴露进 `_compute_index_progress` payload + IndexStatusSerializer + 前端类型；RepositoryIndexCard 渲染「AI 描述：排队中/生成中/已完成/生成失败(+error)」状态行。

### Claude's Discretion
- `_FILE_PHASE_CEIL` 取 20（解析相对 embedding 快、占比小）。
- AI 描述状态行仅在明确状态（pending/running/completed/failed）展示，not_started/空 不展示。
</decisions>

<code_context>
## Existing Code Insights
- `repositories/index_views.py` `_compute_index_progress` / `IndexStatusSerializer` / `IndexProgressStreamView`（SSE 帧含 repository+running_history+graph）/ `_build_graph_payload`。
- `repositories/models.py` `AISummaryStatus` 枚举 + `Repository.ai_summary_status/error`；图谱进度字段（graph_*）。
- 前端 `web/src/composables/useIndexProgressStream.ts`、`RepositoryIndexCard.vue`（向量轨）、`RepositoryGraphCard.vue`（图谱轨）。
</code_context>

<specifics>
## Specific Ideas
- 图谱「提前 INDEXED」是有意设计——不要把向量 100% 拉回（图谱独立轨）。
</specifics>

<deferred>
## Deferred Ideas
- 图谱逐文件串行抽取异步解耦（GRAPHX-01）。
</deferred>
