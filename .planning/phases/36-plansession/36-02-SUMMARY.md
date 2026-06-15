---
phase: 36-plansession
plan: 02
subsystem: delivery
tags: [ORCH-02, PlanSession, state-machine, INV-6, migration]
requires: []
provides:
  - "PlanSession 持久化状态机模型（delivery app）"
  - "PlanSessionService.transition 单一状态入口（_ALLOWED §14）"
  - "delivery migration 0009"
affects:
  - server/delivery/models/__init__.py
  - server/delivery/services/__init__.py
tech-stack:
  added: []
  patterns: ["state machine via _ALLOWED whitelist", "single write entry (INV-6)", "async + sync_to_async ORM"]
key-files:
  created:
    - server/delivery/models/plan_session.py
    - server/delivery/services/plan_session_service.py
    - server/delivery/migrations/0009_plansession.py
    - server/tests/delivery/test_plan_session_models.py
    - server/tests/delivery/test_plan_session_service.py
    - server/tests/delivery/test_plan_session_inv6_guard.py
  modified:
    - server/delivery/models/__init__.py
    - server/delivery/services/__init__.py
decisions:
  - "current_plan_version 用 UUIDField 软引用（不建 FK），避免 36↔37 迁移耦合"
  - "fail 事件不入 _ALLOWED，transition 特判任意状态 → failed"
  - "transition 仅落 payload 中与模型字段同名键（decomposition/current_plan_version/event_time）"
metrics:
  duration: "~30m"
  completed: 2026-06-16
---

# Phase 36 Plan 02: PlanSession 状态机 Summary

立 PlanSession 持久化编排状态机（delivery app，DOMAIN §6/§12.7/§14）：状态全持久化 DB 行、可从任意 status resume，状态变更单一入口 `PlanSessionService.transition` 按 §14 转移表 `_ALLOWED` 白名单驱动，不可恢复错误落结构化 `failed`。

## What Was Built

- **模型** `PlanSession`：UUID pk + `work_item`(nullable SET_NULL FK, INV-2) + `entrypoint`(workflow|chat) + 8-state `status`(默认 decomposing) + `current_plan_version`(UUID 软引用，无 FK) + `decomposition`/`error` JSON + 时间戳 + `event_time`；`db_table=delivery_plan_session`，索引 `status` / `(work_item,status)`。curated re-export 暴露 `PlanSession/PlanSessionStatus/PlanSessionEntrypoint`。
- **迁移** `0009_plansession.py`：makemigrations 生成，依赖 `('delivery','0008_ingestrun')`；`makemigrations --check` 干净。
- **service** `PlanSessionService`：
  - `_ALLOWED` 逐行实现 §14 转移表（decomposed/routed/recalled/clarified/needs_clarification/research_dispatched/research_complete/merged/validation_failed_reclarify/validation_failed_reresearch）。
  - `transition`：唯一 status 入口；非法 event raise（含 from_status + 合法 event 集）status 不变、DB 不写；合法 set status + 落中间 JSON（update_fields 精确）+ `_emit_event` 钩子。
  - `fail` 特判：任意状态 → failed + 结构化 error（非 dict 包成 `{"message":...}`）。
  - `create_session`、`_emit_event`（best-effort no-op + log，Phase 41 真实发射）。ORM 经 `sync_to_async`。
- **守护测试**：模型（默认态/SET_NULL/软引用/JSON）+ service 表驱动遍历 `_ALLOWED` 全合法转移 + 非法 raise + create/resume 持久化 + fail；INV-6 grep 守护（除 service 外无旁路 PlanSession 写）+ 有效性反向断言。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _emit_event 日志 kwarg 与 structlog 保留键冲突**
- **Found during:** Task 2（service 测试 14 例报 `TypeError: got multiple values for argument 'event'`）
- **Issue:** `logger.info("plan_session_event", event=event_name)` —— structlog 用首位置参为 `event`（消息键），再传 `event=` kwarg 冲突。
- **Fix:** kwarg 改 `event_name=event_name`。
- **Commit:** 5ebae4027

**2. [Rule 1 - Bug] 非法转移错误消息显示 enum repr 而非值**
- `{session.status!r}` 对 TextChoices 成员产出 `PlanSessionStatus.DECOMPOSING`；改 `str(session.status)` 输出可读值 `decomposing`（也使消息对人/守护更有用）。

### Event 命名
- §14「validator 失败回退 researching」事件命名采用 `validation_failed_reresearch`（plan 草稿笔误 `rereresearch`，Claude's Discretion 取规整名）。

## Verification Evidence

- `pytest tests/delivery/test_plan_session_*.py` → **20 passed**；`pytest tests/delivery/` 全量 → **229 passed**（无回归）。
- `makemigrations delivery --check --dry-run` → **No changes detected**（模型与迁移一致；迁移随测试 DB 成功 apply）。
- `ruff format --check delivery/models/plan_session.py delivery/services/plan_session_service.py` → 通过。
- `python -c "from delivery.models import PlanSession,...; from delivery.services import PlanSessionService"` → **IMPORT OK**（curated re-export 生效）。

## Success Criteria

- ✅ 成功标准 3（ORCH-02）：PlanSession 状态机可持久化、可从中断恢复，按 §14 转移表推进，不可恢复错误落结构化 failed。

## Self-Check: PASSED
- FOUND: server/delivery/models/plan_session.py, plan_session_service.py, 0009_plansession.py
- FOUND commits a5fdf41bf, 5ebae4027, 85dd0ded7
