---
phase: 37-canonical-technicalplan-technicalplanservice
plan: 01
subsystem: delivery / canonical plan spine
tags: [models, migrations, schema-first, INV-2, INV-6]
requires: [delivery.WorkItem, chat.CodingPlan, mcp_tools.McpWorkItemTechnicalPlan]
provides:
  - delivery.TechnicalPlan
  - delivery.PlanVersion
  - delivery.PlanExternalRef
  - chat.CodingPlan.canonical_plan_id
  - mcp_tools.McpWorkItemTechnicalPlan.canonical_plan_id
affects: [37-02, 37-03, Phase 40, Phase 41]
tech-stack:
  added: []
  patterns: [curated re-export, UUID pk, circular FK via string ref, soft UUID link]
key-files:
  created:
    - server/delivery/models/technical_plan.py
    - server/delivery/migrations/0010_technicalplan_planversion_planexternalref.py
    - server/chat/migrations/0022_codingplan_canonical_plan_id.py
    - server/mcp_tools/migrations/0008_mcpworkitemtechnicalplan_canonical_plan_id.py
    - server/tests/delivery/test_technical_plan_models.py
  modified:
    - server/delivery/models/__init__.py
    - server/chat/models.py
    - server/mcp_tools/models.py
decisions:
  - canonical 模型落 delivery app + curated re-export（与 WorkItem/PlanSession 同 app）
  - work_item nullable SET_NULL（INV-2）；current_version 循环 FK 经字符串前向引用单 migration
  - chat/mcp 用 canonical_plan_id UUIDField 软链（无跨 app 硬 FK）；workflow 用 PlanExternalRef
  - 模型层零业务写方法（写入归 37-02 service，INV-6）
metrics:
  duration: ~15m
  completed: 2026-06-16
---

# Phase 37 Plan 01: canonical TechnicalPlan schema 底座 Summary

立方案唯一事实源的全部 schema：delivery 三模型（TechnicalPlan/PlanVersion/PlanExternalRef）+ 旧表 chat/mcp 的 canonical_plan_id 软链字段，schema-first 让 Wave 2 service 可针对真实列/表实现。

## What Was Built

- **`delivery/models/technical_plan.py`**：`TechnicalPlan`（UUID pk、work_item nullable SET_NULL、origin/status 枚举、current_version 字符串前向引用循环 FK）、`PlanVersion`（version + supersedes self FK + content JSONField + content_hash + `unique_together(plan, version)`）、`PlanExternalRef`（external_ref unique + canonical FK CASCADE）。无任何业务写方法（INV-6）。
- **软链字段**：`chat.CodingPlan` / `mcp_tools.McpWorkItemTechnicalPlan` 各加 `canonical_plan_id UUIDField(null, db_index)`（非硬 FK）。
- **migrations**：delivery 0010（单 migration 建 3 表，循环 FK 经 AddField 编排）+ chat 0022 + mcp_tools 0008。`makemigrations --check` 干净，全部可 migrate。
- **守护测试**：6 用例全绿（INV-2 / SET_NULL / 版本链 unique_together / PlanExternalRef unique+CASCADE / 软链字段 UUIDField 非 relation）。

## Deviations from Plan

**1. [Rule 3 - Blocking] 模型导入校验改用 `manage.py shell -c`**
- **Found during:** Task 1 verify
- **Issue:** 计划 verify 用裸 `python -c`，但 Django 需 settings 配置（ImproperlyConfigured）。
- **Fix:** 改用 `uv run python manage.py shell -c "..."` 跑导入校验，结果 ok。
- **Files modified:** 无（仅命令调整）。

**2. [Rule 3 - Naming] delivery migration 重命名为 canonical 名**
- **Found during:** Task 2
- **Issue:** Django 自动生成名为 `0010_planversion_technicalplan_planversion_plan_and_more.py`。
- **Fix:** 重命名为计划约定的 `0010_technicalplan_planversion_planexternalref.py`（无 migration 依赖它，安全；未改内容）。

## Verification

- `makemigrations --check --dry-run` → No changes detected。
- `pytest tests/delivery/test_technical_plan_models.py` → 6 passed。
- `ruff format --check` + `ruff check` → 通过。

## Self-Check: PASSED

- FOUND: server/delivery/models/technical_plan.py
- FOUND: server/delivery/migrations/0010_technicalplan_planversion_planexternalref.py
- FOUND: server/chat/migrations/0022_codingplan_canonical_plan_id.py
- FOUND: server/mcp_tools/migrations/0008_mcpworkitemtechnicalplan_canonical_plan_id.py
- FOUND: server/tests/delivery/test_technical_plan_models.py
