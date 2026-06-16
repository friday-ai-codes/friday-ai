---
phase: 38-routing-recall
plan: 01
subsystem: delivery
tags: [plan-session, migration, persistence]
requires: []
provides:
  - PlanSession.routing / recall_context / created_by fields
  - PlanSessionService routing/recall_context persistence + created_by
affects: [38-02, 38-03, 39]
tech-stack:
  added: []
  patterns: [_PERSISTABLE_FIELDS whitelist, sync_to_async ORM]
key-files:
  created:
    - server/delivery/migrations/0011_plansession_routing_recall_created_by.py
  modified:
    - server/delivery/models/plan_session.py
    - server/delivery/services/plan_session_service.py
    - server/tests/delivery/test_plan_session_service.py
decisions:
  - created_by 经 settings.AUTH_USER_MODEL FK，related_name="+" 不建反向访问器
  - routing/recall_context 经既有 _PERSISTABLE_FIELDS 循环落库，无需新分支（INV-6 单一入口）
metrics:
  duration: ~4m
  completed: 2026-06-16
---

# Phase 38 Plan 01: PlanSession 字段扩展 + 持久化接线 Summary

为 38-02/38-03 提供持久化底座：PlanSession 新增 `routing`/`recall_context` JSON 字段与 `created_by` nullable FK，并把这两个产物键接入 `PlanSessionService` 单一写入入口（INV-6）；delivery 迁移 0011 与模型一致（`makemigrations --check` 干净）。

## Tasks

- **Task 1** (`b7aedd45c`): PlanSession 三字段 + 迁移 0011（renamed from auto-generated）。`makemigrations --check` 退出码 0。
- **Task 2** (`1859cd038`): `_PERSISTABLE_FIELDS` 追加 routing/recall_context；`create_session(created_by=)` 透传落库；4 个守护测试。

## Deviations from Plan

None - plan executed exactly as written.

## Tests

`tests/delivery/test_plan_session_service.py` — 22 passed（含 4 新增：routed/recalled 持久化 + created_by 持久化/默认 None）。

## Self-Check: PASSED

- FOUND: server/delivery/migrations/0011_plansession_routing_recall_created_by.py
- FOUND: commit b7aedd45c, 1859cd038
