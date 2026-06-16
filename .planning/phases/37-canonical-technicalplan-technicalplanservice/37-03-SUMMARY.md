---
phase: 37-canonical-technicalplan-technicalplanservice
plan: 03
subsystem: delivery / chat lazy+eager migration
tags: [lazy-migration, eager-projection, best-effort, idempotent, conflict-canonical-wins]
requires: [delivery.services.TechnicalPlanService, chat.CodingPlan, mcp_tools.McpWorkItemTechnicalPlan]
provides:
  - delivery.services.chat_codingplan_to_content
  - delivery.services.mcp_plan_to_content
  - chat create_coding_plan eager 投影示范
affects: [Phase 40, Phase 41]
tech-stack:
  added: []
  patterns: [read-time lazy migration, best-effort try/except 隔离, lazy import 防循环, 枚举归一化]
key-files:
  created:
    - server/tests/delivery/test_technical_plan_lazy_migration.py
    - server/tests/delivery/test_chat_eager_projection.py
  modified:
    - server/delivery/services/technical_plan_service.py
    - server/delivery/services/__init__.py
    - server/agents/tools/coding_tools.py
decisions:
  - 取材升级为模块级纯函数 chat_codingplan_to_content / mcp_plan_to_content（eager+lazy 共用）
  - eager 投影接 chat create_coding_plan 真实 chokepoint（coding_tools.py，非计划标注的 chat_tools.py）
  - best-effort try/except：投影失败仅 warning，绝不阻断 CodingPlan 创建
  - resolve 软链命中分支直接读 canonical 保证幂等不重建；冲突以 canonical 最新 current_version 为准
metrics:
  duration: ~20m
  completed: 2026-06-16
---

# Phase 37 Plan 03: 旧路径软链 lazy 迁移 + chat eager 投影 Summary

闭环 PLAN-03 迁移行为：三路径 read-time lazy migration（首次读无 canonical 旧记录 → 建 canonical + 回填软链）+ chat 创建入口 eager 投影示范，冲突以 canonical 为准、归档不级联删旧表。

## What Was Built

- **忠实 lazy 取材**：`chat_codingplan_to_content`（recommended_repository_ids 每仓一 task + affected_files→files + change_type→action 归一化）、`mcp_plan_to_content`（plan_body.execution_plan 优先复用、否则 repository_tasks 映射 + branch_strategy 枚举校正）。产物均过 `validate_technical_plan`。
- **resolve 幂等**：软链命中分支直接 `aget` canonical，绝不重建。
- **chat eager 投影**：`create_coding_plan`（`agents/tools/coding_tools.py`）创建即 best-effort `create_from`+`link` 回填 `canonical_plan_id`，lazy import 防循环、try/except 隔离失败不阻断。
- **测试**：lazy 迁移 6 用例（chat/mcp/workflow + 幂等 + 冲突 + 归档不级联）+ eager 投影 2 用例（回填 + best-effort 守护），共 8；INV-6 守护接线后仍通过。

## Deviations from Plan

**1. [Rule 1 - 文件定位] eager 投影接 coding_tools.py（非计划标注的 chat_tools.py）**
- **Found during:** Task 2
- **Issue:** 计划 `files_modified` 标 `agents/tools/chat_tools.py`，但 chat CodingPlan 实际创建 chokepoint 是 `agents/tools/coding_tools.py` 的 `create_coding_plan`（`aget_or_create_for_conversation`）。
- **Fix:** 在真实 chokepoint `coding_tools.py:create_coding_plan` 接 eager 投影（计划 action 本就要求"先 Read 定位最活跃单一创建 chokepoint"）。
- **Files modified:** server/agents/tools/coding_tools.py

**2. [Rule 1 - 测试隔离] 取材改模块级纯函数 + lazy workflow 测试 external_ref 唯一化**
- **Found during:** Task 1 / Task 3
- **Issue:** ① eager 入口需复用取材逻辑，方法形态不便外部调用；② `link` 经 `sync_to_async` 写 PlanExternalRef 在跨连接下可越测试事务泄漏，固定串 `workflow:exec-1:node-1` 与 models 测试撞 UNIQUE。
- **Fix:** ① 取材改模块级纯函数 `chat_codingplan_to_content`/`mcp_plan_to_content` 并 re-export；② lazy workflow 测试 external_ref 用 uuid 唯一化；幂等测试断言改 delta-based（不依赖全局计数==1）。
- **Files modified:** technical_plan_service.py / __init__.py / test_technical_plan_lazy_migration.py

## Verification

- `pytest test_technical_plan_lazy_migration.py test_chat_eager_projection.py test_technical_plan_inv6_guard.py` → 10 passed。
- 全量回归 `tests/delivery tests/test_coding_tools.py tests/test_coding_plan_model.py tests/mcp_tools` → 379 passed。
- `makemigrations --check --dry-run` → No changes detected；ruff 通过。

## Self-Check: PASSED

- FOUND: server/tests/delivery/test_technical_plan_lazy_migration.py
- FOUND: server/tests/delivery/test_chat_eager_projection.py
- FOUND: server/agents/tools/coding_tools.py (eager projection wired)
