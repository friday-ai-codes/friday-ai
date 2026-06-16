---
phase: 38-routing-recall
plan: 02
subsystem: plan_orchestration
tags: [routing, repo-router, events]
requires: [38-01]
provides:
  - RepoRouterV2Adapter(RouterProtocol)
  - engine._route persist routing + repo.routing event
affects: [38-03, 39, 41]
tech-stack:
  added: []
  patterns: [adapter over RepoRouterV2, _emit_event hook, sync_to_async ORM]
key-files:
  created:
    - server/services/plan_orchestration/repo_router_adapter.py
    - server/tests/services/test_repo_router_adapter.py
  modified:
    - server/services/plan_orchestration/engine.py
    - server/services/plan_orchestration/__init__.py
    - server/tests/services/test_plan_orchestration_engine.py
decisions:
  - 复用 RepoRouterV2.route，不重写路由（LLM/Stage0/v1 降级链自带）
  - 候选范围 include_repos → work_item.project repos → 全库 优先级
  - repo.routing payload 仅 {repo_id, confidence}（INV-5 trace 非 CoT）
metrics:
  duration: ~6m
  completed: 2026-06-16
---

# Phase 38 Plan 02: RepoRouterV2Adapter + engine._route 接线 Summary

把 routing 阶段骨架替换为 `RepoRouterV2Adapter`：复用既有 `RepoRouterV2` 路由出候选仓 + confidence，经 `transition(routing=)` 落 `PlanSession.routing` 并按 §14 routed 转移 routing→recalling，同时经 `_emit_event` 产出 §15 `repo.routing` trace 事件。

## Tasks

- **Task 1** (`059bfd999`): `RepoRouterV2Adapter` + 候选范围三档解析 + 5 测试（RepoRouterV2 mock）。
- **Task 2** (`50a7c3a3f`): `engine._route` 捕获返回 → transition(routing=) + repo.routing 事件 + engine 测试；源码守护 `test_engine_does_not_write_status_directly` 仍绿。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] engine.py 既有 import 排序告警**
- **Found during:** Task 2 lint
- **Issue:** `ruff check` 报 engine.py import block 未排序（I001，预存）
- **Fix:** `ruff check --fix`（仅 import 分组空行合并，无功能变更）
- **Files modified:** server/services/plan_orchestration/engine.py
- **Commit:** 50a7c3a3f

**2. [Rule 1 - Bug] 测试 WorkItemOrigin 枚举值修正**
- **Found during:** Task 1 测试运行
- **Issue:** 测试误用 `WorkItemOrigin.FEISHU`（实际枚举为 FEISHU_WEBHOOK/MANUAL/...）
- **Fix:** 改用 `WorkItemOrigin.MANUAL`
- **Files modified:** server/tests/services/test_repo_router_adapter.py

## Tests

- `tests/services/test_repo_router_adapter.py` — 5 passed。
- `tests/services/test_plan_orchestration_engine.py` — 8 passed（含新增 routing 持久化+事件、源码守护）。

## Self-Check: PASSED

- FOUND: server/services/plan_orchestration/repo_router_adapter.py
- FOUND: commit 059bfd999, 50a7c3a3f
