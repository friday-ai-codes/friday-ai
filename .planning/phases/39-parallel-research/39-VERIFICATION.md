---
phase: 39-parallel-research
status: passed
verified: 2026-06-16
verifier: gsd-executor (goal-backward)
real_container_e2e: deferred
---

# Phase 39 Verification — 并行调研子 agent

> 方法：goal-backward——从 phase 目标（编排 map 段：filter_then_container 并行调研 +
> 结构化 PartialPlan + 子任务级可靠恢复 + §15 事件）反推每条成功标准是否由实现 + 测试坐实。
> **真实容器 E2E 沿用既有里程碑惯例 DEFERRED**：dispatch/解析/聚合/事件逻辑以 mock
> dispatcher/runner/callback payload 覆盖（对齐 `test_callbacks_cross_repo_relevance` 范式）。

## Success Criteria

### SC-1 — filter_then_container fan-out + 结构化 PartialPlan（RESEARCH-01）✅
- **filter**：`ResearchDispatchAdapter.dispatch` 取 `session.routing.candidates`，
  confidence ∈ {high, medium} → deep（起容器）；low/缺失 → 轻量 server 端 PartialPlan。
- **container fan-out**：每仓经 `ResearchService.create_tasks_for_session` 建
  RepoResearchTask + dispatch 独立 `SubAgentSession(TaskType.PLAN)` 容器（复用
  `DispatchTask`/`get_dispatcher`，上下文隔离）+ 回填 running + emit `repo.research.started`。
- **结构化产物**：容器回调经 `parse_partial_plan_content` 解析为 §7 PartialPlan
  （research_summary/proposed_changes/candidate_files/api_contracts_exposed/
  dependencies_on_other_repos），经 `ResearchService.record_partial` 落库（content_hash）。
- **证据**：`test_research_adapter.py`（filter 分流 / 容器回填 running / prompt 注入 §7 /
  no-candidates / runner offline 降级，7 passed）；`test_research_completion_callback.py`
  （结构化/降级 partial 落库，6 passed）；`test_research_aggregation.py`（解析三路，10 passed）。
- **结论**：PASSED（mock 覆盖；真实容器 dispatch 派发延后）。

### SC-2 — 单仓重试不重跑整 session（RESEARCH-02）✅
- `ResearchService.retry_task` 条件更新 `filter(id, status=failed).update(status=pending,
  attempt=F+1)`，影响行数!=1 → ValueError；**绝不触碰其他 task / 不改 session.status**。
- **证据**：`test_research_service.py::test_retry_task_isolation`（A failed→pending+attempt1，
  B/C/session 不变）、`test_retry_non_failed_raises`。
- **结论**：PASSED。

### SC-3 — 重索引 → PartialPlan stale + 融合前重跑（RESEARCH-03）✅
- `ResearchService.invalidate_for_repo` 把 repository 关联 valid PartialPlan→invalid
  （reason=repo_reindexed）+ RepoResearchTask→stale，幂等可重入。
- 挂接 `services.indexer._run_research_stale_invalidation`（base-only FINALIZING 段，
  紧随 modifies_chunk 对账）；best-effort try/except，**失败绝不阻断索引 success**。
- barrier 终态集 {done, failed} **不含 stale** → stale task 阻塞 research_complete，
  融合前须重跑（`amaybe_complete_research` 在有 stale 时返回 False）。
- **证据**：`test_research_service.py::test_invalidate_for_repo_stale`（失效+stale+幂等）、
  `test_research_stale_hook.py`（hook 置 stale / service 异常仅 warning / base-only 接线源码守护）、
  `test_research_aggregation.py::test_terminal_pending_running_stale_false`。
- **结论**：PASSED。

### SC-4 — repo.research.* §15 事件 ✅
- `repo.research.started`（adapter，payload {repo_id, task_id, focus}）；
  `repo.research.completed`（callback，payload {repo_id, task_id, summary, candidate_files,
  api_contracts_exposed}）；`repo.research.failed`（callback 完成空结果 / 容器失败回调，
  payload {repo_id, task_id, error}）——均经 `PlanSessionService._emit_event` 钩子。
- **证据**：`test_research_adapter.py::test_emits_research_started`、
  `test_research_completion_callback.py`（completed/failed 事件 + payload 字段）。
- **结论**：PASSED（事件经 _emit_event 钩子产出；真实 sink 收口 Phase 41）。

## Locked Decisions Honored
- ✅ 复用 `SubAgentSession(TaskType.PLAN)` + `DispatchTask`/`get_dispatcher`（mirror deep_analysis）—— 未重造容器底座。
- ✅ filter_then_container：high/medium→容器，low→轻量 server 端 PartialPlan。
- ✅ research 模型写入只经 `ResearchService`（INV-6 grep 守护 `test_research_inv6_guard` 通过）。
- ✅ engine 不直接 mutate status（`test_engine_does_not_write_status_directly` 保持绿；经 transition）。
- ✅ 单仓 retry 隔离（RESEARCH-02）；reindex stale 经 indexer FINALIZING best-effort（失败不阻断索引）。
- ✅ §15 事件 repo.research.started/completed/failed。

## Migration
- delivery `0013_reporesearchtask_partialplan`（依赖 0012）已生成并应用；
  `makemigrations --check --dry-run` → **No changes detected**（零漂移）。

## Test Summary
- 新增测试：models(5) + service+inv6(9) + adapter(7) + aggregation(10) + callback(6) + stale hook(3) = **40 passed**。
- 回归套件（tests/delivery + plan_orchestration engine + research adapter/aggregation/callback/stale + cross_repo_relevance）：**325 passed**。
- ruff line 100 全通过。

## Deferred / Notes
- **真实容器 E2E DEFERRED**（本地无 runner+docker；逻辑以 mock 全覆盖）—— 逻辑已验证，
  按惯例以 deferred note 通过。
- 3 个 coding_session E2E 测试因本地缺 Anthropic 凭证失败，经 base 提交 abcaece7 复跑确认
  为**既有/环境性失败，非本 phase 回归**（详见 deferred-items.md）。

## Verdict: PASSED (real-container E2E deferred)
