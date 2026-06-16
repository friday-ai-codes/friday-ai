---
phase: 38-routing-recall
plan: 03
subsystem: plan_orchestration
tags: [recall, knowledge-search, events, permissions]
requires: [38-01, 38-02]
provides:
  - DeliveryKnowledgeRecallAdapter(RecallProtocol)
  - engine._recall persist recall_context + knowledge.recalling event
affects: [39, 41]
tech-stack:
  added: []
  patterns: [adapter over DeliveryKnowledgeSearchService, fail-closed actor, _emit_event hook]
key-files:
  created:
    - server/services/plan_orchestration/recall_adapter.py
    - server/tests/services/test_recall_adapter.py
  modified:
    - server/services/plan_orchestration/engine.py
    - server/services/plan_orchestration/__init__.py
    - server/tests/services/test_plan_orchestration_engine.py
decisions:
  - 复用 DeliveryKnowledgeSearchService.search_similar，不重写检索
  - created_by=None 透传（不伪造 actor）→ fail-closed 空召回，不泄漏越权数据
  - 检索异常 best-effort 空召回（try/except + log warning），不阻断编排
  - entity_kinds = [work_item, tech_plan, code_change]（document 本阶段不召回）
metrics:
  duration: ~6m
  completed: 2026-06-16
---

# Phase 38 Plan 03: DeliveryKnowledgeRecallAdapter + engine._recall 接线 Summary

把 recalling 阶段骨架替换为 `DeliveryKnowledgeRecallAdapter`：复用既有 `DeliveryKnowledgeSearchService.search_similar` 召回相似需求/缺陷/复盘/技术方案，经 `transition(recall_context=)` 落 `PlanSession.recall_context` 并按 §14 recalled 转移 recalling→clarifying，同时经 `_emit_event` 产出 §15 `knowledge.recalling` trace 事件。权限 fail-closed：`created_by=None` 透传不伪造 actor。

## Tasks

- **Task 1** (`a28ea26cf`): `DeliveryKnowledgeRecallAdapter` + entity_kinds 映射 + created_by None graceful + 异常 best-effort + routing 候选仓收窄 + 5 测试（search_similar mock）。
- **Task 2** (`f3b71ecf8`): `engine._recall` 捕获返回 → transition(recall_context=) + knowledge.recalling 事件 + engine 测试；源码守护测试仍绿。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] RECALL_ENTITY_KINDS 未在 package __init__ 导出**
- **Found during:** Task 1 测试收集
- **Issue:** 测试从 `services.plan_orchestration` 导入 `RECALL_ENTITY_KINDS` 失败（plan 仅约定 re-export adapter）
- **Fix:** 测试改从 `services.plan_orchestration.recall_adapter` 直接导入常量（不扩大 package 公共面）
- **Files modified:** server/tests/services/test_recall_adapter.py

## Tests

- `tests/services/test_recall_adapter.py` — 5 passed（映射/created_by None fail-closed/异常空召回/routing 收窄/kinds 常量）。
- `tests/services/test_plan_orchestration_engine.py` — 9 passed（含新增 recall 持久化+事件、源码守护）。
- 回归：`tests/delivery/` + plan_orchestration + 两 adapter 共 286 passed。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/recall_adapter.py
- FOUND: commit a28ea26cf, f3b71ecf8
