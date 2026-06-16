---
phase: 39-parallel-research
plan: 02
subsystem: delivery
tags: [service, state-machine, inv6, recovery]
requires: [delivery.RepoResearchTask, delivery.PartialPlan]
provides: [delivery.ResearchService]
affects: [39-03, 39-04]
key-files:
  created:
    - server/delivery/services/research_service.py
    - server/tests/delivery/test_research_service.py
    - server/tests/delivery/test_research_inv6_guard.py
  modified:
    - server/delivery/services/__init__.py
decisions:
  - "retry_task 条件更新 filter(id, status=failed).update(attempt=F+1) 保证单仓隔离 + 非 failed raise"
  - "invalidate_for_repo 基于 valid=True→False 计数，二次调用 0 新增（幂等可重入）"
  - "content_hash 本地 sha256(canonical JSON) 不 import knowledge（INV-3）"
metrics:
  duration: ~6m
  completed: 2026-06-16
---

# Phase 39 Plan 02: ResearchService 单一写入入口 Summary

立 `ResearchService` —— RepoResearchTask/PartialPlan 状态与落库的唯一写入入口（INV-6），
承载子任务级状态机（create/mark_running/done/failed/record_partial）+ 可靠恢复
（retry_task 单仓隔离 RESEARCH-02、invalidate_for_repo 重索引 stale RESEARCH-03）。

## Tasks
1. ResearchService 七方法（async + sync_to_async 桥接）+ curated re-export — commit (service)
2. 行为测试（8）+ INV-6 grep 守护（2）— commit 8509f49

## Tests
- `tests/delivery/test_research_service.py` + `test_research_inv6_guard.py`：9 passed
- 覆盖：建任务幂等 / 状态转移表 / record_partial hash+done / retry 单仓隔离 / 非 failed raise / invalidate stale 幂等 / INV-6 无旁路
- ruff line 100：通过

## Deviations from Plan
- None — 按 plan 行为契约实现。

## Self-Check: PASSED
- FOUND: server/delivery/services/research_service.py
- FOUND commit 8509f49 + service commit
