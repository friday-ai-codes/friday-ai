---
phase: 40-mergedplan-planvalidator
plan: 01
subsystem: delivery / plan_orchestration
tags: [model, migration, schema, validator, pure-function]
requires:
  - delivery.PlanSession (Phase 36)
  - delivery.PlanVersion / TechnicalPlanService (Phase 37)
  - workflows.schemas.technical_plan.validate_technical_plan (PF-02)
provides:
  - delivery.models.ArchitectMerge (DOMAIN §6)
  - services.plan_orchestration.validate_merged_plan (§7 schema)
  - services.plan_orchestration.validate_plan (PlanValidator 5 checks)
affects:
  - 40-02 ArchitectMergeAdapter (consumes model + validators)
tech-stack:
  added: []
  patterns:
    - 软引用 UUIDField (merged_plan_version → PlanVersion.id, 不建硬 FK)
    - fail-closed default (validation_status=failed)
    - 纯函数 fail-safe 校验 (逐字段 isinstance + .get, 恒不抛)
    - execution_plan 子结构复用 validate_technical_plan (不重复造轮子)
key-files:
  created:
    - server/delivery/models/architect_merge.py
    - server/delivery/migrations/0014_architectmerge.py
    - server/services/plan_orchestration/merged_plan.py
    - server/services/plan_orchestration/plan_validator.py
    - server/tests/delivery/test_architect_merge_models.py
    - server/tests/services/test_merged_plan_schema.py
    - server/tests/services/test_plan_validator.py
  modified:
    - server/delivery/models/__init__.py
    - server/services/plan_orchestration/__init__.py
decisions:
  - MergedPlan schema 落新文件 merged_plan.py, execution_plan 子校验复用 technical_plan
  - PlanValidator 依赖图用 DFS 三色检测 (显式栈, 自环显式判环)
  - dependency_dag 约定为 {repo_id: [dep_repo_id]} 邻接表
metrics:
  duration: ~12min
  completed: 2026-06-16
---

# Phase 40 Plan 01: 架构师融合数据底座 + MergedPlan + PlanValidator Summary

立 Phase 40 reduce 段的数据底座 + 校验纯逻辑：`ArchitectMerge` 模型（DOMAIN §6）记录每次架构师融合的验证结果，`validate_merged_plan`（§7 content schema，execution_plan 子结构复用 `validate_technical_plan`），以及 `validate_plan`——PlanValidator 5 项跨仓语义校验让架构师「不只是更贵的总结器」。

## What Was Built

- **ArchitectMerge 模型 + migration 0014**：`session` CASCADE、`merged_plan_version` 软引用可空（不建硬 FK 避免 delivery 内循环）、`validation_status` 默认 `failed`（fail-closed）、`validation_report`/`attempt` 默认。curated re-export `ArchitectMerge`/`ArchitectMergeStatus`。模型层不写任何业务方法（INV-6：写入归 40-02）。
- **`validate_merged_plan`（merged_plan.py）**：顶层 dict 防御 + execution_plan 子结构复用 `validate_technical_plan`（PF-02），保证「过本校验者必过 `create_from` 内校验」。
- **`validate_plan`（plan_validator.py）**：纯函数，5 项校验各自独立函数：契约一致性 / 依赖 DAG 无环（DFS 三色 + 自环显式判环 + 边去重）/ 迁移顺序 / 发布顺序 / 回滚完整。半可信输入恒不抛异常（每个 check 包 try/except fail-safe）。返回 `{valid, errors, warnings}`。

## Tasks Completed

| Task | Name | Commit |
|------|------|--------|
| 1 | ArchitectMerge 模型 + migration 0014 + re-export + 模型守护测试 | feat(40-01) ArchitectMerge model |
| 2 | MergedPlan §7 schema validate_merged_plan（TDD） | feat(40-01) MergedPlan schema |
| 3 | PlanValidator 5 项跨仓校验纯函数（TDD） | feat(40-01) PlanValidator |

## Verification

- `makemigrations delivery --check --dry-run`：零漂移 ✓
- `pytest tests/delivery/test_architect_merge_models.py`：4 passed
- `pytest tests/services/test_merged_plan_schema.py`：5 passed
- `pytest tests/services/test_plan_validator.py`：9 passed
- `ruff check`（3 个新文件）：All checks passed

## Deviations from Plan

None - plan executed exactly as written. `TechnicalPlanOrigin.ORCHESTRATION` 已存在（无需本 plan 处理）。

## Self-Check: PASSED

- 文件均存在（architect_merge.py / 0014 / merged_plan.py / plan_validator.py + 3 测试）
- 3 个 commit 均落库
- `from delivery.models import ArchitectMerge` 与 `from services.plan_orchestration import validate_merged_plan, validate_plan` 可导入（测试已验证）
