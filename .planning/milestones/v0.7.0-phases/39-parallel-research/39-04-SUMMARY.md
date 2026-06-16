---
phase: 39-parallel-research
plan: 04
subsystem: plan_orchestration
tags: [barrier, callback, indexer-hook, engine, events]
requires: [delivery.ResearchService, orchestration.barrier, subagent.callbacks, services.indexer, PlanSessionService]
provides: [research_aggregation, _handle_research_completion, _run_research_stale_invalidation]
affects: [40-merge]
key-files:
  created:
    - server/services/plan_orchestration/research_aggregation.py
    - server/tests/services/test_research_aggregation.py
    - server/tests/services/test_research_completion_callback.py
    - server/tests/services/test_research_stale_hook.py
  modified:
    - server/services/plan_orchestration/engine.py
    - server/services/plan_orchestration/__init__.py
    - server/subagent/api/callbacks.py
    - server/services/indexer.py
decisions:
  - "barrier 终态集 {done, failed}；stale/pending/running 非终态（stale 须重跑）"
  - "engine._research dispatch 后 amaybe_complete_research，未完成则 research_dispatched 自留；engine 不写 status（纯度守护绿）"
  - "回调结果解析 parse_partial_plan_content：结构化 / 文本 JSON / 降级 / None 四路健壮"
  - "callback + indexer hook 均 try/except swallow（回调返 200 / 索引不阻断）"
metrics:
  duration: ~12m
  completed: 2026-06-16
---

# Phase 39 Plan 04: map 段闭环 Summary

合上 map 段闭环：barrier 聚合（所有 RepoResearchTask 终态 → 经 service 推
research_complete → merging，§14）+ 容器回调结果解析（SubAgentSession/TaskResult →
结构化 §7 PartialPlan，非结构化优雅降级）+ §15 调研事件（completed/failed）+ 重索引
stale 失效钩子（indexer FINALIZING best-effort）+ engine `_research` 接线（dispatch
触发 fan-out，barrier/回调驱动转移，engine 不直接写 status）。

## Tasks
1. research_aggregation 模块 + engine._research 改写 + re-export — commit 7514c03
2. callbacks plan_research 完成/失败路由 + §15 事件 + barrier — commit (C2)
3. indexer FINALIZING stale 失效钩子 — commit 32646020

## Tests
- aggregation(10) + callback(6) + stale hook(3) + engine(9) = 28 passed
- 回归套件（tests/delivery + plan_orchestration engine + research adapter/aggregation/callback/stale + cross_repo_relevance）：325 passed
- `makemigrations --check --dry-run`：No changes detected（本 plan 不改模型）
- engine 纯度守护 `test_engine_does_not_write_status_directly`：保持绿
- ruff line 100：通过

## Deviations from Plan
- None — 按 plan 闭环契约实现。

## Pre-existing Failures (out-of-scope, NOT regression)
3 个 coding_session E2E 测试因本地缺 Anthropic 凭证（`coding_graph._call_llm_for_pr_draft`）
失败；在 Phase 39 之前 base 提交 abcaece7 复跑同样失败 → 确认环境性/既有，非本 phase 引入。
详见 deferred-items.md。

## Self-Check: PASSED
- FOUND: server/services/plan_orchestration/research_aggregation.py
- FOUND: server/services/indexer.py:_run_research_stale_invalidation
- FOUND commits 7514c03 / C2 / 32646020
