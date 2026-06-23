---
phase: 68-progress
plan: 01
subsystem: index-progress
tags: [progress, monotonic, ai-summary, graph-track, sse]
requires:
  - phase: "67-concurrency"
    provides: "并发与仓库状态字段基线"
provides:
  - "单调加权阶段进度（消除文件级→chunk 级归零跳变）"
  - "AI 描述生成状态暴露 + 前端渲染（PROG-02）"
  - "图谱独立轨 SSE graph 段前端类型补全"
affects: [仓库索引进度 UI, 图谱进度轨, AI 描述状态]
tech-stack:
  added: []
  patterns:
    - "单调加权阶段进度：解析[0,_FILE_PHASE_CEIL] + chunk[_FILE_PHASE_CEIL,100]，边界续接不回退"
key-files:
  created:
    - server/tests/repositories/test_index_progress_ai_summary.py
  modified:
    - server/repositories/index_views.py
    - server/tests/repositories/test_index_progress_reset.py
    - server/tests/test_e2e_index_flow.py
    - web/src/composables/useIndexProgressStream.ts
    - web/src/api/repositories.ts
    - web/src/components/repository/RepositoryIndexCard.vue
status: complete
---

# Phase 68 Plan 01 Summary — 实时进度统一 + 进度条修复

- **PROG-01 单调进度**：`_compute_index_progress` 重写为单调加权阶段进度——解析阶段 `files_processed/files_total` 映射 `[0, _FILE_PHASE_CEIL=20]`（封顶，消除「100% 索引文件中」误导）；chunk 阶段 `embed×0.7+write×0.3` 映射 `[20,100]`，chunk 总量一建立即从 20% 续接（≥ 解析上限），消除「文件级 90%→chunk 级 0%」归零跳变；全程单调。重触发残留由既有 `IndexTriggerView` reset（4 chunk 字段 + files + current_file）处理，零回归。更新既有断言（reset 50→60、e2e 64→71，complete=100/zero=0 不变）。
- **PROG-02 AI 描述状态**：`Repository.ai_summary_status`（not_started/pending=排队中/running=生成中/completed/failed）+ `ai_summary_error` 暴露进 `_compute_index_progress` payload + `IndexStatusSerializer`（随 SSE `repo_payload` `**progress` 自动流出）+ 前端 `IndexStatusResponse`/`IndexStreamRepositoryPayload` 类型 + `RepositoryIndexCard` 渲染「AI 描述：排队中/生成中/已完成/生成失败(+error)」状态行（`data-testid=ai-summary-status`，仅明确状态展示）。
- **图谱独立轨**：后端 SSE 帧顶层 `graph` 段（`_build_graph_payload`，status/stage/percent/current_file/...）+ `RepositoryGraphCard` 渲染已存在（独立向量轨，不把向量 100% 拉回）；本 plan 补 `useIndexProgressStream` 的 `IndexStreamGraphPayload` 类型 + `IndexStreamEvent.graph` 字段使前端契约完整。
- **附带**：`test_go_extractor` endpoint 断言（Phase 66 改动）随仓库一起，无新增。

验收：`test_index_progress_ai_summary.py`（ai_summary 暴露 + 单调边界 + chunk 阶段单调爬升）+ `test_index_progress_reset`/`test_e2e_index_flow`/`test_index_progress_stream(_graph)` 全绿（13 passed/7 skipped）；前端 repository 组件 83 测零回归；eslint clean。
