---
phase: 39-parallel-research
plan: 01
subsystem: delivery
tags: [models, migration, orchestration]
requires: [delivery.PlanSession, repositories.Repository, subagent.SubAgentSession]
provides: [delivery.RepoResearchTask, delivery.PartialPlan, delivery.RepoResearchTaskStatus, migration 0013]
affects: [39-02, 39-03, 39-04]
key-files:
  created:
    - server/delivery/models/research_task.py
    - server/delivery/migrations/0013_reporesearchtask_partialplan.py
    - server/tests/delivery/test_research_models.py
  modified:
    - server/delivery/models/__init__.py
decisions:
  - "RepoResearchTask 子任务级状态机 5 态（pending/running/done/failed/stale）逐字对齐 DOMAIN §6/§14"
  - "模型层不写业务方法，写入收口 39-02 ResearchService（INV-6 精神）"
metrics:
  duration: ~5m
  completed: 2026-06-16
---

# Phase 39 Plan 01: 并行调研数据底座 Summary

立 Phase 39 map 段数据底座：`RepoResearchTask`（每仓并行调研子任务，子任务级状态机
pending→running→done/failed/stale + attempt 重试计数 + routed_confidence + error JSON）
与 `PartialPlan`（单仓 §7 结构化产物 + valid/stale 失效位 + content_hash），落 `delivery`
app，配 migration 0013（依赖 0012）+ curated re-export + 模型守护测试。

## Tasks
1. `research_task.py` 模型文件（RepoResearchTask + RepoResearchTaskStatus + PartialPlan）— commit 64231e7
2. curated re-export + migration 0013 + 5 个模型守护测试 — commit a58c992

## Tests
- `tests/delivery/test_research_models.py`：5 passed（默认态 / CASCADE / SET_NULL / makemigrations 零漂移）
- `makemigrations delivery --check --dry-run`：No changes detected（零漂移）
- ruff line 100：通过

## Deviations from Plan
- migration 由 makemigrations 自动生成为 `0013_reporesearchtask_partialplan_and_more.py`，按 plan 重命名为 `0013_reporesearchtask_partialplan.py`（内部依赖仍指向 0012，无 import 引用故安全）。

## Self-Check: PASSED
- FOUND: server/delivery/models/research_task.py
- FOUND: server/delivery/migrations/0013_reporesearchtask_partialplan.py
- FOUND commits 64231e7 / a58c992
